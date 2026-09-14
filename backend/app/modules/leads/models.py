import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.mixins import (
    GUID,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
)


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    CONVERTED = "converted"


class LeadSource(StrEnum):
    WEBSITE = "website"
    REFERRAL = "referral"
    SOCIAL = "social"
    EVENT = "event"
    PARTNER = "partner"
    EXISTING_CLIENT = "existing_client"
    OUTREACH = "outreach"
    IMPORT = "import"
    OTHER = "other"


class LeadPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Lead(TenantMixin, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    """Pre-qualification record. Converts into company+contact+opportunity
    without re-entering data already captured."""

    __tablename__ = "leads"

    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)

    source: Mapped[str] = mapped_column(String(32), default=LeadSource.OTHER, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=LeadStatus.NEW, nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(16), default=LeadPriority.MEDIUM, nullable=False)
    interest: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_value_eur: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    next_action: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_action_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    service_line_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("service_lines.id", ondelete="SET NULL"), nullable=True
    )
    # Populated on conversion — the lead keeps pointing at what it became.
    converted_company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    converted_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
