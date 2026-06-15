"""
test_recipe_extraction.py — Tests for AI recipe extraction
=============================================================
Tests the recipe_extraction module's parsing logic with a mocked Anthropic
client (no real network calls), and the /recipes/extract/* endpoints'
behavior when ANTHROPIC_API_KEY is not configured.

Run with:
    pytest test_recipe_extraction.py -v
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import dependencies
from fastapi.testclient import TestClient
from main import app

import recipe_extraction as RE

SCHEMA_SQL = (Path(__file__).with_name("food_log_schema.sql")).read_text()


def _make_in_memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def _tool_use_response(input_dict):
    block = MagicMock()
    block.type = "tool_use"
    block.input = input_dict
    response = MagicMock()
    response.content = [block]
    return response


class TestCallClaudeExtract(unittest.TestCase):
    """Unit tests for _call_claude_extract's parsing logic."""

    def _patched_client(self, response):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response
        return patch("anthropic.Anthropic", return_value=mock_client)

    def test_parses_full_recipe(self):
        response = _tool_use_response({
            "found": True,
            "recipe_name": "Veggie Bowl",
            "num_servings": 4,
            "active_time_mins": 15,
            "total_time_mins": 30,
            "need_oven": True,
            "vegetarian": True,
            "vegan": False,
            "ingredients": [
                {"name": "rolled oats", "quantity": 2, "unit": "cups"},
                {"name": "salt", "quantity": None, "unit": None},
            ],
            "steps": ["Preheat oven.", "Mix ingredients."],
        })
        with self._patched_client(response):
            result = RE._call_claude_extract([{"type": "text", "text": "..."}], "sk-ant-fake")

        self.assertEqual(result.recipe_name, "Veggie Bowl")
        self.assertEqual(result.num_servings, 4)
        self.assertEqual(result.active_time_mins, 15)
        self.assertEqual(result.total_time_mins, 30)
        self.assertTrue(result.need_oven)
        self.assertTrue(result.vegetarian)
        self.assertFalse(result.vegan)
        self.assertEqual(len(result.ingredients), 2)
        self.assertEqual(result.ingredients[0].name, "rolled oats")
        self.assertEqual(result.ingredients[0].quantity, 2)
        self.assertEqual(result.ingredients[0].unit, "cups")
        self.assertIsNone(result.ingredients[1].quantity)
        self.assertEqual(result.steps, ["Preheat oven.", "Mix ingredients."])

    def test_not_found_raises_extraction_error(self):
        response = _tool_use_response({"found": False})
        with self._patched_client(response):
            with self.assertRaises(RE.ExtractionError):
                RE._call_claude_extract([{"type": "text", "text": "..."}], "sk-ant-fake")

    def test_no_tool_use_block_raises_extraction_error(self):
        response = MagicMock()
        response.content = []
        with self._patched_client(response):
            with self.assertRaises(RE.ExtractionError):
                RE._call_claude_extract([{"type": "text", "text": "..."}], "sk-ant-fake")


class TestExtractPageText(unittest.TestCase):
    def test_strips_scripts_and_collapses_whitespace(self):
        html = """
        <html><head><script>var x = 1;</script><style>body{}</style></head>
        <body><nav>Home</nav><main>  Recipe   Title  \n\n\n  Ingredients  </main></body></html>
        """
        text = RE._extract_page_text(html)
        self.assertNotIn("var x", text)
        self.assertNotIn("Home", text)
        self.assertIn("Recipe", text)
        self.assertIn("Ingredients", text)


class TestExtractEndpoints(unittest.TestCase):
    """Without ANTHROPIC_API_KEY configured, the endpoints should 503."""

    def setUp(self):
        self.conn = _make_in_memory_conn()
        app.dependency_overrides[dependencies.get_db] = lambda: self.conn
        app.dependency_overrides[dependencies.require_auth] = lambda: None
        self.client = TestClient(app, raise_server_exceptions=True)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.conn.close()

    def test_extract_from_url_without_api_key_returns_503(self):
        with patch("dependencies.get_anthropic_api_key", return_value=None), \
             patch("routers.recipes.get_anthropic_api_key", return_value=None):
            r = self.client.post("/recipes/extract/url", json={"url": "https://example.com/recipe"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", r.json()["detail"])

    def test_extract_from_image_without_api_key_returns_503(self):
        with patch("dependencies.get_anthropic_api_key", return_value=None), \
             patch("routers.recipes.get_anthropic_api_key", return_value=None):
            r = self.client.post(
                "/recipes/extract/image",
                files={"file": ("recipe.jpg", b"fake-image-bytes", "image/jpeg")},
            )
        self.assertEqual(r.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
