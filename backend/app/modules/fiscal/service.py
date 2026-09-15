"""Fiscal application service — VAT register, settlement, deadlines, F24.

Chain implemented here (ADR-020):

    verified source → versioned rule → canonical VAT entries →
    deterministic calculation → trace → human validation → fiscal liability →
    treasury cash obligation

Guarantees:

* a calculation refuses to run without an **applicable, effective-dated rule
  set**; the rule-set id is stored on the result;
* `unsupported` / `requires_review` entries are excluded from the totals but
  counted and listed, and they force the settlement into `review_required`:
  a payable figure is never presented as final while material data is pending;
* recalculation never overwrites: a new settlement version supersedes the
  previous one;
* only a human validates; the AI layer can read results, never produce them;
* a validated liability becomes **exactly one** treasury open item
  (idempotent on `fiscal:vat_settlement:<period>`), so the cash forecast is
  never double-counted.
"""
import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.companies.models import Company
from app.modules.fiscal import rules
from app.modules.fiscal.models import (
    DeadlineStatus,
    DueDateStatus,
    F24Draft,
    F24Line,
    F24Status,
    FiscalDeadline,
    FiscalPeriod,
    FiscalRuleSet,
    FiscalTaxCode,
    PeriodStatus,
    RuleStatus,
    SettlementStatus,
    VatDirection,
    VatEntry,
    VatSettlement,
    VatSource,
    VatTreatment,
)
from app.shared.events import record_activity, record_audit
from app.shared.mixins import today, utcnow
from app.shared.money import money, parse_money, total

ENGINE_VERSION = rules.ENGINE_VERSION
VAT_FORMULA_VERSION = rules.VAT_FORMULA_VERSION

#: Treatments that may enter a settlement total.
COUNTED_TREATMENTS = frozenset({VatTreatment.SUPPORTED})
#: Treatments that block a clean result.
BLOCKING_TREATMENTS = frozenset({
    VatTreatment.UNSUPPORTED, VatTreatment.REQUIRES_REVIEW, VatTreatment.INSUFFICIENT_DATA,
})
MAX_IMPORT_ROWS = 2000

LIMITATIONS = [
    "Perimetro supportato: liquidazione IVA mensile e trimestrale per opzione (primi tre "
    "trimestri). Quarto trimestre, acconto di dicembre, trimestrali speciali, IVA di gruppo, "
    "split payment, reverse charge, plafond e regimi speciali NON sono calcolati.",
    "Nessuna ingestione automatica di fatture elettroniche XML/SdI: le voci IVA arrivano da "
    "inserimento manuale, import idempotente o collegamento alle fatture della piattaforma "
    "(che nascono come acquisti da verificare).",
    "Nessun formato telematico F24 è implementato e nessun F24 viene trasmesso: l'export "
    "disponibile è interno/sandbox e non è un tracciato ufficiale validato.",
    "Il calendario delle scadenze copre le festività nazionali; le festività locali del santo "
    "patrono non sono modellate.",
]


# ---------------------------------------------------------------------------
# Scope + rule resolution
# ---------------------------------------------------------------------------

def company_or_404(db: Session, company_id: uuid.UUID, tenant_id) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id or company.deleted_at is not None:
        raise NotFoundError("Company not found.")
    return company


def _scoped(model, tenant_id, company_id):
    return select(model).where(model.tenant_id == tenant_id, model.company_id == company_id)


def resolve_rule_set(db: Session, family: str, on_date: date) -> FiscalRuleSet:
    """The rule set in force for `family` at `on_date`, or a refusal."""
    row = db.scalar(
        select(FiscalRuleSet).where(
            FiscalRuleSet.jurisdiction == rules.JURISDICTION,
            FiscalRuleSet.rule_family == family,
            FiscalRuleSet.status == RuleStatus.ACTIVE,
            FiscalRuleSet.effective_from <= on_date,
        ).order_by(FiscalRuleSet.effective_from.desc())
    )
    if row is None or (row.effective_to is not None and row.effective_to < on_date):
        raise ValidationError(
            f"Nessun insieme di regole fiscali vigente per '{family}' alla data "
            f"{on_date.isoformat()}: il calcolo non viene eseguito. Caricare le regole "
            f"verificate per quel periodo.",
            code="no_applicable_rule_set")
    return row


def rule_set_data(row: FiscalRuleSet) -> dict:
    """Provenance-first serialisation: the source is part of the answer."""
    return {
        "id": str(row.id), "code": row.code, "rule_family": row.rule_family,
        "version": row.version, "status": row.status,
        "jurisdiction": row.jurisdiction,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "source": {
            "authority": row.source_authority, "title": row.source_title,
            "url": row.source_url,
            "published_at": row.source_published_at.isoformat() if row.source_published_at else None,
            "retrieved_at": row.retrieved_at.isoformat(),
            "fingerprint": row.source_fingerprint,
            "legal_reference": row.legal_reference,
        },
        "engine_version": row.engine_version,
        "notes": row.notes,
        "payload": row.payload,
    }


def list_rule_sets(db: Session) -> dict:
    rows = db.scalars(
        select(FiscalRuleSet).order_by(FiscalRuleSet.rule_family,
                                       FiscalRuleSet.effective_from.desc())
    ).all()
    codes = db.scalars(select(FiscalTaxCode).order_by(FiscalTaxCode.code)).all()
    return {
        "rule_sets": [rule_set_data(row) for row in rows],
        "tax_codes": [tax_code_data(row) for row in codes],
        "engine_version": ENGINE_VERSION,
        "limitations": LIMITATIONS,
    }


def tax_code_data(row: FiscalTaxCode) -> dict:
    return {
        "id": str(row.id), "code": row.code, "description": row.description,
        "section": row.section, "usage": row.usage,
        "reference_number": row.reference_number,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "requires_reference_period": row.requires_reference_period,
        "source_url": row.source_url, "notes": row.notes,
        "rule_set_id": str(row.rule_set_id),
    }


def _active_tax_codes(db: Session, on_date: date) -> list[FiscalTaxCode]:
    rows = db.scalars(
        select(FiscalTaxCode).where(
            FiscalTaxCode.jurisdiction == rules.JURISDICTION,
            FiscalTaxCode.valid_from <= on_date,
        ).order_by(FiscalTaxCode.valid_from.desc())
    ).all()
    return [row for row in rows if row.valid_to is None or row.valid_to >= on_date]


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

def ensure_period(db: Session, *, tenant_id, company: Company, year: int,
                  period_no: int, frequency: str) -> FiscalPeriod:
    try:
        start, end = rules.period_bounds(year, period_no, frequency)
    except ValueError as exc:
        raise ValidationError(str(exc), code="invalid_period") from exc
    existing = db.scalar(
        _scoped(FiscalPeriod, tenant_id, company.id).where(
            FiscalPeriod.year == year, FiscalPeriod.period_no == period_no,
            FiscalPeriod.frequency == frequency,
        )
    )
    if existing is not None:
        return existing
    period = FiscalPeriod(
        tenant_id=tenant_id, company_id=company.id, year=year, period_no=period_no,
        frequency=frequency, start_date=start, end_date=end,
        status=PeriodStatus.OPEN,
        label=rules.period_label(year, period_no, frequency),
    )
    db.add(period)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Periodo fiscale già presente.", code="period_exists") from exc
    return period


def period_data(period: FiscalPeriod) -> dict:
    return {
        "id": str(period.id), "year": period.year, "period_no": period.period_no,
        "frequency": period.frequency, "label": period.label,
        "start_date": period.start_date.isoformat(), "end_date": period.end_date.isoformat(),
        "status": period.status,
    }


