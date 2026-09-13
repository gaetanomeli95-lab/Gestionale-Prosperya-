"""Billing API — provider-independent. Routers never see provider-specific
payloads; adapters normalize everything before it reaches the domain."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.billing import service
from app.modules.billing.models import (
    BillingProviderConfig,
    Invoice,
    InvoiceTransmissionEvent,
)
from app.modules.billing.providers.registry import available_providers
from app.modules.billing.schemas import (
    FinalizeRequest,
    InvoiceCreate,
    InvoiceDetail,
    InvoiceListItem,
    InvoiceUpdate,
    ProviderConfigIn,
    ProviderConfigOut,
    ProviderStatusOut,
    TransmissionEventOut,
)
from app.modules.billing.statuses import InvoiceStatus
from app.modules.users.models import User
from app.shared.events import record_audit
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/billing", tags=["billing"])


def _issuer_snapshot() -> dict:
    s = get_settings()
    return {
        "legal_name": s.billing_issuer_name,
        "vat_number": s.billing_issuer_vat,
        "tax_code": s.billing_issuer_tax_code,
        "address": s.billing_issuer_address,
        "city": s.billing_issuer_city,
        "postal_code": s.billing_issuer_postal_code,
        "country": s.billing_issuer_country,
        "pec": s.billing_issuer_pec,
    }


def _detail(invoice: Invoice) -> InvoiceDetail:
    return InvoiceDetail.model_validate(invoice)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@router.get("/invoices", response_model=Page[InvoiceListItem])
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    status: InvoiceStatus | None = None,
    company_id: UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("billing:read")),
):
    stmt = select(Invoice).where(Invoice.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Invoice.status == status)
    if company_id:
        stmt = stmt.where(Invoice.company_id == company_id)
    return paginate(
        db, stmt.order_by(Invoice.created_at.desc()),
        PageParams(page, page_size), InvoiceListItem,
    )


@router.post("/invoices", response_model=InvoiceDetail, status_code=201)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("billing:write")),
):
    invoice = service.create_draft(db, payload, actor.id)
    db.commit()
    return _detail(invoice)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("billing:read")),
):
    return _detail(service.get_invoice_or_404(db, invoice_id))


@router.patch("/invoices/{invoice_id}", response_model=InvoiceDetail)
def update_invoice(
    invoice_id: UUID,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("billing:write")),
):
    invoice = service.get_invoice_or_404(db, invoice_id)
    service.update_draft(db, invoice, payload, actor.id)
    db.commit()
    return _detail(invoice)


@router.post("/invoices/{invoice_id}/finalize", response_model=InvoiceDetail)
def finalize_invoice(
    invoice_id: UUID,
    payload: FinalizeRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("billing:submit")),
):
    invoice = service.get_invoice_or_404(db, invoice_id)
    service.finalize_invoice(db, invoice, actor.id, _issuer_snapshot(), payload.issue_date)
    db.commit()
    return _detail(invoice)


@router.post("/invoices/{invoice_id}/send", response_model=InvoiceDetail)
def send_invoice(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("billing:submit")),
):
    """Queues the submission — the provider call runs asynchronously."""
    invoice = service.get_invoice_or_404(db, invoice_id)
    service.request_send(db, invoice, actor.id)
    db.commit()
    return _detail(invoice)


@router.post("/invoices/{invoice_id}/reconcile", response_model=InvoiceDetail)
def reconcile_invoice(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("billing:submit")),
):
    invoice = service.get_invoice_or_404(db, invoice_id)
    service.reconcile_invoice(db, invoice, actor.id)
    db.commit()
    return _detail(invoice)


@router.get("/invoices/{invoice_id}/events", response_model=list[TransmissionEventOut])
def invoice_events(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("billing:read")),
):
    invoice = service.get_invoice_or_404(db, invoice_id)
    rows = db.scalars(
        select(InvoiceTransmissionEvent)
        .where(InvoiceTransmissionEvent.invoice_id == invoice.id)
        .order_by(InvoiceTransmissionEvent.created_at)
    ).all()
    return [TransmissionEventOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Provider configuration — admin only, secrets never leave the server
# ---------------------------------------------------------------------------

def _config_out(config: BillingProviderConfig) -> ProviderConfigOut:
    out = ProviderConfigOut.model_validate(config)
    out.credentials_configured = bool(config.credentials_ref)
    return out


@router.get("/provider", response_model=ProviderStatusOut)
def provider_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("billing:admin")),
):
    config = db.scalar(
        select(BillingProviderConfig).where(BillingProviderConfig.is_active.is_(True))
    )
    if config is None:
        return ProviderStatusOut(configured=False,
                                 available_providers=available_providers())
    return ProviderStatusOut(
        configured=True,
        provider=_config_out(config),
        health_status=config.last_health_status,
        available_providers=available_providers(),
    )


@router.put("/provider", response_model=ProviderConfigOut)
def configure_provider(
    payload: ProviderConfigIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("billing:admin")),
):
    """Activate a provider for NEW transactions only. Existing invoices keep
    their original provider_key/external_id — history is never rewritten."""
    from app.modules.billing.providers.registry import adapter_for

    adapter_for(payload.provider_key, payload.api_version)  # 404 if unregistered
    for row in db.scalars(select(BillingProviderConfig)):
        row.is_active = False
    config = BillingProviderConfig(**payload.model_dump(), is_active=True)
    db.add(config)
    db.flush()
    record_audit(db, actor_id=actor.id, action="billing.provider_changed",
                 entity_type="billing_provider_config", entity_id=config.id,
                 changes={"provider": {"new": f"{payload.provider_key}/{payload.api_version}"}})
    db.commit()
    return _config_out(config)


@router.post("/provider/test", response_model=ProviderStatusOut)
def test_provider_connection(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("billing:admin")),
):
    config, health = service.health_check(db)
    db.commit()
    if config is None:
        return ProviderStatusOut(configured=False,
                                 available_providers=available_providers())
    return ProviderStatusOut(
        configured=True,
        provider=_config_out(config),
        health_status=health.status,
        health_detail=health.detail,
        available_providers=available_providers(),
    )


# ---------------------------------------------------------------------------
# Webhooks + outbox dispatcher
# ---------------------------------------------------------------------------

@router.post("/webhooks/{provider_key}")
async def billing_webhook(
    provider_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Unauthenticated endpoint — the adapter verifies the event itself
    (signature/token per provider docs). Idempotent by provider_event_id."""
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    result = service.ingest_webhook(db, provider_key, headers, body)
    db.commit()
    return {"result": result}


