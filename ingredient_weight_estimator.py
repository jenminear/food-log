"""
ingredient_weight_estimator.py — AI fallback weight estimation
==================================================================
Last-resort estimate of an ingredient quantity's weight in grams, used
only when unitConversion.js's table-based and density-based conversions
both fail — typically count-based amounts with no fixed weight ("2
avocados", "1 large onion") or vague phrases ("a pinch", "to taste").

This is intentionally a separate module/call from recipe_extraction.py:
extraction's search_name cleanup runs for every ingredient inside one
already-paid-for call, but weight estimation is a per-ingredient, opt-in
fallback that should NOT multiply the cost of every recipe import — it
only fires for the subset of ingredients that genuinely have no other
way to resolve a quantity.

Public API
----------
  estimate_grams(ingredient_name, quantity, unit, api_key) -> WeightEstimate | None

Configuration
-------------
Requires the same ANTHROPIC_API_KEY as recipe_extraction.py (get one at
https://console.anthropic.com/settings/keys). Model defaults to
RECIPE_EXTRACTION_MODEL / "claude-haiku-4-5-20251001".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class EstimationError(Exception):
    """Raised when the model call itself fails (network/API error)."""


@dataclass
class WeightEstimate:
    grams: float
    confidence: str  # "high" | "low" — surfaced to the user as a data-quality-style warning


_ESTIMATE_TOOL = {
    "name": "record_weight_estimate",
    "description": "Record an estimated weight in grams for a recipe ingredient quantity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "found": {
                "type": "boolean",
                "description": "Whether a reasonable weight estimate could be made at all. "
                               "False for amounts too vague to estimate (e.g. 'a pinch', "
                               "'to taste', 'as needed').",
            },
            "grams": {
                "type": ["number", "null"],
                "description": "Best-guess TOTAL weight in grams for the full stated quantity "
                               "(e.g. for '2 large bananas', the combined weight of both).",
            },
            "confidence": {
                "type": ["string", "null"],
                "enum": ["high", "low"],
                "description": "'high' for common, fairly consistent items (e.g. 'large egg', "
                               "'medium banana'). 'low' for highly variable or unusual items.",
            },
        },
        "required": ["found"],
    },
}


def estimate_grams(
    ingredient_name: str,
    quantity: Optional[float],
    unit: Optional[str],
    api_key: str,
) -> Optional[WeightEstimate]:
    """
    Ask Claude for a best-guess total weight (in grams) for `quantity` of
    `unit` of `ingredient_name`, e.g.:
        estimate_grams("banana", 2, "large bananas", key)
        -> WeightEstimate(grams=240.0, confidence="high")

    Returns None if no reasonable estimate could be made (the caller
    should fall back to manual entry in that case).
    Raises EstimationError on a model/API failure.
    """
    import anthropic

    model = os.environ.get("RECIPE_EXTRACTION_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(api_key=api_key)

    quantity_text = f"{quantity} {unit}".strip() if quantity is not None else (unit or "some amount")
    prompt = (
        f"Estimate the total weight in grams of: {quantity_text} {ingredient_name}.\n"
        "Use typical real-world weights for common foods (e.g. a large egg is about 50g, "
        "a medium banana is about 120g). If the amount is too vague or variable to "
        "reasonably estimate, set found to false rather than guessing."
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=256,
            tools=[_ESTIMATE_TOOL],
            tool_choice={"type": "tool", "name": "record_weight_estimate"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        raise EstimationError(f"Weight estimation failed: {e}") from e

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise EstimationError("Weight estimation failed: no structured response from model.")

    data = tool_use.input
    if not data.get("found") or data.get("grams") is None:
        return None
    return WeightEstimate(
        grams=float(data["grams"]),
        confidence=data.get("confidence") or "low",
    )
