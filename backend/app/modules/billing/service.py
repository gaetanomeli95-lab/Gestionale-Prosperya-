"""Billing application service — provider-independent lifecycle.

Rules enforced here:
* fiscal number assigned only at finalize, transaction-safely;
* immutable snapshots of customer/issuer frozen at issue;
* send = persist intention (QUEUED + outbox) then async dispatch;
* unknown outcomes → TRANSMISSION_UNKNOWN, never blind retry;
* webhook ingestion is idempotent and order-tolerant;
* every meaningful step writes a transmission event + audit entry.
"""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.billing.models import (
    BillingProviderConfig,
    Invoice,
    InvoiceLine,
    InvoiceSequence,
    InvoiceTransmissionEvent,
    OutboxEvent,
    WebhookEventRecord,
)
from app.modules.billing.providers.base import ErrorCategory, ProviderResult
from app.modules.billing.providers.registry import get_active_provider
from app.modules.billing.statuses import (
    ALLOWED_TRANSITIONS,
    IMMUTABLE_STATUSES,
    RESUBMITTABLE_STATUSES,
    InvoiceStatus,
)
from app.modules.companies.models import Company
from app.shared.events import record_audit
from app.shared.mixins import utcnow

# ---------------------------------------------------------------------------
# Draft lifecycle
# ---------------------------------------------------------------------------

CUSTOMER_SNAPSHOT_FIELDS = (
    "legal_name", "vat_number", "tax_code", "legal_form",
    "address", "city", "postal_code", "region", "country",
    "pec", "email",
)


def _line_total(line: InvoiceLine) -> Decimal:
    gross = (line.quantity or Decimal(0)) * (line.unit_price or Decimal(0))
    if line.discount_percent:
        gross *= (Decimal(100) - line.discount_percent) / Decimal(100)
    return gross.quantize(Decimal("0.01"))


def _recalc_totals(invoice: Invoice) -> None:
    taxable = Decimal(0)
    vat = Decimal(0)
    for line in invoice.lines:
        lt = _line_total(line)
        line.line_total = lt
        taxable += lt
        vat += (lt * (line.vat_rate or Decimal(0)) / Decimal(100)).quantize(Decimal("0.01"))
    invoice.taxable_amount = taxable
    invoice.vat_amount = vat
    invoice.total_amount = taxable + vat + (invoice.stamp_duty or Decimal(0))


def get_invoice_or_404(db: Session, invoice_id: uuid.UUID, tenant_id) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None or inv.tenant_id != tenant_id or inv.deleted_at is not None:
        raise NotFoundError("Invoice not found.")
    return inv


def create_draft(db: Session, payload, actor_id: uuid.UUID, tenant_id) -> Invoice:
    company = db.get(Company, payload.company_id)
    if company is None or company.tenant_id != tenant_id or company.deleted_at is not None:
        raise ValidationError("The specified company does not exist.", code="invalid_company")
    if not payload.lines:
        raise ValidationError("An invoice needs at least one line.", code="invoice_no_lines")
    invoice = Invoice(
        company_id=company.id,
        series=payload.series or "",
        payment_terms=payload.payment_terms,
        payment_method=payload.payment_method,
        notes=payload.notes,
        source="manual",
        created_by_id=actor_id,
        tenant_id=tenant_id,
    )
    for i, line in enumerate(payload.lines):
        invoice.lines.append(InvoiceLine(position=i, **line.model_dump()))
    _recalc_totals(invoice)
    db.add(invoice)
    db.flush()
    _tx_event(db, invoice, "invoice.draft_created")
    record_audit(db, actor_id=actor_id, action="invoice.create",
                 entity_type="invoice", entity_id=invoice.id, tenant_id=tenant_id)
    return invoice


