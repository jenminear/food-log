"""
test_nutrition_lookup.py — Tests for the nutrition lookup module
================================================================
Two sections:

  UNIT TESTS  — mock all HTTP; no network required; run any time.
  INTEGRATION TESTS — real HTTP calls to USDA and OFF APIs.
                      Run manually:  python test_nutrition_lookup.py --integration
                      Skipped by default to avoid rate-limit issues in CI.

Run unit tests only (default):
    python test_nutrition_lookup.py

Run everything including integration tests:
    python test_nutrition_lookup.py --integration
"""

from __future__ import annotations

import sys
import json
import unittest
from typing import Optional
from unittest.mock import patch, MagicMock

import nutrition_lookup as NL


# ===========================================================================
# Shared test fixtures — realistic fake API responses
# ===========================================================================

# --- USDA search response (POST /foods/search) ---
USDA_SEARCH_RESPONSE = {
    "foods": [
        {
            "fdcId": 173904,
            "description": "Oats, rolled, dry",
            "dataType": "SR Legacy",
            "foodNutrients": [
                {"nutrient": {"id": 1008}, "amount": 379.0},   # calories
                {"nutrient": {"id": 1003}, "amount": 13.15},   # protein
                {"nutrient": {"id": 1004}, "amount": 6.52},    # fat
                {"nutrient": {"id": 1005}, "amount": 67.7},    # carbs
                {"nutrient": {"id": 1079}, "amount": 10.1},    # fiber
            ],
        },
        {
            "fdcId": 999001,
            "description": "Oat bran, raw",
            "dataType": "SR Legacy",
            "foodNutrients": [
                {"nutrient": {"id": 1008}, "amount": 246.0},
                {"nutrient": {"id": 1003}, "amount": 17.3},
                {"nutrient": {"id": 1004}, "amount": 7.03},
                {"nutrient": {"id": 1005}, "amount": 66.2},
                {"nutrient": {"id": 1079}, "amount": 15.4},
            ],
        },
        {
            "fdcId": 999002,
            "description": "Granola bar with oats and honey",
            "dataType": "Branded",
            "foodNutrients": [
                {"nutrient": {"id": 1008}, "amount": 450.0},
                {"nutrient": {"id": 1003}, "amount": 8.0},
                {"nutrient": {"id": 1004}, "amount": 18.0},
                {"nutrient": {"id": 1005}, "amount": 64.0},
                {"nutrient": {"id": 1079}, "amount": 3.5},
            ],
        },
    ]
}

# --- USDA detail response (GET /food/{id}) ---
USDA_DETAIL_RESPONSE = {
    "fdcId": 173904,
    "description": "Oats, rolled, dry",
    "dataType": "SR Legacy",
    "foodNutrients": USDA_SEARCH_RESPONSE["foods"][0]["foodNutrients"],
    "foodMeasures": [
        {"disseminationText": "1 cup", "gramWeight": 90.0, "measurementAmount": 1.0},
        {"disseminationText": "1 tbsp", "gramWeight": 5.6, "measurementAmount": 1.0},
        {"disseminationText": "100g", "gramWeight": 100.0, "measurementAmount": 100.0},
    ],
}

# --- USDA detail response with no portions ---
USDA_DETAIL_NO_PORTIONS = {
    "fdcId": 999001,
    "description": "Oat bran, raw",
    "dataType": "SR Legacy",
    "foodNutrients": USDA_SEARCH_RESPONSE["foods"][1]["foodNutrients"],
    "foodMeasures": [],
}

# --- OFF search response ---
OFF_SEARCH_RESPONSE = {
    "products": [
        {
            "id": "0123456789",
            "product_name_en": "Organic Rolled Oats",
            "nutriments": {
                "energy-kcal_100g": 370.0,
                "proteins_100g":    13.0,
                "fat_100g":         6.5,
                "carbohydrates_100g": 67.0,
                "fiber_100g":       10.0,
            },
            "serving_size": "40 g",
        },
        {
            "id": "9876543210",
            "product_name": "Oat Flakes",
            "product_name_en": "",
            "nutriments": {
                "energy-kcal_100g": 360.0,
                "proteins_100g":    12.0,
                "fat_100g":         None,   # missing fat
                "carbohydrates_100g": 65.0,
                "fiber_100g":       9.5,
            },
            "serving_size": "30 g",
        },
        {
            # Product with no name — should score 0
            "id": "0000000000",
            "product_name_en": "",
            "product_name": "",
            "nutriments": {},
            "serving_size": "",
        },
    ]
}

