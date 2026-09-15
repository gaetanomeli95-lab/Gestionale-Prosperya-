"""Fiscal domain — VAT register, periods, settlements, deadlines, F24.

Design rules (ADR-020/021):

* **No fiscal constant lives in code.** Every threshold, due-date rule, tax
  code and interest rate comes from a `FiscalRuleSet` row that carries its
  authoritative source (authority, title, URL, publication/update date,
  retrieval date) and is **effective-dated**. A calculation stores the rule-set
  id it used, so any number can be reproduced later.
* **Append-only where it matters.** `vat_entries` reject UPDATE/DELETE at ORM
  level: a wrong entry is corrected by a reversal entry that points at it.
  `vat_settlements` are *versioned*: a recalculation inserts a new version and
  marks the previous one `superseded` — only lifecycle fields (status,
  validation, supersession) ever change on an existing row, and each change is
  audited.
* **Unsupported is not zero.** A transaction whose VAT treatment the engine
  cannot handle is recorded as `unsupported`/`requires_review` and *excluded*
  from totals while being counted and listed, so a settlement can never look
  precise while ignoring material data.
* Money is `Decimal`/`NUMERIC(20,2)`, serialised as strings; unknown stays
  `NULL`.
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
from app.shared.mixins import GUID, PrimaryKeyMixin, TenantMixin, TimestampMixin


def _check(condition: str) -> CheckConstraint:
    suffix = hashlib.sha256(condition.encode("ascii")).hexdigest()[:12]
    subject = re.sub(r"[^0-9a-z_]", "", condition.split()[0].lower()) or "expr"
    return CheckConstraint(condition, name=f"ck_{subject}_{suffix}")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RuleFamily(StrEnum):
    VAT_PERIODIC = "vat_periodic"        # liquidazione e versamento IVA periodica
    PAYMENT_CALENDAR = "payment_calendar"  # differimenti sabato/festivi e agosto
    F24_TAX_CODES = "f24_tax_codes"      # codici tributo
    F24_FORMAT = "f24_format"            # rappresentazione importi sul modello


class RuleStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DRAFT = "draft"


class VatDirection(StrEnum):
    SALE = "sale"            # IVA a debito (operazioni attive)
    PURCHASE = "purchase"    # IVA a credito (acquisti, se detraibile)


class VatSource(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    INVOICE = "invoice"              # Prosperya invoice (billing module)
    INVOICE_XML = "invoice_xml"      # FatturaPA ingestion — not implemented yet
    ADJUSTMENT = "adjustment"        # rettifica/nota di variazione registrata a mano
    OPENING_BALANCE = "opening_balance"
    SYSTEM_DERIVED = "system_derived"


class VatTreatment(StrEnum):
    """How confidently the engine can use the entry in a settlement."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"            # treatment outside the supported subset
    REQUIRES_REVIEW = "requires_review"    # human must decide before calculating
    INSUFFICIENT_DATA = "insufficient_data"


class PeriodFrequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class PeriodStatus(StrEnum):
    OPEN = "open"
    CALCULATED = "calculated"
    REVIEW_REQUIRED = "review_required"
    VALIDATED = "validated"
    LOCKED = "locked"


class SettlementStatus(StrEnum):
    CALCULATED = "calculated"
    REVIEW_REQUIRED = "review_required"
    VALIDATED = "validated"
    SUPERSEDED = "superseded"


class DeadlineStatus(StrEnum):
    PENDING = "pending"                  # calcolata, non ancora validata
    VALIDATED = "validated"              # obbligazione confermata da un umano
    SETTLED = "settled"                  # pagata e riconciliata
    CANCELLED = "cancelled"              # superata da un nuovo calcolo


class DueDateStatus(StrEnum):
    RESOLVED = "resolved"
    REVIEW_REQUIRED = "review_required"  # differimento non risolvibile con le regole note


class F24Status(StrEnum):
    GENERATED = "generated"
    VALIDATION_REQUIRED = "validation_required"
    VALIDATED = "validated"
    APPROVED = "approved"
    EXPORTED = "exported"
    # Deliberately absent from the supported flow: transmission requires an
    # authorised Entratel/CBI channel that this platform does not have.
    TRANSMITTED = "transmitted"
    PAID = "paid"


# ---------------------------------------------------------------------------
# Versioned regulatory layer (jurisdiction-level reference data)
# ---------------------------------------------------------------------------

