"""
app.py — Food Log Application Logic Layer
==========================================
Orchestrates the five primary user flows by coordinating between the
database access layer (db.py) and the nutrition lookup module
(nutrition_lookup.py).

This layer sits between the UI/voice interface and the data layer.
It handles all business logic: sequencing, ingredient resolution,
nutrition lookup with user confirmation, and transaction management.

The UI layer calls these functions and is responsible for:
  - Rendering the structured dicts returned by each function
  - Collecting user input when a function yields a UserPrompt
  - Calling resume_* functions after the user responds

Design pattern — two-phase flows
---------------------------------
Some flows require user input mid-way (e.g. confirming a nutrition
candidate, choosing a fraction of a batch). These are modelled as:

  start_*()  → returns either a final Result or a UserPrompt
  resume_*() → called with the user's response; returns final Result

All results and prompts are plain dicts so any UI (web, mobile, voice)
can render them without importing this module's types.

Public API — five flows
-----------------------
  add_recipe(conn, name, ...)           → AddRecipeSession
  create_batch(conn, recipe_query, ...) → dict
  record_meal(conn, meal_type, query)   → RecordMealSession
  get_daily_nutrition(conn, date)       → dict   (thin wrapper, direct)
  get_aggregate_nutrition(conn, s, e)   → dict   (thin wrapper, direct)

  add_note(conn, text, ...)             → dict

Sessions (add_recipe, record_meal) are objects with step-by-step methods
that the UI calls in sequence, passing user responses through.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Optional

import db
import nutrition_lookup as NL


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return str(_date.today())


def _resolve_ingredient(
    conn: sqlite3.Connection,
    ingredient_name: str,
    usda_api_key: Optional[str] = None,
) -> tuple[int, bool, Optional[NL.NutritionResult]]:
    """
    Find or look up an ingredient by name.

    Returns (ingredient_id, needs_confirmation, candidate)
      - needs_confirmation=False → ingredient already in DB or auto-picked;
        ingredient_id is valid and committed.
      - needs_confirmation=True  → candidate found but confidence is low;
        call confirm_ingredient() with the user's choice before committing.
        ingredient_id is -1 (not yet created).
    """
    # Already in the database?
    existing = db.find_ingredient_by_name(conn, ingredient_name)
    if existing:
        return existing["ingredient_id"], False, None

    # Look it up
    candidates = NL.lookup(ingredient_name, usda_api_key=usda_api_key)
    if not candidates:
        return -1, True, None   # No results — UI must ask user to enter manually

    best = candidates[0]
    if NL.should_auto_pick(best):
        # High confidence — create the ingredient and commit immediately
        iid = db.create_ingredient(
            conn, best.ingredient_name, **NL.result_to_db_kwargs(best)
        )
        conn.commit()
        return iid, False, best

    # Low/medium confidence — surface candidates to user
    return -1, True, best   # best is just the top; full list fetched separately


# ===========================================================================
# Flow 1: Add a Recipe
# ===========================================================================

@dataclass
class AddRecipeSession:
    """
    Stateful session for the "Add a Recipe" flow.

    Typical usage:
        session = add_recipe(conn, "Lentil Soup", ...)
        for ingredient_name, quantity_multiple in raw_ingredients:
            result = session.add_ingredient(ingredient_name, quantity_multiple)
            if result["needs_confirmation"]:
                # Show result["candidates"] to user, get their choice (1-based index)
                session.confirm_ingredient(result["pending_id"], user_choice, quantity_multiple)
        session.finish()   # commits everything
    """
    conn: sqlite3.Connection
    recipe_id: int
    recipe_name: str
    usda_api_key: Optional[str]
    _ingredients_added: list = field(default_factory=list)
    _pending: dict = field(default_factory=dict)   # ingredient_name → candidates list

    def add_ingredient(
        self,
        ingredient_name: str,
        quantity_multiple: float,
    ) -> dict:
        """
        Attempt to add one ingredient to the recipe.

        Returns a result dict:
          {
            "status":       "added" | "needs_confirmation" | "not_found",
            "ingredient_name": str,         # name as supplied
            "ingredient_id":   int | None,  # set if status == "added"
            "component_id":    int | None,  # set if status == "added"
            "candidates":      list | None, # set if needs_confirmation
            "pending_key":     str | None,  # pass back to confirm_ingredient()
          }
        """
        iid, needs_confirm, best = _resolve_ingredient(
            self.conn, ingredient_name, self.usda_api_key
        )

        if not needs_confirm:
            # Ingredient is in DB (auto-picked or pre-existing) — add component
            cid = db.add_component(
                self.conn, iid, quantity_multiple, recipe_id=self.recipe_id
            )
            self._ingredients_added.append(ingredient_name)
            return {
                "status":          "added",
                "ingredient_name": ingredient_name,
                "ingredient_id":   iid,
                "component_id":    cid,
                "candidates":      None,
                "pending_key":     None,
            }

        # Needs confirmation — store pending state
        candidates = NL.lookup(ingredient_name, usda_api_key=self.usda_api_key)
        pending_key = ingredient_name.lower().strip()
        self._pending[pending_key] = {
            "candidates":       candidates,
            "quantity_multiple": quantity_multiple,
        }
        return {
            "status":          "not_found" if not candidates else "needs_confirmation",
            "ingredient_name": ingredient_name,
            "ingredient_id":   None,
            "component_id":    None,
            "candidates":      [NL.result_to_db_kwargs(c) | {"ingredient_name": c.ingredient_name,
                                                               "summary": c.summary()}
                                 for c in candidates],
            "pending_key":     pending_key,
        }

    def confirm_ingredient(
        self,
        pending_key: str,
        choice: int | None,
        *,
        manual_data: Optional[dict] = None,
    ) -> dict:
        """
        Resolve a pending ingredient after user confirmation.

        Args:
            pending_key:  the pending_key returned by add_ingredient()
            choice:       1-based index into the candidates list, or None
                          if the user wants to enter data manually
            manual_data:  if choice is None, a dict of ingredient fields:
                          {ingredient_name, portion_unit,
                           portion_grams, calories, protein_grams,
                           fat_grams, carb_grams, fiber_grams}

        Returns the same structure as add_ingredient() with status "added".
        Raises KeyError if pending_key is not found.
        Raises ValidationError if choice is out of range.
        """
        pending = self._pending.get(pending_key)
        if pending is None:
            raise KeyError(f"No pending ingredient for key '{pending_key}'.")

        candidates    = pending["candidates"]
        qty_multiple  = pending["quantity_multiple"]

        if choice is not None:
            if not (1 <= choice <= len(candidates)):
                raise db.ValidationError(
                    f"Choice {choice} out of range (1–{len(candidates)})."
                )
            result = candidates[choice - 1]
            name   = result.ingredient_name
            kwargs = NL.result_to_db_kwargs(result)
        else:
            if not manual_data:
                raise db.ValidationError(
                    "manual_data is required when choice is None."
                )
            name   = manual_data.pop("ingredient_name")
            kwargs = manual_data

        iid, _ = db.find_or_create_ingredient(self.conn, name, **kwargs)
        cid = db.add_component(
            self.conn, iid, qty_multiple, recipe_id=self.recipe_id
        )
        del self._pending[pending_key]
        self._ingredients_added.append(name)
        self.conn.commit()

        return {
            "status":          "added",
            "ingredient_name": name,
            "ingredient_id":   iid,
            "component_id":    cid,
            "candidates":      None,
            "pending_key":     None,
        }

    def add_note(self, note_text: str) -> int:
        """Attach a note to this recipe. Returns note_id."""
        nid = db.add_note(self.conn, note_text, recipe_id=self.recipe_id)
        self.conn.commit()
        return nid

    def finish(self) -> dict:
        """
        Finalise the session. Warns about any unresolved pending ingredients.
        Returns a summary dict.
        """
        unresolved = list(self._pending.keys())
        self.conn.commit()
        return {
            "recipe_id":          self.recipe_id,
            "recipe_name":        self.recipe_name,
            "ingredients_added":  self._ingredients_added,
            "unresolved":         unresolved,
            "warnings": (
                [f"Ingredient '{k}' was not confirmed and was skipped."
                 for k in unresolved]
                if unresolved else []
            ),
        }


def add_recipe(
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
    usda_api_key: Optional[str] = None,
) -> AddRecipeSession:
    """
    Start the "Add a Recipe" flow.

    Creates the recipe record and returns an AddRecipeSession the caller
    uses to add ingredients one at a time, handling confirmations as needed.

    Raises db.DuplicateError if a recipe with this name already exists.
    """
    recipe_id = db.create_recipe(
        conn,
        recipe_name,
        steps_txt=steps_txt,
        num_servings=num_servings,
        active_time_mins=active_time_mins,
        total_time_mins=total_time_mins,
        need_oven=need_oven,
        vegan=vegan,
        vegetarian=vegetarian,
        source=source,
        picture_path=picture_path,
    )
    conn.commit()
    return AddRecipeSession(
        conn=conn,
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        usda_api_key=usda_api_key,
    )


# ===========================================================================
# Flow 2: Create a Batch
# ===========================================================================

def create_batch(
    conn: sqlite3.Connection,
    recipe_query: str,
    *,
    batch_date: Optional[str] = None,
    picture_path: Optional[str] = None,
) -> dict:
    """
    Start the "Create a Batch" flow.

    Searches for a recipe by name and creates a new batch.  Returns a dict
    with the batch info and the recipe's current ingredient list so the
    caller can prompt the user for any modifications.

    Returns:
      {
        "status":       "created" | "ambiguous" | "not_found",
        "batch_id":     int | None,
        "recipe_id":    int | None,
        "recipe_name":  str | None,
        "batch_date":   str,
        "components":   list of component dicts | None,
        "candidates":   list of recipe dicts    | None,  # if ambiguous
      }
    """
    if batch_date is None:
        batch_date = _today()

    recipes = db.search_recipes(conn, recipe_query)

    if not recipes:
        return {
            "status": "not_found",
            "batch_id": None, "recipe_id": None, "recipe_name": None,
            "batch_date": batch_date, "components": None, "candidates": None,
        }

    if len(recipes) > 1:
        return {
            "status": "ambiguous",
            "batch_id": None, "recipe_id": None, "recipe_name": None,
            "batch_date": batch_date, "components": None,
            "candidates": [dict(r) for r in recipes],
        }

    recipe = recipes[0]
    batch_id = db.create_batch(
        conn, recipe["recipe_id"], batch_date, picture_path=picture_path
    )
    conn.commit()

    components = db.get_components(conn, recipe_id=recipe["recipe_id"])

    return {
        "status":      "created",
        "batch_id":    batch_id,
        "recipe_id":   recipe["recipe_id"],
        "recipe_name": recipe["recipe_name"],
        "batch_date":  batch_date,
        "components":  _format_components(components),
        "candidates":  None,
    }


def create_batch_from_recipe_id(
    conn: sqlite3.Connection,
    recipe_id: int,
    *,
    batch_date: Optional[str] = None,
    picture_path: Optional[str] = None,
    source_batch_id: Optional[int] = None,
) -> dict:
    """
    Create a batch directly from a known recipe_id (e.g. after resolving
    ambiguity from create_batch()).

    By default, the new batch lazily mirrors the recipe's own ingredient
    list (the usual copy-on-write path — nothing is duplicated until the
    batch is first edited).

    If `source_batch_id` is given, the new batch instead mirrors THAT
    batch's current ingredient list AND notes (e.g. "Cook This" from a
    past batch should reproduce what was actually cooked then, including
    any substitutions — not silently revert to the original recipe). This
    makes the new batch's ingredients diverge from a plain recipe mirror,
    so they're materialized into batch-level components immediately
    (recipe_changes=1) rather than left lazy.
    """
    if batch_date is None:
        batch_date = _today()
    recipe = db.get_recipe(conn, recipe_id)
    batch_id = db.create_batch(conn, recipe_id, batch_date, picture_path=picture_path)

    if source_batch_id is not None:
        source_batch = db.get_batch(conn, source_batch_id)
        source_components = (
            db.get_components(conn, batch_id=source_batch_id)
            if source_batch["recipe_changes"] == 1
            else db.get_components(conn, recipe_id=recipe_id)
        )
        for comp in source_components:
            db.add_component(
                conn,
                ingredient_id=comp["ingredient_id"],
                quantity_multiple=comp["quantity_multiple"],
                batch_id=batch_id,
                original_quantity_text=comp["original_quantity_text"],
            )
        conn.execute("UPDATE batches SET recipe_changes = 1 WHERE batch_id = ?", (batch_id,))
        components = db.get_components(conn, batch_id=batch_id)

        for note in db.get_notes(conn, batch_id=source_batch_id):
            db.add_note(conn, note["note_txt"], batch_id=batch_id, note_date=note["note_date"])
    else:
        components = db.get_components(conn, recipe_id=recipe_id)

    conn.commit()
    return {
        "status":      "created",
        "batch_id":    batch_id,
        "recipe_id":   recipe_id,
        "recipe_name": recipe["recipe_name"],
        "batch_date":  batch_date,
        "components":  _format_components(components),
        "candidates":  None,
    }


def _resolve_batch_component_id(
    conn: sqlite3.Connection,
    batch_id: int,
    component_id: int,
) -> int:
    """
    Ensure a component exists at the batch level and return its batch-level
    component_id.

    When a batch has not yet been modified, its components live at the recipe
    level. If the caller passes a recipe-level component_id, this function
    triggers the copy-on-first-change and returns the matching batch-level
    component_id, via the explicit old-id -> new-id mapping returned by
    copy_recipe_components_to_batch (NOT by re-matching on ingredient_id,
    which is ambiguous when the same ingredient appears more than once in
    the recipe, e.g. "water" listed twice).
    """
    batch = db.get_batch(conn, batch_id)
    if batch["recipe_changes"] == 1:
        # Already copied — component_id should already be batch-level
        return component_id

    # Trigger copy, getting the exact old->new id for every component
    mapping = db.copy_recipe_components_to_batch(conn, batch["recipe_id"], batch_id)
    conn.execute(
        "UPDATE batches SET recipe_changes = 1 WHERE batch_id = ?", (batch_id,)
    )

    if component_id not in mapping:
        raise db.NotFoundError(
            f"Component id={component_id} not found on recipe_id={batch['recipe_id']}."
        )
    return mapping[component_id]


def modify_batch_ingredient(
    conn: sqlite3.Connection,
    batch_id: int,
    action: str,
    *,
    component_id: Optional[int] = None,
    ingredient_name: Optional[str] = None,
    quantity_multiple: Optional[float] = None,
    usda_api_key: Optional[str] = None,
) -> dict:
    """
    Apply a single modification to a batch.

    action must be one of: "add", "remove", "update_quantity".

    For "remove" and "update_quantity": supply component_id.
    For "add": supply ingredient_name and quantity_multiple.
      - If the ingredient is already in the DB, it is added immediately.
      - If it is new, returns status="needs_confirmation" with candidates.

    Returns:
      {
        "status":       "modified" | "needs_confirmation" | "not_found",
        "action":       str,
        "batch_id":     int,
        "component_id": int | None,
        "candidates":   list | None,
        "pending_key":  str | None,
        "components":   updated component list,
      }
    """
    action = action.lower()
    if action not in ("add", "remove", "update_quantity"):
        raise db.ValidationError(
            f"Invalid action '{action}'. Must be add, remove, or update_quantity."
        )

    if action == "remove":
        if component_id is None:
            raise db.ValidationError("component_id required for 'remove'.")
        # If this batch hasn't been modified yet, component_id refers to a
        # recipe-level component. Trigger the copy first, then find the
        # equivalent batch-level component by ingredient_id.
        component_id = _resolve_batch_component_id(conn, batch_id, component_id)
        db.remove_batch_ingredient(conn, batch_id, component_id)
        conn.commit()

    elif action == "update_quantity":
        if component_id is None or quantity_multiple is None:
            raise db.ValidationError(
                "component_id and quantity_multiple required for 'update_quantity'."
            )
        component_id = _resolve_batch_component_id(conn, batch_id, component_id)
        db.update_batch_ingredient_quantity(conn, batch_id, component_id, quantity_multiple)
        conn.commit()

    elif action == "add":
        if ingredient_name is None or quantity_multiple is None:
            raise db.ValidationError(
                "ingredient_name and quantity_multiple required for 'add'."
            )
        iid, needs_confirm, best = _resolve_ingredient(
            conn, ingredient_name, usda_api_key
        )
        if needs_confirm:
            candidates = NL.lookup(ingredient_name, usda_api_key=usda_api_key)
            return {
                "status":       "needs_confirmation",
                "action":       action,
                "batch_id":     batch_id,
                "component_id": None,
                "candidates":   [NL.result_to_db_kwargs(c) | {
                                    "ingredient_name": c.ingredient_name,
                                    "summary": c.summary(),
                                 } for c in candidates],
                "pending_key":  ingredient_name.lower().strip(),
                "components":   None,
            }
        db.add_batch_ingredient(conn, batch_id, iid, quantity_multiple)
        conn.commit()

    batch = db.get_batch(conn, batch_id)
    if batch["recipe_changes"] == 1:
        components = db.get_components(conn, batch_id=batch_id)
    else:
        components = db.get_components(conn, recipe_id=batch["recipe_id"])

    return {
        "status":       "modified",
        "action":       action,
        "batch_id":     batch_id,
        "component_id": component_id,
        "candidates":   None,
        "pending_key":  None,
        "components":   _format_components(components),
    }


def confirm_batch_ingredient(
    conn: sqlite3.Connection,
    batch_id: int,
    ingredient_name: str,
    quantity_multiple: float,
    candidates: list[NL.NutritionResult],
    choice: int | None,
    manual_data: Optional[dict] = None,
) -> dict:
    """
    Confirm a pending ingredient addition to a batch after user selects
    from the candidate list (or provides manual data).
    """
    if choice is not None:
        if not (1 <= choice <= len(candidates)):
            raise db.ValidationError(f"Choice {choice} out of range.")
        result = candidates[choice - 1]
        name   = result.ingredient_name
        kwargs = NL.result_to_db_kwargs(result)
    else:
        if not manual_data:
            raise db.ValidationError("manual_data required when choice is None.")
        name   = manual_data.pop("ingredient_name")
        kwargs = manual_data

    iid, _ = db.find_or_create_ingredient(conn, name, **kwargs)
    db.add_batch_ingredient(conn, batch_id, iid, quantity_multiple)
    conn.commit()

    batch = db.get_batch(conn, batch_id)
    components = db.get_components(
        conn,
        batch_id=batch_id if batch["recipe_changes"] else None,
        recipe_id=batch["recipe_id"] if not batch["recipe_changes"] else None,
    )
    return {
        "status":     "modified",
        "action":     "add",
        "batch_id":   batch_id,
        "components": _format_components(components),
    }


def add_batch_note(conn: sqlite3.Connection, batch_id: int, note_text: str) -> int:
    """Add a note to a batch. Returns note_id."""
    nid = db.add_note(conn, note_text, batch_id=batch_id)
    conn.commit()
    return nid


# ===========================================================================
# Flow 3: Record a Meal
# ===========================================================================

@dataclass
class RecordMealSession:
    """
    Stateful session for the "Record a Meal" flow.

    Typical usage (batch meal):
        session = record_meal(conn, "lunch", "lentil soup")
        # session.search_results has {"recipes": [...], "ingredients": [...]}
        # User picks a recipe:
        result = session.select_recipe(recipe_id, fraction_of_batch=0.5)
        session.finish()

    Typical usage (standalone ingredient meal):
        session = record_meal(conn, "morning_snack", "apple")
        # User picks standalone ingredients:
        session.add_ingredient("apple", quantity_multiple=1.0)
        session.finish()
    """
    conn: sqlite3.Connection
    meal_type: str
    meal_date: str
    search_results: dict       # {"recipes": [...], "ingredients": [...]}
    meal_id: Optional[int] = None
    usda_api_key: Optional[str] = None
    _notes: list = field(default_factory=list)

    def select_recipe(
        self,
        recipe_id: int,
        fraction_of_batch: float,
    ) -> dict:
        """
        Associate this meal with the most recent batch of the given recipe.
        Returns a summary dict including the batch and nutrition preview.
        """
        batch = db.get_latest_batch_for_recipe(self.conn, recipe_id)
        if batch is None:
            raise db.NotFoundError(
                f"No batches found for recipe_id={recipe_id}. "
                "Create a batch before recording a meal from it."
            )

        self.meal_id = db.create_meal(
            self.conn,
            self.meal_type,
            self.meal_date,
            batch_id=batch["batch_id"],
            fraction_of_batch=fraction_of_batch,
        )
        self.conn.commit()

        recipe = db.get_recipe(self.conn, batch["recipe_id"])
        return {
            "status":            "created",
            "meal_id":           self.meal_id,
            "meal_type":         self.meal_type,
            "meal_date":         self.meal_date,
            "batch_id":          batch["batch_id"],
            "recipe_name":       recipe["recipe_name"],
            "fraction_of_batch": fraction_of_batch,
        }

    def start_standalone(self) -> dict:
        """
        Begin a standalone ingredient meal (no associated recipe/batch).
        Must be called before add_ingredient() for standalone meals.
        """
        self.meal_id = db.create_meal(
            self.conn, self.meal_type, self.meal_date
        )
        self.conn.commit()
        return {
            "status":    "created",
            "meal_id":   self.meal_id,
            "meal_type": self.meal_type,
            "meal_date": self.meal_date,
        }

    def add_ingredient(
        self,
        ingredient_name: str,
        quantity_multiple: float,
    ) -> dict:
        """
        Add a standalone ingredient to this meal.
        Returns same structure as AddRecipeSession.add_ingredient().
        Raises db.ValidationError if meal not yet started or is a batch meal.
        """
        if self.meal_id is None:
            raise db.ValidationError(
                "Call start_standalone() before adding ingredients."
            )

        iid, needs_confirm, best = _resolve_ingredient(
            self.conn, ingredient_name, self.usda_api_key
        )

        if not needs_confirm:
            cid = db.add_meal_ingredient(
                self.conn, self.meal_id, iid, quantity_multiple
            )
            self.conn.commit()
            return {
                "status":          "added",
                "ingredient_name": ingredient_name,
                "ingredient_id":   iid,
                "component_id":    cid,
                "candidates":      None,
                "pending_key":     None,
            }

        candidates = NL.lookup(ingredient_name, usda_api_key=self.usda_api_key)
        return {
            "status":          "not_found" if not candidates else "needs_confirmation",
            "ingredient_name": ingredient_name,
            "ingredient_id":   None,
            "component_id":    None,
            "candidates":      [NL.result_to_db_kwargs(c) | {
                                    "ingredient_name": c.ingredient_name,
                                    "summary": c.summary(),
                                } for c in candidates],
            "pending_key":     ingredient_name.lower().strip(),
        }

    def confirm_ingredient(
        self,
        ingredient_name: str,
        quantity_multiple: float,
        candidates: list[NL.NutritionResult],
        choice: int | None,
        manual_data: Optional[dict] = None,
    ) -> dict:
        """Confirm a pending ingredient for this standalone meal."""
        if choice is not None:
            if not (1 <= choice <= len(candidates)):
                raise db.ValidationError(f"Choice {choice} out of range.")
            result = candidates[choice - 1]
            name, kwargs = result.ingredient_name, NL.result_to_db_kwargs(result)
        else:
            if not manual_data:
                raise db.ValidationError("manual_data required when choice is None.")
            name   = manual_data.pop("ingredient_name")
            kwargs = manual_data

        iid, _ = db.find_or_create_ingredient(self.conn, name, **kwargs)
        cid = db.add_meal_ingredient(self.conn, self.meal_id, iid, quantity_multiple)
        self.conn.commit()

        return {
            "status":          "added",
            "ingredient_name": name,
            "ingredient_id":   iid,
            "component_id":    cid,
            "candidates":      None,
            "pending_key":     None,
        }

    def add_note(self, note_text: str) -> int:
        """Add a note to this meal. Returns note_id."""
        if self.meal_id is None:
            raise db.ValidationError("No meal created yet.")
        nid = db.add_note(self.conn, note_text, meal_id=self.meal_id)
        self.conn.commit()
        return nid

    def finish(self) -> dict:
        """Finalise the session. Returns a summary dict."""
        self.conn.commit()
        return {
            "meal_id":   self.meal_id,
            "meal_type": self.meal_type,
            "meal_date": self.meal_date,
            "notes":     self._notes,
        }


def record_meal(
    conn: sqlite3.Connection,
    meal_type: str,
    query: str,
    *,
    meal_date: Optional[str] = None,
    usda_api_key: Optional[str] = None,
) -> RecordMealSession:
    """
    Start the "Record a Meal" flow.

    Searches recipe names and ingredient names simultaneously and returns
    a RecordMealSession. The UI inspects session.search_results to decide
    whether to present recipe or ingredient options to the user.
    """
    if meal_date is None:
        meal_date = _today()

    search_results = db.search_recipes_and_ingredients(conn, query)

    return RecordMealSession(
        conn=conn,
        meal_type=meal_type,
        meal_date=meal_date,
        search_results=search_results,
        usda_api_key=usda_api_key,
    )


# ===========================================================================
# Flow 4: Daily Nutritional Info
# ===========================================================================

def get_daily_nutrition(
    conn: sqlite3.Connection,
    query_date: Optional[str] = None,
) -> dict:
    """
    Return a full nutritional breakdown for a given date.

    Thin wrapper around db.get_daily_nutrition() that adds formatted
    display strings for each nutrient.

    The returned dict has the same structure as db.get_daily_nutrition()
    with an added "display" key on each nutrition block:
      "display": {
          "calories":      "310 kcal",
          "protein_grams": "18.3g protein",
          ...
      }
    """
    if query_date is None:
        query_date = _today()

    report = db.get_daily_nutrition(conn, query_date)
    report["daily_totals"]["display"] = _format_nutrition(report["daily_totals"])

    for meal in report["meals"]:
        meal["nutrition"]["display"] = _format_nutrition(meal["nutrition"])

    return report


# ===========================================================================
# Flow 5: Aggregate Nutritional Info
# ===========================================================================

def get_aggregate_nutrition(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Return summed and averaged nutrition across a date range.

    Thin wrapper around db.get_aggregate_nutrition() that adds formatted
    display strings.
    """
    report = db.get_aggregate_nutrition(conn, start_date, end_date)
    report["totals"]["display"]         = _format_nutrition(report["totals"])
    report["daily_averages"]["display"] = _format_nutrition(report["daily_averages"])
    return report


