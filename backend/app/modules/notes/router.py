from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, NotFoundError
from app.core.rbac import Role, get_current_user, require_permissions
from app.db import get_db
from app.modules.notes.models import Note
from app.modules.notes.schemas import NoteCreate, NoteOut, NoteUpdate
from app.modules.users.models import User
from app.shared.events import record_activity
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=Page[NoteOut])
def list_notes(
    entity_type: str = Query(...),
    entity_id: UUID = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (
        select(Note)
        .where(Note.entity_type == entity_type, Note.entity_id == entity_id)
        .order_by(Note.pinned.desc(), Note.created_at.desc())
    )
    return paginate(db, stmt, PageParams(page, page_size), NoteOut)


@router.post("", response_model=NoteOut, status_code=201)
def create_note(
    payload: NoteCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("notes:write")),
):
    note = Note(**payload.model_dump(), author_id=actor.id)
    db.add(note)
    db.flush()
    record_activity(
        db, actor_id=actor.id, event_type="note.added",
        entity_type=note.entity_type, entity_id=note.entity_id,
        summary=f"Note added by {actor.full_name}",
    )
    db.commit()
    return NoteOut.model_validate(note)


@router.patch("/{note_id}", response_model=NoteOut)
def update_note(
    note_id: UUID,
    payload: NoteUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("notes:write")),
):
    note = db.get(Note, note_id)
    if note is None:
        raise NotFoundError("Note not found.")
    if note.author_id != actor.id and actor.role not in (Role.ADMIN, Role.MANAGEMENT):
        raise ForbiddenError("You can only edit your own notes.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(note, k, v)
    db.commit()
    return NoteOut.model_validate(note)
