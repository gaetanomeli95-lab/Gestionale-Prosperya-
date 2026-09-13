import uuid
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.mixins import (
    GUID,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class CompanyStatus(StrEnum):
    PROSPECT = "prospect"
    CUSTOMER = "customer"
    FORMER = "former"


class LifecycleStage(StrEnum):
    LEAD = "lead"
    QUALIFIED = "qualified"
    ACTIVE = "active"
    DORMANT = "dormant"


class CompanySizeBand(StrEnum):
    MICRO = "micro"          # < 10 employees
    SMALL = "small"          # 10-49
    MEDIUM = "medium"        # 50-249
    LARGE = "large"          # 250+
    UNKNOWN = "unknown"


class Company(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_vat_normalized", "vat_number", unique=True),
        Index("ix_companies_legal_name", "legal_name"),
    )

    legal_name: Mapped[str] = mapped_column(String(300), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    vat_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    legal_form: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ateco_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True)

    size_band: Mapped[str] = mapped_column(String(16), default=CompanySizeBand.UNKNOWN, nullable=False)
    revenue_eur: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    pec: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)

    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default=CompanyStatus.PROSPECT, nullable=False)
    lifecycle_stage: Mapped[str] = mapped_column(String(24), default=LifecycleStage.LEAD, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)

    owner = relationship("User", foreign_keys=[owner_id])
    contacts = relationship("CompanyContact", back_populates="company", cascade="all, delete-orphan")
