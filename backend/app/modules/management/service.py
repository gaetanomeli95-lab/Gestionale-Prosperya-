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
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.companies.models import Company
from app.modules.management.models import (
    Actual,
    BudgetVersion,
    CostCenter,
    ImportBatch,
    ManagementCategory,
)
from app.shared.events import record_audit

# Canonical monetary primitives live in app.shared.money; re-exported here so
# existing callers (and the assistant tools) keep a single import surface.
from app.shared.money import (  # noqa: F401 — intentional re-export
    CENT,
    MAX_MONEY,
    difference,
    money,
    parse_money,
    percentage,
)

FORMULA_VERSION = "management-v1.0"
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


# ---------------------------------------------------------------------------
# Classification: cost nature + cost centers (reference data, mutable)
# ---------------------------------------------------------------------------

CONTRIBUTION_FORMULA_VERSION = "contribution-v1.0"
COST_NATURES = ("fixed", "variable")
CONTRIBUTION_FORMULAS = {
    "variable_costs": "Somma dei costi disponibili le cui categorie sono classificate 'variable'.",
    "fixed_costs": "Somma dei costi disponibili le cui categorie sono classificate 'fixed'.",
    "contribution_margin": "Ricavi disponibili - costi variabili; null se manca una componente.",
    "contribution_margin_ratio": "Margine di contribuzione / ricavi disponibili; null se ricavi assenti o zero.",
    "break_even_revenue": "Costi fissi / indice di margine di contribuzione; calcolabile solo con TUTTI i costi classificati e indice > 0.",
    "break_even_coverage": "Ricavi disponibili / ricavi di break-even; > 1 significa punto di pareggio superato.",
    "cost_center": "Ripartizione per centro di costo assegnato alla categoria; i costi senza centro restano 'non attribuiti'.",
}


def cost_center_data(row: CostCenter) -> dict:
    return {"id": str(row.id), "code": row.code, "name": row.name,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def category_data(row: ManagementCategory, centers: dict) -> dict:
    center = centers.get(row.cost_center_id)
    return {
        "id": str(row.id), "name": row.name, "kind": row.kind,
        "cost_nature": row.cost_nature,
        "cost_center_id": str(row.cost_center_id) if row.cost_center_id else None,
        "cost_center_code": center.code if center else None,
        "cost_center_name": center.name if center else None,
    }


def _centers_by_id(db: Session, tenant_id: UUID, company_id: UUID) -> dict:
    return {row.id: row for row in
            db.scalars(_scoped(CostCenter, tenant_id, company_id)).all()}


def list_cost_centers(db: Session, *, tenant_id: UUID, company_id: UUID) -> list[dict]:
    rows = db.scalars(
        _scoped(CostCenter, tenant_id, company_id).order_by(CostCenter.code)
    ).all()
    return [cost_center_data(row) for row in rows]


def create_cost_center(db: Session, *, tenant_id: UUID, company: Company, actor_id: UUID,
                       code: str, name: str) -> dict:
    row = CostCenter(tenant_id=tenant_id, company_id=company.id, code=code, name=name)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Centro di costo già presente con questo codice.",
                            code="cost_center_exists") from exc
    record_audit(db, actor_id=actor_id, action="management.cost_center.create",
                 entity_type="cost_center", entity_id=row.id, tenant_id=tenant_id,
                 changes=cost_center_data(row))
    return cost_center_data(row)


def list_categories(db: Session, *, tenant_id: UUID, company_id: UUID) -> dict:
    centers = _centers_by_id(db, tenant_id, company_id)
    rows = db.scalars(
        _scoped(ManagementCategory, tenant_id, company_id)
        .order_by(ManagementCategory.kind, ManagementCategory.name)
    ).all()
    items = [category_data(row, centers) for row in rows]
    unclassified = [i["name"] for i in items if i["kind"] == "cost" and i["cost_nature"] is None]
    return {
        "categories": items,
        "cost_natures": list(COST_NATURES),
        "unclassified_costs": unclassified,
        "classification_complete": not unclassified and any(i["kind"] == "cost" for i in items),
        "note": ("La classificazione è dato di riferimento modificabile: i consuntivi "
                 "restano append-only e gli indicatori si ricalcolano dalle fonti."),
    }