def update_draft(db: Session, invoice: Invoice, payload, actor_id: uuid.UUID) -> Invoice:
    if invoice.status in IMMUTABLE_STATUSES:
        raise ConflictError(
            "This invoice is no longer editable: it has reached a fiscal state. "
            "Corrections require a credit note or a controlled reissue.",
            code="invoice_immutable",
        )
    if payload.version != invoice.version:
        raise ConflictError(
            "This record was modified by someone else. Reload and try again.",
            code="stale_version",
        )
    data = payload.model_dump(exclude_unset=True, exclude={"version", "lines"})
    for k, v in data.items():
        setattr(invoice, k, v)
    if payload.lines is not None:
        if not payload.lines:
            raise ValidationError("An invoice needs at least one line.", code="invoice_no_lines")
        invoice.lines.clear()
        db.flush()
        for i, line in enumerate(payload.lines):
            invoice.lines.append(InvoiceLine(position=i, **line.model_dump()))
    _recalc_totals(invoice)
    invoice.version += 1
    record_audit(db, actor_id=actor_id, action="invoice.update",
                 entity_type="invoice", entity_id=invoice.id, tenant_id=invoice.tenant_id)
    return invoice


def finalize_invoice(db: Session, invoice: Invoice, actor_id: uuid.UUID,
                     issuer_snapshot: dict, issue_date: date | None = None) -> Invoice:
    """Assign the fiscal number (transaction-safe) and freeze snapshots."""
    if invoice.status != InvoiceStatus.DRAFT:
        raise ConflictError("Only a draft invoice can be finalized.", code="invalid_state")
    _validate_for_issue(invoice)

    year = (issue_date or datetime.now(UTC).date()).year
    seq = db.scalar(
        select(InvoiceSequence)
        .where(InvoiceSequence.tenant_id == invoice.tenant_id,
               InvoiceSequence.series == invoice.series,
               InvoiceSequence.fiscal_year == year)
        .with_for_update()
    )
    if seq is None:
        seq = InvoiceSequence(tenant_id=invoice.tenant_id, series=invoice.series,
                              fiscal_year=year, last_number=0)
        db.add(seq)
        db.flush()
    seq.last_number += 1

    company = db.get(Company, invoice.company_id)
    invoice.number = seq.last_number
    invoice.fiscal_year = year
    invoice.issue_date = issue_date or datetime.now(UTC).date()
    invoice.customer_snapshot = {
        f: getattr(company, f) for f in CUSTOMER_SNAPSHOT_FIELDS
    } | {"company_id": str(company.id)}
    invoice.issuer_snapshot = issuer_snapshot
    invoice.version += 1
    _transition(db, invoice, InvoiceStatus.READY_TO_SEND, "invoice.finalized")
    record_audit(db, actor_id=actor_id, action="invoice.finalize",
                 entity_type="invoice", entity_id=invoice.id,
                 tenant_id=invoice.tenant_id,
                 changes={"number": {"old": None, "new": invoice.number}})
    return invoice


def _validate_for_issue(invoice: Invoice) -> None:
    """Fail BEFORE transmission with an explicit, actionable message."""
    problems = []
    snap_fields = ("legal_name", "vat_number")
    if not invoice.lines:
        problems.append("the invoice has no lines")
    company_missing = [
        f for f in snap_fields if not getattr(invoice.company, f, None)
    ] if getattr(invoice, "company", None) else []
    for f in company_missing:
        problems.append(f"customer {f} is missing")
    if problems:
        raise ValidationError(
            "Invoice cannot be finalized: " + "; ".join(problems) + ".",
            code="invoice_validation",
            details={"problems": problems},
        )


# ---------------------------------------------------------------------------
# Send flow — persist intention, dispatch via outbox
# ---------------------------------------------------------------------------

