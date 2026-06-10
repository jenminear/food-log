"""
db.py — Food Log Data Access Layer
===================================
All SQL interactions with food_log.db go through this module.
The rest of the app (UI, voice, app-logic) should never write raw SQL.

Conventions
-----------
- Every public function accepts a `conn: sqlite3.Connection` as its first
  argument.  The caller is responsible for opening/closing the connection
  and for calling conn.commit() when a transaction should be persisted.
  Helper `get_connection()` is provided for convenience.
- Functions raise descriptive exceptions on failure rather than returning
  None or error dicts, so callers can catch specific error types.
- All date arguments are ISO-8601 strings: "YYYY-MM-DD".
- Nutrition values (protein, fat, carb, fiber, calories) are always floats
  or None when unknown.
- "quantity_multiple" is the multiplier on an ingredient's base_quantity,
  e.g. if base_quantity=100g and you use 250g, quantity_multiple=2.5.
"""

import sqlite3
import time
from datetime import date as _date
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).with_name("food_log.db")


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """
    Open a connection to the SQLite database with sensible defaults.
    Returns rows as sqlite3.Row objects (accessible by column name).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class FoodLogError(Exception):
    """Base class for all food-log data errors."""

class NotFoundError(FoodLogError):
    """Raised when a requested record does not exist."""

class DuplicateError(FoodLogError):
    """Raised when a uniqueness constraint would be violated."""

class ValidationError(FoodLogError):
    """Raised when caller-supplied data fails a business-logic check."""


# ===========================================================================
# RECIPES
# ===========================================================================

def create_recipe(
    conn: sqlite3.Connection,
    recipe_name: str,
    *,
    steps_txt: Optional[str] = None,
    num_servings: Optional[float] = None,
    active_time_mins: Optional[int] = None,
    total_time_mins: Optional[int] = None,
    need_oven: bool = False,
    vegan: bool = False,
    vegetarian: bool = False,
    source: Optional[str] = None,
    picture_path: Optional[str] = None,
) -> int:
    """
    Insert a new recipe record.
    Returns the new recipe_id.
    Raises DuplicateError if a recipe with the same name already exists.
    """
    recipe_name = recipe_name.strip()
    if not recipe_name:
        raise ValidationError("recipe_name cannot be empty.")

    existing = conn.execute(
        "SELECT recipe_id FROM recipes WHERE LOWER(recipe_name) = LOWER(?)",
        (recipe_name,),
    ).fetchone()
    if existing:
        raise DuplicateError(
            f"A recipe named '{recipe_name}' already exists (id={existing['recipe_id']})."
        )

    cur = conn.execute(
        """
        INSERT INTO recipes
            (recipe_name, picture_path, steps_txt, num_servings,
             active_time_mins, total_time_mins,
             need_oven, vegan, vegetarian, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            recipe_name, picture_path, steps_txt, num_servings,
            active_time_mins, total_time_mins,
            int(need_oven), int(vegan), int(vegetarian), source,
        ),
    )
    return cur.lastrowid