def classify_category(db: Session, *, tenant_id: UUID, company: Company, actor_id: UUID,
                      category_id: UUID, cost_nature: str | None,
                      cost_center_id: UUID | None) -> dict:
    category = db.get(ManagementCategory, category_id)
    if (category is None or category.tenant_id != tenant_id
            or category.company_id != company.id):
        raise NotFoundError("Category not found")
    if cost_nature is not None and cost_nature not in COST_NATURES:
        raise ValidationError("Natura del costo non valida: fixed | variable.",
                              code="invalid_cost_nature")
    if cost_nature is not None and category.kind != "cost":
        raise ValidationError("La natura fisso/variabile si applica solo alle categorie di costo.",
                              code="nature_on_revenue")
    if cost_center_id is not None:
        center = db.get(CostCenter, cost_center_id)
        if (center is None or center.tenant_id != tenant_id
                or center.company_id != company.id or not center.is_active):
            raise ValidationError("Centro di costo inesistente o disattivato.",
                                  code="invalid_cost_center")
    centers = _centers_by_id(db, tenant_id, company.id)
    before = category_data(category, centers)
    category.cost_nature = cost_nature
    category.cost_center_id = cost_center_id
    db.flush()
    centers = _centers_by_id(db, tenant_id, company.id)
    after = category_data(category, centers)
    record_audit(db, actor_id=actor_id, action="management.category.classify",
                 entity_type="management_category", entity_id=category.id,
                 tenant_id=tenant_id, changes={"before": before, "after": after})
    return after


# ---------------------------------------------------------------------------
# Contribution margin + break-even — refuse to compute on partial classification
# ---------------------------------------------------------------------------

def build_contribution(rows, categories, centers, *, year: int, through_month: int) -> dict:
    """Contribution margin, break-even and cost-center split.

    Deliberate refusals: with even one unclassified cost category the variable
    and fixed totals are `null` (a partial split would understate costs), and
    break-even is `not_calculable` with the reason instead of a comfortable
    number.
    """
    start, end = period_dates(year, through_month)
    rows = [row for row in rows if start <= row.date <= end]
    by_id = {category.id: category for category in categories}

    revenue = observed_sum(rows, "revenue")
    cost_rows = [row for row in rows if row.kind == "cost"]
    natures: dict[str, list[Decimal]] = {"fixed": [], "variable": []}
    unclassified: dict[str, Decimal] = {}
    for row in cost_rows:
        category = by_id.get(row.category_id)
        nature = category.cost_nature if category is not None else None
        if nature in natures:
            natures[nature].append(row.amount)
        else:
            unclassified[row.category] = unclassified.get(row.category, Decimal("0.00")) + row.amount

    complete = not unclassified and bool(cost_rows)
    variable_costs = sum(natures["variable"], Decimal("0.00")) if complete else None
    fixed_costs = sum(natures["fixed"], Decimal("0.00")) if complete else None
    contribution = difference(revenue, variable_costs)
    ratio = None
    if contribution is not None and revenue is not None and revenue > 0:
        ratio = (contribution / revenue).quantize(Decimal("0.0001"))

    reasons: list[str] = []
    break_even = None
    coverage = None
    if not cost_rows:
        reasons.append("Nessun costo disponibile nel periodo: break-even non calcolabile.")
    if unclassified:
        reasons.append(
            "Categorie di costo non classificate come fisse o variabili: "
            + ", ".join(sorted(unclassified)) + ". Nessuna ripartizione viene stimata.")
    if revenue is None:
        reasons.append("Ricavi disponibili assenti: indice di margine non calcolabile.")
    if ratio is not None and ratio <= 0:
        reasons.append("Indice di margine di contribuzione non positivo: "
                       "il break-even non esiste alle condizioni osservate.")
    if complete and ratio is not None and ratio > 0 and fixed_costs is not None:
        break_even = (fixed_costs / ratio).quantize(CENT)
        if revenue is not None and break_even > 0:
            coverage = (revenue / break_even).quantize(Decimal("0.0001"))
        elif break_even == 0:
            reasons.append("Nessun costo fisso classificato nel periodo: il pareggio è già "
                           "raggiunto al primo euro di margine di contribuzione, "
                           "quindi la copertura non è un rapporto significativo.")

    center_rows: dict[str, dict] = {}
    for row in rows:
        category = by_id.get(row.category_id)
        center = centers.get(category.cost_center_id) if category is not None else None
        key = str(center.id) if center is not None else "unassigned"
        entry = center_rows.setdefault(key, {
            "cost_center_id": str(center.id) if center is not None else None,
            "code": center.code if center is not None else None,
            "name": center.name if center is not None else "Non attribuiti",
            "revenue": Decimal("0.00"), "costs": Decimal("0.00"),
            "has_revenue": False, "has_costs": False,
        })
        if row.kind == "revenue":
            entry["revenue"] += row.amount
            entry["has_revenue"] = True
        else:
            entry["costs"] += row.amount
            entry["has_costs"] = True

    cost_centers = []
    for entry in sorted(center_rows.values(), key=lambda e: (e["code"] is None, e["code"] or "")):
        center_revenue = entry["revenue"] if entry["has_revenue"] else None
        center_costs = entry["costs"] if entry["has_costs"] else None
        cost_centers.append({
            "cost_center_id": entry["cost_center_id"], "code": entry["code"],
            "name": entry["name"], "revenue": money(center_revenue),
            "costs": money(center_costs),
            "result": money(difference(center_revenue, center_costs)),
        })

    return {
        "period": {"year": year, "through_month": through_month,
                   "label": f"Gen–{MONTH_NAMES[through_month]} {year}",
                   "start": start.isoformat(), "end": end.isoformat()},
        "currency": "EUR",
        "revenue": money(revenue),
        "variable_costs": money(variable_costs),
        "fixed_costs": money(fixed_costs),
        "contribution_margin": money(contribution),
        "contribution_margin_percent": percentage(contribution, revenue),
        "contribution_margin_ratio": format(ratio, "f") if ratio is not None else None,
        "break_even_revenue": money(break_even),
        "break_even_coverage": format(coverage, "f") if coverage is not None else None,
        "break_even_status": "available" if break_even is not None else "not_calculable",
        "status": "available" if complete else "not_calculable",
        "unclassified_costs": [{"category": name, "amount": money(amount)}
                               for name, amount in sorted(unclassified.items())],
        "cost_centers": cost_centers,
        "reasons": reasons,
        "alerts": [],
        "quality": {
            "classification_complete": complete,
            "certified_complete": False,
            "cost_rows": len(cost_rows),
            "issues": [
                "Il margine di contribuzione è calcolato sulle sole fonti disponibili "
                "e classificate: non è un margine civilistico né un EBITDA.",
                *reasons,
            ],
        },
        "trace": {
            "formula_version": CONTRIBUTION_FORMULA_VERSION,
            "formulas": CONTRIBUTION_FORMULAS,
            "source_count": len(rows),
            "source_ids": [str(row.id) for row in rows],
            "category_ids": [str(category.id) for category in categories],
        },
    }


