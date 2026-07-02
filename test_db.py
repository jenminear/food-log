"""
test_db.py — Tests for the Food Log data access layer
======================================================
Run with:  python test_db.py
Uses an in-memory SQLite database so it leaves no files behind.
"""

import sqlite3
import sys
import time
import traceback
from pathlib import Path

# Patch DB_PATH before importing db so it uses in-memory db
import db as D

# ── helpers ────────────────────────────────────────────────────────────────

def make_conn() -> sqlite3.Connection:
    """Fresh in-memory database with schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).with_name("food_log_schema.sql")).read_text()
    conn.executescript(schema)
    return conn


PASS = "✓"
FAIL = "✗"
results = []

def test(name: str, fn):
    try:
        fn()
        print(f"  {PASS}  {name}")
        results.append((name, True, None))
    except Exception as e:
        print(f"  {FAIL}  {name}")
        print(f"       {type(e).__name__}: {e}")
        results.append((name, False, e))


# ── recipe tests ────────────────────────────────────────────────────────────

def test_create_recipe():
    conn = make_conn()
    rid = D.create_recipe(conn, "Lentil Soup",
                          num_servings=6, active_time_mins=20,
                          total_time_mins=60, vegan=True)
    assert isinstance(rid, int) and rid > 0
    row = D.get_recipe(conn, rid)
    assert row["recipe_name"] == "Lentil Soup"
    assert row["vegan"] == 1
    assert row["active_time_mins"] == 20

def test_duplicate_recipe():
    conn = make_conn()
    D.create_recipe(conn, "Pasta")
    try:
        D.create_recipe(conn, "pasta")   # case-insensitive duplicate
        assert False, "Should have raised DuplicateError"
    except D.DuplicateError:
        pass

def test_search_recipes():
    conn = make_conn()
    D.create_recipe(conn, "Lentil Soup")
    D.create_recipe(conn, "Tomato Soup")
    D.create_recipe(conn, "Lentil Curry")
    results = D.search_recipes(conn, "lentil")
    assert len(results) == 2
    results2 = D.search_recipes(conn, "lentil soup")
    assert len(results2) == 1

def test_update_recipe():
    conn = make_conn()
    rid = D.create_recipe(conn, "Oatmeal")
    D.update_recipe(conn, rid, num_servings=2, need_oven=False)
    row = D.get_recipe(conn, rid)
    assert row["num_servings"] == 2

def test_get_recipe_not_found():
    conn = make_conn()
    try:
        D.get_recipe(conn, 9999)
        assert False
    except D.NotFoundError:
        pass


# ── ingredient tests ────────────────────────────────────────────────────────

def test_create_ingredient():
    conn = make_conn()
    iid = D.create_ingredient(conn, "Oats", "g",
                               protein_grams=17, calories=389)
    assert iid > 0
    row = D.find_ingredient_by_name(conn, "oats")  # case-insensitive
    assert row is not None
    assert row["calories"] == 389

def test_get_ingredient():
    conn = make_conn()
    iid = D.create_ingredient(conn, "Oats", "g", protein_grams=17, calories=389)
    row = D.get_ingredient(conn, iid)
    assert row["ingredient_id"] == iid
    assert row["ingredient_name"] == "Oats"
    assert row["calories"] == 389

def test_get_ingredient_not_found():
    conn = make_conn()
    try:
        D.get_ingredient(conn, 9999)
        assert False, "expected NotFoundError"
    except D.NotFoundError:
        pass

def test_find_or_create_ingredient():
    conn = make_conn()
    iid1, created1 = D.find_or_create_ingredient(conn, "Milk", "ml",
                                                   protein_grams=8, calories=150)
    assert created1 is True
    iid2, created2 = D.find_or_create_ingredient(conn, "Milk", "ml")
    assert created2 is False
    assert iid1 == iid2

def test_update_ingredient_nutrition():
    conn = make_conn()
    iid = D.create_ingredient(conn, "Honey", "g")
    D.update_ingredient_nutrition(conn, iid, calories=64, carb_grams=17)
    row = conn.execute(
        "SELECT * FROM ingredients WHERE ingredient_id = ?", (iid,)
    ).fetchone()
    assert row["calories"] == 64

def test_search_ingredients():
    conn = make_conn()
    D.create_ingredient(conn, "Almond Flour", "g")
    D.create_ingredient(conn, "Almond Milk", "ml")
    D.create_ingredient(conn, "Oat Flour", "g")
    r = D.search_ingredients(conn, "almond")
    assert len(r) == 2


# ── component tests ─────────────────────────────────────────────────────────

def test_add_and_get_components():
    conn = make_conn()
    rid = D.create_recipe(conn, "Porridge")
    iid = D.create_ingredient(conn, "Oats", "g", calories=389)
    cid = D.add_component(conn, iid, 1.5, recipe_id=rid)
    assert cid > 0
    comps = D.get_components(conn, recipe_id=rid)
    assert len(comps) == 1
    assert comps[0]["quantity_multiple"] == 1.5

def test_component_requires_one_parent():
    conn = make_conn()
    iid = D.create_ingredient(conn, "Butter", "g")
    try:
        D.add_component(conn, iid, 1.0)  # no parent
        assert False
    except D.ValidationError:
        pass

def test_remove_component():
    conn = make_conn()
    rid = D.create_recipe(conn, "Toast")
    iid = D.create_ingredient(conn, "Bread", "g")
    cid = D.add_component(conn, iid, 2.0, recipe_id=rid)
    D.remove_component(conn, cid)
    assert D.get_components(conn, recipe_id=rid) == []

def test_update_component_quantity():
    conn = make_conn()
    rid = D.create_recipe(conn, "Scrambled Eggs")
    iid = D.create_ingredient(conn, "Eggs", "g")
    cid = D.add_component(conn, iid, 2.0, recipe_id=rid)
    D.update_component_quantity(conn, cid, 3.0)
    comps = D.get_components(conn, recipe_id=rid)
    assert comps[0]["quantity_multiple"] == 3.0


# ── batch tests ─────────────────────────────────────────────────────────────

def test_create_batch():
    conn = make_conn()
    rid = D.create_recipe(conn, "Chili")
    bid = D.create_batch(conn, rid, "2026-05-01")
    assert bid > 0
    batch = D.get_batch(conn, bid)
    assert batch["recipe_name"] == "Chili"
    assert batch["recipe_changes"] == 0

def test_get_latest_batch():
    conn = make_conn()
    rid = D.create_recipe(conn, "Stew")
    D.create_batch(conn, rid, "2026-04-01")
    bid2 = D.create_batch(conn, rid, "2026-05-01")
    latest = D.get_latest_batch_for_recipe(conn, rid)
    assert latest["batch_id"] == bid2

def test_batch_ingredient_modification():
    conn = make_conn()
    rid = D.create_recipe(conn, "Granola")
    iid_oats  = D.create_ingredient(conn, "Rolled Oats", "g", calories=389)
    iid_honey = D.create_ingredient(conn, "Maple Syrup", "ml", calories=52)
    D.add_component(conn, iid_oats,  3.0, recipe_id=rid)
    D.add_component(conn, iid_honey, 2.0, recipe_id=rid)

    bid = D.create_batch(conn, rid, "2026-05-10")
    assert D.get_batch(conn, bid)["recipe_changes"] == 0

    # Adding an ingredient should trigger component copy
    iid_nuts = D.create_ingredient(conn, "Walnuts", "g", calories=196)
    D.add_batch_ingredient(conn, bid, iid_nuts, 1.5)
    assert D.get_batch(conn, bid)["recipe_changes"] == 1

    # Batch should now have 3 components (2 copied + 1 new)
    comps = D.get_components(conn, batch_id=bid)
    assert len(comps) == 3

def test_copy_recipe_components_to_batch():
    conn = make_conn()
    rid = D.create_recipe(conn, "Smoothie")
    iid1 = D.create_ingredient(conn, "Banana", "g", calories=105)
    iid2 = D.create_ingredient(conn, "Spinach", "g", calories=7)
    D.add_component(conn, iid1, 1.0, recipe_id=rid)
    D.add_component(conn, iid2, 1.0, recipe_id=rid)
    bid = D.create_batch(conn, rid, "2026-05-12")
    mapping = D.copy_recipe_components_to_batch(conn, rid, bid)
    assert len(mapping) == 2
    comps = D.get_components(conn, batch_id=bid)
    assert len(comps) == 2


def test_copy_recipe_components_to_batch_handles_duplicate_ingredient():
    """
    Regression test: an ingredient listed twice in a recipe (e.g. "water"
    added as two separate components) must map to two distinct batch-level
    component_ids, not collapse to the same one. Previously,
    _resolve_batch_component_id re-derived the new id by matching on
    ingredient_id alone, which always resolved to the same row for both
    duplicates and broke deleting/editing the second occurrence.
    """
    conn = make_conn()
    rid = D.create_recipe(conn, "Soup")
    iid_water = D.create_ingredient(conn, "Water", "g", calories=0)
    cid1 = D.add_component(conn, iid_water, 200.0, recipe_id=rid)
    cid2 = D.add_component(conn, iid_water, 300.0, recipe_id=rid)
    bid = D.create_batch(conn, rid, "2026-06-01")

    mapping = D.copy_recipe_components_to_batch(conn, rid, bid)
    assert len(mapping) == 2
    assert mapping[cid1] != mapping[cid2]

    comps = {c["component_id"]: c for c in D.get_components(conn, batch_id=bid)}
    assert comps[mapping[cid1]]["quantity_multiple"] == 200.0
    assert comps[mapping[cid2]]["quantity_multiple"] == 300.0


# ── meal tests ──────────────────────────────────────────────────────────────

def test_create_batch_meal():
    conn = make_conn()
    rid = D.create_recipe(conn, "Bean Soup")
    iid = D.create_ingredient(conn, "Black Beans", "g", calories=132)
    D.add_component(conn, iid, 4.0, recipe_id=rid)
    bid = D.create_batch(conn, rid, "2026-05-14")
    mid = D.create_meal(conn, "lunch", "2026-05-14",
                        batch_id=bid, fraction_of_batch=0.25)
    assert mid > 0
    meal = D.get_meal(conn, mid)
    assert meal["fraction_of_batch"] == 0.25

def test_create_ingredient_only_meal():
    conn = make_conn()
    iid = D.create_ingredient(conn, "Apple", "g", calories=95)
    mid = D.create_meal(conn, "morning_snack", "2026-05-14")
    D.add_meal_ingredient(conn, mid, iid, 1.0)
    comps = D.get_components(conn, meal_id=mid)
    assert len(comps) == 1

def test_invalid_meal_type():
    conn = make_conn()
    try:
        D.create_meal(conn, "brunch", "2026-05-14")
        assert False
    except D.ValidationError:
        pass

def test_fraction_validation():
    conn = make_conn()
    rid = D.create_recipe(conn, "Rice")
    bid = D.create_batch(conn, rid, "2026-05-14")
    try:
        D.create_meal(conn, "dinner", "2026-05-14",
                      batch_id=bid, fraction_of_batch=1.5)
        assert False
    except D.ValidationError:
        pass


# ── notes tests ─────────────────────────────────────────────────────────────

def test_add_and_get_notes():
    conn = make_conn()
    rid = D.create_recipe(conn, "Pancakes")
    nid = D.add_note(conn, "Added vanilla extract", recipe_id=rid)
    assert nid > 0
    notes = D.get_notes(conn, recipe_id=rid)
    assert len(notes) == 1
    assert "vanilla" in notes[0]["note_txt"]

def test_note_requires_parent():
    conn = make_conn()
    try:
        D.add_note(conn, "Orphan note")
        assert False
    except D.ValidationError:
        pass


# ── nutrition query tests ───────────────────────────────────────────────────

def _setup_nutrition_scenario(conn):
    """Build a small but complete scenario for nutrition tests."""
    rid = D.create_recipe(conn, "Veggie Bowl")
    iid_rice = D.create_ingredient(conn, "Brown Rice", "100g serving",
                                    protein_grams=2.6, fat_grams=0.9,
                                    carb_grams=23, fiber_grams=1.8, calories=112)
    iid_broc = D.create_ingredient(conn, "Broccoli", "100g serving",
                                    protein_grams=2.8, fat_grams=0.4,
                                    carb_grams=7, fiber_grams=2.6, calories=34)
    D.add_component(conn, iid_rice, 2.0, recipe_id=rid)   # 200g rice
    D.add_component(conn, iid_broc, 1.5, recipe_id=rid)   # 150g broccoli

    bid = D.create_batch(conn, rid, "2026-05-14")
    # Meal: 50% of the batch
    mid1 = D.create_meal(conn, "lunch", "2026-05-14",
                         batch_id=bid, fraction_of_batch=0.5)

    # Standalone snack: just an apple
    iid_apple = D.create_ingredient(conn, "Apple", "100g serving",
                                     protein_grams=0.5, fat_grams=0.2,
                                     carb_grams=25, fiber_grams=4.4, calories=95)
    mid2 = D.create_meal(conn, "afternoon_snack", "2026-05-14")
    D.add_meal_ingredient(conn, mid2, iid_apple, 1.0)

    return rid, bid, mid1, mid2, iid_rice, iid_broc, iid_apple

def test_daily_nutrition():
    conn = make_conn()
    _setup_nutrition_scenario(conn)
    report = D.get_daily_nutrition(conn, "2026-05-14")

    assert report["date"] == "2026-05-14"
    assert len(report["meals"]) == 2

    # Meal 1 is batch-based
    m1 = next(m for m in report["meals"] if m["source"] == "batch")
    # rice: 2.0 * 112 * 0.5 = 112 cal; broc: 1.5 * 34 * 0.5 = 25.5 cal → 137.5 total
    assert abs(m1["nutrition"]["calories"] - 137.5) < 0.01

    # Meal 2 is ingredient-based
    m2 = next(m for m in report["meals"] if m["source"] == "ingredients")
    assert abs(m2["nutrition"]["calories"] - 95.0) < 0.01

    # Daily total
    assert abs(report["daily_totals"]["calories"] - 232.5) < 0.01

def test_aggregate_nutrition():
    conn = make_conn()
    _setup_nutrition_scenario(conn)
    report = D.get_aggregate_nutrition(conn, "2026-05-14", "2026-05-14")
    assert report["num_meals"] == 2
    assert report["num_days"] == 1
    assert abs(report["totals"]["calories"] - 232.5) < 0.01
    assert abs(report["daily_averages"]["calories"] - 232.5) < 0.01

def test_aggregate_daily_average_only_counts_days_with_data():
    """
    Regression test: averaging over the full calendar span (e.g. 7 days)
    when only 1 of those days actually has logged meals understates the
    average by 7x. The average should divide by days *with data* only —
    so with a single day of data, the average should equal the total.
    """
    conn = make_conn()
    _setup_nutrition_scenario(conn)  # all data lands on 2026-05-14
    report = D.get_aggregate_nutrition(conn, "2026-05-09", "2026-05-15")  # 7-day span
    assert report["num_days"] == 7
    assert report["num_days_with_data"] == 1
    assert abs(report["totals"]["calories"] - 232.5) < 0.01
    assert abs(report["daily_averages"]["calories"] - 232.5) < 0.01

def test_aggregate_date_validation():
    conn = make_conn()
    try:
        D.get_aggregate_nutrition(conn, "2026-05-14", "2026-05-01")
        assert False
    except D.ValidationError:
        pass

def test_search_recipes_and_ingredients():
    conn = make_conn()
    D.create_recipe(conn, "Chicken Stir Fry")
    D.create_ingredient(conn, "Chicken Breast", "g")
    results = D.search_recipes_and_ingredients(conn, "chicken")
    assert len(results["recipes"]) == 1
    assert len(results["ingredients"]) == 1


# ── run all tests ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        # recipes
        ("create recipe",               test_create_recipe),
        ("duplicate recipe blocked",    test_duplicate_recipe),
        ("search recipes",              test_search_recipes),
        ("update recipe",               test_update_recipe),
        ("get recipe not found",        test_get_recipe_not_found),
        # ingredients
        ("create ingredient",           test_create_ingredient),
        ("find or create ingredient",   test_find_or_create_ingredient),
        ("update ingredient nutrition", test_update_ingredient_nutrition),
        ("search ingredients",          test_search_ingredients),
        # components
        ("add and get components",      test_add_and_get_components),
        ("component needs one parent",  test_component_requires_one_parent),
        ("remove component",            test_remove_component),
        ("update component quantity",   test_update_component_quantity),
        # batches
        ("create batch",                test_create_batch),
        ("get latest batch",            test_get_latest_batch),
        ("batch ingredient modification", test_batch_ingredient_modification),
        ("copy recipe components to batch", test_copy_recipe_components_to_batch),
        ("copy recipe components to batch handles duplicate ingredient",
            test_copy_recipe_components_to_batch_handles_duplicate_ingredient),
        # meals
        ("create batch meal",           test_create_batch_meal),
        ("create ingredient-only meal", test_create_ingredient_only_meal),
        ("invalid meal type blocked",   test_invalid_meal_type),
        ("fraction > 1 blocked",        test_fraction_validation),
        # notes
        ("add and get notes",           test_add_and_get_notes),
        ("note needs parent",           test_note_requires_parent),
        # nutrition
        ("daily nutrition",             test_daily_nutrition),
        ("aggregate nutrition",         test_aggregate_nutrition),
        ("aggregate daily average only counts days with data",
            test_aggregate_daily_average_only_counts_days_with_data),
        ("aggregate date validation",   test_aggregate_date_validation),
        ("search recipes and ingredients", test_search_recipes_and_ingredients),
    ]

    print(f"\nRunning {len(tests)} tests...\n")
    for name, fn in tests:
        test(name, fn)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n{'─'*40}")
    print(f"  {passed}/{len(results)} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        sys.exit(1)
    else:
        print("  — all good!")
