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

import httpx
from bs4 import BeautifulSoup

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
REQUEST_TIMEOUT = 20
MAX_PAGE_TEXT_CHARS = 15000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ExtractionError(Exception):
    """Raised when a recipe could not be found in the provided content."""


class FetchError(ExtractionError):
    """Raised when the source URL could not be fetched."""


@dataclass
class ExtractedIngredient:
    name:     str
    quantity: Optional[float] = None
    unit:     Optional[str] = None


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
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
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
                        "name": {"type": "string"},
                        "quantity": {"type": ["number", "null"]},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["name"],
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
