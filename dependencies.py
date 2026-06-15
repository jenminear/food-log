"""
dependencies.py — FastAPI Dependency Injection
===============================================
Provides reusable FastAPI dependencies for:
  - Database connection management
  - Optional API key authentication
  - Session store for multi-step flows (recipe add, meal record)

Usage in a router:
    from dependencies import get_db, require_auth

    @router.post("/recipes")
    def create(req: RecipeRequest, conn=Depends(get_db), _=Depends(require_auth)):
        ...
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status

import db as DB

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR   = Path(__file__).parent
DB_PATH    = BASE_DIR / "food_log.db"
IMAGES_DIR = BASE_DIR / "images"

# Ensure image subdirectories exist
for subdir in ("recipes", "batches", "sources"):
    (IMAGES_DIR / subdir).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Database dependency
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    """
    FastAPI dependency that yields a database connection per request.
    The connection is closed automatically after the response is sent.
    Uses WAL mode and foreign key enforcement.
    """
    conn = DB.get_connection(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


DbConn = Annotated[sqlite3.Connection, Depends(get_db)]


# ---------------------------------------------------------------------------
# API key authentication (optional — disabled by default)
# ---------------------------------------------------------------------------

def _get_api_key_secret() -> Optional[str]:
    """
    Read the API key from environment or .env file.
    Returns None if no key is configured (auth disabled).
    """
    if key := os.environ.get("FOOD_LOG_API_KEY"):
        return key
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("FOOD_LOG_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def require_auth(x_api_key: Annotated[Optional[str], Header()] = None) -> None:
    """
    FastAPI dependency for optional API key auth.

    - If FOOD_LOG_API_KEY is not configured: all requests pass through.
    - If FOOD_LOG_API_KEY is configured: requests must include an
      X-Api-Key header matching the configured key.

    Enable by adding to your .env:
        FOOD_LOG_API_KEY=your-secret-key-here
    """
    secret = _get_api_key_secret()
    if secret is None:
        return   # Auth disabled — allow all
    if x_api_key != secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. "
                   "Provide your key in the X-Api-Key header.",
        )


Auth = Annotated[None, Depends(require_auth)]


# ---------------------------------------------------------------------------
# In-memory session store for multi-step flows
# ---------------------------------------------------------------------------
# Multi-step flows (add recipe, record meal) need to maintain state between
# HTTP requests.  We store session objects in a simple dict keyed by a UUID.
# For a personal single-user app this is fine; a multi-user deployment would
# use Redis or a database-backed session store instead.

_sessions: dict[str, object] = {}


def create_session(obj: object) -> str:
    """Store a session object and return its key."""
    key = str(uuid.uuid4())
    _sessions[key] = obj
    return key


def get_session(key: str) -> Optional[object]:
    """Retrieve a session object by key, or None if not found."""
    return _sessions.get(key)


def end_session(key: str) -> None:
    """Remove a session object."""
    _sessions.pop(key, None)


def require_session(key: str, expected_type: type) -> object:
    """
    Retrieve a session, raising HTTP 404 if not found or wrong type.
    Use this in endpoints that need to resume a multi-step flow.
    """
    session = get_session(key)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{key}' not found or has already been completed.",
        )
    if not isinstance(session, expected_type):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session '{key}' is not a {expected_type.__name__} session.",
        )
    return session


# ---------------------------------------------------------------------------
# USDA API key
# ---------------------------------------------------------------------------

def get_usda_api_key() -> Optional[str]:
    """Read the USDA API key from environment or .env file."""
    if key := os.environ.get("USDA_API_KEY"):
        return key
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("USDA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ---------------------------------------------------------------------------
# Anthropic API key
# ---------------------------------------------------------------------------

def get_anthropic_api_key() -> Optional[str]:
    """Read the Anthropic API key from environment or .env file."""
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return key
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ---------------------------------------------------------------------------
# Image file helpers
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_SIZE_BYTES      = 10 * 1024 * 1024   # 10 MB


def save_image(data: bytes, filename: str, subdir: str) -> str:
    """
    Save image bytes to IMAGES_DIR/<subdir>/<filename>.
    Returns the relative path string (for storing in the database).
    Raises ValueError for disallowed extensions or oversized files.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image type '{ext}'. "
            f"Allowed: {sorted(ALLOWED_IMAGE_EXTENSIONS)}"
        )
    if len(data) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError(
            f"Image too large ({len(data) / 1024 / 1024:.1f} MB). "
            f"Maximum: {MAX_IMAGE_SIZE_BYTES // 1024 // 1024} MB."
        )
    target_dir = IMAGES_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    dest.write_bytes(data)
    return f"images/{subdir}/{filename}"


def delete_image(relative_path: str) -> None:
    """Delete an image file given its relative path. Silently ignores missing files."""
    full_path = BASE_DIR / relative_path
    if full_path.exists():
        full_path.unlink()
