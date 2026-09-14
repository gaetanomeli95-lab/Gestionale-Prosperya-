"""Management-control domain service — deterministic, auditable, honest.

Ported from the original Prosperya prototype, adapted to tenant scoping.
Contract: money travels as decimal strings; missing data is NULL, never zero;
every figure carries formula version, sources and quality caveats.
"""
import calendar
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.modules.companies.models import Company
from app.modules.management.models import (
    Actual,
    BudgetVersion,
    ImportBatch,
    ManagementCategory,
)
from app.shared.events import record_audit

FORMULA_VERSION = "management-v1.0"
CENT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999999999.99")
MAX_CSV_BYTES = 1_048_576
MAX_CSV_ROWS = 5000
CSV_HEADERS = ["source_id", "date", "kind", "category", "amount", "currency"]
MONTH_NAMES = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
FORMULAS = {
    "revenue": "Somma degli importi revenue disponibili nel periodo e nella sola azienda.",
    "costs": "Somma degli importi cost disponibili nel periodo e nella sola azienda.",
    "result": "Ricavi disponibili - costi disponibili; null se manca una componente.",
    "margin": "Coincide con il risultato gestionale disponibile; non è EBITDA né utile civilistico.",
    "margin_percent": "Risultato gestionale disponibile / ricavi disponibili * 100; null se ricavi assenti o zero.",
    "budget_result": "Budget ricavi - budget costi; null se mancano mesi o componenti.",
    "variance": "Consuntivo disponibile - budget dello stesso periodo; null senza evidenze mensili comparabili.",
    "comparison": "Stessi mesi di calendario dell'anno precedente; nessun valore storico sintetico.",
}


def parse_money(value: str, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,18}(?:\.[0-9]{1,2})?", value):
        raise ValueError("Importo richiesto come stringa decimale, massimo 18 cifre intere e 2 decimali.")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Importo decimale non valido.") from exc
    if not amount.is_finite() or amount > MAX_MONEY or amount < 0 or (not allow_zero and amount == 0):
        raise ValueError("L'importo deve essere positivo, finito e rappresentabile in NUMERIC(20,2).")
    return amount.quantize(CENT)


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 50
        return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else left - right


