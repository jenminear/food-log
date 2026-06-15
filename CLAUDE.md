# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a full-stack food logging application that tracks recipes, cooking batches, meals, and nutritional information. The backend is a FastAPI Python application with SQLite storage, and the frontend is a React SPA built with Vite.

## Development Commands

### Backend (FastAPI)

```bash
# Install Python dependencies (Python 3.13)
pip install -r requirements.txt

# Initialize database (if food_log.db doesn't exist)
python init_db.py

# Run API server
uvicorn main:app --reload --port 8000
# Or: python main.py

# Run tests
pytest test_api.py
pytest test_app.py
pytest test_db.py
pytest test_nutrition_lookup.py

# Run a specific test
pytest test_api.py::test_name -v
```

### Frontend (React + Vite)

```bash
# Install Node dependencies (Node v24.12.0)
npm install

# Run development server (proxies /api to localhost:8000)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Architecture

### Backend: Three-Layer Architecture

1. **Data Layer** (`db.py`, ~1000 lines)
   - All SQL interactions with `food_log.db`
   - Connection management with `get_connection()`
   - Custom exceptions: `NotFoundError`, `DuplicateError`, `ValidationError`
   - Functions accept `conn: sqlite3.Connection` and never auto-commit
   - Caller is responsible for calling `conn.commit()`

2. **Business Logic Layer** (`app.py`, ~900 lines)
   - Orchestrates the five primary user flows
   - Coordinates between `db.py` and `nutrition_lookup.py`
   - Two-phase flows for user confirmation:
     - `start_*()` → returns `Result` or `UserPrompt`
     - `resume_*()` → called with user response; returns final `Result`
   - Session objects for multi-step flows: `AddRecipeSession`, `RecordMealSession`
   - All results and prompts are plain dicts (UI-agnostic)

3. **API Layer** (`main.py` + routers)
   - FastAPI application with automatic OpenAPI docs at `/docs`
   - Five router modules: `recipes`, `batches`, `meals`, `nutrition`, `notes`
   - Global exception handlers convert `db.py` exceptions to HTTP status codes
   - CORS enabled for local development (all origins allowed)
   - Optional API key authentication via `X-Api-Key` header (configured in `.env`)

### Five Primary User Flows

1. **Add Recipe** (`app.add_recipe()`)
   - Creates recipe, adds ingredients with automatic USDA nutrition lookup
   - Returns `AddRecipeSession` for step-by-step ingredient addition
   - Handles ingredient confirmation when confidence is low

2. **Create Batch** (`app.create_batch()`)
   - Searches recipes by name, creates batch instance
   - Copy-on-write pattern: components live at recipe level until first modification
   - When modified, sets `recipe_changes=1` and copies components to batch level

3. **Record Meal** (`app.record_meal()`)
   - Searches both recipes and ingredients simultaneously
   - Two meal types:
     - Batch meal: links to most recent batch of a recipe, records fraction consumed
     - Standalone meal: direct ingredient list without recipe association
   - Returns `RecordMealSession` for step-by-step meal construction

4. **Daily Nutrition** (`app.get_daily_nutrition()`)
   - Returns nutrition breakdown for a specific date
   - Groups by meal type with totals

5. **Aggregate Nutrition** (`app.get_aggregate_nutrition()`)
   - Sums and averages nutrition across date range

### Nutrition Lookup System

**Module**: `nutrition_lookup.py` (~700 lines)

Searches USDA FoodData Central and Open Food Facts APIs for ingredient nutrition data:
- Confidence scoring system determines auto-pick vs. user confirmation
- High confidence (>0.85): auto-creates ingredient
- Low/medium confidence: surfaces candidates to user
- `result_to_db_kwargs()`: converts API results to database format
- USDA API key configured in `.env` (falls back to DEMO_KEY if unset)

### Database Schema

**File**: `food_log_schema.sql`, `food_log.db` (SQLite)

Core tables:
- `recipes`: recipe metadata (name, steps, servings, times, dietary flags)
- `batches`: cooking instances of recipes (date, optional modifications)
- `ingredients`: nutrition data per base portion (100g default)
- `components`: join table linking ingredients to recipes/batches/meals with quantities
- `meals`: meal instances (type, date, batch reference or standalone)
- `notes`: free-text notes attachable to any entity

Key pattern: **Copy-on-write for batch modifications**
- Components initially reference `recipe_id`
- On first batch modification, components are copied with `batch_id`
- `batches.recipe_changes` flag tracks this state

### Frontend Architecture

**Stack**: React 18 + React Router + Vite

**Structure**:
- `main.jsx`: Entry point, router setup
- `App.jsx`: Root component
- `pages/`: Route components (Today, Recipes, RecipeDetail, Batches, Meals, Reports)
- `components/`: Shared components (Layout, NutGrid)
- `pages/api.js`: API client functions

**API Proxy**: Vite dev server proxies `/api/*` → `http://localhost:8000` (see `vite.config.js`)

### Configuration

**Environment Variables** (`.env`):
- `USDA_API_KEY`: USDA FoodData Central API key (free at https://fdc.nal.usda.gov/api-guide.html)
- `FOOD_LOG_API_KEY`: Optional API protection (leave blank for local use)

**Dependencies** (`dependencies.py`):
- Loads environment variables
- Defines `DB_PATH`, `IMAGES_DIR`
- Provides `Auth` dependency for FastAPI endpoints (validates API key if set)

## Important Patterns

### Database Operations

Always use the connection pattern:
```python
import db
conn = db.get_connection()
try:
    # ... db operations ...
    conn.commit()
finally:
    conn.close()
```

Never write raw SQL outside `db.py`.

### Error Handling

The three custom exceptions are mapped to HTTP status codes:
- `NotFoundError` → 404
- `DuplicateError` → 409
- `ValidationError` → 422

### Ingredient Resolution

When adding ingredients to recipes/batches/meals:
1. Check if ingredient exists in database
2. If not, lookup via `nutrition_lookup.py`
3. If confidence is high, auto-create and commit
4. If confidence is low, return candidates for user confirmation
5. User selects from candidates or provides manual data

### Component Quantity System

Ingredients have a base portion (e.g., "100g", "1 cup").
`components.quantity_multiple` scales this base:
- Base: 100g apple, nutrition for 100g
- Recipe uses 250g: `quantity_multiple = 2.5`
- Nutrition calculation: multiply all values by 2.5

## Testing

Test files mirror main modules:
- `test_db.py`: Data layer tests
- `test_app.py`: Business logic tests
- `test_api.py`: API endpoint tests
- `test_nutrition_lookup.py`: External API integration tests

Tests use pytest with FastAPI's TestClient.
