"""
routers/batches.py — Batch endpoints
======================================
POST   /batches                         Create a new batch (search by recipe name)
POST   /batches/from-recipe/{recipe_id} Create a batch directly from a recipe ID
PATCH  /batches/{batch_id}              Modify a batch ingredient (add/remove/update)
POST   /batches/{batch_id}/ingredients/confirm  Confirm a low-confidence ingredient
POST   /batches/{batch_id}/notes        Add a note to a batch
POST   /batches/{batch_id}/image        Upload a batch photo
GET    /batches/{batch_id}              Get a batch with its current component list
"""

from __future__ import annotations

import app as App
import db
import nutrition_lookup as NL
from dependencies import (
    Auth, DbConn, get_usda_api_key, save_image,
)
from models import (
    BatchModifyRequest, BatchModifyResponse, BatchResponse,
    ComponentSummary, IngredientConfirmRequest, IngredientResult,
    MessageResponse, NoteResponse, NutritionCandidate,
    RecipeSummary,
)

from fastapi import APIRouter, File, HTTPException, UploadFile, status

router = APIRouter(prefix="/batches", tags=["Batches"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_batch_response(result: dict) -> BatchResponse:
    candidates = None
    if result.get("candidates"):
        candidates = [
            RecipeSummary(
                recipe_id    = r["recipe_id"],
                recipe_name  = r["recipe_name"],
                num_servings = r.get("num_servings"),
                vegan        = bool(r.get("vegan", 0)),
                vegetarian   = bool(r.get("vegetarian", 0)),
            )
            for r in result["candidates"]
        ]
    components = None
    if result.get("components"):
        components = [ComponentSummary(**c) for c in result["components"]]

    return BatchResponse(
        status      = result["status"],
        batch_id    = result["batch_id"],
        recipe_id   = result["recipe_id"],
        recipe_name = result["recipe_name"],
        batch_date  = result["batch_date"],
        components  = components,
        candidates  = candidates,
    )


def _ext(filename: str | None) -> str:
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ".jpg"


# ---------------------------------------------------------------------------
# Create batch (search by recipe name)
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new batch by searching for a recipe",
)
def create_batch(
    recipe_query: str,
    conn:         DbConn,
    _:            Auth,
    batch_date:   str | None = None,
):
    """
    Searches for a recipe by name and creates a new batch.

    - `status: "created"` — batch created, `components` shows the ingredient list.
    - `status: "ambiguous"` — multiple recipes matched; pick one from `candidates`
      and call `POST /batches/from-recipe/{recipe_id}` instead.
    - `status: "not_found"` — no matching recipe.
    """
    result = App.create_batch(conn, recipe_query, batch_date=batch_date)
    return _build_batch_response(result)


# ---------------------------------------------------------------------------
# Create batch directly from recipe_id
# ---------------------------------------------------------------------------

@router.post(
    "/from-recipe/{recipe_id}",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a batch directly from a recipe ID",
)
def create_batch_from_recipe(
    recipe_id:  int,
    conn:       DbConn,
    _:          Auth,
    batch_date: str | None = None,
):
    try:
        result = App.create_batch_from_recipe_id(
            conn, recipe_id, batch_date=batch_date
        )
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    return _build_batch_response(result)


# ---------------------------------------------------------------------------
# Get a batch
# ---------------------------------------------------------------------------

@router.get(
    "/{batch_id}",
    response_model=BatchResponse,
    summary="Get a batch and its current component list",
)
def get_batch(batch_id: int, conn: DbConn, _: Auth):
    try:
        batch = db.get_batch(conn, batch_id)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))

    if batch["recipe_changes"]:
        raw_comps = db.get_components(conn, batch_id=batch_id)
    else:
        raw_comps = db.get_components(conn, recipe_id=batch["recipe_id"])

    components = [
        ComponentSummary(
            component_id     = c["component_id"],
            ingredient_id    = c["ingredient_id"],
            ingredient_name  = c["ingredient_name"],
            quantity_multiple = c["quantity_multiple"],
            portion_amount   = c["portion_amount"],
            portion_unit     = c["portion_unit"],
            portion_grams    = c["portion_grams"],
        )
        for c in raw_comps
    ]
    return BatchResponse(
        status      = "ok",
        batch_id    = batch["batch_id"],
        recipe_id   = batch["recipe_id"],
        recipe_name = batch["recipe_name"],
        batch_date  = batch["date"],
        components  = components,
        candidates  = None,
    )


# ---------------------------------------------------------------------------
# Modify a batch ingredient
# ---------------------------------------------------------------------------