def _previous_period_coords(year: int, period_no: int, frequency: str) -> tuple[int, int]:
    if period_no > 1:
        return year, period_no - 1
    return (year - 1, 12) if frequency == "monthly" else (year - 1, 4)


# ---------------------------------------------------------------------------
# VAT entries
# ---------------------------------------------------------------------------

def _entry_fingerprint(direction: str, competence: date, taxable: Decimal,
                       vat: Decimal | None, document: str | None) -> str:
    canonical = json.dumps(
        [direction, competence.isoformat(), money(taxable), money(vat), document],
        ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_entry(*, direction: str, vat_amount: Decimal | None, vat_rate: Decimal | None,
                   vat_nature: str | None, deductible: bool | None) -> tuple[str, str | None]:
    """Decide whether the engine can use an entry, and say why when it cannot.

    Bounded on purpose: ordinary taxed operations and explicitly non-taxable
    ones with a `natura` code are supported; everything else is routed to human
    review instead of being silently treated as ordinary.
    """
    if vat_amount is None:
        return (VatTreatment.INSUFFICIENT_DATA,
                "Importo IVA assente: indicare l'imposta o classificare l'operazione.")
    if vat_nature:
        if vat_amount != 0:
            return (VatTreatment.REQUIRES_REVIEW,
                    f"Operazione con natura {vat_nature} ma imposta non nulla: verificare.")
        return (VatTreatment.SUPPORTED, None)
    if vat_rate is None:
        return (VatTreatment.REQUIRES_REVIEW,
                "Aliquota assente e nessuna natura indicata: trattamento non determinabile.")
    if direction == VatDirection.PURCHASE and deductible is None:
        return (VatTreatment.REQUIRES_REVIEW,
                "Detraibilità dell'IVA sugli acquisti non confermata: richiede verifica.")
    if direction == VatDirection.PURCHASE and deductible is False:
        return (VatTreatment.SUPPORTED, None)  # excluded from credit, see settlement
    return (VatTreatment.SUPPORTED, None)


def record_vat_entry(db: Session, *, tenant_id, company: Company, actor_id,
                     direction: str, competence_date: date, taxable_amount: str,
                     vat_amount: str | None = None, vat_rate: str | None = None,
                     vat_nature: str | None = None, deductible: bool | None = None,
                     document_number: str | None = None, document_date: date | None = None,
                     counterparty_name: str | None = None, counterparty_vat: str | None = None,
                     source: str = VatSource.MANUAL, source_ref: str | None = None,
                     notes: str | None = None, invoice_id: uuid.UUID | None = None,
                     treatment_override: str | None = None,
                     treatment_reason: str | None = None,
                     reverses_entry_id: uuid.UUID | None = None) -> dict:
    """Register one immutable VAT fact, idempotently."""
    if direction not in tuple(VatDirection):
        raise ValidationError("Direzione IVA non valida: sale | purchase.",
                              code="invalid_direction")
    taxable = parse_money(taxable_amount, allow_zero=True)
    vat = parse_money(vat_amount, allow_zero=True) if vat_amount is not None else None
    rate = Decimal(vat_rate) if vat_rate is not None else None
    fingerprint = _entry_fingerprint(direction, competence_date, taxable, vat,
                                     document_number)
    ref = source_ref or f"manual:{fingerprint[:32]}"

    prior = db.scalar(
        _scoped(VatEntry, tenant_id, company.id).where(
            VatEntry.source == source, VatEntry.source_ref == ref)
    )
    if prior is not None:
        if prior.taxable_amount != taxable or prior.vat_amount != vat or prior.direction != direction:
            raise ConflictError(
                "Riferimento già presente con contenuto diverso: registrare una rettifica "
                "(entry di segno opposto) invece di modificare lo storico.",
                code="vat_entry_conflict")
        return {**vat_entry_data(prior), "replayed": True}

    treatment, reason = classify_entry(direction=direction, vat_amount=vat, vat_rate=rate,
                                       vat_nature=vat_nature, deductible=deductible)
    if treatment_override is not None:
        if treatment_override not in tuple(VatTreatment):
            raise ValidationError("Trattamento IVA non valido.", code="invalid_treatment")
        treatment, reason = treatment_override, treatment_reason or reason

    entry = VatEntry(
        tenant_id=tenant_id, company_id=company.id, direction=direction, source=source,
        source_ref=ref, invoice_id=invoice_id, document_number=document_number,
        document_date=document_date, competence_date=competence_date,
        counterparty_name=counterparty_name, counterparty_vat=counterparty_vat,
        taxable_amount=taxable, vat_amount=vat, vat_rate=rate, vat_nature=vat_nature,
        deductible=deductible, treatment=treatment, treatment_reason=reason,
        notes=notes, reverses_entry_id=reverses_entry_id, created_by_id=actor_id,
    )
    db.add(entry)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Voce IVA già registrata.", code="vat_entry_exists") from exc
    record_audit(db, actor_id=actor_id, action="fiscal.vat_entry.create",
                 entity_type="vat_entry", entity_id=entry.id, tenant_id=tenant_id,
                 changes={"direction": direction, "taxable": money(taxable),
                          "vat": money(vat), "treatment": treatment,
                          "competence_date": competence_date.isoformat(),
                          "source": source, "source_ref": ref})
    return {**vat_entry_data(entry), "replayed": False}


def vat_entry_data(entry: VatEntry) -> dict:
    return {
        "id": str(entry.id), "direction": entry.direction, "source": entry.source,
        "source_ref": entry.source_ref,
        "invoice_id": str(entry.invoice_id) if entry.invoice_id else None,
        "document_number": entry.document_number,
        "document_date": entry.document_date.isoformat() if entry.document_date else None,
        "competence_date": entry.competence_date.isoformat(),
        "counterparty_name": entry.counterparty_name,
        "counterparty_vat": entry.counterparty_vat,
        "taxable_amount": money(entry.taxable_amount), "vat_amount": money(entry.vat_amount),
        "vat_rate": str(entry.vat_rate) if entry.vat_rate is not None else None,
        "vat_nature": entry.vat_nature, "deductible": entry.deductible,
        "treatment": entry.treatment, "treatment_reason": entry.treatment_reason,
        "notes": entry.notes,
        "reverses_entry_id": str(entry.reverses_entry_id) if entry.reverses_entry_id else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def import_vat_entries(db: Session, *, tenant_id, company: Company, actor_id,
                       rows: list[dict]) -> dict:
    """Atomic, idempotent bulk ingestion keyed by `source_ref`."""
    if not rows:
        raise ValidationError("Nessuna riga da importare.", code="empty_import")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValidationError(f"Import oltre il limite di {MAX_IMPORT_ROWS} righe.",
                              code="import_too_large")
    refs = [str(row.get("source_ref") or "") for row in rows]
    if any(not ref for ref in refs):
        raise ValidationError("Ogni riga richiede source_ref per l'idempotenza.",
                              code="missing_source_ref")
    if len(set(refs)) != len(refs):
        raise ValidationError("source_ref duplicato nel file.", code="duplicate_source_ref")

    created, skipped, review = 0, 0, 0
    with db.begin_nested():
        for index, raw in enumerate(rows, start=1):
            try:
                result = record_vat_entry(
                    db, tenant_id=tenant_id, company=company, actor_id=actor_id,
                    direction=str(raw["direction"]),
                    competence_date=date.fromisoformat(str(raw["competence_date"])),
                    taxable_amount=str(raw["taxable_amount"]),
                    vat_amount=str(raw["vat_amount"]) if raw.get("vat_amount") is not None else None,
                    vat_rate=str(raw["vat_rate"]) if raw.get("vat_rate") is not None else None,
                    vat_nature=raw.get("vat_nature"),
                    deductible=raw.get("deductible"),
                    document_number=raw.get("document_number"),
                    document_date=(date.fromisoformat(str(raw["document_date"]))
                                   if raw.get("document_date") else None),
                    counterparty_name=raw.get("counterparty_name"),
                    counterparty_vat=raw.get("counterparty_vat"),
                    source=VatSource.IMPORT, source_ref=str(raw["source_ref"]),
                    notes=raw.get("notes"),
                )
            except (KeyError, ValueError) as exc:
                raise ValidationError(f"Riga {index}: {exc}", code="invalid_import_row") from exc
            if result["replayed"]:
                skipped += 1
            else:
                created += 1
            if result["treatment"] in BLOCKING_TREATMENTS:
                review += 1
        db.flush()
    payload = {"created": created, "skipped": skipped, "received": len(rows),
               "requires_review": review}
    record_audit(db, actor_id=actor_id, action="fiscal.vat_entry.import",
                 entity_type="company", entity_id=company.id, tenant_id=tenant_id,
                 changes=payload)
    return payload


def link_invoices(db: Session, *, tenant_id, company: Company, actor_id) -> dict:
    """Derive VAT entries from the workspace invoices issued to this company.

    Same perspective as the treasury (ADR-016): from the subject company's
    ledger those documents are **purchases**. Deductibility is *not* assumed:
    every derived entry lands in `requires_review` until a human confirms it.
    """
    from app.modules.billing import service as billing

    invoices = billing.list_settleable(db, tenant_id=tenant_id, company_id=company.id)
    created, skipped, incomplete = 0, 0, []
    for invoice in invoices:
        ref = f"invoice:{invoice['id']}"
        prior = db.scalar(
            _scoped(VatEntry, tenant_id, company.id).where(
                VatEntry.source == VatSource.INVOICE, VatEntry.source_ref == ref)
        )
        if prior is not None:
            skipped += 1
            continue
        if invoice["issue_date"] is None or invoice["total_amount"] is None:
            incomplete.append(invoice["id"])
            continue
        taxable = invoice.get("taxable_amount")
        vat = invoice.get("vat_amount")
        if taxable is None or vat is None:
            incomplete.append(invoice["id"])
            continue
        record_vat_entry(
            db, tenant_id=tenant_id, company=company, actor_id=actor_id,
            direction=VatDirection.PURCHASE,
            competence_date=date.fromisoformat(invoice["issue_date"]),
            taxable_amount=str(Decimal(taxable).quantize(Decimal("0.01"))),
            vat_amount=str(Decimal(vat).quantize(Decimal("0.01"))),
            document_number=invoice["document_number"],
            document_date=date.fromisoformat(invoice["issue_date"]),
            counterparty_name=invoice.get("customer_name"),
            counterparty_vat=invoice.get("customer_vat"),
            source=VatSource.INVOICE, source_ref=ref,
            invoice_id=uuid.UUID(invoice["id"]),
            treatment_override=VatTreatment.REQUIRES_REVIEW,
            treatment_reason="Documento derivato da fattura della piattaforma: confermare "
                             "detraibilità e competenza IVA prima del calcolo.",
        )
        created += 1
    db.flush()
    return {
        "created": created, "already_present": skipped,
        "skipped_incomplete": incomplete, "considered": len(invoices),
        "note": ("Le voci derivate restano 'requires_review': la detraibilità non viene "
                 "assunta dalla piattaforma."),
    }


def confirm_entry_treatment(db: Session, *, tenant_id, company: Company, actor_id,
                            entry_id: uuid.UUID, treatment: str, deductible: bool | None,
                            reason: str | None) -> dict:
    """Human decision on a pending entry, recorded as a new immutable entry.

    The original row is never edited (append-only): a `system_derived` twin
    carries the confirmed treatment and points back at the source entry.
    """
    if treatment not in (VatTreatment.SUPPORTED, VatTreatment.UNSUPPORTED):
        raise ValidationError("Il trattamento confermabile è 'supported' o 'unsupported'.",
                              code="invalid_treatment")
    original = db.get(VatEntry, entry_id)
    if (original is None or original.tenant_id != tenant_id
            or original.company_id != company.id):
        raise NotFoundError("VatEntry not found")
    if original.treatment not in BLOCKING_TREATMENTS:
        raise ConflictError("La voce non è in attesa di verifica.", code="entry_not_pending")
    existing = db.scalar(
        _scoped(VatEntry, tenant_id, company.id).where(
            VatEntry.source == VatSource.SYSTEM_DERIVED,
            VatEntry.source_ref == f"confirm:{entry_id}")
    )
    if existing is not None:
        raise ConflictError("Verifica già registrata per questa voce.",
                            code="entry_already_confirmed")
    confirmed = VatEntry(
        tenant_id=tenant_id, company_id=company.id, direction=original.direction,
        source=VatSource.SYSTEM_DERIVED, source_ref=f"confirm:{entry_id}",
        invoice_id=original.invoice_id, document_number=original.document_number,
        document_date=original.document_date, competence_date=original.competence_date,
        counterparty_name=original.counterparty_name, counterparty_vat=original.counterparty_vat,
        taxable_amount=original.taxable_amount, vat_amount=original.vat_amount,
        vat_rate=original.vat_rate, vat_nature=original.vat_nature,
        deductible=deductible if deductible is not None else original.deductible,
        treatment=treatment,
        treatment_reason=(reason or "Trattamento confermato da operatore.")[:300],
        notes=f"Verifica umana della voce {entry_id}.",
        reverses_entry_id=original.id, created_by_id=actor_id,
    )
    db.add(confirmed)
    db.flush()
    record_audit(db, actor_id=actor_id, action="fiscal.vat_entry.confirm",
                 entity_type="vat_entry", entity_id=confirmed.id, tenant_id=tenant_id,
                 changes={"original_entry_id": str(entry_id), "treatment": treatment,
                          "deductible": deductible, "reason": reason})
    return vat_entry_data(confirmed)


def _period_entries(db: Session, tenant_id, company_id, period: FiscalPeriod) -> list[VatEntry]:
    """Entries competent to the period, with confirmations replacing originals."""
    rows = db.scalars(
        _scoped(VatEntry, tenant_id, company_id)
        .where(VatEntry.competence_date.between(period.start_date, period.end_date))
        .order_by(VatEntry.competence_date, VatEntry.id)
    ).all()
    superseded = {row.reverses_entry_id for row in rows
                  if row.source == VatSource.SYSTEM_DERIVED and row.reverses_entry_id}
    return [row for row in rows if row.id not in superseded]


def list_vat_entries(db: Session, *, tenant_id, company_id, year: int,
                     period_no: int | None = None, frequency: str = "monthly") -> dict:
    if period_no is None:
        start, end = date(year, 1, 1), date(year, 12, 31)
        label = f"Anno {year}"
    else:
        start, end = rules.period_bounds(year, period_no, frequency)
        label = rules.period_label(year, period_no, frequency)
    rows = db.scalars(
        _scoped(VatEntry, tenant_id, company_id)
        .where(VatEntry.competence_date.between(start, end))
        .order_by(VatEntry.competence_date, VatEntry.id)
    ).all()
    superseded = {row.reverses_entry_id for row in rows
                  if row.source == VatSource.SYSTEM_DERIVED and row.reverses_entry_id}
    items = [{**vat_entry_data(row), "superseded": row.id in superseded} for row in rows]
    pending = [i for i in items if not i["superseded"] and i["treatment"] in BLOCKING_TREATMENTS]
    return {
        "period": {"label": label, "start": start.isoformat(), "end": end.isoformat()},
        "entries": items,
        "counters": {
            "total": len(items),
            "effective": sum(1 for i in items if not i["superseded"]),
            "requires_review": len(pending),
            "sales": sum(1 for i in items if i["direction"] == "sale" and not i["superseded"]),
            "purchases": sum(1 for i in items if i["direction"] == "purchase" and not i["superseded"]),
        },
        "pending_review": pending,
        "limitations": LIMITATIONS,
    }


# ---------------------------------------------------------------------------
# Settlement engine
# ---------------------------------------------------------------------------

def _prior_position(db: Session, tenant_id, company_id, period: FiscalPeriod
                    ) -> tuple[Decimal, Decimal, dict, list[dict]]:
    """Prior-period credit / small debit, with provenance and warnings."""
    warnings: list[dict] = []
    prev_year, prev_no = _previous_period_coords(period.year, period.period_no, period.frequency)
    previous = db.scalar(
        _scoped(FiscalPeriod, tenant_id, company_id).where(
            FiscalPeriod.year == prev_year, FiscalPeriod.period_no == prev_no,
            FiscalPeriod.frequency == period.frequency)
    )
    if previous is None:
        warnings.append({
            "code": "no_prior_period", "severity": "warning",
            "title": "Nessun periodo IVA precedente tracciato",
            "message": ("Credito e debito pregressi non risultano registrati: se esistono, "
                        "inserirli come voce di apertura prima di considerare definitivo "
                        "il risultato."),
            "formula": "posizione precedente = liquidazione del periodo precedente",
        })
        return Decimal("0.00"), Decimal("0.00"), {"prior_source": None}, warnings

    settlement = db.scalar(
        select(VatSettlement).where(
            VatSettlement.tenant_id == tenant_id,
            VatSettlement.period_id == previous.id,
            VatSettlement.status != SettlementStatus.SUPERSEDED,
        ).order_by(VatSettlement.version.desc())
    )
    if settlement is None:
        warnings.append({
            "code": "prior_period_not_calculated", "severity": "warning",
            "title": "Periodo precedente non liquidato",
            "message": (f"Il periodo {previous.label} esiste ma non ha una liquidazione: "
                        f"credito e debito pregressi sono assunti assenti."),
            "formula": "posizione precedente = liquidazione del periodo precedente",
        })
        return Decimal("0.00"), Decimal("0.00"), {"prior_source": None}, warnings

    if settlement.status != SettlementStatus.VALIDATED:
        warnings.append({
            "code": "prior_period_not_validated", "severity": "warning",
            "title": "Posizione precedente non validata",
            "message": (f"La liquidazione di {previous.label} è calcolata ma non validata: "
                        f"il riporto usato non è ancora confermato da una persona."),
            "formula": "riporto = carry-forward della liquidazione precedente",
        })
    return (
        settlement.carry_forward_credit or Decimal("0.00"),
        settlement.carry_forward_debit or Decimal("0.00"),
        {"prior_source": {"settlement_id": str(settlement.id), "period": previous.label,
                          "status": settlement.status, "version": settlement.version}},
        warnings,
    )


def calculate_settlement(db: Session, *, tenant_id, company: Company, actor_id,
                         year: int, period_no: int, frequency: str) -> dict:
    """Run the deterministic periodic VAT settlement for one period."""
    period = ensure_period(db, tenant_id=tenant_id, company=company, year=year,
                           period_no=period_no, frequency=frequency)
    vat_rules = resolve_rule_set(db, "vat_periodic", period.end_date)
    calendar_rules = resolve_rule_set(db, "payment_calendar", period.end_date)
    payload = vat_rules.payload

    supported, reason = rules.is_supported_period(frequency, period_no, payload)
    if not supported:
        raise ValidationError(
            f"Periodo non supportato dal motore: {reason}", code="unsupported_period")

    entries = _period_entries(db, tenant_id, company.id, period)
    counted = [e for e in entries if e.treatment in COUNTED_TREATMENTS]
    blocked = [e for e in entries if e.treatment in BLOCKING_TREATMENTS]

    debit = total([e.vat_amount for e in counted
                   if e.direction == VatDirection.SALE and e.vat_amount is not None]) or Decimal("0.00")
    credit = total([e.vat_amount for e in counted
                    if e.direction == VatDirection.PURCHASE and e.vat_amount is not None
                    and e.deductible is not False]) or Decimal("0.00")
    non_deductible = total([e.vat_amount for e in counted
                            if e.direction == VatDirection.PURCHASE
                            and e.deductible is False and e.vat_amount is not None])

    prior_credit, prior_small_debit, prior_trace, warnings = _prior_position(
        db, tenant_id, company.id, period)

    math = rules.compute_settlement(
        rules.SettlementInput(
            debit_total=debit, credit_total=credit, prior_credit=prior_credit,
            prior_small_debit=prior_small_debit, frequency=frequency,
            is_fourth_quarter=(frequency == "quarterly" and period_no == 4),
        ),
        payload,
    )

    if blocked:
        blocked_vat = total([e.vat_amount for e in blocked if e.vat_amount is not None])
        warnings.append({
            "code": "unsupported_entries", "severity": "critical",
            "title": "Operazioni non utilizzabili nel calcolo",
            "message": (f"{len(blocked)} voci IVA del periodo non sono utilizzabili "
                        f"(non supportate o da verificare) per un totale imposta "
                        f"{money(blocked_vat) or 'non determinabile'} EUR: il risultato "
                        f"non può essere considerato definitivo."),
            "formula": "voci con trattamento unsupported | requires_review | insufficient_data",
        })
    if not counted:
        warnings.append({
            "code": "no_countable_entries", "severity": "warning",
            "title": "Nessuna voce IVA utilizzabile nel periodo",
            "message": "Nessuna operazione supportata: la posizione non è significativa.",
            "formula": "voci con trattamento supported",
        })

    status = (SettlementStatus.REVIEW_REQUIRED
              if any(w["severity"] in ("critical", "warning") for w in warnings)
              else SettlementStatus.CALCULATED)

    statutory = rules.statutory_due_date(year, period_no, frequency, payload)
    due = rules.resolve_due_date(statutory, calendar_rules.payload)

    previous_versions = db.scalars(
        select(VatSettlement).where(
            VatSettlement.tenant_id == tenant_id, VatSettlement.period_id == period.id
        ).order_by(VatSettlement.version.desc())
    ).all()
    version = (previous_versions[0].version + 1) if previous_versions else 1

    trace = {
        "formula_version": VAT_FORMULA_VERSION,
        "engine_version": ENGINE_VERSION,
        "rule_set": rule_set_data(vat_rules),
        "calendar_rule_set": rule_set_data(calendar_rules),
        "formula_steps": payload["formula"]["steps"],
        "applied_rules": list(math.applied_rules),
        "components": {
            "debit_total": money(debit), "credit_total": money(credit),
            "non_deductible_purchase_vat": money(non_deductible),
            "prior_credit": money(prior_credit), "prior_small_debit": money(prior_small_debit),
            "net_position": money(math.net_position), "interest": money(math.interest_amount),
        },
        **prior_trace,
        "debit_sources": [{"id": str(e.id), "document_number": e.document_number,
                           "competence_date": e.competence_date.isoformat(),
                           "counterparty_name": e.counterparty_name,
                           "vat_amount": money(e.vat_amount)}
                          for e in counted if e.direction == VatDirection.SALE],
        "credit_sources": [{"id": str(e.id), "document_number": e.document_number,
                            "competence_date": e.competence_date.isoformat(),
                            "counterparty_name": e.counterparty_name,
                            "vat_amount": money(e.vat_amount),
                            "deductible": e.deductible}
                           for e in counted if e.direction == VatDirection.PURCHASE],
        "excluded_sources": [{"id": str(e.id), "treatment": e.treatment,
                              "reason": e.treatment_reason,
                              "vat_amount": money(e.vat_amount)}
                             for e in blocked],
        "due_date": {
            "statutory": due.statutory_date.isoformat(),
            "resolved": due.due_date.isoformat() if due.due_date else None,
            "status": due.status, "applied_rules": list(due.applied_rules),
            "reason": due.reason, "formula_version": due.formula_version,
        },
        "outcome": math.outcome,
        "supported_cases": payload["supported_cases"],
        "unsupported_cases": payload["unsupported_cases"],
    }

    settlement = VatSettlement(
        tenant_id=tenant_id, company_id=company.id, period_id=period.id, version=version,
        rule_set_id=vat_rules.id, formula_version=VAT_FORMULA_VERSION, status=status,
        debit_total=debit, credit_total=credit, prior_credit=prior_credit,
        prior_small_debit=prior_small_debit, interest_amount=math.interest_amount,
        net_position=math.net_position, payable_amount=math.payable_amount,
        carry_forward_credit=math.carry_forward_credit,
        carry_forward_debit=math.carry_forward_debit,
        source_count=len(counted), unsupported_count=len(blocked),
        trace=trace, warnings=warnings, calculated_at=utcnow(), calculated_by_id=actor_id,
    )
    db.add(settlement)
    db.flush()

    for older in previous_versions:
        if older.status != SettlementStatus.SUPERSEDED:
            older.status = SettlementStatus.SUPERSEDED
            older.superseded_by_id = settlement.id
    period.status = (PeriodStatus.REVIEW_REQUIRED
                     if status == SettlementStatus.REVIEW_REQUIRED else PeriodStatus.CALCULATED)

    deadline = _upsert_deadline(db, tenant_id=tenant_id, company=company, period=period,
                                settlement=settlement, due=due,
                                rule_set_id=vat_rules.id)
    db.flush()
    record_audit(db, actor_id=actor_id, action="fiscal.settlement.calculate",
                 entity_type="vat_settlement", entity_id=settlement.id, tenant_id=tenant_id,
                 changes={"period": period.label, "version": version, "status": status,
                          "rule_set_version": vat_rules.version,
                          "net_position": money(math.net_position),
                          "payable": money(math.payable_amount),
                          "unsupported_count": len(blocked)})
    return settlement_data(db, settlement, period=period, deadline=deadline)


def _upsert_deadline(db: Session, *, tenant_id, company: Company, period: FiscalPeriod,
                     settlement: VatSettlement, due, rule_set_id) -> FiscalDeadline:
    """One deadline per (company, kind, period); recalculation refreshes it.

    A deadline that was already validated (and therefore turned into a cash
    obligation) is **not** silently rewritten: it is cancelled and replaced, so
    the treasury link stays traceable.
    """
    existing = db.scalar(
        _scoped(FiscalDeadline, tenant_id, company.id).where(
            FiscalDeadline.kind == "vat_periodic_payment",
            FiscalDeadline.period_id == period.id)
    )
    amount = settlement.payable_amount
    if existing is None:
        deadline = FiscalDeadline(
            tenant_id=tenant_id, company_id=company.id, kind="vat_periodic_payment",
            period_id=period.id, settlement_id=settlement.id,
            statutory_date=due.statutory_date, due_date=due.due_date,
            due_date_status=(DueDateStatus.RESOLVED if due.due_date
                             else DueDateStatus.REVIEW_REQUIRED),
            deferral_reason=due.reason, amount=amount, status=DeadlineStatus.PENDING,
            rule_set_id=rule_set_id,
        )
        db.add(deadline)
        db.flush()
        return deadline

    if existing.status == DeadlineStatus.VALIDATED and existing.open_item_id is not None:
        existing.status = DeadlineStatus.CANCELLED
        existing.notes = ("Sostituita da un nuovo calcolo: la partita di tesoreria collegata "
                          "resta storicizzata e va chiusa manualmente se non più dovuta.")
        db.flush()
        replacement = FiscalDeadline(
            tenant_id=tenant_id, company_id=company.id,
            kind="vat_periodic_payment_recalculated", period_id=period.id,
            settlement_id=settlement.id, statutory_date=due.statutory_date,
            due_date=due.due_date,
            due_date_status=(DueDateStatus.RESOLVED if due.due_date
                             else DueDateStatus.REVIEW_REQUIRED),
            deferral_reason=due.reason, amount=amount, status=DeadlineStatus.PENDING,
            rule_set_id=rule_set_id,
        )
        db.add(replacement)
        db.flush()
        return replacement

    existing.settlement_id = settlement.id
    existing.statutory_date = due.statutory_date
    existing.due_date = due.due_date
    existing.due_date_status = (DueDateStatus.RESOLVED if due.due_date
                                else DueDateStatus.REVIEW_REQUIRED)
    existing.deferral_reason = due.reason
    existing.amount = amount
    existing.status = DeadlineStatus.PENDING
    existing.rule_set_id = rule_set_id
    db.flush()
    return existing


def settlement_data(db: Session, settlement: VatSettlement, *,
                    period: FiscalPeriod | None = None,
                    deadline: FiscalDeadline | None = None) -> dict:
    period = period or db.get(FiscalPeriod, settlement.period_id)
    if deadline is None:
        deadline = db.scalar(
            select(FiscalDeadline).where(
                FiscalDeadline.tenant_id == settlement.tenant_id,
                FiscalDeadline.settlement_id == settlement.id)
        )
    draft = db.scalar(
        select(F24Draft).where(F24Draft.tenant_id == settlement.tenant_id,
                               F24Draft.settlement_id == settlement.id)
    )
    return {
        "id": str(settlement.id), "version": settlement.version,
        "status": settlement.status, "currency": settlement.currency,
        "period": period_data(period) if period else None,
        "debit_total": money(settlement.debit_total),
        "credit_total": money(settlement.credit_total),
        "prior_credit": money(settlement.prior_credit),
        "prior_small_debit": money(settlement.prior_small_debit),
        "interest_amount": money(settlement.interest_amount),
        "net_position": money(settlement.net_position),
        "payable_amount": money(settlement.payable_amount),
        "carry_forward_credit": money(settlement.carry_forward_credit),
        "carry_forward_debit": money(settlement.carry_forward_debit),
        "outcome": settlement.trace.get("outcome"),
        "source_count": settlement.source_count,
        "unsupported_count": settlement.unsupported_count,
        "warnings": settlement.warnings,
        "trace": settlement.trace,
        "formula_version": settlement.formula_version,
        "rule_set_id": str(settlement.rule_set_id),
        "calculated_at": settlement.calculated_at.isoformat() if settlement.calculated_at else None,
        "validated_at": settlement.validated_at.isoformat() if settlement.validated_at else None,
        "validated_by_id": str(settlement.validated_by_id) if settlement.validated_by_id else None,
        "validation_note": settlement.validation_note,
        "superseded_by_id": str(settlement.superseded_by_id) if settlement.superseded_by_id else None,
        "deadline": deadline_data(deadline) if deadline else None,
        "f24_draft_id": str(draft.id) if draft else None,
        "limitations": LIMITATIONS,
    }


def deadline_data(row: FiscalDeadline) -> dict:
    return {
        "id": str(row.id), "kind": row.kind,
        "period_id": str(row.period_id) if row.period_id else None,
        "settlement_id": str(row.settlement_id) if row.settlement_id else None,
        "statutory_date": row.statutory_date.isoformat() if row.statutory_date else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "due_date_status": row.due_date_status,
        "deferral_reason": row.deferral_reason,
        "amount": money(row.amount), "status": row.status,
        "open_item_id": str(row.open_item_id) if row.open_item_id else None,
        "notes": row.notes,
    }


def validate_settlement(db: Session, *, tenant_id, company: Company, actor_id,
                        settlement_id: uuid.UUID, note: str | None,
                        acknowledge_warnings: bool = False) -> dict:
    """Human validation. The AI layer can never reach this path."""
    settlement = db.get(VatSettlement, settlement_id)
    if (settlement is None or settlement.tenant_id != tenant_id
            or settlement.company_id != company.id):
        raise NotFoundError("VatSettlement not found")
    if settlement.status == SettlementStatus.SUPERSEDED:
        raise ConflictError("Liquidazione superata da un ricalcolo: validare l'ultima versione.",
                            code="settlement_superseded")
    if settlement.status == SettlementStatus.VALIDATED:
        return settlement_data(db, settlement)
    blocking = [w for w in settlement.warnings if w["severity"] == "critical"]
    if blocking and not acknowledge_warnings:
        raise ConflictError(
            "La liquidazione contiene operazioni non utilizzabili: risolvere le verifiche "
            "oppure validare dichiarando esplicitamente di assumerne la responsabilità "
            "(acknowledge_warnings).",
            code="settlement_requires_review")
    if blocking and not (note and note.strip()):
        raise ValidationError(
            "Validando con segnalazioni critiche è obbligatoria una nota di motivazione.",
            code="validation_note_required")

    settlement.status = SettlementStatus.VALIDATED
    settlement.validated_by_id = actor_id
    settlement.validated_at = utcnow()
    settlement.validation_note = (note or "").strip()[:600] or None

    period = db.get(FiscalPeriod, settlement.period_id)
    if period is not None:
        period.status = PeriodStatus.VALIDATED

    deadline = db.scalar(
        select(FiscalDeadline).where(
            FiscalDeadline.tenant_id == tenant_id,
            FiscalDeadline.settlement_id == settlement.id,
            FiscalDeadline.status != DeadlineStatus.CANCELLED)
    )
    liability = None
    if deadline is not None:
        deadline.status = DeadlineStatus.VALIDATED
        liability = sync_fiscal_liability(db, tenant_id=tenant_id, company=company,
                                          actor_id=actor_id, deadline=deadline,
                                          settlement=settlement, period=period)
    db.flush()
    record_audit(db, actor_id=actor_id, action="fiscal.settlement.validate",
                 entity_type="vat_settlement", entity_id=settlement.id, tenant_id=tenant_id,
                 changes={"note": settlement.validation_note,
                          "acknowledged_warnings": bool(blocking and acknowledge_warnings),
                          "payable": money(settlement.payable_amount),
                          "open_item_id": liability.get("open_item_id") if liability else None})
    record_activity(db, tenant_id=tenant_id, actor_id=actor_id,
                    event_type="fiscal.settlement_validated", entity_type="company",
                    entity_id=company.id,
                    summary=(f"Liquidazione IVA {period.label if period else ''} validata: "
                             f"{money(settlement.payable_amount) or 'nessun versamento'} EUR."),
                    payload={"settlement_id": str(settlement.id)})
    return {**settlement_data(db, settlement), "liability": liability}


# ---------------------------------------------------------------------------
# Treasury integration — exactly one cash obligation per validated liability
# ---------------------------------------------------------------------------

def sync_fiscal_liability(db: Session, *, tenant_id, company: Company, actor_id,
                          deadline: FiscalDeadline, settlement: VatSettlement,
                          period: FiscalPeriod | None) -> dict:
    """Turn a validated fiscal liability into one treasury open item.

    Idempotent by construction: `source_ref = "vat_settlement:<period_id>"`, so
    recalculating and re-validating the same period cannot create a second cash
    obligation. Nothing is created when there is nothing to pay.
    """
    from app.modules.treasury import service as treasury

    if settlement.payable_amount is None or settlement.payable_amount <= 0:
        return {"created": False, "reason": "Nessun importo a debito da versare.",
                "open_item_id": None}
    if deadline.due_date is None:
        return {"created": False,
                "reason": ("Scadenza non risolta (differimento da verificare): nessuna "
                           "obbligazione di cassa creata senza una data certa."),
                "open_item_id": None}
    if deadline.open_item_id is not None:
        return {"created": False, "reason": "Obbligazione già presente in tesoreria.",
                "open_item_id": str(deadline.open_item_id)}

    label = period.label if period else "periodo IVA"
    result = treasury.create_open_item(
        db, tenant_id=tenant_id, company=company, actor_id=actor_id,
        direction="payable",
        counterparty_name="Erario — IVA periodica",
        due_date=deadline.due_date,
        amount=money(settlement.payable_amount),
        source="fiscal",
        source_ref=f"vat_settlement:{settlement.period_id}",
        document_number=f"Liquidazione IVA {label}",
        document_date=period.end_date if period else None,
        category="IVA",
        notes=(f"Obbligazione generata dalla liquidazione IVA validata "
               f"(versione {settlement.version}, regole {settlement.trace['rule_set']['version']})."),
    )
    deadline.open_item_id = uuid.UUID(result["id"])
    db.flush()
    return {"created": not result.get("replayed", False),
            "open_item_id": result["id"],
            "amount": result["amount"], "due_date": result["due_date"]}


# ---------------------------------------------------------------------------
# F24 drafts
# ---------------------------------------------------------------------------

def generate_f24(db: Session, *, tenant_id, company: Company, actor_id,
                 settlement_id: uuid.UUID) -> dict:
    """Build the internal F24 draft for a validated settlement."""
    settlement = db.get(VatSettlement, settlement_id)
    if (settlement is None or settlement.tenant_id != tenant_id
            or settlement.company_id != company.id):
        raise NotFoundError("VatSettlement not found")
    if settlement.status != SettlementStatus.VALIDATED:
        raise ConflictError(
            "L'F24 si genera solo da una liquidazione validata: la validazione umana "
            "precede il documento di versamento.", code="settlement_not_validated")
    if settlement.payable_amount is None or settlement.payable_amount <= 0:
        raise ConflictError("Nessun importo a debito: non è dovuto alcun F24 per il periodo.",
                            code="nothing_to_pay")
    existing = db.scalar(
        select(F24Draft).where(F24Draft.tenant_id == tenant_id,
                               F24Draft.settlement_id == settlement.id)
    )
    if existing is not None:
        return {**f24_data(existing), "replayed": True}

    period = db.get(FiscalPeriod, settlement.period_id)
    deadline = db.scalar(
        select(FiscalDeadline).where(
            FiscalDeadline.tenant_id == tenant_id,
            FiscalDeadline.settlement_id == settlement.id,
            FiscalDeadline.status != DeadlineStatus.CANCELLED)
    )
    format_rules = resolve_rule_set(db, "f24_format", period.end_date)
    codes = _active_tax_codes(db, period.end_date)
    code_row = rules.tax_code_for(period.frequency, period.period_no, codes)
    if code_row is None:
        raise ValidationError(
            "Nessun codice tributo verificato disponibile per il periodo: aggiornare il "
            "registro dei codici prima di generare l'F24.", code="missing_tax_code")

    amount = rules.quantize_f24(settlement.payable_amount, format_rules.payload)
    draft = F24Draft(
        tenant_id=tenant_id, company_id=company.id, settlement_id=settlement.id,
        deadline_id=deadline.id if deadline else None, rule_set_id=format_rules.id,
        status=F24Status.VALIDATION_REQUIRED, total_debit=amount,
        total_credit=Decimal("0.00"), balance=amount,
        due_date=deadline.due_date if deadline else None,
        taxpayer_snapshot={
            "legal_name": company.legal_name, "vat_number": company.vat_number,
            "tax_code": company.tax_code, "city": company.city, "region": company.region,
        },
        notes=("Bozza interna: non è un tracciato telematico F24 e non può essere trasmessa."),
        created_by_id=actor_id,
    )
    db.add(draft)
    db.flush()

    line = F24Line(
        tenant_id=tenant_id, company_id=company.id, draft_id=draft.id, position=0,
        section=code_row.section, tax_code=code_row.code, tax_code_id=code_row.id,
        tax_code_description=code_row.description,
        reference_year=period.year,
        reference_period=(str(period.period_no) if code_row.requires_reference_period else None),
        debit_amount=amount, credit_amount=Decimal("0.00"),
        origin_kind="vat_settlement", origin_settlement_id=settlement.id,
        origin_deadline_id=deadline.id if deadline else None,
        rule_reference=(f"{code_row.description} — {code_row.source_url}"),
        explanation=(
            f"Liquidazione IVA {period.label} validata il "
            f"{settlement.validated_at.date().isoformat() if settlement.validated_at else 'n.d.'}: "
            f"IVA a debito {money(settlement.debit_total)} − IVA a credito "
            f"{money(settlement.credit_total)} − credito precedente "
            f"{money(settlement.prior_credit)} + debito precedente sotto soglia "
            f"{money(settlement.prior_small_debit)}"
            + (f" + interessi 1% {money(settlement.interest_amount)}"
               if settlement.interest_amount else "")
            + f" = {money(amount)} EUR."
        ),
    )
    db.add(line)
    db.flush()
    record_audit(db, actor_id=actor_id, action="fiscal.f24.generate",
                 entity_type="f24_draft", entity_id=draft.id, tenant_id=tenant_id,
                 changes={"settlement_id": str(settlement.id), "amount": money(amount),
                          "tax_code": code_row.code, "period": period.label})
    return {**f24_data(draft), "replayed": False}


def f24_data(draft: F24Draft) -> dict:
    return {
        "id": str(draft.id), "status": draft.status, "currency": draft.currency,
        "settlement_id": str(draft.settlement_id) if draft.settlement_id else None,
        "deadline_id": str(draft.deadline_id) if draft.deadline_id else None,
        "total_debit": money(draft.total_debit), "total_credit": money(draft.total_credit),
        "balance": money(draft.balance),
        "due_date": draft.due_date.isoformat() if draft.due_date else None,
        "taxpayer": draft.taxpayer_snapshot,
        "notes": draft.notes,
        "validated_at": draft.validated_at.isoformat() if draft.validated_at else None,
        "approved_at": draft.approved_at.isoformat() if draft.approved_at else None,
        "exported_at": draft.exported_at.isoformat() if draft.exported_at else None,
        "export_format": draft.export_format,
        "export_fingerprint": draft.export_fingerprint,
        "transmission": {
            "supported": False,
            "note": ("Nessuna trasmissione telematica: richiede canale Entratel/CBI "
                     "autorizzato e specifica tecnica ufficiale verificata."),
        },
        "lines": [{
            "id": str(line.id), "position": line.position, "section": line.section,
            "tax_code": line.tax_code, "tax_code_description": line.tax_code_description,
            "reference_year": line.reference_year, "reference_period": line.reference_period,
            "debit_amount": money(line.debit_amount), "credit_amount": money(line.credit_amount),
            "origin_kind": line.origin_kind,
            "origin_settlement_id": str(line.origin_settlement_id) if line.origin_settlement_id else None,
            "rule_reference": line.rule_reference,
            "explanation": line.explanation,
        } for line in sorted(draft.lines, key=lambda row: row.position)],
    }


def transition_f24(db: Session, *, tenant_id, company: Company, actor_id,
                   draft_id: uuid.UUID, action: str, note: str | None = None) -> dict:
    """Move a draft through validation → approval. Human acts only."""
    draft = db.get(F24Draft, draft_id)
    if draft is None or draft.tenant_id != tenant_id or draft.company_id != company.id:
        raise NotFoundError("F24Draft not found")
    allowed = {
        "validate": (F24Status.VALIDATION_REQUIRED, F24Status.VALIDATED),
        "approve": (F24Status.VALIDATED, F24Status.APPROVED),
    }
    if action not in allowed:
        raise ValidationError("Azione non supportata: validate | approve.",
                              code="invalid_f24_action")
    expected, target = allowed[action]
    if draft.status != expected:
        raise ConflictError(
            f"Transizione non ammessa: la bozza è in stato '{draft.status}', attesa "
            f"'{expected}'.", code="invalid_f24_transition")
    draft.status = target
    if action == "validate":
        draft.validated_by_id, draft.validated_at = actor_id, utcnow()
    else:
        draft.approved_by_id, draft.approved_at = actor_id, utcnow()
    if note:
        draft.notes = (draft.notes or "") + f"\n{action}: {note.strip()[:300]}"
    db.flush()
    record_audit(db, actor_id=actor_id, action=f"fiscal.f24.{action}",
                 entity_type="f24_draft", entity_id=draft.id, tenant_id=tenant_id,
                 changes={"status": target, "note": note})
    return f24_data(draft)


def get_f24_draft(db: Session, *, tenant_id, company: Company,
                  draft_id: uuid.UUID) -> F24Draft:
    draft = db.get(F24Draft, draft_id)
    if draft is None or draft.tenant_id != tenant_id or draft.company_id != company.id:
        raise NotFoundError("F24Draft not found")
    return draft


def export_f24(db: Session, *, tenant_id, company: Company, actor_id,
               draft: F24Draft, fmt: str) -> tuple[str, str, str]:
    """Render an approved draft for review. Internal formats only.

    The draft must be at least `approved`: exporting an unreviewed document
    would let a number leave the platform before a human signed off on it.
    """
    from app.modules.fiscal import f24 as f24_render

    if draft.status not in (F24Status.APPROVED, F24Status.EXPORTED):
        raise ConflictError(
            "L'export richiede una bozza approvata: validazione e approvazione umana "
            "precedono qualsiasi uscita del documento.", code="f24_not_approved")
    content, media_type, digest = f24_render.render(draft, fmt)
    draft.status = F24Status.EXPORTED
    draft.exported_at = utcnow()
    draft.export_format = fmt
    draft.export_fingerprint = digest
    db.flush()
    record_audit(db, actor_id=actor_id, action="fiscal.f24.export",
                 entity_type="f24_draft", entity_id=draft.id, tenant_id=tenant_id,
                 changes={"format": fmt, "fingerprint": digest})
    return content, media_type, digest


# ---------------------------------------------------------------------------
# Snapshot for cockpit / hub / AI tools
# ---------------------------------------------------------------------------

def fiscal_snapshot(db: Session, *, tenant_id, company_id, as_of: date | None = None,
                    year: int | None = None) -> dict:
    """Everything the fiscal UI and the AI tools read — computed once."""
    as_of = as_of or today()
    year = year or as_of.year
    periods = db.scalars(
        _scoped(FiscalPeriod, tenant_id, company_id)
        .where(FiscalPeriod.year == year)
        .order_by(FiscalPeriod.frequency, FiscalPeriod.period_no)
    ).all()
    settlements = db.scalars(
        select(VatSettlement).where(
            VatSettlement.tenant_id == tenant_id, VatSettlement.company_id == company_id,
            VatSettlement.status != SettlementStatus.SUPERSEDED,
        ).order_by(VatSettlement.calculated_at.desc())
    ).all()
    by_period = {row.period_id: row for row in settlements}
    deadlines = db.scalars(
        _scoped(FiscalDeadline, tenant_id, company_id)
        .where(FiscalDeadline.status != DeadlineStatus.CANCELLED)
        .order_by(FiscalDeadline.due_date)
    ).all()
    drafts = db.scalars(
        _scoped(F24Draft, tenant_id, company_id).order_by(F24Draft.created_at.desc())
    ).all()

    pending_entries = db.scalars(
        _scoped(VatEntry, tenant_id, company_id)
        .where(VatEntry.treatment.in_(tuple(BLOCKING_TREATMENTS)))
    ).all()
    confirmed = {row.reverses_entry_id for row in db.scalars(
        _scoped(VatEntry, tenant_id, company_id)
        .where(VatEntry.source == VatSource.SYSTEM_DERIVED)).all()}
    pending_entries = [row for row in pending_entries if row.id not in confirmed]

    latest = None
    for period in reversed(periods):
        settlement = by_period.get(period.id)
        if settlement is not None:
            latest = settlement_data(db, settlement, period=period)
            break

    warnings = _snapshot_warnings(latest, pending_entries, deadlines, as_of)
    return {
        "as_of": as_of.isoformat(), "year": year, "currency": "EUR",
        "engine_version": ENGINE_VERSION,
        "latest_settlement": latest,
        "periods": [{
            **period_data(period),
            "settlement": ({
                "id": str(by_period[period.id].id),
                "status": by_period[period.id].status,
                "version": by_period[period.id].version,
                "net_position": money(by_period[period.id].net_position),
                "payable_amount": money(by_period[period.id].payable_amount),
                "unsupported_count": by_period[period.id].unsupported_count,
            } if period.id in by_period else None),
        } for period in periods],
        "deadlines": [deadline_data(row) for row in deadlines],
        "f24_drafts": [{
            "id": str(row.id), "status": row.status, "balance": money(row.balance),
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "settlement_id": str(row.settlement_id) if row.settlement_id else None,
        } for row in drafts],
        "counters": {
            "periods": len(periods),
            "calculated": sum(1 for p in periods if p.id in by_period),
            "validated": sum(1 for p in periods
                             if p.id in by_period
                             and by_period[p.id].status == SettlementStatus.VALIDATED),
            "pending_entries": len(pending_entries),
            "open_deadlines": sum(1 for row in deadlines
                                  if row.status in (DeadlineStatus.PENDING,
                                                    DeadlineStatus.VALIDATED)),
            "f24_drafts": len(drafts),
        },
        "pending_entries": [vat_entry_data(row) for row in pending_entries[:20]],
        "warnings": warnings,
        "limitations": LIMITATIONS,
        "transmission": {"supported": False,
                         "note": "Nessun F24 viene trasmesso da questa piattaforma."},
    }


def _snapshot_warnings(latest: dict | None, pending: list, deadlines: list,
                       as_of: date) -> list[dict]:
    """Deterministic fiscal warnings for the cockpit and the hub."""
    out: list[dict] = []
    if latest is not None and latest["status"] == SettlementStatus.REVIEW_REQUIRED:
        out.append({
            "code": "vat_settlement_requires_review", "severity": "critical",
            "category": "fiscal", "action_required": True,
            "title": "Liquidazione IVA da rivedere",
            "message": (f"La liquidazione {latest['period']['label']} è calcolata ma richiede "
                        f"verifica: {latest['unsupported_count']} operazioni non utilizzabili."),
            "formula": "voci con trattamento unsupported | requires_review | insufficient_data",
            "formula_version": latest["formula_version"],
            "evidence": {"settlement_id": latest["id"],
                         "unsupported_count": latest["unsupported_count"],
                         "warnings": latest["warnings"]},
        })
    if pending:
        out.append({
            "code": "vat_entries_pending_review", "severity": "warning",
            "category": "data_quality", "action_required": True,
            "title": "Operazioni IVA da verificare",
            "message": (f"{len(pending)} voci IVA attendono una verifica umana "
                        f"(detraibilità o trattamento non determinato)."),
            "formula": "voci IVA con trattamento bloccante e nessuna conferma registrata",
            "formula_version": ENGINE_VERSION,
            "evidence": {"count": len(pending),
                         "entries": [str(row.id) for row in pending[:10]]},
        })
    for row in deadlines:
        if row.status not in (DeadlineStatus.PENDING, DeadlineStatus.VALIDATED):
            continue
        if row.due_date_status == DueDateStatus.REVIEW_REQUIRED:
            out.append({
                "code": "fiscal_due_date_unresolved", "severity": "warning",
                "category": "fiscal", "action_required": True,
                "title": "Scadenza fiscale da confermare",
                "message": ("Il differimento della scadenza non è risolvibile con le regole "
                            "note: confermare manualmente la data di versamento."),
                "formula": "differimento sabato/festivi e 1–20 agosto",
                "formula_version": rules.DUE_DATE_FORMULA_VERSION,
                "evidence": {"deadline_id": str(row.id),
                             "statutory_date": row.statutory_date.isoformat()
                             if row.statutory_date else None},
            })
            continue
        if row.due_date is None or row.amount is None:
            continue
        days = (row.due_date - as_of).days
        if 0 <= days <= 30 and row.status == DeadlineStatus.VALIDATED:
            out.append({
                "code": "fiscal_payment_upcoming", "severity": "info",
                "category": "fiscal", "action_required": False,
                "title": "Versamento fiscale in scadenza",
                "message": (f"Obbligazione IVA validata di {money(row.amount)} EUR in scadenza "
                            f"il {row.due_date.isoformat()} (tra {days} giorni)."),
                "formula": "scadenza validata con data risolta entro 30 giorni",
                "formula_version": rules.DUE_DATE_FORMULA_VERSION,
                "evidence": {"deadline_id": str(row.id), "amount": money(row.amount),
                             "due_date": row.due_date.isoformat()},
            })
        elif days < 0 and row.status == DeadlineStatus.VALIDATED:
            out.append({
                "code": "fiscal_payment_overdue", "severity": "critical",
                "category": "fiscal", "action_required": True,
                "title": "Versamento fiscale scaduto",
                "message": (f"Obbligazione IVA di {money(row.amount)} EUR scaduta il "
                            f"{row.due_date.isoformat()} ({-days} giorni)."),
                "formula": "scadenza validata con data anteriore alla data di analisi",
                "formula_version": rules.DUE_DATE_FORMULA_VERSION,
                "evidence": {"deadline_id": str(row.id), "amount": money(row.amount)},
            })
    return out


def next_obligation(snapshot: dict) -> dict | None:
    """The nearest validated obligation with a resolved date, if any."""
    candidates = [row for row in snapshot["deadlines"]
                  if row["due_date"] and row["amount"] and row["status"] == "validated"]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: row["due_date"])[0]
