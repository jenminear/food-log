"""
test_api.py — Tests for the Food Log REST API
===============================================
Uses FastAPI's TestClient (backed by httpx) so the full ASGI stack is
exercised without a running server.  All tests use an in-memory SQLite
database and mock nutrition_lookup so no network calls are made.

Run with:
    python test_api.py

Or via pytest:
    pytest test_api.py -v
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Patch the DB path before importing the app ────────────────────────────
# We redirect the app to an in-memory database for every test.
import dependencies
_ORIG_DB_PATH = dependencies.DB_PATH

from fastapi.testclient import TestClient
from main import app

import db
import nutrition_lookup as NL

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SCHEMA_SQL = (Path(__file__).with_name("food_log_schema.sql")).read_text()


def _make_in_memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def _make_nl_result(name="Rolled Oats", confidence=0.92, **kwargs) -> NL.NutritionResult:
    defaults = dict(
        ingredient_name = name,
        source          = "usda",
        source_id       = "173904",
        source_url      = "https://fdc.nal.usda.gov/fdc-app.html#/food-details/173904/nutrients",
        portion_unit    = "1 cup",
        portion_grams   = 90.0,
        calories        = 379.0,
        protein_grams   = 13.15,
        fat_grams       = 6.52,
        carb_grams      = 67.7,
        fiber_grams     = 10.1,
        confidence      = confidence,
    )
    defaults.update(kwargs)
    return NL.NutritionResult(**defaults)


class BaseAPITest(unittest.TestCase):
    """
    Base class that wires the app to an in-memory database for each test.
    Each test method gets a fresh database.
    """

    def setUp(self):
        self.conn = _make_in_memory_conn()
        # Override get_db to yield our in-memory connection
        app.dependency_overrides[dependencies.get_db]   = lambda: self.conn
        app.dependency_overrides[dependencies.require_auth] = lambda: None
        self.client = TestClient(app, raise_server_exceptions=True)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.conn.close()

    # ── Seed helpers ──────────────────────────────────────────────────────

    def _seed_recipe(self, name="Veggie Bowl") -> int:
        rid  = db.create_recipe(self.conn, name)
        iid1 = db.create_ingredient(self.conn, "Brown Rice",
                                     portion_unit="g", portion_grams=100.0,
                                     calories=112, protein_grams=2.6,
                                     fat_grams=0.9, carb_grams=23.0, fiber_grams=1.8)
        iid2 = db.create_ingredient(self.conn, "Broccoli",
                                     portion_unit="cup", portion_grams=91.0,
                                     calories=34, protein_grams=2.8,
                                     fat_grams=0.4, carb_grams=7.0, fiber_grams=2.6)
        db.add_component(self.conn, iid1, 2.0, recipe_id=rid)
        db.add_component(self.conn, iid2, 1.5, recipe_id=rid)
        self.conn.commit()
        return rid

    def _seed_batch(self, recipe_id: int, date="2026-05-14") -> int:
        bid = db.create_batch(self.conn, recipe_id, date)
        self.conn.commit()
        return bid


# ===========================================================================
# Health check
# ===========================================================================

class TestHealth(BaseAPITest):

    def test_health_returns_200(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")


# ===========================================================================
# Recipes
# ===========================================================================

class TestRecipeEndpoints(BaseAPITest):

    def test_create_recipe_returns_session_key(self):
        r = self.client.post("/recipes", json={"recipe_name": "Lentil Soup"})
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertIn("session_key", data)
        self.assertIn("recipe_id",   data)

    def test_create_duplicate_recipe_returns_409(self):
        self.client.post("/recipes", json={"recipe_name": "Pasta"})
        r = self.client.post("/recipes", json={"recipe_name": "Pasta"})
        self.assertEqual(r.status_code, 409)

    def test_create_recipe_with_all_fields(self):
        payload = {
            "recipe_name":      "Chili",
            "steps_txt":        "1. Brown beef. 2. Add beans.",
            "num_servings":     6,
            "active_time_mins": 20,
            "total_time_mins":  60,
            "need_oven":        False,
            "vegan":            False,
            "vegetarian":       False,
            "source":           "https://example.com/chili",
        }
        r = self.client.post("/recipes", json=payload)
        self.assertEqual(r.status_code, 201)

    def test_add_ingredient_existing(self):
        """Ingredient already in DB → status added immediately."""
        db.create_ingredient(self.conn, "Rolled Oats",
                              portion_unit="cup", portion_grams=90.0, calories=379)
        self.conn.commit()
        r1   = self.client.post("/recipes", json={"recipe_name": "Porridge"})
        skey = r1.json()["session_key"]
        r2   = self.client.post(
            f"/recipes/{skey}/ingredients",
            json={"ingredient_name": "Rolled Oats", "quantity_multiple": 1.0},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "added")

    def test_add_ingredient_high_confidence(self):
        """High-confidence lookup → auto-added."""
        mock_result = _make_nl_result("Rolled Oats", confidence=0.92)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            r1   = self.client.post("/recipes", json={"recipe_name": "Oats"})
            skey = r1.json()["session_key"]
            r2   = self.client.post(
                f"/recipes/{skey}/ingredients",
                json={"ingredient_name": "oats", "quantity_multiple": 1.5},
            )
        self.assertEqual(r2.json()["status"], "added")

    def test_add_ingredient_low_confidence_needs_confirmation(self):
        mock_result = _make_nl_result("Oat Bran", confidence=0.35)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            r1   = self.client.post("/recipes", json={"recipe_name": "Bran Bowl"})
            skey = r1.json()["session_key"]
            r2   = self.client.post(
                f"/recipes/{skey}/ingredients",
                json={"ingredient_name": "bran stuff", "quantity_multiple": 1.0},
            )
        data = r2.json()
        self.assertEqual(data["status"], "needs_confirmation")
        self.assertIsNotNone(data["candidates"])
        self.assertIsNotNone(data["pending_key"])

    def test_confirm_ingredient(self):
        mock_result = _make_nl_result("Quinoa", confidence=0.40)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            r1   = self.client.post("/recipes", json={"recipe_name": "Grain Bowl"})
            skey = r1.json()["session_key"]
            pend = self.client.post(
                f"/recipes/{skey}/ingredients",
                json={"ingredient_name": "quinoa", "quantity_multiple": 1.0},
            )
        pending_key = pend.json()["pending_key"]
        r3 = self.client.post(
            f"/recipes/{skey}/ingredients/confirm",
            json={"pending_key": pending_key, "choice": 1},
        )
        self.assertEqual(r3.json()["status"], "added")

    def test_confirm_ingredient_manual_data(self):
        with patch("nutrition_lookup.lookup", return_value=[]):
            r1   = self.client.post("/recipes", json={"recipe_name": "Custom"})
            skey = r1.json()["session_key"]
            pend = self.client.post(
                f"/recipes/{skey}/ingredients",
                json={"ingredient_name": "mystery grain", "quantity_multiple": 1.0},
            )
        pending_key = pend.json()["pending_key"]
        r3 = self.client.post(
            f"/recipes/{skey}/ingredients/confirm",
            json={
                "pending_key": pending_key,
                "choice":      None,
                "manual_data": {
                    "ingredient_name": "Mystery Grain",
                    "portion_unit":    "1 cup",
                    "portion_grams":   120.0,
                    "calories":        300.0,
                    "protein_grams":   10.0,
                    "fat_grams":       4.0,
                    "carb_grams":      55.0,
                    "fiber_grams":     6.0,
                },
            },
        )
        self.assertEqual(r3.json()["status"], "added")

    def test_finish_recipe_session(self):
        db.create_ingredient(self.conn, "Lentils",
                              portion_unit="cup", portion_grams=192.0, calories=230)
        self.conn.commit()
        r1   = self.client.post("/recipes", json={"recipe_name": "Lentil Stew"})
        skey = r1.json()["session_key"]
        self.client.post(
            f"/recipes/{skey}/ingredients",
            json={"ingredient_name": "Lentils", "quantity_multiple": 2.0},
        )
        r3 = self.client.post(f"/recipes/{skey}/finish")
        self.assertEqual(r3.status_code, 200)
        data = r3.json()
        self.assertIn("ingredients_added", data)
        self.assertIn("Lentils", data["ingredients_added"])

    def test_get_recipe(self):
        rid = self._seed_recipe()
        r   = self.client.get(f"/recipes/{rid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["recipe_name"], "Veggie Bowl")

    def test_get_recipe_not_found(self):
        r = self.client.get("/recipes/9999")
        self.assertEqual(r.status_code, 404)

    def test_search_recipes(self):
        self._seed_recipe("Veggie Bowl")
        db.create_recipe(self.conn, "Veggie Stir Fry")
        db.create_recipe(self.conn, "Lentil Soup")
        self.conn.commit()
        r = self.client.get("/recipes/search?q=veggie")
        self.assertEqual(r.status_code, 200)
        names = [x["recipe_name"] for x in r.json()]
        self.assertIn("Veggie Bowl",     names)
        self.assertIn("Veggie Stir Fry", names)
        self.assertNotIn("Lentil Soup",  names)

    def test_search_recipes_no_results(self):
        r = self.client.get("/recipes/search?q=xyznonexistent")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_update_recipe(self):
        rid = self._seed_recipe()
        r   = self.client.put(
            f"/recipes/{rid}",
            json={"recipe_name": "Veggie Bowl Updated", "vegan": True},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["recipe_name"], "Veggie Bowl Updated")
        self.assertTrue(r.json()["vegan"])

    def test_add_note_to_recipe_session(self):
        r1   = self.client.post("/recipes", json={"recipe_name": "Stew"})
        skey = r1.json()["session_key"]
        r2   = self.client.post(
            f"/recipes/{skey}/notes",
            json={"note_txt": "Add more cumin.", "recipe_id": r1.json()["recipe_id"]},
        )
        self.assertEqual(r2.status_code, 201)
        self.assertIn("note_id", r2.json())


# ===========================================================================
# Batches
# ===========================================================================

class TestBatchEndpoints(BaseAPITest):

    def test_create_batch_found(self):
        self._seed_recipe()
        r = self.client.post("/batches?recipe_query=Veggie+Bowl")
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertEqual(data["status"], "created")
        self.assertIsNotNone(data["batch_id"])
        self.assertEqual(len(data["components"]), 2)

    def test_create_batch_not_found(self):
        r = self.client.post("/batches?recipe_query=nonexistent")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["status"], "not_found")

    def test_create_batch_ambiguous(self):
        db.create_recipe(self.conn, "Lentil Soup Red")
        db.create_recipe(self.conn, "Lentil Soup Green")
        self.conn.commit()
        r = self.client.post("/batches?recipe_query=Lentil+Soup")
        data = r.json()
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(len(data["candidates"]), 2)

    def test_create_batch_from_recipe_id(self):
        rid = self._seed_recipe()
        r   = self.client.post(f"/batches/from-recipe/{rid}")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["status"], "created")

    def test_get_batch(self):
        rid = self._seed_recipe()
        bid = self._seed_batch(rid)
        r   = self.client.get(f"/batches/{bid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["batch_id"], bid)
        self.assertEqual(len(r.json()["components"]), 2)

    def test_get_batch_not_found(self):
        r = self.client.get("/batches/9999")
        self.assertEqual(r.status_code, 404)

    def test_modify_batch_remove(self):
        rid  = self._seed_recipe()
        r1   = self.client.post(f"/batches/from-recipe/{rid}")
        bid  = r1.json()["batch_id"]
        comp = r1.json()["components"][0]["component_id"]
        r2   = self.client.patch(
            f"/batches/{bid}",
            json={"action": "remove", "component_id": comp},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "modified")
        self.assertEqual(len(r2.json()["components"]), 1)

    def test_modify_batch_update_quantity(self):
        rid  = self._seed_recipe()
        r1   = self.client.post(f"/batches/from-recipe/{rid}")
        bid  = r1.json()["batch_id"]
        comp = r1.json()["components"][0]["component_id"]
        r2   = self.client.patch(
            f"/batches/{bid}",
            json={"action": "update_quantity", "component_id": comp, "quantity_multiple": 5.0},
        )
        self.assertEqual(r2.status_code, 200)
        quantities = [c["quantity_multiple"] for c in r2.json()["components"]]
        self.assertIn(5.0, quantities)

    def test_modify_batch_add_existing_ingredient(self):
        rid = self._seed_recipe()
        db.create_ingredient(self.conn, "Chickpeas",
                              portion_unit="cup", portion_grams=164.0, calories=269)
        self.conn.commit()
        r1  = self.client.post(f"/batches/from-recipe/{rid}")
        bid = r1.json()["batch_id"]
        r2  = self.client.patch(
            f"/batches/{bid}",
            json={"action": "add", "ingredient_name": "Chickpeas", "quantity_multiple": 1.0},
        )
        self.assertEqual(r2.json()["status"], "modified")
        self.assertEqual(len(r2.json()["components"]), 3)

    def test_modify_batch_invalid_action_returns_422(self):
        rid = self._seed_recipe()
        r1  = self.client.post(f"/batches/from-recipe/{rid}")
        bid = r1.json()["batch_id"]
        r2  = self.client.patch(
            f"/batches/{bid}",
            json={"action": "explode"},
        )
        self.assertEqual(r2.status_code, 422)

    def test_add_batch_note(self):
        rid = self._seed_recipe()
        bid = self._seed_batch(rid)
        r   = self.client.post(f"/batches/{bid}/notes?note_txt=Used+less+salt")
        self.assertEqual(r.status_code, 201)
        self.assertIn("note_id", r.json())


# ===========================================================================
# Meals
# ===========================================================================

class TestMealEndpoints(BaseAPITest):

    def test_start_meal_returns_session(self):
        self._seed_recipe()
        r = self.client.post("/meals/start", json={
            "meal_type": "lunch",
            "query":     "veggie",
            "meal_date": "2026-05-14",
        })
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertIn("session_key", data)
        self.assertGreater(len(data["recipes"]), 0)

    def test_select_recipe_creates_meal(self):
        rid = self._seed_recipe()
        bid = self._seed_batch(rid, "2026-05-14")
        r1  = self.client.post("/meals/start", json={
            "meal_type": "lunch", "query": "veggie", "meal_date": "2026-05-14",
        })
        skey = r1.json()["session_key"]
        r2   = self.client.post("/meals/select-recipe", json={
            "session_key":       skey,
            "recipe_id":         rid,
            "fraction_of_batch": 0.5,
        })
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r2.json()["meal_type"], "lunch")
        self.assertAlmostEqual(r2.json()["fraction_of_batch"], 0.5)

    def test_select_recipe_no_batch_returns_404(self):
        rid = self._seed_recipe()
        # No batch created
        r1  = self.client.post("/meals/start", json={
            "meal_type": "dinner", "query": "veggie",
        })
        skey = r1.json()["session_key"]
        r2   = self.client.post("/meals/select-recipe", json={
            "session_key": skey, "recipe_id": rid, "fraction_of_batch": 0.5,
        })
        self.assertEqual(r2.status_code, 404)

    def test_standalone_meal_flow(self):
        db.create_ingredient(self.conn, "Apple",
                              portion_unit="medium", portion_grams=182.0, calories=95)
        self.conn.commit()
        r1   = self.client.post("/meals/start", json={
            "meal_type": "morning_snack", "query": "apple",
        })
        skey = r1.json()["session_key"]
        r2   = self.client.post(f"/meals/start-standalone?session_key={skey}")
        self.assertEqual(r2.status_code, 201)
        r3   = self.client.post(f"/meals/{skey}/ingredients", json={
            "ingredient_name": "Apple", "quantity_multiple": 1.0,
        })
        self.assertEqual(r3.json()["status"], "added")
        r4   = self.client.post(f"/meals/{skey}/finish")
        self.assertEqual(r4.status_code, 200)

    def test_invalid_meal_type_returns_422(self):
        r = self.client.post("/meals/start", json={
            "meal_type": "brunch", "query": "eggs",
        })
        self.assertEqual(r.status_code, 422)

    def test_fraction_out_of_range_returns_422(self):
        rid = self._seed_recipe()
        self._seed_batch(rid, "2026-05-14")
        r1  = self.client.post("/meals/start", json={
            "meal_type": "lunch", "query": "veggie", "meal_date": "2026-05-14",
        })
        skey = r1.json()["session_key"]
        r2   = self.client.post("/meals/select-recipe", json={
            "session_key": skey, "recipe_id": rid, "fraction_of_batch": 2.0,
        })
        self.assertEqual(r2.status_code, 422)

    def test_get_meal(self):
        mid = db.create_meal(self.conn, "breakfast", "2026-05-14")
        self.conn.commit()
        r = self.client.get(f"/meals/{mid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["meal_type"], "breakfast")

    def test_get_meal_not_found(self):
        r = self.client.get("/meals/9999")
        self.assertEqual(r.status_code, 404)


# ===========================================================================
# Nutrition
# ===========================================================================

class TestNutritionEndpoints(BaseAPITest):

    def _seed_full_day(self, date="2026-05-14"):
        # Reuse existing recipe if already seeded, otherwise create it
        existing = db.search_recipes(self.conn, "Veggie Bowl")
        if existing:
            rid = existing[0]["recipe_id"]
        else:
            rid = self._seed_recipe()
        bid = self._seed_batch(rid, date)
        db.create_meal(self.conn, "lunch", date,
                       batch_id=bid, fraction_of_batch=0.5)
        self.conn.commit()

    def test_daily_nutrition(self):
        self._seed_full_day()
        r = self.client.get("/nutrition/daily?date=2026-05-14")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["date"], "2026-05-14")
        self.assertEqual(len(data["meals"]), 1)
        self.assertIn("display", data["daily_totals"])

    def test_daily_nutrition_defaults_to_today(self):
        r = self.client.get("/nutrition/daily")
        self.assertEqual(r.status_code, 200)
        from datetime import date
        self.assertEqual(r.json()["date"], str(date.today()))

    def test_daily_nutrition_invalid_date(self):
        r = self.client.get("/nutrition/daily?date=not-a-date")
        self.assertEqual(r.status_code, 422)

    def test_daily_nutrition_empty_day(self):
        r = self.client.get("/nutrition/daily?date=2020-01-01")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["meals"], [])

    def test_range_nutrition(self):
        self._seed_full_day("2026-05-13")
        self._seed_full_day("2026-05-14")
        r = self.client.get(
            "/nutrition/range?start_date=2026-05-13&end_date=2026-05-14"
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["num_days"],  2)
        self.assertEqual(data["num_meals"], 2)
        self.assertIn("display", data["totals"])
        self.assertIn("display", data["daily_averages"])

    def test_range_nutrition_invalid_date_order(self):
        r = self.client.get(
            "/nutrition/range?start_date=2026-05-14&end_date=2026-05-01"
        )
        self.assertEqual(r.status_code, 422)

    def test_range_nutrition_bad_date_format(self):
        r = self.client.get(
            "/nutrition/range?start_date=not-a-date&end_date=2026-05-14"
        )
        self.assertEqual(r.status_code, 422)


# ===========================================================================
# Notes
# ===========================================================================

class TestNotesEndpoints(BaseAPITest):

    def test_add_note_to_recipe(self):
        rid = self._seed_recipe()
        r   = self.client.post("/notes", json={
            "note_txt":  "Add more seasoning.",
            "recipe_id": rid,
        })
        self.assertEqual(r.status_code, 201)
        self.assertIn("note_id", r.json())

    def test_add_note_to_batch(self):
        rid = self._seed_recipe()
        bid = self._seed_batch(rid)
        r   = self.client.post("/notes", json={
            "note_txt": "Used less salt today.",
            "batch_id": bid,
        })
        self.assertEqual(r.status_code, 201)

    def test_add_note_to_meal(self):
        mid = db.create_meal(self.conn, "dinner", "2026-05-14")
        self.conn.commit()
        r   = self.client.post("/notes", json={
            "note_txt": "Felt full.",
            "meal_id":  mid,
        })
        self.assertEqual(r.status_code, 201)

    def test_add_note_no_parent_returns_422(self):
        r = self.client.post("/notes", json={"note_txt": "Orphan note."})
        self.assertEqual(r.status_code, 422)

    def test_get_notes_for_recipe(self):
        rid = self._seed_recipe()
        db.add_note(self.conn, "Note 1", recipe_id=rid)
        db.add_note(self.conn, "Note 2", recipe_id=rid)
        self.conn.commit()
        r = self.client.get(f"/notes?recipe_id={rid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 2)

    def test_get_notes_no_parent_returns_422(self):
        r = self.client.get("/notes")
        self.assertEqual(r.status_code, 422)


# ===========================================================================
# Auth
# ===========================================================================

class TestAuth(BaseAPITest):

    def test_no_key_configured_allows_all(self):
        """With no FOOD_LOG_API_KEY set, all requests pass through."""
        with patch("dependencies._get_api_key_secret", return_value=None):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)

    def test_wrong_key_returns_401(self):
        app.dependency_overrides.clear()   # restore real auth
        app.dependency_overrides[dependencies.get_db] = lambda: self.conn
        with patch("dependencies._get_api_key_secret", return_value="secret123"):
            r = self.client.get(
                "/health", headers={"X-Api-Key": "wrongkey"}
            )
        self.assertEqual(r.status_code, 401)

    def test_correct_key_passes(self):
        app.dependency_overrides.clear()
        app.dependency_overrides[dependencies.get_db] = lambda: self.conn
        with patch("dependencies._get_api_key_secret", return_value="secret123"):
            r = self.client.get(
                "/health", headers={"X-Api-Key": "secret123"}
            )
        self.assertEqual(r.status_code, 200)


# ===========================================================================
# Models validation
# ===========================================================================

class TestModelValidation(unittest.TestCase):
    """Test Pydantic model validation without needing the full app."""

    def test_recipe_request_empty_name_raises(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            from models import RecipeRequest
            RecipeRequest(recipe_name="")

    def test_batch_modify_remove_requires_component_id(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            from models import BatchModifyRequest
            BatchModifyRequest(action="remove")   # missing component_id

    def test_batch_modify_add_requires_ingredient_name(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            from models import BatchModifyRequest
            BatchModifyRequest(action="add", quantity_multiple=1.0)  # missing name

    def test_note_request_requires_parent(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            from models import NoteRequest
            NoteRequest(note_txt="Orphan")

    def test_meal_start_invalid_type(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            from models import MealStartRequest
            MealStartRequest(meal_type="brunch", query="eggs")

    def test_meal_start_invalid_date_format(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            from models import MealStartRequest
            MealStartRequest(meal_type="lunch", query="salad", meal_date="05/14/2026")

    def test_ingredient_confirm_needs_choice_or_manual(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            from models import IngredientConfirmRequest
            IngredientConfirmRequest(pending_key="oats")  # neither choice nor manual


# ===========================================================================
# Runner
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{'═' * 60}")
    print("  Food Log REST API — Tests")
    print(f"{'═' * 60}\n")

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [
        TestHealth,
        TestRecipeEndpoints,
        TestBatchEndpoints,
        TestMealEndpoints,
        TestNutritionEndpoints,
        TestNotesEndpoints,
        TestAuth,
        TestModelValidation,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