def request_send(db: Session, invoice: Invoice, actor_id: uuid.UUID) -> Invoice:
    """Persist the send intention atomically: status + idempotency key +
    outbox row commit together — the external call happens later."""
    if invoice.status not in RESUBMITTABLE_STATUSES:
        raise ConflictError(
            f"An invoice in state '{invoice.status}' cannot be sent.",
            code="invalid_state",
        )
    if invoice.status == InvoiceStatus.REQUIRES_RECONCILIATION:
        raise ConflictError(
            "The outcome of the previous transmission is unknown. "
            "Reconcile the provider status before sending again.",
            code="requires_reconciliation",
        )
    if not invoice.submission_key:
        invoice.submission_key = uuid.uuid4().hex
    _transition(db, invoice, InvoiceStatus.QUEUED, "invoice.send_requested")
    db.add(OutboxEvent(
        tenant_id=invoice.tenant_id,
        event_type="billing.send_invoice",
        payload={"invoice_id": str(invoice.id), "submission_key": invoice.submission_key},
    ))
    record_audit(db, actor_id=actor_id, action="invoice.send_requested",
                 entity_type="invoice", entity_id=invoice.id, tenant_id=invoice.tenant_id)
    return invoice


def dispatch_pending_sends(db: Session, tenant_id=None, limit: int = 20) -> int:
    """Drain pending billing outbox events. Called by the dev endpoint now,
    by a real worker later — the domain doesn't care which. When tenant_id
    is given only that tenant's queue is drained."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == "pending",
               OutboxEvent.event_type == "billing.send_invoice")
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if tenant_id is not None:
        stmt = stmt.where(OutboxEvent.tenant_id == tenant_id)
    events = db.scalars(stmt).all()
    for event in events:
        event.attempts += 1
        try:
            _dispatch_send(db, uuid.UUID(event.payload["invoice_id"]),
                           event.payload["submission_key"], event.tenant_id)
            event.status = "done"
        except Exception as exc:  # noqa: BLE001 — the outbox must never lose the operation
            event.status = "failed"
            event.last_error = str(exc)[:500]
        event.processed_at = utcnow()
    return len(events)


def _dispatch_send(db: Session, invoice_id: uuid.UUID, submission_key: str,
                   tenant_id) -> None:
    invoice = get_invoice_or_404(db, invoice_id, tenant_id)
    config, provider = get_active_provider(db, tenant_id)

    problems = provider.validate_configuration()
    if problems:
        _transition(db, invoice, InvoiceStatus.READY_TO_SEND, "invoice.send_aborted")
        _tx_event(db, invoice, "provider.configuration_error",
                  provider=config, error=ErrorCategory.CONFIGURATION,
                  detail="; ".join(problems))
        return

    _transition(db, invoice, InvoiceStatus.TRANSMITTING, "invoice.transmitting")
    result = provider.submit_invoice(invoice, idempotency_key=submission_key)
    _apply_provider_result(db, invoice, result, provider=config)
    if result.ok:
        config.last_successful_send_at = utcnow()


def _apply_provider_result(db: Session, invoice: Invoice, result: ProviderResult,
                           provider: BillingProviderConfig | None = None) -> None:
    """Map a normalized provider result onto the invoice. The KEY safety
    property: an ambiguous outcome lands on TRANSMISSION_UNKNOWN and blocks
    resubmission until reconciled — blind retries can't duplicate."""
    if provider is not None:
        invoice.provider_key = provider.provider_key
        invoice.provider_api_version = provider.api_version
    if result.external_id:
        invoice.provider_external_id = result.external_id
    if result.provider_status:
        invoice.provider_status = result.provider_status
    if result.sdi_status:
        invoice.sdi_status = result.sdi_status
    if result.sdi_identifier:
        invoice.sdi_identifier = result.sdi_identifier

    if result.ok and result.normalized_status:
        _walk_to_status(db, invoice, result.normalized_status, provider,
                        result.provider_status)
        now = utcnow()
        if result.normalized_status == InvoiceStatus.DELIVERED:
            invoice.delivered_at = invoice.delivered_at or now
            invoice.sent_at = invoice.sent_at or now
        elif result.normalized_status == InvoiceStatus.REJECTED:
            invoice.rejected_at = now
        elif result.normalized_status in (InvoiceStatus.SENT_TO_PROVIDER,
                                          InvoiceStatus.SUBMITTED_TO_SDI):
            invoice.sent_at = invoice.sent_at or now
        return

    err = result.error
    category = err.category if err else ErrorCategory.TEMPORARY
    detail = err.technical_detail if err else None
    if category in (ErrorCategory.TIMEOUT, ErrorCategory.UNKNOWN_STATUS,
                    ErrorCategory.MALFORMED_RESPONSE):
        # outcome unknowable → safe state, no auto-retry
        _transition(db, invoice, InvoiceStatus.TRANSMISSION_UNKNOWN, "provider.unknown_outcome",
                    provider=provider, error=category, detail=detail)
    elif category == ErrorCategory.REJECTED:
        target = result.normalized_status or InvoiceStatus.REJECTED
        _transition(db, invoice, target, "provider.rejected",
                    provider=provider, error=category, detail=err.message if err else detail)
        invoice.rejected_at = utcnow()
    else:
        # auth/config/unavailable/rate-limit/temporary → back to ready, retryable
        _transition(db, invoice, InvoiceStatus.READY_TO_SEND, "provider.send_failed",
                    provider=provider, error=category, detail=detail)


