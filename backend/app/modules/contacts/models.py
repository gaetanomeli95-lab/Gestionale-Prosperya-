import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.mixins import (
    GUID,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class Contact(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    """A person. May relate to zero, one or several companies."""

    __tablename__ = "contacts"

    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    role_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    preferred_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    privacy_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    privacy_consent_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    companies = relationship("CompanyContact", back_populates="contact", cascade="all, delete-orphan")


class CompanyContact(PrimaryKeyMixin, Base):
    """Link table: a person in a company, with the relationship role."""

    __tablename__ = "company_contacts"
    __table_args__ = (UniqueConstraint("company_id", "contact_id", name="uq_company_contact"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    company = relationship("Company", back_populates="contacts")
    contact = relationship("Contact", back_populates="companies")
