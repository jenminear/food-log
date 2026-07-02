"""
recipe_extraction.py — AI Recipe Extraction Module
====================================================
Extracts structured recipe data (name, servings, times, dietary flags,
ingredients, and steps) from either a recipe web page or a photo of a
recipe, using the Anthropic API (Claude with vision).

Public API
----------
  extract_recipe_from_url(url, api_key)          -> ExtractedRecipe
  extract_recipe_from_image(data, media_type, api_key) -> ExtractedRecipe

Configuration
-------------
Requires an Anthropic API key (`sk-ant-...`), set as `ANTHROPIC_API_KEY`
in the environment or `.env` file. Get one at:
  https://console.anthropic.com/settings/keys

The extraction model defaults to "claude-haiku-4-5-20251001" and can be
overridden with the `RECIPE_EXTRACTION_MODEL` environment variable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
REQUEST_TIMEOUT = 20
MAX_PAGE_TEXT_CHARS = 15000

# Many recipe sites (AllRecipes, Food Network, Simply Recipes, The Kitchn,
# ...) sit behind bot-detection (e.g. Cloudflare) that fingerprints the
# TLS handshake / header ordering of the HTTP client itself — a plain
# httpx/requests GET gets a 403 even with a perfectly normal Chrome
# User-Agent header. curl_cffi's impersonate="chrome" mode reproduces a
# real Chrome TLS fingerprint and gets through where httpx could not.
IMPERSONATE = "chrome"


class ExtractionError(Exception):
    """Raised when a recipe could not be found in the provided content."""


class FetchError(ExtractionError):
    """Raised when the source URL could not be fetched."""


class InvalidUrlError(FetchError):
    """Raised when the given URL is malformed — a client input error, not a fetch failure."""


@dataclass
class ExtractedIngredient:
    name:        str
    quantity:    Optional[float] = None
    unit:        Optional[str] = None
    # A short, clean core ingredient name (e.g. "tomato", "red onion") with
    # prep instructions, descriptors ("ripe", "finely chopped"), and "or"
    # alternatives stripped out — used as the nutrition-database search
    # query instead of `name`, since searching the full descriptive phrase
    # tends to surface irrelevant branded products (e.g. "ripe tomato,
    # chopped (optional)" matches "CHOPPED RIPE OLIVES" over any tomato).
    search_name: Optional[str] = None
    # The amount exactly as written in the source recipe (e.g. "1 (15-oz)
    # can", "2 tbsp", "a pinch") — richer than `quantity`/`unit` alone,
    # which are a simplified numeric approximation used for unit
    # conversion. Stored verbatim on the component for display, since a
    # user reading "44g" has no intuition for how many cups/cans that was.
    original_quantity_text: Optional[str] = None


@dataclass
class ExtractedRecipe:
    recipe_name:      Optional[str] = None
    num_servings:     Optional[float] = None
    active_time_mins: Optional[int] = None
    total_time_mins:  Optional[int] = None
    need_oven:        bool = False
    vegetarian:       bool = False
    vegan:            bool = False
    ingredients:      list[ExtractedIngredient] = field(default_factory=list)
    steps:            list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def extract_recipe_from_url(url: str, api_key: str) -> ExtractedRecipe:
    """Fetch a recipe web page and extract structured recipe data from it."""
    if not re.match(r"^https?://", url.strip(), re.IGNORECASE):
        raise InvalidUrlError(
            "That doesn't look like a valid URL — it should start with http:// or https://."
        )

    try:
        resp = curl_requests.get(
            url,
            impersonate=IMPERSONATE,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except curl_requests.exceptions.HTTPError as e:
        raise FetchError(f"Could not fetch the URL: {e}") from e
    except curl_requests.exceptions.RequestException as e:
        raise FetchError(f"Could not fetch the URL: {e}") from e

    page_text = _extract_page_text(resp.text)
    if not page_text.strip():
        raise FetchError("The page appears to have no readable content.")

    content_blocks = [
        {"type": "text", "text": f"Web page content:\n\n{page_text}"},
    ]
    return _call_claude_extract(content_blocks, api_key)


def extract_recipe_from_image(data: bytes, media_type: str, api_key: str) -> ExtractedRecipe:
    """Extract structured recipe data from a photo of a recipe."""
    import base64
    encoded = base64.b64encode(data).decode("ascii")
    content_blocks = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": encoded},
        },
        {"type": "text", "text": "Extract the recipe shown in this image."},
    ]
    return _call_claude_extract(content_blocks, api_key)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _extract_page_text(html: str) -> str:
    """Strip non-content tags and collapse whitespace, truncating to a safe length."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()[:MAX_PAGE_TEXT_CHARS]