@router.patch(
    "/{batch_id}",
    response_model=BatchModifyResponse,
    summary="Add, remove, or update an ingredient in a batch",
)
def modify_batch(
    batch_id: int,
    req:      BatchModifyRequest,
    conn:     DbConn,
    _:        Auth,
):
    """
    Applies a single modification to a batch.

    Actions:
    - `add`: supply `ingredient_name` and `quantity_multiple`.
      May return `status: "needs_confirmation"` with `candidates`.
    - `remove`: supply `component_id`.
    - `update_quantity`: supply `component_id` and `quantity_multiple`.

    On the first modification, recipe components are automatically copied
    to the batch level so subsequent changes don't affect the base recipe.
    """
    try:
        result = App.modify_batch_ingredient(
            conn,
            batch_id,
            req.action,
            component_id     = req.component_id,
            ingredient_name  = req.ingredient_name,
            quantity_multiple = req.quantity_multiple,
            usda_api_key     = get_usda_api_key(),
        )
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    candidates = None
    if result.get("candidates"):
        candidates = [NutritionCandidate(**c) for c in result["candidates"]]

    components = None
    if result.get("components"):
        components = [ComponentSummary(**c) for c in result["components"]]

    return BatchModifyResponse(
        status       = result["status"],
        action       = result["action"],
        batch_id     = batch_id,
        component_id = result.get("component_id"),
        candidates   = candidates,
        pending_key  = result.get("pending_key"),
        components   = components,
    )


# ---------------------------------------------------------------------------
# Confirm ingredient (after needs_confirmation on add)
# ---------------------------------------------------------------------------

@router.post(
    "/{batch_id}/ingredients/confirm",
    response_model=BatchModifyResponse,
    summary="Confirm a pending ingredient addition to a batch",
)
def confirm_batch_ingredient(
    batch_id: int,
    req:      IngredientConfirmRequest,
    conn:     DbConn,
    _:        Auth,
):
    """
    Called after `PATCH /batches/{batch_id}` returns `needs_confirmation`.
    Supply `pending_key` (from the PATCH response), and either:
    - `choice`: 1-based index into the `candidates` list, or
    - `manual_data`: dict with full ingredient fields.
    """
    # Re-fetch candidates from lookup to resolve the choice
    pending_session = _get_pending_batch_ingredient(batch_id, req.pending_key)
    if pending_session is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No pending ingredient '{req.pending_key}' for batch {batch_id}.",
        )
    candidates_raw, qty_multiple = pending_session

    try:
        result = App.confirm_batch_ingredient(
            conn,
            batch_id,
            req.pending_key,
            qty_multiple,
            candidates_raw,
            choice      = req.choice,
            manual_data = req.manual_data,
        )
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    _clear_pending_batch_ingredient(batch_id, req.pending_key)

    components = [ComponentSummary(**c) for c in result.get("components", [])]
    return BatchModifyResponse(
        status       = result["status"],
        action       = "add",
        batch_id     = batch_id,
        component_id = None,
        candidates   = None,
        pending_key  = None,
        components   = components,
    )


# ---------------------------------------------------------------------------
# Pending ingredient store for batches
# (parallel to session store but keyed by batch_id + ingredient_name)
# ---------------------------------------------------------------------------
_pending_batch: dict[str, tuple] = {}


def _pending_key(batch_id: int, ingredient_name: str) -> str:
    return f"{batch_id}::{ingredient_name.lower().strip()}"


def store_pending_batch_ingredient(
    batch_id: int, ingredient_name: str,
    candidates: list, qty_multiple: float,
) -> None:
    _pending_batch[_pending_key(batch_id, ingredient_name)] = (candidates, qty_multiple)


def _get_pending_batch_ingredient(
    batch_id: int, ingredient_name: str
) -> tuple | None:
    return _pending_batch.get(_pending_key(batch_id, ingredient_name))


def _clear_pending_batch_ingredient(batch_id: int, ingredient_name: str) -> None:
    _pending_batch.pop(_pending_key(batch_id, ingredient_name), None)


# ---------------------------------------------------------------------------
# Add note to batch
# ---------------------------------------------------------------------------

@router.post(
    "/{batch_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to a batch",
)
def add_batch_note(batch_id: int, note_txt: str, conn: DbConn, _: Auth):
    try:
        nid = App.add_batch_note(conn, batch_id, note_txt)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    from datetime import date
    return NoteResponse(note_id=nid, note_date=str(date.today()))


# ---------------------------------------------------------------------------
# Upload batch image
# ---------------------------------------------------------------------------

@router.post(
    "/{batch_id}/image",
    response_model=MessageResponse,
    summary="Upload or replace the batch photo",
)
async def upload_batch_image(
    batch_id: int,
    conn:     DbConn,
    _:        Auth,
    file:     UploadFile = File(...),
):
    try:
        db.get_batch(conn, batch_id)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))

    data     = await file.read()
    filename = f"{batch_id}{_ext(file.filename)}"
    try:
        path = save_image(data, filename, "batches")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    conn.execute(
        "UPDATE batches SET picture_path = ? WHERE batch_id = ?",
        (path, batch_id),
    )
    conn.commit()
    return MessageResponse(message=f"Image saved to {path}")
