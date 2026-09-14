"""Assistant API — tenant/company-scoped deterministic AI chat."""
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.assistant import service
from app.modules.companies.models import Company
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/assistant", tags=["assistant"])


class ChatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000, strict=True)
    year: int = Field(default=2026, ge=2000, le=2100, strict=True)
    through_month: int = Field(default=6, ge=1, le=12, strict=True)


@router.post("/companies/{company_id}/chat")
def assistant_chat(
    company_id: UUID,
    payload: ChatPayload,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("assistant:use")),
):
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != ctx.tenant_id or company.deleted_at is not None:
        raise NotFoundError("Company not found.")
    return service.chat(db, tenant_id=ctx.tenant_id, company=company,
                        message=payload.message, year=payload.year,
                        through_month=payload.through_month)
