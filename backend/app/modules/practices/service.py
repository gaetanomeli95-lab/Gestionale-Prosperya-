"""Generic practice operations — lifecycle, blockers, client requests,
deadline→task synchronisation and the company dossier.

Deadlines reuse the existing Task model with a deterministic `sync_key`:
repeated syncs update the same task instead of creating duplicates.
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.activities.models import ActivityEvent
from app.modules.companies.models import Company
from app.modules.documents import service as doc_service
from app.modules.documents.models import (
    DocumentRequirement,
    RequirementStatus,
)
from app.modules.practices.models import (
    PRACTICE_TRANSITIONS,
    TERMINAL_STATUSES,
    BlockerKind,
    BlockerStatus,
    ClientRequest,
    ClientRequestStatus,
    Practice,
    PracticeBlocker,
    PracticePriority,
    PracticeStatus,
    PracticeType,
)
from app.modules.tasks.models import Task, TaskPriority, TaskStatus
from app.shared.mixins import utcnow


def _d(value) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _blocker_out(b: PracticeBlocker) -> dict:
    return {
        "id": str(b.id), "kind": b.kind, "ref_type": b.ref_type,
        "ref_id": str(b.ref_id) if b.ref_id else None,
        "detail": b.detail, "status": b.status,
        "created_at": _d(b.created_at), "resolved_at": _d(b.resolved_at),
    }


def _request_out(r: ClientRequest) -> dict:
    return {
        "id": str(r.id), "company_id": str(r.company_id),
        "practice_id": str(r.practice_id) if r.practice_id else None,
        "item": r.item, "description": r.description,
        "requested_by_id": (str(r.requested_by_id)
                            if r.requested_by_id else None),
        "requested_at": _d(r.requested_at), "due_at": _d(r.due_at),
        "status": r.status, "fulfilled_at": _d(r.fulfilled_at),
        "fulfilled_by_id": (str(r.fulfilled_by_id)
                            if r.fulfilled_by_id else None),
        "notes": r.notes, "created_at": _d(r.created_at),
    }


def _practice_out(p: Practice, *, detail: bool = False) -> dict:
    out = {
        "id": str(p.id), "company_id": str(p.company_id),
        "practice_type": p.practice_type, "title": p.title,
        "description": p.description, "status": p.status,
        "priority": p.priority,
        "owner_id": str(p.owner_id) if p.owner_id else None,
        "opened_at": _d(p.opened_at), "target_date": _d(p.target_date),
        "closed_at": _d(p.closed_at), "source_module": p.source_module,
        "external_ref": p.external_ref, "notes": p.notes,
        "created_at": _d(p.created_at),
        "open_blockers": sum(1 for b in p.blockers
                             if b.status == BlockerStatus.OPEN),
    }
    if detail:
        out["blockers"] = [_blocker_out(b) for b in p.blockers]
        out["client_requests"] = [_request_out(r)
                                  for r in p.client_requests]
    return out


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _company_or_404(db: Session, tenant_id, company_id) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id or company.deleted_at:
        raise NotFoundError("Azienda non trovata.")
    return company


def _practice_or_404(db: Session, tenant_id, practice_id) -> Practice:
    p = db.get(Practice, practice_id)
    if p is None or p.tenant_id != tenant_id or p.deleted_at:
        raise NotFoundError("Pratica non trovata.")
    return p


def _request_or_404(db: Session, tenant_id, request_id) -> ClientRequest:
    r = db.get(ClientRequest, request_id)
    if r is None or r.tenant_id != tenant_id or r.deleted_at:
        raise NotFoundError("Richiesta cliente non trovata.")
    return r


def _activity(db: Session, *, tenant_id, actor_id, event_type: str,
              entity_type: str, entity_id, summary: str,
              payload: dict | None = None) -> None:
    db.add(ActivityEvent(
        tenant_id=tenant_id, actor_id=actor_id, event_type=event_type,
        entity_type=entity_type, entity_id=entity_id, summary=summary,
        payload=payload or {}))


# ---------------------------------------------------------------------------
# Practice lifecycle
# ---------------------------------------------------------------------------

def create_practice(db: Session, *, tenant_id, company_id, actor_id,
                    title: str, practice_type: str = PracticeType.GENERIC,
                    description: str | None = None,
                    owner_id=None, priority: str = PracticePriority.MEDIUM,
                    target_date: datetime | None = None,
                    source_module: str | None = None,
                    external_ref: str | None = None,
                    notes: str | None = None,
                    status: str = PracticeStatus.OPEN) -> Practice:
    """Open a generic operational practice. Returns the ORM row so domain
    modules (funding…) can link their specialised records to it."""
    company = _company_or_404(db, tenant_id, company_id)
    if practice_type not in {t.value for t in PracticeType}:
        raise ValidationError(f"Tipo pratica non valido: {practice_type}.",
                              code="practice_type")
    if status not in {PracticeStatus.DRAFT, PracticeStatus.OPEN}:
        raise ValidationError("Una nuova pratica parte da draft o open.",
                              code="practice_initial_status")
    p = Practice(tenant_id=tenant_id, company_id=company.id,
                 practice_type=practice_type, title=title,
                 description=description, status=status, priority=priority,
                 owner_id=owner_id or actor_id, target_date=target_date,
                 source_module=source_module, external_ref=external_ref,
                 notes=notes)
    db.add(p)
    db.flush()
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="practice_created", entity_type="practice",
              entity_id=p.id, summary=f"Pratica aperta: {title}",
              payload={"practice_type": practice_type,
                       "source_module": source_module})
    return p


def transition_practice(db: Session, *, tenant_id, practice_id, actor_id,
                        action: str, note: str | None = None) -> dict:
    p = _practice_or_404(db, tenant_id, practice_id)
    allowed = PRACTICE_TRANSITIONS.get(p.status, set())
    if action not in allowed:
        raise ConflictError(
            f"Transizione {p.status} → {action} non consentita.",
            code="practice_transition")
    previous = p.status
    p.status = action
    if action in TERMINAL_STATUSES:
        p.closed_at = utcnow()
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="practice_status_changed", entity_type="practice",
              entity_id=p.id,
              summary=f"{p.title}: {previous} → {action}"
                      + (f" — {note}" if note else ""),
              payload={"from": previous, "to": action})
    db.flush()
    return _practice_out(p, detail=True)


def get_practice(db: Session, *, tenant_id, practice_id) -> dict:
    return _practice_out(_practice_or_404(db, tenant_id, practice_id),
                         detail=True)


def list_practices(db: Session, *, tenant_id, company_id=None,
                   owner_id=None, practice_type: str | None = None,
                   status: str | None = None,
                   priority: str | None = None,
                   waiting_client: bool = False,
                   deadline_risk: bool = False) -> dict:
    stmt = (select(Practice)
            .where(Practice.tenant_id == tenant_id,
                   Practice.deleted_at.is_(None))
            .order_by(Practice.opened_at.desc()))
    if company_id:
        stmt = stmt.where(Practice.company_id == company_id)
    if owner_id:
        stmt = stmt.where(Practice.owner_id == owner_id)
    if practice_type:
        stmt = stmt.where(Practice.practice_type == practice_type)
    if status:
        stmt = stmt.where(Practice.status == status)
    if priority:
        stmt = stmt.where(Practice.priority == priority)
    if waiting_client:
        stmt = stmt.where(Practice.status == PracticeStatus.WAITING_CLIENT)
    rows = db.scalars(stmt).all()
    if deadline_risk:
        horizon = utcnow().timestamp() + 14 * 86400
        rows = [p for p in rows
                if p.target_date
                and p.target_date.timestamp() <= horizon
                and p.status not in TERMINAL_STATUSES]
    return {"practices": [_practice_out(p) for p in rows]}


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------

def add_blocker(db: Session, *, tenant_id, practice_id, actor_id,
                kind: str, detail: str | None = None,
                ref_type: str | None = None, ref_id=None) -> dict:
    p = _practice_or_404(db, tenant_id, practice_id)
    if kind not in {k.value for k in BlockerKind}:
        raise ValidationError(f"Tipo blocco non valido: {kind}.",
                              code="blocker_kind")
    b = PracticeBlocker(tenant_id=tenant_id, practice_id=p.id, kind=kind,
                        ref_type=ref_type, ref_id=ref_id, detail=detail)
    db.add(b)
    db.flush()
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="practice_blocker_added", entity_type="practice",
              entity_id=p.id, summary=f"Blocco su \"{p.title}\": {kind}",
              payload={"kind": kind, "detail": detail})
    return _blocker_out(b)


def resolve_blocker(db: Session, *, tenant_id, practice_id, blocker_id,
                    actor_id) -> dict:
    p = _practice_or_404(db, tenant_id, practice_id)
    b = db.get(PracticeBlocker, blocker_id)
    if b is None or b.practice_id != p.id:
        raise NotFoundError("Blocco non trovato.")
    if b.status == BlockerStatus.OPEN:
        b.status = BlockerStatus.RESOLVED
        b.resolved_at = utcnow()
        _activity(db, tenant_id=tenant_id, actor_id=actor_id,
                  event_type="practice_blocker_resolved",
                  entity_type="practice", entity_id=p.id,
                  summary=f"Blocco risolto su \"{p.title}\": {b.kind}",
                  payload={"kind": b.kind})
    db.flush()
    return _blocker_out(b)


def sync_document_blockers(db: Session, *, tenant_id, practice_id,
                           actor_id=None) -> None:
    """Deterministic blocker sync: one open MISSING_DOCUMENT blocker per
    unsatisfied mandatory requirement; resolved automatically when the
    requirement is received/validated/not_applicable."""
    reqs = db.scalars(
        select(DocumentRequirement).where(
            DocumentRequirement.tenant_id == tenant_id,
            DocumentRequirement.practice_id == practice_id,
            DocumentRequirement.mandatory.is_(True))).all()
    open_blockers = {b.ref_id: b for b in db.scalars(
        select(PracticeBlocker).where(
            PracticeBlocker.practice_id == practice_id,
            PracticeBlocker.kind == BlockerKind.MISSING_DOCUMENT,
            PracticeBlocker.status == BlockerStatus.OPEN))}
    satisfied = {RequirementStatus.RECEIVED, RequirementStatus.VALIDATED,
                 RequirementStatus.NOT_APPLICABLE}
    for req in reqs:
        blocker = open_blockers.pop(req.id, None)
        if req.status in satisfied:
            if blocker is not None:
                blocker.status = BlockerStatus.RESOLVED
                blocker.resolved_at = utcnow()
        elif blocker is None:
            db.add(PracticeBlocker(
                tenant_id=tenant_id, practice_id=practice_id,
                kind=BlockerKind.MISSING_DOCUMENT,
                ref_type="document_requirement", ref_id=req.id,
                detail=f"Documento obbligatorio mancante: {req.label}"))
    # Requirements removed/marked optional → stale blockers resolve.
    for stale in open_blockers.values():
        stale.status = BlockerStatus.RESOLVED
        stale.resolved_at = utcnow()
    db.flush()


# ---------------------------------------------------------------------------
# Client requests
# ---------------------------------------------------------------------------

_REQUEST_TRANSITIONS: dict[str, set[str]] = {
    ClientRequestStatus.DRAFT: {ClientRequestStatus.SENT,
                                ClientRequestStatus.CANCELLED},
    ClientRequestStatus.SENT: {ClientRequestStatus.PARTIAL,
                               ClientRequestStatus.FULFILLED,
                               ClientRequestStatus.OVERDUE,
                               ClientRequestStatus.CANCELLED},
    ClientRequestStatus.PARTIAL: {ClientRequestStatus.FULFILLED,
                                  ClientRequestStatus.OVERDUE,
                                  ClientRequestStatus.CANCELLED},
    ClientRequestStatus.OVERDUE: {ClientRequestStatus.PARTIAL,
                                  ClientRequestStatus.FULFILLED,
                                  ClientRequestStatus.CANCELLED},
    ClientRequestStatus.FULFILLED: set(),
    ClientRequestStatus.CANCELLED: set(),
}


def create_client_request(db: Session, *, tenant_id, company_id, actor_id,
                          item: str, practice_id=None,
                          description: str | None = None,
                          due_at: datetime | None = None,
                          notes: str | None = None,
                          send: bool = True) -> dict:
    company = _company_or_404(db, tenant_id, company_id)
    if practice_id is not None:
        p = _practice_or_404(db, tenant_id, practice_id)
        if p.company_id != company.id:
            raise ValidationError(
                "La pratica appartiene a un'altra azienda.",
                code="request_practice_mismatch")
    r = ClientRequest(
        tenant_id=tenant_id, company_id=company.id,
        practice_id=practice_id, item=item, description=description,
        requested_by_id=actor_id, due_at=due_at, notes=notes,
        status=(ClientRequestStatus.SENT if send
                else ClientRequestStatus.DRAFT),
        requested_at=utcnow() if send else None)
    db.add(r)
    db.flush()
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="client_request_created",
              entity_type="client_request", entity_id=r.id,
              summary=f"Richiesta al cliente: {item}",
              payload={"practice_id": str(practice_id)
                       if practice_id else None})
    return _request_out(r)


def transition_client_request(db: Session, *, tenant_id, request_id,
                              actor_id, action: str,
                              notes: str | None = None) -> dict:
    r = _request_or_404(db, tenant_id, request_id)
    allowed = _REQUEST_TRANSITIONS.get(r.status, set())
    if action not in allowed:
        raise ConflictError(
            f"Transizione {r.status} → {action} non consentita.",
            code="client_request_transition")
    previous = r.status
    r.status = action
    if action == ClientRequestStatus.SENT and r.requested_at is None:
        r.requested_at = utcnow()
    if action == ClientRequestStatus.FULFILLED:
        r.fulfilled_at = utcnow()
        r.fulfilled_by_id = actor_id
    if notes:
        r.notes = notes
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="client_request_updated",
              entity_type="client_request", entity_id=r.id,
              summary=f"Richiesta \"{r.item}\": {previous} → {action}",
              payload={"from": previous, "to": action})
    db.flush()
    return _request_out(r)


def refresh_overdue_requests(db: Session, *, tenant_id,
                             now: datetime | None = None) -> int:
    """Mark sent/partial requests past due as OVERDUE. Deterministic and
    idempotent — OVERDUE can still move to fulfilled/partial/cancelled."""
    now = now or utcnow()
    rows = db.scalars(
        select(ClientRequest).where(
            ClientRequest.tenant_id == tenant_id,
            ClientRequest.deleted_at.is_(None),
            ClientRequest.status.in_([ClientRequestStatus.SENT,
                                      ClientRequestStatus.PARTIAL]),
            ClientRequest.due_at.is_not(None),
            ClientRequest.due_at < now)).all()
    for r in rows:
        r.status = ClientRequestStatus.OVERDUE
    db.flush()
    return len(rows)


def list_client_requests(db: Session, *, tenant_id, company_id=None,
                         practice_id=None, status: str | None = None) -> dict:
    stmt = (select(ClientRequest)
            .where(ClientRequest.tenant_id == tenant_id,
                   ClientRequest.deleted_at.is_(None))
            .order_by(ClientRequest.created_at.desc()))
    if company_id:
        stmt = stmt.where(ClientRequest.company_id == company_id)
    if practice_id:
        stmt = stmt.where(ClientRequest.practice_id == practice_id)
    if status:
        stmt = stmt.where(ClientRequest.status == status)
    rows = db.scalars(stmt).all()
    return {"requests": [_request_out(r) for r in rows]}


# ---------------------------------------------------------------------------
# Deadlines → tasks (exactly-once)
# ---------------------------------------------------------------------------

def sync_deadline_task(db: Session, *, tenant_id, practice_id, actor_id,
                       title: str, due_at: datetime,
                       kind: str = "deadline",
                       priority: str = TaskPriority.HIGH) -> Task:
    """Create-or-update the operational task for a practice deadline.

    The sync key `practice:{id}:{kind}:{due}` makes repeated syncs
    idempotent: same deadline ⇒ same task, updated in place."""
    p = _practice_or_404(db, tenant_id, practice_id)
    sync_key = f"practice:{p.id}:{kind}:{due_at.date().isoformat()}"

    def _existing() -> Task | None:
        return db.scalars(
            select(Task).where(Task.tenant_id == tenant_id,
                               Task.sync_key == sync_key,
                               Task.deleted_at.is_(None))).first()

    task = _existing()
    if task is None:
        task = Task(tenant_id=tenant_id, title=title,
                    description=f"Pratica \"{p.title}\" — {kind}.",
                    status=TaskStatus.TODO, priority=priority,
                    owner_id=p.owner_id, created_by_id=actor_id,
                    due_date=due_at, entity_type="practice",
                    entity_id=p.id, sync_key=sync_key)
        # The unique index uq_tasks_tenant_sync_key is the real exactly-once
        # guarantee: if a concurrent request inserted the same key between our
        # read and this insert, roll back just this SAVEPOINT and adopt theirs.
        try:
            with db.begin_nested():
                db.add(task)
                db.flush()
        except IntegrityError:
            if task in db:           # savepoint rollback usually expunges it already
                db.expunge(task)
            task = _existing()
            if task is None:  # pragma: no cover — constraint fired for another reason
                raise
    # Same deadline ⇒ same task, refreshed in place (no-op for a fresh one).
    task.title = title
    task.due_date = due_at
    task.owner_id = p.owner_id
    if task.status == TaskStatus.CANCELLED:
        task.status = TaskStatus.TODO
    db.flush()
    return task


# ---------------------------------------------------------------------------
# Company dossier — the accountant's operational view
# ---------------------------------------------------------------------------

def company_dossier(db: Session, *, tenant_id, company_id) -> dict:
    """One coherent read: practices, documents, missing requirements,
    client requests, upcoming deadlines, recent activity."""
    company = _company_or_404(db, tenant_id, company_id)
    refresh_overdue_requests(db, tenant_id=tenant_id)

    practices = db.scalars(
        select(Practice)
        .where(Practice.tenant_id == tenant_id,
               Practice.company_id == company.id,
               Practice.deleted_at.is_(None))
        .order_by(Practice.opened_at.desc())).all()

    requirements = doc_service.list_requirements(
        db, tenant_id=tenant_id, company_id=company.id)["requirements"]
    missing = [r for r in requirements
               if r["status"] in {RequirementStatus.MISSING,
                                  RequirementStatus.REQUESTED,
                                  RequirementStatus.REJECTED}]

    documents = doc_service.list_documents(
        db, tenant_id=tenant_id, company_id=company.id)["documents"]

    requests = list_client_requests(
        db, tenant_id=tenant_id, company_id=company.id)["requests"]

    practice_ids = [p.id for p in practices]
    deadlines = []
    if practice_ids:
        tasks = db.scalars(
            select(Task)
            .where(Task.tenant_id == tenant_id,
                   Task.entity_type == "practice",
                   Task.entity_id.in_(practice_ids),
                   Task.deleted_at.is_(None),
                   Task.status != TaskStatus.DONE,
                   Task.due_date.is_not(None))
            .order_by(Task.due_date)).all()
        deadlines = [
            {"task_id": str(t.id), "practice_id": str(t.entity_id),
             "title": t.title, "due_at": _d(t.due_date),
             "status": t.status, "priority": t.priority}
            for t in tasks
        ]

    entity_ids = [str(p.id) for p in practices]
    activities = []
    if entity_ids:
        events = db.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.tenant_id == tenant_id,
                   ActivityEvent.entity_type.in_(
                       ["practice", "client_request",
                        "document_requirement", "document"]),
                   ActivityEvent.entity_id.in_(
                       [p.id for p in practices]
                       + [uuid.UUID(r["id"]) for r in requirements]
                       + [uuid.UUID(r["id"]) for r in requests]
                       + [uuid.UUID(d["id"]) for d in documents]))
            .order_by(ActivityEvent.created_at.desc()).limit(30)).all()
        activities = [
            {"id": str(e.id), "event_type": e.event_type,
             "entity_type": e.entity_type, "entity_id": str(e.entity_id),
             "summary": e.summary, "created_at": _d(e.created_at)}
            for e in events
        ]

    return {
        "company_id": str(company.id),
        "practices": [_practice_out(p) for p in practices],
        "documents": documents,
        "missing_documents": missing,
        "client_requests": requests,
        "deadlines": deadlines,
        "activities": activities,
    }
