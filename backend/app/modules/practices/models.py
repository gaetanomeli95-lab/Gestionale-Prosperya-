"""Generic operational practice / case core.

One canonical container for office work across domains: funding, fiscal,
consulting, startup, controlling, generic and future modules. Domain
modules keep their specialised records (e.g. FundingPractice) and link to
a generic Practice for the shared operational surface — status, owner,
blockers, client requests, deadlines, activity.

Lifecycle is bounded but deliberately coarse; richer domain workflows stay
inside their own modules.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.mixins import (
    GUID,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    utcnow,
)


class PracticeType(StrEnum):
    FUNDING = "funding"
    FISCAL = "fiscal"
    CONSULTING = "consulting"
    STARTUP = "startup"
    CONTROLLING = "controlling"
    GENERIC = "generic"


class PracticeStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    WAITING_CLIENT = "waiting_client"
    WAITING_EXTERNAL = "waiting_external"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PracticePriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class BlockerKind(StrEnum):
    MISSING_DOCUMENT = "missing_document"
    CLIENT_RESPONSE_REQUIRED = "client_response_required"
    EXTERNAL_RESPONSE_REQUIRED = "external_response_required"
    DATA_INCOMPLETE = "data_incomplete"
    REVIEW_REQUIRED = "review_required"
    DEADLINE_RISK = "deadline_risk"


class BlockerStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ClientRequestStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    PARTIAL = "partial"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


#: Bounded generic lifecycle. Domain modules may keep richer workflows —
# this is the shared operational surface, not a straitjacket.
PRACTICE_TRANSITIONS: dict[str, set[str]] = {
    PracticeStatus.DRAFT: {PracticeStatus.OPEN, PracticeStatus.CANCELLED},
    PracticeStatus.OPEN: {PracticeStatus.IN_PROGRESS,
                          PracticeStatus.WAITING_CLIENT,
                          PracticeStatus.WAITING_EXTERNAL,
                          PracticeStatus.READY, PracticeStatus.CANCELLED},
    PracticeStatus.IN_PROGRESS: {PracticeStatus.WAITING_CLIENT,
                                 PracticeStatus.WAITING_EXTERNAL,
                                 PracticeStatus.READY,
                                 PracticeStatus.COMPLETED,
                                 PracticeStatus.CANCELLED},
    PracticeStatus.WAITING_CLIENT: {PracticeStatus.IN_PROGRESS,
                                    PracticeStatus.OPEN,
                                    PracticeStatus.CANCELLED},
    PracticeStatus.WAITING_EXTERNAL: {PracticeStatus.IN_PROGRESS,
                                      PracticeStatus.OPEN,
                                      PracticeStatus.CANCELLED},
    PracticeStatus.READY: {PracticeStatus.IN_PROGRESS,
                           PracticeStatus.COMPLETED,
                           PracticeStatus.WAITING_CLIENT,
                           PracticeStatus.WAITING_EXTERNAL,
                           PracticeStatus.CANCELLED},
    PracticeStatus.COMPLETED: set(),
    PracticeStatus.CANCELLED: set(),
}

TERMINAL_STATUSES = {PracticeStatus.COMPLETED, PracticeStatus.CANCELLED}


class Practice(TenantMixin, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Operational case container. `source_module` records which domain
    opened it; `external_ref` holds an outside-system reference when the
    practice mirrors work tracked elsewhere."""

    __tablename__ = "practices"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    practice_type: Mapped[str] = mapped_column(
        String(20), default=PracticeType.GENERIC, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=PracticeStatus.DRAFT, nullable=False, index=True)
    priority: Mapped[str] = mapped_column(
        String(16), default=PracticePriority.MEDIUM, nullable=False)

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False)
    target_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    source_module: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    company = relationship("Company")
    owner = relationship("User")
    blockers = relationship("PracticeBlocker", back_populates="practice",
                            order_by="PracticeBlocker.created_at")
    client_requests = relationship("ClientRequest", back_populates="practice")


class PracticeBlocker(TenantMixin, PrimaryKeyMixin, Base):
    """Structural reason a practice cannot advance — never just free text.
    `ref_type`/`ref_id` point at the blocking entity (a document
    requirement, a client request, a deadline) when applicable."""

    __tablename__ = "practice_blockers"

    practice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=BlockerStatus.OPEN, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    practice = relationship("Practice", back_populates="blockers")


class ClientRequest(TenantMixin, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Lightweight request to the client for information or documents.
    V1 tracks the operational state only — no portal/email automation."""

    __tablename__ = "client_requests"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    practice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("practices.id", ondelete="SET NULL"),
        nullable=True, index=True)
    item: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=ClientRequestStatus.DRAFT, nullable=False, index=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    fulfilled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    company = relationship("Company")
    practice = relationship("Practice", back_populates="client_requests")
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    fulfilled_by = relationship("User", foreign_keys=[fulfilled_by_id])
