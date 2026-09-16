"""Controlling & early-warning service — orchestration over pure engines.

The engines (`metrics`, `ew`, `scenarios`) are pure functions; this module
owns the database reads that assemble their facts, the durable alert
lifecycle and every audited human transition. Money travels as decimal
strings; a missing input is `null`, never zero.

Separation of concerns (ADR-022): management metrics describe performance,
early-warning rules surface *segnali da verificare* anchored to the CCII —
nothing here concludes that a company is in crisis.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.companies.models import Company
from app.modules.controlling import ew, metrics, rules_seed, scenarios
from app.modules.controlling.models import (
    AlertStatus,
    ControllingAlert,
    DebtFacility,
    DebtServiceLine,
    InstalmentStatus,
)
from app.modules.management import service as management_service
from app.modules.treasury import service as treasury_service
from app.modules.treasury.models import OpenItem
from app.shared.events import record_audit
from app.shared.mixins import today, utcnow
from app.shared.money import money, parse_money, total

ENGINE_VERSION = metrics.ENGINE_VERSION

LIMITATIONS = [
    "Gli indicatori sono calcolati sulle sole obbligazioni datate registrate: "
    "non estrapolano trend né stimano ricavi/costi futuri.",
    "Il DSCR è un proxy gestionale (CFADS da partite aperte), non il flusso "
    "civilistico: la soglia è un parametro operativo dichiarato, non un valore di legge.",
    "I segnali di early warning indicano condizioni da verificare ai sensi del "
    "D.Lgs. 14/2019: non costituiscono una determinazione di stato di crisi.",
    "Gli scenari ricalcolano copie dei dati con ipotesi esplicite: i consuntivi "
    "storici non vengono mai modificati.",
    "Un dato mancante produce null o insufficient_data, mai uno zero comodo.",
]


def company_or_404(db: Session, company_id: uuid.UUID, tenant_id) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id or company.deleted_at is not None:
        raise NotFoundError("Company not found.")
    return company


def _scoped(model, tenant_id, company_id):
    return select(model).where(model.tenant_id == tenant_id,
                               model.company_id == company_id)


def _owned(db: Session, model, entity_id: uuid.UUID, tenant_id, company_id):
    row = db.get(model, entity_id)
    if row is None or row.tenant_id != tenant_id or row.company_id != company_id:
        raise NotFoundError(f"{model.__name__} not found")
    return row


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------

def facility_data(row: DebtFacility, lines: list[DebtServiceLine] | None = None) -> dict:
    data = {
        "id": str(row.id), "name": row.name, "lender_name": row.lender_name,
        "facility_type": row.facility_type,
        "outstanding_principal": money(row.outstanding_principal),
        "currency": row.currency, "notes": row.notes, "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if lines is not None:
        scheduled = [ln for ln in lines if ln.status == InstalmentStatus.SCHEDULED]
        data["lines"] = [debt_line_data(ln) for ln in
                         sorted(lines, key=lambda ln: (ln.due_date, ln.instalment_no))]
        data["scheduled_count"] = len(scheduled)
        data["scheduled_service"] = money(total([ln.principal + ln.interest
                                                 for ln in scheduled]))
    return data


def debt_line_data(row: DebtServiceLine) -> dict:
    return {
        "id": str(row.id), "facility_id": str(row.facility_id),
        "instalment_no": row.instalment_no, "due_date": row.due_date.isoformat(),
        "principal": money(row.principal), "interest": money(row.interest),
        "service": money(row.principal + row.interest),
        "currency": row.currency, "status": row.status,
        "settled_on": row.settled_on.isoformat() if row.settled_on else None,
        "status_note": row.status_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def alert_data(row: ControllingAlert) -> dict:
    return {
        "id": str(row.id), "kind": row.kind, "rule_code": row.rule_code,
        "rule_version": row.rule_version, "severity": row.severity,
        "title": row.title, "message": row.message, "formula": row.formula,
        "formula_version": row.formula_version, "evidence": row.evidence,
        "status": row.status,
        "detected_at": row.detected_at.isoformat(),
        "first_detected_at": row.first_detected_at.isoformat(),
        "acknowledged_at": (row.acknowledged_at.isoformat()
                            if row.acknowledged_at else None),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolution_kind": row.resolution_kind,
        "resolution_note": row.resolution_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# Debt facilities & service lines (reference data + tracked transitions)
# ---------------------------------------------------------------------------

def list_facilities(db: Session, *, tenant_id, company_id) -> dict:
    facilities = db.scalars(
        _scoped(DebtFacility, tenant_id, company_id)
        .order_by(DebtFacility.is_active.desc(), DebtFacility.name)
    ).all()
    lines = db.scalars(
        _scoped(DebtServiceLine, tenant_id, company_id)
        .order_by(DebtServiceLine.due_date, DebtServiceLine.instalment_no)
    ).all()
    by_facility: dict[uuid.UUID, list[DebtServiceLine]] = {}
    for line in lines:
        by_facility.setdefault(line.facility_id, []).append(line)
    return {
        "facilities": [facility_data(f, by_facility.get(f.id, [])) for f in facilities],
        "counters": {
            "facilities": len(facilities),
            "instalments": len(lines),
            "scheduled": sum(1 for ln in lines if ln.status == InstalmentStatus.SCHEDULED),
            "paid": sum(1 for ln in lines if ln.status == InstalmentStatus.PAID),
            "waived": sum(1 for ln in lines if ln.status == InstalmentStatus.WAIVED),
        },
        "engine_version": ENGINE_VERSION,
    }


def create_facility(db: Session, *, tenant_id, company: Company, actor_id,
                    name: str, facility_type: str, lender_name: str | None,
                    outstanding_principal: str | None, notes: str | None) -> dict:
    principal = (parse_money(outstanding_principal, allow_zero=True)
                 if outstanding_principal is not None else None)
    row = DebtFacility(
        tenant_id=tenant_id, company_id=company.id, name=name.strip(),
        lender_name=(lender_name or None), facility_type=facility_type,
        outstanding_principal=principal, notes=notes, created_by_id=actor_id)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Esiste già una linea di debito con questo nome.",
                            code="duplicate_facility") from exc
    record_audit(db, actor_id=actor_id, action="controlling.facility.create",
                 entity_type="debt_facility", entity_id=row.id, tenant_id=tenant_id,
                 changes={"name": row.name, "facility_type": row.facility_type,
                          "outstanding_principal": money(row.outstanding_principal)})
    return facility_data(row, [])


def update_facility(db: Session, *, tenant_id, company: Company, actor_id,
                    facility_id: uuid.UUID, changes: dict) -> dict:
    """Reference-data correction — audited, never a rewrite of instalments."""
    row = _owned(db, DebtFacility, facility_id, tenant_id, company.id)
    before = facility_data(row)
    if "name" in changes and changes["name"] is not None:
        row.name = changes["name"].strip()
    if "lender_name" in changes:
        row.lender_name = changes["lender_name"]
    if "outstanding_principal" in changes:
        value = changes["outstanding_principal"]
        row.outstanding_principal = (parse_money(value, allow_zero=True)
                                     if value is not None else None)
    if "notes" in changes:
        row.notes = changes["notes"]
    if "is_active" in changes and changes["is_active"] is not None:
        row.is_active = bool(changes["is_active"])
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Esiste già una linea di debito con questo nome.",
                            code="duplicate_facility") from exc
    after = facility_data(row)
    diff = {k: {"old": before[k], "new": after[k]}
            for k in after if before.get(k) != after.get(k)}
    record_audit(db, actor_id=actor_id, action="controlling.facility.update",
                 entity_type="debt_facility", entity_id=row.id, tenant_id=tenant_id,
                 changes=diff)
    return after


def add_instalment(db: Session, *, tenant_id, company: Company, actor_id,
                   facility_id: uuid.UUID, instalment_no: int, due_date: date,
                   principal: str, interest: str) -> dict:
    facility = _owned(db, DebtFacility, facility_id, tenant_id, company.id)
    p = parse_money(principal, allow_zero=True)
    i = parse_money(interest, allow_zero=True)
    if p == 0 and i == 0:
        raise ValidationError("Quota capitale e interessi non possono essere entrambe zero.",
                              code="empty_instalment")
    row = DebtServiceLine(
        tenant_id=tenant_id, company_id=company.id, facility_id=facility.id,
        instalment_no=instalment_no, due_date=due_date, principal=p, interest=i)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"La rata n. {instalment_no} esiste già per questa linea di debito.",
            code="duplicate_instalment") from exc
    record_audit(db, actor_id=actor_id, action="controlling.instalment.add",
                 entity_type="debt_service_line", entity_id=row.id, tenant_id=tenant_id,
                 changes={"facility": facility.name, "instalment_no": instalment_no,
                          "due_date": due_date.isoformat(),
                          "service": money(p + i)})
    return debt_line_data(row)


def settle_instalment(db: Session, *, tenant_id, company: Company, actor_id,
                      line_id: uuid.UUID, action: str,
                      settled_on: date | None, note: str | None) -> dict:
    """Tracked transition: scheduled → paid | waived. Never silent edits."""
    row = _owned(db, DebtServiceLine, line_id, tenant_id, company.id)
    if row.status != InstalmentStatus.SCHEDULED:
        raise ConflictError(f"La rata è già '{row.status}': transizione non ammessa.",
                            code="invalid_transition")
    if action == "paid":
        row.status = InstalmentStatus.PAID
        row.settled_on = settled_on or today()
        row.status_note = note
    elif action == "waived":
        if not note or len(note.strip()) < 5:
            raise ValidationError("Motivazione obbligatoria per sospendere una rata.",
                                  code="reason_required")
        row.status = InstalmentStatus.WAIVED
        row.settled_on = None
        row.status_note = note.strip()[:300]
    else:
        raise ValidationError("Azione non valida: ammesse 'paid' o 'waived'.",
                              code="invalid_action")
    db.flush()
    record_audit(db, actor_id=actor_id, action=f"controlling.instalment.{action}",
                 entity_type="debt_service_line", entity_id=row.id, tenant_id=tenant_id,
                 changes={"status": row.status,
                          "settled_on": row.settled_on.isoformat() if row.settled_on else None,
                          "note": row.status_note})
    return debt_line_data(row)


# ---------------------------------------------------------------------------
# Fact assembly — the only place engines meet the database
# ---------------------------------------------------------------------------

def _item_residuals(db: Session, tenant_id, company_id) -> list[dict]:
    """Open items with residual > 0, reduced to what the engines need."""
    by_item, _ = treasury_service._allocations_by(db, tenant_id, company_id)
    rows = db.scalars(_scoped(OpenItem, tenant_id, company_id)).all()
    out = []
    for item in rows:
        state = treasury_service.item_state(item, by_item.get(item.id, []))
        if state.residual <= 0:
            continue
        out.append({"id": str(item.id), "direction": item.direction,
                    "due_date": item.due_date, "residual": state.residual,
                    "counterparty_name": item.counterparty_name,
                    "category": (item.category or "").strip().lower(),
                    "source": item.source})
    return out


def _debt_facts(db: Session, tenant_id, company_id) -> list[metrics.DebtLineFact]:
    rows = db.scalars(
        _scoped(DebtServiceLine, tenant_id, company_id)
        .order_by(DebtServiceLine.due_date, DebtServiceLine.instalment_no)
    ).all()
    facilities = {f.id: f for f in db.scalars(
        _scoped(DebtFacility, tenant_id, company_id)).all()}
    return [metrics.DebtLineFact(
        id=str(row.id), facility_id=str(row.facility_id),
        facility_name=(facilities[row.facility_id].name
                       if row.facility_id in facilities else "?"),
        due_date=row.due_date, principal=row.principal, interest=row.interest,
        status=row.status) for row in rows]


def _flow_facts(items: list[dict],
                debt_lines: list[metrics.DebtLineFact]) -> list[metrics.FlowFact]:
    """Dated obligations only: open-item residuals + scheduled debt service."""
    flows: list[metrics.FlowFact] = []
    for item in items:
        if item["direction"] == "receivable":
            nature = "trade_receivable"
        elif item["source"] == "fiscal":
            nature = "fiscal"
        elif item["category"] in ew.FINANCIAL_CATEGORIES:
            nature = "financial"
        else:
            nature = "trade_payable"
        flows.append(metrics.FlowFact(
            id=item["id"], nature=nature,
            direction="inflow" if item["direction"] == "receivable" else "outflow",
            due_date=item["due_date"], amount=item["residual"],
            counterparty_name=item["counterparty_name"], source="open_item"))
    for line in debt_lines:
        if line.status != InstalmentStatus.SCHEDULED:
            continue
        flows.append(metrics.FlowFact(
            id=line.id, nature="debt_service", direction="outflow",
            due_date=line.due_date, amount=line.service,
            counterparty_name=line.facility_name, source="debt_service"))
    return flows


def _opening_balance(db: Session, tenant_id, company_id, as_of: date):
    position = treasury_service.cash_position(db, tenant_id=tenant_id,
                                              company_id=company_id, as_of=as_of)
    amount = Decimal(position["amount"]) if position["amount"] is not None else None
    return amount, position


def _ew_facts(items: list[dict], debt_lines: list[metrics.DebtLineFact], *,
              as_of: date, dscr: dict, continuity: dict,
              opening_status: str) -> ew.EwFacts:
    overdue_pay = [i for i in items if i["direction"] == "payable"
                   and i["due_date"] < as_of]

    payroll_all = [i for i in items if i["direction"] == "payable"
                   and i["category"] in ew.PAYROLL_CATEGORIES]
    payroll_overdue = [i for i in payroll_all if i["due_date"] < as_of]

    def is_trade(i: dict) -> bool:
        return (i["source"] != "fiscal"
                and i["category"] not in ew.FINANCIAL_CATEGORIES
                and i["category"] not in ew.PAYROLL_CATEGORIES)

    supplier_open = [i for i in items if i["direction"] == "payable" and is_trade(i)]
    supplier_overdue = [i for i in supplier_open if i["due_date"] < as_of]

    fin_items = [i for i in overdue_pay if i["category"] in ew.FINANCIAL_CATEGORIES]
    fin_debt = [d for d in debt_lines if d.status == InstalmentStatus.SCHEDULED
                and d.due_date < as_of]
    fin_amount = (total([i["residual"] for i in fin_items]) or Decimal("0.00")) + \
        (total([d.service for d in fin_debt]) or Decimal("0.00"))
    fin_count = len(fin_items) + len(fin_debt)

    public_overdue = [i for i in overdue_pay if i["source"] == "fiscal"]

    return ew.EwFacts(
        as_of=as_of,
        overdue_payroll_amount=total([i["residual"] for i in payroll_overdue]),
        overdue_payroll_count=len(payroll_overdue),
        overdue_payroll_max_days=max(((as_of - i["due_date"]).days
                                      for i in payroll_overdue), default=0),
        payroll_items_configured=bool(payroll_all),
        overdue_supplier_amount=total([i["residual"] for i in supplier_overdue]),
        supplier_payable_total=total([i["residual"] for i in supplier_open]),
        overdue_supplier_max_days=max(((as_of - i["due_date"]).days
                                       for i in supplier_overdue), default=0),
        overdue_financial_amount=(fin_amount if fin_count else None),
        overdue_financial_count=fin_count,
        overdue_public_amount=total([i["residual"] for i in public_overdue]),
        overdue_public_count=len(public_overdue),
        dscr_value=(Decimal(dscr["value"]) if dscr.get("value") is not None else None),
        dscr_status=dscr.get("status", "insufficient_data"),
        first_negative_date=continuity.get("first_negative_date"),
        days_to_negative=continuity.get("runway_days"),
        opening_balance_status=opening_status,
        source_ids={
            "EW-FIN-OVERDUE": {"item_ids": [i["id"] for i in fin_items],
                               "debt_line_ids": [d.id for d in fin_debt]},
            "EW-PAYROLL-OVERDUE": {"item_ids": [i["id"] for i in payroll_overdue]},
            "EW-SUPPLIER-OVERDUE": {"item_ids": [i["id"] for i in supplier_overdue]},
            "EW-PUBLIC-CREDITOR": {"item_ids": [i["id"] for i in public_overdue]},
            "EW-DSCR-12M": {"debt_line_ids": dscr.get("debt_line_ids", [])},
            "EW-CONTINUITY-12M": {},
        })


# ---------------------------------------------------------------------------
# Snapshot — everything the UI, cockpit and AI tools read
# ---------------------------------------------------------------------------

def controlling_snapshot(db: Session, *, tenant_id, company_id,
                         as_of: date | None = None) -> dict:
    """Metrics + live rule evaluations + persisted alerts. Read-only: rule
    detection persists only via `run_detection`."""
    as_of = as_of or today()
    items = _item_residuals(db, tenant_id, company_id)
    debt_lines = _debt_facts(db, tenant_id, company_id)
    flows = _flow_facts(items, debt_lines)
    opening, position = _opening_balance(db, tenant_id, company_id, as_of)

    dscr = metrics.compute_dscr(flows, debt_lines, as_of=as_of,
                                opening_balance=opening)
    continuity = metrics.continuity_view(flows, as_of=as_of,
                                         opening_balance=opening)

    contribution = management_service.get_contribution(
        db, tenant_id=tenant_id, company_id=company_id,
        year=as_of.year, through_month=as_of.month)
    mos = metrics.margin_of_safety(
        Decimal(contribution["revenue"]) if contribution["revenue"] else None,
        Decimal(contribution["break_even_revenue"])
        if contribution["break_even_revenue"] else None)

    current = {
        "contribution_margin_percent": contribution["contribution_margin_percent"],
        "dscr": {"value": dscr.get("value")},
        "overdue_receivables": money(total(
            [i["residual"] for i in items if i["direction"] == "receivable"
             and i["due_date"] < as_of])),
        "overdue_payables": money(total(
            [i["residual"] for i in items if i["direction"] == "payable"
             and i["due_date"] < as_of])),
        "runway_days": continuity["runway_days"],
    }
    previous = None
    if as_of.month > 1:
        prev = management_service.get_contribution(
            db, tenant_id=tenant_id, company_id=company_id,
            year=as_of.year, through_month=as_of.month - 1)
        previous = {"contribution_margin_percent": prev["contribution_margin_percent"]}
    trends = metrics.detect_trends(current, previous)

    facts = _ew_facts(items, debt_lines, as_of=as_of, dscr=dscr,
                      continuity=continuity, opening_status=position["status"])
    rules = rules_seed.active_rules(db, tenant_id=tenant_id, on_date=as_of)
    evaluations = [ew.evaluate(rules_seed.rule_dict(rule), facts) for rule in rules]

    alerts = db.scalars(
        _scoped(ControllingAlert, tenant_id, company_id)
        .order_by(ControllingAlert.detected_at.desc(), ControllingAlert.rule_code)
    ).all()

    return {
        "as_of": as_of.isoformat(), "currency": "EUR",
        "opening_balance": money(opening),
        "opening_balance_status": position["status"],
        "dscr": dscr,
        "continuity": continuity,
        "profitability": {
            "contribution": contribution,
            "margin_of_safety": mos.as_dict(),
        },
        "trends": trends,
        "evaluations": evaluations,
        "alerts": [alert_data(a) for a in alerts],
        "counters": {
            "open_items": len(items),
            "debt_lines_scheduled": sum(1 for d in debt_lines
                                        if d.status == InstalmentStatus.SCHEDULED),
            "alerts_open": sum(1 for a in alerts if a.status in
                               (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)),
            "rules_active": len(rules),
            "rules_fired": sum(1 for e in evaluations if e["state"] == "fired"),
        },
        "engine_version": ENGINE_VERSION,
        "formula_versions": {
            "dscr": metrics.DSCR_FORMULA_VERSION,
            "continuity": metrics.CONTINUITY_FORMULA_VERSION,
            "early_warning": ew.EW_FORMULA_VERSION,
            "scenario": scenarios.SCENARIO_FORMULA_VERSION,
        },
        "limitations": LIMITATIONS,
    }


# ---------------------------------------------------------------------------
# Detection — persist evaluations as durable alerts (idempotent by dedupe_key)
# ---------------------------------------------------------------------------

def run_detection(db: Session, *, tenant_id, company: Company, actor_id,
                  as_of: date | None = None) -> dict:
    """Evaluate active rules and upsert alerts. Re-running refreshes evidence
    of the same alert; a cleared condition auto-resolves it."""
    as_of = as_of or today()
    items = _item_residuals(db, tenant_id, company.id)
    debt_lines = _debt_facts(db, tenant_id, company.id)
    flows = _flow_facts(items, debt_lines)
    opening, position = _opening_balance(db, tenant_id, company.id, as_of)
    dscr = metrics.compute_dscr(flows, debt_lines, as_of=as_of,
                                opening_balance=opening)
    continuity = metrics.continuity_view(flows, as_of=as_of,
                                         opening_balance=opening)
    facts = _ew_facts(items, debt_lines, as_of=as_of, dscr=dscr,
                      continuity=continuity, opening_status=position["status"])

    rules = rules_seed.active_rules(db, tenant_id=tenant_id, on_date=as_of)
    existing = {a.dedupe_key: a for a in db.scalars(
        _scoped(ControllingAlert, tenant_id, company.id)).all()}

    created = refreshed = auto_resolved = reopened = 0
    evaluations: list[dict] = []
    for rule in rules:
        spec = rules_seed.rule_dict(rule)
        result = ew.evaluate(spec, facts)
        evaluations.append(result)
        alert = existing.get(rule.code)
        if result["state"] == "fired":
            if alert is None:
                db.add(ControllingAlert(
                    tenant_id=tenant_id, company_id=company.id,
                    kind=("early_warning" if rule.category == "ccii_legal"
                          else "management"),
                    rule_code=rule.code, rule_version=rule.version,
                    dedupe_key=rule.code, severity=result["severity"],
                    title=result["title"], message=result["message"],
                    formula=rule.formula, formula_version=rule.formula_version,
                    evidence=result.get("evidence", {}),
                    status=AlertStatus.OPEN,
                    detected_at=as_of, first_detected_at=as_of))
                created += 1
            elif alert.status in (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED):
                alert.detected_at = as_of
                alert.rule_version = rule.version
                alert.severity = result["severity"]
                alert.message = result["message"]
                alert.evidence = result.get("evidence", {})
                refreshed += 1
            else:
                # Resolved/dismissed by a human but the condition is true
                # again: reopen with the prior decision kept in evidence.
                alert.status = AlertStatus.OPEN
                alert.detected_at = as_of
                alert.rule_version = rule.version
                alert.severity = result["severity"]
                alert.message = result["message"]
                alert.evidence = {**result.get("evidence", {}),
                                  "reopened": True,
                                  "previous_resolution": alert.resolution_note}
                alert.resolved_at = None
                alert.resolved_by_id = None
                alert.resolution_kind = None
                alert.resolution_note = None
                reopened += 1
                record_audit(db, actor_id=actor_id,
                             action="controlling.alert.reopen",
                             entity_type="controlling_alert", entity_id=alert.id,
                             tenant_id=tenant_id,
                             changes={"rule_code": rule.code})
        elif alert is not None and alert.status in (AlertStatus.OPEN,
                                                    AlertStatus.ACKNOWLEDGED):
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = utcnow()
            alert.resolution_kind = "auto"
            alert.resolution_note = (f"Condizione non più verificata "
                                     f"(stato regola: {result['state']}).")
            auto_resolved += 1
            record_audit(db, actor_id=actor_id,
                         action="controlling.alert.auto_resolve",
                         entity_type="controlling_alert", entity_id=alert.id,
                         tenant_id=tenant_id,
                         changes={"rule_code": rule.code,
                                  "rule_state": result["state"]})
    db.flush()
    return {
        "as_of": as_of.isoformat(), "evaluations": evaluations,
        "counters": {"rules_evaluated": len(rules), "created": created,
                     "refreshed": refreshed, "reopened": reopened,
                     "auto_resolved": auto_resolved},
        "engine_version": ENGINE_VERSION,
        "formula_version": ew.EW_FORMULA_VERSION,
    }


# ---------------------------------------------------------------------------
# Alert lifecycle — human decisions, audited
# ---------------------------------------------------------------------------

def list_alerts(db: Session, *, tenant_id, company_id,
                status: str | None = None) -> dict:
    stmt = _scoped(ControllingAlert, tenant_id, company_id)
    if status is not None:
        stmt = stmt.where(ControllingAlert.status == status)
    rows = db.scalars(
        stmt.order_by(ControllingAlert.detected_at.desc(),
                      ControllingAlert.rule_code)).all()
    return {
        "alerts": [alert_data(a) for a in rows],
        "counters": {
            "total": len(rows),
            "open": sum(1 for a in rows if a.status == AlertStatus.OPEN),
            "acknowledged": sum(1 for a in rows
                                if a.status == AlertStatus.ACKNOWLEDGED),
            "resolved": sum(1 for a in rows if a.status == AlertStatus.RESOLVED),
            "dismissed": sum(1 for a in rows if a.status == AlertStatus.DISMISSED),
        },
        "engine_version": ENGINE_VERSION,
    }


def transition_alert(db: Session, *, tenant_id, company: Company, actor_id,
                     alert_id: uuid.UUID, action: str, note: str | None) -> dict:
    alert = _owned(db, ControllingAlert, alert_id, tenant_id, company.id)
    if alert.status in (AlertStatus.RESOLVED, AlertStatus.DISMISSED):
        raise ConflictError(f"L'alert è già '{alert.status}': transizione non ammessa.",
                            code="invalid_transition")
    if action == "acknowledge":
        if alert.status == AlertStatus.ACKNOWLEDGED:
            raise ConflictError("L'alert è già preso in carico.",
                                code="invalid_transition")
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by_id = actor_id
        alert.acknowledged_at = utcnow()
    elif action in ("resolve", "dismiss"):
        if action == "dismiss" and (not note or len(note.strip()) < 5):
            raise ValidationError("Motivazione obbligatoria per ignorare un alert.",
                                  code="reason_required")
        alert.status = (AlertStatus.RESOLVED if action == "resolve"
                        else AlertStatus.DISMISSED)
        alert.resolved_at = utcnow()
        alert.resolved_by_id = actor_id
        alert.resolution_kind = "human"
        alert.resolution_note = note.strip()[:600] if note else None
    else:
        raise ValidationError("Azione non valida: ammesse 'acknowledge', "
                              "'resolve', 'dismiss'.", code="invalid_action")
    db.flush()
    record_audit(db, actor_id=actor_id, action=f"controlling.alert.{action}",
                 entity_type="controlling_alert", entity_id=alert.id,
                 tenant_id=tenant_id,
                 changes={"status": alert.status, "note": alert.resolution_note})
    return alert_data(alert)


# ---------------------------------------------------------------------------
# Rules (jurisdiction-level reference data)
# ---------------------------------------------------------------------------

def list_rules(db: Session, *, tenant_id, as_of: date | None = None) -> dict:
    as_of = as_of or today()
    rules = rules_seed.active_rules(db, tenant_id=tenant_id, on_date=as_of)
    return {
        "as_of": as_of.isoformat(),
        "rules": [rules_seed.rule_dict(r) for r in rules],
        "formula_version": ew.EW_FORMULA_VERSION,
        "disclaimer": ("Regole di early warning con riferimenti al D.Lgs. 14/2019: "
                       "le soglie marcate 'operational' sono parametri di lavoro, "
                       "non valori di legge."),
    }


def sync_rules(db: Session, *, tenant_id) -> dict:
    return rules_seed.ensure_rules(db, tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# Scenarios — deterministic recompute on transformed copies
# ---------------------------------------------------------------------------

def list_presets() -> dict:
    return {
        "presets": {key: {"label": a.label, "assumptions": {
            "revenue_change_pct": str(a.revenue_change_pct),
            "collection_delay_days": a.collection_delay_days,
            "supplier_delay_days": a.supplier_delay_days,
            "fixed_cost_monthly_delta": money(a.fixed_cost_monthly_delta),
            "variable_cost_change_pct": str(a.variable_cost_change_pct),
            "debt_service_change_pct": str(a.debt_service_change_pct),
        }} for key, a in sorted(scenarios.PRESETS.items())},
        "bounds": {k: list(v) for k, v in scenarios.BOUNDS.items()},
        "formula_version": scenarios.SCENARIO_FORMULA_VERSION,
    }


def run_scenario(db: Session, *, tenant_id, company_id, raw: dict,
                 as_of: date | None = None) -> dict:
    as_of = as_of or today()
    try:
        assumptions = scenarios.parse_assumptions(raw)
    except ValueError as exc:
        raise ValidationError(str(exc), code="invalid_assumptions") from exc

    items = _item_residuals(db, tenant_id, company_id)
    debt_lines = _debt_facts(db, tenant_id, company_id)
    flows = _flow_facts(items, debt_lines)
    opening, _ = _opening_balance(db, tenant_id, company_id, as_of)
    contribution = management_service.get_contribution(
        db, tenant_id=tenant_id, company_id=company_id,
        year=as_of.year, through_month=as_of.month)
    contribution = {**contribution, "months_elapsed": as_of.month}

    result = scenarios.run(flows, debt_lines, contribution=contribution,
                           assumptions=assumptions, as_of=as_of,
                           opening_balance=opening)
    result["as_of"] = as_of.isoformat()
    result["engine_version"] = ENGINE_VERSION
    return result
