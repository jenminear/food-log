"""
main.py — Food Log API
=======================
Entry point for the FastAPI application.

Run locally:
    uvicorn main:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs      ← Swagger UI
    http://localhost:8000/redoc     ← ReDoc

Configuration (via .env or environment variables):
    USDA_API_KEY      — USDA FoodData Central API key
    FOOD_LOG_API_KEY  — Optional API key to protect the API
                        (leave unset for local personal use)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import db as DB
from dependencies import DB_PATH, IMAGES_DIR, Auth
from routers import batches, meals, notes, nutrition, recipes

# ---------------------------------------------------------------------------
# Lifespan — runs once on startup and shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database on startup if it doesn't exist yet."""
    if not DB_PATH.exists():
        schema_path = Path(__file__).with_name("food_log_schema.sql")
        if schema_path.exists():
            conn = DB.get_connection(DB_PATH)
            conn.executescript(schema_path.read_text())
            conn.commit()
            conn.close()
            print(f"[startup] Database initialised at {DB_PATH}")
        else:
            print(
                f"[startup] WARNING: {schema_path} not found. "
                "Run init_db.py to create the database."
            )
    else:
        print(f"[startup] Database found at {DB_PATH}")
    yield
    # Shutdown — nothing to clean up for SQLite


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title       = "Food Log API",
    description = (
        "Personal food logging API. Track recipes, cooking batches, meals, "
        "and nutritional information. Nutrition data sourced from USDA "
        "FoodData Central and Open Food Facts."
    ),
    version     = "1.0.0",
    lifespan    = lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow all origins for local development.
# Tighten this when deploying to a server.
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(recipes.router)
app.include_router(batches.router)
app.include_router(meals.router)
app.include_router(nutrition.router)
app.include_router(notes.router)

# ---------------------------------------------------------------------------
# Static file serving — images uploaded via the API
# ---------------------------------------------------------------------------

if IMAGES_DIR.exists():
    app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")

# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(DB.NotFoundError)
async def not_found_handler(request: Request, exc: DB.NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(DB.DuplicateError)
async def duplicate_handler(request: Request, exc: DB.DuplicateError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(DB.ValidationError)
async def validation_handler(request: Request, exc: DB.ValidationError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"], summary="API health check")
def health(_: Auth):
    """Returns 200 OK when the API is running."""
    return {"status": "ok", "db": str(DB_PATH)}


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
