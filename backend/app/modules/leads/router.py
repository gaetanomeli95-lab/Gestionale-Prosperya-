from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.companies.models import Company
from app.modules.companies.service import find_duplicates
from app.modules.contacts.models import CompanyContact, Contact
from app.modules.leads.models import Lead, LeadStatus
from app.modules.leads.schemas import (
    LeadConvertRequest,
    LeadConvertResponse,
    LeadCreate,
    LeadOut,
    LeadUpdate,
)
from app.modules.opportunities.models import Opportunity
from app.modules.service_lines.models import PipelineStage
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User
from app.shared.events import record_activity, record_audit
from app.shared.mixins import utcnow
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/leads", tags=["leads"])


def _get_lead_or_404(db: Session, lead_id: UUID, ctx: TenantContext) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != ctx.tenant_id or lead.deleted_at is not None:
        raise NotFoundError("Lead not found.")
    return lead


@router.get("", response_model=Page[LeadOut])
def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: str | None = None,
    status: LeadStatus | None = None,
    owner_id: UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("leads:read")),
):
    stmt = select(Lead).where(Lead.tenant_id == ctx.tenant_id, Lead.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Lead.company_name.ilike(like),
                Lead.contact_name.ilike(like),
                Lead.email.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(Lead.status == status)
    if owner_id:
        stmt = stmt.where(Lead.owner_id == owner_id)
    return paginate(db, stmt.order_by(Lead.created_at.desc()), PageParams(page, page_size), LeadOut)


@router.post("", response_model=LeadOut, status_code=201)
def create_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("leads:write")),
):
    lead = Lead(**payload.model_dump(), tenant_id=ctx.tenant_id)
    db.add(lead)
    db.flush()
    record_activity(
        db, tenant_id=ctx.tenant_id, actor_id=actor.id, event_type="lead.created",
        entity_type="lead",
        entity_id=lead.id, summary=f"Lead “{lead.company_name}” created",
    )
    record_audit(db, actor_id=actor.id, action="lead.create", entity_type="lead",
                 entity_id=lead.id, tenant_id=ctx.tenant_id)
    db.commit()
    return LeadOut.model_validate(lead)


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("leads:read")),
):
    return LeadOut.model_validate(_get_lead_or_404(db, lead_id, ctx))


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("leads:write")),
):
    lead = _get_lead_or_404(db, lead_id, ctx)
    if payload.version != lead.version:
        raise ConflictError(
            "This record was modified by someone else. Reload and try again.",
            code="stale_version",
        )
    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    if lead.status == LeadStatus.CONVERTED and data.get("status") != LeadStatus.CONVERTED:
        raise ValidationError("A converted lead cannot change status.", code="lead_already_converted")
    for k, v in data.items():
        setattr(lead, k, v)
    lead.version += 1
    record_audit(
        db, actor_id=actor.id, action="lead.update", entity_type="lead",
        entity_id=lead.id, tenant_id=ctx.tenant_id, changes={"fields": sorted(data)},
    )
    db.commit()
    return LeadOut.model_validate(lead)