def _path_to_target(current: InvoiceStatus, target: InvoiceStatus) -> list[InvoiceStatus] | None:
    """Shortest legal path through ALLOWED_TRANSITIONS (BFS)."""
    from collections import deque

    visited = {current}
    queue = deque([(current, [])])
    while queue:
        state, path = queue.popleft()
        for nxt in ALLOWED_TRANSITIONS.get(state, frozenset()):
            if nxt == target:
                return [*path, nxt]
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, [*path, nxt]))
    return None


def _walk_to_status(db: Session, invoice: Invoice, target: InvoiceStatus,
                    provider: BillingProviderConfig | None,
                    provider_status: str | None) -> None:
    path = _path_to_target(InvoiceStatus(invoice.status), target)
    if path is None:
        raise ConflictError(
            f"Illegal invoice transition {invoice.status} → {target}.",
            code="invalid_transition",
        )
    for step in path:
        _transition(db, invoice, step, "provider.status_update",
                    provider=provider, provider_status=provider_status)


def reconcile_invoice(db: Session, invoice: Invoice, actor_id: uuid.UUID | None) -> Invoice:
    """Ask the provider for the real status of an unresolved invoice.
    Falls back to the submission key when the provider's external id was
    lost with the response (e.g. timeout after provider-side processing)."""
    reference = invoice.provider_external_id or invoice.submission_key
    if not reference:
        raise ConflictError(
            "Nothing was transmitted for this invoice — nothing to reconcile.",
            code="nothing_to_reconcile",
        )
    _, provider = get_active_provider(db, invoice.tenant_id)
    result = provider.get_invoice_status(reference)
    if result.ok and result.normalized_status:
        _apply_provider_result(db, invoice, result)
        record_audit(db, actor_id=actor_id, action="invoice.reconciled",
                     entity_type="invoice", entity_id=invoice.id,
                     tenant_id=invoice.tenant_id,
                     changes={"status": {"new": invoice.status}})
    elif result.error and result.error.category == ErrorCategory.UNKNOWN_STATUS:
        _transition(db, invoice, InvoiceStatus.REQUIRES_RECONCILIATION,
                    "provider.status_unmapped", error=result.error.category,
                    detail=result.error.technical_detail)
    return invoice


# ---------------------------------------------------------------------------
# Webhooks — idempotent, order-tolerant ingestion
# ---------------------------------------------------------------------------