# ===========================================================================
# Notes (standalone — any level)
# ===========================================================================

def add_note(
    conn: sqlite3.Connection,
    note_text: str,
    *,
    recipe_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    meal_id: Optional[int] = None,
    note_date: Optional[str] = None,
) -> dict:
    """
    Add a free-text note to a recipe, batch, or meal.
    Returns {"note_id": int, "note_date": str}.
    """
    nid = db.add_note(
        conn, note_text,
        recipe_id=recipe_id, batch_id=batch_id, meal_id=meal_id,
        note_date=note_date,
    )
    conn.commit()
    return {"note_id": nid, "note_date": note_date or _today()}


# ===========================================================================
# Formatting helpers
# ===========================================================================

def _format_nutrition(nutrition: dict) -> dict:
    """
    Build human-readable strings for each nutrient.
    Returns a dict of display strings (None values shown as "—").
    """
    def fmt(value, unit, decimals=1):
        if value is None:
            return "—"
        return f"{value:.{decimals}f}{unit}"

    return {
        "calories":      fmt(nutrition.get("calories"),      " kcal", 0),
        "protein_grams": fmt(nutrition.get("protein_grams"), "g protein"),
        "fat_grams":     fmt(nutrition.get("fat_grams"),     "g fat"),
        "carb_grams":    fmt(nutrition.get("carb_grams"),    "g carbs"),
        "fiber_grams":   fmt(nutrition.get("fiber_grams"),   "g fiber"),
    }


def _format_components(components) -> list[dict]:
    """Convert a list of sqlite3.Row component rows to plain dicts."""
    result = []
    for c in components:
        result.append({
            "component_id":    c["component_id"],
            "ingredient_id":   c["ingredient_id"],
            "ingredient_name": c["ingredient_name"],
            "quantity_multiple": c["quantity_multiple"],
            "portion_unit":    c["portion_unit"],
            "portion_grams":   c["portion_grams"],
            "original_quantity_text": c["original_quantity_text"],
            "calories":        c["calories"],
            "protein_grams":   c["protein_grams"],
            "fat_grams":       c["fat_grams"],
            "carb_grams":      c["carb_grams"],
            "fiber_grams":     c["fiber_grams"],
        })
    return result
