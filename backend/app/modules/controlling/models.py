"""Controlling & early-warning domain — debt service, CCII rules, alerts.

Tables owned here (all `tenant_id` + `company_id` where entity-level):

| Tabella | Ruolo | Mutabilità |
|---|---|---|
| `debt_facilities` | linea di debito (mutuo, finanziamento, leasing) | dato di riferimento mutabile |
| `debt_service_lines` | rata pianificata (quota capitale + interessi) | mutabile solo via transizioni di stato tracciate |
| `early_warning_rules` | regole CCII/organizzative versionate, effective-dated | **mai modificate**: nuova versione |
| `controlling_alerts` | alert durevole con ciclo di vita umano | stato mutabile con audit |

Debt service is deliberately **not** an `open_item`: an instalment is a
contracted schedule fact, not a trade payable. It feeds DSCR, the 12-month
continuity view and the "overdue financial exposure" signal without
double-counting treasury open items.
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.mixins import GUID, PrimaryKeyMixin, TenantMixin, TimestampMixin


def _check(condition: str) -> CheckConstraint:
    suffix = hashlib.sha256(condition.encode("ascii")).hexdigest()[:12]
    subject = re.sub(r"[^0-9a-z_]", "", condition.split()[0].lower()) or "expr"
    return CheckConstraint(condition, name=f"ck_{subject}_{suffix}")


class FacilityType(StrEnum):
    MORTGAGE = "mortgage"        # mutuo ipotecario/chirografario
    LOAN = "loan"                # finanziamento a medio termine
    LEASING = "leasing"
    CREDIT_LINE = "credit_line"  # fido con rimborso pianificato
    OTHER = "other"


class InstalmentStatus(StrEnum):
    SCHEDULED = "scheduled"   # in scadenza
    PAID = "paid"             # versata (con data)
    WAIVED = "waived"         # sospesa/annullata con motivazione


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class AlertKind(StrEnum):
    MANAGEMENT = "management"      # indicatore gestionale deteriorato
    EARLY_WARNING = "early_warning"  # segnale legato a regole CCII/organizzative


class RuleStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class ControllingScope(TenantMixin, TimestampMixin):
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class DebtFacility(ControllingScope, PrimaryKeyMixin, Base):
    """A financing line of the client company — reference data.

    Mutable like `management_categories`: correcting a label is not rewriting
    history. What matters for metrics are the scheduled lines.
    """

    __tablename__ = "debt_facilities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "name",
                         name="uq_debt_facility_scope_name"),
        _check("facility_type IN ('mortgage','loan','leasing','credit_line','other')"),
        _check("outstanding_principal IS NULL OR "
               "(outstanding_principal >= 0 AND outstanding_principal < 1000000000000000000)"),
        _check("currency = 'EUR'"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    lender_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    facility_type: Mapped[str] = mapped_column(String(20), nullable=False)
    outstanding_principal: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), nullable=True
    )  # declared residual debt; null = not declared
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )

    lines = relationship("DebtServiceLine", back_populates="facility")


class DebtServiceLine(ControllingScope, PrimaryKeyMixin, Base):
    """One scheduled instalment: principal + interest due on `due_date`.

    `status` transitions are tracked (`paid`/`waived` require evidence fields)
    because a line is a contracted fact — DSCR and continuity depend on it.
    """

    __tablename__ = "debt_service_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "facility_id", "instalment_no",
                         name="uq_debt_line_scope_instalment"),
        _check("instalment_no >= 0"),
        _check("principal >= 0 AND interest >= 0"),
        _check("principal > 0 OR interest > 0"),
        _check("principal < 1000000000000000000 AND interest < 1000000000000000000"),
        _check("status IN ('scheduled','paid','waived')"),
        _check("currency = 'EUR'"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("debt_facilities.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    instalment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    principal: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    interest: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=InstalmentStatus.SCHEDULED,
                                        nullable=False)
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    facility = relationship("DebtFacility", back_populates="lines")


class EarlyWarningRule(TenantMixin, PrimaryKeyMixin, Base):
    """Versioned early-warning rule — jurisdiction-level reference data.

    Same discipline as `fiscal_rule_sets` (ADR-020): rules are effective-dated,
    never edited in place, and carry their source. `params` holds the
    thresholds; each param is labelled `statutory` or `operational` so the UI
    can distinguish a legal value from a configurable working threshold.
    """

    __tablename__ = "early_warning_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version",
                         name="uq_ew_rule_scope_code_version"),
        _check("status IN ('active','superseded')"),
        _check("category IN ('ccii_legal','organizational','operational')"),
        _check("version >= 1"),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=RuleStatus.ACTIVE,
                                        nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    legal_reference: Mapped[str] = mapped_column(String(400), nullable=False)
    source_authority: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_retrieved_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    data_requirements: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)


class ControllingAlert(ControllingScope, PrimaryKeyMixin, Base):
    """Durable alert with a human lifecycle — not a recomputed badge.

    `dedupe_key` makes detection idempotent: re-running the engines refreshes
    `evidence`/`detected_at` of the same alert instead of stacking duplicates.
    When the underlying condition clears, the engine resolves the alert itself
    (`resolution_kind='auto'`); a human may acknowledge, resolve or dismiss
    with a note. Legal/early-warning alerts keep the rule version that fired.
    """

    __tablename__ = "controlling_alerts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "dedupe_key",
                         name="uq_alert_scope_dedupe"),
        _check("status IN ('open','acknowledged','resolved','dismissed')"),
        _check("kind IN ('management','early_warning')"),
        _check("severity IN ('critical','warning','info')"),
    )

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=AlertStatus.OPEN,
                                        nullable=False)
    detected_at: Mapped[date] = mapped_column(Date, nullable=False)
    first_detected_at: Mapped[date] = mapped_column(Date, nullable=False)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )
    resolution_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
