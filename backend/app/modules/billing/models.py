"""Billing domain — provider-independent core entities.

Invoices live in Prosperya's own database. Providers are transport
channels: ``provider_key``/``provider_external_id`` record WHERE a
document was sent, never WHO the document is. A provider switch changes
the config row — history stays untouched.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
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
from app.modules.billing.statuses import InvoiceStatus
from app.shared.mixins import (
    GUID,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
    utcnow,
)


class Invoice(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    """Prosperya-owned invoice. Fiscal fields are frozen at finalize time;
    provider/SdI identifiers accrete as transmission progresses."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("series", "fiscal_year", "number", name="uq_invoice_number"),
    )

    # --- identity / numbering (assigned at finalize, never in draft) ----
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    series: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)

    # --- parties --------------------------------------------------------
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Immutable snapshots captured at issue time — later CRM edits to the
    # customer record must NOT rewrite issued fiscal documents.
    customer_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    issuer_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # --- internal workflow status (normalized) ---------------------------
    status: Mapped[str] = mapped_column(
        String(40), default=InvoiceStatus.DRAFT, nullable=False, index=True
    )
    # Separate axes — never merged into ``status``:
    provider_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sdi_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # --- money -----------------------------------------------------------
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    taxable_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    withholding_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    stamp_duty: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    payment_terms: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- transmission metadata -------------------------------------------
    provider_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_api_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_external_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    sdi_identifier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sdi_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    xml_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Idempotency key: one per send-intention; retries of the same
    # intention reuse it so a retry can never duplicate the submission.
    submission_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # provenance: manual | import | api — imported docs are never re-sent
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)

    company = relationship("Company")
    lines = relationship("InvoiceLine", back_populates="invoice",
                         cascade="all, delete-orphan", order_by="InvoiceLine.position")
    transmission_events = relationship(
        "InvoiceTransmissionEvent", back_populates="invoice",
        cascade="all, delete-orphan", order_by="InvoiceTransmissionEvent.created_at",
    )


class InvoiceLine(PrimaryKeyMixin, Base):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)          # e.g. 22.00
    vat_nature: Mapped[str | None] = mapped_column(String(8), nullable=True)         # es. N2.2
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    invoice = relationship("Invoice", back_populates="lines")


class InvoiceSequence(Base):
    """Transaction-safe fiscal numbering: one row per (series, fiscal_year).
    ``last_number`` is incremented inside the finalize transaction."""

    __tablename__ = "invoice_sequences"
    __table_args__ = (UniqueConstraint("series", "fiscal_year", name="uq_invoice_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    series: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class BillingProviderConfig(PrimaryKeyMixin, TimestampMixin, Base):
    """Configured provider instance. Exactly one row has ``is_active``.
    ``credentials_ref`` names an env var / secret-manager key — secrets are
    NEVER persisted here."""

    __tablename__ = "billing_provider_configs"

    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    api_version: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), default="sandbox", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    credentials_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    webhook_secret_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvoiceTransmissionEvent(Base):
    """Append-only transmission history. Survives provider switches —
    each event records WHICH provider/api-version produced it."""

    __tablename__ = "invoice_transmission_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_api_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    invoice = relationship("Invoice", back_populates="transmission_events")


class WebhookEventRecord(Base):
    """Inbound provider events. ``(provider_key, provider_event_id)`` is
    unique: duplicate deliveries are acknowledged but never reprocessed."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider_key", "provider_event_id", name="uq_webhook_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processing_result: Mapped[str | None] = mapped_column(String(60), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEvent(Base):
    """Generic transactional outbox. A business transaction commits the
    domain change AND the outbox row atomically — a later dispatcher
    performs the external call. Swappable for a real worker/queue."""

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
