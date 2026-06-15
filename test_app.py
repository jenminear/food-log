"""
test_app.py — Tests for the application logic layer (app.py)
=============================================================
All tests use an in-memory SQLite database and mock nutrition_lookup
so no network calls are made.

Run with:  python test_app.py
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import db
import app
import nutrition_lookup as NL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).with_name("food_log_schema.sql")).read_text()
    conn.executescript(schema)
    return conn


def _make_nl_result(name="Rolled Oats", confidence=0.92, **kwargs) -> NL.NutritionResult:
    defaults = dict(
        ingredient_name=name,
        source="usda",
        source_id="173904",
        source_url="https://fdc.nal.usda.gov/fdc-app.html#/food-details/173904/nutrients",
        portion_unit="1 cup",
        portion_grams=90.0,
        calories=379.0,
        protein_grams=13.15,
        fat_grams=6.52,
        carb_grams=67.7,
        fiber_grams=10.1,
        confidence=confidence,
    )
    defaults.update(kwargs)
    return NL.NutritionResult(**defaults)


def _seed_recipe_with_ingredients(conn) -> tuple[int, int, int]:
    """Create a recipe with two ingredients. Returns (recipe_id, iid1, iid2)."""
    rid  = db.create_recipe(conn, "Veggie Bowl")
    iid1 = db.create_ingredient(conn, "Brown Rice",
                                 portion_unit="g", portion_grams=100.0,
                                 calories=112, protein_grams=2.6,
                                 fat_grams=0.9, carb_grams=23.0, fiber_grams=1.8)
    iid2 = db.create_ingredient(conn, "Broccoli",
                                 portion_unit="cup", portion_grams=91.0,
                                 calories=34, protein_grams=2.8,
                                 fat_grams=0.4, carb_grams=7.0, fiber_grams=2.6)
    db.add_component(conn, iid1, 2.0, recipe_id=rid)
    db.add_component(conn, iid2, 1.5, recipe_id=rid)
    conn.commit()
    return rid, iid1, iid2


# ===========================================================================
# Flow 1: Add Recipe
# ===========================================================================

class TestAddRecipe(unittest.TestCase):

    def test_creates_recipe_record(self):
        conn = make_conn()
        session = app.add_recipe(conn, "Lentil Soup", num_servings=6, vegan=True)
        self.assertIsInstance(session, app.AddRecipeSession)
        row = db.get_recipe(conn, session.recipe_id)
        self.assertEqual(row["recipe_name"], "Lentil Soup")
        self.assertEqual(row["vegan"], 1)

    def test_duplicate_recipe_raises(self):
        conn = make_conn()
        app.add_recipe(conn, "Pasta")
        with self.assertRaises(db.DuplicateError):
            app.add_recipe(conn, "Pasta")

    def test_add_ingredient_existing_in_db(self):
        """If ingredient already exists, no lookup needed — added immediately."""
        conn = make_conn()
        db.create_ingredient(conn, "Rolled Oats",
                              portion_unit="cup", portion_grams=90.0, calories=379)
        conn.commit()
        session = app.add_recipe(conn, "Porridge")
        result = session.add_ingredient("Rolled Oats", 1.0)
        self.assertEqual(result["status"], "added")
        self.assertIsNotNone(result["ingredient_id"])
        self.assertIsNotNone(result["component_id"])

    def test_add_ingredient_high_confidence_lookup(self):
        """High confidence lookup → auto-added, no confirmation needed."""
        conn = make_conn()
        mock_result = _make_nl_result("Rolled Oats", confidence=0.92)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.add_recipe(conn, "Porridge")
            result = session.add_ingredient("oats", 1.5)
        self.assertEqual(result["status"], "added")
        self.assertIsNotNone(result["ingredient_id"])

    def test_add_ingredient_low_confidence_needs_confirmation(self):
        """Low confidence lookup → returns candidates for user to choose."""
        conn = make_conn()
        mock_result = _make_nl_result("Oat Bran", confidence=0.35)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.add_recipe(conn, "Oat Bowl")
            result = session.add_ingredient("oat stuff", 1.0)
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertIsNotNone(result["candidates"])
        self.assertIsNotNone(result["pending_key"])

    def test_add_ingredient_no_results(self):
        """No lookup results → status not_found."""
        conn = make_conn()
        with patch("nutrition_lookup.lookup", return_value=[]):
            session = app.add_recipe(conn, "Mystery Bowl")
            result = session.add_ingredient("xyzunknown", 1.0)
        self.assertEqual(result["status"], "not_found")

    def test_confirm_ingredient_valid_choice(self):
        """After needs_confirmation, user picks candidate #1."""
        conn = make_conn()
        mock_result = _make_nl_result("Oat Bran", confidence=0.35)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.add_recipe(conn, "Oat Bowl")
            result = session.add_ingredient("oat bran", 1.0)
        self.assertEqual(result["status"], "needs_confirmation")

        confirmed = session.confirm_ingredient(
            result["pending_key"], choice=1
        )
        self.assertEqual(confirmed["status"], "added")
        self.assertIsNotNone(confirmed["ingredient_id"])

    def test_confirm_ingredient_out_of_range(self):
        conn = make_conn()
        mock_result = _make_nl_result("Oat Bran", confidence=0.35)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.add_recipe(conn, "Oat Bowl")
            result = session.add_ingredient("oat bran", 1.0)
        with self.assertRaises(db.ValidationError):
            session.confirm_ingredient(result["pending_key"], choice=99)

    def test_confirm_ingredient_manual_data(self):
        """User provides manual data instead of picking a candidate."""
        conn = make_conn()
        with patch("nutrition_lookup.lookup", return_value=[]):
            session = app.add_recipe(conn, "Custom Bowl")
            result = session.add_ingredient("mystery grain", 1.0)
        confirmed = session.confirm_ingredient(
            result["pending_key"],
            choice=None,
            manual_data={
                "ingredient_name": "Mystery Grain",
                "portion_unit":    "1 cup",
                "portion_grams":   120.0,
                "calories":        350.0,
                "protein_grams":   10.0,
                "fat_grams":       5.0,
                "carb_grams":      60.0,
                "fiber_grams":     8.0,
            },
        )
        self.assertEqual(confirmed["status"], "added")

    def test_add_note_to_recipe(self):
        conn = make_conn()
        session = app.add_recipe(conn, "Stew")
        nid = session.add_note("Add extra cumin next time.")
        self.assertGreater(nid, 0)
        notes = db.get_notes(conn, recipe_id=session.recipe_id)
        self.assertEqual(len(notes), 1)
        self.assertIn("cumin", notes[0]["note_txt"])

    def test_finish_returns_summary(self):
        conn = make_conn()
        db.create_ingredient(conn, "Lentils",
                              portion_unit="cup", portion_grams=192.0, calories=230)
        conn.commit()
        session = app.add_recipe(conn, "Lentil Soup")
        session.add_ingredient("Lentils", 2.0)
        summary = session.finish()
        self.assertEqual(summary["recipe_name"], "Lentil Soup")
        self.assertIn("Lentils", summary["ingredients_added"])
        self.assertEqual(summary["unresolved"], [])
        self.assertEqual(summary["warnings"], [])

    def test_finish_reports_unresolved(self):
        """Ingredients that were never confirmed appear in unresolved."""
        conn = make_conn()
        mock_result = _make_nl_result("Oat Bran", confidence=0.35)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.add_recipe(conn, "Partial Recipe")
            session.add_ingredient("oat bran", 1.0)   # never confirmed
        summary = session.finish()
        self.assertEqual(len(summary["unresolved"]), 1)
        self.assertEqual(len(summary["warnings"]), 1)

    def test_components_linked_to_recipe(self):
        """Confirmed ingredients appear as components on the recipe."""
        conn = make_conn()
        mock_result = _make_nl_result("Rolled Oats", confidence=0.92)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.add_recipe(conn, "Overnight Oats")
            session.add_ingredient("rolled oats", 1.0)
        session.finish()
        comps = db.get_components(conn, recipe_id=session.recipe_id)
        self.assertEqual(len(comps), 1)


