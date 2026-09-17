"""Funding Core — finanza agevolata: canonical domain model.

A programme is a *measure*; a version is one immutable official notice.
Assessments snapshot the exact version + engine + company data used, so a
result stays reproducible after rules change. Nothing here guesses: missing
facts stay INSUFFICIENT_DATA, unknown rules stay UNSUPPORTED.

| Tabella | Ruolo | Mutabilità |
|---|---|---|
| `funding_authorities` | ente erogatore (UE, MIMIT, Invitalia, Regione…) | reference data |
| `funding_sources` | provenance record of an official document | append-only |
| `funding_programmes` | la misura (contenitore logico) | reference data |
| `funding_programme_versions` | un avviso/bando versionato | **mai modificato**: nuova versione |
| `funding_windows` | finestra di presentazione della versione | mutabile via nuova versione |
| `funding_requirements` | regole strutturate della versione | immutabile con la versione |
| `funding_benefits` | forma dell'agevolazione | immutabile con la versione |
| `funding_expense_categories` | spese ammissibili/escluse | immutabile con la versione |
| `funding_document_requirements` | checklist documentale del bando | immutabile con la versione |
| `aid_regimes` | regimi di aiuto versionati (de minimis…) | effective-dated |
| `company_aids` | aiuti già ricevuti dall'azienda | dato dichiarato, mutabile |
| `funding_company_profiles` | attributi di eligibilità non in Company | mutabile (dichiarati) |
| `funding_assessments` | valutazione persistita + snapshot | stato review mutabile |
| `funding_assessment_items` | esito per-requisito con evidenza | immutabile |
| `funding_practices` | pratica di accesso al bando | ciclo di vita mutabile |
| `funding_practice_documents` | checklist documenti della pratica | stato mutabile |
| `funding_practice_deadlines` | scadenze operative della pratica | mutabile |
| `funding_practice_activities` | log attività della pratica | append-only |
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


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AuthorityLevel(StrEnum):
    EU = "eu"
    NATIONAL = "national"
    REGIONAL = "regional"
    AGENCY = "agency"            # Invitalia, gestori, camere di commercio
    OTHER = "other"


class ProgrammeStatus(StrEnum):
    DRAFT = "draft"
    UPCOMING = "upcoming"
    OPEN = "open"
    CLOSED = "closed"
    SUSPENDED = "suspended"
    EXHAUSTED = "exhausted"
    ARCHIVED = "archived"


class WindowKind(StrEnum):
    FIXED = "fixed"                    # opens_at + closes_at
    ROLLING = "rolling"                # sportello, no fixed close
    UNTIL_EXHAUSTED = "until_exhausted"
    UNKNOWN = "unknown"                # not yet defined — never a fake date
    SUSPENDED = "suspended"
    REOPENED = "reopened"


class RuleResult(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED = "unsupported"
    REVIEW_REQUIRED = "review_required"


class AssessmentResult(StrEnum):
    ELIGIBLE = "eligible_on_known_data"
    NOT_ELIGIBLE = "not_eligible"
    POTENTIALLY_ELIGIBLE = "potentially_eligible"
    REVIEW_REQUIRED = "review_required"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED = "unsupported"


class AssessmentStatus(StrEnum):
    CALCULATED = "calculated"
    REVIEW_REQUIRED = "review_required"
    REVIEWED = "reviewed"
    APPROVED_FOR_PRACTICE = "approved_for_practice"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class BenefitType(StrEnum):
    GRANT = "grant"
    SOFT_LOAN = "soft_loan"
    GUARANTEE = "guarantee"
    TAX_CREDIT = "tax_credit"
    INTEREST_SUBSIDY = "interest_subsidy"
    MIXED = "mixed"


class ExpenseStatus(StrEnum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    CONDITIONAL = "conditional"
    REVIEW_REQUIRED = "review_required"


class PracticeStatus(StrEnum):
    DRAFT = "draft"
    DATA_COLLECTION = "data_collection"
    DOCUMENT_COLLECTION = "document_collection"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    INTEGRATION_REQUESTED = "integration_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class PracticeDocStatus(StrEnum):
    MISSING = "missing"
    REQUESTED = "requested"
    RECEIVED = "received"
    VALIDATED = "validated"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


class PracticeDeadlineStatus(StrEnum):
    OPEN = "open"
    MET = "met"
    MISSED = "missed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Reference data: authorities, sources, programmes, versions
# ---------------------------------------------------------------------------

class FundingAuthority(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Erogatore: Commissione UE, MIMIT, Invitalia, Regione Siciliana…"""

    __tablename__ = "funding_authorities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_funding_authority_code"),
        _check("level IN ('eu','national','regional','agency','other')"),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)


