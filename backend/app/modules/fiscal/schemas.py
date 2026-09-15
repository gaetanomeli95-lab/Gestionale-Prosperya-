"""Fiscal API request models. Responses are plain dicts built by the service."""
from datetime import date

from pydantic import BaseModel, Field


class VatEntryCreate(BaseModel):
    direction: str = Field(pattern="^(sale|purchase)$")
    competence_date: date
    taxable_amount: str
    vat_amount: str | None = None
    vat_rate: str | None = None
    vat_nature: str | None = Field(default=None, max_length=8)
    deductible: bool | None = None
    document_number: str | None = Field(default=None, max_length=80)
    document_date: date | None = None
    counterparty_name: str | None = Field(default=None, max_length=300)
    counterparty_vat: str | None = Field(default=None, max_length=32)
    source_ref: str | None = Field(default=None, max_length=160)
    notes: str | None = None


class VatEntryRow(BaseModel):
    direction: str = Field(pattern="^(sale|purchase)$")
    competence_date: date
    taxable_amount: str
    source_ref: str = Field(min_length=1, max_length=160)
    vat_amount: str | None = None
    vat_rate: str | None = None
    vat_nature: str | None = Field(default=None, max_length=8)
    deductible: bool | None = None
    document_number: str | None = Field(default=None, max_length=80)
    document_date: date | None = None
    counterparty_name: str | None = Field(default=None, max_length=300)
    counterparty_vat: str | None = Field(default=None, max_length=32)
    notes: str | None = None


class VatEntryImport(BaseModel):
    rows: list[VatEntryRow] = Field(min_length=1)


class EntryConfirm(BaseModel):
    treatment: str = Field(pattern="^(supported|unsupported)$")
    deductible: bool | None = None
    reason: str | None = Field(default=None, max_length=300)


class SettlementCalculate(BaseModel):
    year: int = Field(ge=2000, le=2100)
    period_no: int = Field(ge=1, le=12)
    frequency: str = Field(pattern="^(monthly|quarterly)$")


class SettlementValidate(BaseModel):
    note: str | None = Field(default=None, max_length=600)
    acknowledge_warnings: bool = False


class F24Transition(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class F24ExportRequest(BaseModel):
    format: str = Field(default="json", pattern="^(json|csv)$")
