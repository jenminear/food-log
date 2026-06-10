"""
routers/nutrition.py — Nutrition report endpoints
===================================================
GET  /nutrition/daily              Daily breakdown for a given date
GET  /nutrition/range              Aggregate totals for a date range
"""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, HTTPException, Query, status

import app as App
import db
from dependencies import Auth, DbConn
from models import (
    AggregateNutritionResponse, DailyNutritionResponse,
    MealNutritionDetail, NutritionDisplay,
)

router = APIRouter(prefix="/nutrition", tags=["Nutrition"])


def _make_nutrition_display(n: dict) -> NutritionDisplay:
    return NutritionDisplay(
        calories      = n.get("calories"),
        protein_grams = n.get("protein_grams"),
        fat_grams     = n.get("fat_grams"),
        carb_grams    = n.get("carb_grams"),
        fiber_grams   = n.get("fiber_grams"),
        display       = n.get("display", {}),
    )


@router.get(
    "/daily",
    response_model=DailyNutritionResponse,
    summary="Daily nutritional breakdown for a given date",
)
def daily_nutrition(
    conn: DbConn,
    _:    Auth,
    date: str = Query(
        default=None,
        description="ISO-8601 date (YYYY-MM-DD). Defaults to today.",
    ),
):
    """
    Returns each meal for the date in chronological order, with per-meal
    and daily-total nutrition.  Batch meals are shown with recipe name and
    fraction consumed; standalone meals list each ingredient separately.
    """
    if date is None:
        date = str(_date.today())
    else:
        try:
            _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date must be ISO-8601 (YYYY-MM-DD).",
            )

    report = App.get_daily_nutrition(conn, date)

    meals = [
        MealNutritionDetail(
            meal_id           = m["meal_id"],
            meal_type         = m["meal_type"],
            timestamp         = m.get("timestamp"),
            source            = m["source"],
            recipe_name       = m.get("recipe_name"),
            fraction_of_batch = m.get("fraction_of_batch"),
            components        = m.get("components", []),
            nutrition         = _make_nutrition_display(m["nutrition"]),
        )
        for m in report["meals"]
    ]

    return DailyNutritionResponse(
        date         = report["date"],
        meals        = meals,
        daily_totals = _make_nutrition_display(report["daily_totals"]),
    )


@router.get(
    "/range",
    response_model=AggregateNutritionResponse,
    summary="Aggregate nutrition across a date range",
)
def range_nutrition(
    conn:       DbConn,
    _:          Auth,
    start_date: str = Query(..., description="ISO-8601 start date (inclusive)"),
    end_date:   str = Query(..., description="ISO-8601 end date (inclusive)"),
):
    """
    Sums nutrition across all meals in the date range and returns totals
    plus daily averages.
    """
    for label, d in (("start_date", start_date), ("end_date", end_date)):
        try:
            _date.fromisoformat(d)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{label} must be ISO-8601 (YYYY-MM-DD).",
            )

    try:
        report = App.get_aggregate_nutrition(conn, start_date, end_date)
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return AggregateNutritionResponse(
        start_date     = report["start_date"],
        end_date       = report["end_date"],
        num_days       = report["num_days"],
        num_meals      = report["num_meals"],
        totals         = _make_nutrition_display(report["totals"]),
        daily_averages = _make_nutrition_display(report["daily_averages"]),
    )