def ingest_webhook(db: Session, provider_key: str, headers: dict, body: bytes) -> str:
    """Verify → dedupe → store → apply. Returns a processing result string.

    Webhooks are unauthenticated: the tenant is identified by whichever
    per-tenant provider config verifies the signature/token."""
    import os

    from app.modules.billing.providers.registry import adapter_for

    configs = db.scalars(
        select(BillingProviderConfig).where(
            BillingProviderConfig.provider_key == provider_key,
            BillingProviderConfig.is_active.is_(True),
        )
    ).all()
    if not configs:
        raise NotFoundError("Unknown billing provider.", code="unknown_billing_provider")

    config = event = None
    for candidate in configs:
        cls = adapter_for(candidate.provider_key, candidate.api_version)
        credentials: dict = {}
        if candidate.webhook_secret_ref:
            credentials["webhook_token"] = os.environ.get(candidate.webhook_secret_ref, "")
        adapter = cls(config={"environment": candidate.environment, **(candidate.config or {})},
                      credentials=credentials)
        event = adapter.verify_webhook(headers, body)
        if event is not None:
            config = candidate
            break
    if event is None or config is None:
        raise ValidationError("Webhook verification failed.", code="webhook_unverified")

    record = WebhookEventRecord(
        tenant_id=config.tenant_id,
        provider_key=provider_key,
        provider_event_id=event.provider_event_id,
        payload=event.raw | {"provider_status": event.provider_status,
                             "external_id": event.external_id},
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return "duplicate_ignored"

    result = "stored_no_match"
    if event.external_id:
        invoice = db.scalar(
            select(Invoice).where(
                Invoice.tenant_id == config.tenant_id,
                Invoice.provider_external_id == event.external_id,
            )
        )
        if invoice is not None and event.normalized_status is not None:
            record.invoice_id = invoice.id
            try:
                _transition(db, invoice, event.normalized_status, "provider.webhook",
                            provider_status=event.provider_status,
                            provider_event_id=event.provider_event_id)
                if event.sdi_status:
                    invoice.sdi_status = event.sdi_status
                if event.provider_status:
                    invoice.provider_status = event.provider_status
                result = "applied"
            except ConflictError:
                # Out-of-order or already-terminal: keep the raw event,
                # don't corrupt the invoice state machine.
                result = "ignored_out_of_order"
    record.processed = True
    record.processing_result = result
    record.processed_at = utcnow()
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _transition(db: Session, invoice: Invoice, target: InvoiceStatus,
                event_type: str, provider: BillingProviderConfig | None = None,
                provider_status: str | None = None,
                provider_event_id: str | None = None,
                error: ErrorCategory | None = None, detail: str | None = None) -> None:
    allowed = ALLOWED_TRANSITIONS.get(InvoiceStatus(invoice.status), frozenset())
    if target not in allowed:
        raise ConflictError(
            f"Illegal invoice transition {invoice.status} → {target}.",
            code="invalid_transition",
        )
    _tx_event(db, invoice, event_type, provider=provider,
              from_status=InvoiceStatus(invoice.status), to_status=target,
              provider_status=provider_status, provider_event_id=provider_event_id,
              error=error, detail=detail)
    invoice.status = target
    invoice.version += 1


def _tx_event(db: Session, invoice: Invoice, event_type: str, *,
              provider: BillingProviderConfig | None = None,
              from_status: InvoiceStatus | str | None = None,
              to_status: InvoiceStatus | str | None = None,
              provider_status: str | None = None,
              provider_event_id: str | None = None,
              error: ErrorCategory | None = None,
              detail: str | None = None) -> None:
    db.add(InvoiceTransmissionEvent(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        event_type=event_type,
        provider_key=provider.provider_key if provider else invoice.provider_key,
        provider_api_version=provider.api_version if provider else invoice.provider_api_version,
        from_status=str(from_status) if from_status else None,
        to_status=str(to_status) if to_status else None,
        provider_status=provider_status,
        provider_event_id=provider_event_id,
        error_category=str(error) if error else None,
        detail=detail,
    ))


def health_check(db: Session, tenant_id) -> tuple[BillingProviderConfig | None, object]:
    config = db.scalar(
        select(BillingProviderConfig).where(
            BillingProviderConfig.tenant_id == tenant_id,
            BillingProviderConfig.is_active.is_(True),
        )
    )
    if config is None:
        return None, None
    _, provider = get_active_provider(db, tenant_id)
    health = provider.health_check()
    config.last_health_check_at = utcnow()
    config.last_health_status = str(health.status)
    return config, health
