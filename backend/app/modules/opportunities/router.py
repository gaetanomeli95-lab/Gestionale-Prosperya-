from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.companies.models import Company
from app.modules.opportunities.models import Opportunity, OpportunityStatus
from app.modules.opportunities.schemas import (
    OpportunityCreate,
    OpportunityListItem,
    OpportunityMove,
    OpportunityOut,
    OpportunityUpdate,
)
from app.modules.service_lines.models import PipelineStage
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User
from app.shared.events import record_activity, record_audit
from app.shared.mixins import utcnow
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def _get_or_404(db: Session, opportunity_id: UUID, ctx: TenantContext) -> Opportunity:
    opp = db.get(Opportunity, opportunity_id)
    if opp is None or opp.tenant_id != ctx.tenant_id or opp.deleted_at is not None:
        raise NotFoundError("Opportunity not found.")
    return opp


def _get_stage(db: Session, stage_id: UUID, ctx: TenantContext) -> PipelineStage:
    stage = db.get(PipelineStage, stage_id)
    if stage is None or stage.tenant_id != ctx.tenant_id or not stage.is_active:
        raise ValidationError("The specified pipeline stage does not exist.", code="invalid_stage")
    return stage


@router.get("", response_model=Page[OpportunityListItem])
def list_opportunities(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    q: str | None = None,
    status: OpportunityStatus | None = None,
    stage_id: UUID | None = None,
    owner_id: UUID | None = None,
    service_line_id: UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("opportunities:read")),
):
    stmt = select(Opportunity).where(
        Opportunity.tenant_id == ctx.tenant_id, Opportunity.deleted_at.is_(None)
    )
    if q:
        stmt = stmt.where(Opportunity.title.ilike(f"%{q}%"))
    if status:
        stmt = stmt.where(Opportunity.status == status)
    if stage_id:
        stmt = stmt.where(Opportunity.stage_id == stage_id)
    if owner_id:
        stmt = stmt.where(Opportunity.owner_id == owner_id)
    if service_line_id:
        stmt = stmt.where(Opportunity.service_line_id == service_line_id)
    return paginate(
        db, stmt.order_by(Opportunity.updated_at.desc()),
        PageParams(page, page_size), OpportunityListItem,
    )


@router.post("", response_model=OpportunityOut, status_code=201)
def create_opportunity(
    payload: OpportunityCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("opportunities:write")),
):
    company = db.get(Company, payload.company_id)
    if (
        company is None
        or company.tenant_id != ctx.tenant_id
        or company.deleted_at is not None
    ):
        raise ValidationError("The specified company does not exist.", code="invalid_company")
    stage = _get_stage(db, payload.stage_id, ctx)
    opp = Opportunity(**payload.model_dump(), tenant_id=ctx.tenant_id)
    if opp.probability is None:
        opp.probability = stage.default_probability
    if stage.is_won:
        opp.status = OpportunityStatus.WON
        opp.closed_at = utcnow()
    elif stage.is_lost:
        opp.status = OpportunityStatus.LOST
        opp.closed_at = utcnow()
    db.add(opp)
    db.flush()
    record_activity(
        db, tenant_id=ctx.tenant_id, actor_id=actor.id, event_type="opportunity.created",
        entity_type="opportunity",
        entity_id=opp.id, summary=f"Opportunity “{opp.title}” created",
        payload={"company_id": str(company.id)},
    )
    record_audit(db, actor_id=actor.id, action="opportunity.create",
                 entity_type="opportunity", entity_id=opp.id, tenant_id=ctx.tenant_id)
    db.commit()
    return OpportunityOut.model_validate(opp)


@router.get("/{opportunity_id}", response_model=OpportunityOut)
def get_opportunity(
    opportunity_id: UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("opportunities:read")),
):
    return OpportunityOut.model_validate(_get_or_404(db, opportunity_id, ctx))


@router.post("/{opportunity_id}/move", response_model=OpportunityOut)
def move_stage(
    opportunity_id: UUID,
    payload: OpportunityMove,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("opportunities:write")),
):
    opp = _get_or_404(db, opportunity_id, ctx)
    stage = _get_stage(db, payload.stage_id, ctx)
    previous = str(opp.stage_id)
    opp.stage_id = stage.id
    if stage.is_won:
        opp.status = OpportunityStatus.WON
        opp.closed_at = utcnow()
    elif stage.is_lost:
        opp.status = OpportunityStatus.LOST
        opp.closed_at = utcnow()
        if payload.lost_reason:
            opp.lost_reason = payload.lost_reason
    else:
        opp.status = OpportunityStatus.OPEN
        opp.closed_at = None
        opp.lost_reason = None
    opp.version += 1
    record_activity(
        db, tenant_id=ctx.tenant_id, actor_id=actor.id,
        event_type="opportunity.stage_changed", entity_type="opportunity",
        entity_id=opp.id,
        summary=f"Opportunity “{opp.title}” moved to {stage.name}",
        payload={"from_stage": previous, "to_stage": str(stage.id), "status": opp.status},
    )
    record_audit(
        db, actor_id=actor.id, action="opportunity.move", entity_type="opportunity",
        entity_id=opp.id, tenant_id=ctx.tenant_id,
        changes={"stage_id": {"old": previous, "new": str(stage.id)}},
    )
    db.commit()
    return OpportunityOut.model_validate(opp)


@router.patch("/{opportunity_id}", response_model=OpportunityOut)
def update_opportunity(
    opportunity_id: UUID,
    payload: OpportunityUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("opportunities:write")),
):
    opp = _get_or_404(db, opportunity_id, ctx)
    if payload.version != opp.version:
        raise ConflictError(
            "This record was modified by someone else. Reload and try again.",
            code="stale_version",
        )
    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    for k, v in data.items():
        setattr(opp, k, v)
    opp.version += 1
    record_audit(
        db, actor_id=actor.id, action="opportunity.update", entity_type="opportunity",
        entity_id=opp.id, tenant_id=ctx.tenant_id, changes={"fields": sorted(data)},
    )
    db.commit()
    return OpportunityOut.model_validate(opp)


@router.delete("/{opportunity_id}", status_code=204)
def delete_opportunity(
    opportunity_id: UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("opportunities:write")),
):
    opp = _get_or_404(db, opportunity_id, ctx)
    opp.deleted_at = utcnow()
    opp.version += 1
    record_audit(
        db, actor_id=actor.id, action="opportunity.delete",
        entity_type="opportunity", entity_id=opp.id, tenant_id=ctx.tenant_id,
    )
    db.commit()