class FiscalRuleSet(PrimaryKeyMixin, TimestampMixin, Base):
    """An effective-dated set of fiscal rules with its authoritative source.

    Not tenant-scoped: the law is the same for every tenant. Rows are
    reference data — a new version supersedes the previous one instead of
    editing it, so past calculations stay reproducible.
    """

    __tablename__ = "fiscal_rule_sets"
    __table_args__ = (
        UniqueConstraint("jurisdiction", "rule_family", "version",
                         name="uq_rule_set_family_version"),
        _check("status IN ('active', 'superseded', 'draft')"),
        _check("effective_to IS NULL OR effective_to >= effective_from"),
    )

    code: Mapped[str] = mapped_column(String(80), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(8), default="IT", nullable=False)
    rule_family: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=RuleStatus.ACTIVE, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    #: The rule values themselves (thresholds, rates, codes, calendars).
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # --- provenance: mandatory, not decorative --------------------------
    source_authority: Mapped[str] = mapped_column(String(120), nullable=False)
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str] = mapped_column(String(600), nullable=False)
    source_published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[date] = mapped_column(Date, nullable=False)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legal_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)

    tax_codes = relationship("FiscalTaxCode", back_populates="rule_set")


class FiscalTaxCode(PrimaryKeyMixin, TimestampMixin, Base):
    """F24 tax-code registry entry, effective-dated and sourced.

    Only the codes needed by the supported flows are seeded: transcribing
    thousands of codes by hand would create unverifiable data. `sync` from an
    official source is the intended growth path.
    """

    __tablename__ = "fiscal_tax_codes"
    __table_args__ = (
        UniqueConstraint("jurisdiction", "code", "valid_from", name="uq_tax_code_validity"),
        _check("section IN ('erario', 'inps', 'regioni', 'imu', 'altri')"),
        _check("valid_to IS NULL OR valid_to >= valid_from"),
    )

    code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    jurisdiction: Mapped[str] = mapped_column(String(8), default="IT", nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    section: Mapped[str] = mapped_column(String(16), default="erario", nullable=False)
    #: What the code is used for inside the platform (vat_monthly, vat_quarterly…).
    usage: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Month (1-12) or quarter (1-4) the code is tied to, when applicable.
    reference_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Whether "rateazione/regione/prov./mese rif." must stay empty.
    requires_reference_period: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_rule_sets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(String(600), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rule_set = relationship("FiscalRuleSet", back_populates="tax_codes")


# ---------------------------------------------------------------------------
# Tenant-scoped fiscal data
# ---------------------------------------------------------------------------

class FiscalScope(TenantMixin, TimestampMixin):
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class VatEntry(FiscalScope, PrimaryKeyMixin, Base):
    """One VAT-relevant fact. Immutable.

    `competence_date` is the date that decides **which period** the entry
    belongs to (esigibilità for sales, exercise of the deduction right for
    purchases); `document_date` stays for traceability. Keeping them separate
    is what makes a defensible settlement possible.
    """

    __tablename__ = "vat_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "source", "source_ref",
                         name="uq_vat_entry_source_ref"),
        _check("direction IN ('sale', 'purchase')"),
        _check("treatment IN ('supported', 'unsupported', 'requires_review', 'insufficient_data')"),
        _check("taxable_amount > -1000000000000000000 AND taxable_amount < 1000000000000000000"),
        _check("vat_amount IS NULL OR (vat_amount > -1000000000000000000 "
               "AND vat_amount < 1000000000000000000)"),
        _check("currency = 'EUR'"),
    )

    direction: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    document_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    competence_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    counterparty_vat: Mapped[str | None] = mapped_column(String(32), nullable=True)

    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    #: FatturaPA "natura" code (N1…N7) when the operation carries no VAT.
    vat_nature: Mapped[str | None] = mapped_column(String(8), nullable=True)
    #: Purchases only: False when VAT is not deductible (art. 19-bis1 cases).
    deductible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    treatment: Mapped[str] = mapped_column(
        String(24), default=VatTreatment.SUPPORTED, nullable=False, index=True
    )
    treatment_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Reversal link: an adjustment entry points at the entry it corrects.
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)


class FiscalPeriod(FiscalScope, PrimaryKeyMixin, Base):
    """An explicit VAT period. Calculations always name their period."""

    __tablename__ = "fiscal_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "year", "frequency", "period_no",
                         name="uq_fiscal_period_scope"),
        _check("frequency IN ('monthly', 'quarterly')"),
        _check("year BETWEEN 2000 AND 2100"),
        _check("period_no BETWEEN 1 AND 12"),
        _check("end_date >= start_date"),
        _check("status IN ('open', 'calculated', 'review_required', 'validated', 'locked')"),
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_no: Mapped[int] = mapped_column(Integer, nullable=False)
    frequency: Mapped[str] = mapped_column(String(12), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=PeriodStatus.OPEN, nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False)


