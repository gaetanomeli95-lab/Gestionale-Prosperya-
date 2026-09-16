"""Controlling API request models. Responses are plain dicts built by the service."""
from datetime import date

from pydantic import BaseModel, Field


class FacilityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    facility_type: str = Field(pattern="^(mortgage|loan|leasing|credit_line|other)$")
    lender_name: str | None = Field(default=None, max_length=160)
    outstanding_principal: str | None = None
    notes: str | None = None


class FacilityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    lender_name: str | None = Field(default=None, max_length=160)
    outstanding_principal: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class InstalmentCreate(BaseModel):
    instalment_no: int = Field(ge=0)
    due_date: date
    principal: str
    interest: str


class InstalmentSettle(BaseModel):
    action: str = Field(pattern="^(paid|waived)$")
    settled_on: date | None = None
    note: str | None = Field(default=None, max_length=300)


class AlertTransition(BaseModel):
    note: str | None = Field(default=None, max_length=600)


class ScenarioRun(BaseModel):
    label: str | None = Field(default=None, max_length=20)
    revenue_change_pct: str = "0"
    collection_delay_days: int = 0
    supplier_delay_days: int = 0
    fixed_cost_monthly_delta: str = "0"
    variable_cost_change_pct: str = "0"
    debt_service_change_pct: str = "0"
