"""Controlling API — debt service, early-warning rules, alerts, scenarios.

Routers only parse/authorize and delegate: no business logic lives here.
Every figure is a decimal string or null; a missing value is never zero.
Rule sync requires `controlling:admin` — a scope only the platform admin holds.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.controlling import schemas as s
from app.modules.controlling import service
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/controlling", tags=["controlling"])


def _company(db: Session, company_id: uuid.UUID, ctx: TenantContext):
    return service.company_or_404(db, company_id, ctx.tenant_id)


# --- early-warning rules (jurisdiction-level reference data) -----------------

@router.get("/rules")
def list_rules(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("controlling:read")),
):
    """The verified early-warning rules in force today, with sources."""
    return service.list_rules(db, tenant_id=ctx.tenant_id)


@router.post("/rules/sync", status_code=201)
def sync_rules(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("controlling:admin")),
):
    """Materialise the verified rules. Idempotent: an existing (code, version)
    is never edited — a regulatory change must arrive as a new version."""
    result = service.sync_rules(db, tenant_id=ctx.tenant_id)
    db.commit()
    return result


# --- debt facilities & service lines -----------------------------------------

@router.get("/companies/{company_id}/facilities")
def list_facilities(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("controlling:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_facilities(db, tenant_id=ctx.tenant_id, company_id=company.id)


@router.post("/companies/{company_id}/facilities", status_code=201)
def create_facility(
    company_id: uuid.UUID,
    payload: s.FacilityCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    company = _company(db, company_id, ctx)
    result = service.create_facility(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        name=payload.name, facility_type=payload.facility_type,
        lender_name=payload.lender_name,
        outstanding_principal=payload.outstanding_principal, notes=payload.notes)
    db.commit()
    return result


@router.patch("/companies/{company_id}/facilities/{facility_id}")
def update_facility(
    company_id: uuid.UUID,
    facility_id: uuid.UUID,
    payload: s.FacilityUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    """Reference-data correction (label, lender, declared residual)."""
    company = _company(db, company_id, ctx)
    result = service.update_facility(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        facility_id=facility_id,
        changes=payload.model_dump(exclude_unset=True))
    db.commit()
    return result


@router.post("/companies/{company_id}/facilities/{facility_id}/instalments",
             status_code=201)
def add_instalment(
    company_id: uuid.UUID,
    facility_id: uuid.UUID,
    payload: s.InstalmentCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    company = _company(db, company_id, ctx)
    result = service.add_instalment(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        facility_id=facility_id, instalment_no=payload.instalment_no,
        due_date=payload.due_date, principal=payload.principal,
        interest=payload.interest)
    db.commit()
    return result


@router.post("/companies/{company_id}/instalments/{line_id}/settle")
def settle_instalment(
    company_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: s.InstalmentSettle,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    """Tracked transition: scheduled → paid | waived (with evidence)."""
    company = _company(db, company_id, ctx)
    result = service.settle_instalment(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        line_id=line_id, action=payload.action,
        settled_on=payload.settled_on, note=payload.note)
    db.commit()
    return result


# --- snapshot (metrics + live evaluations + persisted alerts) -----------------

@router.get("/companies/{company_id}/snapshot")
def snapshot(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("controlling:read")),
):
    """DSCR, 12-month continuity, margin of safety, trends, live rule
    evaluations and persisted alerts. Read-only: nothing is persisted here."""
    company = _company(db, company_id, ctx)
    return service.controlling_snapshot(db, tenant_id=ctx.tenant_id,
                                        company_id=company.id)


# --- alerts -------------------------------------------------------------------

@router.post("/companies/{company_id}/alerts/evaluate", status_code=201)
def evaluate_alerts(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    """Run detection and persist alerts. Idempotent by `dedupe_key`: re-runs
    refresh evidence, cleared conditions auto-resolve."""
    company = _company(db, company_id, ctx)
    result = service.run_detection(db, tenant_id=ctx.tenant_id, company=company,
                                   actor_id=actor.id)
    db.commit()
    return result


@router.get("/companies/{company_id}/alerts")
def list_alerts(
    company_id: uuid.UUID,
    status: str | None = Query(
        None, pattern="^(open|acknowledged|resolved|dismissed)$"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("controlling:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_alerts(db, tenant_id=ctx.tenant_id, company_id=company.id,
                               status=status)


@router.post("/companies/{company_id}/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    company_id: uuid.UUID,
    alert_id: uuid.UUID,
    payload: s.AlertTransition,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    company = _company(db, company_id, ctx)
    result = service.transition_alert(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        alert_id=alert_id, action="acknowledge", note=payload.note)
    db.commit()
    return result


@router.post("/companies/{company_id}/alerts/{alert_id}/resolve")
def resolve_alert(
    company_id: uuid.UUID,
    alert_id: uuid.UUID,
    payload: s.AlertTransition,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    company = _company(db, company_id, ctx)
    result = service.transition_alert(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        alert_id=alert_id, action="resolve", note=payload.note)
    db.commit()
    return result


@router.post("/companies/{company_id}/alerts/{alert_id}/dismiss")
def dismiss_alert(
    company_id: uuid.UUID,
    alert_id: uuid.UUID,
    payload: s.AlertTransition,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("controlling:write")),
):
    """Dismiss requires a mandatory note — a human decision, audited."""
    company = _company(db, company_id, ctx)
    result = service.transition_alert(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        alert_id=alert_id, action="dismiss", note=payload.note)
    db.commit()
    return result


# --- scenarios -----------------------------------------------------------------

@router.get("/companies/{company_id}/scenarios/presets")
def scenario_presets(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("controlling:read")),
):
    _company(db, company_id, ctx)
    return service.list_presets()


@router.post("/companies/{company_id}/scenarios/run")
def run_scenario(
    company_id: uuid.UUID,
    payload: s.ScenarioRun,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("controlling:read")),
):
    """Deterministic recompute on transformed copies of the canonical facts.
    Historical actuals are never touched — a scenario is a recompute, not a
    write."""
    company = _company(db, company_id, ctx)
    return service.run_scenario(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                raw=payload.model_dump(exclude_none=True))
