import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.leads.models import LeadPriority, LeadSource, LeadStatus


class LeadBase(BaseModel):
    company_name: str = Field(min_length=1, max_length=300)
    contact_name: str | None = Field(default=None, max_length=240)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    source: LeadSource = LeadSource.OTHER
    status: LeadStatus = LeadStatus.NEW
    priority: LeadPriority = LeadPriority.MEDIUM
    interest: str | None = None
    estimated_value_eur: float | None = None
    next_action: str | None = Field(default=None, max_length=300)
    next_action_date: datetime | None = None
    owner_id: uuid.UUID | None = None
    service_line_id: uuid.UUID | None = None


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    version: int
    company_name: str | None = Field(default=None, min_length=1, max_length=300)
    contact_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    source: LeadSource | None = None
    status: LeadStatus | None = None
    priority: LeadPriority | None = None
    interest: str | None = None
    estimated_value_eur: float | None = None
    next_action: str | None = None
    next_action_date: datetime | None = None
    owner_id: uuid.UUID | None = None
    service_line_id: uuid.UUID | None = None


class LeadOut(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    converted_company_id: uuid.UUID | None
    converted_contact_id: uuid.UUID | None
    converted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadConvertRequest(BaseModel):
    """Convert a lead. All captured data is carried forward — the operator
    never retypes what the CRM already knows."""

    create_opportunity: bool = True
    opportunity_title: str | None = None
    stage_id: uuid.UUID | None = None
    existing_company_id: uuid.UUID | None = None  # link instead of creating


class LeadConvertResponse(BaseModel):
    lead: LeadOut
    company_id: uuid.UUID
    contact_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
