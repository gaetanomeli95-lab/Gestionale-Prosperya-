"""Funding signals for cockpit/hub + the company funding view.

Read-only deterministic composition — the same signal contract used by
management/treasury/fiscal/controlling: code, severity, title, message,
formula, formula_version, evidence, action_required.
"""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.funding import rules, service
from app.modules.funding.models import (
    FundingPractice,
    FundingProgrammeVersion,
    PracticeDeadlineStatus,
    PracticeDocStatus,
    PracticeStatus,
)
from app.modules.funding.practices import list_deadlines, list_practices
from app.shared.mixins import today as utc_today


def _days_label(days: int) -> str:
    return f"tra {days} giorni" if days >= 0 else f"da {-days} giorni"


def company_funding(db: Session, *, tenant_id, company: Company) -> dict:
    """The funding section of Company detail: profile, aids, assessments,
    practices, deadlines, de minimis position."""
    profile = service.get_profile(db, tenant_id=tenant_id,
                                  company_id=company.id)
    return {
        "company_id": str(company.id),
        "profile": service._profile_out(profile),
        "aids": service.list_company_aids(
            db, tenant_id=tenant_id, company_id=company.id)["aids"],
        "assessments": service.list_assessments(
            db, tenant_id=tenant_id, company_id=company.id)["assessments"],
        "practices": list_practices(
            db, tenant_id=tenant_id, company_id=company.id)["practices"],
        "deadlines": list_deadlines(
            db, tenant_id=tenant_id, company_id=company.id)["deadlines"],
        "de_minimis": service.de_minimis_position(
            db, tenant_id=tenant_id, company=company),
        "limitations": service.LIMITATIONS,
    }


def funding_signals(db: Session, *, tenant_id, company: Company,
                    as_of: date | None = None) -> list[dict]:
    """Deterministic signals — read-only, never a write.

    Codes: funding_opportunity, funding_missing_data,
    funding_window_closing, funding_docs_missing,
    funding_deadline_imminent.
    """
    as_of = as_of or utc_today()
    signals: list[dict] = []
    # Funding signals track declared funding work: without a profile, an
    # assessment or a practice the company is outside the funding perimeter
    # and speculative matching must not produce warnings.
    profile = service.get_profile(db, tenant_id=tenant_id,
                                  company_id=company.id)
    has_context = (
        profile is not None
        or service.list_assessments(db, tenant_id=tenant_id,
                                    company_id=company.id)["assessments"]
        or list_practices(db, tenant_id=tenant_id,
                          company_id=company.id)["practices"])
    if not has_context:
        return signals
    match = service.match_company(db, tenant_id=tenant_id, company=company)
    groups = match["groups"]
    eligible = groups["eligible_on_known_data"]
    potential = groups["potentially_eligible"]
    review = groups["review_required"]
    if eligible:
        signals.append({
            "code": "funding_opportunity", "severity": "info",
            "category": "funding",
            "title": "Agevolazioni compatibili sui dati noti",
            "message": (f"{len(eligible)} programmi risultano compatibili; "
                        f"il primo è \"{eligible[0]['programme_title']}\"."),
            "formula": "assessment deterministico eligible_on_known_data",
            "formula_version": rules.ENGINE_VERSION,
            "evidence": {"count": len(eligible),
                         "items": [{"version_id": e["version_id"],
                                    "title": e["programme_title"]}
                                   for e in eligible[:5]]},
            "action_required": False})
    if potential or review:
        count = len(potential) + len(review)
        signals.append({
            "code": "funding_missing_data", "severity": "warning",
            "category": "funding",
            "title": "Agevolazioni con dati mancanti o da verificare",
            "message": (f"{count} programmi richiedono dati aggiuntivi o "
                        f"revisione professionale prima di concludere "
                        f"l'eligibilità."),
            "formula": "esito potentially_eligible o review_required",
            "formula_version": rules.ENGINE_VERSION,
            "evidence": {"potentially_eligible": len(potential),
                         "review_required": len(review)},
            "action_required": True})
    # windows closing within 30 days on matched programmes
    seen_windows: set[str] = set()
    for group_name in ("eligible_on_known_data", "potentially_eligible",
                       "review_required"):
        for entry in groups[group_name]:
            version = db.get(FundingProgrammeVersion,
                             uuid.UUID(entry["version_id"]))
            if version is None:
                continue
            for window in version.windows:
                if window.closes_at is None:
                    continue
                key = f"{version.id}:{window.closes_at.isoformat()}"
                if key in seen_windows:
                    continue
                seen_windows.add(key)
                days = (window.closes_at.date() - as_of).days
                if 0 <= days <= 30:
                    signals.append({
                        "code": "funding_window_closing",
                        "severity": "warning" if days > 7 else "critical",
                        "category": "funding",
                        "title": "Finestra bando in chiusura",
                        "message": (f"\"{entry['programme_title']}\" chiude "
                                    f"tra {days} giorni "
                                    f"({window.closes_at.date().isoformat()})."),
                        "formula": "window.closes_at - today <= 30 giorni",
                        "formula_version": rules.ENGINE_VERSION,
                        "evidence": {"version_id": entry["version_id"],
                                     "closes_at": window.closes_at.isoformat(),
                                     "days_left": days},
                        "action_required": True})
    # open practices: missing required docs / imminent deadlines
    practices = db.scalars(
        select(FundingPractice).where(
            FundingPractice.tenant_id == tenant_id,
            FundingPractice.company_id == company.id,
            FundingPractice.status.notin_([
                PracticeStatus.APPROVED, PracticeStatus.REJECTED,
                PracticeStatus.WITHDRAWN, PracticeStatus.CLOSED]))).all()
    for practice in practices:
        missing_docs = [d for d in practice.documents
                        if d.required and d.status in (
                            PracticeDocStatus.MISSING,
                            PracticeDocStatus.REQUESTED,
                            PracticeDocStatus.REJECTED)]
        if missing_docs:
            signals.append({
                "code": "funding_docs_missing", "severity": "warning",
                "category": "funding",
                "title": "Pratica con documenti mancanti",
                "message": (f"La pratica su \"{practice.version.programme.title}\" "
                            f"ha {len(missing_docs)} documenti obbligatori "
                            f"non acquisiti."),
                "formula": "documenti required con stato missing/requested/"
                           "rejected",
                "formula_version": rules.ENGINE_VERSION,
                "evidence": {"practice_id": str(practice.id),
                             "missing": [d.doc_type for d in missing_docs[:10]]},
                "action_required": True})
        for dl in practice.deadlines:
            if dl.status != PracticeDeadlineStatus.OPEN:
                continue
            days = (dl.due_at.date() - as_of).days
            if days <= 14:
                signals.append({
                    "code": "funding_deadline_imminent",
                    "severity": "critical" if days <= 3 else "warning",
                    "category": "funding",
                    "title": "Scadenza pratica imminente",
                    "message": (f"\"{dl.title}\" scade "
                                f"{_days_label(days)} "
                                f"({dl.due_at.date().isoformat()})."),
                    "formula": "deadline.due_at - today <= 14 giorni",
                    "formula_version": rules.ENGINE_VERSION,
                    "evidence": {"practice_id": str(practice.id),
                                 "deadline_id": str(dl.id),
                                 "due_at": dl.due_at.isoformat(),
                                 "days_left": days},
                    "action_required": True})
    return signals
