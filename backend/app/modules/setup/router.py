"""First-run setup for a fresh installation (no demo data).

`POST /setup` is only allowed while the database has ZERO users. It creates
the customer's tenant, provisions defaults (pipeline stages, service lines)
and the first administrator. After that the endpoint is permanently closed.
"""
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.rbac import Role
from app.core.security import create_access_token, hash_password
from app.db import get_db
from app.modules.tenancy.models import Tenant
from app.modules.tenancy.provisioning import provision_defaults
from app.modules.users.models import User
from app.modules.users.schemas import TokenResponse, UserOut

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    needs_setup: bool


class SetupPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: str = Field(min_length=2, max_length=200)
    vat_number: str | None = Field(default=None, max_length=20)
    admin_name: str = Field(min_length=1, max_length=200)
    admin_email: EmailStr
    admin_password: str = Field(min_length=10, max_length=200)


def _needs_setup(db: Session) -> bool:
    return (db.scalar(select(func.count(User.id))) or 0) == 0


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "azienda")[:60]


@router.get("/status", response_model=SetupStatus)
def setup_status(db: Session = Depends(get_db)):
    return SetupStatus(needs_setup=_needs_setup(db))


@router.post("", response_model=TokenResponse, status_code=201)
def run_setup(payload: SetupPayload, db: Session = Depends(get_db)):
    if not _needs_setup(db):
        raise ConflictError("L'installazione è già configurata.", code="setup_done")
    tenant = Tenant(
        slug=_slugify(payload.company_name),
        display_name=payload.company_name,
        legal_name=payload.company_name,
        vat_number=payload.vat_number or None,
        is_platform_org=True,  # in a single-customer install the customer IS the org
        branding={"app_name": payload.company_name},
    )
    db.add(tenant)
    db.flush()
    provision_defaults(db, tenant)
    admin = User(
        email=payload.admin_email.lower(),
        full_name=payload.admin_name,
        hashed_password=hash_password(payload.admin_password),
        role=Role.ADMIN,
        tenant_id=tenant.id,
    )
    db.add(admin)
    db.commit()
    return TokenResponse(access_token=create_access_token(admin.id), user=UserOut.model_validate(admin))
