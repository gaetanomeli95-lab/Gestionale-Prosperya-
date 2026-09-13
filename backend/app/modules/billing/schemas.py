import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.billing.statuses import (
    InvoiceStatus,
    PaymentStatus,
    ProviderHealthStatus,
    SdiStatus,
)


class InvoiceLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100)
    vat_rate: Decimal = Field(ge=0, le=100)
    vat_nature: str | None = Field(default=None, max_length=8)


class InvoiceLineOut(InvoiceLineIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    line_total: Decimal | None


class InvoiceCreate(BaseModel):
    company_id: uuid.UUID
    series: str | None = Field(default=None, max_length=16)
    payment_terms: str | None = Field(default=None, max_length=160)
    payment_method: str | None = Field(default=None, max_length=60)
    notes: str | None = None
    lines: list[InvoiceLineIn] = Field(min_length=1)


class InvoiceUpdate(BaseModel):
    version: int
    series: str | None = Field(default=None, max_length=16)
    payment_terms: str | None = None
    payment_method: str | None = None
    notes: str | None = None
    stamp_duty: Decimal | None = Field(default=None, ge=0)
    lines: list[InvoiceLineIn] | None = Field(default=None, min_length=1)


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    number: int | None
    series: str
    fiscal_year: int | None
    issue_date: date | None
    company_id: uuid.UUID
    customer_snapshot: dict
    issuer_snapshot: dict
    status: InvoiceStatus
    provider_status: str | None
    sdi_status: SdiStatus | str | None
    payment_status: PaymentStatus | str | None
    currency: str
    taxable_amount: Decimal | None
    vat_amount: Decimal | None
    total_amount: Decimal | None
    payment_terms: str | None
    payment_method: str | None
    notes: str | None
    provider_key: str | None
    provider_external_id: str | None
    sdi_identifier: str | None
    source: str
    sent_at: datetime | None
    delivered_at: datetime | None
    rejected_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceDetail(InvoiceOut):
    lines: list[InvoiceLineOut] = []


class InvoiceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int | None
    series: str
    fiscal_year: int | None
    issue_date: date | None
    company_id: uuid.UUID
    status: InvoiceStatus
    provider_status: str | None
    total_amount: Decimal | None
    updated_at: datetime


class TransmissionEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    provider_key: str | None
    provider_api_version: str | None
    from_status: str | None
    to_status: str | None
    provider_status: str | None
    provider_event_id: str | None
    error_category: str | None
    detail: str | None
    created_at: datetime


class ProviderConfigIn(BaseModel):
    provider_key: str = Field(min_length=1, max_length=60)
    api_version: str = Field(min_length=1, max_length=20)
    display_name: str | None = Field(default=None, max_length=160)
    environment: str = Field(default="sandbox", pattern="^(sandbox|production)$")
    config: dict = Field(default_factory=dict)
    credentials_ref: str | None = Field(default=None, max_length=120)
    webhook_secret_ref: str | None = Field(default=None, max_length=120)


class ProviderConfigOut(BaseModel):
    """Never exposes secrets — only metadata and the credentials_ref name."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_key: str
    api_version: str
    display_name: str | None
    environment: str
    is_active: bool
    credentials_configured: bool = False
    last_health_check_at: datetime | None
    last_health_status: str | None
    last_successful_sync_at: datetime | None
    last_successful_send_at: datetime | None


class ProviderStatusOut(BaseModel):
    configured: bool
    provider: ProviderConfigOut | None = None
    health_status: ProviderHealthStatus | None = None
    health_detail: str | None = None
    capabilities: dict | None = None
    available_providers: list[dict] = []


class FinalizeRequest(BaseModel):
    issue_date: date | None = None