def get_recipe(conn: sqlite3.Connection, recipe_id: int) -> sqlite3.Row:
    """
    Fetch a single recipe by id.
    Raises NotFoundError if it does not exist.
    """
    row = conn.execute(
        "SELECT * FROM recipes WHERE recipe_id = ?", (recipe_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Recipe id={recipe_id} not found.")
    return row


def search_recipes(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """
    Full-text-style word search across recipe names.
    Returns a list of matching recipe rows (may be empty).
    Matches any recipe whose name contains every whitespace-separated word
    in `query` (case-insensitive).
    """
    words = query.strip().split()
    if not words:
        return []

    sql = "SELECT * FROM recipes WHERE " + " AND ".join(
        ["LOWER(recipe_name) LIKE LOWER(?)"] * len(words)
    ) + " ORDER BY recipe_name"
    params = [f"%{w}%" for w in words]
    return conn.execute(sql, params).fetchall()


def update_recipe(
    conn: sqlite3.Connection,
    recipe_id: int,
    **kwargs,
) -> None:
    """
    Update one or more fields on a recipe.
    Allowed kwargs: recipe_name, steps_txt, num_servings, active_time_mins,
                    total_time_mins, need_oven, vegan, vegetarian,
                    source, picture_path.
    Raises NotFoundError if the recipe does not exist.
    Raises ValidationError for unknown fields.
    """
    allowed = {
        "recipe_name", "steps_txt", "num_servings", "active_time_mins",
        "total_time_mins", "need_oven", "vegan", "vegetarian",
        "source", "picture_path",
    }
    bad = set(kwargs) - allowed
    if bad:
        raise ValidationError(f"Unknown recipe fields: {bad}")
    if not kwargs:
        return

    get_recipe(conn, recipe_id)  # raises NotFoundError if missing

    # Coerce booleans
    for bool_field in ("need_oven", "vegan", "vegetarian"):
        if bool_field in kwargs:
            kwargs[bool_field] = int(kwargs[bool_field])

    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(
        f"UPDATE recipes SET {set_clause} WHERE recipe_id = ?",
        (*kwargs.values(), recipe_id),
    )


# ===========================================================================
# INGREDIENTS
# ===========================================================================

def find_ingredient_by_name(
    conn: sqlite3.Connection, name: str
) -> Optional[sqlite3.Row]:
    """
    Look up an ingredient by exact name (case-insensitive).
    Returns the row or None if not found.
    """
    return conn.execute(
        "SELECT * FROM ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
        (name.strip(),),
    ).fetchone()


def create_ingredient(
    conn: sqlite3.Connection,
    ingredient_name: str,
    portion_amount: float = 1.0,
    portion_unit: str = "g",
    *,
    portion_grams: float = 100.0,
    protein_grams: Optional[float] = None,
    fat_grams: Optional[float] = None,
    carb_grams: Optional[float] = None,
    fiber_grams: Optional[float] = None,
    calories: Optional[float] = None,
    nutrition_info_source: Optional[str] = None,
) -> int:
    """
    Insert a new ingredient. All nutrition values are per 100g.
    Portion fields capture a typical serving size for unit conversion:
      portion_amount=1, portion_unit="cup", portion_grams=90  →  1 cup = 90g
    quantity_multiple in components means "number of portions."

    Nutrition calculation:
      nutrient = quantity_multiple × (portion_grams / 100) × nutrient_per_100g

    Returns the new ingredient_id.
    Raises DuplicateError if the name already exists.
    """
    ingredient_name = ingredient_name.strip()
    if not ingredient_name:
        raise ValidationError("ingredient_name cannot be empty.")
    if portion_amount <= 0:
        raise ValidationError("portion_amount must be positive.")
    if not portion_unit.strip():
        raise ValidationError("portion_unit cannot be empty.")
    if portion_grams <= 0:
        raise ValidationError("portion_grams must be positive.")

    if find_ingredient_by_name(conn, ingredient_name):
        raise DuplicateError(f"Ingredient '{ingredient_name}' already exists.")

    cur = conn.execute(
        """
        INSERT INTO ingredients
            (ingredient_name, portion_amount, portion_unit, portion_grams,
             protein_grams, fat_grams, carb_grams, fiber_grams,
             calories, nutrition_info_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ingredient_name, portion_amount, portion_unit, portion_grams,
            protein_grams, fat_grams, carb_grams, fiber_grams,
            calories, nutrition_info_source,
        ),
    )
    return cur.lastrowid


def find_or_create_ingredient(
    conn: sqlite3.Connection,
    ingredient_name: str,
    portion_amount: float = 1.0,
    portion_unit: str = "g",
    **kwargs,
) -> tuple[int, bool]:
    """
    Return (ingredient_id, created) where `created` is True if a new record
    was inserted.  kwargs are passed through to create_ingredient (portion
    fields and nutrition values) and are only used when creating.
    This is the primary entry point when processing recipe ingredients.
    """
    row = find_ingredient_by_name(conn, ingredient_name)
    if row:
        return row["ingredient_id"], False
    ingredient_id = create_ingredient(conn, ingredient_name, portion_amount, portion_unit, **kwargs)
    return ingredient_id, True


def update_ingredient_nutrition(
    conn: sqlite3.Connection,
    ingredient_id: int,
    *,
    portion_amount: Optional[float] = None,
    portion_unit: Optional[str] = None,
    portion_grams: Optional[float] = None,
    protein_grams: Optional[float] = None,
    fat_grams: Optional[float] = None,
    carb_grams: Optional[float] = None,
    fiber_grams: Optional[float] = None,
    calories: Optional[float] = None,
    nutrition_info_source: Optional[str] = None,
) -> None:
    """
    Update nutrition and/or portion fields for an existing ingredient.
    Only fields explicitly passed (non-None) will be updated.
    Raises NotFoundError if the ingredient does not exist.
    """
    fields = {
        "portion_amount": portion_amount,
        "portion_unit": portion_unit,
        "portion_grams": portion_grams,
        "protein_grams": protein_grams,
        "fat_grams": fat_grams,
        "carb_grams": carb_grams,
        "fiber_grams": fiber_grams,
        "calories": calories,
        "nutrition_info_source": nutrition_info_source,
    }
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return

    row = conn.execute(
        "SELECT 1 FROM ingredients WHERE ingredient_id = ?", (ingredient_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Ingredient id={ingredient_id} not found.")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE ingredients SET {set_clause} WHERE ingredient_id = ?",
        (*updates.values(), ingredient_id),
    )


def search_ingredients(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """
    Search ingredient names (case-insensitive substring match).
    Returns a list of matching rows.
    """
    words = query.strip().split()
    if not words:
        return []
    sql = "SELECT * FROM ingredients WHERE " + " AND ".join(
        ["LOWER(ingredient_name) LIKE LOWER(?)"] * len(words)
    ) + " ORDER BY ingredient_name"
    params = [f"%{w}%" for w in words]
    return conn.execute(sql, params).fetchall()


# ===========================================================================
# COMPONENTS
# ===========================================================================

def add_component(
    conn: sqlite3.Connection,
    ingredient_id: int,
    quantity_multiple: float,
    *,
    recipe_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    meal_id: Optional[int] = None,
) -> int:
    """
    Link an ingredient to exactly one of: recipe, batch, or meal.
    Returns the new component_id.
    Raises ValidationError if not exactly one parent is supplied.
    """
    parents = [recipe_id, batch_id, meal_id]
    if sum(p is not None for p in parents) != 1:
        raise ValidationError(
            "Exactly one of recipe_id, batch_id, or meal_id must be provided."
        )
    if quantity_multiple <= 0:
        raise ValidationError("quantity_multiple must be positive.")

    cur = conn.execute(
        """
        INSERT INTO components
            (recipe_id, batch_id, meal_id, ingredient_id, quantity_multiple)
        VALUES (?, ?, ?, ?, ?)
        """,
        (recipe_id, batch_id, meal_id, ingredient_id, quantity_multiple),
    )
    return cur.lastrowid


def get_components(
    conn: sqlite3.Connection,
    *,
    recipe_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    meal_id: Optional[int] = None,
) -> list[sqlite3.Row]:
    """
    Fetch all components for a given recipe, batch, or meal,
    joined with their ingredient data.
    """
    parents = {"recipe_id": recipe_id, "batch_id": batch_id, "meal_id": meal_id}
    active = {k: v for k, v in parents.items() if v is not None}
    if len(active) != 1:
        raise ValidationError(
            "Exactly one of recipe_id, batch_id, or meal_id must be provided."
        )
    col, val = next(iter(active.items()))
    return conn.execute(
        f"""
        SELECT c.*, i.ingredient_name,
               i.portion_amount, i.portion_unit, i.portion_grams,
               i.protein_grams, i.fat_grams, i.carb_grams,
               i.fiber_grams, i.calories
        FROM   components c
        JOIN   ingredients i ON i.ingredient_id = c.ingredient_id
        WHERE  c.{col} = ?
        """,
        (val,),
    ).fetchall()


def remove_component(conn: sqlite3.Connection, component_id: int) -> None:
    """
    Delete a single component record.
    Raises NotFoundError if it does not exist.
    """
    row = conn.execute(
        "SELECT 1 FROM components WHERE component_id = ?", (component_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Component id={component_id} not found.")
    conn.execute("DELETE FROM components WHERE component_id = ?", (component_id,))


def update_component_quantity(
    conn: sqlite3.Connection, component_id: int, quantity_multiple: float
) -> None:
    """
    Change the quantity_multiple for an existing component.
    Raises NotFoundError if it does not exist.
    Raises ValidationError if quantity_multiple <= 0.
    """
    if quantity_multiple <= 0:
        raise ValidationError("quantity_multiple must be positive.")
    row = conn.execute(
        "SELECT 1 FROM components WHERE component_id = ?", (component_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Component id={component_id} not found.")
    conn.execute(
        "UPDATE components SET quantity_multiple = ? WHERE component_id = ?",
        (quantity_multiple, component_id),
    )


def copy_recipe_components_to_batch(
    conn: sqlite3.Connection, recipe_id: int, batch_id: int
) -> int:
    """
    Copy all recipe-level components to the batch, associating them with
    batch_id instead of recipe_id.  Called on the first modification to a
    batch so subsequent edits affect only the batch copy.
    Returns the number of components copied.
    Raises NotFoundError if no components exist for the recipe.
    """
    recipe_components = get_components(conn, recipe_id=recipe_id)
    if not recipe_components:
        raise NotFoundError(
            f"No components found for recipe_id={recipe_id}. "
            "Cannot copy to batch."
        )
    for comp in recipe_components:
        add_component(
            conn,
            ingredient_id=comp["ingredient_id"],
            quantity_multiple=comp["quantity_multiple"],
            batch_id=batch_id,
        )
    return len(recipe_components)


# ===========================================================================
# BATCHES
# ===========================================================================

def create_batch(
    conn: sqlite3.Connection,
    recipe_id: int,
    batch_date: Optional[str] = None,
    *,
    picture_path: Optional[str] = None,
) -> int:
    """
    Create a new batch for the given recipe on batch_date (defaults to today).
    Returns the new batch_id.
    Raises NotFoundError if the recipe does not exist.
    """
    get_recipe(conn, recipe_id)  # raises if missing
    if batch_date is None:
        batch_date = str(_date.today())

    cur = conn.execute(
        """
        INSERT INTO batches (recipe_id, date, picture_path, recipe_changes)
        VALUES (?, ?, ?, 0)
        """,
        (recipe_id, batch_date, picture_path),
    )
    return cur.lastrowid


def get_batch(conn: sqlite3.Connection, batch_id: int) -> sqlite3.Row:
    """
    Fetch a single batch by id, joined with its recipe name.
    Raises NotFoundError if it does not exist.
    """
    row = conn.execute(
        """
        SELECT b.*, r.recipe_name
        FROM   batches b
        JOIN   recipes r ON r.recipe_id = b.recipe_id
        WHERE  b.batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Batch id={batch_id} not found.")
    return row


def get_latest_batch_for_recipe(
    conn: sqlite3.Connection, recipe_id: int
) -> Optional[sqlite3.Row]:
    """
    Return the most recently created batch for a recipe, or None if none exist.
    """
    return conn.execute(
        """
        SELECT * FROM batches
        WHERE  recipe_id = ?
        ORDER  BY date DESC, batch_id DESC
        LIMIT  1
        """,
        (recipe_id,),
    ).fetchone()


def _ensure_batch_components_copied(
    conn: sqlite3.Connection, batch_id: int
) -> None:
    """
    Internal helper: if this is the first modification to a batch, copy the
    recipe's components to the batch and set recipe_changes = 1.
    Idempotent — safe to call multiple times.
    """
    batch = get_batch(conn, batch_id)
    if batch["recipe_changes"] == 0:
        copy_recipe_components_to_batch(conn, batch["recipe_id"], batch_id)
        conn.execute(
            "UPDATE batches SET recipe_changes = 1 WHERE batch_id = ?",
            (batch_id,),
        )


def add_batch_ingredient(
    conn: sqlite3.Connection,
    batch_id: int,
    ingredient_id: int,
    quantity_multiple: float,
) -> int:
    """
    Add a new ingredient to a batch (triggers component copy if first change).
    Returns the new component_id.
    """
    _ensure_batch_components_copied(conn, batch_id)
    return add_component(
        conn, ingredient_id, quantity_multiple, batch_id=batch_id
    )


def remove_batch_ingredient(
    conn: sqlite3.Connection, batch_id: int, component_id: int
) -> None:
    """
    Remove an ingredient component from a batch (triggers copy if first change).
    Raises NotFoundError if the component does not belong to this batch.
    """
    _ensure_batch_components_copied(conn, batch_id)
    row = conn.execute(
        "SELECT 1 FROM components WHERE component_id = ? AND batch_id = ?",
        (component_id, batch_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(
            f"Component id={component_id} not found on batch id={batch_id}."
        )
    remove_component(conn, component_id)


def update_batch_ingredient_quantity(
    conn: sqlite3.Connection,
    batch_id: int,
    component_id: int,
    quantity_multiple: float,
) -> None:
    """
    Change the quantity of an ingredient in a batch (triggers copy if first change).
    Raises NotFoundError if the component does not belong to this batch.
    """
    _ensure_batch_components_copied(conn, batch_id)
    row = conn.execute(
        "SELECT 1 FROM components WHERE component_id = ? AND batch_id = ?",
        (component_id, batch_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(
            f"Component id={component_id} not found on batch id={batch_id}."
        )
    update_component_quantity(conn, component_id, quantity_multiple)


# ===========================================================================
# MEALS
# ===========================================================================

VALID_MEAL_TYPES = {
    "breakfast", "lunch", "dinner",
    "morning_snack", "afternoon_snack", "evening_snack",
}


def create_meal(
    conn: sqlite3.Connection,
    meal_type: str,
    meal_date: Optional[str] = None,
    *,
    batch_id: Optional[int] = None,
    fraction_of_batch: Optional[float] = None,
    timestamp: Optional[int] = None,
) -> int:
    """
    Create a new meal record.

    For batch-based meals:  supply batch_id and fraction_of_batch (0 < f <= 1).
    For ingredient-only meals: leave batch_id=None, then call
                                add_meal_ingredient() for each item.

    timestamp defaults to the current Unix time if not provided.
    Returns the new meal_id.
    """
    meal_type = meal_type.strip().lower()
    if meal_type not in VALID_MEAL_TYPES:
        raise ValidationError(
            f"Invalid meal_type '{meal_type}'. "
            f"Must be one of: {sorted(VALID_MEAL_TYPES)}"
        )
    if meal_date is None:
        meal_date = str(_date.today())
    if timestamp is None:
        timestamp = int(time.time())

    if batch_id is not None:
        if fraction_of_batch is None:
            raise ValidationError(
                "fraction_of_batch is required when batch_id is provided."
            )
        if not (0 < fraction_of_batch <= 1):
            raise ValidationError("fraction_of_batch must be between 0 (exclusive) and 1.")
        # Verify the batch exists
        get_batch(conn, batch_id)

    cur = conn.execute(
        """
        INSERT INTO meals (meal_type, date, timestamp, fraction_of_batch, batch_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (meal_type, meal_date, timestamp, fraction_of_batch, batch_id),
    )
    return cur.lastrowid


def get_meal(conn: sqlite3.Connection, meal_id: int) -> sqlite3.Row:
    """Fetch a meal by id. Raises NotFoundError if missing."""
    row = conn.execute(
        "SELECT * FROM meals WHERE meal_id = ?", (meal_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Meal id={meal_id} not found.")
    return row


def add_meal_ingredient(
    conn: sqlite3.Connection,
    meal_id: int,
    ingredient_id: int,
    quantity_multiple: float,
) -> int:
    """
    Add a standalone ingredient to an ingredient-only meal.
    Raises ValidationError if the meal already has a batch_id (it's a batch meal).
    Returns the new component_id.
    """
    meal = get_meal(conn, meal_id)
    if meal["batch_id"] is not None:
        raise ValidationError(
            f"Meal id={meal_id} is a batch meal; cannot add standalone ingredients."
        )
    return add_component(conn, ingredient_id, quantity_multiple, meal_id=meal_id)


def search_recipes_and_ingredients(
    conn: sqlite3.Connection, query: str
) -> dict[str, list]:
    """
    Search both recipe names and ingredient names simultaneously.
    Returns {"recipes": [...rows], "ingredients": [...rows]}.
    Useful when recording a meal and the user types a food name.
    """
    return {
        "recipes": search_recipes(conn, query),
        "ingredients": search_ingredients(conn, query),
    }


# ===========================================================================
# NOTES
# ===========================================================================

def add_note(
    conn: sqlite3.Connection,
    note_txt: str,
    *,
    recipe_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    meal_id: Optional[int] = None,
    note_date: Optional[str] = None,
) -> int:
    """
    Add a free-text note attached to a recipe, batch, or meal.
    At least one parent id must be supplied.
    note_date defaults to today.
    Returns the new note_id.
    """
    note_txt = note_txt.strip()
    if not note_txt:
        raise ValidationError("note_txt cannot be empty.")

    parents = [recipe_id, batch_id, meal_id]
    if sum(p is not None for p in parents) == 0:
        raise ValidationError(
            "At least one of recipe_id, batch_id, or meal_id must be provided."
        )
    if note_date is None:
        note_date = str(_date.today())

    cur = conn.execute(
        """
        INSERT INTO notes (note_date, recipe_id, batch_id, meal_id, note_txt)
        VALUES (?, ?, ?, ?, ?)
        """,
        (note_date, recipe_id, batch_id, meal_id, note_txt),
    )
    return cur.lastrowid


def get_notes(
    conn: sqlite3.Connection,
    *,
    recipe_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    meal_id: Optional[int] = None,
) -> list[sqlite3.Row]:
    """
    Retrieve notes for a recipe, batch, or meal (supply exactly one).
    Returns rows ordered by date descending.
    """
    parents = {"recipe_id": recipe_id, "batch_id": batch_id, "meal_id": meal_id}
    active = {k: v for k, v in parents.items() if v is not None}
    if len(active) != 1:
        raise ValidationError(
            "Exactly one of recipe_id, batch_id, or meal_id must be provided."
        )
    col, val = next(iter(active.items()))
    return conn.execute(
        f"SELECT * FROM notes WHERE {col} = ? ORDER BY note_date DESC, note_id DESC",
        (val,),
    ).fetchall()


# ===========================================================================
# NUTRITION QUERIES
# ===========================================================================

def _component_nutrition(components: list[sqlite3.Row]) -> dict:
    """
    Compute summed nutrition across a list of component rows.
    Each row must include: quantity_multiple, base_quantity,
    protein_grams, fat_grams, carb_grams, fiber_grams, calories.
    Returns a dict of totals, with None where data is incomplete.
    """
    totals = {k: 0.0 for k in ("protein_grams", "fat_grams", "carb_grams", "fiber_grams", "calories")}
    has_data = {k: False for k in totals}

    for comp in components:
        # quantity_multiple = number of portions; portion_grams/100 converts to
        # the 100g unit that all nutrition columns are expressed in.
        portion_scale = comp["quantity_multiple"] * (comp["portion_grams"] / 100.0)
        for key in totals:
            val = comp[key]
            if val is not None:
                totals[key] += val * portion_scale
                has_data[key] = True

    # Return None for any nutrient with no data at all
    return {k: (totals[k] if has_data[k] else None) for k in totals}


def get_daily_nutrition(
    conn: sqlite3.Connection, query_date: Optional[str] = None
) -> dict:
    """
    Return a full nutritional breakdown for every meal on query_date.

    Structure returned:
    {
        "date": "YYYY-MM-DD",
        "meals": [
            {
                "meal_id": int,
                "meal_type": str,
                "timestamp": int,
                "source": "batch" | "ingredients",
                "recipe_name": str | None,
                "fraction_of_batch": float | None,
                "components": [...],       # list of dicts with ingredient details
                "nutrition": {
                    "protein_grams": float | None,
                    "fat_grams":     float | None,
                    "carb_grams":    float | None,
                    "fiber_grams":   float | None,
                    "calories":      float | None,
                }
            },
            ...
        ],
        "daily_totals": { same nutrition keys }
    }
    """
    if query_date is None:
        query_date = str(_date.today())

    meals = conn.execute(
        """
        SELECT m.*, b.recipe_id, r.recipe_name
        FROM   meals m
        LEFT   JOIN batches b ON b.batch_id = m.batch_id
        LEFT   JOIN recipes r ON r.recipe_id = b.recipe_id
        WHERE  m.date = ?
        ORDER  BY m.timestamp ASC, m.meal_id ASC
        """,
        (query_date,),
    ).fetchall()

    meal_results = []
    daily_totals = {k: 0.0 for k in ("protein_grams", "fat_grams", "carb_grams", "fiber_grams", "calories")}
    daily_has_data = {k: False for k in daily_totals}

    for meal in meals:
        if meal["batch_id"] is not None:
            # Batch meal: if the batch was never modified, components are still
            # stored under recipe_id; only use batch_id if changes were made.
            batch = get_batch(conn, meal["batch_id"])
            if batch["recipe_changes"] == 1:
                components = get_components(conn, batch_id=meal["batch_id"])
            else:
                components = get_components(conn, recipe_id=batch["recipe_id"])
            frac = meal["fraction_of_batch"] or 1.0
            # Build a scaled view for display
            comp_list = []
            for c in components:
                comp_list.append({
                    "ingredient_name":  c["ingredient_name"],
                    "quantity_multiple": c["quantity_multiple"] * frac,
                    "portion_amount":   c["portion_amount"],
                    "portion_unit":     c["portion_unit"],
                    "portion_grams":    c["portion_grams"],
                })
            # Scale nutrition by fraction
            raw_nutrition = _component_nutrition(components)
            nutrition = {
                k: (v * frac if v is not None else None)
                for k, v in raw_nutrition.items()
            }
            source = "batch"
        else:
            # Standalone ingredient meal
            components = get_components(conn, meal_id=meal["meal_id"])
            comp_list = []
            for c in components:
                comp_list.append({
                    "ingredient_name":  c["ingredient_name"],
                    "quantity_multiple": c["quantity_multiple"],
                    "portion_amount":   c["portion_amount"],
                    "portion_unit":     c["portion_unit"],
                    "portion_grams":    c["portion_grams"],
                })
            nutrition = _component_nutrition(components)
            source = "ingredients"

        # Accumulate daily totals
        for k in daily_totals:
            if nutrition[k] is not None:
                daily_totals[k] += nutrition[k]
                daily_has_data[k] = True

        meal_results.append({
            "meal_id":          meal["meal_id"],
            "meal_type":        meal["meal_type"],
            "timestamp":        meal["timestamp"],
            "source":           source,
            "recipe_name":      meal["recipe_name"],
            "fraction_of_batch": meal["fraction_of_batch"],
            "components":       comp_list,
            "nutrition":        nutrition,
        })

    final_totals = {
        k: (daily_totals[k] if daily_has_data[k] else None)
        for k in daily_totals
    }

    return {
        "date":         query_date,
        "meals":        meal_results,
        "daily_totals": final_totals,
    }


def get_aggregate_nutrition(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Sum nutritional information across all meals between start_date and
    end_date (inclusive, ISO-8601 strings).

    Structure returned:
    {
        "start_date": str,
        "end_date":   str,
        "num_days":   int,   # calendar days in range
        "num_meals":  int,
        "totals": {
            "protein_grams": float | None,
            "fat_grams":     float | None,
            "carb_grams":    float | None,
            "fiber_grams":   float | None,
            "calories":      float | None,
        },
        "daily_averages": { same keys, totals / num_days }
    }
    """
    if start_date > end_date:
        raise ValidationError("start_date must be on or before end_date.")

    # Fetch all meals in the range
    meals = conn.execute(
        """
        SELECT m.meal_id, m.batch_id, m.fraction_of_batch
        FROM   meals m
        WHERE  m.date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchall()

    totals = {k: 0.0 for k in ("protein_grams", "fat_grams", "carb_grams", "fiber_grams", "calories")}
    has_data = {k: False for k in totals}

    for meal in meals:
        if meal["batch_id"] is not None:
            batch = get_batch(conn, meal["batch_id"])
            if batch["recipe_changes"] == 1:
                components = get_components(conn, batch_id=meal["batch_id"])
            else:
                components = get_components(conn, recipe_id=batch["recipe_id"])
            frac = meal["fraction_of_batch"] or 1.0
            nutrition = {
                k: (v * frac if v is not None else None)
                for k, v in _component_nutrition(components).items()
            }
        else:
            components = get_components(conn, meal_id=meal["meal_id"])
            nutrition = _component_nutrition(components)

        for k in totals:
            if nutrition[k] is not None:
                totals[k] += nutrition[k]
                has_data[k] = True

    final_totals = {k: (totals[k] if has_data[k] else None) for k in totals}

    # Calendar days in range
    from datetime import date as _d
    start = _d.fromisoformat(start_date)
    end   = _d.fromisoformat(end_date)
    num_days = (end - start).days + 1

    daily_averages = {
        k: (final_totals[k] / num_days if final_totals[k] is not None else None)
        for k in final_totals
    }

    return {
        "start_date":     start_date,
        "end_date":       end_date,
        "num_days":       num_days,
        "num_meals":      len(meals),
        "totals":         final_totals,
        "daily_averages": daily_averages,
    }
