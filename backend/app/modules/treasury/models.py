"""Treasury domain — open items, bank movements, reconciliation.

The canonical financial chain this module owns (ADR-016):

    invoice / manual entry
      -> open_item      (what is owed, by whom, when)
      -> bank_transaction (what actually moved on the account)
      -> reconciliation_allocation (which movement settles which item, and why)
      -> cash position / forecast

Discipline, identical to `management` (ADR-014):

* **Append-only**: `bank_transactions`, `open_items` and
  `reconciliation_allocations` reject UPDATE/DELETE at ORM level. A wrong open
  item is closed by a `cancellation` allocation, never edited; an unrecoverable
  receivable is closed by a `write_off` allocation. Every closure keeps an
  actor and evidence.
* **Derived, never stored**: settled amount, residual and status are computed
  from allocations, so a number can always be re-derived from its sources.
* Money is `Decimal`/`NUMERIC(20,2)`; bank amounts are signed (negative =
  outflow), open items are always positive with an explicit `direction`.
"""
import hashlib
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.mixins import GUID, PrimaryKeyMixin, TenantMixin, TimestampMixin, utcnow


def _check(condition: str) -> CheckConstraint:
    """Stable, portable constraint name derived from the condition itself."""
    suffix = hashlib.sha256(condition.encode("ascii")).hexdigest()[:12]
    subject = re.sub(r"[^0-9a-z_]", "", condition.split()[0].lower()) or "expr"
    return CheckConstraint(condition, name=f"ck_{subject}_{suffix}")


class ItemDirection(StrEnum):
    RECEIVABLE = "receivable"   # crediti verso clienti — inflow expected
    PAYABLE = "payable"         # debiti verso fornitori/enti — outflow expected


class ItemSource(StrEnum):
    INVOICE = "invoice"         # derived from an issued Prosperya invoice
    MANUAL = "manual"           # entered by an operator
    IMPORT = "import"           # loaded from an external file/feed


class ItemStatus(StrEnum):
    """Derived, never persisted — see `service.item_state`."""

    OPEN = "open"
    PARTIALLY_SETTLED = "partially_settled"
    SETTLED = "settled"
    WRITTEN_OFF = "written_off"
    CANCELLED = "cancelled"


class AllocationMethod(StrEnum):
    EXACT = "exact"             # level 1: deterministic exact match
    FUZZY = "fuzzy"             # level 2: deterministic scoring, human-approved
    MANUAL = "manual"           # operator chose the pairing
    WRITE_OFF = "write_off"     # closed without a bank movement (loss)
    CANCELLATION = "cancellation"  # item was wrong: closed with evidence


class ConnectionStatus(StrEnum):
    NOT_CONNECTED = "not_connected"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class TreasuryScope(TenantMixin, TimestampMixin):
    """Every treasury row belongs to exactly one (tenant, company) pair."""

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class BankAccount(TreasuryScope, PrimaryKeyMixin, Base):
    """A bank account of the client company.

    Holds the latest known balance plus its provenance. Secrets are never
    stored: a provider connection is referenced by `credentials_ref` (env var /
    secret-manager key) exactly like billing providers (ADR-009). Only the last
    four IBAN characters are persisted — enough to recognise the account,
    useless if the database leaks.
    """

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "provider_key", "provider_account_id",
                         name="uq_bank_account_provider_ref"),
        _check("currency = 'EUR'"),
        _check("balance_amount IS NULL OR (balance_amount > -1000000000000000000 "
               "AND balance_amount < 1000000000000000000)"),
        _check("balance_source IN ('provider', 'manual')"),
    )

    label: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    iban_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)

    # --- provider connection (abstraction, never a hard-wired vendor) -------
    provider_key: Mapped[str] = mapped_column(String(60), default="manual", nullable=False)
    provider_api_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_account_id: Mapped[str] = mapped_column(String(160), nullable=False)
    credentials_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Non-secret adapter configuration (endpoints, scripted sandbox scenarios).
    # Secrets belong to `credentials_ref` only.
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    connection_status: Mapped[str] = mapped_column(
        String(24), default=ConnectionStatus.NOT_CONNECTED, nullable=False
    )
    connection_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- latest known balance + provenance ----------------------------------
    balance_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    balance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    balance_source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)

    transactions = relationship("BankTransaction", back_populates="account")


