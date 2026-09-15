"""Fiscal API — registro IVA, liquidazioni, scadenze, bozze F24.

Every figure is a decimal string or null; a missing value is never zero.
Routers only parse/authorize and delegate: no business logic lives here.
Validation endpoints require `fiscal:validate` — a scope the AI layer and the
backoffice role do not hold.
"""
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.fiscal import rules_seed, service
from app.modules.fiscal import schemas as s
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/fiscal", tags=["fiscal"])


def _company(db: Session, company_id: uuid.UUID, ctx: TenantContext):
    return service.company_or_404(db, company_id, ctx.tenant_id)


# --- rule sets (jurisdiction-level reference data) --------------------------

@router.get("/rule-sets")
def list_rule_sets(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("fiscal:read")),
):
    """The verified rules currently loaded, with their authoritative sources."""
    return service.list_rule_sets(db)


@router.post("/rule-sets/sync", status_code=201)
def sync_rule_sets(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("fiscal:admin")),
):
    """Materialise the verified rule sets. Idempotent: existing versions are
    never edited — a law change must arrive as a new version."""
    result = rules_seed.ensure_rule_sets(db)
    db.commit()
    return result


# --- VAT register -----------------------------------------------------------

@router.get("/companies/{company_id}/vat-entries")
def list_vat_entries(
    company_id: uuid.UUID,
    year: int = Query(..., ge=2000, le=2100),
    period_no: int | None = Query(None, ge=1, le=12),
    frequency: str = Query("monthly", pattern="^(monthly|quarterly)$"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("fiscal:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_vat_entries(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                    year=year, period_no=period_no, frequency=frequency)


@router.post("/companies/{company_id}/vat-entries", status_code=201)
def create_vat_entry(
    company_id: uuid.UUID,
    payload: s.VatEntryCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:write")),
):
    company = _company(db, company_id, ctx)
    result = service.record_vat_entry(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        direction=payload.direction, competence_date=payload.competence_date,
        taxable_amount=payload.taxable_amount, vat_amount=payload.vat_amount,
        vat_rate=payload.vat_rate, vat_nature=payload.vat_nature,
        deductible=payload.deductible, document_number=payload.document_number,
        document_date=payload.document_date,
        counterparty_name=payload.counterparty_name,
        counterparty_vat=payload.counterparty_vat,
        source_ref=payload.source_ref, notes=payload.notes)
    db.commit()
    return result


@router.post("/companies/{company_id}/vat-entries/import", status_code=201)
def import_vat_entries(
    company_id: uuid.UUID,
    payload: s.VatEntryImport,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:write")),
):
    """Atomic, idempotent VAT-register ingestion keyed by `source_ref`."""
    company = _company(db, company_id, ctx)
    result = service.import_vat_entries(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        rows=[row.model_dump() for row in payload.rows])
    db.commit()
    return result


@router.post("/companies/{company_id}/vat-entries/from-invoices", status_code=201)
def link_invoices(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:write", "billing:read")),
):
    """Derive VAT entries from workspace invoices. Derived entries land in
    `requires_review`: deductibility is never assumed."""
    company = _company(db, company_id, ctx)
    result = service.link_invoices(db, tenant_id=ctx.tenant_id, company=company,
                                   actor_id=actor.id)
    db.commit()
    return result


@router.post("/companies/{company_id}/vat-entries/{entry_id}/confirm", status_code=201)
def confirm_entry(
    company_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: s.EntryConfirm,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:write")),
):
    """Human decision on a pending entry — recorded as a new immutable entry."""
    company = _company(db, company_id, ctx)
    result = service.confirm_entry_treatment(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        entry_id=entry_id, treatment=payload.treatment,
        deductible=payload.deductible, reason=payload.reason)
    db.commit()
    return result


# --- settlements ------------------------------------------------------------

@router.post("/companies/{company_id}/settlements/calculate", status_code=201)
def calculate_settlement(
    company_id: uuid.UUID,
    payload: s.SettlementCalculate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:write")),
):
    """Deterministic periodic VAT settlement. Versioned: a recalculation
    supersedes the previous version instead of overwriting it."""
    company = _company(db, company_id, ctx)
    result = service.calculate_settlement(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        year=payload.year, period_no=payload.period_no, frequency=payload.frequency)
    db.commit()
    return result


@router.get("/companies/{company_id}/settlements")
def list_settlements(
    company_id: uuid.UUID,
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("fiscal:read")),
):
    company = _company(db, company_id, ctx)
    return service.fiscal_snapshot(db, tenant_id=ctx.tenant_id,
                                   company_id=company.id, year=year)


@router.post("/companies/{company_id}/settlements/{settlement_id}/validate")
def validate_settlement(
    company_id: uuid.UUID,
    settlement_id: uuid.UUID,
    payload: s.SettlementValidate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:validate")),
):
    """Human validation of a settlement. Turns a payable result into a fiscal
    deadline and exactly one treasury cash obligation."""
    company = _company(db, company_id, ctx)
    result = service.validate_settlement(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        settlement_id=settlement_id, note=payload.note,
        acknowledge_warnings=payload.acknowledge_warnings)
    db.commit()
    return result


# --- deadlines --------------------------------------------------------------

@router.get("/companies/{company_id}/deadlines")
def list_deadlines(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("fiscal:read")),
):
    company = _company(db, company_id, ctx)
    return service.fiscal_snapshot(db, tenant_id=ctx.tenant_id,
                                   company_id=company.id)["deadlines"]


# --- F24 drafts ---------------------------------------------------------------

@router.post("/companies/{company_id}/f24/generate", status_code=201)
def generate_f24(
    company_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:write")),
):
    company = _company(db, company_id, ctx)
    result = service.generate_f24(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        settlement_id=uuid.UUID(str(payload["settlement_id"])))
    db.commit()
    return result


@router.get("/companies/{company_id}/f24/{draft_id}")
def get_f24(
    company_id: uuid.UUID,
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("fiscal:read")),
):
    company = _company(db, company_id, ctx)
    draft = service.get_f24_draft(db, tenant_id=ctx.tenant_id, company=company,
                                  draft_id=draft_id)
    return service.f24_data(draft)


