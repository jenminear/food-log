"""
models.py — Pydantic Request / Response Models
================================================
All FastAPI endpoints use these models for automatic request validation
and response serialisation.  Keeping them here (rather than inline in
the routers) means they can be imported by tests without pulling in the
full FastAPI app.

Naming convention
-----------------
  *Request  — incoming request body (POST / PATCH)
  *Response — outgoing response body
  *Summary  — lightweight version used in list responses
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Shared / base types
# ---------------------------------------------------------------------------

class NutritionBlock(BaseModel):
    """Nutrition values per 100g (all optional — may be unknown)."""
    calories:      Optional[float] = None
    protein_grams: Optional[float] = None
    fat_grams:     Optional[float] = None
    carb_grams:    Optional[float] = None
    fiber_grams:   Optional[float] = None


class NutritionDisplay(NutritionBlock):
    """Nutrition block with additional human-readable display strings."""
    display: dict[str, str] = Field(default_factory=dict)


class ComponentSummary(BaseModel):
    """One ingredient within a recipe, batch, or meal."""
    component_id:     int
    ingredient_id:    int
    ingredient_name:  str
    quantity_multiple: float
    portion_amount:   float
    portion_unit:     str
    portion_grams:    float


class NutritionCandidate(BaseModel):
    """A candidate nutrition result returned for user confirmation."""
    ingredient_name:      str
    summary:              str
    portion_amount:       float
    portion_unit:         str
    portion_grams:        float
    calories:             Optional[float] = None
    protein_grams:        Optional[float] = None
    fat_grams:            Optional[float] = None
    carb_grams:           Optional[float] = None
    fiber_grams:          Optional[float] = None
    nutrition_info_source: Optional[str]  = None


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------

class RecipeRequest(BaseModel):
    recipe_name:      str          = Field(..., min_length=1, max_length=255)
    steps_txt:        Optional[str]  = None
    num_servings:     Optional[float] = Field(None, gt=0)
    active_time_mins: Optional[int]   = Field(None, ge=0)
    total_time_mins:  Optional[int]   = Field(None, ge=0)
    need_oven:        bool = False
    vegan:            bool = False
    vegetarian:       bool = False
    source:           Optional[str] = None


class RecipeResponse(BaseModel):
    recipe_id:        int
    recipe_name:      str
    steps_txt:        Optional[str]
    num_servings:     Optional[float]
    active_time_mins: Optional[int]
    total_time_mins:  Optional[int]
    need_oven:        bool
    vegan:            bool
    vegetarian:       bool
    source:           Optional[str]
    picture_path:     Optional[str]


class RecipeSummary(BaseModel):
    recipe_id:   int
    recipe_name: str
    num_servings: Optional[float]
    vegan:        bool
    vegetarian:   bool


# ---------------------------------------------------------------------------
# Ingredients  (used inside recipe / meal flows)
# ---------------------------------------------------------------------------

class IngredientConfirmRequest(BaseModel):
    """Sent back after showing the user a list of candidates."""
    pending_key:  str
    choice:       Optional[int]  = Field(None, ge=1)
    manual_data:  Optional[dict] = None

    @model_validator(mode="after")
    def choice_or_manual(self) -> "IngredientConfirmRequest":
        if self.choice is None and self.manual_data is None:
            raise ValueError("Provide either 'choice' (1-based) or 'manual_data'.")
        return self


class IngredientAddRequest(BaseModel):
    ingredient_name:  str   = Field(..., min_length=1)
    quantity_multiple: float = Field(..., gt=0)


class IngredientResult(BaseModel):
    """Result of attempting to add a single ingredient."""
    status:          str    # "added" | "needs_confirmation" | "not_found"
    ingredient_name: str
    ingredient_id:   Optional[int]  = None
    component_id:    Optional[int]  = None
    candidates:      Optional[list[NutritionCandidate]] = None
    pending_key:     Optional[str]  = None


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

class BatchResponse(BaseModel):
    status:      str   # "created" | "ambiguous" | "not_found"
    batch_id:    Optional[int]
    recipe_id:   Optional[int]
    recipe_name: Optional[str]
    batch_date:  str
    components:  Optional[list[ComponentSummary]]
    candidates:  Optional[list[RecipeSummary]]   # populated when ambiguous


class BatchModifyRequest(BaseModel):
    action:            str   = Field(..., pattern="^(add|remove|update_quantity)$")
    component_id:      Optional[int]   = Field(None, ge=1)
    ingredient_name:   Optional[str]   = None
    quantity_multiple: Optional[float] = Field(None, gt=0)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "BatchModifyRequest":
        if self.action == "remove" and self.component_id is None:
            raise ValueError("'remove' requires component_id.")
        if self.action == "update_quantity":
            if self.component_id is None or self.quantity_multiple is None:
                raise ValueError(
                    "'update_quantity' requires component_id and quantity_multiple."
                )
        if self.action == "add":
            if self.ingredient_name is None or self.quantity_multiple is None:
                raise ValueError(
                    "'add' requires ingredient_name and quantity_multiple."
                )
        return self


class BatchModifyResponse(BaseModel):
    status:       str
    action:       str
    batch_id:     int
    component_id: Optional[int]
    candidates:   Optional[list[NutritionCandidate]]
    pending_key:  Optional[str]
    components:   Optional[list[ComponentSummary]]


# ---------------------------------------------------------------------------
# Meals
# ---------------------------------------------------------------------------

VALID_MEAL_TYPES = {
    "breakfast", "lunch", "dinner",
    "morning_snack", "afternoon_snack", "evening_snack",
}


class MealStartRequest(BaseModel):
    meal_type:  str  = Field(...)
    meal_date:  Optional[str] = None   # ISO-8601 YYYY-MM-DD; defaults to today
    query:      str  = Field(..., min_length=1,
                             description="Recipe or ingredient name to search for")

    @field_validator("meal_type")
    @classmethod
    def validate_meal_type(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_MEAL_TYPES:
            raise ValueError(
                f"Invalid meal_type '{v}'. "
                f"Must be one of: {sorted(VALID_MEAL_TYPES)}"
            )
        return v

    @field_validator("meal_date")
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError("meal_date must be ISO-8601 (YYYY-MM-DD).")
        return v


class MealSearchResponse(BaseModel):
    """Returned after starting a meal — user picks from these results."""
    session_key:    str   # opaque token the client passes back
    meal_type:      str
    meal_date:      str
    recipes:        list[RecipeSummary]
    ingredients:    list[dict]


class MealSelectRecipeRequest(BaseModel):
    session_key:       str
    recipe_id:         int  = Field(..., ge=1)
    fraction_of_batch: float = Field(..., gt=0, le=1)


class MealAddIngredientRequest(BaseModel):
    session_key:       str
    ingredient_name:   str   = Field(..., min_length=1)
    quantity_multiple: float = Field(..., gt=0)


class MealResponse(BaseModel):
    meal_id:           int
    meal_type:         str
    meal_date:         str
    batch_id:          Optional[int]   = None
    recipe_name:       Optional[str]   = None
    fraction_of_batch: Optional[float] = None


# ---------------------------------------------------------------------------
# Nutrition
# ---------------------------------------------------------------------------

class MealNutritionDetail(BaseModel):
    meal_id:           int
    meal_type:         str
    timestamp:         Optional[int]
    source:            str   # "batch" | "ingredients"
    recipe_name:       Optional[str]
    fraction_of_batch: Optional[float]
    components:        list[dict]
    nutrition:         NutritionDisplay


class DailyNutritionResponse(BaseModel):
    date:         str
    meals:        list[MealNutritionDetail]
    daily_totals: NutritionDisplay


class AggregateNutritionResponse(BaseModel):
    start_date:     str
    end_date:       str
    num_days:       int
    num_meals:      int
    totals:         NutritionDisplay
    daily_averages: NutritionDisplay


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

class NoteRequest(BaseModel):
    note_txt:  str  = Field(..., min_length=1)
    recipe_id: Optional[int] = None
    batch_id:  Optional[int] = None
    meal_id:   Optional[int] = None
    note_date: Optional[str] = None

    @model_validator(mode="after")
    def requires_parent(self) -> "NoteRequest":
        if not any([self.recipe_id, self.batch_id, self.meal_id]):
            raise ValueError(
                "At least one of recipe_id, batch_id, or meal_id is required."
            )
        return self


class NoteResponse(BaseModel):
    note_id:   int
    note_date: str


# ---------------------------------------------------------------------------
# Generic responses
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