# --- USDA search response: exact match ---
USDA_EXACT_MATCH_RESPONSE = {
    "foods": [
        {
            "fdcId": 200001,
            "description": "Broccoli",
            "dataType": "Foundation",
            "foodNutrients": [
                {"nutrient": {"id": 1008}, "amount": 34.0},
                {"nutrient": {"id": 1003}, "amount": 2.82},
                {"nutrient": {"id": 1004}, "amount": 0.37},
                {"nutrient": {"id": 1005}, "amount": 6.64},
                {"nutrient": {"id": 1079}, "amount": 2.6},
            ],
        }
    ]
}

USDA_EXACT_DETAIL_RESPONSE = {
    "fdcId": 200001,
    "description": "Broccoli",
    "dataType": "Foundation",
    "foodNutrients": USDA_EXACT_MATCH_RESPONSE["foods"][0]["foodNutrients"],
    "foodMeasures": [
        {"disseminationText": "1 cup chopped", "gramWeight": 91.0, "measurementAmount": 1.0},
        {"disseminationText": "1 medium stalk", "gramWeight": 148.0, "measurementAmount": 1.0},
    ],
}

USDA_BRANDED_DETAIL = {
    "fdcId": 300001,
    "description": "Greek Yogurt, Plain, Nonfat",
    "dataType": "Branded",
    "servingSize": 170.0,
    "servingSizeUnit": "g",
    "foodNutrients": [
        {"nutrient": {"id": 1008}, "amount": 59.0},
        {"nutrient": {"id": 1003}, "amount": 10.0},
        {"nutrient": {"id": 1004}, "amount": 0.7},
        {"nutrient": {"id": 1005}, "amount": 3.6},
        {"nutrient": {"id": 1079}, "amount": 0.0},
    ],
    "foodMeasures": [],
}


# ===========================================================================
# Helpers
# ===========================================================================

def _make_result(**kwargs) -> NL.NutritionResult:
    """Build a minimal NutritionResult for testing."""
    defaults = dict(
        ingredient_name="Test Ingredient",
        source="usda",
        source_id="12345",
        source_url="https://example.com",
        portion_unit="1 cup",
        portion_grams=90.0,
        calories=379.0,
        protein_grams=13.15,
        fat_grams=6.52,
        carb_grams=67.7,
        fiber_grams=10.1,
        confidence=0.9,
    )
    defaults.update(kwargs)
    return NL.NutritionResult(**defaults)


# ===========================================================================
# UNIT TESTS
# ===========================================================================