@router.post("/{lead_id}/convert", response_model=LeadConvertResponse)
def convert_lead(
    lead_id: UUID,
    payload: LeadConvertRequest,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("leads:write", "companies:write")),
):
    lead = _get_lead_or_404(db, lead_id, ctx)
    if lead.status == LeadStatus.CONVERTED:
        raise ConflictError("This lead has already been converted.", code="lead_already_converted")

    # Company: reuse an existing record or create one carrying lead data.
    if payload.existing_company_id:
        company = db.get(Company, payload.existing_company_id)
        if (
            company is None
            or company.tenant_id != ctx.tenant_id
            or company.deleted_at is not None
        ):
            raise ValidationError("The specified company does not exist.", code="invalid_company")
    else:
        company = Company(
            legal_name=lead.company_name,
            email=lead.email,
            phone=lead.phone,
            source=f"lead:{lead.source}",
            owner_id=lead.owner_id,
            created_by_id=actor.id,
            tenant_id=ctx.tenant_id,
        )
        db.add(company)
        db.flush()

    # Contact: create when we have a person name, then link to the company.
    contact: Contact | None = None
    if lead.contact_name or lead.email:
        parts = (lead.contact_name or "").strip().split(None, 1)
        contact = Contact(
            first_name=parts[0] if parts else (lead.email or "Contatto").split("@")[0],
            last_name=parts[1] if len(parts) > 1 else "—",
            email=lead.email,
            phone=lead.phone,
            owner_id=lead.owner_id,
            tenant_id=ctx.tenant_id,
        )
        db.add(contact)
        db.flush()
        db.add(CompanyContact(company_id=company.id, contact_id=contact.id, is_primary=True))

    # Opportunity: optional, created in the requested/default first stage.
    opportunity: Opportunity | None = None
    if payload.create_opportunity:
        stage = None
        if payload.stage_id:
            stage = db.get(PipelineStage, payload.stage_id)
            if stage is not None and stage.tenant_id != ctx.tenant_id:
                stage = None
        if stage is None:
            stage = db.scalar(
                select(PipelineStage)
                .where(
                    PipelineStage.tenant_id == ctx.tenant_id,
                    PipelineStage.is_active.is_(True),
                    PipelineStage.is_won.is_(False),
                    PipelineStage.is_lost.is_(False),
                )
                .order_by(PipelineStage.position)
                .limit(1)
            )
        if stage is None:
            raise ValidationError(
                "No pipeline stage is configured. Create one first.", code="no_pipeline_stage"
            )
        opportunity = Opportunity(
            title=payload.opportunity_title or f"{lead.company_name} — {lead.interest or 'opportunity'}",
            company_id=company.id,
            contact_id=contact.id if contact else None,
            service_line_id=lead.service_line_id,
            stage_id=stage.id,
            owner_id=lead.owner_id,
            expected_value_eur=lead.estimated_value_eur,
            probability=stage.default_probability,
            source=f"lead:{lead.source}",
            tenant_id=ctx.tenant_id,
        )
        db.add(opportunity)
        db.flush()
        record_activity(
            db, tenant_id=ctx.tenant_id, actor_id=actor.id,
            event_type="opportunity.created", entity_type="opportunity",
            entity_id=opportunity.id,
            summary=f"Opportunity “{opportunity.title}” created from lead",
        )

    lead.status = LeadStatus.CONVERTED
    lead.converted_company_id = company.id
    lead.converted_contact_id = contact.id if contact else None
    lead.converted_at = utcnow()
    lead.version += 1

    record_activity(
        db, tenant_id=ctx.tenant_id, actor_id=actor.id, event_type="lead.converted",
        entity_type="lead",
        entity_id=lead.id, summary=f"Lead “{lead.company_name}” converted",
        payload={"company_id": str(company.id)},
    )
    record_audit(
        db, actor_id=actor.id, action="lead.convert", entity_type="lead",
        entity_id=lead.id, tenant_id=ctx.tenant_id, changes={"company_id": str(company.id)},
    )
    db.commit()
    return LeadConvertResponse(
        lead=LeadOut.model_validate(lead),
        company_id=company.id,
        contact_id=contact.id if contact else None,
        opportunity_id=opportunity.id if opportunity else None,
    )


@router.delete("/{lead_id}", status_code=204)
def delete_lead(
    lead_id: UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("leads:write")),
):
    lead = _get_lead_or_404(db, lead_id, ctx)
    lead.deleted_at = utcnow()
    lead.version += 1
    record_audit(db, actor_id=actor.id, action="lead.delete", entity_type="lead",
                 entity_id=lead.id, tenant_id=ctx.tenant_id)
    db.commit()


# Re-exported for the duplicate-warning check used by the leads UI.
def lead_company_duplicates(db: Session, tenant_id, company_name: str):
    return find_duplicates(db, tenant_id, legal_name=company_name)
