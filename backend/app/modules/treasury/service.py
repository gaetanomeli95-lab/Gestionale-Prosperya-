"""Treasury application service — scadenzario, banca, riconciliazione, cassa.

Scope convention (ADR-016): every row is keyed by `(tenant_id, company_id)`
where `company_id` is the **subject** company whose ledger we maintain — the
same key `management` uses, so the CFO cockpit can join the two without
duplicating master data.

Guarantees enforced here:

* tenant + company ownership re-checked on every read and write;
* bank sync is idempotent (`provider_tx_id` per account, `idempotency_key`
  per batch): re-running it can never duplicate a movement;
* open-item ingestion is idempotent (`source` + `source_ref`) and atomic;
  same content → skipped, different content for the same ref → 409;
* allocations can never over-allocate a movement or an item, and are
  append-only with actor, method, engine version and evidence;
* level-2 (fuzzy) pairings are never applied without an explicit human act.
"""
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.companies.models import Company
from app.modules.treasury import analytics, matching
from app.modules.treasury.models import (
    AllocationMethod,
    BankAccount,
    BankSyncBatch,
    BankTransaction,
    ConnectionStatus,
    ItemDirection,
    ItemSource,
    ItemStatus,
    OpenItem,
    ReconciliationAllocation,
)
from app.modules.treasury.providers.registry import (
    available_providers,
    provider_for_account,
)
from app.shared.events import record_activity, record_audit
from app.shared.mixins import today, utcnow
from app.shared.money import money, parse_money, parse_signed_money, total

FORMULA_VERSION = analytics.FORMULA_VERSION
ENGINE_VERSION = matching.ENGINE_VERSION

#: Allocation methods that actually settle money (as opposed to closing a row).
SETTLEMENT_METHODS = frozenset({
    AllocationMethod.EXACT, AllocationMethod.FUZZY, AllocationMethod.MANUAL,
})
CLOSURE_METHODS = frozenset({AllocationMethod.WRITE_OFF, AllocationMethod.CANCELLATION})
MAX_IMPORT_ROWS = 2000
MAX_SYNC_WINDOW_DAYS = 365
MAX_ALLOCATIONS_PER_CALL = 20

LIMITATIONS = [
    "Ingestione delle fatture attive/passive proprie dell'azienda (XML/SdI) non implementata: "
    "lo scadenzario arriva da import idempotente o inserimento manuale.",
    "Nessuna iniziazione di pagamenti: il modulo è in sola lettura sui conti (AIS).",
    "Le previsioni usano solo partite aperte datate e il saldo noto: nessun modello di ritardo o trend.",
]


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def company_or_404(db: Session, company_id: uuid.UUID, tenant_id) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id or company.deleted_at is not None:
        raise NotFoundError("Company not found.")
    return company


def _scoped(model, tenant_id, company_id):
    return select(model).where(model.tenant_id == tenant_id, model.company_id == company_id)


def _owned(db: Session, model, entity_id: uuid.UUID, tenant_id, company_id):
    row = db.get(model, entity_id)
    if (row is None or row.tenant_id != tenant_id or row.company_id != company_id):
        raise NotFoundError(f"{model.__name__} not found")
    return row


# ---------------------------------------------------------------------------
# Derived state — computed from allocations, never stored
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ItemState:
    settled: Decimal
    written_off: Decimal
    cancelled: bool
    residual: Decimal
    status: str


def item_state(item: OpenItem, allocations: list[ReconciliationAllocation]) -> ItemState:
    settled = total([a.amount for a in allocations if a.method in SETTLEMENT_METHODS]) or Decimal("0.00")
    written_off = total([a.amount for a in allocations
                         if a.method == AllocationMethod.WRITE_OFF]) or Decimal("0.00")
    cancelled = any(a.method == AllocationMethod.CANCELLATION for a in allocations)
    residual = Decimal("0.00") if cancelled else max(
        Decimal("0.00"), item.amount - settled - written_off)
    if cancelled:
        status = ItemStatus.CANCELLED
    elif residual == 0 and written_off > 0:
        status = ItemStatus.WRITTEN_OFF
    elif residual == 0:
        status = ItemStatus.SETTLED
    elif settled > 0 or written_off > 0:
        status = ItemStatus.PARTIALLY_SETTLED
    else:
        status = ItemStatus.OPEN
    return ItemState(settled, written_off, cancelled, residual, str(status))


def _allocations_by(db: Session, tenant_id, company_id) -> tuple[dict, dict]:
    """(by open_item_id, by bank_transaction_id) for the whole company."""
    rows = db.scalars(_scoped(ReconciliationAllocation, tenant_id, company_id)).all()
    by_item: dict[uuid.UUID, list] = {}
    by_tx: dict[uuid.UUID, list] = {}
    for row in rows:
        by_item.setdefault(row.open_item_id, []).append(row)
        if row.bank_transaction_id is not None:
            by_tx.setdefault(row.bank_transaction_id, []).append(row)
    return by_item, by_tx


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC).replace(tzinfo=None)


def _created_key(row) -> tuple[int, datetime]:
    """Sortable timestamp across dialects.

    PostgreSQL returns timezone-aware values, SQLite naive ones, and rows just
    created in-session carry the aware Python default — comparing them raw
    raises. Normalising to naive UTC keeps ordering stable everywhere.
    """
    value = getattr(row, "created_at", None)
    if value is None:
        return (1, _EPOCH)
    return (0, value.replace(tzinfo=None) if value.tzinfo is not None else value)