@router.post("/companies/{company_id}/f24/{draft_id}/validate")
def validate_f24(
    company_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: s.F24Transition,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:validate")),
):
    company = _company(db, company_id, ctx)
    result = service.transition_f24(db, tenant_id=ctx.tenant_id, company=company,
                                    actor_id=actor.id, draft_id=draft_id,
                                    action="validate", note=payload.note)
    db.commit()
    return result


@router.post("/companies/{company_id}/f24/{draft_id}/approve")
def approve_f24(
    company_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: s.F24Transition,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:validate")),
):
    company = _company(db, company_id, ctx)
    result = service.transition_f24(db, tenant_id=ctx.tenant_id, company=company,
                                    actor_id=actor.id, draft_id=draft_id,
                                    action="approve", note=payload.note)
    db.commit()
    return result


@router.post("/companies/{company_id}/f24/{draft_id}/export")
def export_f24(
    company_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: s.F24ExportRequest,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("fiscal:read")),
):
    """Internal export (JSON/CSV) of an approved draft.

    This is NOT a telematic F24 file: no Entratel/CBI record layout is
    implemented and nothing is transmitted.
    """
    company = _company(db, company_id, ctx)
    draft = service.get_f24_draft(db, tenant_id=ctx.tenant_id, company=company,
                                  draft_id=draft_id)
    content, media_type, digest = service.export_f24(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        draft=draft, fmt=payload.format)
    db.commit()
    extension = "json" if payload.format == "json" else "csv"
    return Response(
        content=content, media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="f24-draft-{draft_id}.{extension}"',
            "X-Export-Fingerprint": digest,
            "X-Export-Disclaimer": "Bozza interna - non trasmissibile",
        })


# --- snapshot (cockpit / hub / AI tools) ------------------------------------

@router.get("/companies/{company_id}/snapshot")
def snapshot(
    company_id: uuid.UUID,
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("fiscal:read")),
):
    company = _company(db, company_id, ctx)
    return service.fiscal_snapshot(db, tenant_id=ctx.tenant_id,
                                   company_id=company.id, year=year)