def derive_contribution_alerts(contribution: dict) -> list[dict]:
    alerts = []
    if contribution["break_even_coverage"] is not None:
        coverage = Decimal(contribution["break_even_coverage"])
        if coverage < Decimal("1"):
            alerts.append({
                "code": "break_even_not_reached", "severity": "warning",
                "title": "Punto di pareggio non raggiunto",
                "message": (f"I ricavi disponibili coprono il {percentage(coverage, Decimal('1'))}% "
                            f"dei ricavi di break-even ({contribution['break_even_revenue']} EUR) "
                            f"nel periodo osservato."),
                "formula": CONTRIBUTION_FORMULAS["break_even_coverage"],
            })
    if contribution["status"] == "not_calculable" and contribution["unclassified_costs"]:
        alerts.append({
            "code": "costs_unclassified", "severity": "info",
            "title": "Costi non classificati",
            "message": ("Classificare le categorie come fisse o variabili per ottenere "
                        "margine di contribuzione e break-even; nessuna ripartizione è stimata."),
            "formula": CONTRIBUTION_FORMULAS["variable_costs"],
        })
    return alerts


def get_contribution(db: Session, *, tenant_id: UUID, company_id: UUID,
                     year: int, through_month: int) -> dict:
    start, end = period_dates(year, through_month)
    rows = db.scalars(
        _scoped(Actual, tenant_id, company_id)
        .where(Actual.date.between(start, end)).order_by(Actual.date, Actual.id)
    ).all()
    categories = db.scalars(_scoped(ManagementCategory, tenant_id, company_id)).all()
    centers = _centers_by_id(db, tenant_id, company_id)
    contribution = build_contribution(rows, categories, centers,
                                      year=year, through_month=through_month)
    contribution["alerts"] = derive_contribution_alerts(contribution)
    return contribution


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
