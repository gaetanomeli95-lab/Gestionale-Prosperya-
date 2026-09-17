"""Funding API — programmes, assessments, practices, aid history.

Routers only parse/authorize and delegate: no business logic lives here.
Programme entry requires `funding:write`; regime sync `funding:admin`.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.funding import practices as practice_svc
from app.modules.funding import schemas as s
from app.modules.funding import service, signals
from app.modules.funding.seed_data import sync_reference_data
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/funding", tags=["funding"])


def _company(db: Session, company_id: uuid.UUID, ctx: TenantContext):
    return service.company_or_404(db, company_id, ctx.tenant_id)


# --- reference data -----------------------------------------------------------

@router.get("/authorities")
def list_authorities(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    return service.list_authorities(db, tenant_id=ctx.tenant_id)


@router.post("/authorities", status_code=201)
def create_authority(
    payload: s.AuthorityCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:write")),
):
    from app.modules.funding.models import FundingAuthority
    authority = FundingAuthority(tenant_id=ctx.tenant_id,
                                 **payload.model_dump())
    db.add(authority)
    db.commit()
    return {"id": str(authority.id), "code": authority.code,
            "name": authority.name, "level": authority.level}


@router.get("/aid-regimes")
def list_aid_regimes(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    """Versioned aid regimes (de minimis…) with effective dates."""
    return service.list_aid_regimes(db, tenant_id=ctx.tenant_id)


@router.post("/sync", status_code=201)
def sync_reference(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:admin")),
):
    """Materialise verified reference data (authorities, regimes, seed
    programmes). Idempotent: existing (code, version) is never edited."""
    result = sync_reference_data(db, tenant_id=ctx.tenant_id)
    db.commit()
    return result


# --- programmes ---------------------------------------------------------------

@router.get("/programmes")
def list_programmes(
    status: str | None = Query(
        None, pattern="^(draft|upcoming|open|closed|suspended|exhausted|"
                      "archived)$"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    return service.list_programmes(db, tenant_id=ctx.tenant_id, status=status)


@router.post("/programmes", status_code=201)
def create_programme(
    payload: s.ProgrammeCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    """Manual/structured entry of a programme + version. Idempotent on
    (code, version_no) — a regulatory change arrives as a new version."""
    result = service.create_programme(
        db, tenant_id=ctx.tenant_id, actor_id=actor.id,
        payload=payload.model_dump())
    db.commit()
    return result


@router.get("/programmes/{programme_id}")
def get_programme(
    programme_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    return service.get_programme(db, tenant_id=ctx.tenant_id,
                                 programme_id=programme_id)


# --- company profile & aid history --------------------------------------------

@router.get("/companies/{company_id}/profile")
def get_profile(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    company = _company(db, company_id, ctx)
    profile = service.get_profile(db, tenant_id=ctx.tenant_id,
                                  company_id=company.id)
    return {"profile": service._profile_out(profile)}


@router.put("/companies/{company_id}/profile")
def upsert_profile(
    company_id: uuid.UUID,
    payload: s.ProfileUpsert,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:write")),
):
    """Declared funding attributes — null fields stay INSUFFICIENT_DATA."""
    company = _company(db, company_id, ctx)
    result = service.upsert_profile(
        db, tenant_id=ctx.tenant_id, company=company,
        payload=payload.model_dump(exclude_unset=True))
    db.commit()
    return {"profile": result}


@router.get("/companies/{company_id}/aids")
def list_aids(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_company_aids(db, tenant_id=ctx.tenant_id,
                                     company_id=company.id)


@router.post("/companies/{company_id}/aids", status_code=201)
def add_aid(
    company_id: uuid.UUID,
    payload: s.CompanyAidCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:write")),
):
    company = _company(db, company_id, ctx)
    result = service.add_company_aid(db, tenant_id=ctx.tenant_id,
                                     company=company,
                                     payload=payload.model_dump())
    db.commit()
    return result


@router.get("/companies/{company_id}/de-minimis")
def de_minimis(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    """Headroom under the de minimis regime in force — declared aids only."""
    company = _company(db, company_id, ctx)
    return service.de_minimis_position(db, tenant_id=ctx.tenant_id,
                                       company=company)


# --- assessments ---------------------------------------------------------------

@router.post("/companies/{company_id}/assessments", status_code=201)
def run_assessment(
    company_id: uuid.UUID,
    payload: s.AssessmentRun,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    """Persisted deterministic evaluation — snapshots version + engine +
    company facts. Never a freeform AI verdict."""
    company = _company(db, company_id, ctx)
    result = service.run_assessment(db, tenant_id=ctx.tenant_id,
                                    company=company,
                                    version_id=payload.version_id,
                                    actor_id=actor.id)
    db.commit()
    return result


@router.get("/companies/{company_id}/assessments")
def list_assessments(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_assessments(db, tenant_id=ctx.tenant_id,
                                    company_id=company.id)


@router.get("/assessments/{assessment_id}")
def get_assessment(
    assessment_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    return service.get_assessment(db, tenant_id=ctx.tenant_id,
                                  assessment_id=assessment_id)


@router.post("/assessments/{assessment_id}/review")
def review_assessment(
    assessment_id: uuid.UUID,
    payload: s.AssessmentReview,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    """Human review transition — audited, with reviewer + notes."""
    result = service.review_assessment(
        db, tenant_id=ctx.tenant_id, assessment_id=assessment_id,
        actor_id=actor.id, action=payload.action, notes=payload.notes)
    db.commit()
    return result


@router.get("/companies/{company_id}/match")
def match(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    """Deterministic pre-screening across active versions — grouped by
    outcome, never a match percentage."""
    company = _company(db, company_id, ctx)
    return service.match_company(db, tenant_id=ctx.tenant_id, company=company)


# --- practices ------------------------------------------------------------------

@router.post("/companies/{company_id}/practices", status_code=201)
def create_practice(
    company_id: uuid.UUID,
    payload: s.PracticeCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    """Open a managed practice — materialises the document checklist and
    the application deadline from the version."""
    company = _company(db, company_id, ctx)
    result = practice_svc.create_practice(
        db, tenant_id=ctx.tenant_id, company=company,
        version_id=payload.version_id, actor_id=actor.id,
        assessment_id=payload.assessment_id, owner_id=payload.owner_id,
        notes=payload.notes)
    db.commit()
    return result


@router.get("/companies/{company_id}/practices")
def list_practices(
    company_id: uuid.UUID,
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    company = _company(db, company_id, ctx)
    return practice_svc.list_practices(db, tenant_id=ctx.tenant_id,
                                       company_id=company.id, status=status)


@router.get("/practices/{practice_id}")
def get_practice(
    practice_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    return practice_svc.get_practice(db, tenant_id=ctx.tenant_id,
                                     practice_id=practice_id)


@router.post("/practices/{practice_id}/transition")
def transition_practice(
    practice_id: uuid.UUID,
    payload: s.PracticeTransition,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    result = practice_svc.transition_practice(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        actor_id=actor.id, action=payload.action, note=payload.note)
    db.commit()
    return result


@router.patch("/practices/{practice_id}/documents/{document_id}")
def update_practice_document(
    practice_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: s.PracticeDocumentUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    result = practice_svc.update_practice_document(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        document_id=document_id, actor_id=actor.id, status=payload.status,
        note=payload.note, document_ref=payload.document_ref)
    db.commit()
    return result


@router.post("/practices/{practice_id}/deadlines", status_code=201)
def add_practice_deadline(
    practice_id: uuid.UUID,
    payload: s.PracticeDeadlineCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    result = practice_svc.add_practice_deadline(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        actor_id=actor.id, kind=payload.kind, title=payload.title,
        due_at=payload.due_at, notes=payload.notes)
    db.commit()
    return result


@router.post("/practices/{practice_id}/notes", status_code=201)
def add_practice_note(
    practice_id: uuid.UUID,
    payload: s.PracticeNoteCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("funding:write")),
):
    result = practice_svc.add_practice_note(
        db, tenant_id=ctx.tenant_id, practice_id=practice_id,
        actor_id=actor.id, note=payload.note)
    db.commit()
    return result


@router.get("/deadlines")
def list_deadlines(
    company_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    return practice_svc.list_deadlines(db, tenant_id=ctx.tenant_id,
                                       company_id=company_id)


# --- company funding view -------------------------------------------------------

@router.get("/companies/{company_id}/overview")
def company_overview(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("funding:read")),
):
    """The funding section of Company detail — profile, aids, assessments,
    practices, deadlines, de minimis position, limitations."""
    company = _company(db, company_id, ctx)
    return signals.company_funding(db, tenant_id=ctx.tenant_id,
                                   company=company)
