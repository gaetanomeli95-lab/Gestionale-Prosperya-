import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.mixins import (
    GUID,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class OpportunityStatus(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class Opportunity(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "opportunities"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    service_line_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("service_lines.id", ondelete="SET NULL"), nullable=True
    )
    stage_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("pipeline_stages.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(16), default=OpportunityStatus.OPEN, nullable=False, index=True
    )
    probability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_value_eur: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    next_action: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_action_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    lost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company = relationship("Company")
    stage = relationship("PipelineStage")
    service_line = relationship("ServiceLine")
