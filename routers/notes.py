"""
routers/notes.py — Notes endpoints
=====================================
POST   /notes               Add a note to a recipe, batch, or meal
GET    /notes                Retrieve notes for a recipe, batch, or meal
PATCH  /notes/{note_id}      Edit a note's text
DELETE /notes/{note_id}      Delete a note
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

import app as App
import db
from dependencies import Auth, DbConn
from models import NoteDetail, NoteRequest, NoteResponse, NoteUpdateRequest

router = APIRouter(prefix="/notes", tags=["Notes"])


@router.post(
    "",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to a recipe, batch, or meal",
)
def add_note(req: NoteRequest, conn: DbConn, _: Auth):
    """
    At least one of `recipe_id`, `batch_id`, or `meal_id` must be provided.
    `note_date` defaults to today.
    """
    try:
        result = App.add_note(
            conn,
            req.note_txt,
            recipe_id = req.recipe_id,
            batch_id  = req.batch_id,
            meal_id   = req.meal_id,
            note_date = req.note_date,
        )
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))

    return NoteResponse(note_id=result["note_id"], note_date=result["note_date"])


@router.get(
    "",
    response_model=list[NoteDetail],
    summary="Get notes for a recipe, batch, or meal",
)
def get_notes(
    conn:      DbConn,
    _:         Auth,
    recipe_id: int | None = Query(None),
    batch_id:  int | None = Query(None),
    meal_id:   int | None = Query(None),
):
    """
    Supply exactly one of `recipe_id`, `batch_id`, or `meal_id`.
    Returns notes in reverse chronological order.
    """
    try:
        notes = db.get_notes(
            conn,
            recipe_id = recipe_id,
            batch_id  = batch_id,
            meal_id   = meal_id,
        )
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return [
        NoteDetail(
            note_id   = n["note_id"],
            note_date = n["note_date"],
            note_txt  = n["note_txt"],
        )
        for n in notes
    ]


@router.patch(
    "/{note_id}",
    response_model=NoteDetail,
    summary="Edit a note's text",
)
def update_note(note_id: int, req: NoteUpdateRequest, conn: DbConn, _: Auth):
    try:
        db.update_note(conn, note_id, req.note_txt)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM notes WHERE note_id = ?", (note_id,)
        ).fetchone()
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    except db.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return NoteDetail(note_id=row["note_id"], note_date=row["note_date"], note_txt=row["note_txt"])


@router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a note",
)
def delete_note(note_id: int, conn: DbConn, _: Auth):
    try:
        db.delete_note(conn, note_id)
        conn.commit()
    except db.NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
