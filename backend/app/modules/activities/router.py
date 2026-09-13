import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user
from app.db import get_db
from app.modules.activities.models import ActivityEvent
from app.modules.users.models import User
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/timeline", tags=["timeline"])


class ActivityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    summary: str
    payload: dict
    created_at: datetime


@router.get("/{entity_type}/{entity_id}", response_model=Page[ActivityEventOut])
def entity_timeline(
    entity_type: str,
    entity_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (
        select(ActivityEvent)
        .where(ActivityEvent.entity_type == entity_type, ActivityEvent.entity_id == entity_id)
        .order_by(ActivityEvent.created_at.desc())
    )
    return paginate(db, stmt, PageParams(page, page_size), ActivityEventOut)
