"""Cockpit API — CFO cockpit per company and multi-company control hub."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.cockpit import service
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.treasury import service as treasury
from app.modules.users.models import User

router = APIRouter(prefix="/cockpit", tags=["cockpit"])


@router.get("/hub")
def hub(
    year: int = Query(2026, ge=2000, le=2100),
    through_month: int = Query(6, ge=1, le=12),
    horizon_days: int = Query(90, ge=1, le=365),
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("cockpit:read", "management:read", "treasury:read")),
):
    """Portfolio control hub: which company needs attention first, and why."""
    return service.hub(db, tenant_id=ctx.tenant_id, year=year,
                       through_month=through_month, horizon_days=horizon_days,
                       as_of=as_of)


@router.get("/companies/{company_id}")
def company_cockpit(
    company_id: uuid.UUID,
    year: int = Query(2026, ge=2000, le=2100),
    through_month: int = Query(6, ge=1, le=12),
    horizon_days: int = Query(90, ge=1, le=365),
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("cockpit:read", "management:read", "treasury:read")),
):
    """One company: registry, economics, cash, commercial, ranked actions."""
    company = treasury.company_or_404(db, company_id, ctx.tenant_id)
    return service.company_cockpit(db, tenant_id=ctx.tenant_id, company=company,
                                   year=year, through_month=through_month,
                                   horizon_days=horizon_days, as_of=as_of)
