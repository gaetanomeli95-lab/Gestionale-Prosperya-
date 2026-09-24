"""Canonical document domain — one infrastructure for every module.

A Document is the logical identity (title, type, company). A DocumentVersion
is immutable content metadata: checksum, storage reference, source. Content
is never overwritten — a new file is a new version; the previous one is
marked SUPERSEDED and stays reproducible as evidence.

DocumentRequirement generalises "this practice needs document X" so funding,
fiscal and future modules share the same checklist mechanics instead of
growing private mini-document systems.
"""
import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class DocumentStatus(StrEnum):
    RECEIVED = "received"          # content stored, not yet reviewed
    TO_REVIEW = "to_review"        # explicitly queued for human review
    VALIDATED = "validated"        # human-validated current version
    REJECTED = "rejected"          # current version rejected by a human
    EXPIRED = "expired"            # past expires_on
    SUPERSEDED = "superseded"      # replaced by a newer document/version
    ARCHIVED = "archived"          # soft-retired, kept for evidence


class VersionStatus(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"


class DocumentSource(StrEnum):
    UPLOAD = "upload"              # manual upload by a user
    IMPORT = "import"              # structured import
    GENERATED = "generated"        # produced by the system (e.g. F24 draft)
    EXTERNAL = "external"          # reference to an external system


class ValidationResult(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"


class RequirementStatus(StrEnum):
    MISSING = "missing"
    REQUESTED = "requested"
    RECEIVED = "received"
    VALIDATED = "validated"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


class DocumentType(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-scoped registry of document types. Seeded with the common
    office set; tenants may add their own. `code` is the stable key modules
    reference (e.g. "visura_camerale", "f24_draft")."""

    __tablename__ = "document_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_document_type_code"),
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(40), default="generic", nullable=False)
    tracks_expiry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Document(TenantMixin, PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Logical document identity. Never holds bytes — only metadata and the
    pointer to the current immutable version."""

    __tablename__ = "documents"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("document_types.id", ondelete="SET NULL"),
        nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.RECEIVED, nullable=False, index=True)
    # Circular FK (documents <-> document_versions) emitted via ALTER TABLE.
    # It MUST be named: PostgreSQL needs the name for DROP CONSTRAINT during
    # metadata.drop_all. The name matches PostgreSQL's default for the
    # constraint created by migration fddef49e1556, so ORM and DB agree.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("document_versions.id", ondelete="SET NULL",
                           use_alter=True,
                           name="documents_current_version_id_fkey"),
        nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    company = relationship("Company")
    doc_type = relationship("DocumentType")
    versions = relationship(
        "DocumentVersion", back_populates="document",
        foreign_keys="DocumentVersion.document_id",
        order_by="DocumentVersion.version_no")
    current_version = relationship(
        "DocumentVersion", foreign_keys=[current_version_id],
        post_update=True)
    links = relationship("DocumentLink", back_populates="document")


class DocumentVersion(TenantMixin, PrimaryKeyMixin, Base):
    """Immutable content version. Rows are never updated in place except the
    `status` flag (current → superseded) — content metadata is frozen at
    insert time so evidence stays reproducible."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no",
                         name="uq_document_version_no"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    storage_provider: Mapped[str] = mapped_column(
        String(40), default="local_filesystem", nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(500), nullable=False)

    source: Mapped[str] = mapped_column(
        String(20), default=DocumentSource.UPLOAD, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=VersionStatus.CURRENT, nullable=False)

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    document = relationship("Document", back_populates="versions",
                            foreign_keys=[document_id])
    uploaded_by = relationship("User")
    validations = relationship("DocumentValidation",
                               back_populates="version")


class DocumentLink(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Generic link from a document to any business entity — practice,
    fiscal output, funding assessment, future modules."""

    __tablename__ = "document_links"

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    document = relationship("Document", back_populates="links")


class DocumentValidation(TenantMixin, PrimaryKeyMixin, Base):
    """Human validation record on a specific version. AI may later suggest;
    the final decision is always a user's."""

    __tablename__ = "document_validations"

    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    validated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    version = relationship("DocumentVersion", back_populates="validations")
    validated_by = relationship("User")


class DocumentRequirement(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """"This practice/company needs document X" — the shared checklist row.

    `module` says who asked (funding, fiscal, generic…). `practice_id` links
    to the generic operational practice when the requirement belongs to one.
    `source_ref` keeps the id of the domain-side record (e.g. a
    FundingPracticeDocument) so specialised modules stay authoritative for
    their own detail while the dossier reads one canonical list."""

    __tablename__ = "document_requirements"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    practice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("practices.id", ondelete="SET NULL"),
        nullable=True, index=True)
    module: Mapped[str] = mapped_column(String(40), default="generic", nullable=False)
    doc_type_code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_validation: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=RequirementStatus.MISSING, nullable=False, index=True)
    accepted_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    accepted_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    company = relationship("Company")
    practice = relationship("Practice")
    accepted_document = relationship("Document")
    accepted_version = relationship("DocumentVersion")


# ---------------------------------------------------------------------------
# Seed registry — common office document types.
# ---------------------------------------------------------------------------

DOCUMENT_TYPE_SEED: list[dict] = [
    {"code": "visura_camerale", "label": "Visura camerale",
     "domain": "generic", "tracks_expiry": True},
    {"code": "documento_identita", "label": "Documento d'identità",
     "domain": "generic", "tracks_expiry": True},
    {"code": "bilancio", "label": "Bilancio d'esercizio",
     "domain": "generic", "tracks_expiry": False},
    {"code": "durc", "label": "DURC", "domain": "fiscal",
     "tracks_expiry": True},
    {"code": "f24_draft", "label": "F24 (bozza interna)", "domain": "fiscal",
     "tracks_expiry": False},
    {"code": "certificato", "label": "Certificato / attestazione",
     "domain": "generic", "tracks_expiry": True},
    {"code": "business_plan", "label": "Business plan",
     "domain": "funding", "tracks_expiry": False},
    {"code": "preventivo", "label": "Preventivo / fattura proforma",
     "domain": "funding", "tracks_expiry": False},
    {"code": "delega", "label": "Delega / autorizzazione",
     "domain": "generic", "tracks_expiry": True},
    {"code": "altro", "label": "Altro documento", "domain": "generic",
     "tracks_expiry": False},
]