def tx_unallocated(tx: BankTransaction, allocations: list[ReconciliationAllocation]) -> Decimal:
    """Signed residual of a movement (same sign as the movement itself)."""
    allocated = total([a.amount for a in allocations]) or Decimal("0.00")
    magnitude = max(Decimal("0.00"), tx.amount.copy_abs() - allocated)
    return magnitude if tx.amount > 0 else -magnitude


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def account_data(account: BankAccount) -> dict:
    capabilities = provider_for_account(account).capabilities
    return {
        "id": str(account.id), "label": account.label, "bank_name": account.bank_name,
        "iban_last4": account.iban_last4, "currency": account.currency,
        "provider_key": account.provider_key,
        "provider_api_version": account.provider_api_version,
        "provider_account_id": account.provider_account_id,
        "is_real_institution": capabilities.is_real_institution,
        "supports_transactions": capabilities.supports_transactions,
        "credentials_configured": bool(account.credentials_ref),
        "connection_status": account.connection_status,
        "connection_expires_at": (account.connection_expires_at.isoformat()
                                  if account.connection_expires_at else None),
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
        "last_sync_error": account.last_sync_error,
        "balance": money(account.balance_amount),
        "balance_date": account.balance_date.isoformat() if account.balance_date else None,
        "balance_source": account.balance_source,
        "is_active": account.is_active,
    }


