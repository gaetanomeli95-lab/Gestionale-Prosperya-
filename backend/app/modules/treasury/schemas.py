"""Treasury request schemas.

Money always travels as a **string** (`"1234.56"`): no float ever parses a
monetary value. `extra="forbid"` everywhere so a typo in a client payload
fails loudly instead of being silently ignored.
"""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.money import money, parse_money, parse_signed_money

_AMOUNT = r"^[0-9]{1,18}(?:\.[0-9]{1,2})?$"
_SIGNED_AMOUNT = r"^-?[0-9]{1,18}(?:\.[0-9]{1,2})?$"
_REF = r"^[A-Za-z0-9_./:\- ]+$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BankAccountCreate(Strict):
    label: str = Field(min_length=2, max_length=120, strict=True)
    provider_key: str = Field(default="manual", min_length=1, max_length=60, strict=True)
    provider_api_version: str = Field(default="v1", min_length=1, max_length=20, strict=True)
    provider_account_id: str = Field(min_length=1, max_length=160, pattern=_REF, strict=True)
    bank_name: str | None = Field(default=None, max_length=160)
    iban_last4: str | None = Field(default=None, pattern=r"^[0-9A-Za-z]{4}$")
    credentials_ref: str | None = Field(default=None, max_length=120, pattern=r"^[A-Z0-9_]+$")
    config: dict = Field(default_factory=dict)
    opening_balance: str | None = Field(default=None, pattern=_SIGNED_AMOUNT, strict=True)
    balance_date: date | None = None


class BalanceUpdate(Strict):
    amount: str = Field(pattern=_SIGNED_AMOUNT, strict=True)
    balance_date: date

    @field_validator("amount")
    @classmethod
    def normalized(cls, value: str) -> str:
        return money(parse_signed_money(value, allow_zero=True)) or "0.00"


class SyncRequest(Strict):
    date_from: date | None = None
    date_to: date | None = None
    idempotency_key: str = Field(min_length=1, max_length=128,
                                 pattern=r"^[A-Za-z0-9_.:-]+$", strict=True)


class ManualTransaction(Strict):
    bank_account_id: str = Field(min_length=36, max_length=36)
    provider_tx_id: str = Field(min_length=1, max_length=160, pattern=_REF, strict=True)
    value_date: date
    booking_date: date | None = None
    amount: str = Field(pattern=_SIGNED_AMOUNT, strict=True)
    description: str = Field(default="", max_length=600)
    counterparty_name: str | None = Field(default=None, max_length=300)

    @field_validator("amount")
    @classmethod
    def normalized(cls, value: str) -> str:
        return money(parse_signed_money(value)) or "0.00"


class OpenItemCreate(Strict):
    direction: str = Field(pattern="^(receivable|payable)$", strict=True)
    counterparty_name: str = Field(min_length=1, max_length=300, strict=True)
    counterparty_vat: str | None = Field(default=None, max_length=32)
    document_number: str | None = Field(default=None, max_length=80)
    document_date: date | None = None
    due_date: date
    amount: str = Field(pattern=_AMOUNT, strict=True)
    category: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    source_ref: str | None = Field(default=None, max_length=160, pattern=_REF)

    @field_validator("amount")
    @classmethod
    def normalized(cls, value: str) -> str:
        return money(parse_money(value)) or "0.00"

    @field_validator("due_date", "document_date")
    @classmethod
    def in_range(cls, value: date | None) -> date | None:
        if value is not None and not 2000 <= value.year <= 2100:
            raise ValueError("Data fuori intervallo 2000..2100.")
        return value


class OpenItemImportRow(OpenItemCreate):
    source_ref: str = Field(min_length=1, max_length=160, pattern=_REF, strict=True)


class OpenItemImport(Strict):
    rows: list[OpenItemImportRow] = Field(min_length=1, max_length=2000)


class CloseItemRequest(Strict):
    method: str = Field(pattern="^(write_off|cancellation)$", strict=True)
    reason: str = Field(min_length=5, max_length=300, strict=True)


class AllocationIn(Strict):
    open_item_id: str = Field(min_length=36, max_length=36)
    amount: str = Field(pattern=_AMOUNT, strict=True)

    @field_validator("amount")
    @classmethod
    def normalized(cls, value: str) -> str:
        return money(parse_money(value)) or "0.00"


class ApplyAllocations(Strict):
    bank_transaction_id: str = Field(min_length=36, max_length=36)
    allocations: list[AllocationIn] = Field(min_length=1, max_length=20)
    method: str = Field(default="manual", pattern="^(exact|fuzzy|manual)$", strict=True)
    confidence: str | None = Field(default=None, pattern=r"^(0(?:\.[0-9]{1,2})?|1(?:\.00?)?)$")
    reason: str | None = Field(default=None, max_length=300)
    evidence: dict = Field(default_factory=dict)


class AutoApplyRequest(Strict):
    limit: int = Field(default=50, ge=1, le=200, strict=True)