class FundingSource(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Provenance of an official document — never a blog or an aggregator."""

    __tablename__ = "funding_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_funding_source_ref"),
        _check("provider IN ('manual','structured_import')"),
    )

    authority_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("funding_authorities.id", ondelete="SET NULL"),
        nullable=True)
    provider: Mapped[str] = mapped_column(String(24), default="manual",
                                          nullable=False)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FundingProgramme(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """La misura — contenitore logico che sopravvive alle versioni."""

    __tablename__ = "funding_programmes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_funding_programme_code"),
        _check("status IN ('draft','upcoming','open','closed','suspended',"
               "'exhausted','archived')"),
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    authority_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("funding_authorities.id", ondelete="SET NULL"),
        nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=ProgrammeStatus.DRAFT,
                                        nullable=False)
    geography: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    authority = relationship("FundingAuthority")
    versions = relationship("FundingProgrammeVersion", back_populates="programme")


class FundingProgrammeVersion(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Un avviso/bando specifico — immutabile una volta usato in valutazioni."""

    __tablename__ = "funding_programme_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "programme_id", "version_no",
                         name="uq_funding_version_scope"),
        _check("status IN ('draft','upcoming','open','closed','suspended',"
               "'exhausted','archived')"),
        _check("version_no >= 1"),
    )

    programme_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programmes.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=ProgrammeStatus.DRAFT,
                                        nullable=False)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("funding_sources.id", ondelete="SET NULL"),
        nullable=True)
    source_title: Mapped[str | None] = mapped_column(String(400), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    aid_regime_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    programme = relationship("FundingProgramme", back_populates="versions")
    source = relationship("FundingSource")
    windows = relationship("FundingWindow", back_populates="version")
    requirements = relationship("FundingRequirement", back_populates="version")
    benefits = relationship("FundingBenefit", back_populates="version")
    expense_categories = relationship("FundingExpenseCategory",
                                      back_populates="version")
    document_requirements = relationship("FundingDocumentRequirement",
                                         back_populates="version")


class FundingWindow(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Application window of a version. `kind='unknown'` is explicit — never
    a far-future placeholder date."""

    __tablename__ = "funding_windows"
    __table_args__ = (
        _check("kind IN ('fixed','rolling','until_exhausted','unknown',"
               "'suspended','reopened')"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programme_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                      nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                       nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    version = relationship("FundingProgrammeVersion", back_populates="windows")


class FundingRequirement(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """One structured eligibility rule of a version.

    `rule_code` selects a deterministic evaluator from the registry;
    `params` carries its operands. Unknown codes evaluate to UNSUPPORTED,
    never to a guess.
    """

    __tablename__ = "funding_requirements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version_id", "sort",
                         name="uq_funding_req_sort"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programme_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(60), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False)

    version = relationship("FundingProgrammeVersion",
                           back_populates="requirements")


class FundingBenefit(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Forma dell'agevolazione. Null = non dichiarato dalla fonte ufficiale."""

    __tablename__ = "funding_benefits"
    __table_args__ = (
        _check("benefit_type IN ('grant','soft_loan','guarantee','tax_credit',"
               "'interest_subsidy','mixed')"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programme_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    benefit_type: Mapped[str] = mapped_column(String(24), nullable=False)
    max_aid_intensity: Mapped[Decimal | None] = mapped_column(Numeric(6, 4),
                                                              nullable=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2),
                                                       nullable=True)
    min_investment: Mapped[Decimal | None] = mapped_column(Numeric(20, 2),
                                                           nullable=True)
    max_investment: Mapped[Decimal | None] = mapped_column(Numeric(20, 2),
                                                           nullable=True)
    financing_share: Mapped[Decimal | None] = mapped_column(Numeric(6, 4),
                                                            nullable=True)
    repayment_term_months: Mapped[int | None] = mapped_column(Integer,
                                                              nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    version = relationship("FundingProgrammeVersion", back_populates="benefits")


class FundingExpenseCategory(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "funding_expense_categories"
    __table_args__ = (
        _check("status IN ('eligible','excluded','conditional','review_required')"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programme_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    category_code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)

    version = relationship("FundingProgrammeVersion",
                           back_populates="expense_categories")


class FundingDocumentRequirement(TenantMixin, PrimaryKeyMixin, TimestampMixin,
                                 Base):
    __tablename__ = "funding_document_requirements"

    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programme_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    version = relationship("FundingProgrammeVersion",
                           back_populates="document_requirements")


# ---------------------------------------------------------------------------
# Aid regimes & company aid history
# ---------------------------------------------------------------------------

class AidRegime(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Versioned aid regime — e.g. Reg. (UE) 2023/2831 de minimis.

    Thresholds are effective-dated reference data, never hard-coded in the
    engine. `period_months` + `rolling` describe the reference window.
    """

    __tablename__ = "aid_regimes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "effective_from",
                         name="uq_aid_regime_version"),
        _check("threshold >= 0"),
        _check("period_months > 0"),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    authority: Mapped[str] = mapped_column(String(120), nullable=False)
    legal_reference: Mapped[str] = mapped_column(String(400), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    threshold: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    period_months: Mapped[int] = mapped_column(Integer, nullable=False)
    rolling: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sector_exclusions: Mapped[list] = mapped_column(JSON, default=list,
                                                    nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)


class CompanyAid(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Un aiuto già concesso all'azienda — dato dichiarato/importato."""

    __tablename__ = "company_aids"
    __table_args__ = (
        _check("amount >= 0"),
        _check("status IN ('declared','imported','verified')"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    programme_label: Mapped[str] = mapped_column(String(300), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    regime_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    granted_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    gge_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2),
                                                       nullable=True)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="declared",
                                        nullable=False)


class FundingCompanyProfile(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Funding-relevant attributes NOT on Company — declared by the operator.

    Absent row or null field = INSUFFICIENT_DATA, never a fabricated value.
    """

    __tablename__ = "funding_company_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id",
                         name="uq_funding_profile_company"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    incorporated_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_startup: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_innovative_startup: Mapped[bool | None] = mapped_column(Boolean,
                                                               nullable=True)
    female_ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2),
                                                                 nullable=True)
    youth_ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2),
                                                                nullable=True)
    project_region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    project_location: Mapped[str | None] = mapped_column(String(200),
                                                         nullable=True)
    single_undertaking_known: Mapped[bool | None] = mapped_column(Boolean,
                                                                  nullable=True)
    group_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    aid_history_complete: Mapped[bool | None] = mapped_column(Boolean,
                                                              nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------

class FundingAssessment(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Persisted eligibility evaluation — reproducible snapshot.

    `company_snapshot` freezes the facts used; `engine_version` +
    `version_id` make the result replayable even after rules change.
    """

    __tablename__ = "funding_assessments"
    __table_args__ = (
        _check("result IN ('eligible_on_known_data','not_eligible',"
               "'potentially_eligible','review_required','insufficient_data',"
               "'unsupported')"),
        _check("status IN ('calculated','review_required','reviewed',"
               "'approved_for_practice','rejected','superseded')"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programme_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(24),
                                        default=AssessmentStatus.CALCULATED,
                                        nullable=False)
    company_snapshot: Mapped[dict] = mapped_column(JSON, default=dict,
                                                   nullable=False)
    missing_data: Mapped[list] = mapped_column(JSON, default=list,
                                               nullable=False)
    unsupported_rules: Mapped[list] = mapped_column(JSON, default=list,
                                                    nullable=False)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True)

    items = relationship("FundingAssessmentItem", back_populates="assessment")


class FundingAssessmentItem(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "funding_assessment_items"
    __table_args__ = (
        _check("result IN ('satisfied','not_satisfied','insufficient_data',"
               "'unsupported','review_required')"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_assessments.id", ondelete="CASCADE"),
        nullable=False, index=True)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("funding_requirements.id", ondelete="SET NULL"),
        nullable=True)
    rule_code: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True,
                                            nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    assessment = relationship("FundingAssessment", back_populates="items")


# ---------------------------------------------------------------------------
# Practices
# ---------------------------------------------------------------------------

class FundingPractice(TenantMixin, PrimaryKeyMixin, TimestampMixin, Base):
    """Pratica di accesso al bando — ciclo di vita gestito da un professionista."""

    __tablename__ = "funding_practices"
    __table_args__ = (
        _check("status IN ('draft','data_collection','document_collection',"
               "'ready_to_submit','submitted','under_review',"
               "'integration_requested','approved','rejected','withdrawn',"
               "'closed')"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_programme_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("funding_assessments.id", ondelete="SET NULL"),
        nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default=PracticeStatus.DRAFT,
                                        nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True)
    # Link to the generic operational practice (document/practice core).
    practice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("practices.id", ondelete="SET NULL"),
        nullable=True, index=True)

    version = relationship("FundingProgrammeVersion")
    documents = relationship("FundingPracticeDocument",
                             back_populates="practice")
    deadlines = relationship("FundingPracticeDeadline",
                             back_populates="practice")
    activities = relationship("FundingPracticeActivity",
                              back_populates="practice")


class FundingPracticeDocument(TenantMixin, PrimaryKeyMixin, TimestampMixin,
                              Base):
    __tablename__ = "funding_practice_documents"
    __table_args__ = (
        _check("status IN ('missing','requested','received','validated',"
               "'rejected','not_applicable')"),
    )

    practice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_practices.id", ondelete="CASCADE"),
        nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20),
                                        default=PracticeDocStatus.MISSING,
                                        nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    practice = relationship("FundingPractice", back_populates="documents")


class FundingPracticeDeadline(TenantMixin, PrimaryKeyMixin, TimestampMixin,
                              Base):
    __tablename__ = "funding_practice_deadlines"
    __table_args__ = (
        _check("status IN ('open','met','missed','cancelled')"),
    )

    practice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_practices.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                             nullable=False)
    status: Mapped[str] = mapped_column(String(12),
                                        default=PracticeDeadlineStatus.OPEN,
                                        nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    practice = relationship("FundingPractice", back_populates="deadlines")


class FundingPracticeActivity(TenantMixin, PrimaryKeyMixin, TimestampMixin,
                              Base):
    __tablename__ = "funding_practice_activities"

    practice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("funding_practices.id", ondelete="CASCADE"),
        nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    practice = relationship("FundingPractice", back_populates="activities")