class TestApiKeyResolution(unittest.TestCase):

    def test_override_takes_priority(self):
        key = NL._get_usda_api_key(override="MY_KEY")
        self.assertEqual(key, "MY_KEY")

    def test_env_var(self):
        with patch.dict("os.environ", {"USDA_API_KEY": "ENV_KEY"}):
            key = NL._get_usda_api_key()
        self.assertEqual(key, "ENV_KEY")

    def test_falls_back_to_demo(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("nutrition_lookup.Path.exists", return_value=False):
                key = NL._get_usda_api_key()
        self.assertEqual(key, "DEMO_KEY")


class TestNutritionResult(unittest.TestCase):

    def test_nutrition_complete_all_present(self):
        r = _make_result()
        self.assertTrue(r.nutrition_complete())

    def test_nutrition_complete_missing_field(self):
        r = _make_result(fiber_grams=None)
        self.assertFalse(r.nutrition_complete())

    def test_summary_contains_name_and_source(self):
        r = _make_result(ingredient_name="Rolled Oats", source="usda")
        s = r.summary()
        self.assertIn("Rolled Oats", s)
        self.assertIn("usda", s)
        self.assertIn("379", s)   # calories
        self.assertIn("13.2", s)  # protein rounded to 1dp

    def test_summary_handles_none_calories(self):
        r = _make_result(calories=None)
        self.assertIn("? kcal", r.summary())

    def test_result_to_db_kwargs_keys(self):
        r = _make_result()
        kwargs = NL.result_to_db_kwargs(r)
        expected_keys = {
            "portion_unit", "portion_grams",
            "calories", "protein_grams", "fat_grams",
            "carb_grams", "fiber_grams", "source_food_name", "nutrition_info_source",
        }
        self.assertEqual(set(kwargs.keys()), expected_keys)

    def test_result_to_db_kwargs_values(self):
        r = _make_result(calories=379.0, portion_grams=90.0,
                         ingredient_name="Oats, raw", source="usda")
        kwargs = NL.result_to_db_kwargs(r)
        self.assertEqual(kwargs["calories"], 379.0)
        self.assertEqual(kwargs["portion_grams"], 90.0)
        self.assertEqual(kwargs["nutrition_info_source"], "USDA: Oats, raw")


class TestShouldAutoPick(unittest.TestCase):

    def test_high_confidence_auto_picks(self):
        r = _make_result(confidence=NL.CONFIDENCE_HIGH)
        self.assertTrue(NL.should_auto_pick(r))

    def test_above_threshold_auto_picks(self):
        r = _make_result(confidence=0.99)
        self.assertTrue(NL.should_auto_pick(r))

    def test_below_threshold_does_not_auto_pick(self):
        r = _make_result(confidence=NL.CONFIDENCE_HIGH - 0.01)
        self.assertFalse(NL.should_auto_pick(r))

    def test_zero_confidence_does_not_auto_pick(self):
        r = _make_result(confidence=0.0)
        self.assertFalse(NL.should_auto_pick(r))


class TestFormatCandidatesForDisplay(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(NL.format_candidates_for_display([]), "No results found.")

    def test_numbered_list(self):
        candidates = [
            _make_result(ingredient_name="Rolled Oats", confidence=0.9),
            _make_result(ingredient_name="Oat Bran",    confidence=0.5),
        ]
        output = NL.format_candidates_for_display(candidates)
        self.assertIn("1.", output)
        self.assertIn("2.", output)
        self.assertIn("Rolled Oats", output)
        self.assertIn("Oat Bran", output)

    def test_confidence_labels(self):
        candidates = [
            _make_result(confidence=0.9),   # high
            _make_result(confidence=0.55),  # medium
            _make_result(confidence=0.2),   # low
        ]
        output = NL.format_candidates_for_display(candidates)
        self.assertIn("high confidence", output)
        self.assertIn("medium confidence", output)
        self.assertIn("low confidence", output)


class TestExtractUsdaNutrients(unittest.TestCase):

    def test_extracts_all_five_nutrients(self):
        food = USDA_SEARCH_RESPONSE["foods"][0]
        nutrients = NL._extract_usda_nutrients(food)
        self.assertAlmostEqual(nutrients["calories"],      379.0)
        self.assertAlmostEqual(nutrients["protein_grams"], 13.15)
        self.assertAlmostEqual(nutrients["fat_grams"],     6.52)
        self.assertAlmostEqual(nutrients["carb_grams"],    67.7)
        self.assertAlmostEqual(nutrients["fiber_grams"],   10.1)

    def test_missing_nutrient_returns_none(self):
        food = {"foodNutrients": []}
        nutrients = NL._extract_usda_nutrients(food)
        for v in nutrients.values():
            self.assertIsNone(v)

    def test_partial_nutrients(self):
        food = {"foodNutrients": [
            {"nutrient": {"id": 1008}, "amount": 200.0},  # calories only
        ]}
        nutrients = NL._extract_usda_nutrients(food)
        self.assertAlmostEqual(nutrients["calories"], 200.0)
        self.assertIsNone(nutrients["protein_grams"])


class TestExtractUsdaPortions(unittest.TestCase):

    def test_prefers_cup_over_tbsp(self):
        pu, pg, all_p = NL._extract_usda_portions(USDA_DETAIL_RESPONSE)
        self.assertEqual(pu, "1 cup")
        self.assertAlmostEqual(pg, 90.0)

    def test_falls_back_to_grams_when_no_portions(self):
        pu, pg, all_p = NL._extract_usda_portions(USDA_DETAIL_NO_PORTIONS)
        self.assertAlmostEqual(pg, 1.0)
        self.assertEqual(pu, "g")

    def test_all_portions_populated(self):
        _, _, all_p = NL._extract_usda_portions(USDA_DETAIL_RESPONSE)
        self.assertEqual(len(all_p), 3)

    def test_branded_food_uses_serving_size(self):
        pu, pg, all_p = NL._extract_usda_portions(USDA_BRANDED_DETAIL)
        self.assertAlmostEqual(pg, 170.0)
        self.assertEqual(pu, "g")


class TestScoreUsdaResult(unittest.TestCase):

    def test_exact_match_scores_1(self):
        food = {"description": "broccoli", "dataType": "Foundation"}
        score = NL._score_usda_result("broccoli", food)
        self.assertAlmostEqual(score, 1.0)

    def test_partial_word_match_scores_lower(self):
        # "oats" matches 1 of 6 words in the description — should score < 0.75
        # (below the auto-pick threshold, meaning the user would be asked to confirm)
        food = {"description": "granola bar with oats and honey", "dataType": "Branded"}
        score = NL._score_usda_result("oats", food)
        self.assertLess(score, NL.CONFIDENCE_HIGH)

    def test_sr_legacy_boosted_over_branded(self):
        # Data type boost only differentiates on exact matches (non-exact scores
        # are dominated by word overlap and brevity penalty, both equal here).
        # Use an exact-match query to demonstrate the boost.
        sr_food  = {"description": "rolled oats", "dataType": "SR Legacy"}
        branded  = {"description": "rolled oats", "dataType": "Branded"}
        sr_score = NL._score_usda_result("rolled oats", sr_food)
        b_score  = NL._score_usda_result("rolled oats", branded)
        self.assertGreater(sr_score, b_score)

    def test_unrelated_scores_low(self):
        food = {"description": "chocolate cake with frosting", "dataType": "Branded"}
        score = NL._score_usda_result("broccoli", food)
        self.assertLess(score, 0.2)

    def test_score_capped_at_1(self):
        food = {"description": "oats", "dataType": "SR Legacy"}
        score = NL._score_usda_result("oats", food)
        self.assertLessEqual(score, 1.0)


class TestExtractOffNutrients(unittest.TestCase):

    def test_extracts_all_five(self):
        product = OFF_SEARCH_RESPONSE["products"][0]
        nutrients = NL._extract_off_nutrients(product)
        self.assertAlmostEqual(nutrients["calories"],      370.0)
        self.assertAlmostEqual(nutrients["protein_grams"], 13.0)
        self.assertAlmostEqual(nutrients["fat_grams"],     6.5)
        self.assertAlmostEqual(nutrients["carb_grams"],    67.0)
        self.assertAlmostEqual(nutrients["fiber_grams"],   10.0)

    def test_missing_nutrient_returns_none(self):
        product = OFF_SEARCH_RESPONSE["products"][1]
        nutrients = NL._extract_off_nutrients(product)
        self.assertIsNone(nutrients["fat_grams"])

    def test_empty_nutriments_all_none(self):
        product = {"nutriments": {}}
        nutrients = NL._extract_off_nutrients(product)
        for v in nutrients.values():
            self.assertIsNone(v)


class TestExtractOffPortions(unittest.TestCase):

    def test_parses_gram_serving_size(self):
        product = {"serving_size": "40 g"}
        pu, pg, all_p = NL._extract_off_portions(product)
        self.assertAlmostEqual(pg, 40.0)

    def test_parses_ml_serving_size(self):
        product = {"serving_size": "240 ml"}
        pu, pg, _ = NL._extract_off_portions(product)
        self.assertAlmostEqual(pg, 240.0)
        self.assertEqual(pu, "ml")

    def test_no_serving_size_falls_back_to_100g(self):
        product = {"serving_size": ""}
        pu, pg, _ = NL._extract_off_portions(product)
        self.assertAlmostEqual(pg, 100.0)
        self.assertEqual(pu, "g")

    def test_complex_serving_size_string(self):
        product = {"serving_size": "1 cup (240ml)"}
        pu, pg, _ = NL._extract_off_portions(product)
        self.assertAlmostEqual(pg, 240.0)


class TestScoreOffResult(unittest.TestCase):

    def test_exact_name_match_scores_high(self):
        product = {"product_name_en": "rolled oats", "nutriments": {}}
        score = NL._score_off_result("rolled oats", product)
        self.assertAlmostEqual(score, 0.93)

    def test_no_name_scores_zero(self):
        product = {"product_name_en": "", "product_name": "", "nutriments": {}}
        score = NL._score_off_result("oats", product)
        self.assertEqual(score, 0.0)

    def test_complete_nutrition_boosts_score(self):
        complete = {
            "product_name_en": "oats",
            "nutriments": {
                "energy-kcal_100g": 379, "proteins_100g": 13,
                "fat_100g": 7, "carbohydrates_100g": 67, "fiber_100g": 10,
            }
        }
        incomplete = {
            "product_name_en": "oats",
            "nutriments": {},
        }
        self.assertGreaterEqual(
            NL._score_off_result("oats", complete),
            NL._score_off_result("oats", incomplete),
        )

    def test_score_capped_at_0_97(self):
        product = {
            "product_name_en": "rolled oats",
            "nutriments": {
                "energy-kcal_100g": 379, "proteins_100g": 13,
                "fat_100g": 7, "carbohydrates_100g": 67, "fiber_100g": 10,
            }
        }
        score = NL._score_off_result("rolled oats", product)
        self.assertLessEqual(score, 0.97)


class TestSearchUsdaMocked(unittest.TestCase):
    """Test _search_usda with mocked HTTP calls."""

    def _mock_post(self, url, payload, headers=None):
        return USDA_SEARCH_RESPONSE

    def _mock_get(self, url, params=None):
        fdc_id = int(url.split("/")[-1].split("?")[0])
        if fdc_id == 173904:
            return USDA_DETAIL_RESPONSE
        if fdc_id == 999001:
            return USDA_DETAIL_NO_PORTIONS
        return None

    def test_returns_results(self):
        with patch("nutrition_lookup._post_json", side_effect=self._mock_post), \
             patch("nutrition_lookup._get_json", side_effect=self._mock_get):
            results = NL._search_usda("rolled oats", api_key="DEMO_KEY")
        self.assertGreater(len(results), 0)

    def test_results_are_nutrition_results(self):
        with patch("nutrition_lookup._post_json", side_effect=self._mock_post), \
             patch("nutrition_lookup._get_json", side_effect=self._mock_get):
            results = NL._search_usda("rolled oats", api_key="DEMO_KEY")
        for r in results:
            self.assertIsInstance(r, NL.NutritionResult)
            self.assertEqual(r.source, "usda")

    def test_top_result_has_portion_data(self):
        with patch("nutrition_lookup._post_json", side_effect=self._mock_post), \
             patch("nutrition_lookup._get_json", side_effect=self._mock_get):
            results = NL._search_usda("rolled oats", api_key="DEMO_KEY")
        top = results[0]
        # Should have fetched detail and gotten the cup portion
        self.assertEqual(top.portion_unit, "1 cup")
        self.assertAlmostEqual(top.portion_grams, 90.0)

    def test_sr_legacy_ranked_above_branded(self):
        with patch("nutrition_lookup._post_json", side_effect=self._mock_post), \
             patch("nutrition_lookup._get_json", side_effect=self._mock_get):
            results = NL._search_usda("oats", api_key="DEMO_KEY")
        # SR Legacy results should come before Branded
        sr_indices = [i for i, r in enumerate(results) if "SR Legacy" in r.data_type]
        br_indices  = [i for i, r in enumerate(results) if "Branded" in r.data_type]
        if sr_indices and br_indices:
            self.assertLess(min(sr_indices), min(br_indices))

    def test_empty_search_returns_empty_list(self):
        with patch("nutrition_lookup._post_json", return_value={"foods": []}), \
             patch("nutrition_lookup._get_json", return_value=None):
            results = NL._search_usda("xyznonexistentfood123", api_key="DEMO_KEY")
        self.assertEqual(results, [])

    def test_nutrients_extracted_correctly(self):
        with patch("nutrition_lookup._post_json", side_effect=self._mock_post), \
             patch("nutrition_lookup._get_json", side_effect=self._mock_get):
            results = NL._search_usda("rolled oats", api_key="DEMO_KEY")
        top = next(r for r in results if r.source_id == "173904")
        self.assertAlmostEqual(top.calories,      379.0)
        self.assertAlmostEqual(top.protein_grams, 13.15)
        self.assertAlmostEqual(top.fat_grams,     6.52)
        self.assertAlmostEqual(top.carb_grams,    67.7)
        self.assertAlmostEqual(top.fiber_grams,   10.1)


class TestSearchOffMocked(unittest.TestCase):
    """Test _search_off with mocked HTTP calls."""

    def test_returns_results(self):
        with patch("nutrition_lookup._get_json", return_value=OFF_SEARCH_RESPONSE):
            results = NL._search_off("rolled oats")
        self.assertGreater(len(results), 0)

    def test_skips_nameless_products(self):
        with patch("nutrition_lookup._get_json", return_value=OFF_SEARCH_RESPONSE):
            results = NL._search_off("rolled oats")
        # The nameless product should have confidence 0 and appear last (or be deduplicated)
        names = [r.ingredient_name for r in results]
        self.assertNotIn("Unknown product", names[:2])

    def test_source_set_to_open_food_facts(self):
        with patch("nutrition_lookup._get_json", return_value=OFF_SEARCH_RESPONSE):
            results = NL._search_off("rolled oats")
        for r in results:
            self.assertEqual(r.source, "open_food_facts")

    def test_portion_extracted(self):
        with patch("nutrition_lookup._get_json", return_value=OFF_SEARCH_RESPONSE):
            results = NL._search_off("rolled oats")
        top = results[0]
        self.assertAlmostEqual(top.portion_grams, 40.0)

    def test_empty_response_returns_empty_list(self):
        with patch("nutrition_lookup._get_json", return_value={"products": []}):
            results = NL._search_off("xyznonexistent")
        self.assertEqual(results, [])


class TestLookupMocked(unittest.TestCase):
    """Test the top-level lookup() function with mocked HTTP."""

    def _usda_post(self, url, payload, headers=None):
        return USDA_SEARCH_RESPONSE

    def _usda_get(self, url, params=None):
        if "173904" in url:
            return USDA_DETAIL_RESPONSE
        return USDA_DETAIL_NO_PORTIONS

    def _off_get(self, url, params=None):
        return OFF_SEARCH_RESPONSE

    def _patched_lookup(self, name, **kwargs):
        with patch("nutrition_lookup._post_json", side_effect=self._usda_post), \
             patch("nutrition_lookup._get_json", side_effect=self._off_get):
            return NL.lookup(name, **kwargs)

    def test_returns_list(self):
        results = self._patched_lookup("rolled oats")
        self.assertIsInstance(results, list)

    def test_results_sorted_by_confidence_descending(self):
        results = self._patched_lookup("rolled oats")
        for i in range(len(results) - 1):
            self.assertGreaterEqual(results[i].confidence, results[i + 1].confidence)

    def test_deduplication(self):
        # If USDA and OFF return the same ingredient name, keep only one
        results = self._patched_lookup("rolled oats")
        names = [r.ingredient_name.lower() for r in results]
        self.assertEqual(len(names), len(set(names)))

    def test_max_candidates_respected(self):
        results = self._patched_lookup("oats", max_candidates=2)
        self.assertLessEqual(len(results), 2)

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            NL.lookup("   ")

    def test_off_disabled(self):
        with patch("nutrition_lookup._post_json", side_effect=self._usda_post), \
             patch("nutrition_lookup._get_json", side_effect=self._usda_get):
            results = NL.lookup("rolled oats", include_off=False)
        # All results should come from USDA only
        for r in results:
            self.assertEqual(r.source, "usda")

    def test_usda_failure_falls_through_to_off(self):
        """If USDA raises an unexpected error, OFF results still returned."""
        with patch("nutrition_lookup._post_json", side_effect=Exception("USDA down")), \
             patch("nutrition_lookup._get_json", return_value=OFF_SEARCH_RESPONSE):
            results = NL.lookup("rolled oats")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertEqual(r.source, "open_food_facts")

    def test_network_error_propagates(self):
        with patch("nutrition_lookup._post_json",
                   side_effect=NL.NetworkError("No connection")):
            with self.assertRaises(NL.NetworkError):
                NL.lookup("rolled oats")

    def test_rate_limit_error_propagates(self):
        with patch("nutrition_lookup._post_json",
                   side_effect=NL.RateLimitError("Too many requests")):
            with self.assertRaises(NL.RateLimitError):
                NL.lookup("rolled oats")


class TestBestMatchMocked(unittest.TestCase):

    def _usda_post(self, url, payload, headers=None):
        return USDA_EXACT_MATCH_RESPONSE

    def _get_json_dispatch(self, url, params=None):
        # Route detail fetches to USDA detail; everything else returns empty OFF response
        if "api.nal.usda.gov" in url:
            return USDA_EXACT_DETAIL_RESPONSE
        return {"products": []}   # OFF returns nothing — USDA result is sufficient

    def test_returns_top_candidate(self):
        with patch("nutrition_lookup._post_json", side_effect=self._usda_post), \
             patch("nutrition_lookup._get_json", side_effect=self._get_json_dispatch):
            result = NL.best_match("broccoli")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, NL.NutritionResult)

    def test_returns_none_when_no_results(self):
        with patch("nutrition_lookup._post_json", return_value={"foods": []}), \
             patch("nutrition_lookup._get_json", return_value={"products": []}):
            result = NL.best_match("xyznonexistentfood999")
        self.assertIsNone(result)

    def test_exact_match_auto_picks(self):
        with patch("nutrition_lookup._post_json", side_effect=self._usda_post), \
             patch("nutrition_lookup._get_json", side_effect=self._get_json_dispatch):
            result = NL.best_match("broccoli")
        self.assertIsNotNone(result)
        self.assertTrue(NL.should_auto_pick(result))


class TestDataTypePriority(unittest.TestCase):

    def test_sr_legacy_is_highest_priority(self):
        self.assertEqual(NL._usda_data_type_priority("SR Legacy"), 0)

    def test_foundation_is_second(self):
        self.assertEqual(NL._usda_data_type_priority("Foundation"), 1)

    def test_branded_is_lowest_known(self):
        branded = NL._usda_data_type_priority("Branded")
        sr      = NL._usda_data_type_priority("SR Legacy")
        self.assertGreater(branded, sr)

    def test_unknown_type_gets_max_priority_value(self):
        unknown = NL._usda_data_type_priority("SomeUnknownType")
        self.assertEqual(unknown, len(NL.USDA_PREFERRED_DATA_TYPES))


# ===========================================================================
# INTEGRATION TESTS  (live network — skipped unless --integration passed)
# ===========================================================================

SKIP_INTEGRATION = "--integration" not in sys.argv

@unittest.skipIf(SKIP_INTEGRATION, "Integration tests skipped (pass --integration to run)")
class TestIntegrationUSDA(unittest.TestCase):
    """Live calls to USDA FoodData Central."""

    def test_rolled_oats_returns_results(self):
        results = NL._search_usda("rolled oats", api_key=NL._get_usda_api_key())
        self.assertGreater(len(results), 0)

    def test_rolled_oats_top_result_has_calories(self):
        results = NL._search_usda("rolled oats", api_key=NL._get_usda_api_key())
        self.assertIsNotNone(results[0].calories)
        self.assertGreater(results[0].calories, 0)

    def test_rolled_oats_has_portion_data(self):
        results = NL._search_usda("rolled oats", api_key=NL._get_usda_api_key())
        # Top result should have had its detail fetched with portion info
        top = results[0]
        self.assertNotEqual(top.portion_unit, "g")  # Should be "cup" or similar

    def test_broccoli_exact_match_high_confidence(self):
        results = NL._search_usda("broccoli", api_key=NL._get_usda_api_key())
        self.assertGreater(results[0].confidence, NL.CONFIDENCE_HIGH)

    def test_nonsense_query_returns_empty_or_low_confidence(self):
        results = NL._search_usda("xyznonexistentfood999abc",
                                   api_key=NL._get_usda_api_key())
        if results:
            self.assertLess(results[0].confidence, NL.CONFIDENCE_HIGH)

    def test_sr_legacy_preferred_for_raw_ingredient(self):
        results = NL._search_usda("chicken breast", api_key=NL._get_usda_api_key())
        if len(results) > 1:
            # First result should not be Branded if SR Legacy / Foundation available
            sr_or_foundation = [r for r in results
                                 if "SR Legacy" in r.data_type or "Foundation" in r.data_type]
            if sr_or_foundation:
                self.assertLessEqual(results.index(sr_or_foundation[0]), 1)


@unittest.skipIf(SKIP_INTEGRATION, "Integration tests skipped (pass --integration to run)")
class TestIntegrationOFF(unittest.TestCase):
    """Live calls to Open Food Facts."""

    def test_search_returns_results(self):
        results = NL._search_off("oat milk")
        self.assertGreater(len(results), 0)

    def test_results_have_source_set(self):
        results = NL._search_off("oat milk")
        for r in results:
            self.assertEqual(r.source, "open_food_facts")

    def test_branded_product_has_nutrition(self):
        # Packaged products should generally have at least calories
        results = NL._search_off("almond milk")
        has_calories = [r for r in results if r.calories is not None]
        self.assertGreater(len(has_calories), 0)


@unittest.skipIf(SKIP_INTEGRATION, "Integration tests skipped (pass --integration to run)")
class TestIntegrationLookup(unittest.TestCase):
    """End-to-end tests of the public lookup() API."""

    def test_rolled_oats_lookup(self):
        results = NL.lookup("rolled oats")
        self.assertGreater(len(results), 0)
        self.assertGreaterEqual(results[0].confidence, NL.CONFIDENCE_LOW)

    def test_results_sorted_descending(self):
        results = NL.lookup("broccoli")
        for i in range(len(results) - 1):
            self.assertGreaterEqual(results[i].confidence, results[i + 1].confidence)

    def test_no_duplicate_names(self):
        results = NL.lookup("oats")
        names = [r.ingredient_name.lower() for r in results]
        self.assertEqual(len(names), len(set(names)))

    def test_best_match_broccoli_auto_picks(self):
        result = NL.best_match("broccoli")
        self.assertIsNotNone(result)
        self.assertTrue(NL.should_auto_pick(result))

    def test_result_to_db_kwargs_roundtrip(self):
        """result_to_db_kwargs should produce valid db.create_ingredient kwargs."""
        import db
        import sqlite3
        from pathlib import Path

        result = NL.best_match("broccoli")
        self.assertIsNotNone(result)

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        schema = (Path(__file__).with_name("food_log_schema.sql")).read_text()
        conn.executescript(schema)

        kwargs = NL.result_to_db_kwargs(result)
        iid = db.create_ingredient(conn, result.ingredient_name, **kwargs)
        self.assertGreater(iid, 0)

        row = db.find_ingredient_by_name(conn, result.ingredient_name)
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["portion_grams"], result.portion_grams, places=1)


# ===========================================================================
# Runner
# ===========================================================================

if __name__ == "__main__":
    # Strip --integration from argv before passing to unittest
    argv = [a for a in sys.argv if a != "--integration"]

    print(f"\n{'═' * 60}")
    print("  Nutrition Lookup — Unit Tests")
    if not SKIP_INTEGRATION:
        print("  + Integration Tests (live network)")
    print(f"{'═' * 60}\n")

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    # Always run unit tests
    unit_classes = [
        TestApiKeyResolution,
        TestNutritionResult,
        TestShouldAutoPick,
        TestFormatCandidatesForDisplay,
        TestExtractUsdaNutrients,
        TestExtractUsdaPortions,
        TestScoreUsdaResult,
        TestExtractOffNutrients,
        TestExtractOffPortions,
        TestScoreOffResult,
        TestSearchUsdaMocked,
        TestSearchOffMocked,
        TestLookupMocked,
        TestBestMatchMocked,
        TestDataTypePriority,
    ]
    for cls in unit_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    # Integration tests (only if --integration)
    if not SKIP_INTEGRATION:
        for cls in [TestIntegrationUSDA, TestIntegrationOFF, TestIntegrationLookup]:
            suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