_RECIPE_TOOL = {
    "name": "record_recipe",
    "description": "Record the structured recipe extracted from the provided content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "found": {
                "type": "boolean",
                "description": "Whether a recipe was found in the provided content.",
            },
            "recipe_name": {"type": ["string", "null"]},
            "num_servings": {"type": ["number", "null"]},
            "active_time_mins": {"type": ["integer", "null"]},
            "total_time_mins": {"type": ["integer", "null"]},
            "need_oven": {"type": "boolean"},
            "vegetarian": {"type": "boolean"},
            "vegan": {"type": "boolean"},
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The ingredient exactly as written in the recipe, "
                                           "including any prep notes (e.g. \"ripe tomato, "
                                           "chopped (optional)\").",
                        },
                        "quantity": {"type": ["number", "null"]},
                        "unit": {"type": ["string", "null"]},
                        "search_name": {
                            "type": "string",
                            "description": "A short (1-4 word) core ingredient name suitable "
                                           "for searching a nutrition database — strip prep "
                                           "instructions, descriptors (\"ripe\", \"fresh\", "
                                           "\"finely chopped\"), and parenthetical asides, and "
                                           "pick the first option from any \"X or Y\" "
                                           "alternatives. E.g. \"ripe tomato, chopped "
                                           "(optional)\" -> \"tomato\"; \"serrano (or "
                                           "jalapeno) chilis, stems and seeds removed, minced\" "
                                           "-> \"serrano pepper\"; \"minced red onion or thinly "
                                           "sliced green onion\" -> \"red onion\".",
                        },
                        "original_quantity_text": {
                            "type": ["string", "null"],
                            "description": "The amount exactly as written in the recipe, "
                                           "verbatim — e.g. \"1 (15-ounce/425g) can\", "
                                           "\"2 tbsp\", \"a pinch\", \"to taste\". Keep any "
                                           "parenthetical detail (can sizes, weights) that "
                                           "`quantity`/`unit` alone would lose. Null only if "
                                           "no amount is given at all.",
                        },
                    },
                    "required": ["name", "search_name"],
                    "additionalProperties": False,
                },
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["found"],
    },
}


def _call_claude_extract(content_blocks: list[dict], api_key: str) -> ExtractedRecipe:
    import anthropic

    model = os.environ.get("RECIPE_EXTRACTION_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            tools=[_RECIPE_TOOL],
            tool_choice={"type": "tool", "name": "record_recipe"},
            messages=[{"role": "user", "content": content_blocks}],
        )
    except anthropic.APIError as e:
        raise ExtractionError(f"Recipe extraction failed: {e}") from e

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise ExtractionError("Recipe extraction failed: no structured response from model.")

    data = tool_use.input
    if not data.get("found"):
        raise ExtractionError("Couldn't find a recipe in the provided content.")

    ingredients = [
        ExtractedIngredient(
            name=i["name"],
            quantity=i.get("quantity"),
            unit=i.get("unit"),
            search_name=i.get("search_name") or i["name"],
            original_quantity_text=i.get("original_quantity_text"),
        )
        for i in data.get("ingredients", [])
    ]

    return ExtractedRecipe(
        recipe_name=data.get("recipe_name"),
        num_servings=data.get("num_servings"),
        active_time_mins=data.get("active_time_mins"),
        total_time_mins=data.get("total_time_mins"),
        need_oven=bool(data.get("need_oven", False)),
        vegetarian=bool(data.get("vegetarian", False)),
        vegan=bool(data.get("vegan", False)),
        ingredients=ingredients,
        steps=data.get("steps", []),
    )
