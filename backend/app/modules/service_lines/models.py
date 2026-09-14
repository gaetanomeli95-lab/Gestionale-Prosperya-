from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.mixins import GUID, PrimaryKeyMixin, TenantMixin, TimestampMixin


class ServiceLine(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Configurable Prosperya service lines — never free-text on records."""

    __tablename__ = "service_lines"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_service_line_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PipelineStage(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Configurable pipeline stage. Stages are ordered and may be terminal."""

    __tablename__ = "pipeline_stages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "service_line_id", "name", name="uq_stage_per_service"),
    )

    service_line_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("service_lines.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    default_probability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_won: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expected_value_eur: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