class VatSettlement(FiscalScope, PrimaryKeyMixin, Base):
    """The result of a periodic VAT calculation. Append-only and versioned.

    Recalculating does not overwrite: a new version is inserted and the
    previous one becomes `superseded`, keeping the audit trail intact.
    """

    __tablename__ = "vat_settlements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_id", "version", name="uq_settlement_version"),
        _check("version > 0"),
        _check("status IN ('calculated', 'review_required', 'validated', 'superseded')"),
        _check("currency = 'EUR'"),
    )

    period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_periods.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_rule_sets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)

    # --- components, never just a final number --------------------------
    debit_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    credit_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    prior_credit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    prior_small_debit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    interest_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    net_position: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    payable_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    carry_forward_credit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    carry_forward_debit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)

    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unsupported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Full trace: source ids, components, formulas, rule provenance, warnings.
    trace: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    validated_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_note: Mapped[str | None] = mapped_column(String(600), nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class FiscalDeadline(FiscalScope, PrimaryKeyMixin, Base):
    """A dated fiscal obligation produced by a calculation.

    `due_date` may be NULL with `due_date_status='review_required'`: when the
    deferral rules known to the engine cannot resolve a date (e.g. a local
    patron-saint holiday), the platform says so instead of guessing.
    """

    __tablename__ = "fiscal_deadlines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "kind", "period_id",
                         name="uq_fiscal_deadline_period"),
        _check("status IN ('pending', 'validated', 'settled', 'cancelled')"),
        _check("due_date_status IN ('resolved', 'review_required')"),
        _check("amount IS NULL OR amount >= 0"),
    )

    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("fiscal_periods.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("vat_settlements.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    statutory_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    due_date_status: Mapped[str] = mapped_column(
        String(20), default=DueDateStatus.RESOLVED, nullable=False
    )
    deferral_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=DeadlineStatus.PENDING, nullable=False)
    rule_set_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("fiscal_rule_sets.id", ondelete="RESTRICT"), nullable=True
    )
    #: Treasury open item created once the obligation is validated.
    open_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class F24Draft(FiscalScope, PrimaryKeyMixin, Base):
    """An F24 draft built from validated fiscal liabilities.

    This is an **internal** document. It is not a telematic F24: producing one
    requires an official technical specification and an authorised channel
    (see `docs/FISCAL_ARCHITECTURE.md` §F24 export).
    """

    __tablename__ = "f24_drafts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "settlement_id", name="uq_f24_draft_settlement"),
        _check("status IN ('generated', 'validation_required', 'validated', 'approved', 'exported')"),
        _check("currency = 'EUR'"),
    )

    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("vat_settlements.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    deadline_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("fiscal_deadlines.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    rule_set_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("fiscal_rule_sets.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default=F24Status.GENERATED, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    total_debit: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    total_credit: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Snapshot of the taxpayer identity at generation time.
    taxpayer_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    validated_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_format: Mapped[str | None] = mapped_column(String(40), nullable=True)
    export_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    lines = relationship("F24Line", back_populates="draft",
                         cascade="all, delete-orphan", order_by="F24Line.position")


class F24Line(FiscalScope, PrimaryKeyMixin, Base):
    """One F24 row. Every line must answer "why does this line exist?"."""

    __tablename__ = "f24_lines"
    __table_args__ = (
        _check("section IN ('erario', 'inps', 'regioni', 'imu', 'altri')"),
        _check("debit_amount >= 0 AND credit_amount >= 0"),
        _check("reference_year BETWEEN 2000 AND 2100"),
    )

    draft_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("f24_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    section: Mapped[str] = mapped_column(String(16), default="erario", nullable=False)
    tax_code: Mapped[str] = mapped_column(String(12), nullable=False)
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("fiscal_tax_codes.id", ondelete="RESTRICT"), nullable=True
    )
    tax_code_description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reference_year: Mapped[int] = mapped_column(Integer, nullable=False)
    #: "rateazione/regione/prov./mese rif." — empty when the code forbids it.
    reference_period: Mapped[str | None] = mapped_column(String(12), nullable=True)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0, nullable=False)

    #: Provenance of the line: which liability/calculation produced it.
    origin_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    origin_settlement_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    origin_deadline_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    rule_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    explanation: Mapped[str | None] = mapped_column(String(600), nullable=False)

    draft = relationship("F24Draft", back_populates="lines")


def _reject_mutation(mapper, connection, target) -> None:  # noqa: ARG001 — SQLAlchemy signature
    raise ValueError(
        "Lo storico fiscale è append-only: registrare una rettifica o ricalcolare "
        "creando una nuova versione tracciata."
    )


for _model in (VatEntry,):
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)