class BankTransaction(TreasuryScope, PrimaryKeyMixin, Base):
    """An immutable bank movement.

    `provider_tx_id` is unique per account: re-running a sync can never
    duplicate a movement. `amount` is signed (negative = outflow).
    """

    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bank_account_id", "provider_tx_id",
                         name="uq_bank_tx_provider_ref"),
        _check("amount <> 0 AND amount > -1000000000000000000 AND amount < 1000000000000000000"),
        _check("currency = 'EUR'"),
    )

    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_tx_id: Mapped[str] = mapped_column(String(160), nullable=False)
    booking_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    counterparty_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    counterparty_iban_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    description: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    # provenance of the row itself: which provider/sync produced it
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    sync_batch_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)

    account = relationship("BankAccount", back_populates="transactions")


class OpenItem(TreasuryScope, PrimaryKeyMixin, Base):
    """A receivable or payable with a due date — the scadenzario row.

    Immutable. `source` + `source_ref` make ingestion idempotent: syncing the
    same invoice twice is a no-op, and an imported row can always be traced
    back to its origin document.
    """

    __tablename__ = "open_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "source", "source_ref",
                         name="uq_open_item_source_ref"),
        _check("direction IN ('receivable', 'payable')"),
        _check("source IN ('invoice', 'manual', 'import')"),
        _check("amount > 0 AND amount < 1000000000000000000"),
        _check("currency = 'EUR'"),
    )

    direction: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    counterparty_name: Mapped[str] = mapped_column(String(300), nullable=False)
    counterparty_vat: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    # Optional management classification so a settled item can feed cost
    # analysis without re-typing (kept nullable: unknown stays unknown).
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)

    allocations = relationship("ReconciliationAllocation", back_populates="open_item")


class ReconciliationAllocation(TreasuryScope, PrimaryKeyMixin, Base):
    """Append-only link: this much of this movement settles this open item.

    Supports every real-world shape: one movement → many items (cumulative
    payment), many movements → one item (instalments), partial settlement, and
    closures without a movement (`write_off` / `cancellation`, where
    `bank_transaction_id` is NULL).

    `method` records HOW the pairing was decided, `engine_version` +
    `evidence` make it reproducible, `approved_by_id` records the human who
    accepted it. Nothing here is ever written by an AI without approval.
    """

    __tablename__ = "reconciliation_allocations"
    __table_args__ = (
        _check("amount > 0 AND amount < 1000000000000000000"),
        _check("method IN ('exact', 'fuzzy', 'manual', 'write_off', 'cancellation')"),
        _check("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)"),
        _check("(bank_transaction_id IS NOT NULL) "
               "OR method IN ('write_off', 'cancellation')"),
    )

    open_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("open_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    open_item = relationship("OpenItem", back_populates="allocations")


class BankSyncBatch(TreasuryScope, PrimaryKeyMixin, Base):
    """One provider refresh run — the audit record of a data ingestion."""

    __tablename__ = "bank_sync_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "idempotency_key",
                         name="uq_bank_sync_idempotency"),
        _check("fetched_count >= 0 AND inserted_count >= 0 AND duplicate_count >= 0"),
    )

    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_api_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), default="sandbox", nullable=False)
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=True
    )


def _reject_mutation(mapper, connection, target) -> None:  # noqa: ARG001 — SQLAlchemy signature
    raise ValueError(
        "Lo storico di tesoreria è append-only: chiudere la partita con una "
        "nuova allocazione (write_off/cancellation) tracciata."
    )


for _model in (BankTransaction, OpenItem, ReconciliationAllocation, BankSyncBatch):
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)
