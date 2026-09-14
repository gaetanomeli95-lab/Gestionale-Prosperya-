"""Helpers to record activity events and audit entries consistently."""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modules.activities.models import ActivityEvent
from app.modules.audit.models import AuditLog


def record_activity(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        ActivityEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            payload=payload or {},
        )
    )


def record_audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None = None,
    changes: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            tenant_id=tenant_id,
            changes=changes or {},
            context=context or {},
        )
    )


def diff_changes(before: dict, after: dict) -> dict:
    """Return {field: {"old":…, "new":…}} for changed keys only."""
    out = {}
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            out[key] = {"old": before.get(key), "new": after.get(key)}
    return out
