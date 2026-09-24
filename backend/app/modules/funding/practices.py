"""Funding practices — managed lifecycle of an application to a measure.

A practice is opened from an approved assessment (or directly by a
professional), materialises the document checklist from the version's
requirements, and carries operational deadlines linked to first-class
Tasks. Transitions are explicit — never a free status field.
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.companies.models import Company
from app.modules.documents.models import (
    DocumentRequirement,
    RequirementStatus,
)
from app.modules.funding.models import (
    AssessmentStatus,
    FundingAssessment,
    FundingPractice,
    FundingPracticeActivity,
    FundingPracticeDeadline,
    FundingPracticeDocument,
    FundingProgrammeVersion,
    PracticeDeadlineStatus,
    PracticeDocStatus,
    PracticeStatus,
)
from app.modules.tasks.models import Task, TaskPriority, TaskStatus
from app.shared.mixins import utcnow

#: Allowed practice transitions — a managed lifecycle, not a free field.
PRACTICE_TRANSITIONS: dict[str, set[str]] = {
    PracticeStatus.DRAFT: {PracticeStatus.DATA_COLLECTION,
                           PracticeStatus.WITHDRAWN},
    PracticeStatus.DATA_COLLECTION: {PracticeStatus.DOCUMENT_COLLECTION,
                                     PracticeStatus.WITHDRAWN},
    PracticeStatus.DOCUMENT_COLLECTION: {PracticeStatus.READY_TO_SUBMIT,
                                         PracticeStatus.DATA_COLLECTION,
                                         PracticeStatus.WITHDRAWN},
    PracticeStatus.READY_TO_SUBMIT: {PracticeStatus.SUBMITTED,
                                     PracticeStatus.DOCUMENT_COLLECTION,
                                     PracticeStatus.WITHDRAWN},
    PracticeStatus.SUBMITTED: {PracticeStatus.UNDER_REVIEW,
                               PracticeStatus.WITHDRAWN},
    PracticeStatus.UNDER_REVIEW: {PracticeStatus.INTEGRATION_REQUESTED,
                                  PracticeStatus.APPROVED,
                                  PracticeStatus.REJECTED},
    PracticeStatus.INTEGRATION_REQUESTED: {PracticeStatus.UNDER_REVIEW,
                                           PracticeStatus.REJECTED,
                                           PracticeStatus.WITHDRAWN},
    PracticeStatus.APPROVED: {PracticeStatus.CLOSED},
    PracticeStatus.REJECTED: {PracticeStatus.CLOSED},
    PracticeStatus.WITHDRAWN: {PracticeStatus.CLOSED},
    PracticeStatus.CLOSED: set(),
}


def _practice_or_404(db: Session, practice_id: uuid.UUID, tenant_id) -> FundingPractice:
    practice = db.get(FundingPractice, practice_id)
    if practice is None or practice.tenant_id != tenant_id:
        raise NotFoundError("Pratica non trovata.")
    return practice


def _version_or_404(db: Session, version_id: uuid.UUID, tenant_id) -> FundingProgrammeVersion:
    version = db.get(FundingProgrammeVersion, version_id)
    if version is None or version.tenant_id != tenant_id:
        raise NotFoundError("Versione del programma non trovata.")
    return version


def _d(value) -> str | None:
    return value.isoformat() if value is not None else None


def _practice_doc_out(doc: FundingPracticeDocument) -> dict:
    return {
        "id": str(doc.id), "doc_type": doc.doc_type, "label": doc.label,
        "required": doc.required, "status": doc.status,
        "due_date": _d(doc.due_date), "document_ref": doc.document_ref,
        "notes": doc.notes,
    }


def _practice_deadline_out(dl: FundingPracticeDeadline) -> dict:
    return {
        "id": str(dl.id), "practice_id": str(dl.practice_id),
        "kind": dl.kind, "title": dl.title, "due_at": _d(dl.due_at),
        "status": dl.status, "task_id": str(dl.task_id) if dl.task_id else None,
        "notes": dl.notes,
    }


def _practice_out(practice: FundingPractice, *, detail: bool = False) -> dict:
    out = {
        "id": str(practice.id), "company_id": str(practice.company_id),
        "version_id": str(practice.version_id),
        "assessment_id": (str(practice.assessment_id)
                          if practice.assessment_id else None),
        "owner_id": str(practice.owner_id) if practice.owner_id else None,
        "status": practice.status, "notes": practice.notes,
        # Generic operational Practice this funding record is linked to (ADR-023).
        "practice_id": str(practice.practice_id) if practice.practice_id else None,
        "created_at": _d(practice.created_at),
    }
    if detail:
        out["documents"] = [_practice_doc_out(d) for d in practice.documents]
        out["deadlines"] = [_practice_deadline_out(d) for d in practice.deadlines]
        out["activities"] = [
            {"id": str(a.id), "kind": a.kind, "note": a.note,
             "actor_id": str(a.actor_id) if a.actor_id else None,
             "created_at": _d(a.created_at)}
            for a in practice.activities
        ]
    return out


def create_practice(db: Session, *, tenant_id, company: Company,
                    version_id: uuid.UUID, actor_id,
                    assessment_id: uuid.UUID | None = None,
                    owner_id: uuid.UUID | None = None,
                    notes: str | None = None) -> dict:
    """Open a managed practice from an assessment (or directly).

    When an assessment is linked it must belong to the same company/version
    and be approved_for_practice — a practice is a professional decision.
    The document checklist is materialised from the version requirements.
    """
    version = _version_or_404(db, version_id, tenant_id)
    if assessment_id is not None:
        assessment = db.get(FundingAssessment, assessment_id)
        if assessment is None or assessment.tenant_id != tenant_id:
            raise NotFoundError("Valutazione non trovata.")
        if assessment.company_id != company.id or assessment.version_id != version.id:
            raise ValidationError(
                "La valutazione non appartiene a questa azienda/versione.",
                code="funding_assessment_mismatch")
        if assessment.status != AssessmentStatus.APPROVED_FOR_PRACTICE:
            raise ConflictError(
                "La valutazione deve essere approvata per la pratica.",
                code="funding_assessment_not_approved")
    practice = FundingPractice(
        tenant_id=tenant_id, company_id=company.id, version_id=version.id,
        assessment_id=assessment_id, owner_id=owner_id or actor_id,
        status=PracticeStatus.DRAFT, notes=notes, created_by_id=actor_id)
    db.add(practice)
    db.flush()
    # Generic operational container — the dossier/hub read this layer.
    from app.modules.practices import service as practice_service
    generic = practice_service.create_practice(
        db, tenant_id=tenant_id, company_id=company.id, actor_id=actor_id,
        title=f"Finanza agevolata — {version.programme.title}",
        practice_type="funding", owner_id=practice.owner_id,
        source_module="funding", external_ref=str(practice.id),
        status="draft", notes=notes)
    practice.practice_id = generic.id
    for req in version.document_requirements:
        fdoc = FundingPracticeDocument(
            tenant_id=tenant_id, practice_id=practice.id,
            doc_type=req.doc_type, label=req.label, required=req.required,
            status=PracticeDocStatus.MISSING, notes=req.notes)
        db.add(fdoc)
        db.flush()
        db.add(DocumentRequirement(
            tenant_id=tenant_id, company_id=company.id,
            practice_id=generic.id, module="funding",
            doc_type_code=req.doc_type, label=req.label,
            mandatory=req.required, requires_validation=True,
            status=RequirementStatus.MISSING,
            source_ref=str(fdoc.id), notes=req.notes))
    practice_service.sync_document_blockers(
        db, tenant_id=tenant_id, practice_id=generic.id, actor_id=actor_id)
    for window in version.windows:
        if window.closes_at is not None:
            _add_deadline(db, tenant_id=tenant_id, practice=practice,
                          kind="application_close",
                          title=f"Chiusura bando — {version.programme.title}",
                          due_at=window.closes_at, actor_id=actor_id)
    db.add(FundingPracticeActivity(
        tenant_id=tenant_id, practice_id=practice.id, actor_id=actor_id,
        kind="created", note="Pratica creata."))
    db.flush()
    return _practice_out(practice, detail=True)


def _add_deadline(db: Session, *, tenant_id, practice: FundingPractice,
                  kind: str, title: str, due_at: datetime,
                  actor_id, notes: str | None = None) -> FundingPracticeDeadline:
    """Practice deadline + linked operational Task (existing architecture)."""
    task = Task(tenant_id=tenant_id, title=title,
                description=f"Pratica finanza agevolata — scadenza {kind}.",
                status=TaskStatus.TODO, priority=TaskPriority.HIGH,
                owner_id=practice.owner_id, created_by_id=actor_id,
                due_date=due_at,
                entity_type="funding_practice", entity_id=practice.id)
    db.add(task)
    db.flush()
    deadline = FundingPracticeDeadline(
        tenant_id=tenant_id, practice_id=practice.id, kind=kind, title=title,
        due_at=due_at, status=PracticeDeadlineStatus.OPEN, task_id=task.id,
        notes=notes)
    db.add(deadline)
    db.flush()
    return deadline


def transition_practice(db: Session, *, tenant_id, practice_id, actor_id,
                        action: str, note: str | None = None) -> dict:
    practice = _practice_or_404(db, practice_id, tenant_id)
    allowed = PRACTICE_TRANSITIONS.get(practice.status, set())
    if action not in allowed:
        raise ConflictError(
            f"Transizione {practice.status} → {action} non consentita.",
            code="funding_practice_transition")
    previous = practice.status
    practice.status = action
    db.add(FundingPracticeActivity(
        tenant_id=tenant_id, practice_id=practice.id, actor_id=actor_id,
        kind="status_change",
        note=f"{previous} → {action}" + (f" — {note}" if note else "")))
    # Reflect the funding workflow on the generic operational container.
    if practice.practice_id:
        from app.modules.practices.models import Practice as GenericPractice
        generic = db.get(GenericPractice, practice.practice_id)
        if generic is not None:
            if action in {PracticeStatus.APPROVED, PracticeStatus.REJECTED,
                          PracticeStatus.WITHDRAWN}:
                generic.status = ("completed" if action == PracticeStatus.APPROVED
                                  else "cancelled")
                generic.closed_at = utcnow()
            elif action == PracticeStatus.CLOSED:
                # Closing is administrative: it must not flip an approved
                # (completed) practice to cancelled. Outcome comes from the
                # state we are closing FROM; closed_at set only if still open.
                if previous == PracticeStatus.APPROVED:
                    generic.status = "completed"
                elif previous in {PracticeStatus.REJECTED, PracticeStatus.WITHDRAWN}:
                    generic.status = "cancelled"
                generic.closed_at = generic.closed_at or utcnow()
            elif action in {PracticeStatus.DATA_COLLECTION,
                            PracticeStatus.DOCUMENT_COLLECTION}:
                generic.status = "in_progress"
            elif action == PracticeStatus.READY_TO_SUBMIT:
                generic.status = "ready"
            elif action in {PracticeStatus.SUBMITTED,
                            PracticeStatus.UNDER_REVIEW,
                            PracticeStatus.INTEGRATION_REQUESTED}:
                generic.status = "waiting_external"
    db.flush()
    return _practice_out(practice, detail=True)


def list_practices(db: Session, *, tenant_id, company_id=None,
                   status: str | None = None) -> dict:
    stmt = (select(FundingPractice)
            .where(FundingPractice.tenant_id == tenant_id)
            .order_by(FundingPractice.created_at.desc()))
    if company_id:
        stmt = stmt.where(FundingPractice.company_id == company_id)
    if status:
        stmt = stmt.where(FundingPractice.status == status)
    rows = db.scalars(stmt).all()
    return {"practices": [_practice_out(p) for p in rows]}


def get_practice(db: Session, *, tenant_id, practice_id) -> dict:
    practice = _practice_or_404(db, practice_id, tenant_id)
    out = _practice_out(practice, detail=True)
    if practice.version:
        from app.modules.funding.service import _version_out
        out["programme_version"] = _version_out(practice.version)
    return out


def update_practice_document(db: Session, *, tenant_id, practice_id,
                             document_id, actor_id, status: str,
                             note: str | None = None,
                             document_ref: str | None = None) -> dict:
    practice = _practice_or_404(db, practice_id, tenant_id)
    doc = db.get(FundingPracticeDocument, document_id)
    if doc is None or doc.practice_id != practice.id:
        raise NotFoundError("Documento della pratica non trovato.")
    if status not in {s.value for s in PracticeDocStatus}:
        raise ValidationError("Stato documento non valido.",
                              code="funding_doc_status")
    doc.status = status
    if document_ref is not None:
        doc.document_ref = document_ref
    if note:
        doc.notes = note
    db.add(FundingPracticeActivity(
        tenant_id=tenant_id, practice_id=practice.id, actor_id=actor_id,
        kind="document",
        note=f"{doc.doc_type}: {status}" + (f" — {note}" if note else "")))
    # Mirror the status onto the canonical requirement + refresh blockers.
    if practice.practice_id:
        req = db.scalars(
            select(DocumentRequirement).where(
                DocumentRequirement.tenant_id == tenant_id,
                DocumentRequirement.source_ref == str(doc.id))).first()
        if req is not None:
            req.status = status
        from app.modules.practices import service as practice_service
        practice_service.sync_document_blockers(
            db, tenant_id=tenant_id, practice_id=practice.practice_id,
            actor_id=actor_id)
    db.flush()
    return _practice_doc_out(doc)


def add_practice_deadline(db: Session, *, tenant_id, practice_id, actor_id,
                          kind: str, title: str, due_at: datetime,
                          notes: str | None = None) -> dict:
    practice = _practice_or_404(db, practice_id, tenant_id)
    deadline = _add_deadline(db, tenant_id=tenant_id, practice=practice,
                             kind=kind, title=title, due_at=due_at,
                             actor_id=actor_id, notes=notes)
    return _practice_deadline_out(deadline)


def list_deadlines(db: Session, *, tenant_id, company_id=None) -> dict:
    stmt = (select(FundingPracticeDeadline)
            .join(FundingPractice,
                  FundingPractice.id == FundingPracticeDeadline.practice_id)
            .where(FundingPracticeDeadline.tenant_id == tenant_id,
                   FundingPracticeDeadline.status == PracticeDeadlineStatus.OPEN)
            .order_by(FundingPracticeDeadline.due_at))
    if company_id:
        stmt = stmt.where(FundingPractice.company_id == company_id)
    rows = db.scalars(stmt).all()
    return {"deadlines": [_practice_deadline_out(d) for d in rows]}


def add_practice_note(db: Session, *, tenant_id, practice_id, actor_id,
                      note: str) -> dict:
    practice = _practice_or_404(db, practice_id, tenant_id)
    activity = FundingPracticeActivity(
        tenant_id=tenant_id, practice_id=practice.id, actor_id=actor_id,
        kind="note", note=note)
    db.add(activity)
    db.flush()
    return {"id": str(activity.id), "kind": activity.kind,
            "note": activity.note, "created_at": _d(activity.created_at)}
