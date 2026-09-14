"""Tenants = client companies served by the platform operator (ADR-011)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.mixins import PrimaryKeyMixin, utcnow


class Tenant(Base, PrimaryKeyMixin):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    vat_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_platform_org: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        doc="True for the operator's own org tenant (staff home tenant).",
    )
    branding: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        doc="White-label: {app_name, logo_url, accent_color, ...}",
    )
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.slug}>"