@router.post("/jobs/dispatch")
def dispatch_jobs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("billing:admin")),
):
    """Dev/admin trigger for the outbox dispatcher. A scheduler/worker will
    call the same service function in production."""
    processed = service.dispatch_pending_sends(db)
    db.commit()
    return {"processed": processed}


# ---------------------------------------------------------------------------
# Operational overview widget
# ---------------------------------------------------------------------------

@router.get("/overview")
def billing_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("billing:read")),
):
    from sqlalchemy import func

    counts = dict(
        db.execute(
            select(Invoice.status, func.count(Invoice.id))
            .where(Invoice.deleted_at.is_(None))
            .group_by(Invoice.status)
        ).all()
    )
    return {
        "to_send": int(counts.get(InvoiceStatus.READY_TO_SEND, 0)),
        "awaiting_sdi": int(
            counts.get(InvoiceStatus.SENT_TO_PROVIDER, 0)
            + counts.get(InvoiceStatus.SUBMITTED_TO_SDI, 0)
            + counts.get(InvoiceStatus.QUEUED, 0)
            + counts.get(InvoiceStatus.TRANSMITTING, 0)
        ),
        "delivered": int(counts.get(InvoiceStatus.DELIVERED, 0))
        + int(counts.get(InvoiceStatus.ACCEPTED, 0)),
        "rejected": int(counts.get(InvoiceStatus.REJECTED, 0))
        + int(counts.get(InvoiceStatus.DELIVERY_FAILED, 0)),
        "requires_attention": int(counts.get(InvoiceStatus.TRANSMISSION_UNKNOWN, 0))
        + int(counts.get(InvoiceStatus.REQUIRES_RECONCILIATION, 0)),
    }
