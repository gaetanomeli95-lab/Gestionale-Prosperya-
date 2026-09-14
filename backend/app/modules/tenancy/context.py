"""Tenant context resolution (ADR-011).

Effective tenant =
  - client-role users  -> always their own `user.tenant_id` (locked)
  - staff roles        -> `X-Tenant-Id` header if provided, else their home tenant

Every tenant-scoped query must go through `scope()` or verify ownership via
`get_owned()`.
"""
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, NotFoundError
from app.core.rbac import STAFF_ROLES, get_current_user
from app.db import get_db
from app.modules.tenancy.models import Tenant
from app.modules.users.models import User


@dataclass
class TenantContext:
    tenant: Tenant
    user: User
    switched: bool  # staff acting on a tenant that isn't their home tenant

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id


def get_tenant_ctx(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> TenantContext:
    is_staff = user.role in STAFF_ROLES
    target_id = None
    if is_staff and x_tenant_id:
        try:
            target_id = uuid.UUID(x_tenant_id)
        except ValueError:
            raise ForbiddenError("Invalid X-Tenant-Id header.", code="invalid_tenant") from None
    elif user.tenant_id is not None:
        target_id = user.tenant_id
    if target_id is None:
        # Staff without a home tenant: fall back to the platform org tenant.
        tenant = db.scalar(select(Tenant).where(Tenant.is_platform_org.is_(True)).limit(1))
        if tenant is None:
            raise ForbiddenError("No tenant context available.", code="no_tenant")
        return TenantContext(tenant=tenant, user=user, switched=False)

    tenant = db.get(Tenant, target_id)
    if tenant is None or not tenant.is_active:
        raise ForbiddenError("Tenant not found or inactive.", code="tenant_not_found")
    if not is_staff and user.tenant_id != tenant.id:
        raise ForbiddenError("Cross-tenant access denied.", code="tenant_forbidden")
    return TenantContext(tenant=tenant, user=user, switched=target_id != user.tenant_id)


def scope(stmt, model, ctx: TenantContext):
    """Apply tenant isolation to a SELECT on a TenantMixin model."""
    return stmt.where(model.tenant_id == ctx.tenant_id)


def get_owned(db: Session, model, entity_id: uuid.UUID, ctx: TenantContext):
    """Fetch a tenant-scoped entity or 404 (never leak cross-tenant existence)."""
    obj = db.get(model, entity_id)
    if obj is None or getattr(obj, "tenant_id", ctx.tenant_id) != ctx.tenant_id:
        raise NotFoundError(f"{model.__name__} not found")
    return obj
