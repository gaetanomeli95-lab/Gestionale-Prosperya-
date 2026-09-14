import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.companies.models import Company
from app.modules.contacts.models import Contact
from app.modules.leads.models import Lead
from app.modules.opportunities.models import Opportunity
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/search", tags=["search"])


class SearchHit(BaseModel):
    type: Literal["company", "contact", "lead", "opportunity"]
    id: uuid.UUID
    title: str
    subtitle: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]


@router.get("", response_model=SearchResponse)
def global_search(
    q: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(8, ge=1, le=25),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("search:read")),
):
    tid = ctx.tenant_id
    like = f"%{q}%"
    results: list[SearchHit] = []

    companies = db.scalars(
        select(Company)
        .where(
            Company.tenant_id == tid,
            Company.deleted_at.is_(None),
            or_(
                Company.legal_name.ilike(like),
                Company.trading_name.ilike(like),
                Company.vat_number.ilike(like),
                Company.pec.ilike(like),
            ),
        )
        .limit(limit)
    )
    results += [
        SearchHit(type="company", id=c.id, title=c.legal_name,
                  subtitle=c.vat_number or c.city)
        for c in companies
    ]

    contacts = db.scalars(
        select(Contact)
        .where(
            Contact.tenant_id == tid,
            Contact.deleted_at.is_(None),
            or_(
                Contact.first_name.ilike(like),
                Contact.last_name.ilike(like),
                Contact.email.ilike(like),
                Contact.phone.ilike(like),
            ),
        )
        .limit(limit)
    )
    results += [
        SearchHit(type="contact", id=c.id, title=f"{c.first_name} {c.last_name}",
                  subtitle=c.email or c.phone)
        for c in contacts
    ]

    leads = db.scalars(
        select(Lead)
        .where(Lead.tenant_id == tid, Lead.deleted_at.is_(None), Lead.company_name.ilike(like))
        .limit(limit)
    )
    results += [
        SearchHit(type="lead", id=lead.id, title=lead.company_name, subtitle=f"Lead · {lead.status}")
        for lead in leads
    ]

    opps = db.scalars(
        select(Opportunity)
        .where(
            Opportunity.tenant_id == tid,
            Opportunity.deleted_at.is_(None),
            Opportunity.title.ilike(like),
        )
        .limit(limit)
    )
    results += [
        SearchHit(type="opportunity", id=o.id, title=o.title, subtitle=f"Opportunity · {o.status}")
        for o in opps
    ]

    return SearchResponse(query=q, results=results[: limit * 2])
