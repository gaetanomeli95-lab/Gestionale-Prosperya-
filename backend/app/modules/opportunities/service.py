"""Opportunities read service.

Public, plain-data read surface used by the cockpit/hub so other modules never
query `opportunities` directly (ARCHITECTURE §1). Write paths still live in
`router.py` and are untouched.
"""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.opportunities.models import Opportunity, OpportunityStatus
from app.shared.mixins import today

#: Days without any update after which an open opportunity is "stale".
DEFAULT_STALE_DAYS = 12


def list_open(db: Session, *, tenant_id, company_id: uuid.UUID | None = None,
              as_of: date | None = None) -> list[dict]:
    """Open opportunities with their inactivity in days.

    `days_inactive` is measured on `updated_at` — the only activity signal
    guaranteed to exist on the record. It is a *proxy*, and the cockpit labels
    it as such.
    """
    as_of = as_of or today()
    stmt = select(Opportunity).where(
        Opportunity.tenant_id == tenant_id,
        Opportunity.deleted_at.is_(None),
        Opportunity.status == OpportunityStatus.OPEN,
    )
    if company_id is not None:
        stmt = stmt.where(Opportunity.company_id == company_id)
    rows = db.scalars(stmt.order_by(Opportunity.updated_at)).all()
    return [{
        "id": str(row.id),
        "title": row.title,
        "company_id": str(row.company_id),
        "stage_id": str(row.stage_id),
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "probability": row.probability,
        "expected_value_eur": (str(row.expected_value_eur)
                               if row.expected_value_eur is not None else None),
        "expected_close_date": (row.expected_close_date.isoformat()
                                if row.expected_close_date else None),
        "next_action": row.next_action,
        "next_action_date": (row.next_action_date.isoformat()
                             if row.next_action_date else None),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "days_inactive": ((as_of - row.updated_at.date()).days
                          if row.updated_at else None),
    } for row in rows]
