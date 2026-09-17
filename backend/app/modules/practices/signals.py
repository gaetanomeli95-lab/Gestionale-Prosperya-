"""Operational signals for the cockpit/hub — deterministic, explainable.

Codes: ops_document_missing, ops_deadline_approaching,
ops_client_request_overdue, ops_document_expiring, ops_practice_blocked.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.documents.models import (
    Document,
    DocumentRequirement,
    DocumentVersion,
    RequirementStatus,
)
from app.modules.practices import service as practice_service
from app.modules.practices.models import (
    BlockerStatus,
    ClientRequest,
    ClientRequestStatus,
    Practice,
    PracticeBlocker,
    PracticeStatus,
)
from app.shared.mixins import today as utc_today
from app.shared.mixins import utcnow

ENGINE_VERSION = "ops-signals-v1.0"

_OPEN_PRACTICE_STATUSES = {
    PracticeStatus.DRAFT, PracticeStatus.OPEN, PracticeStatus.WAITING_CLIENT,
    PracticeStatus.WAITING_EXTERNAL, PracticeStatus.READY,
    PracticeStatus.IN_PROGRESS,
}
_UNSATISFIED = {RequirementStatus.MISSING, RequirementStatus.REQUESTED,
                RequirementStatus.REJECTED}


def operations_signals(db: Session, *, tenant_id, company: Company,
                       as_of: date | None = None) -> list[dict]:
    """Deterministic operational signals — read-only, never a write."""
    as_of = as_of or utc_today()
    now = utcnow()
    practice_service.refresh_overdue_requests(db, tenant_id=tenant_id, now=now)

    signals: list[dict] = []

    practices = db.scalars(
        select(Practice).where(
            Practice.tenant_id == tenant_id,
            Practice.company_id == company.id,
            Practice.deleted_at.is_(None),
            Practice.status.in_(_OPEN_PRACTICE_STATUSES))).all()
    if not practices:
        return signals
    practice_ids = [p.id for p in practices]
    by_id = {p.id: p for p in practices}

    # --- Missing mandatory documents -------------------------------------
    reqs = db.scalars(
        select(DocumentRequirement).where(
            DocumentRequirement.tenant_id == tenant_id,
            DocumentRequirement.practice_id.in_(practice_ids),
            DocumentRequirement.mandatory.is_(True),
            DocumentRequirement.status.in_(_UNSATISFIED))).all()
    for req in reqs:
        p = by_id.get(req.practice_id)
        days = ((req.due_at.date() - as_of).days
                if req.due_at is not None else None)
        critical = days is not None and days <= 7
        signals.append({
            "code": "ops_document_missing",
            "severity": "critical" if critical else "warning",
            "category": "operations",
            "title": "Documento obbligatorio mancante",
            "message": (f"\"{req.label}\" manca per la pratica "
                        f"\"{p.title if p else req.practice_id}\""
                        + (f" (scadenza tra {days} giorni)."
                           if days is not None else ".")),
            "formula": "requirement.mandatory AND status IN "
                       "(missing|requested|rejected)",
            "formula_version": ENGINE_VERSION,
            "evidence": {"requirement_id": str(req.id),
                         "practice_id": str(req.practice_id),
                         "days_to_due": days},
            "action_required": True})

    # --- Approaching practice deadlines ----------------------------------
    for p in practices:
        if p.target_date is None:
            continue
        days = (p.target_date.date() - as_of).days
        if days <= 14:
            signals.append({
                "code": "ops_deadline_approaching",
                "severity": "critical" if days <= 3 else "warning",
                "category": "operations",
                "title": "Scadenza pratica in avvicinamento",
                "message": (f"\"{p.title}\" ha data obiettivo "
                            f"{p.target_date.date().isoformat()} "
                            f"({days} giorni)."),
                "formula": "practice.target_date - today <= 14 giorni",
                "formula_version": ENGINE_VERSION,
                "evidence": {"practice_id": str(p.id),
                             "target_date": p.target_date.isoformat(),
                             "days_left": days},
                "action_required": True})

    # --- Overdue client requests ------------------------------------------
    overdue = db.scalars(
        select(ClientRequest).where(
            ClientRequest.tenant_id == tenant_id,
            ClientRequest.company_id == company.id,
            ClientRequest.deleted_at.is_(None),
            ClientRequest.status == ClientRequestStatus.OVERDUE)).all()
    for r in overdue:
        signals.append({
            "code": "ops_client_request_overdue",
            "severity": "warning",
            "category": "operations",
            "title": "Richiesta al cliente scaduta",
            "message": (f"\"{r.item}\" richiesta il "
                        f"{r.requested_at.date().isoformat() if r.requested_at else 'n.d.'}"
                        f", scaduta il {r.due_at.date().isoformat()}."),
            "formula": "client_request.due_at < now AND status = overdue",
            "formula_version": ENGINE_VERSION,
            "evidence": {"request_id": str(r.id),
                         "practice_id": str(r.practice_id)
                         if r.practice_id else None},
            "action_required": True})

    # --- Expiring documents ------------------------------------------------
    docs = db.scalars(
        select(Document)
        .join(DocumentVersion,
              Document.current_version_id == DocumentVersion.id)
        .where(Document.tenant_id == tenant_id,
               Document.company_id == company.id,
               Document.deleted_at.is_(None),
               DocumentVersion.expires_on.is_not(None))).all()
    for doc in docs:
        days = (doc.current_version.expires_on - as_of).days
        if days <= 30:
            signals.append({
                "code": "ops_document_expiring",
                "severity": "critical" if days < 0 else "warning",
                "category": "operations",
                "title": ("Documento scaduto" if days < 0
                          else "Documento in scadenza"),
                "message": (f"\"{doc.title}\" "
                            + (f"è scaduto da {-days} giorni."
                               if days < 0 else
                               f"scade tra {days} giorni "
                               f"({doc.current_version.expires_on.isoformat()}).")),
                "formula": "current_version.expires_on - today <= 30 giorni",
                "formula_version": ENGINE_VERSION,
                "evidence": {"document_id": str(doc.id),
                             "expires_on":
                                 doc.current_version.expires_on.isoformat(),
                             "days_left": days},
                "action_required": days < 0})

    # --- Blocked practices --------------------------------------------------
    blocked = db.scalars(
        select(PracticeBlocker.practice_id)
        .where(PracticeBlocker.tenant_id == tenant_id,
               PracticeBlocker.practice_id.in_(practice_ids),
               PracticeBlocker.status == BlockerStatus.OPEN)
        .group_by(PracticeBlocker.practice_id)).all()
    for pid in blocked:
        p = by_id.get(pid)
        if p is None:
            continue
        signals.append({
            "code": "ops_practice_blocked",
            "severity": "warning",
            "category": "operations",
            "title": "Pratica bloccata",
            "message": f"\"{p.title}\" ha blocchi operativi aperti.",
            "formula": "count(open blockers) > 0",
            "formula_version": ENGINE_VERSION,
            "evidence": {"practice_id": str(p.id)},
            "action_required": True})

    return signals
