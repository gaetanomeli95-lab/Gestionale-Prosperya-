"""Practices API — generic operational cases, blockers, client requests,
deadline sync and the company dossier."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.practices import service
from app.modules.practices.schemas import (
    BlockerCreate,
    ClientRequestCreate,
    ClientRequestTransition,
    DeadlineSync,
    PracticeCreate,
    PracticeTransition,
)
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/practices", tags=["practices"])

READ = require_permissions("practices:read")
WRITE = require_permissions("practices:write")


@router.get("")
def list_practices(company_id: uuid.UUID | None = None,
                   owner_id: uuid.UUID | None = None,
                   practice_type: str | None = None,
                   status: str | None = None, priority: str | None = None,
                   waiting_client: bool = False,
                   deadline_risk: bool = False,
                   db: Session = Depends(get_db),
                   ctx: TenantContext = Depends(get_tenant_ctx),
                   _: User = Depends(READ)):
    return service.list_practices(
        db, tenant_id=ctx.tenant_id, company_id=company_id,
        owner_id=owner_id, practice_type=practice_type, status=status,
        priority=priority, waiting_client=waiting_client,
        deadline_risk=deadline_risk)


@router.post("/companies/{company_id}", status_code=201)
def create_practice(company_id: uuid.UUID, payload: PracticeCreate,
                    db: Session = Depends(get_db),
                    ctx: TenantContext = Depends(get_tenant_ctx),
                    user: User = Depends(WRITE)):
    p = service.create_practice(
        db, tenant_id=ctx.tenant_id, company_id=company_id,
        actor_id=user.id, **payload.model_dump())
    out = service.get_practice(db, tenant_id=ctx.tenant_id, practice_id=p.id)
    db.commit()
    return out


@router.get("/{practice_id}")
def get_practice(practice_id: uuid.UUID, db: Session = Depends(get_db),
                 ctx: TenantContext = Depends(get_tenant_ctx),
                 _: User = Depends(READ)):
    return service.get_practice(db, tenant_id=ctx.tenant_id,
                                practice_id=practice_id)


@router.post("/{practice_id}/transition")
def transition(practice_id: uuid.UUID, payload: PracticeTransition,
               db: Session = Depends(get_db),
               ctx: TenantContext = Depends(get_tenant_ctx),
               user: User = Depends(WRITE)):
    out = service.transition_practice(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        actor_id=user.id, action=payload.action, note=payload.note)
    db.commit()
    return out


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------

@router.post("/{practice_id}/blockers", status_code=201)
def add_blocker(practice_id: uuid.UUID, payload: BlockerCreate,
                db: Session = Depends(get_db),
                ctx: TenantContext = Depends(get_tenant_ctx),
                user: User = Depends(WRITE)):
    out = service.add_blocker(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        actor_id=user.id, kind=payload.kind, detail=payload.detail,
        ref_type=payload.ref_type, ref_id=payload.ref_id)
    db.commit()
    return out


@router.post("/{practice_id}/blockers/{blocker_id}/resolve")
def resolve_blocker(practice_id: uuid.UUID, blocker_id: uuid.UUID,
                    db: Session = Depends(get_db),
                    ctx: TenantContext = Depends(get_tenant_ctx),
                    user: User = Depends(WRITE)):
    out = service.resolve_blocker(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        blocker_id=blocker_id, actor_id=user.id)
    db.commit()
    return out


# ---------------------------------------------------------------------------
# Deadlines → tasks
# ---------------------------------------------------------------------------

@router.post("/{practice_id}/deadlines", status_code=201)
def sync_deadline(practice_id: uuid.UUID, payload: DeadlineSync,
                  db: Session = Depends(get_db),
                  ctx: TenantContext = Depends(get_tenant_ctx),
                  user: User = Depends(WRITE)):
    task = service.sync_deadline_task(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        actor_id=user.id, title=payload.title, due_at=payload.due_at,
        kind=payload.kind, priority=payload.priority)
    out = {"task_id": str(task.id), "sync_key": task.sync_key,
           "due_at": task.due_date.isoformat() if task.due_date else None,
           "status": task.status}
    db.commit()
    return out


# ---------------------------------------------------------------------------
# Client requests
# ---------------------------------------------------------------------------

@router.get("/requests/list")
def list_client_requests(company_id: uuid.UUID | None = None,
                         practice_id: uuid.UUID | None = None,
                         status: str | None = None,
                         db: Session = Depends(get_db),
                         ctx: TenantContext = Depends(get_tenant_ctx),
                         _: User = Depends(READ)):
    return service.list_client_requests(
        db, tenant_id=ctx.tenant_id, company_id=company_id,
        practice_id=practice_id, status=status)


@router.post("/companies/{company_id}/requests", status_code=201)
def create_client_request(company_id: uuid.UUID,
                          payload: ClientRequestCreate,
                          db: Session = Depends(get_db),
                          ctx: TenantContext = Depends(get_tenant_ctx),
                          user: User = Depends(WRITE)):
    out = service.create_client_request(
        db, tenant_id=ctx.tenant_id, company_id=company_id,
        actor_id=user.id, **payload.model_dump())
    db.commit()
    return out


@router.post("/requests/{request_id}/transition")
def transition_request(request_id: uuid.UUID,
                       payload: ClientRequestTransition,
                       db: Session = Depends(get_db),
                       ctx: TenantContext = Depends(get_tenant_ctx),
                       user: User = Depends(WRITE)):
    out = service.transition_client_request(
        db, tenant_id=ctx.tenant_id, request_id=request_id,
        actor_id=user.id, action=payload.action, notes=payload.notes)
    db.commit()
    return out


# ---------------------------------------------------------------------------
# Company dossier
# ---------------------------------------------------------------------------

@router.get("/companies/{company_id}/dossier")
def company_dossier(company_id: uuid.UUID, db: Session = Depends(get_db),
                    ctx: TenantContext = Depends(get_tenant_ctx),
                    _: User = Depends(READ)):
    out = service.company_dossier(db, tenant_id=ctx.tenant_id,
                                  company_id=company_id)
    db.commit()
    return out
