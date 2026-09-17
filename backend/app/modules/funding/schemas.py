"""Funding API request schemas — parse only, no business logic."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SourceIn(BaseModel):
    provider: str = Field(default="manual", pattern="^(manual|structured_import)$")
    title: str = Field(min_length=1, max_length=400)
    reference: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=500)
    published_on: date | None = None
    retrieved_at: datetime | None = None
    notes: str | None = None


class WindowIn(BaseModel):
    kind: str = Field(pattern="^(fixed|rolling|until_exhausted|unknown|"
                             "suspended|reopened)$")
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=40)
    notes: str | None = None


class RequirementIn(BaseModel):
    rule_code: str = Field(min_length=1, max_length=60)
    params: dict = Field(default_factory=dict)
    description: str = Field(min_length=1, max_length=400)
    mandatory: bool = True
    sort: int | None = None


class BenefitIn(BaseModel):
    benefit_type: str = Field(pattern="^(grant|soft_loan|guarantee|tax_credit|"
                                      "interest_subsidy|mixed)$")
    max_aid_intensity: Decimal | None = None
    max_amount: Decimal | None = None
    min_investment: Decimal | None = None
    max_investment: Decimal | None = None
    financing_share: Decimal | None = None
    repayment_term_months: int | None = None
    notes: str | None = None


class ExpenseCategoryIn(BaseModel):
    category_code: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=200)
    status: str = Field(pattern="^(eligible|excluded|conditional|"
                                "review_required)$")
    conditions: str | None = None


class DocumentRequirementIn(BaseModel):
    doc_type: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=300)
    required: bool = True
    stage: str | None = Field(default=None, max_length=40)
    notes: str | None = None


class VersionIn(BaseModel):
    version_no: int = Field(default=1, ge=1)
    status: str = Field(default="draft",
                        pattern="^(draft|upcoming|open|closed|suspended|"
                                "exhausted|archived)$")
    publication_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    source: SourceIn | None = None
    source_title: str | None = Field(default=None, max_length=400)
    source_reference: str | None = Field(default=None, max_length=200)
    retrieved_at: datetime | None = None
    change_summary: str | None = None
    notes: str | None = None
    aid_regime_code: str | None = Field(default=None, max_length=40)
    windows: list[WindowIn] = Field(default_factory=list)
    requirements: list[RequirementIn] = Field(default_factory=list)
    benefits: list[BenefitIn] = Field(default_factory=list)
    expense_categories: list[ExpenseCategoryIn] = Field(default_factory=list)
    document_requirements: list[DocumentRequirementIn] = Field(
        default_factory=list)


class ProgrammeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=300)
    authority_id: uuid.UUID | None = None
    authority_code: str | None = Field(default=None, max_length=40)
    status: str = Field(default="draft",
                        pattern="^(draft|upcoming|open|closed|suspended|"
                                "exhausted|archived)$")
    geography: str | None = Field(default=None, max_length=120)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    version: VersionIn | None = None


class AuthorityCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    level: str = Field(pattern="^(eu|national|regional|agency|other)$")
    website: str | None = Field(default=None, max_length=500)


class ProfileUpsert(BaseModel):
    incorporated_on: date | None = None
    is_startup: bool | None = None
    is_innovative_startup: bool | None = None
    female_ownership_pct: Decimal | None = None
    youth_ownership_pct: Decimal | None = None
    project_region: str | None = Field(default=None, max_length=80)
    project_location: str | None = Field(default=None, max_length=200)
    single_undertaking_known: bool | None = None
    group_notes: str | None = None
    aid_history_complete: bool | None = None
    notes: str | None = None


class CompanyAidCreate(BaseModel):
    programme_label: str = Field(min_length=1, max_length=300)
    authority: str | None = Field(default=None, max_length=200)
    regime_code: str | None = Field(default=None, max_length=40)
    granted_on: date
    amount: Decimal = Field(ge=0)
    gge_amount: Decimal | None = Field(default=None, ge=0)
    reference: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    status: str = Field(default="declared",
                        pattern="^(declared|imported|verified)$")


class AssessmentRun(BaseModel):
    version_id: uuid.UUID


class AssessmentReview(BaseModel):
    action: str = Field(pattern="^(review_required|reviewed|"
                                "approved_for_practice|rejected)$")
    notes: str | None = None


class PracticeCreate(BaseModel):
    version_id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    notes: str | None = None


class PracticeTransition(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    note: str | None = None


class PracticeDocumentUpdate(BaseModel):
    status: str = Field(pattern="^(missing|requested|received|validated|"
                                "rejected|not_applicable)$")
    note: str | None = None
    document_ref: str | None = Field(default=None, max_length=300)


class PracticeDeadlineCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime
    notes: str | None = None


class PracticeNoteCreate(BaseModel):
    note: str = Field(min_length=1)
