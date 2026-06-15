"""
nutrition_lookup.py — Nutrition Data Lookup Module
====================================================
Fetches nutrition data for ingredients from two sources:

  1. USDA FoodData Central (primary — best for raw/whole ingredients)
  2. Open Food Facts (fallback — best for packaged/branded foods)

All nutrition values are normalised to per-100g before being returned.
Portion data (e.g. "1 cup = 90g") is extracted and stored alongside so
the app can convert recipe units to grams without repeated lookups.

Public API
----------
  lookup(name)           → list[NutritionResult]  (ranked candidates)
  best_match(name)       → NutritionResult | None  (auto-pick or None)
  result_to_db_kwargs(r) → dict  (ready to pass to db.create_ingredient)

Configuration
-------------
Set the USDA API key in one of:
  - Environment variable:  USDA_API_KEY=your_key
  - .env file in the project root:  USDA_API_KEY=your_key
  - Pass directly:  lookup(name, usda_api_key="your_key")

A free key (rate-limited) is used as the fallback demo key.
Get your own at: https://fdc.nal.usda.gov/api-guide.html
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USDA_API_BASE = "https://api.nal.usda.gov/fdc/v1"
OFF_API_BASE  = "https://world.openfoodfacts.org/cgi/search.pl"

# Confidence thresholds: >= HIGH → auto-pick; < LOW → always show options
CONFIDENCE_HIGH = 0.75
CONFIDENCE_LOW  = 0.40

# How many candidates to return when confidence is below HIGH
MAX_CANDIDATES = 5

# Request timeout in seconds
REQUEST_TIMEOUT = 10

# USDA food types preferred for raw ingredients (in priority order)
USDA_PREFERRED_DATA_TYPES = [
    "SR Legacy",        # USDA Standard Reference — raw ingredients
    "Foundation",       # Foundation Foods — detailed raw data
    "Survey (FNDDS)",   # What We Eat in America
    "Branded",          # Branded products (lowest preference)
]


def _get_usda_api_key(override: Optional[str] = None) -> str:
    """Resolve the USDA API key from override → env var → .env file → demo key."""
    if override:
        return override
    if key := os.environ.get("USDA_API_KEY"):
        return key
    # Try a .env file in the same directory as this module
    env_file = Path(__file__).with_name(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("USDA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    # Fall back to the USDA demo key (1000 req/day, 30 req/min)
    return "DEMO_KEY"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class NutritionResult:
    """
    A single ingredient candidate returned by a lookup.
    All nutrition values are per 100g.
    Portion fields describe a typical serving size from the data source.
    """
    # Identity
    ingredient_name: str          # canonical name from data source
    source: str                   # "usda" or "open_food_facts"
    source_id: str                # USDA fdcId or OFF barcode/id
    source_url: str               # direct URL to the data source record

    # Portion (for unit conversion in recipes)
    portion_unit: str             # e.g. "1 cup"
    portion_grams: float          # e.g. 90.0  (grams per one portion)

    # Nutrition per 100g (None = not available in source)
    calories:      Optional[float] = None
    protein_grams: Optional[float] = None
    fat_grams:     Optional[float] = None
    carb_grams:    Optional[float] = None
    fiber_grams:   Optional[float] = None

    # Internal scoring (not exposed to callers)
    confidence:    float = 0.0
    data_type:     str   = ""     # USDA data type string, if applicable
    all_portions:  list  = field(default_factory=list)  # all available portions

    def nutrition_complete(self) -> bool:
        """True if all five nutrition fields are populated."""
        return all(v is not None for v in [
            self.calories, self.protein_grams, self.fat_grams,
            self.carb_grams, self.fiber_grams,
        ])

    def summary(self) -> str:
        """One-line human-readable summary for display."""
        cal  = f"{self.calories:.0f} kcal" if self.calories is not None else "? kcal"
        prot = f"{self.protein_grams:.1f}g protein" if self.protein_grams is not None else "? protein"
        portion = f"{self.portion_unit} = {self.portion_grams:.0f}g"
        return (
            f"{self.ingredient_name}  [{self.source}]  "
            f"{cal}, {prot} per 100g  |  portion: {portion}"
        )


def result_to_db_kwargs(result: NutritionResult) -> dict:
    """
    Convert a NutritionResult to a dict of kwargs ready for
    db.create_ingredient() or db.update_ingredient_nutrition().
    """
    return {
        "portion_unit":          result.portion_unit,
        "portion_grams":         result.portion_grams,
        "calories":              result.calories,
        "protein_grams":         result.protein_grams,
        "fat_grams":             result.fat_grams,
        "carb_grams":            result.carb_grams,
        "fiber_grams":           result.fiber_grams,
        "source_food_name":      result.ingredient_name,
        "nutrition_info_source": (
            f"USDA: {result.ingredient_name}" if result.source == "usda"
            else f"{result.source}: {result.ingredient_name}"
        ),
    }


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get_json(url: str, params: Optional[dict] = None) -> dict | list | None:
    """
    Make a GET request and return parsed JSON, or None on error.
    Raises urllib.error.HTTPError for HTTP errors so callers can handle them.
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "FoodLogApp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimitError("API rate limit exceeded. Try again in a moment.") from e
        raise
    except urllib.error.URLError as e:
        raise NetworkError(f"Network error reaching {url}: {e}") from e


