from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.rbac import CLIENT_ROLES, Role, get_current_user, require_permissions
from app.core.security import hash_password
from app.db import get_db
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.tenancy.models import Tenant
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserOut, UserUpdate
from app.shared.events import record_audit
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserOut])
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: str | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(get_current_user),
):
    # Staff see every user (they manage tenants); client-role users only
    # ever see accounts inside their own tenant.
    stmt = select(User).order_by(User.full_name)
    if ctx.user.role in CLIENT_ROLES:
        stmt = stmt.where(User.tenant_id == ctx.tenant_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.full_name.ilike(like)) | (User.email.ilike(like)))
    return paginate(db, stmt, PageParams(page, page_size), UserOut)


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("users:write")),
):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("A user with this email already exists.", code="duplicate_user")
    role = Role(payload.role)
    tenant_id = payload.tenant_id
    if actor.role in CLIENT_ROLES and role not in CLIENT_ROLES:
        raise ForbiddenError("Client users cannot assign staff roles.")
    if role in CLIENT_ROLES:
        # Client users must belong to a concrete tenant. Client admins can
        # only create users inside their own tenant.
        if actor.role in CLIENT_ROLES and tenant_id not in (None, actor.tenant_id):
            raise ForbiddenError("Client users can only create accounts in their own tenant.")
        tenant_id = tenant_id or (actor.tenant_id if actor.role in CLIENT_ROLES else ctx.tenant_id)
        if tenant_id is None or db.get(Tenant, tenant_id) is None:
            raise ValidationError("A valid tenant is required for client roles.",
                                  code="tenant_required")
    elif tenant_id is not None and db.get(Tenant, tenant_id) is None:
        raise ValidationError("Unknown tenant.", code="tenant_not_found")
    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=role,
        tenant_id=tenant_id,
        team=payload.team,
        timezone=payload.timezone,
    )
    db.add(user)
    db.flush()
    record_audit(db, actor_id=actor.id, action="user.create", entity_type="user",
                 entity_id=user.id, tenant_id=tenant_id)
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("users:write")),
):
    user = db.get(User, user_id)
    if user is None or (
        actor.role in CLIENT_ROLES and user.tenant_id != actor.tenant_id
    ):
        raise NotFoundError("User not found.")
    data = payload.model_dump(exclude_unset=True)
    if "role" in data and actor.role in CLIENT_ROLES and Role(data["role"]) not in CLIENT_ROLES:
        raise ForbiddenError("Client users cannot assign staff roles.")
    if "tenant_id" in data and actor.role in CLIENT_ROLES:
        raise ForbiddenError("Client users cannot move accounts across tenants.")
    for k, v in data.items():
        setattr(user, k, v)
    record_audit(
        db, actor_id=actor.id, action="user.update", entity_type="user",
        entity_id=user.id, tenant_id=user.tenant_id, changes={"fields": sorted(data)},
    )
    db.commit()
    return UserOut.model_validate(user)
