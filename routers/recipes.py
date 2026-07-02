"""
routers/recipes.py — Recipe endpoints
======================================
POST   /recipes                        Create a new recipe (starts a session)
POST   /recipes/{session_key}/ingredients      Add an ingredient to the recipe
POST   /recipes/{session_key}/ingredients/confirm   Confirm a low-confidence ingredient
POST   /recipes/{session_key}/notes    Add a note to the recipe
POST   /recipes/{session_key}/finish   Finalise and close the session
GET    /recipes/search                 Search recipes by name
GET    /recipes/ingredients/search     Search for an ingredient (no recipe creation)
GET    /recipes/{recipe_id}            Get a single recipe
PUT    /recipes/{recipe_id}            Update recipe metadata
POST   /recipes/{recipe_id}/image      Upload a recipe photo
POST   /recipes/extract/url            Extract recipe data from a web page
POST   /recipes/extract/image          Extract recipe data from a photo
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

import app as App
import db
import ingredient_weight_estimator as WE
import nutrition_lookup as NL
import recipe_extraction as RE
from dependencies import (
    ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE_BYTES,
    Auth, DbConn, create_session, end_session,
    get_anthropic_api_key, get_usda_api_key, require_session, save_image,
)
from models import (
    BatchSummary,
    ComponentAddRequest, ComponentSummary, ComponentUpdateRequest,
    ExtractedIngredient, ExtractedRecipeResponse,
    IngredientAddRequest, IngredientConfirmRequest, IngredientCreateRequest,
    IngredientDetailResponse,
    IngredientResolveRequest, IngredientResult, IngredientSummary,
    IngredientUpdateRequest,
    MessageResponse, NoteRequest, NoteResponse,
    RecipeRequest, RecipeResponse, RecipeSummary, RecipeUrlRequest,
    WeightEstimateRequest, WeightEstimateResponse,
)

router = APIRouter(prefix="/recipes", tags=["Recipes"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_component_summary(row) -> ComponentSummary:
    return ComponentSummary(
        component_id      = row["component_id"],
        ingredient_id     = row["ingredient_id"],
        ingredient_name   = row["ingredient_name"],
        quantity_multiple = row["quantity_multiple"],
        portion_unit      = row["portion_unit"],
        portion_grams     = row["portion_grams"],
        original_quantity_text = row["original_quantity_text"],
        calories          = row["calories"],
        protein_grams     = row["protein_grams"],
        fat_grams         = row["fat_grams"],
        carb_grams        = row["carb_grams"],
        fiber_grams       = row["fiber_grams"],
    )


def _row_to_ingredient_detail(row) -> IngredientDetailResponse:
    return IngredientDetailResponse(
        ingredient_id          = row["ingredient_id"],
        ingredient_name        = row["ingredient_name"],
        portion_unit           = row["portion_unit"],
        portion_grams          = row["portion_grams"],
        calories               = row["calories"],
        protein_grams          = row["protein_grams"],
        fat_grams              = row["fat_grams"],
        carb_grams             = row["carb_grams"],
        fiber_grams            = row["fiber_grams"],
        source_food_name       = row["source_food_name"],
        nutrition_info_source  = row["nutrition_info_source"],
        data_quality_warning   = NL.compute_data_quality_warning(
            calories=row["calories"], protein_grams=row["protein_grams"],
            fat_grams=row["fat_grams"], carb_grams=row["carb_grams"],
            portion_unit=row["portion_unit"],
        ),
    )


def _row_to_recipe_response(
    conn, row, components: list[ComponentSummary] | None = None
) -> RecipeResponse:
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
        is_locked        = db.recipe_has_batches(conn, row["recipe_id"]),
        components       = components or [],
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
# Search ingredients
# ---------------------------------------------------------------------------

@router.get(
    "/ingredients/search",
    response_model=dict,
    summary="Search for an ingredient without creating a recipe",
)
def search_ingredient(
    conn: DbConn,
    _: Auth,
    q: str = Query(..., min_length=1, description="Ingredient name to search"),
    external_only: bool = Query(
        False,
        description="Skip the local-database lookup and search external APIs directly "
                    "(used when the user rejects the local match via 'None of these')",
    ),
    limit: int = Query(
        5, ge=1, le=25,
        description="Max number of external candidates to return (used by 'more options')",
    ),
):
    """
    Search for an ingredient in the database or via external APIs.
    Returns ingredient info if found, without creating any database records.

    Response format:
    {
        "status": "found" | "candidates" | "not_found",
        "ingredient": {...} | null,       # if status == "found"
        "candidates": [...] | null,       # if status == "candidates"
    }
    """
    # First check if ingredient already exists in database
    existing = None if external_only else db.find_ingredient_by_name(conn, q)
    if existing:
        return {
            "status": "found",
            "ingredient": {
                "ingredient_id": existing["ingredient_id"],
                "ingredient_name": existing["ingredient_name"],
                "portion_unit": existing["portion_unit"],
                "portion_grams": existing["portion_grams"],
                "calories": existing["calories"],
                "protein_grams": existing["protein_grams"],
                "fat_grams": existing["fat_grams"],
                "carb_grams": existing["carb_grams"],
                "fiber_grams": existing["fiber_grams"],
                "data_quality_warning": NL.compute_data_quality_warning(
                    calories=existing["calories"], protein_grams=existing["protein_grams"],
                    fat_grams=existing["fat_grams"], carb_grams=existing["carb_grams"],
                    portion_unit=existing["portion_unit"],
                ),
            },
            "candidates": None,
        }

    # Not in database - search external APIs
    candidates = NL.lookup(q, usda_api_key=get_usda_api_key(), max_candidates=limit)

    if not candidates:
        return {
            "status": "not_found",
            "ingredient": None,
            "candidates": None,
        }

    # Always surface candidates for user verification (even high-confidence
    # matches) - USDA results can be misleading (e.g. "Carrot, dehydrated"
    # for query "carrot"), so the user picks/confirms the result and its
    # portion unit rather than having it silently auto-created.
    return {
        "status": "candidates",
        "ingredient": None,
        "candidates": [
            {
                "ingredient_name": c.ingredient_name,
                "portion_unit": c.portion_unit,
                "portion_grams": c.portion_grams,
                "calories": c.calories,
                "protein_grams": c.protein_grams,
                "fat_grams": c.fat_grams,
                "carb_grams": c.carb_grams,
                "fiber_grams": c.fiber_grams,
                "all_portions": c.all_portions,
                "nutrition_info_source": (
                    f"USDA: {c.ingredient_name}" if c.source == "usda"
                    else f"{c.source}: {c.ingredient_name}"
                ),
                "data_quality_warning": c.data_quality_warning(),
                "summary": c.summary(),
            }
            for c in candidates
        ],
    }


# ---------------------------------------------------------------------------
# Local-only ingredient search (live autocomplete)
# ---------------------------------------------------------------------------

@router.get(
    "/ingredients/local-search",
    response_model=list[IngredientSummary],
    summary="Search the local ingredients table only (for live autocomplete)",
)
def local_search_ingredients(
    conn: DbConn,
    _: Auth,
    q: str = Query(..., min_length=1, description="Ingredient name to search"),
):
    rows = db.search_ingredients(conn, q)
    return [
        IngredientSummary(
            ingredient_id   = r["ingredient_id"],
            ingredient_name = r["ingredient_name"],
            portion_unit    = r["portion_unit"],
            portion_grams   = r["portion_grams"],
            calories        = r["calories"],
            protein_grams   = r["protein_grams"],
            fat_grams       = r["fat_grams"],
            carb_grams      = r["carb_grams"],
            fiber_grams     = r["fiber_grams"],
            data_quality_warning = NL.compute_data_quality_warning(
                calories=r["calories"], protein_grams=r["protein_grams"],
                fat_grams=r["fat_grams"], carb_grams=r["carb_grams"],
                portion_unit=r["portion_unit"],
            ),
        )
        for r in rows[:8]
    ]


# ---------------------------------------------------------------------------
# Browse / create standalone ingredients (the Ingredients tab)
# ---------------------------------------------------------------------------

@router.get(
    "/ingredients",
    response_model=list[IngredientSummary],
    summary="Search the ingredients table (for the Ingredients tab — not capped like local-search)",
)
def browse_ingredients(
    conn: DbConn,
    _: Auth,
    q: str = Query(..., min_length=1, description="Ingredient name to search"),
):
    rows = db.search_ingredients(conn, q)
    return [
        IngredientSummary(
            ingredient_id   = r["ingredient_id"],
            ingredient_name = r["ingredient_name"],
            portion_unit    = r["portion_unit"],
            portion_grams   = r["portion_grams"],
            calories        = r["calories"],
            protein_grams   = r["protein_grams"],
            fat_grams       = r["fat_grams"],
            carb_grams      = r["carb_grams"],
            fiber_grams     = r["fiber_grams"],
            data_quality_warning = NL.compute_data_quality_warning(
                calories=r["calories"], protein_grams=r["protein_grams"],
                fat_grams=r["fat_grams"], carb_grams=r["carb_grams"],
                portion_unit=r["portion_unit"],
            ),
        )
        for r in rows[:50]
    ]


@router.post(
    "/ingredients",
    response_model=IngredientDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a single standalone ingredient directly (no USDA/OFF lookup)",
)
def create_ingredient(req: IngredientCreateRequest, conn: DbConn, _: Auth):
    try:
        ingredient_id = db.create_ingredient(
            conn, req.ingredient_name, req.portion_unit,
            portion_grams=req.portion_grams,
            calories=req.calories,
            protein_grams=req.protein_grams,
            fat_grams=req.fat_grams,
            carb_grams=req.carb_grams,
            fiber_grams=req.fiber_grams,
            nutrition_info_source=req.nutrition_info_source,
        )
        conn.commit()
        row = db.get_ingredient(conn, ingredient_id)
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return _row_to_ingredient_detail(row)


# ---------------------------------------------------------------------------
# Resolve (persist) an ingredient before adding it as a component
# ---------------------------------------------------------------------------

@router.post(
    "/ingredients/resolve",
    response_model=IngredientDetailResponse,
    summary="Find or create an ingredient from a USDA candidate or manual entry",
)
def resolve_ingredient(req: IngredientResolveRequest, conn: DbConn, _: Auth):
    data = req.candidate if req.candidate is not None else req.manual_data
    kwargs = {
        k: v for k, v in data.items()
        if k not in ("ingredient_name", "summary", "ingredient_id", "all_portions", "data_quality_warning")
    }
    if req.candidate is not None:
        # The candidate's own ingredient_name is the USDA/OFF source food
        # name (e.g. "Apple, raw"), distinct from req.ingredient_name (the
        # user's chosen label, e.g. "apple"). It's the de-dup key.
        kwargs["source_food_name"] = data.get("ingredient_name")
    try:
        ingredient_id, _created = db.find_or_create_ingredient(
            conn, req.ingredient_name, **kwargs
        )
        conn.commit()
        row = db.get_ingredient(conn, ingredient_id)
    except (db.ValidationError, TypeError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return _row_to_ingredient_detail(row)


# ---------------------------------------------------------------------------
# Get / update a single ingredient
# ---------------------------------------------------------------------------

@router.get(
    "/ingredients/{ingredient_id}",
    response_model=IngredientDetailResponse,
    summary="Get a single ingredient by ID",
)
def get_ingredient(ingredient_id: int, conn: DbConn, _: Auth):
    try:
        row = db.get_ingredient(conn, ingredient_id)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    return _row_to_ingredient_detail(row)


@router.patch(
    "/ingredients/{ingredient_id}",
    response_model=IngredientDetailResponse,
    summary="Edit an ingredient's nutrition/portion fields",
)
def update_ingredient(ingredient_id: int, req: IngredientUpdateRequest, conn: DbConn, _: Auth):
    fields = req.model_dump(exclude_unset=True, exclude={"ingredient_name"})
    try:
        if req.ingredient_name is not None:
            conn.execute(
                "UPDATE ingredients SET ingredient_name = ? WHERE ingredient_id = ?",
                (req.ingredient_name, ingredient_id),
            )
        if fields:
            db.update_ingredient_nutrition(conn, ingredient_id, **fields)
        conn.commit()
        row = db.get_ingredient(conn, ingredient_id)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return _row_to_ingredient_detail(row)


@router.delete(
    "/ingredients/{ingredient_id}",
    response_model=MessageResponse,
    summary="Delete an ingredient (only if not used in any recipe, batch, or meal)",
)
def delete_ingredient(ingredient_id: int, conn: DbConn, _: Auth):
    try:
        db.delete_ingredient(conn, ingredient_id)
        conn.commit()
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    return MessageResponse(message=f"Ingredient {ingredient_id} deleted.")


# ---------------------------------------------------------------------------
# AI recipe extraction (from URL or photo)
# ---------------------------------------------------------------------------

_IMAGE_MEDIA_TYPES = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}


def _require_anthropic_key() -> str:
    api_key = get_anthropic_api_key()
    if not api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Recipe extraction requires an ANTHROPIC_API_KEY. "
                "Get one at https://console.anthropic.com/settings/keys "
                "and add it to your .env file."
            ),
        )
    return api_key


def _extracted_to_response(extracted: RE.ExtractedRecipe) -> ExtractedRecipeResponse:
    return ExtractedRecipeResponse(
        recipe_name      = extracted.recipe_name,
        num_servings     = extracted.num_servings,
        active_time_mins = extracted.active_time_mins,
        total_time_mins  = extracted.total_time_mins,
        need_oven        = extracted.need_oven,
        vegetarian       = extracted.vegetarian,
        vegan            = extracted.vegan,
        ingredients      = [
            ExtractedIngredient(
                name=i.name, quantity=i.quantity, unit=i.unit, search_name=i.search_name,
                original_quantity_text=i.original_quantity_text,
            )
            for i in extracted.ingredients
        ],
        steps            = extracted.steps,
    )


@router.post(
    "/extract/url",
    response_model=ExtractedRecipeResponse,
    summary="Extract recipe data from a web page using AI",
)
def extract_recipe_from_url(req: RecipeUrlRequest, _: Auth):
    api_key = _require_anthropic_key()
    try:
        extracted = RE.extract_recipe_from_url(req.url, api_key)
    except RE.InvalidUrlError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except RE.FetchError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except RE.ExtractionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return _extracted_to_response(extracted)


@router.post(
    "/extract/image",
    response_model=ExtractedRecipeResponse,
    summary="Extract recipe data from a photo using AI",
)
async def extract_recipe_from_image(_: Auth, file: UploadFile = File(...)):
    api_key = _require_anthropic_key()

    ext = _ext(file.filename)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported image type '{ext}'. Allowed: {sorted(ALLOWED_IMAGE_EXTENSIONS)}",
        )

    data = await file.read()
    if len(data) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Image too large ({len(data) / 1024 / 1024:.1f} MB). "
                   f"Maximum: {MAX_IMAGE_SIZE_BYTES // 1024 // 1024} MB.",
        )

    try:
        extracted = RE.extract_recipe_from_image(data, _IMAGE_MEDIA_TYPES[ext], api_key)
    except RE.ExtractionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return _extracted_to_response(extracted)


@router.post(
    "/ingredients/estimate-weight",
    response_model=WeightEstimateResponse,
    summary="AI-estimate an ingredient quantity's weight in grams (last resort)",
)
def estimate_ingredient_weight(req: WeightEstimateRequest, _: Auth):
    """
    Used only when the frontend's table-based and density-based unit
    conversions both fail (e.g. count-based amounts like "2 avocados", or
    vague phrases). Returns `found: false` if no reasonable estimate could
    be made — the caller should fall back to manual entry in that case.
    """
    api_key = _require_anthropic_key()
    try:
        estimate = WE.estimate_grams(req.ingredient_name, req.quantity, req.unit, api_key)
    except WE.EstimationError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(e))
    if estimate is None:
        return WeightEstimateResponse(found=False)
    return WeightEstimateResponse(found=True, grams=estimate.grams, confidence=estimate.confidence)


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
    components = [_row_to_component_summary(c) for c in db.get_components(conn, recipe_id=recipe_id)]
    return _row_to_recipe_response(conn, row, components)


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
    return _row_to_recipe_response(conn, row)


# ---------------------------------------------------------------------------
# Delete a recipe (only while it has no batches — i.e. still a draft)
# ---------------------------------------------------------------------------

@router.delete(
    "/{recipe_id}",
    response_model=MessageResponse,
    summary="Delete a recipe (only allowed before it has any batches)",
)
def delete_recipe(recipe_id: int, conn: DbConn, _: Auth):
    try:
        db.delete_recipe(conn, recipe_id)
        conn.commit()
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    return MessageResponse(message=f"Recipe {recipe_id} deleted.")


# ---------------------------------------------------------------------------
# Batch history for a recipe
# ---------------------------------------------------------------------------

@router.get(
    "/{recipe_id}/batches",
    response_model=list[BatchSummary],
    summary="List a recipe's batches (newest first)",
)
def list_recipe_batches(recipe_id: int, conn: DbConn, _: Auth):
    try:
        db.get_recipe(conn, recipe_id)  # 404 if missing
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    rows = db.list_batches_for_recipe(conn, recipe_id)
    return [BatchSummary(batch_id=r["batch_id"], date=r["date"]) for r in rows]


# ---------------------------------------------------------------------------
# Recipe components (ingredients within a recipe)
# ---------------------------------------------------------------------------

def _require_unlocked_recipe(conn, recipe_id: int) -> None:
    """
    Raise 409 if the recipe already has a batch — once cooked, the recipe's
    own ingredient list is frozen; further quantity changes belong to a
    batch (via /batches/{batch_id}/components), not the recipe itself.
    """
    if db.recipe_has_batches(conn, recipe_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This recipe has been cooked and its ingredients are frozen. "
                   "Use 'Cook This' and edit the batch instead.",
        )


@router.post(
    "/{recipe_id}/components",
    response_model=ComponentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Add an ingredient (component) to a recipe",
)
def add_recipe_component(recipe_id: int, req: ComponentAddRequest, conn: DbConn, _: Auth):
    _require_unlocked_recipe(conn, recipe_id)
    try:
        component_id = db.add_component(
            conn, req.ingredient_id, req.quantity_multiple, recipe_id=recipe_id,
            original_quantity_text=req.original_quantity_text,
        )
        conn.commit()
    except (db.NotFoundError, db.ValidationError) as e:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(e, db.NotFoundError) else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code, detail=str(e))
    rows = db.get_components(conn, recipe_id=recipe_id)
    row = next(r for r in rows if r["component_id"] == component_id)
    return _row_to_component_summary(row)


@router.patch(
    "/{recipe_id}/components/{component_id}",
    response_model=ComponentSummary,
    summary="Update a recipe component's quantity",
)
def update_recipe_component(
    recipe_id: int, component_id: int, req: ComponentUpdateRequest, conn: DbConn, _: Auth,
):
    _require_unlocked_recipe(conn, recipe_id)
    try:
        db.update_component_quantity(
            conn, component_id, req.quantity_multiple,
            original_quantity_text=req.original_quantity_text,
            update_original_quantity_text=True,
        )
        conn.commit()
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    rows = db.get_components(conn, recipe_id=recipe_id)
    row = next(r for r in rows if r["component_id"] == component_id)
    return _row_to_component_summary(row)


@router.delete(
    "/{recipe_id}/components/{component_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an ingredient (component) from a recipe",
)
def delete_recipe_component(recipe_id: int, component_id: int, conn: DbConn, _: Auth):
    _require_unlocked_recipe(conn, recipe_id)
    try:
        db.remove_component(conn, component_id)
        conn.commit()
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))


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