def _post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict | list | None:
    """Make a POST request with JSON body and return parsed JSON."""
    body = json.dumps(payload).encode()
    req_headers = {"Content-Type": "application/json", "User-Agent": "FoodLogApp/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimitError("API rate limit exceeded.") from e
        raise
    except urllib.error.URLError as e:
        raise NetworkError(f"Network error: {e}") from e


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class LookupError(Exception):
    """Base class for nutrition lookup errors."""

class NetworkError(LookupError):
    """Raised when a network request fails."""

class RateLimitError(LookupError):
    """Raised when an API rate limit is hit."""

class NoResultsError(LookupError):
    """Raised when no nutrition data is found for the query."""


# ---------------------------------------------------------------------------
# USDA FoodData Central
# ---------------------------------------------------------------------------

# Nutrient IDs in USDA FoodData Central
_USDA_NUTRIENT_IDS = {
    "calories":      1008,   # Energy (kcal)
    "protein_grams": 1003,   # Protein
    "fat_grams":     1004,   # Total lipids (fat)
    "carb_grams":    1005,   # Carbohydrate, by difference
    "fiber_grams":   1079,   # Fiber, total dietary
}

# Preferred portion unit keywords (matched against USDA measure descriptions)
_PREFERRED_PORTION_KEYWORDS = [
    "cup", "tbsp", "tablespoon", "tsp", "teaspoon",
    "oz", "ounce", "slice", "piece", "medium", "large", "small",
]


def _usda_data_type_priority(data_type: str) -> int:
    """Lower = higher priority."""
    for i, dt in enumerate(USDA_PREFERRED_DATA_TYPES):
        if dt.lower() in data_type.lower():
            return i
    return len(USDA_PREFERRED_DATA_TYPES)


def _extract_usda_nutrients(food: dict) -> dict[str, Optional[float]]:
    """Pull the five key nutrients from a USDA food dict.

    The /foods/search endpoint returns flat entries like
    {"nutrientId": 1008, "value": 389}, while the /food/{fdcId} detail
    endpoint nests them as {"nutrient": {"id": 1008}, "amount": 389}.
    Handle both shapes.
    """
    nutrients = {}
    nutrient_map = {}
    for n in food.get("foodNutrients", []):
        nid = n["nutrient"]["id"] if "nutrient" in n else n.get("nutrientId")
        if nid is not None:
            nutrient_map[nid] = n
    for key, nid in _USDA_NUTRIENT_IDS.items():
        entry = nutrient_map.get(nid)
        if entry is None:
            nutrients[key] = None
            continue
        value = entry["amount"] if "amount" in entry else entry.get("value")
        nutrients[key] = round(value, 2) if value is not None else None
    return nutrients


def _extract_usda_portions(food: dict) -> tuple[str, float, list]:
    """
    Extract the best portion and all available portions from a USDA food dict.
    Returns (portion_unit, portion_grams, all_portions).
    Falls back to 100g if no portions available.
    """
    measures = food.get("foodMeasures", [])
    all_portions = []

    for m in measures:
        desc        = m.get("disseminationText", m.get("measureDescription", ""))
        grams       = m.get("gramWeight")
        if grams and desc:
            all_portions.append({
                "unit":   desc,
                "grams":  float(grams),
            })

    # SR Legacy / Foundation foods describe portions via
    # foodPortions: {"amount": 1.0, "modifier": "cup", "gramWeight": 156.0}.
    # Survey (FNDDS) foods instead have a human-readable "portionDescription"
    # (e.g. "1 small") and a numeric "modifier" portion code (not a unit).
    if not all_portions:
        for p in food.get("foodPortions", []):
            grams = p.get("gramWeight")
            if not grams:
                continue
            desc = p.get("portionDescription", "")
            if not desc or desc.lower() == "quantity not specified":
                amount   = p.get("amount")
                modifier = p.get("modifier", "")
                if not modifier or modifier.lower() == "undetermined" or modifier.isdigit():
                    continue
                desc = f"{amount:g} {modifier}" if amount else modifier
            all_portions.append({
                "unit":   desc,
                "grams":  float(grams),
            })

    # Check top-level serving size (Branded foods)
    if not all_portions:
        srv_size = food.get("servingSize")
        srv_unit = food.get("servingSizeUnit", "g")
        if srv_size:
            all_portions.append({
                "unit":   srv_unit,
                "grams":  float(srv_size),
            })

    if not all_portions:
        # Default: plain grams (1 unit = 1g)
        return "g", 1.0, []

    # Pick the best portion: prefer recognisable volume/unit measures
    def portion_score(p: dict) -> int:
        unit_lower = p["unit"].lower()
        for i, kw in enumerate(_PREFERRED_PORTION_KEYWORDS):
            if kw in unit_lower:
                return i
        return 99

    best = min(all_portions, key=portion_score)
    return best["unit"], best["grams"], all_portions


def _singular(word: str) -> str:
    """Crude singularization so "apple" matches "apples"."""
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _score_usda_result(query: str, food: dict) -> float:
    """
    Score 0–1 for how well this USDA food matches the query.
    Higher = better match.
    """
    desc = food.get("description", "").lower()
    query_lower = query.lower()
    query_words = {_singular(w) for w in query_lower.split()}

    # Resolve data_type up front so it's available for all branches.
    # Kept small relative to word/head scoring so it acts as a tiebreaker,
    # not something that alone can push an irrelevant match to "high confidence".
    data_type  = food.get("dataType", "")
    type_boost = max(0.0, 0.04 * (len(USDA_PREFERRED_DATA_TYPES) - _usda_data_type_priority(data_type)))

    # Exact match — factor in data type so SR Legacy beats Branded on equal names
    if desc == query_lower:
        return min(1.0, 0.9 + type_boost)

    # Word overlap (singular-normalised so "apple" matches "apples, raw")
    desc_words = {_singular(w) for w in re.findall(r'\w+', desc)}
    overlap = query_words & desc_words
    word_score = len(overlap) / max(len(query_words), 1)

    # Penalise if query words appear but description has many extra words
    # (e.g. query="oats" shouldn't score a "granola bar with oats" highly)
    extra_words = len(desc_words - query_words)
    brevity_penalty = max(0.0, 1.0 - (extra_words / max(len(desc_words), 1)) * 0.5)

    # Bonus if the query matches the head term of the description (the part
    # before the first comma), e.g. "Apples, raw" for query "apple".
    # Without this, modifier matches like "Croissants, apple" can outscore
    # the actual food the user is looking for. Only applies when the
    # description actually has a "Head, modifiers" structure.
    head_bonus = 0.0
    if ',' in desc:
        head_words = {_singular(w) for w in re.findall(r'\w+', desc.split(',')[0])}
        if query_words and query_words <= head_words:
            head_bonus = 0.15

    return min(1.0, word_score * brevity_penalty + type_boost + head_bonus)


def _search_usda(
    query: str, api_key: str, max_results: int = 10
) -> list[NutritionResult]:
    """
    Search USDA FoodData Central and return NutritionResult candidates.
    Uses the /foods/search endpoint, then fetches full detail for top hits.
    """
    # Step 1: search. Fetch more than max_results so that less-common data
    # types (e.g. SR Legacy) aren't crowded out by Branded products before
    # we get a chance to score and rank them ourselves.
    search_payload = {
        "query":         query,
        "dataType":      USDA_PREFERRED_DATA_TYPES,
        "pageSize":      max(max_results * 5, 50),
    }
    url = f"{USDA_API_BASE}/foods/search?api_key={api_key}"
    data = _post_json(url, search_payload)
    if not data or not data.get("foods"):
        return []

    results = []
    for food in data["foods"]:
        fdc_id    = food.get("fdcId")
        desc      = food.get("description", "Unknown")
        data_type = food.get("dataType", "")

        # Extract nutrients directly from search result (saves a round-trip)
        nutrients = _extract_usda_nutrients(food)

        # Portions require a detail fetch (not in search results)
        # We fetch detail only for top candidates to save API calls
        portion_unit, portion_grams, all_portions = "g", 1.0, []

        confidence = _score_usda_result(query, food)
        source_url = f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{fdc_id}/nutrients"

        results.append(NutritionResult(
            ingredient_name = desc,
            source          = "usda",
            source_id       = str(fdc_id),
            source_url      = source_url,
            portion_unit    = portion_unit,
            portion_grams   = portion_grams,
            confidence      = confidence,
            data_type       = data_type,
            all_portions    = all_portions,
            **nutrients,
        ))

    # Step 2: keep only the top candidates, then fetch full detail for the
    # top 3 to get portion data
    results.sort(key=lambda r: -r.confidence)
    results = results[:max_results]
    for result in results[:3]:
        try:
            detail = _get_json(
                f"{USDA_API_BASE}/food/{result.source_id}",
                params={"api_key": api_key},
            )
            if detail:
                pu, pg, all_p = _extract_usda_portions(detail)
                result.portion_unit   = pu
                result.portion_grams  = pg
                result.all_portions   = all_p
                # Also refresh nutrients from detail (more complete)
                refreshed = _extract_usda_nutrients(detail)
                for k, v in refreshed.items():
                    if v is not None:
                        setattr(result, k, v)
        except Exception:
            pass  # Detail fetch is best-effort; we already have the basics

    return results


# ---------------------------------------------------------------------------
# Open Food Facts
# ---------------------------------------------------------------------------

def _extract_off_nutrients(product: dict) -> dict[str, Optional[float]]:
    """Extract the five key nutrients from an OFF product dict (per 100g)."""
    n = product.get("nutriments", {})
    def get_n(key: str) -> Optional[float]:
        v = n.get(f"{key}_100g")
        return round(float(v), 2) if v is not None else None

    return {
        "calories":      get_n("energy-kcal"),
        "protein_grams": get_n("proteins"),
        "fat_grams":     get_n("fat"),
        "carb_grams":    get_n("carbohydrates"),
        "fiber_grams":   get_n("fiber"),
    }


def _extract_off_portions(product: dict) -> tuple[str, float, list]:
    """Extract serving size from an OFF product. Falls back to 100g.

    Handles strings like "30 g", "240 ml", "1 cup (240ml)".
    When multiple unit matches exist (e.g. "1 cup (240ml)"), the last
    numeric+unit pair is used since it tends to be the gram/ml weight.
    """
    srv = product.get("serving_size", "")
    if srv:
        # Find all numeric+unit pairs; use the last one (most likely the weight)
        matches = re.findall(r"([\d.]+)\s*(g|ml|oz|cup|tbsp|tsp)", srv, re.IGNORECASE)
        if matches:
            # Prefer g or ml match over cup/tbsp since those are actual weights
            weight_matches = [(v, u) for v, u in matches if u.lower() in ("g", "ml")]
            val_str, unit = weight_matches[-1] if weight_matches else matches[-1]
            grams = float(val_str)
            unit  = unit.lower()
            portion = {"unit": unit, "grams": grams}
            return unit, grams, [portion]
    return "g", 100.0, []


def _score_off_result(query: str, product: dict) -> float:
    """Score 0–1 for OFF product match quality."""
    name = (
        product.get("product_name_en")
        or product.get("product_name")
        or ""
    ).lower()
    query_lower = query.lower()
    query_words = set(query_lower.split())

    if not name:
        return 0.0
    if name == query_lower:
        return 0.93  # cap at 0.93; USDA SR Legacy preferred for exact matches

    name_words = set(re.findall(r'\w+', name))
    overlap = query_words & name_words
    word_score = len(overlap) / max(len(query_words), 1)
    extra_penalty = max(0.0, 1.0 - (len(name_words - query_words) / max(len(name_words), 1)) * 0.4)

    # Prefer products with complete nutrition data
    nutrients = _extract_off_nutrients(product)
    completeness_boost = 0.05 * sum(1 for v in nutrients.values() if v is not None)

    return min(0.97, word_score * extra_penalty + completeness_boost)


def _search_off(query: str, max_results: int = 10) -> list[NutritionResult]:
    """
    Search Open Food Facts and return NutritionResult candidates.
    """
    params = {
        "search_terms":  query,
        "search_simple": 1,
        "action":        "process",
        "json":          1,
        "page_size":     max_results,
        "fields": (
            "product_name,product_name_en,nutriments,"
            "serving_size,id,brands,categories"
        ),
    }
    data = _get_json(OFF_API_BASE, params)
    if not data or not data.get("products"):
        return []

    results = []
    for product in data["products"][:max_results]:
        pid  = product.get("id", product.get("_id", "unknown"))
        name = (
            product.get("product_name_en")
            or product.get("product_name")
            or "Unknown product"
        )
        nutrients   = _extract_off_nutrients(product)
        pu, pg, all_p = _extract_off_portions(product)
        confidence  = _score_off_result(query, product)
        source_url  = f"https://world.openfoodfacts.org/product/{pid}"

        results.append(NutritionResult(
            ingredient_name = name,
            source          = "open_food_facts",
            source_id       = str(pid),
            source_url      = source_url,
            portion_unit    = pu,
            portion_grams   = pg,
            confidence      = confidence,
            all_portions    = all_p,
            **nutrients,
        ))

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup(
    name: str,
    *,
    usda_api_key: Optional[str] = None,
    max_candidates: int = MAX_CANDIDATES,
    include_off: bool = True,
) -> list[NutritionResult]:
    """
    Search for nutrition data for `name` across USDA and (optionally) OFF.

    Returns a ranked list of NutritionResult candidates (best first).
    The list may be empty if nothing is found.

    Parameters
    ----------
    name            : ingredient name to search for (e.g. "rolled oats")
    usda_api_key    : override API key (else uses env/config/demo)
    max_candidates  : maximum number of results to return
    include_off     : if True, also search Open Food Facts as a fallback
    """
    name = name.strip()
    if not name:
        raise ValueError("name cannot be empty.")

    api_key = _get_usda_api_key(usda_api_key)
    all_results: list[NutritionResult] = []

    # USDA first
    try:
        usda_results = _search_usda(name, api_key, max_results=max_candidates * 2)
        all_results.extend(usda_results)
    except (NetworkError, RateLimitError):
        raise
    except Exception as e:
        # USDA failed for an unexpected reason — continue to OFF
        pass

    # OFF as complement / fallback
    if include_off:
        try:
            off_results = _search_off(name, max_results=max_candidates * 2)
            all_results.extend(off_results)
        except (NetworkError, RateLimitError):
            raise
        except Exception:
            pass  # OFF is best-effort

    if not all_results:
        return []

    # Deduplicate by normalised name (keep highest-confidence duplicate)
    seen: dict[str, NutritionResult] = {}
    for r in all_results:
        key = re.sub(r'\s+', ' ', r.ingredient_name.lower().strip())
        if key not in seen or r.confidence > seen[key].confidence:
            seen[key] = r

    ranked = sorted(seen.values(), key=lambda r: -r.confidence)
    return ranked[:max_candidates]


def best_match(
    name: str,
    *,
    usda_api_key: Optional[str] = None,
) -> Optional[NutritionResult]:
    """
    Return the single best NutritionResult for `name`, or None if not found.

    Auto-picks when confidence >= CONFIDENCE_HIGH.
    Returns the top candidate regardless when confidence is lower, so the
    caller can decide whether to present options to the user.

    The returned result has a `.confidence` attribute (0–1) and a
    `.nutrition_complete()` method the caller can check.
    """
    candidates = lookup(name, usda_api_key=usda_api_key, max_candidates=MAX_CANDIDATES)
    if not candidates:
        return None
    return candidates[0]


def should_auto_pick(result: NutritionResult) -> bool:
    """True if confidence is high enough to skip user confirmation."""
    return result.confidence >= CONFIDENCE_HIGH


def format_candidates_for_display(
    candidates: list[NutritionResult],
) -> str:
    """
    Format a list of candidates as a numbered list for display to the user.
    """
    if not candidates:
        return "No results found."
    lines = []
    for i, r in enumerate(candidates, 1):
        conf_label = (
            "high confidence" if r.confidence >= CONFIDENCE_HIGH
            else "low confidence" if r.confidence < CONFIDENCE_LOW
            else "medium confidence"
        )
        lines.append(f"{i}. [{conf_label}] {r.summary()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI — useful for manual testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "rolled oats"
    print(f"\nSearching for: '{query}'\n{'─' * 60}")

    try:
        candidates = lookup(query)
    except NetworkError as e:
        print(f"Network error: {e}")
        sys.exit(1)
    except RateLimitError as e:
        print(f"Rate limit: {e}")
        sys.exit(1)

    if not candidates:
        print("No results found.")
        sys.exit(0)

    best = candidates[0]
    auto = should_auto_pick(best)

    print(format_candidates_for_display(candidates))
    print(f"\n{'─' * 60}")
    if auto:
        print(f"✓ Auto-pick: #{1}  '{best.ingredient_name}' (confidence={best.confidence:.2f})")
    else:
        print(f"⚠ Low confidence — user should confirm from list above.")

    print(f"\nDB kwargs for '{best.ingredient_name}':")
    for k, v in result_to_db_kwargs(best).items():
        print(f"  {k}: {v}")