# ===========================================================================
# Flow 2: Create Batch
# ===========================================================================

class TestCreateBatch(unittest.TestCase):

    def test_creates_batch_from_search(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        result = app.create_batch(conn, "Veggie Bowl")
        self.assertEqual(result["status"], "created")
        self.assertIsNotNone(result["batch_id"])
        self.assertEqual(result["recipe_name"], "Veggie Bowl")
        self.assertIsInstance(result["components"], list)
        self.assertEqual(len(result["components"]), 2)

    def test_not_found_returns_status(self):
        conn = make_conn()
        result = app.create_batch(conn, "nonexistent recipe xyz")
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["batch_id"])

    def test_ambiguous_returns_candidates(self):
        conn = make_conn()
        db.create_recipe(conn, "Lentil Soup Red")
        db.create_recipe(conn, "Lentil Soup Green")
        conn.commit()
        result = app.create_batch(conn, "Lentil Soup")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)

    def test_create_from_recipe_id(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        result = app.create_batch_from_recipe_id(conn, rid)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["recipe_id"], rid)

    def test_batch_date_defaults_to_today(self):
        conn = make_conn()
        _seed_recipe_with_ingredients(conn)
        result = app.create_batch(conn, "Veggie Bowl")
        from datetime import date
        self.assertEqual(result["batch_date"], str(date.today()))

    def test_modify_batch_remove(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        batch_result = app.create_batch(conn, "Veggie Bowl")
        bid = batch_result["batch_id"]
        comp_id = batch_result["components"][0]["component_id"]

        result = app.modify_batch_ingredient(
            conn, bid, "remove", component_id=comp_id
        )
        self.assertEqual(result["status"], "modified")
        self.assertEqual(len(result["components"]), 1)

    def test_modify_batch_update_quantity(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        batch_result = app.create_batch(conn, "Veggie Bowl")
        bid = batch_result["batch_id"]
        comp_id = batch_result["components"][0]["component_id"]

        result = app.modify_batch_ingredient(
            conn, bid, "update_quantity",
            component_id=comp_id, quantity_multiple=3.0
        )
        self.assertEqual(result["status"], "modified")
        # After the first modification, component_id is now a batch-level id;
        # verify by checking that one component has quantity_multiple == 3.0
        quantities = [c["quantity_multiple"] for c in result["components"]]
        self.assertIn(3.0, quantities)

    def test_modify_batch_add_existing_ingredient(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        db.create_ingredient(conn, "Chickpeas",
                              portion_unit="cup", portion_grams=164.0, calories=269)
        conn.commit()
        batch_result = app.create_batch(conn, "Veggie Bowl")
        bid = batch_result["batch_id"]

        result = app.modify_batch_ingredient(
            conn, bid, "add",
            ingredient_name="Chickpeas", quantity_multiple=1.0
        )
        self.assertEqual(result["status"], "modified")
        self.assertEqual(len(result["components"]), 3)

    def test_modify_batch_add_new_ingredient_needs_confirmation(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        batch_result = app.create_batch(conn, "Veggie Bowl")
        bid = batch_result["batch_id"]
        mock_result = _make_nl_result("Tahini", confidence=0.45)

        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            result = app.modify_batch_ingredient(
                conn, bid, "add",
                ingredient_name="tahini", quantity_multiple=2.0
            )
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertIsNotNone(result["candidates"])

    def test_modify_batch_invalid_action(self):
        conn = make_conn()
        _seed_recipe_with_ingredients(conn)
        batch_result = app.create_batch(conn, "Veggie Bowl")
        with self.assertRaises(db.ValidationError):
            app.modify_batch_ingredient(conn, batch_result["batch_id"], "explode")

    def test_add_batch_note(self):
        conn = make_conn()
        _seed_recipe_with_ingredients(conn)
        batch_result = app.create_batch(conn, "Veggie Bowl")
        bid = batch_result["batch_id"]
        nid = app.add_batch_note(conn, bid, "Used less salt today.")
        self.assertGreater(nid, 0)
        notes = db.get_notes(conn, batch_id=bid)
        self.assertEqual(len(notes), 1)


# ===========================================================================
# Flow 3: Record Meal
# ===========================================================================

class TestRecordMeal(unittest.TestCase):

    def test_record_meal_returns_session(self):
        conn = make_conn()
        session = app.record_meal(conn, "lunch", "veggie bowl")
        self.assertIsInstance(session, app.RecordMealSession)

    def test_search_results_populated(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        session = app.record_meal(conn, "lunch", "veggie")
        self.assertIn("recipes", session.search_results)
        self.assertGreater(len(session.search_results["recipes"]), 0)

    def test_select_recipe_batch_meal(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        bid = db.create_batch(conn, rid, "2026-05-14")
        conn.commit()
        session = app.record_meal(conn, "lunch", "veggie bowl",
                                  meal_date="2026-05-14")
        result = session.select_recipe(rid, fraction_of_batch=0.5)
        self.assertEqual(result["status"], "created")
        self.assertIsNotNone(result["meal_id"])
        self.assertEqual(result["batch_id"], bid)
        self.assertAlmostEqual(result["fraction_of_batch"], 0.5)

    def test_select_recipe_no_batch_raises(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        # No batch created
        session = app.record_meal(conn, "dinner", "veggie bowl")
        with self.assertRaises(db.NotFoundError):
            session.select_recipe(rid, fraction_of_batch=0.5)

    def test_standalone_meal_flow(self):
        conn = make_conn()
        db.create_ingredient(conn, "Apple",
                              portion_unit="medium", portion_grams=182.0, calories=95)
        conn.commit()
        session = app.record_meal(conn, "morning_snack", "apple")
        started = session.start_standalone()
        self.assertEqual(started["status"], "created")

        result = session.add_ingredient("Apple", 1.0)
        self.assertEqual(result["status"], "added")

    def test_add_ingredient_before_start_raises(self):
        conn = make_conn()
        session = app.record_meal(conn, "morning_snack", "apple")
        with self.assertRaises(db.ValidationError):
            session.add_ingredient("Apple", 1.0)

    def test_standalone_meal_with_lookup(self):
        conn = make_conn()
        mock_result = _make_nl_result("Banana", confidence=0.90,
                                       portion_unit="medium", portion_grams=118.0,
                                       calories=89)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.record_meal(conn, "afternoon_snack", "banana")
            session.start_standalone()
            result = session.add_ingredient("banana", 1.0)
        self.assertEqual(result["status"], "added")

    def test_standalone_meal_low_confidence_needs_confirmation(self):
        conn = make_conn()
        mock_result = _make_nl_result("Some Grain", confidence=0.30)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.record_meal(conn, "lunch", "grain")
            session.start_standalone()
            result = session.add_ingredient("grain", 1.0)
        self.assertEqual(result["status"], "needs_confirmation")

    def test_confirm_ingredient_in_meal(self):
        conn = make_conn()
        mock_result = _make_nl_result("Quinoa", confidence=0.40)
        with patch("nutrition_lookup.lookup", return_value=[mock_result]):
            session = app.record_meal(conn, "lunch", "quinoa")
            session.start_standalone()
            pend = session.add_ingredient("quinoa", 1.0)

        confirmed = session.confirm_ingredient(
            "quinoa", 1.0, [mock_result], choice=1
        )
        self.assertEqual(confirmed["status"], "added")

    def test_add_meal_note(self):
        conn = make_conn()
        session = app.record_meal(conn, "dinner", "pasta")
        session.start_standalone()
        nid = session.add_note("Felt satisfied after this.")
        self.assertGreater(nid, 0)

    def test_finish_returns_summary(self):
        conn = make_conn()
        session = app.record_meal(conn, "breakfast", "eggs")
        session.start_standalone()
        summary = session.finish()
        self.assertIsNotNone(summary["meal_id"])
        self.assertEqual(summary["meal_type"], "breakfast")

    def test_invalid_meal_type_raises(self):
        conn = make_conn()
        session = app.record_meal(conn, "brunch", "toast")
        with self.assertRaises(db.ValidationError):
            session.start_standalone()

    def test_fraction_out_of_range_raises(self):
        conn = make_conn()
        rid, _, _ = _seed_recipe_with_ingredients(conn)
        db.create_batch(conn, rid, "2026-05-14")
        conn.commit()
        session = app.record_meal(conn, "lunch", "veggie bowl",
                                  meal_date="2026-05-14")
        with self.assertRaises(db.ValidationError):
            session.select_recipe(rid, fraction_of_batch=1.5)


# ===========================================================================
# Flow 4: Daily Nutrition
# ===========================================================================

class TestDailyNutrition(unittest.TestCase):

    def _seed_day(self, conn, date="2026-05-14"):
        rid, iid1, iid2 = _seed_recipe_with_ingredients(conn)
        bid = db.create_batch(conn, rid, date)
        db.create_meal(conn, "lunch", date, batch_id=bid, fraction_of_batch=0.5)
        conn.commit()

    def test_returns_report_for_date(self):
        conn = make_conn()
        self._seed_day(conn)
        report = app.get_daily_nutrition(conn, "2026-05-14")
        self.assertEqual(report["date"], "2026-05-14")
        self.assertEqual(len(report["meals"]), 1)

    def test_display_strings_added(self):
        conn = make_conn()
        self._seed_day(conn)
        report = app.get_daily_nutrition(conn, "2026-05-14")
        display = report["daily_totals"]["display"]
        self.assertIn("kcal", display["calories"])
        self.assertIn("protein", display["protein_grams"])

    def test_none_nutrition_displays_dash(self):
        """Ingredients without nutrition data show '—' not a crash."""
        conn = make_conn()
        rid = db.create_recipe(conn, "Mystery Stew")
        iid = db.create_ingredient(conn, "Unknown Herb",
                                    portion_unit="tsp", portion_grams=1.0)
        db.add_component(conn, iid, 1.0, recipe_id=rid)
        bid = db.create_batch(conn, rid, "2026-05-14")
        db.create_meal(conn, "dinner", "2026-05-14",
                       batch_id=bid, fraction_of_batch=1.0)
        conn.commit()
        report = app.get_daily_nutrition(conn, "2026-05-14")
        display = report["daily_totals"]["display"]
        self.assertEqual(display["calories"], "—")

    def test_empty_date_returns_empty_meals(self):
        conn = make_conn()
        report = app.get_daily_nutrition(conn, "2020-01-01")
        self.assertEqual(report["meals"], [])

    def test_defaults_to_today(self):
        conn = make_conn()
        from datetime import date
        report = app.get_daily_nutrition(conn)
        self.assertEqual(report["date"], str(date.today()))


# ===========================================================================
# Flow 5: Aggregate Nutrition
# ===========================================================================

class TestAggregateNutrition(unittest.TestCase):

    def _seed_two_days(self, conn):
        rid, iid1, iid2 = _seed_recipe_with_ingredients(conn)
        for date in ("2026-05-13", "2026-05-14"):
            bid = db.create_batch(conn, rid, date)
            db.create_meal(conn, "lunch", date,
                           batch_id=bid, fraction_of_batch=1.0)
        conn.commit()

    def test_returns_aggregate_report(self):
        conn = make_conn()
        self._seed_two_days(conn)
        report = app.get_aggregate_nutrition(conn, "2026-05-13", "2026-05-14")
        self.assertEqual(report["num_days"],  2)
        self.assertEqual(report["num_meals"], 2)

    def test_display_strings_on_totals(self):
        conn = make_conn()
        self._seed_two_days(conn)
        report = app.get_aggregate_nutrition(conn, "2026-05-13", "2026-05-14")
        self.assertIn("kcal", report["totals"]["display"]["calories"])
        self.assertIn("kcal", report["daily_averages"]["display"]["calories"])

    def test_daily_averages_are_half_totals(self):
        conn = make_conn()
        self._seed_two_days(conn)
        report = app.get_aggregate_nutrition(conn, "2026-05-13", "2026-05-14")
        if report["totals"]["calories"] is not None:
            self.assertAlmostEqual(
                report["daily_averages"]["calories"],
                report["totals"]["calories"] / 2,
                places=2,
            )

    def test_invalid_date_range_raises(self):
        conn = make_conn()
        with self.assertRaises(db.ValidationError):
            app.get_aggregate_nutrition(conn, "2026-05-14", "2026-05-01")


# ===========================================================================
# Notes
# ===========================================================================

class TestAddNote(unittest.TestCase):

    def test_add_note_to_recipe(self):
        conn = make_conn()
        rid = db.create_recipe(conn, "Chili")
        result = app.add_note(conn, "Use dried chipotle.", recipe_id=rid)
        self.assertIn("note_id", result)
        self.assertGreater(result["note_id"], 0)

    def test_add_note_to_batch(self):
        conn = make_conn()
        rid = db.create_recipe(conn, "Chili")
        bid = db.create_batch(conn, rid, "2026-05-14")
        conn.commit()
        result = app.add_note(conn, "Added extra beans.", batch_id=bid)
        self.assertGreater(result["note_id"], 0)

    def test_add_note_to_meal(self):
        conn = make_conn()
        mid = db.create_meal(conn, "dinner", "2026-05-14")
        conn.commit()
        result = app.add_note(conn, "Felt full.", meal_id=mid)
        self.assertGreater(result["note_id"], 0)

    def test_note_without_parent_raises(self):
        conn = make_conn()
        with self.assertRaises(db.ValidationError):
            app.add_note(conn, "Orphan note.")


# ===========================================================================
# Formatting helpers
# ===========================================================================

class TestFormatHelpers(unittest.TestCase):

    def test_format_nutrition_all_present(self):
        nutrition = {
            "calories": 310.4, "protein_grams": 18.3,
            "fat_grams": 7.8,  "carb_grams": 44.5, "fiber_grams": 6.1,
        }
        display = app._format_nutrition(nutrition)
        self.assertEqual(display["calories"],      "310 kcal")
        self.assertEqual(display["protein_grams"], "18.3g protein")
        self.assertEqual(display["fat_grams"],     "7.8g fat")
        self.assertEqual(display["carb_grams"],    "44.5g carbs")
        self.assertEqual(display["fiber_grams"],   "6.1g fiber")

    def test_format_nutrition_none_shows_dash(self):
        nutrition = {"calories": None, "protein_grams": None,
                     "fat_grams": None, "carb_grams": None, "fiber_grams": None}
        display = app._format_nutrition(nutrition)
        for v in display.values():
            self.assertEqual(v, "—")

    def test_format_components_returns_list_of_dicts(self):
        conn = make_conn()
        rid, iid1, _ = _seed_recipe_with_ingredients(conn)
        comps = db.get_components(conn, recipe_id=rid)
        formatted = app._format_components(comps)
        self.assertIsInstance(formatted, list)
        self.assertIsInstance(formatted[0], dict)
        self.assertIn("ingredient_name", formatted[0])
        self.assertIn("quantity_multiple", formatted[0])


# ===========================================================================
# End-to-end scenario: full recipe → batch → meal → report
# ===========================================================================

class TestEndToEnd(unittest.TestCase):

    def test_full_flow(self):
        """
        Add a recipe with two ingredients, create a batch, record a meal,
        check the daily report. Everything should link up correctly.
        """
        conn = make_conn()

        # 1. Add recipe
        session = app.add_recipe(
            conn, "Simple Stir Fry",
            num_servings=4, total_time_mins=30,
        )
        # Pre-seed both ingredients so no lookup needed
        db.create_ingredient(conn, "Tofu",
                              portion_unit="g", portion_grams=100.0,
                              calories=76, protein_grams=8.0,
                              fat_grams=4.0, carb_grams=2.0, fiber_grams=0.3)
        db.create_ingredient(conn, "Bok Choy",
                              portion_unit="cup", portion_grams=70.0,
                              calories=9, protein_grams=1.1,
                              fat_grams=0.1, carb_grams=1.5, fiber_grams=0.7)
        conn.commit()

        r1 = session.add_ingredient("Tofu",     quantity_multiple=3.0)
        r2 = session.add_ingredient("Bok Choy", quantity_multiple=2.0)
        self.assertEqual(r1["status"], "added")
        self.assertEqual(r2["status"], "added")
        summary = session.finish()
        self.assertEqual(len(summary["ingredients_added"]), 2)

        # 2. Create batch
        batch_result = app.create_batch(conn, "Simple Stir Fry",
                                         batch_date="2026-05-14")
        self.assertEqual(batch_result["status"], "created")
        bid = batch_result["batch_id"]

        # 3. Record meal (50% of the batch)
        meal_session = app.record_meal(conn, "dinner", "stir fry",
                                        meal_date="2026-05-14")
        meal_result = meal_session.select_recipe(
            session.recipe_id, fraction_of_batch=0.5
        )
        self.assertEqual(meal_result["status"], "created")
        meal_session.add_note("Very tasty — add more ginger next time.")
        meal_session.finish()

        # 4. Daily nutrition
        report = app.get_daily_nutrition(conn, "2026-05-14")
        self.assertEqual(len(report["meals"]), 1)
        meal = report["meals"][0]
        self.assertEqual(meal["source"], "batch")

        # Tofu: 3.0 * (100/100) * 76 * 0.5 = 114 kcal
        # Bok choy: 2.0 * (70/100) * 9 * 0.5 = 6.3 kcal
        # Total: 120.3 kcal
        self.assertAlmostEqual(meal["nutrition"]["calories"], 120.3, places=1)
        self.assertAlmostEqual(
            report["daily_totals"]["calories"], 120.3, places=1
        )
        self.assertIn("kcal", report["daily_totals"]["display"]["calories"])


# ===========================================================================
# Runner
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{'═' * 60}")
    print("  App Logic Layer — Tests")
    print(f"{'═' * 60}\n")

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [
        TestAddRecipe,
        TestCreateBatch,
        TestRecordMeal,
        TestDailyNutrition,
        TestAggregateNutrition,
        TestAddNote,
        TestFormatHelpers,
        TestEndToEnd,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