def percentage(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 50
        return money(numerator / denominator * Decimal("100"))


# ---------------------------------------------------------------------------
# CSV import — bounded, atomic, idempotent
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedActual:
    source_id: str
    date: date
    kind: str
    category: str
    amount: Decimal
    currency: str

    @property
    def source_hash(self) -> str:
        canonical = json.dumps(
            [self.source_id, self.date.isoformat(), self.kind, self.category,
             money(self.amount), self.currency],
            ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def csv_payload_bytes(content: str) -> bytes:
    if not isinstance(content, str) or not content:
        raise ValueError("CSV vuoto o non testuale.")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Il CSV contiene caratteri Unicode non validi.") from exc
    if len(encoded) > MAX_CSV_BYTES:
        raise ValueError("CSV oltre il limite di 1 MiB.")
    return encoded


def parse_csv(content: str) -> list[ParsedActual]:
    csv_payload_bytes(content)
    if "\x00" in content:
        raise ValueError("Il CSV contiene caratteri non consentiti.")
    try:
        reader = csv.DictReader(io.StringIO(content.removeprefix("﻿"), newline=""), strict=True)
        if reader.fieldnames != CSV_HEADERS:
            raise ValueError("Intestazione richiesta: " + ",".join(CSV_HEADERS))
        rows = []
        seen = set()
        for row_number, raw in enumerate(reader, start=2):
            if len(rows) >= MAX_CSV_ROWS:
                raise ValueError(f"Il CSV supera il limite di {MAX_CSV_ROWS} righe.")
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f"Riga {row_number}: numero di colonne non valido.")
            values = {key: value.strip() for key, value in raw.items()}
            if any(not value or any(ord(char) < 32 for char in value) for value in values.values()):
                raise ValueError(f"Riga {row_number}: campi vuoti o caratteri di controllo.")
            source_id = values["source_id"]
            if len(source_id) > 160 or len(values["category"]) > 120:
                raise ValueError(f"Riga {row_number}: identificativo o categoria troppo lunghi.")
            if source_id in seen:
                raise ValueError(f"Riga {row_number}: source_id duplicato nel file.")
            seen.add(source_id)
            if values["kind"] not in {"revenue", "cost"}:
                raise ValueError(f"Riga {row_number}: kind deve essere revenue o cost.")
            if values["currency"] != "EUR":
                raise ValueError(f"Riga {row_number}: V1 supporta esclusivamente movimenti in EUR.")
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", values["date"]):
                raise ValueError(f"Riga {row_number}: data richiesta nel formato YYYY-MM-DD.")
            try:
                recorded_on = date.fromisoformat(values["date"])
                if not 2000 <= recorded_on.year <= 2100:
                    raise ValueError("Anno fuori intervallo 2000..2100.")
                amount = parse_money(values["amount"])
            except ValueError as exc:
                raise ValueError(f"Riga {row_number}: {exc}") from exc
            rows.append(ParsedActual(source_id, recorded_on, values["kind"],
                                     values["category"], amount, "EUR"))
    except csv.Error as exc:
        raise ValueError("CSV non valido o campo oltre il limite del parser.") from exc
    if not rows:
        raise ValueError("Il CSV deve contenere almeno un movimento.")
    return rows


def _scoped(stmt_model, tenant_id, company_id):
    return select(stmt_model).where(
        stmt_model.tenant_id == tenant_id, stmt_model.company_id == company_id
    )


def batch_data(batch: ImportBatch, *, replayed: bool = False) -> dict:
    return {
        "id": str(batch.id), "filename": batch.filename,
        "idempotency_key": batch.idempotency_key, "payload_hash": batch.payload_hash,
        "row_count": batch.row_count, "duplicate_count": batch.duplicate_count,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "origin": batch.origin, "replayed": replayed,
    }


def _check_idempotency(existing: ImportBatch | None, payload_hash: str) -> dict | None:
    if existing is None:
        return None
    if existing.payload_hash != payload_hash:
        raise ConflictError("Chiave di idempotenza già usata per un CSV diverso.",
                            code="idempotency_conflict")
    return batch_data(existing, replayed=True)


def import_actuals(db: Session, *, tenant_id: UUID, company: Company, actor_id: UUID,
                   filename: str, csv_content: str, idempotency_key: str,
                   origin: str = "csv_import") -> dict:
    payload_hash = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()
    prior = _scoped(ImportBatch, tenant_id, company.id).where(
        ImportBatch.idempotency_key == idempotency_key
    )
    replay = _check_idempotency(db.scalar(prior), payload_hash)
    if replay is not None:
        return replay
    try:
        rows = parse_csv(csv_content)
    except ValueError as exc:
        raise ValidationError(str(exc), code="invalid_csv") from exc
    try:
        with db.begin_nested():
            db.execute(
                select(Company.id)
                .where(Company.id == company.id, Company.tenant_id == tenant_id)
                .with_for_update()
            )
            replay = _check_idempotency(db.scalar(prior), payload_hash)
            if replay is not None:
                return replay
            existing = {
                row.source_id: row
                for row in db.scalars(
                    _scoped(Actual, tenant_id, company.id)
                    .where(Actual.source_id.in_([r.source_id for r in rows]))
                ).all()
            }
            new_rows = []
            for row in rows:
                previous = existing.get(row.source_id)
                if previous is not None:
                    if previous.source_hash != row.source_hash:
                        raise ConflictError(
                            "source_id già presente con contenuto diverso.",
                            code="source_conflict")
                else:
                    new_rows.append(row)
            batch = ImportBatch(
                tenant_id=tenant_id, company_id=company.id, filename=filename,
                idempotency_key=idempotency_key, payload_hash=payload_hash,
                actor_id=actor_id, row_count=len(new_rows),
                duplicate_count=len(rows) - len(new_rows), origin=origin,
            )
            db.add(batch)
            db.flush()
            categories = {
                (item.kind, item.name): item
                for item in db.scalars(
                    _scoped(ManagementCategory, tenant_id, company.id)).all()
            }
            for row in new_rows:
                key = (row.kind, row.category)
                if key not in categories:
                    category = ManagementCategory(
                        tenant_id=tenant_id, company_id=company.id,
                        name=row.category, kind=row.kind)
                    db.add(category)
                    db.flush()
                    categories[key] = category
                db.add(Actual(
                    tenant_id=tenant_id, company_id=company.id,
                    import_batch_id=batch.id, source_id=row.source_id,
                    source_hash=row.source_hash, date=row.date, kind=row.kind,
                    category_id=categories[key].id, category=row.category,
                    amount=row.amount, currency=row.currency))
            db.flush()
            record_audit(db, actor_id=actor_id, action="management.import",
                         entity_type="import_batch", entity_id=batch.id,
                         tenant_id=tenant_id, changes=batch_data(batch))
            return batch_data(batch)
    except IntegrityError as exc:
        replay = _check_idempotency(db.scalar(prior), payload_hash)
        if replay is not None:
            return replay
        raise ConflictError(
            "Conflitto concorrente: riprovare con la stessa chiave e lo stesso CSV.",
            code="import_conflict") from exc


# ---------------------------------------------------------------------------
# Budgets — versioned, never overwritten
# ---------------------------------------------------------------------------

def latest_budgets(rows) -> dict[int, BudgetVersion]:
    result = {}
    for row in rows:
        if row.month not in result or row.version > result[row.month].version:
            result[row.month] = row
    return result


def budget_data(row: BudgetVersion | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.id), "year": row.year, "month": row.month, "version": row.version,
        "revenue": money(row.revenue), "costs": money(row.costs),
        "result": money(difference(row.revenue, row.costs)), "currency": row.currency,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def save_budget(db: Session, *, tenant_id: UUID, company: Company, actor_id: UUID,
                year: int, month: int, revenue: str | None, costs: str | None) -> dict:
    revenue_d = parse_money(revenue, allow_zero=True) if revenue is not None else None
    costs_d = parse_money(costs, allow_zero=True) if costs is not None else None
    if revenue_d is None and costs_d is None:
        raise ValidationError(
            "Specificare almeno una componente di budget; i dati mancanti restano null.",
            code="budget_empty")
    try:
        with db.begin_nested():
            previous = db.scalar(
                _scoped(BudgetVersion, tenant_id, company.id)
                .where(BudgetVersion.year == year, BudgetVersion.month == month)
                .order_by(BudgetVersion.version.desc()).limit(1)
            )
            row = BudgetVersion(
                tenant_id=tenant_id, company_id=company.id,
                year=year, month=month,
                version=previous.version + 1 if previous else 1,
                revenue=revenue_d, costs=costs_d, currency="EUR", actor_id=actor_id,
            )
            db.add(row)
            db.flush()
            record_audit(db, actor_id=actor_id, action="management.budget.version",
                         entity_type="budget_version", entity_id=row.id,
                         tenant_id=tenant_id,
                         changes={"before": budget_data(previous), "after": budget_data(row)})
            return budget_data(row)
    except IntegrityError as exc:
        raise ConflictError("Versione budget concorrente: ricaricare e riprovare.",
                            code="budget_conflict") from exc


def get_budgets(db: Session, *, tenant_id: UUID, company_id: UUID, year: int) -> list[dict]:
    rows = db.scalars(
        _scoped(BudgetVersion, tenant_id, company_id).where(BudgetVersion.year == year)
    ).all()
    return [budget_data(row) for _, row in sorted(latest_budgets(rows).items())]


# ---------------------------------------------------------------------------
# Overview — honest aggregation: missing data is NULL, never zero
# ---------------------------------------------------------------------------

def observed_sum(rows, kind: str) -> Decimal | None:
    amounts = [row.amount for row in rows if row.kind == kind]
    return sum(amounts, Decimal("0.00")) if amounts else None


def period_dates(year: int, through_month: int) -> tuple[date, date]:
    if not 2000 <= year <= 2100 or not 1 <= through_month <= 12:
        raise ValueError("Periodo fuori intervallo.")
    return date(year, 1, 1), date(year, through_month,
                                 calendar.monthrange(year, through_month)[1])


def build_overview(rows, budget_rows, previous_rows, year: int, through_month: int) -> dict:
    start, end = period_dates(year, through_month)
    rows = [row for row in rows if start <= row.date <= end]
    budgets = latest_budgets(
        [row for row in budget_rows if row.year == year and row.month <= through_month])
    previous_start = date(year - 1, 1, 1)
    previous_end = date(year - 1, through_month,
                        calendar.monthrange(year - 1, through_month)[1])
    previous_rows = [row for row in previous_rows if previous_start <= row.date <= previous_end]
    revenue, costs = observed_sum(rows, "revenue"), observed_sum(rows, "cost")
    result = difference(revenue, costs)
    monthly, type_evidence = [], []
    for month in range(1, through_month + 1):
        month_rows = [row for row in rows if row.date.month == month]
        month_revenue, month_costs = observed_sum(month_rows, "revenue"), observed_sum(month_rows, "cost")
        budget = budgets.get(month)
        monthly.append({
            "month": month, "revenue": money(month_revenue), "costs": money(month_costs),
            "result": money(difference(month_revenue, month_costs)),
            "budget_revenue": money(budget.revenue) if budget else None,
            "budget_costs": money(budget.costs) if budget else None,
        })
        type_evidence.append({"month": month, "revenue": month_revenue is not None,
                              "costs": month_costs is not None})
    budget_revenue = (
        sum((budgets[m].revenue for m in range(1, through_month + 1)), Decimal("0.00"))
        if all(m in budgets and budgets[m].revenue is not None for m in range(1, through_month + 1))
        else None
    )
    budget_costs = (
        sum((budgets[m].costs for m in range(1, through_month + 1)), Decimal("0.00"))
        if all(m in budgets and budgets[m].costs is not None for m in range(1, through_month + 1))
        else None
    )
    budget_result = difference(budget_revenue, budget_costs)
    revenue_evidence = all(item["revenue"] for item in type_evidence)
    cost_evidence = all(item["costs"] for item in type_evidence)
    cost_categories: dict[str, Decimal] = {}
    for row in rows:
        if row.kind == "cost":
            cost_categories[row.category] = cost_categories.get(row.category, Decimal("0.00")) + row.amount
    previous_revenue, previous_costs = observed_sum(previous_rows, "revenue"), observed_sum(previous_rows, "cost")
    previous_result = difference(previous_revenue, previous_costs)
    previous_revenue_evidence = all(
        any(row.kind == "revenue" and row.date.month == m for row in previous_rows)
        for m in range(1, through_month + 1))
    previous_cost_evidence = all(
        any(row.kind == "cost" and row.date.month == m for row in previous_rows)
        for m in range(1, through_month + 1))
    revenue_change = difference(revenue, previous_revenue) if revenue_evidence and previous_revenue_evidence else None
    cost_change = difference(costs, previous_costs) if cost_evidence and previous_cost_evidence else None
    result_change = (
        difference(result, previous_result)
        if revenue_evidence and cost_evidence and previous_revenue_evidence and previous_cost_evidence
        else None
    )
    covered_months = [item["month"] for item in type_evidence if item["revenue"] or item["costs"]]
    issues = ["Fonti disponibili non certificate complete; presenza di righe e mesi non attesta completezza.",
              "Il risultato gestionale disponibile non è EBITDA, utile civilistico o saldo di cassa."]
    if not revenue_evidence or not cost_evidence:
        issues.append("Mancano evidenze di ricavi o costi in uno o più mesi; assenza di righe non equivale a zero.")
    if budget_revenue is None or budget_costs is None:
        issues.append("Budget incompleto: componenti o mesi mancanti restano null.")
    if not previous_revenue_evidence or not previous_cost_evidence:
        issues.append("Confronto storico limitato: mancano evidenze mensili nello stesso periodo dell'anno precedente.")
    overview = {
        "period": {"year": year, "through_month": through_month,
                   "label": f"Gen–{MONTH_NAMES[through_month]} {year}",
                   "start": start.isoformat(), "end": end.isoformat()},
        "currency": "EUR", "revenue": money(revenue), "costs": money(costs),
        "margin": money(result), "margin_percent": percentage(result, revenue),
        "result": money(result),
        "budget": {"revenue": money(budget_revenue), "costs": money(budget_costs),
                   "result": money(budget_result),
                   "revenue_variance": money(difference(revenue, budget_revenue)) if revenue_evidence else None,
                   "cost_variance": money(difference(costs, budget_costs)) if cost_evidence else None,
                   "result_variance": money(difference(result, budget_result)) if revenue_evidence and cost_evidence else None},
        "monthly": monthly,
        "cost_categories": [{"category": category, "amount": money(amount)}
                            for category, amount in sorted(cost_categories.items(), key=lambda item: (-item[1], item[0]))],
        "comparison": {"basis": "same_calendar_period_previous_year",
                       "period": {"start": previous_start.isoformat(), "end": previous_end.isoformat(),
                                  "label": f"Gen–{MONTH_NAMES[through_month]} {year - 1}"},
                       "revenue": money(previous_revenue), "costs": money(previous_costs),
                       "result": money(previous_result),
                       "revenue_change": money(revenue_change), "cost_change": money(cost_change),
                       "result_change": money(result_change),
                       "revenue_change_percent": percentage(revenue_change, previous_revenue),
                       "cost_change_percent": percentage(cost_change, previous_costs),
                       "quality": "partial" if previous_rows else "empty",
                       "source_ids": [str(row.id) for row in previous_rows]},
        "quality": {"status": "partial" if rows else "empty", "certified_complete": False,
                    "covered_months": len(covered_months), "expected_months": through_month,
                    "months_with_sources": covered_months, "type_evidence": type_evidence,
                    "issues": issues},
        "alerts": [],
        "trace": {"formula_version": FORMULA_VERSION, "formulas": FORMULAS,
                  "source_count": len(rows), "source_ids": [str(row.id) for row in rows],
                  "budget_version_ids": [str(row.id) for row in budgets.values()]},
    }
    overview["alerts"] = derive_alerts(overview)
    return overview


def derive_alerts(overview: dict) -> list[dict]:
    alerts = []
    monthly = overview["monthly"]
    recent = monthly[-3:]
    if len(recent) == 3 and all(item["revenue"] is not None for item in recent):
        values = [Decimal(item["revenue"]) for item in recent]
        if values[0] > values[1] > values[2]:
            alerts.append({"code": "revenue_declining", "severity": "warning",
                           "title": "Ricavi disponibili in calo",
                           "message": "Calo nei tre ultimi mesi osservati; verificare la completezza prima di decidere.",
                           "months": [item["month"] for item in recent],
                           "formula": "R(m-2) > R(m-1) > R(m)"})
    if overview["budget"]["cost_variance"] is not None and Decimal(overview["budget"]["cost_variance"]) > 0:
        alerts.append({"code": "costs_over_budget", "severity": "warning",
                       "title": "Costi disponibili oltre budget",
                       "message": "I costi osservati superano il budget dello stesso periodo; dato non certificato completo.",
                       "amount": overview["budget"]["cost_variance"],
                       "formula": "costi disponibili - budget costi > 0"})
    if overview["result"] is not None and Decimal(overview["result"]) < 0:
        alerts.append({"code": "negative_available_result", "severity": "danger",
                       "title": "Risultato gestionale disponibile negativo",
                       "message": "I costi disponibili superano i ricavi disponibili; non equivale a perdita civilistica.",
                       "formula": "ricavi disponibili - costi disponibili < 0"})
    if overview["quality"]["status"] == "empty":
        alerts.append({"code": "no_sources", "severity": "info", "title": "Nessuna fonte nel periodo",
                       "message": "Importare fonti per calcolare indicatori; nessun valore è assunto pari a zero."})
    return alerts


def get_overview(db: Session, *, tenant_id: UUID, company_id: UUID,
                 year: int, through_month: int) -> dict:
    start, end = period_dates(year, through_month)
    previous_start = date(year - 1, 1, 1)
    previous_end = date(year - 1, through_month,
                        calendar.monthrange(year - 1, through_month)[1])
    rows = db.scalars(
        _scoped(Actual, tenant_id, company_id)
        .where(Actual.date.between(start, end)).order_by(Actual.date, Actual.id)
    ).all()
    previous_rows = db.scalars(
        _scoped(Actual, tenant_id, company_id)
        .where(Actual.date.between(previous_start, previous_end))
        .order_by(Actual.date, Actual.id)
    ).all()
    budgets = db.scalars(
        _scoped(BudgetVersion, tenant_id, company_id)
        .where(BudgetVersion.year == year, BudgetVersion.month <= through_month)
    ).all()
    return build_overview(rows, budgets, previous_rows, year, through_month)


def get_actuals(db: Session, *, tenant_id: UUID, company_id: UUID, year: int,
                through_month: int = 12) -> dict:
    start, end = period_dates(year, through_month)
    rows = db.scalars(
        _scoped(Actual, tenant_id, company_id)
        .where(Actual.date.between(start, end)).order_by(Actual.date, Actual.id)
    ).all()
    return {
        "formula_version": FORMULA_VERSION,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "currency": "EUR", "quality": "partial" if rows else "empty",
        "rows": [{
            "id": str(row.id), "source_id": row.source_id,
            "import_batch_id": str(row.import_batch_id), "date": row.date.isoformat(),
            "kind": row.kind, "category": row.category,
            "category_id": str(row.category_id),
            "cost_center_id": str(row.cost_center_id) if row.cost_center_id else None,
            "amount": money(row.amount), "currency": row.currency,
            "source_hash": row.source_hash,
            "created_at": row.created_at.isoformat(),
            "formula_version": FORMULA_VERSION,
        } for row in rows],
    }
