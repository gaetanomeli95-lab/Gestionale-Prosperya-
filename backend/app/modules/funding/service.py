"""Funding Core service — canonical model, deterministic assessments,
human review.

Layering: routers parse/authorize → service decides → rules.py evaluates.
Every persisted assessment snapshots the programme version, the engine
version and the company facts used, so results stay reproducible.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.companies.models import Company
from app.modules.funding import rules
from app.modules.funding.models import (
    AidRegime,
    AssessmentResult,
    AssessmentStatus,
    CompanyAid,
    FundingAssessment,
    FundingAssessmentItem,
    FundingAuthority,
    FundingBenefit,
    FundingCompanyProfile,
    FundingDocumentRequirement,
    FundingExpenseCategory,
    FundingProgramme,
    FundingProgrammeVersion,
    FundingRequirement,
    FundingSource,
    FundingWindow,
    ProgrammeStatus,
    RuleResult,
)
from app.shared.mixins import today, utcnow

LIMITATIONS = [
    "L'eligibilità è deterministica su dati dichiarati: non sostituisce la "
    "verifica professionale né la lettura integrale dell'avviso.",
    "Il cumulo de minimis è calcolato solo sugli aiuti dichiarati: senza "
    "storico completo e perimetro di impresa unica il risultato è parziale.",
    "Nessuna integrazione automatica con RNA o portali ufficiali in V1: "
    "le fonti sono inserite manualmente o via import strutturato.",
]

ASSESSMENT_TRANSITIONS: dict[str, set[str]] = {
    AssessmentStatus.CALCULATED: {AssessmentStatus.REVIEW_REQUIRED,
                                  AssessmentStatus.REVIEWED,
                                  AssessmentStatus.REJECTED},
    AssessmentStatus.REVIEW_REQUIRED: {AssessmentStatus.REVIEWED,
                                       AssessmentStatus.REJECTED},
    AssessmentStatus.REVIEWED: {AssessmentStatus.APPROVED_FOR_PRACTICE,
                                AssessmentStatus.REJECTED},
    AssessmentStatus.APPROVED_FOR_PRACTICE: {AssessmentStatus.SUPERSEDED},
    AssessmentStatus.REJECTED: set(),
    AssessmentStatus.SUPERSEDED: set(),
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def company_or_404(db: Session, company_id: uuid.UUID, tenant_id) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id or company.deleted_at:
        raise NotFoundError("Azienda non trovata.")
    return company


def _version_or_404(db: Session, version_id: uuid.UUID, tenant_id) -> FundingProgrammeVersion:
    version = db.get(FundingProgrammeVersion, version_id)
    if version is None or version.tenant_id != tenant_id:
        raise NotFoundError("Versione del programma non trovata.")
    return version


def _programme_or_404(db: Session, programme_id: uuid.UUID, tenant_id) -> FundingProgramme:
    programme = db.get(FundingProgramme, programme_id)
    if programme is None or programme.tenant_id != tenant_id:
        raise NotFoundError("Programma non trovato.")
    return programme


def _assessment_or_404(db: Session, assessment_id: uuid.UUID, tenant_id) -> FundingAssessment:
    assessment = db.get(FundingAssessment, assessment_id)
    if assessment is None or assessment.tenant_id != tenant_id:
        raise NotFoundError("Valutazione non trovata.")
    return assessment


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _d(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def _source_out(source: FundingSource | None) -> dict | None:
    if source is None:
        return None
    return {
        "id": str(source.id), "provider": source.provider,
        "title": source.title, "reference": source.reference,
        "url": source.url, "published_on": _d(source.published_on),
        "retrieved_at": _dt(source.retrieved_at), "notes": source.notes,
    }


def _window_out(window: FundingWindow) -> dict:
    return {
        "id": str(window.id), "kind": window.kind,
        "opens_at": _dt(window.opens_at), "closes_at": _dt(window.closes_at),
        "timezone": window.timezone, "notes": window.notes,
    }


def _requirement_out(req: FundingRequirement) -> dict:
    return {
        "id": str(req.id), "rule_code": req.rule_code, "params": req.params,
        "description": req.description, "mandatory": req.mandatory,
        "sort": req.sort,
    }


def _benefit_out(benefit: FundingBenefit) -> dict:
    return {
        "id": str(benefit.id), "benefit_type": benefit.benefit_type,
        "max_aid_intensity": _dec(benefit.max_aid_intensity),
        "max_amount": _dec(benefit.max_amount),
        "min_investment": _dec(benefit.min_investment),
        "max_investment": _dec(benefit.max_investment),
        "financing_share": _dec(benefit.financing_share),
        "repayment_term_months": benefit.repayment_term_months,
        "notes": benefit.notes,
    }


def _expense_out(row: FundingExpenseCategory) -> dict:
    return {
        "id": str(row.id), "category_code": row.category_code,
        "label": row.label, "status": row.status, "conditions": row.conditions,
    }


def _doc_req_out(row: FundingDocumentRequirement) -> dict:
    return {
        "id": str(row.id), "doc_type": row.doc_type, "label": row.label,
        "required": row.required, "stage": row.stage, "notes": row.notes,
    }


def _version_out(version: FundingProgrammeVersion, *, detail: bool = False) -> dict:
    out = {
        "id": str(version.id), "programme_id": str(version.programme_id),
        "version_no": version.version_no, "status": version.status,
        "publication_date": _d(version.publication_date),
        "effective_from": _d(version.effective_from),
        "effective_to": _d(version.effective_to),
        "source_id": str(version.source_id) if version.source_id else None,
        "source_title": version.source_title,
        "source_reference": version.source_reference,
        "retrieved_at": _dt(version.retrieved_at),
        "change_summary": version.change_summary,
        "aid_regime_code": version.aid_regime_code,
        "windows": [_window_out(w) for w in version.windows],
    }
    if detail:
        out["requirements"] = [_requirement_out(r)
                               for r in sorted(version.requirements,
                                               key=lambda r: r.sort)]
        out["benefits"] = [_benefit_out(b) for b in version.benefits]
        out["expense_categories"] = [_expense_out(e)
                                     for e in version.expense_categories]
        out["document_requirements"] = [_doc_req_out(d)
                                        for d in version.document_requirements]
        out["source"] = _source_out(version.source) if version.source else None
        out["notes"] = version.notes
    return out


def _programme_out(programme: FundingProgramme, *, detail: bool = False) -> dict:
    versions = sorted(programme.versions, key=lambda v: v.version_no)
    current = versions[-1] if versions else None
    out = {
        "id": str(programme.id), "code": programme.code,
        "title": programme.title, "status": programme.status,
        "authority_id": (str(programme.authority_id)
                         if programme.authority_id else None),
        "authority_name": (programme.authority.name
                           if programme.authority else None),
        "geography": programme.geography, "description": programme.description,
        "tags": programme.tags,
        "current_version": (_version_out(current) if current else None),
        "version_count": len(versions),
    }
    if detail:
        out["versions"] = [_version_out(v, detail=True) for v in versions]
    return out


def _item_out(item: FundingAssessmentItem) -> dict:
    return {
        "id": str(item.id), "requirement_id": (str(item.requirement_id)
                                               if item.requirement_id else None),
        "rule_code": item.rule_code, "description": item.description,
        "mandatory": item.mandatory, "result": item.result,
        "evidence": item.evidence,
    }


def _assessment_out(assessment: FundingAssessment, *, detail: bool = False) -> dict:
    out = {
        "id": str(assessment.id), "company_id": str(assessment.company_id),
        "version_id": str(assessment.version_id),
        "assessed_at": _dt(assessment.assessed_at),
        "engine_version": assessment.engine_version,
        "result": assessment.result, "status": assessment.status,
        "missing_data": assessment.missing_data,
        "unsupported_rules": assessment.unsupported_rules,
        "reviewed_by_id": (str(assessment.reviewed_by_id)
                           if assessment.reviewed_by_id else None),
        "reviewed_at": _dt(assessment.reviewed_at),
        "reviewer_notes": assessment.reviewer_notes,
    }
    if detail:
        out["items"] = [_item_out(i) for i in assessment.items]
        out["company_snapshot"] = assessment.company_snapshot
    return out


# ---------------------------------------------------------------------------
# reference data: authorities, sources, programmes, versions
# ---------------------------------------------------------------------------

def list_authorities(db: Session, *, tenant_id) -> dict:
    rows = db.scalars(
        select(FundingAuthority).where(FundingAuthority.tenant_id == tenant_id)
        .order_by(FundingAuthority.name)).all()
    return {"authorities": [
        {"id": str(a.id), "code": a.code, "name": a.name, "level": a.level,
         "website": a.website} for a in rows]}


def list_programmes(db: Session, *, tenant_id,
                    status: str | None = None) -> dict:
    stmt = (select(FundingProgramme)
            .where(FundingProgramme.tenant_id == tenant_id)
            .order_by(FundingProgramme.title))
    if status:
        stmt = stmt.where(FundingProgramme.status == status)
    rows = db.scalars(stmt).all()
    return {"programmes": [_programme_out(p) for p in rows]}


def get_programme(db: Session, *, tenant_id, programme_id) -> dict:
    programme = _programme_or_404(db, programme_id, tenant_id)
    return _programme_out(programme, detail=True)


def create_programme(db: Session, *, tenant_id, actor_id, payload: dict) -> dict:
    """Manual/structured entry of a programme + first version.

    Idempotent on (code, version_no): re-importing the same notice updates
    nothing and returns the existing version.
    """
    code = payload["code"]
    programme = db.scalar(select(FundingProgramme).where(
        FundingProgramme.tenant_id == tenant_id,
        FundingProgramme.code == code))
    if programme is None:
        authority_id = payload.get("authority_id")
        if authority_id is None and payload.get("authority_code"):
            authority = db.scalar(select(FundingAuthority).where(
                FundingAuthority.tenant_id == tenant_id,
                FundingAuthority.code == payload["authority_code"]))
            authority_id = authority.id if authority else None
        programme = FundingProgramme(
            tenant_id=tenant_id, code=code, title=payload["title"],
            authority_id=authority_id,
            status=payload.get("status", ProgrammeStatus.DRAFT),
            geography=payload.get("geography"),
            description=payload.get("description"),
            tags=payload.get("tags", []))
        db.add(programme)
        db.flush()
    version_payload = payload.get("version") or {}
    version_no = int(version_payload.get("version_no", 1))
    existing = db.scalar(select(FundingProgrammeVersion).where(
        FundingProgrammeVersion.tenant_id == tenant_id,
        FundingProgrammeVersion.programme_id == programme.id,
        FundingProgrammeVersion.version_no == version_no))
    if existing is not None:
        return {"programme": _programme_out(programme),
                "version": _version_out(existing, detail=True),
                "created": False}
    version = _build_version(db, tenant_id=tenant_id, programme=programme,
                             payload=version_payload, version_no=version_no)
    if version_payload.get("status"):
        programme.status = version_payload["status"]
    db.flush()
    return {"programme": _programme_out(programme),
            "version": _version_out(version, detail=True),
            "created": True}


def _build_version(db: Session, *, tenant_id, programme: FundingProgramme,
                   payload: dict, version_no: int) -> FundingProgrammeVersion:
    source = None
    source_payload = payload.get("source")
    if source_payload:
        source = db.scalar(select(FundingSource).where(
            FundingSource.tenant_id == tenant_id,
            FundingSource.reference == source_payload["reference"]))
        if source is None:
            source = FundingSource(
                tenant_id=tenant_id,
                authority_id=programme.authority_id,
                provider=source_payload.get("provider", "manual"),
                title=source_payload["title"],
                reference=source_payload["reference"],
                url=source_payload.get("url"),
                published_on=source_payload.get("published_on"),
                retrieved_at=source_payload.get("retrieved_at") or utcnow(),
                notes=source_payload.get("notes"))
            db.add(source)
            db.flush()
    version = FundingProgrammeVersion(
        tenant_id=tenant_id, programme_id=programme.id,
        version_no=version_no,
        status=payload.get("status", ProgrammeStatus.DRAFT),
        publication_date=payload.get("publication_date"),
        effective_from=payload.get("effective_from"),
        effective_to=payload.get("effective_to"),
        source_id=source.id if source else None,
        source_title=payload.get("source_title") or (
            source.title if source else None),
        source_reference=payload.get("source_reference") or (
            source.reference if source else None),
        retrieved_at=payload.get("retrieved_at") or (
            source.retrieved_at if source else None),
        change_summary=payload.get("change_summary"),
        notes=payload.get("notes"),
        aid_regime_code=payload.get("aid_regime_code"))
    db.add(version)
    db.flush()
    for w in payload.get("windows", []):
        db.add(FundingWindow(
            tenant_id=tenant_id, version_id=version.id, kind=w["kind"],
            opens_at=w.get("opens_at"), closes_at=w.get("closes_at"),
            timezone=w.get("timezone"), notes=w.get("notes")))
    for i, r in enumerate(payload.get("requirements", []), start=1):
        db.add(FundingRequirement(
            tenant_id=tenant_id, version_id=version.id,
            rule_code=r["rule_code"], params=r.get("params", {}),
            description=r["description"],
            mandatory=r.get("mandatory", True), sort=r.get("sort", i)))
    for b in payload.get("benefits", []):
        db.add(FundingBenefit(
            tenant_id=tenant_id, version_id=version.id,
            benefit_type=b["benefit_type"],
            max_aid_intensity=b.get("max_amount") and b.get("max_aid_intensity"),
            max_amount=b.get("max_amount"),
            min_investment=b.get("min_investment"),
            max_investment=b.get("max_investment"),
            financing_share=b.get("financing_share"),
            repayment_term_months=b.get("repayment_term_months"),
            notes=b.get("notes")))
    for e in payload.get("expense_categories", []):
        db.add(FundingExpenseCategory(
            tenant_id=tenant_id, version_id=version.id,
            category_code=e["category_code"], label=e["label"],
            status=e["status"], conditions=e.get("conditions")))
    for d in payload.get("document_requirements", []):
        db.add(FundingDocumentRequirement(
            tenant_id=tenant_id, version_id=version.id,
            doc_type=d["doc_type"], label=d["label"],
            required=d.get("required", True), stage=d.get("stage"),
            notes=d.get("notes")))
    db.flush()
    return version


# ---------------------------------------------------------------------------
# aid regimes & company aid history
# ---------------------------------------------------------------------------

def list_aid_regimes(db: Session, *, tenant_id) -> dict:
    rows = db.scalars(
        select(AidRegime).where(AidRegime.tenant_id == tenant_id)
        .order_by(AidRegime.code, AidRegime.effective_from)).all()
    return {"regimes": [
        {"id": str(r.id), "code": r.code, "name": r.name,
         "authority": r.authority, "legal_reference": r.legal_reference,
         "effective_from": _d(r.effective_from),
         "effective_to": _d(r.effective_to),
         "threshold": _dec(r.threshold), "period_months": r.period_months,
         "rolling": r.rolling, "sector_exclusions": r.sector_exclusions,
         "formula_version": r.formula_version} for r in rows]}


def regime_in_force(db: Session, *, tenant_id, code: str,
                    on: date | None = None) -> AidRegime | None:
    """The version of `code` effective on `on` (default today)."""
    on = on or today()
    return db.scalar(
        select(AidRegime).where(
            AidRegime.tenant_id == tenant_id, AidRegime.code == code,
            AidRegime.effective_from <= on,
            (AidRegime.effective_to.is_(None))
            | (AidRegime.effective_to >= on))
        .order_by(AidRegime.effective_from.desc()).limit(1))


def upsert_profile(db: Session, *, tenant_id, company: Company,
                   payload: dict) -> dict:
    profile = db.scalar(select(FundingCompanyProfile).where(
        FundingCompanyProfile.tenant_id == tenant_id,
        FundingCompanyProfile.company_id == company.id))
    if profile is None:
        profile = FundingCompanyProfile(tenant_id=tenant_id,
                                        company_id=company.id)
        db.add(profile)
    for key, value in payload.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    db.flush()
    return _profile_out(profile)


def _profile_out(profile: FundingCompanyProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "id": str(profile.id), "company_id": str(profile.company_id),
        "incorporated_on": _d(profile.incorporated_on),
        "is_startup": profile.is_startup,
        "is_innovative_startup": profile.is_innovative_startup,
        "female_ownership_pct": _dec(profile.female_ownership_pct),
        "youth_ownership_pct": _dec(profile.youth_ownership_pct),
        "project_region": profile.project_region,
        "project_location": profile.project_location,
        "single_undertaking_known": profile.single_undertaking_known,
        "group_notes": profile.group_notes,
        "aid_history_complete": profile.aid_history_complete,
        "notes": profile.notes,
    }


def get_profile(db: Session, *, tenant_id, company_id) -> FundingCompanyProfile | None:
    return db.scalar(select(FundingCompanyProfile).where(
        FundingCompanyProfile.tenant_id == tenant_id,
        FundingCompanyProfile.company_id == company_id))


def add_company_aid(db: Session, *, tenant_id, company: Company,
                    payload: dict) -> dict:
    aid = CompanyAid(
        tenant_id=tenant_id, company_id=company.id,
        programme_label=payload["programme_label"],
        authority=payload.get("authority"),
        regime_code=payload.get("regime_code"),
        granted_on=payload["granted_on"], amount=payload["amount"],
        gge_amount=payload.get("gge_amount"),
        reference=payload.get("reference"), source=payload.get("source"),
        status=payload.get("status", "declared"))
    db.add(aid)
    db.flush()
    return {"id": str(aid.id), "programme_label": aid.programme_label,
            "granted_on": _d(aid.granted_on), "amount": _dec(aid.amount),
            "regime_code": aid.regime_code, "status": aid.status}


def list_company_aids(db: Session, *, tenant_id, company_id) -> dict:
    rows = db.scalars(
        select(CompanyAid).where(CompanyAid.tenant_id == tenant_id,
                                 CompanyAid.company_id == company_id)
        .order_by(CompanyAid.granted_on.desc())).all()
    return {"aids": [
        {"id": str(a.id), "programme_label": a.programme_label,
         "authority": a.authority, "regime_code": a.regime_code,
         "granted_on": _d(a.granted_on), "amount": _dec(a.amount),
         "gge_amount": _dec(a.gge_amount), "reference": a.reference,
         "source": a.source, "status": a.status} for a in rows]}


def _window_start(on: date, months: int) -> date:
    """Rolling window start: `months` back from `on` (approximate by years)."""
    years = months // 12
    try:
        return on.replace(year=on.year - years)
    except ValueError:  # 29 Feb
        return on.replace(year=on.year - years, day=28)


def de_minimis_position(db: Session, *, tenant_id, company: Company,
                        regime_code: str = "DE_MINIMIS") -> dict:
    """Headroom under the de minimis regime in force today.

    Only declared aids count. If the profile does not declare the aid
    history complete or the single-undertaking perimeter is unknown, the
    position is reported as partial — never as compliant.
    """
    regime = regime_in_force(db, tenant_id=tenant_id, code=regime_code)
    profile = get_profile(db, tenant_id=tenant_id, company_id=company.id)
    if regime is None:
        return {"status": "insufficient_data",
                "reason": f"Regime {regime_code} non censito.",
                "regime": None}
    window_start = _window_start(today(), regime.period_months)
    total = db.scalar(
        select(func.coalesce(func.sum(
            func.coalesce(CompanyAid.gge_amount, CompanyAid.amount)), 0))
        .where(CompanyAid.tenant_id == tenant_id,
               CompanyAid.company_id == company.id,
               CompanyAid.regime_code == regime_code,
               CompanyAid.granted_on >= window_start))
    total = Decimal(str(total))
    headroom = regime.threshold - total
    status = "available"
    reasons = []
    if profile is None or profile.aid_history_complete is not True:
        status = "insufficient_data"
        reasons.append("Storico aiuti non dichiarato completo.")
    if profile is None or profile.single_undertaking_known is not True:
        if status == "available":
            status = "review_required"
        reasons.append("Perimetro di impresa unica non verificato.")
    return {
        "status": status, "reasons": reasons,
        "regime": {"code": regime.code, "legal_reference": regime.legal_reference,
                   "threshold": _dec(regime.threshold),
                   "period_months": regime.period_months,
                   "effective_from": _d(regime.effective_from),
                   "formula_version": regime.formula_version},
        "window_start": window_start.isoformat(),
        "aid_total": str(total), "headroom": str(headroom),
    }


# ---------------------------------------------------------------------------
# company facts + assessment
# ---------------------------------------------------------------------------

def build_company_facts(db: Session, *, tenant_id,
                        company: Company) -> rules.CompanyFacts:
    """Assemble the canonical fact set the rules read.

    Company supplies registry facts; FundingCompanyProfile supplies the
    funding-specific declared attributes. Missing = None = INSUFFICIENT_DATA.
    """
    profile = get_profile(db, tenant_id=tenant_id, company_id=company.id)
    regime = regime_in_force(db, tenant_id=tenant_id, code="DE_MINIMIS")
    aid_total = None
    window_months = None
    if regime is not None:
        window_start = _window_start(today(), regime.period_months)
        raw = db.scalar(
            select(func.coalesce(func.sum(
                func.coalesce(CompanyAid.gge_amount, CompanyAid.amount)), 0))
            .where(CompanyAid.tenant_id == tenant_id,
                   CompanyAid.company_id == company.id,
                   CompanyAid.regime_code == "DE_MINIMIS",
                   CompanyAid.granted_on >= window_start))
        aid_total = Decimal(str(raw))
        window_months = regime.period_months
    return rules.CompanyFacts(
        legal_form=company.legal_form,
        ateco_code=company.ateco_code,
        region=company.region,
        size_band=company.size_band,
        employee_count=company.employee_count,
        revenue_eur=(Decimal(str(company.revenue_eur))
                     if company.revenue_eur is not None else None),
        incorporated_on=profile.incorporated_on if profile else None,
        is_startup=profile.is_startup if profile else None,
        is_innovative_startup=(profile.is_innovative_startup
                               if profile else None),
        female_ownership_pct=(profile.female_ownership_pct
                              if profile else None),
        youth_ownership_pct=(profile.youth_ownership_pct
                             if profile else None),
        project_region=profile.project_region if profile else None,
        project_location=profile.project_location if profile else None,
        single_undertaking_known=(profile.single_undertaking_known
                                  if profile else None),
        aid_history_complete=(profile.aid_history_complete
                              if profile else None),
        aid_total_eur=aid_total,
        aid_window_months=window_months,
        aid_threshold_eur=(regime.threshold if regime else None),
    )


def _facts_snapshot(facts: rules.CompanyFacts) -> dict:
    return {k: (v.isoformat() if isinstance(v, (date, datetime))
                else str(v) if isinstance(v, Decimal) else v)
            for k, v in vars(facts).items()}


def run_assessment(db: Session, *, tenant_id, company: Company,
                   version_id: uuid.UUID, actor_id) -> dict:
    """Evaluate every structured requirement of a programme version and
    persist the assessment + per-rule items. Reproducible by construction."""
    version = _version_or_404(db, version_id, tenant_id)
    facts = build_company_facts(db, tenant_id=tenant_id, company=company)
    requirements = sorted(version.requirements, key=lambda r: r.sort)
    if not requirements:
        raise ValidationError(
            "La versione non ha requisiti strutturati: la valutazione "
            "deterministica non è possibile.",
            code="funding_no_rules")
    outcomes, missing, unsupported = [], [], []
    items = []
    for req in requirements:
        outcome = rules.evaluate(req.rule_code, req.params, facts)
        outcomes.append(outcome)
        if outcome.result == RuleResult.INSUFFICIENT_DATA:
            missing.append({"rule_code": req.rule_code,
                            "description": req.description,
                            "missing": outcome.evidence.get("missing")})
        if outcome.result == RuleResult.UNSUPPORTED:
            unsupported.append(req.rule_code)
        items.append((req, outcome))
    result = rules.overall_result(outcomes, [r.mandatory for r in requirements])
    status = (AssessmentStatus.REVIEW_REQUIRED
              if result in (AssessmentResult.REVIEW_REQUIRED,
                            AssessmentResult.POTENTIALLY_ELIGIBLE,
                            AssessmentResult.INSUFFICIENT_DATA)
              else AssessmentStatus.CALCULATED)
    assessment = FundingAssessment(
        tenant_id=tenant_id, company_id=company.id, version_id=version.id,
        assessed_at=utcnow(), engine_version=rules.ENGINE_VERSION,
        result=result, status=status,
        company_snapshot=_facts_snapshot(facts),
        missing_data=missing, unsupported_rules=unsupported,
        created_by_id=actor_id)
    db.add(assessment)
    db.flush()
    for req, outcome in items:
        db.add(FundingAssessmentItem(
            tenant_id=tenant_id, assessment_id=assessment.id,
            requirement_id=req.id, rule_code=req.rule_code,
            description=req.description, mandatory=req.mandatory,
            result=outcome.result, evidence=outcome.evidence))
    db.flush()
    return _assessment_out(assessment, detail=True)


def list_assessments(db: Session, *, tenant_id,
                     company_id=None, version_id=None) -> dict:
    stmt = (select(FundingAssessment)
            .where(FundingAssessment.tenant_id == tenant_id)
            .order_by(FundingAssessment.assessed_at.desc()))
    if company_id:
        stmt = stmt.where(FundingAssessment.company_id == company_id)
    if version_id:
        stmt = stmt.where(FundingAssessment.version_id == version_id)
    rows = db.scalars(stmt).all()
    return {"assessments": [_assessment_out(a) for a in rows]}


def get_assessment(db: Session, *, tenant_id, assessment_id) -> dict:
    assessment = _assessment_or_404(db, assessment_id, tenant_id)
    out = _assessment_out(assessment, detail=True)
    out["programme_version"] = _version_out(assessment.version, detail=False) \
        if assessment.version else None
    return out


def review_assessment(db: Session, *, tenant_id, assessment_id, actor_id,
                      action: str, notes: str | None) -> dict:
    """Human review lifecycle. `action` ∈ review_required | reviewed |
    approved_for_practice | rejected."""
    assessment = _assessment_or_404(db, assessment_id, tenant_id)
    target = {
        "review_required": AssessmentStatus.REVIEW_REQUIRED,
        "reviewed": AssessmentStatus.REVIEWED,
        "approved_for_practice": AssessmentStatus.APPROVED_FOR_PRACTICE,
        "rejected": AssessmentStatus.REJECTED,
    }.get(action)
    if target is None:
        raise ValidationError("Azione di review non valida.",
                              code="funding_review_action")
    allowed = ASSESSMENT_TRANSITIONS.get(assessment.status, set())
    if target not in allowed:
        raise ConflictError(
            f"Transizione {assessment.status} → {target} non consentita.",
            code="funding_review_transition")
    if action in ("reviewed", "approved_for_practice", "rejected"):
        assessment.reviewed_by_id = actor_id
        assessment.reviewed_at = utcnow()
        assessment.reviewer_notes = notes
    assessment.status = target
    db.flush()
    return _assessment_out(assessment, detail=True)


# ---------------------------------------------------------------------------
# matching / opportunities
# ---------------------------------------------------------------------------

def match_company(db: Session, *, tenant_id, company: Company) -> dict:
    """Deterministic pre-screening across active programme versions.

    Only versions with structured requirements participate. Results are
    grouped by outcome — never a match percentage.
    """
    versions = db.scalars(
        select(FundingProgrammeVersion)
        .join(FundingProgramme,
              FundingProgramme.id == FundingProgrammeVersion.programme_id)
        .where(FundingProgrammeVersion.tenant_id == tenant_id,
               FundingProgrammeVersion.status.in_(
                   [ProgrammeStatus.OPEN, ProgrammeStatus.UPCOMING]))
        .order_by(FundingProgrammeVersion.programme_id,
                  FundingProgrammeVersion.version_no.desc())).all()
    latest: dict[uuid.UUID, FundingProgrammeVersion] = {}
    for v in versions:
        latest.setdefault(v.programme_id, v)
    facts = build_company_facts(db, tenant_id=tenant_id, company=company)
    groups: dict[str, list] = {k: [] for k in (
        "eligible_on_known_data", "potentially_eligible", "review_required",
        "insufficient_data", "not_eligible", "unsupported")}
    for version in latest.values():
        requirements = sorted(version.requirements, key=lambda r: r.sort)
        if not requirements:
            continue
        outcomes = [rules.evaluate(r.rule_code, r.params, facts)
                    for r in requirements]
        result = rules.overall_result(
            outcomes, [r.mandatory for r in requirements])
        groups[result].append({
            "version_id": str(version.id),
            "programme_id": str(version.programme_id),
            "programme_title": version.programme.title,
            "version_no": version.version_no,
            "status": version.status,
            "results": [{"rule_code": r.rule_code, "result": o.result,
                         "description": r.description}
                        for r, o in zip(requirements, outcomes, strict=True)],
        })
    return {"company_id": str(company.id), "groups": groups,
            "engine_version": rules.ENGINE_VERSION}
