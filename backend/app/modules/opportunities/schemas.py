import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.opportunities.models import OpportunityStatus


class OpportunityBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    company_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    service_line_id: uuid.UUID | None = None
    stage_id: uuid.UUID
    owner_id: uuid.UUID | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_value_eur: float | None = None
    expected_close_date: date | None = None
    source: str | None = Field(default=None, max_length=120)
    next_action: str | None = Field(default=None, max_length=300)
    next_action_date: date | None = None


class OpportunityCreate(OpportunityBase):
    pass


class OpportunityUpdate(BaseModel):
    version: int
    title: str | None = Field(default=None, min_length=1, max_length=300)
    contact_id: uuid.UUID | None = None
    service_line_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_value_eur: float | None = None
    expected_close_date: date | None = None
    source: str | None = None
    next_action: str | None = None
    next_action_date: date | None = None
    lost_reason: str | None = None


class OpportunityMove(BaseModel):
    stage_id: uuid.UUID
    lost_reason: str | None = None


class OpportunityOut(OpportunityBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    status: OpportunityStatus
    lost_reason: str | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OpportunityListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    company_id: uuid.UUID
    stage_id: uuid.UUID
    status: OpportunityStatus
    probability: int | None
    expected_value_eur: float | None
    expected_close_date: date | None
    owner_id: uuid.UUID | None
    updated_at: datetime
