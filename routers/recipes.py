"""
routers/recipes.py — Recipe endpoints
======================================
POST   /recipes                        Create a new recipe (starts a session)
POST   /recipes/{session_key}/ingredients      Add an ingredient to the recipe
POST   /recipes/{session_key}/ingredients/confirm   Confirm a low-confidence ingredient
POST   /recipes/{session_key}/notes    Add a note to the recipe
POST   /recipes/{session_key}/finish   Finalise and close the session
GET    /recipes/search                 Search recipes by name
GET    /recipes/{recipe_id}            Get a single recipe
PUT    /recipes/{recipe_id}            Update recipe metadata
POST   /recipes/{recipe_id}/image      Upload a recipe photo
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

import app as App
import db
from dependencies import (
    Auth, DbConn, create_session, end_session,
    get_usda_api_key, require_session, save_image,
)
from models import (
    IngredientAddRequest, IngredientConfirmRequest, IngredientResult,
    MessageResponse, NoteRequest, NoteResponse,
    RecipeRequest, RecipeResponse, RecipeSummary,
)

router = APIRouter(prefix="/recipes", tags=["Recipes"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_recipe_response(row) -> RecipeResponse:
    return RecipeResponse(
        recipe_id        = row["recipe_id"],
        recipe_name      = row["recipe_name"],
        steps_txt        = row["steps_txt"],
        num_servings     = row["num_servings"],
        active_time_mins = row["active_time_mins"],
        total_time_mins  = row["total_time_mins"],
        need_oven        = bool(row["need_oven"]),
        vegan            = bool(row["vegan"]),
        vegetarian       = bool(row["vegetarian"]),
        source           = row["source"],
        picture_path     = row["picture_path"],
    )


# ---------------------------------------------------------------------------
# Create recipe (starts a multi-step session)
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new recipe and start an ingredient-entry session",
)
def create_recipe(
    req:  RecipeRequest,
    conn: DbConn,
    _:    Auth,
):
    """
    Creates the recipe record and opens a session for adding ingredients.
    Returns a `session_key` that must be included in subsequent calls to
    add ingredients, add notes, and finish the recipe.
    """
    try:
        session = App.add_recipe(
            conn,
            req.recipe_name,
            steps_txt        = req.steps_txt,
            num_servings     = req.num_servings,
            active_time_mins = req.active_time_mins,
            total_time_mins  = req.total_time_mins,
            need_oven        = req.need_oven,
            vegan            = req.vegan,
            vegetarian       = req.vegetarian,
            source           = req.source,
            usda_api_key     = get_usda_api_key(),
        )
    except db.DuplicateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))

    session_key = create_session(session)
    return {
        "session_key": session_key,
        "recipe_id":   session.recipe_id,
        "recipe_name": session.recipe_name,
        "message":     "Recipe created. Use session_key to add ingredients.",
    }


# ---------------------------------------------------------------------------
# Add ingredient to recipe session
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/ingredients",
    response_model=IngredientResult,
    summary="Add an ingredient to a recipe session",
)
def add_ingredient(
    session_key: str,
    req:         IngredientAddRequest,
    conn:        DbConn,
    _:           Auth,
):
    """
    Attempts to add one ingredient to the recipe.

    - If the ingredient is already in the database or found with high
      confidence, it is added immediately (`status: "added"`).
    - If confidence is low, returns `status: "needs_confirmation"` with
      a list of `candidates`. Call `/confirm` with the user's choice.
    - If nothing is found, returns `status: "not_found"`. Call `/confirm`
      with `manual_data` to enter the ingredient manually.
    """
    session = require_session(session_key, App.AddRecipeSession)
    # Attach the live connection (session was created with a different request's conn)
    session.conn = conn
    result = session.add_ingredient(req.ingredient_name, req.quantity_multiple)
    return IngredientResult(**result)


# ---------------------------------------------------------------------------
# Confirm ingredient (after needs_confirmation)
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/ingredients/confirm",
    response_model=IngredientResult,
    summary="Confirm a pending low-confidence ingredient",
)
def confirm_ingredient(
    session_key: str,
    req:         IngredientConfirmRequest,
    conn:        DbConn,
    _:           Auth,
):
    session = require_session(session_key, App.AddRecipeSession)
    session.conn = conn
    try:
        result = session.confirm_ingredient(
            req.pending_key,
            choice      = req.choice,
            manual_data = req.manual_data,
        )
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return IngredientResult(**result)


# ---------------------------------------------------------------------------
# Add note to recipe session
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to the recipe",
)
def add_note(session_key: str, req: NoteRequest, conn: DbConn, _: Auth):
    session = require_session(session_key, App.AddRecipeSession)
    session.conn = conn
    nid = session.add_note(req.note_txt)
    return NoteResponse(note_id=nid, note_date=req.note_date or "")


# ---------------------------------------------------------------------------
# Finish recipe session
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/finish",
    response_model=dict,
    summary="Finalise the recipe and close the session",
)
def finish_recipe(session_key: str, conn: DbConn, _: Auth):
    """
    Commits all pending changes and returns a summary. Any ingredients that
    were presented for confirmation but never confirmed are reported in
    `unresolved` with a warning.
    """
    session = require_session(session_key, App.AddRecipeSession)
    session.conn = conn
    summary = session.finish()
    end_session(session_key)
    return summary


# ---------------------------------------------------------------------------
# Search recipes
# ---------------------------------------------------------------------------

@router.get(
    "/search",
    response_model=list[RecipeSummary],
    summary="Search recipes by name",
)
def search_recipes(
    conn: DbConn,
    _: Auth,
    q:    str = Query(..., min_length=1, description="Search query"),
):
    rows = db.search_recipes(conn, q)
    return [
        RecipeSummary(
            recipe_id    = r["recipe_id"],
            recipe_name  = r["recipe_name"],
            num_servings = r["num_servings"],
            vegan        = bool(r["vegan"]),
            vegetarian   = bool(r["vegetarian"]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Get single recipe
# ---------------------------------------------------------------------------

@router.get(
    "/{recipe_id}",
    response_model=RecipeResponse,
    summary="Get a recipe by ID",
)
def get_recipe(recipe_id: int, conn: DbConn, _: Auth):
    try:
        row = db.get_recipe(conn, recipe_id)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    return _row_to_recipe_response(row)


# ---------------------------------------------------------------------------
# Update recipe metadata
# ---------------------------------------------------------------------------

@router.put(
    "/{recipe_id}",
    response_model=RecipeResponse,
    summary="Update recipe metadata",
)
def update_recipe(recipe_id: int, req: RecipeRequest, conn: DbConn, _: Auth):
    try:
        db.update_recipe(
            conn, recipe_id,
            recipe_name      = req.recipe_name,
            steps_txt        = req.steps_txt,
            num_servings     = req.num_servings,
            active_time_mins = req.active_time_mins,
            total_time_mins  = req.total_time_mins,
            need_oven        = req.need_oven,
            vegan            = req.vegan,
            vegetarian       = req.vegetarian,
            source           = req.source,
        )
        conn.commit()
        row = db.get_recipe(conn, recipe_id)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    return _row_to_recipe_response(row)


# ---------------------------------------------------------------------------
# Upload recipe image
# ---------------------------------------------------------------------------

@router.post(
    "/{recipe_id}/image",
    response_model=MessageResponse,
    summary="Upload or replace the recipe photo",
)
async def upload_recipe_image(
    recipe_id: int,
    conn:      DbConn,
    _:         Auth,
    file:      UploadFile = File(...),
):
    try:
        db.get_recipe(conn, recipe_id)   # raises if not found
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))

    data     = await file.read()
    filename = f"{recipe_id}{_ext(file.filename)}"
    try:
        path = save_image(data, filename, "recipes")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    db.update_recipe(conn, recipe_id, picture_path=path)
    conn.commit()
    return MessageResponse(message=f"Image saved to {path}")


def _ext(filename: str | None) -> str:
    """Extract the file extension, defaulting to .jpg."""
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ".jpg"