def transaction_data(tx: BankTransaction, allocations: list[ReconciliationAllocation]) -> dict:
    unallocated = tx_unallocated(tx, allocations)
    return {
        "id": str(tx.id), "bank_account_id": str(tx.bank_account_id),
        "provider_tx_id": tx.provider_tx_id,
        "booking_date": tx.booking_date.isoformat(), "value_date": tx.value_date.isoformat(),
        "amount": money(tx.amount), "currency": tx.currency,
        "counterparty_name": tx.counterparty_name,
        "counterparty_iban_last4": tx.counterparty_iban_last4,
        "description": tx.description, "source": tx.source,
        "allocated": money(total([a.amount for a in allocations]) or Decimal("0.00")),
        "unallocated": money(unallocated),
        "is_reconciled": unallocated == 0,
        "allocations": [{
            "id": str(a.id), "open_item_id": str(a.open_item_id),
            "amount": money(a.amount), "method": a.method,
            "confidence": str(a.confidence) if a.confidence is not None else None,
            "engine_version": a.engine_version, "reason": a.reason,
            "approved_by_id": str(a.approved_by_id) if a.approved_by_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a in sorted(allocations, key=_created_key)],
    }


def open_item_data(item: OpenItem, allocations: list[ReconciliationAllocation],
                   *, as_of: date) -> dict:
    state = item_state(item, allocations)
    return {
        "id": str(item.id), "direction": item.direction,
        "counterparty_name": item.counterparty_name,
        "counterparty_vat": item.counterparty_vat,
        "document_number": item.document_number,
        "document_date": item.document_date.isoformat() if item.document_date else None,
        "due_date": item.due_date.isoformat(),
        "amount": money(item.amount), "currency": item.currency,
        "settled": money(state.settled), "written_off": money(state.written_off),
        "residual": money(state.residual), "status": state.status,
        "days_overdue": max(0, (as_of - item.due_date).days) if state.residual > 0 else 0,
        "is_overdue": state.residual > 0 and item.due_date < as_of,
        "category": item.category,
        "source": item.source, "source_ref": item.source_ref,
        "invoice_id": str(item.invoice_id) if item.invoice_id else None,
        "notes": item.notes,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "allocations": [{
            "id": str(a.id), "amount": money(a.amount), "method": a.method,
            "bank_transaction_id": str(a.bank_transaction_id) if a.bank_transaction_id else None,
            "confidence": str(a.confidence) if a.confidence is not None else None,
            "reason": a.reason, "engine_version": a.engine_version,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a in sorted(allocations, key=_created_key)],
    }


# ---------------------------------------------------------------------------
# Bank accounts
# ---------------------------------------------------------------------------

def list_accounts(db: Session, *, tenant_id, company_id) -> dict:
    rows = db.scalars(
        _scoped(BankAccount, tenant_id, company_id).order_by(BankAccount.label)
    ).all()
    return {
        "accounts": [account_data(a) for a in rows],
        "available_providers": available_providers(),
        "limitations": LIMITATIONS,
    }


def create_account(db: Session, *, tenant_id, company: Company, actor_id,
                   label: str, provider_key: str, provider_api_version: str,
                   provider_account_id: str, bank_name: str | None = None,
                   iban_last4: str | None = None, credentials_ref: str | None = None,
                   config: dict | None = None, opening_balance: str | None = None,
                   balance_date: date | None = None) -> dict:
    balance = parse_signed_money(opening_balance, allow_zero=True) if opening_balance is not None else None
    if balance is not None and balance_date is None:
        raise ValidationError("Indicare la data del saldo: un saldo senza data non è verificabile.",
                              code="balance_date_required")
    account = BankAccount(
        tenant_id=tenant_id, company_id=company.id, label=label, bank_name=bank_name,
        iban_last4=iban_last4, provider_key=provider_key,
        provider_api_version=provider_api_version,
        provider_account_id=provider_account_id, credentials_ref=credentials_ref,
        config=config or {}, balance_amount=balance, balance_date=balance_date,
        balance_source="manual", created_by_id=actor_id,
        connection_status=ConnectionStatus.NOT_CONNECTED,
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Conto già presente per questo provider e identificativo.",
                            code="bank_account_exists") from exc
    provider = provider_for_account(account)
    if problems := provider.validate_configuration():
        raise ValidationError(problems[0], code="bank_provider_misconfigured")
    record_audit(db, actor_id=actor_id, action="treasury.account.create",
                 entity_type="bank_account", entity_id=account.id, tenant_id=tenant_id,
                 changes={"label": label, "provider_key": provider_key,
                          "company_id": str(company.id)})
    return account_data(account)


def set_balance(db: Session, *, tenant_id, company: Company, account_id: uuid.UUID,
                actor_id, amount: str, balance_date: date) -> dict:
    account = _owned(db, BankAccount, account_id, tenant_id, company.id)
    before = {"balance": money(account.balance_amount),
              "balance_date": account.balance_date.isoformat() if account.balance_date else None}
    account.balance_amount = parse_signed_money(amount, allow_zero=True)
    account.balance_date = balance_date
    account.balance_source = "manual"
    db.flush()
    record_audit(db, actor_id=actor_id, action="treasury.account.balance",
                 entity_type="bank_account", entity_id=account.id, tenant_id=tenant_id,
                 changes={"before": before, "after": {"balance": money(account.balance_amount),
                                                      "balance_date": balance_date.isoformat()}})
    return account_data(account)


def connection_status(db: Session, *, tenant_id, company: Company,
                      account_id: uuid.UUID) -> dict:
    account = _owned(db, BankAccount, account_id, tenant_id, company.id)
    provider = provider_for_account(account)
    result = provider.connection_status()
    return {
        "account_id": str(account.id),
        "ok": result.ok,
        "status": result.connection.status if result.connection else account.connection_status,
        "detail": result.connection.detail if result.connection else None,
        "environment": result.connection.environment if result.connection else None,
        "is_real_institution": provider.capabilities.is_real_institution,
        "error": {"category": result.error.category, "message": result.error.message}
        if result.error else None,
    }


def sync_account(db: Session, *, tenant_id, company: Company, account_id: uuid.UUID,
                 actor_id, date_from: date, date_to: date, idempotency_key: str) -> dict:
    """Pull balances + movements from the configured provider, idempotently."""
    account = _owned(db, BankAccount, account_id, tenant_id, company.id)
    if date_to < date_from:
        raise ValidationError("Finestra temporale non valida.", code="invalid_window")
    if (date_to - date_from).days > MAX_SYNC_WINDOW_DAYS:
        raise ValidationError(f"Finestra massima {MAX_SYNC_WINDOW_DAYS} giorni.",
                              code="window_too_large")
    prior = db.scalar(
        _scoped(BankSyncBatch, tenant_id, company.id)
        .where(BankSyncBatch.idempotency_key == idempotency_key)
    )
    if prior is not None:
        return {**sync_batch_data(prior), "replayed": True}

    provider = provider_for_account(account)
    if not provider.capabilities.supports_transactions:
        raise ConflictError(
            "Il provider configurato non fornisce movimenti: registrare i movimenti "
            "manualmente o via import.", code="provider_no_transactions")

    result = provider.refresh_transactions(account.provider_account_id,
                                           date_from=date_from, date_to=date_to)
    if not result.ok:
        account.last_sync_error = result.error.message if result.error else "Errore non classificato."
        account.connection_status = (
            ConnectionStatus.EXPIRED if result.error and result.error.category == "consent_expired"
            else ConnectionStatus.ERROR)
        batch = BankSyncBatch(
            tenant_id=tenant_id, company_id=company.id, bank_account_id=account.id,
            idempotency_key=idempotency_key, provider_key=account.provider_key,
            provider_api_version=account.provider_api_version,
            environment=provider.environment, window_start=date_from, window_end=date_to,
            status="error", detail=account.last_sync_error, actor_id=actor_id,
        )
        db.add(batch)
        db.flush()
        record_audit(db, actor_id=actor_id, action="treasury.sync.error",
                     entity_type="bank_account", entity_id=account.id, tenant_id=tenant_id,
                     changes={"detail": account.last_sync_error})
        return {**sync_batch_data(batch), "replayed": False,
                "error": account.last_sync_error}

    existing = {
        row.provider_tx_id for row in db.scalars(
            _scoped(BankTransaction, tenant_id, company.id)
            .where(BankTransaction.bank_account_id == account.id)
        ).all()
    }
    # The batch id is generated up front so movements can be tagged with it,
    # while the batch row itself is written exactly once with final counters:
    # `bank_sync_batches` is append-only and must never be UPDATEd.
    batch_id = uuid.uuid4()
    inserted = 0
    try:
        with db.begin_nested():
            for row in result.transactions:
                if row.provider_tx_id in existing:
                    continue
                db.add(BankTransaction(
                    tenant_id=tenant_id, company_id=company.id, bank_account_id=account.id,
                    provider_tx_id=row.provider_tx_id, booking_date=row.booking_date,
                    value_date=row.value_date, amount=row.amount.quantize(Decimal("0.01")),
                    currency=row.currency, counterparty_name=row.counterparty_name,
                    counterparty_iban_last4=row.counterparty_iban_last4,
                    description=row.description[:600],
                    source=f"{account.provider_key}/{account.provider_api_version}",
                    sync_batch_id=batch_id,
                ))
                existing.add(row.provider_tx_id)
                inserted += 1
            batch = BankSyncBatch(
                id=batch_id, tenant_id=tenant_id, company_id=company.id,
                bank_account_id=account.id, idempotency_key=idempotency_key,
                provider_key=account.provider_key,
                provider_api_version=account.provider_api_version,
                environment=provider.environment, window_start=date_from,
                window_end=date_to, fetched_count=len(result.transactions),
                inserted_count=inserted,
                duplicate_count=len(result.transactions) - inserted,
                status="ok", actor_id=actor_id,
            )
            db.add(batch)
            db.flush()
    except IntegrityError as exc:
        concurrent = db.scalar(
            _scoped(BankSyncBatch, tenant_id, company.id)
            .where(BankSyncBatch.idempotency_key == idempotency_key)
        )
        if concurrent is not None:
            return {**sync_batch_data(concurrent), "replayed": True}
        raise ConflictError("Sync concorrente: ripetere con la stessa chiave di idempotenza.",
                            code="sync_conflict") from exc

    balances = provider.get_balances(account.provider_account_id)
    if balances.ok and balances.balances:
        latest = balances.balances[0]
        account.balance_amount = latest.amount.quantize(Decimal("0.01"))
        account.balance_date = latest.balance_date
        account.balance_source = "provider"
    account.last_sync_at = utcnow()
    account.last_sync_error = None
    account.connection_status = ConnectionStatus.ACTIVE
    db.flush()
    record_audit(db, actor_id=actor_id, action="treasury.sync",
                 entity_type="bank_account", entity_id=account.id, tenant_id=tenant_id,
                 changes=sync_batch_data(batch))
    return {**sync_batch_data(batch), "replayed": False,
            "balance": money(account.balance_amount),
            "balance_date": account.balance_date.isoformat() if account.balance_date else None}


def sync_batch_data(batch: BankSyncBatch) -> dict:
    return {
        "id": str(batch.id), "bank_account_id": str(batch.bank_account_id),
        "idempotency_key": batch.idempotency_key, "provider_key": batch.provider_key,
        "provider_api_version": batch.provider_api_version,
        "environment": batch.environment,
        "window_start": batch.window_start.isoformat() if batch.window_start else None,
        "window_end": batch.window_end.isoformat() if batch.window_end else None,
        "fetched_count": batch.fetched_count, "inserted_count": batch.inserted_count,
        "duplicate_count": batch.duplicate_count, "status": batch.status,
        "detail": batch.detail,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
    }


def record_manual_transaction(db: Session, *, tenant_id, company: Company, actor_id,
                              account_id: uuid.UUID, provider_tx_id: str,
                              value_date: date, amount: str, description: str = "",
                              counterparty_name: str | None = None,
                              booking_date: date | None = None) -> dict:
    """Hand-entered movement (or file import). Immutable once written."""
    account = _owned(db, BankAccount, account_id, tenant_id, company.id)
    signed = parse_signed_money(amount)
    tx = BankTransaction(
        tenant_id=tenant_id, company_id=company.id, bank_account_id=account.id,
        provider_tx_id=provider_tx_id, booking_date=booking_date or value_date,
        value_date=value_date, amount=signed, currency="EUR",
        counterparty_name=counterparty_name, description=description[:600],
        source="manual",
    )
    db.add(tx)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Movimento già registrato con lo stesso identificativo.",
                            code="transaction_exists") from exc
    record_audit(db, actor_id=actor_id, action="treasury.transaction.manual",
                 entity_type="bank_transaction", entity_id=tx.id, tenant_id=tenant_id,
                 changes={"amount": money(signed), "value_date": value_date.isoformat()})
    return transaction_data(tx, [])


def list_transactions(db: Session, *, tenant_id, company_id, limit: int = 200,
                      unreconciled_only: bool = False) -> dict:
    _, by_tx = _allocations_by(db, tenant_id, company_id)
    rows = db.scalars(
        _scoped(BankTransaction, tenant_id, company_id)
        .order_by(BankTransaction.value_date.desc(), BankTransaction.id)
    ).all()
    items = [transaction_data(tx, by_tx.get(tx.id, [])) for tx in rows]
    if unreconciled_only:
        items = [i for i in items if not i["is_reconciled"]]
    return {
        "transactions": items[:limit],
        "counters": {
            "total": len(rows),
            "returned": min(len(items), limit),
            "unreconciled": sum(1 for i in items if not i["is_reconciled"]),
        },
        "formula_version": FORMULA_VERSION,
    }


# ---------------------------------------------------------------------------
# Open items (scadenzario)
# ---------------------------------------------------------------------------

def _item_fingerprint(direction: str, counterparty: str, due: date,
                      amount: Decimal, document: str | None) -> str:
    canonical = json.dumps([direction, counterparty, due.isoformat(), money(amount), document],
                           ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_open_item(db: Session, *, tenant_id, company: Company, actor_id,
                     direction: str, counterparty_name: str, due_date: date,
                     amount: str, source: str = ItemSource.MANUAL,
                     source_ref: str | None = None,
                     counterparty_vat: str | None = None,
                     document_number: str | None = None,
                     document_date: date | None = None,
                     category: str | None = None, notes: str | None = None,
                     invoice_id: uuid.UUID | None = None) -> dict:
    if direction not in tuple(ItemDirection):
        raise ValidationError("Direzione partita non valida.", code="invalid_direction")
    parsed = parse_money(amount)
    ref = source_ref or f"manual:{_item_fingerprint(direction, counterparty_name, due_date, parsed, document_number)[:32]}"
    prior = db.scalar(
        _scoped(OpenItem, tenant_id, company.id)
        .where(OpenItem.source == source, OpenItem.source_ref == ref)
    )
    if prior is not None:
        if (prior.amount != parsed or prior.due_date != due_date
                or prior.direction != direction):
            raise ConflictError(
                "Riferimento già presente con contenuto diverso: correggere con una "
                "nuova partita e chiudere quella errata (annullamento tracciato).",
                code="open_item_conflict")
        return {**open_item_data(prior, prior.allocations, as_of=today()), "replayed": True}
    item = OpenItem(
        tenant_id=tenant_id, company_id=company.id, direction=direction,
        counterparty_name=counterparty_name, counterparty_vat=counterparty_vat,
        document_number=document_number, document_date=document_date,
        due_date=due_date, amount=parsed, currency="EUR", category=category,
        source=source, source_ref=ref, invoice_id=invoice_id, notes=notes,
        created_by_id=actor_id,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Partita già presente.", code="open_item_exists") from exc
    record_audit(db, actor_id=actor_id, action="treasury.open_item.create",
                 entity_type="open_item", entity_id=item.id, tenant_id=tenant_id,
                 changes={"direction": direction, "amount": money(parsed),
                          "due_date": due_date.isoformat(), "source": source,
                          "source_ref": ref})
    return {**open_item_data(item, [], as_of=today()), "replayed": False}


def import_open_items(db: Session, *, tenant_id, company: Company, actor_id,
                      rows: list[dict], source: str = ItemSource.IMPORT) -> dict:
    """Bulk, atomic, idempotent ingestion of a scadenzario.

    Each row needs a stable `source_ref`; rows already present with identical
    content are skipped, different content for the same ref aborts the batch.
    """
    if not rows:
        raise ValidationError("Nessuna riga da importare.", code="empty_import")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValidationError(f"Import oltre il limite di {MAX_IMPORT_ROWS} righe.",
                              code="import_too_large")
    refs = [str(r.get("source_ref") or "") for r in rows]
    if any(not ref for ref in refs):
        raise ValidationError("Ogni riga richiede source_ref per l'idempotenza.",
                              code="missing_source_ref")
    if len(set(refs)) != len(refs):
        raise ValidationError("source_ref duplicato nel file.", code="duplicate_source_ref")

    existing = {
        row.source_ref: row for row in db.scalars(
            _scoped(OpenItem, tenant_id, company.id)
            .where(OpenItem.source == source, OpenItem.source_ref.in_(refs))
        ).all()
    }
    created, skipped = 0, 0
    with db.begin_nested():
        for index, raw in enumerate(rows, start=1):
            try:
                direction = str(raw["direction"])
                counterparty = str(raw["counterparty_name"]).strip()
                due = date.fromisoformat(str(raw["due_date"]))
                amount = parse_money(str(raw["amount"]))
            except (KeyError, ValueError) as exc:
                raise ValidationError(f"Riga {index}: {exc}", code="invalid_import_row") from exc
            if direction not in tuple(ItemDirection):
                raise ValidationError(f"Riga {index}: direzione non valida.",
                                      code="invalid_direction")
            if not counterparty or len(counterparty) > 300:
                raise ValidationError(f"Riga {index}: controparte mancante o troppo lunga.",
                                      code="invalid_counterparty")
            if not 2000 <= due.year <= 2100:
                raise ValidationError(f"Riga {index}: scadenza fuori intervallo.",
                                      code="invalid_due_date")
            ref = str(raw["source_ref"])
            prior = existing.get(ref)
            if prior is not None:
                if (prior.amount != amount or prior.due_date != due
                        or prior.direction != direction):
                    raise ConflictError(
                        f"Riga {index}: riferimento {ref} già presente con contenuto diverso.",
                        code="open_item_conflict")
                skipped += 1
                continue
            document_date = raw.get("document_date")
            db.add(OpenItem(
                tenant_id=tenant_id, company_id=company.id, direction=direction,
                counterparty_name=counterparty,
                counterparty_vat=(str(raw["counterparty_vat"])[:32]
                                  if raw.get("counterparty_vat") else None),
                document_number=(str(raw["document_number"])[:80]
                                 if raw.get("document_number") else None),
                document_date=date.fromisoformat(str(document_date)) if document_date else None,
                due_date=due, amount=amount, currency="EUR",
                category=str(raw["category"])[:120] if raw.get("category") else None,
                source=source, source_ref=ref, created_by_id=actor_id,
                notes=str(raw["notes"])[:2000] if raw.get("notes") else None,
            ))
            created += 1
        db.flush()
    payload = {"created": created, "skipped": skipped, "received": len(rows), "source": source}
    record_audit(db, actor_id=actor_id, action="treasury.open_item.import",
                 entity_type="company", entity_id=company.id, tenant_id=tenant_id,
                 changes=payload)
    return payload


def link_invoices(db: Session, *, tenant_id, company: Company, actor_id) -> dict:
    """Create payables from the workspace's own invoices issued to this company.

    Direction is `payable` on purpose: from the subject company's ledger, an
    invoice it *received* is something it owes. Invoices without a due date are
    reported as skipped — a missing date is never invented.
    """
    from app.modules.billing import service as billing

    invoices = billing.list_settleable(db, tenant_id=tenant_id, company_id=company.id)
    created, skipped_no_due, skipped_existing, skipped_no_total = 0, [], 0, []
    for invoice in invoices:
        if invoice["total_amount"] is None:
            skipped_no_total.append(invoice["id"])
            continue
        if invoice["due_date"] is None:
            skipped_no_due.append(invoice["id"])
            continue
        ref = f"invoice:{invoice['id']}"
        prior = db.scalar(
            _scoped(OpenItem, tenant_id, company.id)
            .where(OpenItem.source == ItemSource.INVOICE, OpenItem.source_ref == ref)
        )
        if prior is not None:
            skipped_existing += 1
            continue
        issuer = invoice.get("customer_name")  # snapshot of the invoiced party
        db.add(OpenItem(
            tenant_id=tenant_id, company_id=company.id,
            direction=ItemDirection.PAYABLE,
            counterparty_name=(issuer or "Emittente piattaforma")[:300],
            counterparty_vat=invoice.get("customer_vat"),
            document_number=invoice["document_number"],
            document_date=date.fromisoformat(invoice["issue_date"]) if invoice["issue_date"] else None,
            due_date=date.fromisoformat(invoice["due_date"]),
            amount=parse_money(str(Decimal(invoice["total_amount"]).quantize(Decimal("0.01")))),
            currency="EUR", source=ItemSource.INVOICE, source_ref=ref,
            invoice_id=uuid.UUID(invoice["id"]), created_by_id=actor_id,
        ))
        created += 1
    db.flush()
    result = {
        "created": created, "already_present": skipped_existing,
        "skipped_without_due_date": skipped_no_due,
        "skipped_without_total": skipped_no_total,
        "considered": len(invoices),
        "note": ("Le fatture senza data di scadenza non generano partite: la scadenza "
                 "non viene inventata."),
    }
    if created:
        record_audit(db, actor_id=actor_id, action="treasury.open_item.from_invoices",
                     entity_type="company", entity_id=company.id, tenant_id=tenant_id,
                     changes=result)
    return result


def list_open_items(db: Session, *, tenant_id, company_id, as_of: date | None = None,
                    direction: str | None = None, status: str | None = None,
                    limit: int = 500) -> dict:
    as_of = as_of or today()
    by_item, _ = _allocations_by(db, tenant_id, company_id)
    stmt = _scoped(OpenItem, tenant_id, company_id)
    if direction is not None:
        stmt = stmt.where(OpenItem.direction == direction)
    rows = db.scalars(stmt.order_by(OpenItem.due_date, OpenItem.id)).all()
    items = [open_item_data(item, by_item.get(item.id, []), as_of=as_of) for item in rows]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return {
        "as_of": as_of.isoformat(), "items": items[:limit],
        "counters": {
            "total": len(rows), "returned": min(len(items), limit),
            "open": sum(1 for i in items if i["status"] in
                        (ItemStatus.OPEN, ItemStatus.PARTIALLY_SETTLED)),
            "overdue": sum(1 for i in items if i["is_overdue"]),
        },
        "formula": analytics.FORMULAS["open_residual"],
        "formula_version": FORMULA_VERSION,
    }


def close_open_item(db: Session, *, tenant_id, company: Company, actor_id,
                    item_id: uuid.UUID, method: str, reason: str) -> dict:
    """Close a residual without a bank movement: write-off or cancellation.

    Both are audited human decisions with a mandatory reason — the item row
    itself is never edited or deleted.
    """
    if method not in CLOSURE_METHODS:
        raise ValidationError("Metodo di chiusura non valido.", code="invalid_closure")
    if not reason or len(reason.strip()) < 5:
        raise ValidationError("Motivazione obbligatoria per la chiusura della partita.",
                              code="reason_required")
    item = _owned(db, OpenItem, item_id, tenant_id, company.id)
    allocations = list(item.allocations)
    state = item_state(item, allocations)
    if state.residual <= 0:
        raise ConflictError("La partita non ha residuo da chiudere.", code="no_residual")
    allocation = ReconciliationAllocation(
        tenant_id=tenant_id, company_id=company.id, open_item_id=item.id,
        bank_transaction_id=None, amount=state.residual, method=method,
        confidence=None, engine_version=None,
        evidence={"residual_before": money(state.residual),
                  "rule": "chiusura manuale senza movimento bancario"},
        reason=reason.strip()[:300], actor_id=actor_id, approved_by_id=actor_id,
        approved_at=utcnow(),
    )
    db.add(allocation)
    db.flush()
    record_audit(db, actor_id=actor_id, action=f"treasury.open_item.{method}",
                 entity_type="open_item", entity_id=item.id, tenant_id=tenant_id,
                 changes={"amount": money(state.residual), "reason": reason.strip()[:300]})
    return open_item_data(item, [*allocations, allocation], as_of=today())


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def _engine_views(db: Session, tenant_id, company_id) -> tuple[list, list, dict, dict]:
    by_item, by_tx = _allocations_by(db, tenant_id, company_id)
    txs = db.scalars(
        _scoped(BankTransaction, tenant_id, company_id)
        .order_by(BankTransaction.value_date, BankTransaction.id)
    ).all()
    items = db.scalars(
        _scoped(OpenItem, tenant_id, company_id).order_by(OpenItem.due_date, OpenItem.id)
    ).all()
    tx_views, item_views = [], []
    for tx in txs:
        unallocated = tx_unallocated(tx, by_tx.get(tx.id, []))
        if unallocated == 0:
            continue
        tx_views.append(matching.TxView(
            id=str(tx.id), value_date=tx.value_date, booking_date=tx.booking_date,
            amount=tx.amount, unallocated=unallocated, description=tx.description,
            counterparty_name=tx.counterparty_name,
        ))
    for item in items:
        state = item_state(item, by_item.get(item.id, []))
        if state.residual <= 0:
            continue
        item_views.append(matching.ItemView(
            id=str(item.id), direction=item.direction,
            counterparty_name=item.counterparty_name, due_date=item.due_date,
            amount=item.amount, residual=state.residual,
            document_number=item.document_number, counterparty_vat=item.counterparty_vat,
            document_date=item.document_date,
        ))
    return tx_views, item_views, by_item, by_tx


def suggestions(db: Session, *, tenant_id, company_id) -> dict:
    tx_views, item_views, _, _ = _engine_views(db, tenant_id, company_id)
    result = matching.suggest(tx_views, item_views)
    result["open_items"] = [{
        "id": v.id, "direction": v.direction, "counterparty_name": v.counterparty_name,
        "document_number": v.document_number, "due_date": v.due_date.isoformat(),
        "residual": money(v.residual),
    } for v in item_views]
    result["approval_policy"] = (
        "I match di livello 1 (esatti e non ambigui) possono essere applicati in blocco "
        "da un operatore; i match di livello 2 richiedono approvazione puntuale. "
        "Nessun abbinamento viene applicato automaticamente dal sistema."
    )
    return result


def apply_allocations(db: Session, *, tenant_id, company: Company, actor_id,
                      bank_transaction_id: uuid.UUID, allocations: list[dict],
                      method: str = AllocationMethod.MANUAL,
                      confidence: str | None = None, reason: str | None = None,
                      evidence: dict | None = None) -> dict:
    """Apply one or more allocations of a movement to open items (human act)."""
    if method not in SETTLEMENT_METHODS:
        raise ValidationError("Metodo di allocazione non valido per un movimento bancario.",
                              code="invalid_method")
    if not allocations:
        raise ValidationError("Nessuna allocazione richiesta.", code="empty_allocation")
    if len(allocations) > MAX_ALLOCATIONS_PER_CALL:
        raise ValidationError(f"Massimo {MAX_ALLOCATIONS_PER_CALL} allocazioni per chiamata.",
                              code="too_many_allocations")
    tx = _owned(db, BankTransaction, bank_transaction_id, tenant_id, company.id)
    by_item, by_tx = _allocations_by(db, tenant_id, company.id)
    available = tx_unallocated(tx, by_tx.get(tx.id, [])).copy_abs()
    if available <= 0:
        raise ConflictError("Movimento già interamente allocato.", code="tx_fully_allocated")

    parsed: list[tuple[OpenItem, Decimal]] = []
    requested = Decimal("0.00")
    seen: set[uuid.UUID] = set()
    for raw in allocations:
        try:
            item_id = uuid.UUID(str(raw["open_item_id"]))
            amount = parse_money(str(raw["amount"]))
        except (KeyError, ValueError) as exc:
            raise ValidationError("Allocazione non valida: servono open_item_id e amount.",
                                  code="invalid_allocation") from exc
        if item_id in seen:
            raise ValidationError("Partita ripetuta nella stessa allocazione.",
                                  code="duplicate_item")
        seen.add(item_id)
        item = _owned(db, OpenItem, item_id, tenant_id, company.id)
        state = item_state(item, by_item.get(item.id, []))
        if state.status in (ItemStatus.CANCELLED, ItemStatus.SETTLED, ItemStatus.WRITTEN_OFF):
            raise ConflictError(f"Partita {item_id} già chiusa ({state.status}).",
                                code="item_closed")
        if amount > state.residual:
            raise ValidationError(
                f"Allocazione {money(amount)} superiore al residuo {money(state.residual)} "
                f"della partita {item_id}.", code="over_allocation")
        expected = "receivable" if tx.amount > 0 else "payable"
        if item.direction != expected:
            raise ValidationError(
                f"Segno incoerente: un movimento di {money(tx.amount)} può chiudere solo "
                f"partite '{expected}'.", code="direction_mismatch")
        if any(a.open_item_id == item.id and a.amount == amount and a.method == method
               for a in by_tx.get(tx.id, [])):
            raise ConflictError("Allocazione identica già registrata per questo movimento.",
                                code="allocation_exists")
        requested += amount
        parsed.append((item, amount))
    if requested > available:
        raise ValidationError(
            f"Totale allocazioni {money(requested)} superiore al residuo del movimento "
            f"{money(available)}.", code="over_allocation")

    confidence_d = None
    if confidence is not None:
        confidence_d = Decimal(confidence).quantize(Decimal("0.01"))
        if not (Decimal("0") <= confidence_d <= Decimal("1")):
            raise ValidationError("Confidenza fuori intervallo 0..1.", code="invalid_confidence")
    created = []
    for item, amount in parsed:
        allocation = ReconciliationAllocation(
            tenant_id=tenant_id, company_id=company.id, open_item_id=item.id,
            bank_transaction_id=tx.id, amount=amount, method=method,
            confidence=confidence_d,
            engine_version=ENGINE_VERSION if method != AllocationMethod.MANUAL else None,
            evidence=evidence or {}, reason=(reason or "")[:300] or None,
            actor_id=actor_id, approved_by_id=actor_id, approved_at=utcnow(),
        )
        db.add(allocation)
        created.append(allocation)
    db.flush()
    record_audit(db, actor_id=actor_id, action="treasury.reconciliation.apply",
                 entity_type="bank_transaction", entity_id=tx.id, tenant_id=tenant_id,
                 changes={"method": method, "confidence": str(confidence_d) if confidence_d else None,
                          "engine_version": ENGINE_VERSION,
                          "allocations": [{"open_item_id": str(i.id), "amount": money(a)}
                                          for i, a in parsed],
                          "evidence": evidence or {}, "approved_by": str(actor_id)})
    record_activity(db, tenant_id=tenant_id, actor_id=actor_id,
                    event_type="treasury.reconciled", entity_type="company",
                    entity_id=company.id,
                    summary=f"Riconciliato movimento {money(tx.amount)} EUR su "
                            f"{len(parsed)} partita/e ({method}).",
                    payload={"bank_transaction_id": str(tx.id), "method": method})
    by_item, by_tx = _allocations_by(db, tenant_id, company.id)
    return {
        "transaction": transaction_data(tx, by_tx.get(tx.id, [])),
        "items": [open_item_data(item, by_item.get(item.id, []), as_of=today())
                  for item, _ in parsed],
        "applied": len(created), "method": method,
    }


def auto_apply_exact(db: Session, *, tenant_id, company: Company, actor_id,
                     limit: int = 50) -> dict:
    """Apply only level-1 exact, unambiguous matches, triggered by a human.

    Ambiguity (more than one exact candidate) and every fuzzy match are left
    untouched for manual review.
    """
    plan = suggestions(db, tenant_id=tenant_id, company_id=company.id)
    applied, results = 0, []
    for entry in plan["transactions"]:
        if applied >= limit:
            break
        if not entry["auto_applicable"]:
            continue
        suggestion = next((s for s in entry["suggestions"]
                           if s["method"] == "exact" and s["confidence"] == "1.00"), None)
        if suggestion is None:
            continue
        outcome = apply_allocations(
            db, tenant_id=tenant_id, company=company, actor_id=actor_id,
            bank_transaction_id=uuid.UUID(entry["bank_transaction_id"]),
            allocations=suggestion["allocations"], method=AllocationMethod.EXACT,
            confidence=suggestion["confidence"],
            reason="Match deterministico esatto applicato su richiesta operatore.",
            evidence={**suggestion["evidence"], "reasons": suggestion["reasons"],
                      "engine_version": suggestion["engine_version"]},
        )
        applied += 1
        results.append({"bank_transaction_id": entry["bank_transaction_id"],
                        "allocations": suggestion["allocations"],
                        "settled_items": [{"id": item["id"], "status": item["status"],
                                           "residual": item["residual"]}
                                          for item in outcome["items"]]})
    return {
        "applied": applied, "engine_version": ENGINE_VERSION,
        "skipped_requiring_approval": sum(
            1 for e in plan["transactions"] if not e["auto_applicable"]),
        "unmatched": len(plan["unmatched_transaction_ids"]),
        "details": results,
        "policy": "Applicati solo match esatti non ambigui; tutto il resto resta in revisione umana.",
    }


# ---------------------------------------------------------------------------
# Analytics entry points
# ---------------------------------------------------------------------------

def _facts(db: Session, tenant_id, company_id, *, as_of: date):
    by_item, by_tx = _allocations_by(db, tenant_id, company_id)
    accounts = db.scalars(
        _scoped(BankAccount, tenant_id, company_id)
        .where(BankAccount.is_active.is_(True)).order_by(BankAccount.label)
    ).all()
    account_facts = [analytics.AccountFact(
        id=str(a.id), label=a.label, bank_name=a.bank_name, iban_last4=a.iban_last4,
        provider_key=a.provider_key,
        is_real_institution=provider_for_account(a).capabilities.is_real_institution,
        connection_status=a.connection_status, balance_amount=a.balance_amount,
        balance_date=a.balance_date, balance_source=a.balance_source,
        last_sync_at=a.last_sync_at.date() if a.last_sync_at else None,
    ) for a in accounts]

    item_facts = []
    for item in db.scalars(_scoped(OpenItem, tenant_id, company_id)).all():
        state = item_state(item, by_item.get(item.id, []))
        item_facts.append(analytics.ItemFact(
            id=str(item.id), direction=item.direction,
            counterparty_name=item.counterparty_name, document_number=item.document_number,
            due_date=item.due_date, amount=item.amount, residual=state.residual,
            status=state.status, source=item.source,
            invoice_id=str(item.invoice_id) if item.invoice_id else None,
        ))

    unreconciled = []
    for tx in db.scalars(_scoped(BankTransaction, tenant_id, company_id)).all():
        residual = tx_unallocated(tx, by_tx.get(tx.id, []))
        if residual == 0 or tx.value_date > as_of:
            continue
        unreconciled.append(analytics.UnreconciledFact(
            id=str(tx.id), value_date=tx.value_date, amount=tx.amount,
            unallocated=residual, description=tx.description,
            counterparty_name=tx.counterparty_name,
        ))
    return account_facts, item_facts, unreconciled


def cash_position(db: Session, *, tenant_id, company_id, as_of: date | None = None) -> dict:
    as_of = as_of or today()
    accounts, _, _ = _facts(db, tenant_id, company_id, as_of=as_of)
    return analytics.build_position(accounts, as_of=as_of)


def cash_forecast(db: Session, *, tenant_id, company_id, as_of: date | None = None,
                  horizon_days: int = 90) -> dict:
    as_of = as_of or today()
    accounts, items, _ = _facts(db, tenant_id, company_id, as_of=as_of)
    position = analytics.build_position(accounts, as_of=as_of)
    return analytics.build_forecast(position, items, as_of=as_of, horizon_days=horizon_days)


def aging(db: Session, *, tenant_id, company_id, as_of: date | None = None) -> dict:
    as_of = as_of or today()
    _, items, _ = _facts(db, tenant_id, company_id, as_of=as_of)
    return analytics.build_aging(items, as_of=as_of)


def snapshot(db: Session, *, tenant_id, company_id, as_of: date | None = None,
             horizon_days: int = 90) -> dict:
    """Everything the cockpit, the hub and the AI tools read — computed once."""
    as_of = as_of or today()
    accounts, items, unreconciled = _facts(db, tenant_id, company_id, as_of=as_of)
    position = analytics.build_position(accounts, as_of=as_of)
    forecast = analytics.build_forecast(position, items, as_of=as_of, horizon_days=horizon_days)
    ageing = analytics.build_aging(items, as_of=as_of)
    warnings = analytics.derive_warnings(
        position=position, forecast=forecast, aging=ageing,
        unreconciled=unreconciled, as_of=as_of)
    open_items = [i for i in items if i.residual > 0]
    return {
        "as_of": as_of.isoformat(), "currency": "EUR",
        "position": position, "forecast": forecast, "aging": ageing,
        "warnings": warnings,
        "counters": {
            "accounts": len(accounts),
            "open_items": len(open_items),
            "overdue_items": sum(1 for i in open_items if i.due_date < as_of),
            "unreconciled_transactions": len(unreconciled),
            "unreconciled_amount": money(total([u.unallocated.copy_abs()
                                                for u in unreconciled])),
            "receivable_residual": money(total([i.residual for i in open_items
                                                if i.direction == "receivable"])),
            "payable_residual": money(total([i.residual for i in open_items
                                             if i.direction == "payable"])),
        },
        "reconciliation": {
            "engine_version": ENGINE_VERSION,
            "levels_implemented": [1, 2],
            "level_3_ai_triage": "DESIGNED — non implementato",
        },
        "formula_version": FORMULA_VERSION,
        "limitations": LIMITATIONS,
    }


def default_sync_window(as_of: date | None = None, days: int = 90) -> tuple[date, date]:
    as_of = as_of or today()
    return as_of - timedelta(days=days), as_of
