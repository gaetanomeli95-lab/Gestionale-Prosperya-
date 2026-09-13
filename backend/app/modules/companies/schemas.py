import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.companies.models import CompanySizeBand, CompanyStatus, LifecycleStage


class CompanyBase(BaseModel):
    legal_name: str = Field(min_length=1, max_length=300)
    trading_name: str | None = Field(default=None, max_length=300)
    vat_number: str | None = Field(default=None, max_length=32)
    tax_code: str | None = Field(default=None, max_length=32)
    legal_form: str | None = Field(default=None, max_length=60)
    ateco_code: str | None = Field(default=None, max_length=16)
    industry: str | None = Field(default=None, max_length=160)
    size_band: CompanySizeBand = CompanySizeBand.UNKNOWN
    revenue_eur: float | None = None
    employee_count: int | None = Field(default=None, ge=0)
    country: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    postal_code: str | None = Field(default=None, max_length=16)
    website: str | None = Field(default=None, max_length=300)
    email: EmailStr | None = None
    pec: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    source: str | None = Field(default=None, max_length=120)
    status: CompanyStatus = CompanyStatus.PROSPECT
    lifecycle_stage: LifecycleStage = LifecycleStage.LEAD
    tags: list[str] = Field(default_factory=list)
    custom_fields: dict = Field(default_factory=dict)
    owner_id: uuid.UUID | None = None


class CompanyCreate(CompanyBase):
    confirm_duplicate: bool = False


class CompanyUpdate(BaseModel):
    version: int
    legal_name: str | None = Field(default=None, min_length=1, max_length=300)
    trading_name: str | None = None
    vat_number: str | None = None
    tax_code: str | None = None
    legal_form: str | None = None
    ateco_code: str | None = None
    industry: str | None = None
    size_band: CompanySizeBand | None = None
    revenue_eur: float | None = None
    employee_count: int | None = Field(default=None, ge=0)
    country: str | None = None
    region: str | None = None
    city: str | None = None
    address: str | None = None
    postal_code: str | None = None
    website: str | None = None
    email: EmailStr | None = None
    pec: EmailStr | None = None
    phone: str | None = None
    source: str | None = None
    status: CompanyStatus | None = None
    lifecycle_stage: LifecycleStage | None = None
    tags: list[str] | None = None
    custom_fields: dict | None = None
    owner_id: uuid.UUID | None = None


class CompanyOut(CompanyBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CompanyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    legal_name: str
    vat_number: str | None
    city: str | None
    region: str | None
    status: CompanyStatus
    lifecycle_stage: LifecycleStage
    size_band: CompanySizeBand
    owner_id: uuid.UUID | None
    updated_at: datetime


class DuplicateMatch(BaseModel):
    kind: str  # "vat" | "tax_code" | "pec" | "name"
    company_id: uuid.UUID
    legal_name: str
    detail: str


class DuplicateCheckResponse(BaseModel):
    matches: list[DuplicateMatch]
