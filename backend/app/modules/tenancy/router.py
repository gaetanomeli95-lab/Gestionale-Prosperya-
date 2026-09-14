"""Tenant management (staff) + current-tenant info (everyone)."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.tenancy.models import Tenant
from app.modules.tenancy.provisioning import provision_defaults
from app.modules.users.models import User

router = APIRouter(tags=["tenancy"])


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str
    legal_name: str | None
    vat_number: str | None
    is_active: bool
    is_platform_org: bool
    branding: dict

    model_config = {"from_attributes": True}


class TenantCreate(BaseModel):
    slug: str
    display_name: str
    legal_name: str | None = None
    vat_number: str | None = None


@router.get("/tenants/current", response_model=TenantOut)
def current_tenant(ctx: TenantContext = Depends(get_tenant_ctx)):
    return ctx.tenant


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("tenants:read")),
):
    return db.scalars(select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.display_name)).all()


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("tenants:write")),
):
    tenant = Tenant(**payload.model_dump())
    db.add(tenant)
    db.flush()
    provision_defaults(db, tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("tenants:write")),
):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Tenant not found")
    for k in ("display_name", "legal_name", "vat_number", "is_active", "branding", "settings"):
        if k in payload:
            setattr(tenant, k, payload[k])
    db.commit()
    db.refresh(tenant)
    return tenant
