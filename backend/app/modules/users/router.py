from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.rbac import Role, get_current_user, require_permissions
from app.core.security import hash_password
from app.db import get_db
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
    _: User = Depends(get_current_user),
):
    stmt = select(User).order_by(User.full_name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.full_name.ilike(like)) | (User.email.ilike(like)))
    return paginate(db, stmt, PageParams(page, page_size), UserOut)


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("users:write")),
):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("A user with this email already exists.", code="duplicate_user")
    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=Role(payload.role),
        team=payload.team,
        timezone=payload.timezone,
    )
    db.add(user)
    db.flush()
    record_audit(db, actor_id=actor.id, action="user.create", entity_type="user", entity_id=user.id)
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("users:write")),
):
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(user, k, v)
    record_audit(
        db, actor_id=actor.id, action="user.update", entity_type="user",
        entity_id=user.id, changes={"fields": sorted(data)},
    )
    db.commit()
    return UserOut.model_validate(user)
