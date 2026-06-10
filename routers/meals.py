"""
routers/meals.py — Meal endpoints
===================================
POST   /meals/start                     Start a meal session (search + return options)
POST   /meals/select-recipe             Select a recipe batch for the meal
POST   /meals/start-standalone          Begin a standalone ingredient meal
POST   /meals/{session_key}/ingredients Add an ingredient to a standalone meal
POST   /meals/{session_key}/ingredients/confirm  Confirm low-confidence ingredient
POST   /meals/{session_key}/notes       Add a note to the meal
POST   /meals/{session_key}/finish      Finalise the meal and close the session
GET    /meals/{meal_id}                 Get a meal record
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

import app as App
import db
from dependencies import (
    Auth, DbConn, create_session, end_session,
    get_usda_api_key, require_session,
)
from models import (
    IngredientAddRequest, IngredientConfirmRequest, IngredientResult,
    MealAddIngredientRequest, MealResponse, MealSearchResponse,
    MealSelectRecipeRequest, MealStartRequest, NoteResponse, RecipeSummary,
)

router = APIRouter(prefix="/meals", tags=["Meals"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_response(session: App.RecordMealSession, session_key: str) -> MealSearchResponse:
    recipes = [
        RecipeSummary(
            recipe_id    = r["recipe_id"],
            recipe_name  = r["recipe_name"],
            num_servings = dict(r).get("num_servings"),
            vegan        = bool(dict(r).get("vegan", 0)),
            vegetarian   = bool(dict(r).get("vegetarian", 0)),
        )
        for r in session.search_results.get("recipes", [])
    ]
    ingredients = [
        {
            "ingredient_id":   i["ingredient_id"],
            "ingredient_name": i["ingredient_name"],
            "portion_unit":    i["portion_unit"],
        }
        for i in session.search_results.get("ingredients", [])
    ]
    return MealSearchResponse(
        session_key  = session_key,
        meal_type    = session.meal_type,
        meal_date    = session.meal_date,
        recipes      = recipes,
        ingredients  = ingredients,
    )


# ---------------------------------------------------------------------------
# Start meal session (search)
# ---------------------------------------------------------------------------

@router.post(
    "/start",
    response_model=MealSearchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a meal session — searches recipes and ingredients",
)
def start_meal(req: MealStartRequest, conn: DbConn, _: Auth):
    """
    Searches recipe names and ingredient names for `query`.
    Returns a `session_key` plus matching `recipes` and `ingredients`.

    Next step — choose one:
    - If eating a recipe batch: `POST /meals/select-recipe`
    - If eating standalone ingredients: `POST /meals/start-standalone`
    """
    session = App.record_meal(
        conn,
        req.meal_type,
        req.query,
        meal_date    = req.meal_date,
        usda_api_key = get_usda_api_key(),
    )
    session_key = create_session(session)
    return _session_response(session, session_key)


# ---------------------------------------------------------------------------
# Select recipe batch
# ---------------------------------------------------------------------------

@router.post(
    "/select-recipe",
    response_model=MealResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Associate a meal with the most recent batch of a recipe",
)
def select_recipe(req: MealSelectRecipeRequest, conn: DbConn, _: Auth):
    """
    Links the meal to the most recent batch of `recipe_id`.
    Provide `fraction_of_batch` (0 < f ≤ 1).
    Automatically closes the session.
    """
    session: App.RecordMealSession = require_session(req.session_key, App.RecordMealSession)
    session.conn = conn

    try:
        result = session.select_recipe(req.recipe_id, req.fraction_of_batch)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    session.finish()
    end_session(req.session_key)
    return MealResponse(**result)


# ---------------------------------------------------------------------------
# Start standalone (ingredient-only) meal
# ---------------------------------------------------------------------------

@router.post(
    "/start-standalone",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Begin a standalone ingredient meal (no associated recipe)",
)
def start_standalone(session_key: str, conn: DbConn, _: Auth):
    """
    Creates the meal record. Follow up with `POST /meals/{session_key}/ingredients`
    for each ingredient consumed.
    """
    session: App.RecordMealSession = require_session(session_key, App.RecordMealSession)
    session.conn = conn

    try:
        result = session.start_standalone()
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return {"session_key": session_key, **result}


# ---------------------------------------------------------------------------
# Add ingredient to standalone meal
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/ingredients",
    response_model=IngredientResult,
    summary="Add an ingredient to a standalone meal",
)
def add_meal_ingredient(
    session_key: str,
    req:         IngredientAddRequest,
    conn:        DbConn,
    _:           Auth,
):
    session: App.RecordMealSession = require_session(session_key, App.RecordMealSession)
    session.conn = conn

    try:
        result = session.add_ingredient(req.ingredient_name, req.quantity_multiple)
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return IngredientResult(**result)


# ---------------------------------------------------------------------------
# Confirm ingredient
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/ingredients/confirm",
    response_model=IngredientResult,
    summary="Confirm a pending low-confidence ingredient for a meal",
)
def confirm_meal_ingredient(
    session_key: str,
    req:         IngredientConfirmRequest,
    conn:        DbConn,
    _:           Auth,
):
    session: App.RecordMealSession = require_session(session_key, App.RecordMealSession)
    session.conn = conn

    # Re-run the lookup to get NutritionResult objects for the choice
    import nutrition_lookup as NL
    candidates_raw = NL.lookup(
        req.pending_key, usda_api_key=get_usda_api_key()
    )

    try:
        # Find the quantity_multiple that was stored with the pending ingredient
        # by re-parsing from the session (stored in the pending dict key)
        # We need the qty from the original add_ingredient call; since we
        # don't store it in the session, the client must re-send it.
        # For robustness, default to 1.0 if missing (client should always send it).
        qty = getattr(req, "quantity_multiple", 1.0) or 1.0
        result = session.confirm_ingredient(
            req.pending_key,
            qty,
            candidates_raw,
            choice      = req.choice,
            manual_data = req.manual_data,
        )
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return IngredientResult(**result)


# ---------------------------------------------------------------------------
# Add note
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to the meal",
)
def add_meal_note(session_key: str, note_txt: str, conn: DbConn, _: Auth):
    session: App.RecordMealSession = require_session(session_key, App.RecordMealSession)
    session.conn = conn
    try:
        nid = session.add_note(note_txt)
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    from datetime import date
    return NoteResponse(note_id=nid, note_date=str(date.today()))


# ---------------------------------------------------------------------------
# Finish meal session
# ---------------------------------------------------------------------------

@router.post(
    "/{session_key}/finish",
    response_model=dict,
    summary="Finalise the meal and close the session",
)
def finish_meal(session_key: str, conn: DbConn, _: Auth):
    session: App.RecordMealSession = require_session(session_key, App.RecordMealSession)
    session.conn = conn
    summary = session.finish()
    end_session(session_key)
    return summary


# ---------------------------------------------------------------------------
# Get meal
# ---------------------------------------------------------------------------

@router.get(
    "/{meal_id}",
    response_model=MealResponse,
    summary="Get a meal record by ID",
)
def get_meal(meal_id: int, conn: DbConn, _: Auth):
    try:
        meal = db.get_meal(conn, meal_id)
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    return MealResponse(
        meal_id           = meal["meal_id"],
        meal_type         = meal["meal_type"],
        meal_date         = meal["date"],
        batch_id          = meal["batch_id"],
        fraction_of_batch = meal["fraction_of_batch"],
    )
