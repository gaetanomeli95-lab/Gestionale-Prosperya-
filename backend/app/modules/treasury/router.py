"""Treasury API — scadenzario, conti bancari, riconciliazione, cassa.

Every figure is a decimal string or null; a missing value is never zero.
Routers only parse/authorize and delegate: no business logic lives here.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.treasury import schemas as s
from app.modules.treasury import service
from app.modules.treasury.models import AllocationMethod
from app.modules.users.models import User

router = APIRouter(prefix="/treasury", tags=["treasury"])


def _company(db: Session, company_id: uuid.UUID, ctx: TenantContext):
    return service.company_or_404(db, company_id, ctx.tenant_id)


# --- bank accounts --------------------------------------------------------

@router.get("/companies/{company_id}/accounts")
def list_accounts(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_accounts(db, tenant_id=ctx.tenant_id, company_id=company.id)


@router.post("/companies/{company_id}/accounts", status_code=201)
def create_account(
    company_id: uuid.UUID,
    payload: s.BankAccountCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    company = _company(db, company_id, ctx)
    result = service.create_account(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        label=payload.label, provider_key=payload.provider_key,
        provider_api_version=payload.provider_api_version,
        provider_account_id=payload.provider_account_id, bank_name=payload.bank_name,
        iban_last4=payload.iban_last4, credentials_ref=payload.credentials_ref,
        config=payload.config, opening_balance=payload.opening_balance,
        balance_date=payload.balance_date)
    db.commit()
    return result


@router.put("/companies/{company_id}/accounts/{account_id}/balance")
def update_balance(
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: s.BalanceUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    company = _company(db, company_id, ctx)
    result = service.set_balance(db, tenant_id=ctx.tenant_id, company=company,
                                 account_id=account_id, actor_id=actor.id,
                                 amount=payload.amount, balance_date=payload.balance_date)
    db.commit()
    return result


@router.get("/companies/{company_id}/accounts/{account_id}/connection")
def connection_status(
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    company = _company(db, company_id, ctx)
    return service.connection_status(db, tenant_id=ctx.tenant_id, company=company,
                                     account_id=account_id)


@router.post("/companies/{company_id}/accounts/{account_id}/sync", status_code=201)
def sync_account(
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: s.SyncRequest,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    """Pull movements + balance from the configured banking provider.

    Idempotent per `idempotency_key`: replaying a key returns the original
    batch instead of importing anything twice.
    """
    company = _company(db, company_id, ctx)
    default_from, default_to = service.default_sync_window()
    result = service.sync_account(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        account_id=account_id, date_from=payload.date_from or default_from,
        date_to=payload.date_to or default_to, idempotency_key=payload.idempotency_key)
    db.commit()
    return result


# --- bank transactions ----------------------------------------------------

@router.get("/companies/{company_id}/transactions")
def list_transactions(
    company_id: uuid.UUID,
    limit: int = Query(200, ge=1, le=1000),
    unreconciled_only: bool = Query(False),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_transactions(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                     limit=limit, unreconciled_only=unreconciled_only)


@router.post("/companies/{company_id}/transactions", status_code=201)
def create_transaction(
    company_id: uuid.UUID,
    payload: s.ManualTransaction,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    company = _company(db, company_id, ctx)
    result = service.record_manual_transaction(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        account_id=uuid.UUID(payload.bank_account_id),
        provider_tx_id=payload.provider_tx_id, value_date=payload.value_date,
        booking_date=payload.booking_date, amount=payload.amount,
        description=payload.description, counterparty_name=payload.counterparty_name)
    db.commit()
    return result


# --- open items -----------------------------------------------------------

@router.get("/companies/{company_id}/open-items")
def list_open_items(
    company_id: uuid.UUID,
    direction: str | None = Query(None, pattern="^(receivable|payable)$"),
    status: str | None = Query(
        None, pattern="^(open|partially_settled|settled|written_off|cancelled)$"),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    company = _company(db, company_id, ctx)
    return service.list_open_items(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                   direction=direction, status=status, limit=limit)


@router.post("/companies/{company_id}/open-items", status_code=201)
def create_open_item(
    company_id: uuid.UUID,
    payload: s.OpenItemCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    company = _company(db, company_id, ctx)
    result = service.create_open_item(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        direction=payload.direction, counterparty_name=payload.counterparty_name,
        due_date=payload.due_date, amount=payload.amount,
        counterparty_vat=payload.counterparty_vat,
        document_number=payload.document_number, document_date=payload.document_date,
        category=payload.category, notes=payload.notes, source_ref=payload.source_ref)
    db.commit()
    return result


@router.post("/companies/{company_id}/open-items/import", status_code=201)
def import_open_items(
    company_id: uuid.UUID,
    payload: s.OpenItemImport,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    """Atomic, idempotent scadenzario ingestion keyed by `source_ref`."""
    company = _company(db, company_id, ctx)
    result = service.import_open_items(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        rows=[row.model_dump() for row in payload.rows])
    db.commit()
    return result


@router.post("/companies/{company_id}/open-items/from-invoices", status_code=201)
def link_invoices(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write", "billing:read")),
):
    """Derive payables from the workspace invoices issued to this company."""
    company = _company(db, company_id, ctx)
    result = service.link_invoices(db, tenant_id=ctx.tenant_id, company=company,
                                   actor_id=actor.id)
    db.commit()
    return result


@router.post("/companies/{company_id}/open-items/{item_id}/close")
def close_open_item(
    company_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: s.CloseItemRequest,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    company = _company(db, company_id, ctx)
    result = service.close_open_item(db, tenant_id=ctx.tenant_id, company=company,
                                     actor_id=actor.id, item_id=item_id,
                                     method=payload.method, reason=payload.reason)
    db.commit()
    return result


# --- reconciliation -------------------------------------------------------

@router.get("/companies/{company_id}/reconciliation/suggestions")
def reconciliation_suggestions(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    """Deterministic level-1/level-2 proposals with their evidence.

    Nothing is applied here: this endpoint only computes.
    """
    company = _company(db, company_id, ctx)
    return service.suggestions(db, tenant_id=ctx.tenant_id, company_id=company.id)


@router.post("/companies/{company_id}/reconciliation/apply", status_code=201)
def apply_allocations(
    company_id: uuid.UUID,
    payload: s.ApplyAllocations,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    """Record the human decision that a movement settles one or more items."""
    company = _company(db, company_id, ctx)
    result = service.apply_allocations(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        bank_transaction_id=uuid.UUID(payload.bank_transaction_id),
        allocations=[a.model_dump() for a in payload.allocations],
        method=AllocationMethod(payload.method), confidence=payload.confidence,
        reason=payload.reason, evidence=payload.evidence)
    db.commit()
    return result


@router.post("/companies/{company_id}/reconciliation/auto-apply", status_code=201)
def auto_apply(
    company_id: uuid.UUID,
    payload: s.AutoApplyRequest,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("treasury:write")),
):
    """Apply *only* unambiguous level-1 exact matches, on operator request."""
    company = _company(db, company_id, ctx)
    result = service.auto_apply_exact(db, tenant_id=ctx.tenant_id, company=company,
                                      actor_id=actor.id, limit=payload.limit)
    db.commit()
    return result


# --- analytics ------------------------------------------------------------

@router.get("/companies/{company_id}/cash-position")
def cash_position(
    company_id: uuid.UUID,
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    company = _company(db, company_id, ctx)
    return service.cash_position(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                 as_of=as_of)


@router.get("/companies/{company_id}/cash-forecast")
def cash_forecast(
    company_id: uuid.UUID,
    horizon_days: int = Query(90, ge=1, le=365),
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    company = _company(db, company_id, ctx)
    return service.cash_forecast(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                 as_of=as_of, horizon_days=horizon_days)


@router.get("/companies/{company_id}/aging")
def aging(
    company_id: uuid.UUID,
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    company = _company(db, company_id, ctx)
    return service.aging(db, tenant_id=ctx.tenant_id, company_id=company.id, as_of=as_of)


@router.get("/companies/{company_id}/snapshot")
def snapshot(
    company_id: uuid.UUID,
    horizon_days: int = Query(90, ge=1, le=365),
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("treasury:read")),
):
    """Position + forecast + aging + deterministic warnings in one payload."""
    company = _company(db, company_id, ctx)
    return service.snapshot(db, tenant_id=ctx.tenant_id, company_id=company.id,
                            as_of=as_of, horizon_days=horizon_days)
