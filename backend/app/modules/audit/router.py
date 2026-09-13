import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.audit.models import AuditLog
from app.modules.users.models import User
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    changes: dict
    created_at: datetime


@router.get("", response_model=Page[AuditOut])
def list_audit(
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    action: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("audit:read")),
):
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return paginate(
        db, stmt.order_by(AuditLog.created_at.desc()),
        PageParams(page, page_size), AuditOut,
    )
