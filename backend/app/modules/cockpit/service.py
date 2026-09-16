"""CFO cockpit + multi-company control hub.

This module owns **no tables**. It composes the deterministic outputs of
`management` (economics), `treasury` (cash), `fiscal` (IVA/F24 obligations)
and `opportunities` (commercial) into the two screens a consultant actually
works from:

* `company_cockpit` — one client company, end to end;
* `hub` — the whole portfolio, ordered by "what deserves attention first".

Every entry in the action center is a *deterministic* signal produced by a
domain engine, carrying its formula, its evidence and its formula version. The
AI layer may read and explain these; it can neither create nor rank them.
Nothing here estimates a missing value.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.controlling import service as controlling
from app.modules.controlling.models import AlertStatus
from app.modules.fiscal import service as fiscal
from app.modules.management import service as management
from app.modules.opportunities import service as opportunities
from app.modules.treasury import service as treasury
from app.shared.mixins import today

PRIORITY_VERSION = "cockpit-priority-v1.2"

#: Deterministic ranking weights. Documented because the ordering of the
#: consultant's morning is a product decision, not an implementation detail.
SEVERITY_WEIGHT = {"critical": 100, "danger": 100, "warning": 50, "info": 10}
CATEGORY_WEIGHT = {
    "treasury": 15,      # running out of cash beats everything else
    "early_warning": 14, # a CCII signal is a legal-grade warning, not a KPI
    "fiscal": 12,        # a missed tax payment is a legal default, not a delay
    "financial": 10,     # overdue money
    "management": 5,     # margin/budget deterioration
    "commercial": 5,
    "data_quality": 0,   # never outranks a real problem, never hidden either
}
ACTION_REQUIRED_BONUS = 20

PRIORITY_FORMULA = (
    "score = peso(severità) + peso(categoria) + 20 se richiede azione umana. "
    "A pari punteggio l'ordine è alfabetico per azienda e codice segnale: "
    "l'elenco è riproducibile."
)


def _priority(severity: str, category: str, action_required: bool) -> int:
    return (SEVERITY_WEIGHT.get(severity, 10)
            + CATEGORY_WEIGHT.get(category, 0)
            + (ACTION_REQUIRED_BONUS if action_required else 0))


def _signal(*, code: str, severity: str, category: str, title: str, message: str,
            formula: str, formula_version: str, evidence: dict,
            action_required: bool = False, company: Company | None = None) -> dict:
    signal = {
        "code": code, "severity": severity, "category": category,
        "title": title, "message": message, "formula": formula,
        "formula_version": formula_version, "evidence": evidence,
        "action_required": action_required,
        "priority": _priority(severity, category, action_required),
        "priority_version": PRIORITY_VERSION,
    }
    if company is not None:
        signal["company_id"] = str(company.id)
        signal["company_name"] = company.legal_name
    return signal


def _management_signals(overview: dict, company: Company | None = None) -> list[dict]:
    """Map management alerts onto the common signal shape."""
    return [
        _signal(
            code=alert["code"],
            severity="warning" if alert["severity"] == "warning" else (
                "critical" if alert["severity"] == "danger" else "info"),
            category="management",
            title=alert["title"], message=alert["message"],
            formula=alert.get("formula", management.FORMULAS.get("result", "")),
            formula_version=overview["trace"]["formula_version"],
            evidence={k: v for k, v in alert.items()
                      if k not in ("code", "severity", "title", "message", "formula")},
            action_required=alert["severity"] in ("danger", "warning"),
            company=company,
        )
        for alert in overview["alerts"]
    ]


def _contribution_signals(contribution: dict, company: Company | None = None) -> list[dict]:
    """Break-even and classification signals from the contribution engine."""
    return [
        _signal(
            code=alert["code"],
            severity="warning" if alert["severity"] == "warning" else "info",
            category="management" if alert["severity"] == "warning" else "data_quality",
            title=alert["title"], message=alert["message"],
            formula=alert["formula"],
            formula_version=contribution["trace"]["formula_version"],
            evidence={"break_even_revenue": contribution["break_even_revenue"],
                      "break_even_coverage": contribution["break_even_coverage"],
                      "contribution_margin": contribution["contribution_margin"],
                      "unclassified_costs": contribution["unclassified_costs"]},
            action_required=alert["severity"] == "warning",
            company=company,
        )
        for alert in contribution["alerts"]
    ]


def _treasury_signals(snapshot: dict, company: Company | None = None) -> list[dict]:
    return [
        _signal(
            code=warning["code"], severity=warning["severity"],
            category=warning["category"], title=warning["title"],
            message=warning["message"], formula=warning["formula"],
            formula_version=warning["formula_version"],
            evidence=warning["evidence"],
            action_required=warning["action_required"], company=company,
        )
        for warning in snapshot["warnings"]
    ]


def _fiscal_signals(snapshot: dict, cash: dict, *,
                    company: Company | None = None) -> list[dict]:
    """Map fiscal warnings onto the common signal shape, plus the
    liquidity-vs-obligation cross-check the fiscal engine cannot see alone.

    `fiscal_liquidity_risk` fires when a *validated* fiscal obligation falls
    inside the cash horizon and the projected balance on its due date is
    negative: the money for the tax payment is not there. Deterministic —
    both inputs are engine outputs, nothing is estimated.
    """
    signals = [
        _signal(
            code=warning["code"], severity=warning["severity"],
            category=warning["category"], title=warning["title"],
            message=warning["message"], formula=warning["formula"],
            formula_version=warning["formula_version"],
            evidence=warning["evidence"],
            action_required=warning["action_required"], company=company,
        )
        for warning in snapshot["warnings"]
    ]

    projected_by_date = {
        row["date"]: row["projected_balance"]
        for row in cash["forecast"]["daily"]
        if row["projected_balance"] is not None
    }
    uncovered = []
    for deadline in snapshot["deadlines"]:
        if deadline["status"] != "validated" or not deadline["due_date"]:
            continue
        balance = projected_by_date.get(deadline["due_date"])
        if balance is not None and Decimal(balance) < 0:
            uncovered.append({
                "deadline_id": deadline["id"], "kind": deadline["kind"],
                "due_date": deadline["due_date"], "amount": deadline["amount"],
                "projected_balance": balance,
            })
    if uncovered:
        total_due = sum(Decimal(row["amount"]) for row in uncovered
                        if row["amount"] is not None)
        first = min(uncovered, key=lambda row: row["due_date"])
        signals.append(_signal(
            code="fiscal_liquidity_risk", severity="critical", category="fiscal",
            title="Obbligazione fiscale scoperta",
            message=(f"{len(uncovered)} obbligazioni fiscali validate "
                     f"({total_due} EUR) cadono in giorni con saldo proiettato "
                     f"negativo; la prima è il {first['due_date']} "
                     f"(saldo {first['projected_balance']} EUR)."),
            formula=("scadenza validata con saldo proiettato alla data di "
                     "versamento < 0"),
            formula_version=f"{fiscal.ENGINE_VERSION}+treasury-forecast",
            evidence={"uncovered": uncovered,
                      "horizon_days": cash["forecast"]["horizon_days"],
                      "opening_balance_status":
                          cash["forecast"]["opening_balance_status"]},
            action_required=True, company=company,
        ))
    return signals


def _controlling_signals(alerts: list[dict], *,
                         company: Company | None = None) -> list[dict]:
    """Persisted controlling alerts (open/acknowledged) as signals.

    The cockpit reads the durable alert rows — detection itself is a write
    and stays behind `controlling:write`. Each signal keeps the rule code,
    the rule version that fired and the evidence captured at detection.
    """
    return [
        _signal(
            code=alert["rule_code"], severity=alert["severity"],
            category=("early_warning" if alert["kind"] == "early_warning"
                      else "management"),
            title=alert["title"], message=alert["message"],
            formula=alert["formula"], formula_version=alert["formula_version"],
            evidence={"alert_id": alert["id"], "status": alert["status"],
                      "rule_version": alert["rule_version"],
                      "first_detected_at": alert["first_detected_at"],
                      **alert["evidence"]},
            action_required=alert["severity"] in ("critical", "warning"),
            company=company,
        )
        for alert in alerts
    ]


def _commercial_signals(rows: list[dict], *, stale_days: int,
                        company: Company | None = None) -> list[dict]:
    """Open opportunities with no recorded change for `stale_days`."""
    stale = [r for r in rows
             if r["days_inactive"] is not None and r["days_inactive"] >= stale_days]
    if not stale:
        return []
    ranked = sorted(stale, key=lambda r: (-(float(r["expected_value_eur"] or 0)),
                                          r["title"]))
    top = ranked[0]
    return [_signal(
        code="opportunity_stale", severity="warning", category="commercial",
        title="Opportunità senza aggiornamenti",
        message=(f"{len(stale)} opportunità aperte senza modifiche da almeno "
                 f"{stale_days} giorni; la più rilevante è \"{top['title']}\" "
                 f"({top['expected_value_eur'] or 'valore n.d.'} EUR, "
                 f"{top['days_inactive']} giorni)."),
        formula=f"opportunità con status=open e giorni da updated_at >= {stale_days}",
        formula_version="opportunities-staleness-v1.0",
        evidence={"count": len(stale),
                  "proxy": "updated_at come proxy di attività: non è un log di contatti",
                  "items": [{"id": r["id"], "title": r["title"],
                             "expected_value_eur": r["expected_value_eur"],
                             "days_inactive": r["days_inactive"]} for r in ranked[:5]]},
        action_required=True, company=company,
    )]


def company_cockpit(db: Session, *, tenant_id, company: Company, year: int,
                    through_month: int, horizon_days: int = 90,
                    as_of: date | None = None,
                    stale_days: int = opportunities.DEFAULT_STALE_DAYS) -> dict:
    """One company: registry + economics + cash + commercial + ranked actions."""
    as_of = as_of or today()
    overview = management.get_overview(db, tenant_id=tenant_id, company_id=company.id,
                                       year=year, through_month=through_month)
    contribution = management.get_contribution(db, tenant_id=tenant_id, company_id=company.id,
                                               year=year, through_month=through_month)
    cash = treasury.snapshot(db, tenant_id=tenant_id, company_id=company.id,
                             as_of=as_of, horizon_days=horizon_days)
    fiscal_view = fiscal.fiscal_snapshot(db, tenant_id=tenant_id,
                                         company_id=company.id, as_of=as_of,
                                         year=year)
    ctrl_alerts = [a for a in controlling.list_alerts(
        db, tenant_id=tenant_id, company_id=company.id)["alerts"]
        if a["status"] in (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)]
    pipeline = opportunities.list_open(db, tenant_id=tenant_id, company_id=company.id,
                                       as_of=as_of)
    signals = [
        *_treasury_signals(cash),
        *_fiscal_signals(fiscal_view, cash),
        *_controlling_signals(ctrl_alerts),
        *_management_signals(overview),
        *_contribution_signals(contribution),
        *_commercial_signals(pipeline, stale_days=stale_days),
    ]
    signals.sort(key=lambda s: (-s["priority"], s["code"]))
    return {
        "as_of": as_of.isoformat(),
        "company": {
            "id": str(company.id), "legal_name": company.legal_name,
            "trading_name": company.trading_name, "vat_number": company.vat_number,
            "tax_code": company.tax_code, "legal_form": company.legal_form,
            "ateco_code": company.ateco_code, "industry": company.industry,
            "size_band": company.size_band, "employee_count": company.employee_count,
            "region": company.region, "city": company.city, "country": company.country,
            "status": company.status, "lifecycle_stage": company.lifecycle_stage,
        },
        "management": overview,
        "contribution": contribution,
        "treasury": cash,
        "fiscal": {
            "year": fiscal_view["year"],
            "engine_version": fiscal_view["engine_version"],
            "latest_settlement": fiscal_view["latest_settlement"],
            "next_obligation": fiscal.next_obligation(fiscal_view),
            "deadlines": fiscal_view["deadlines"],
            "counters": fiscal_view["counters"],
            "pending_entries": fiscal_view["pending_entries"],
            "f24_drafts": fiscal_view["f24_drafts"],
            "limitations": fiscal_view["limitations"],
            "transmission": fiscal_view["transmission"],
        },
        "controlling": {
            "open_alerts": len(ctrl_alerts),
            "alerts": ctrl_alerts,
            "note": ("Alert durevoli del motore di early warning: la detection "
                     "è una scrittura esplicita, il cockpit legge soltanto."),
        },
        "commercial": {
            "open_opportunities": len(pipeline),
            "stale_days_threshold": stale_days,
            "items": pipeline[:10],
            "expected_value_note": ("Valori attesi inseriti dall'operatore: non sono "
                                    "ricavi né impegni contrattuali."),
        },
        "actions": signals,
        "priority": {"formula": PRIORITY_FORMULA, "version": PRIORITY_VERSION,
                     "severity_weight": SEVERITY_WEIGHT,
                     "category_weight": CATEGORY_WEIGHT,
                     "action_required_bonus": ACTION_REQUIRED_BONUS},
        "limitations": [
            *treasury.LIMITATIONS,
            "Il risultato gestionale disponibile non è EBITDA, utile civilistico o cassa.",
            *fiscal_view["limitations"],
            *controlling.LIMITATIONS,
        ],
    }


def hub(db: Session, *, tenant_id, year: int, through_month: int,
        horizon_days: int = 90, as_of: date | None = None,
        stale_days: int = opportunities.DEFAULT_STALE_DAYS) -> dict:
    """Portfolio view: one row per company, ordered by urgency.

    Answers "which company do I look at first this morning, and why?" with
    deterministic signals only — the `why` is always a formula plus evidence.
    """
    as_of = as_of or today()
    companies = db.scalars(
        select(Company).where(Company.tenant_id == tenant_id,
                              Company.deleted_at.is_(None))
        .order_by(Company.legal_name)
    ).all()
    pipeline = opportunities.list_open(db, tenant_id=tenant_id, as_of=as_of)
    by_company: dict[str, list[dict]] = {}
    for row in pipeline:
        by_company.setdefault(row["company_id"], []).append(row)

    entries, actions = [], []
    for company in companies:
        overview = management.get_overview(db, tenant_id=tenant_id, company_id=company.id,
                                           year=year, through_month=through_month)
        contribution = management.get_contribution(db, tenant_id=tenant_id,
                                                   company_id=company.id, year=year,
                                                   through_month=through_month)
        cash = treasury.snapshot(db, tenant_id=tenant_id, company_id=company.id,
                                 as_of=as_of, horizon_days=horizon_days)
        fiscal_view = fiscal.fiscal_snapshot(db, tenant_id=tenant_id,
                                             company_id=company.id, as_of=as_of,
                                             year=year)
        ctrl_alerts = [a for a in controlling.list_alerts(
            db, tenant_id=tenant_id, company_id=company.id)["alerts"]
            if a["status"] in (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)]
        signals = [
            *_treasury_signals(cash, company),
            *_fiscal_signals(fiscal_view, cash, company=company),
            *_controlling_signals(ctrl_alerts, company=company),
            *_management_signals(overview, company),
            *_contribution_signals(contribution, company),
            *_commercial_signals(by_company.get(str(company.id), []),
                                 stale_days=stale_days, company=company),
        ]
        actions.extend(signals)
        worst = max((s["priority"] for s in signals), default=0)
        entries.append({
            "company": {"id": str(company.id), "legal_name": company.legal_name,
                        "vat_number": company.vat_number, "region": company.region,
                        "ateco_code": company.ateco_code,
                        "size_band": company.size_band},
            "attention_score": worst,
            "health": _health(signals, cash, overview),
            "economics": {
                "period": overview["period"], "revenue": overview["revenue"],
                "costs": overview["costs"], "result": overview["result"],
                "margin_percent": overview["margin_percent"],
                "quality": overview["quality"]["status"],
                "covered_months": overview["quality"]["covered_months"],
                "expected_months": overview["quality"]["expected_months"],
                "contribution_margin": contribution["contribution_margin"],
                "contribution_margin_percent": contribution["contribution_margin_percent"],
                "break_even_revenue": contribution["break_even_revenue"],
                "break_even_status": contribution["break_even_status"],
            },
            "cash": {
                "position": cash["position"]["amount"],
                "position_status": cash["position"]["status"],
                "first_negative_date": cash["forecast"]["first_negative_date"],
                "days_to_negative": cash["forecast"]["days_to_negative"],
                "receivable_residual": cash["counters"]["receivable_residual"],
                "payable_residual": cash["counters"]["payable_residual"],
                "overdue_receivables": cash["aging"]["receivables"]["overdue"]["amount"],
                "overdue_payables": cash["aging"]["payables"]["overdue"]["amount"],
                "unreconciled_transactions": cash["counters"]["unreconciled_transactions"],
            },
            "fiscal": {
                "next_obligation": fiscal.next_obligation(fiscal_view),
                "open_deadlines": fiscal_view["counters"]["open_deadlines"],
                "pending_entries": fiscal_view["counters"]["pending_entries"],
                "validated_settlements": fiscal_view["counters"]["validated"],
                "f24_drafts": fiscal_view["counters"]["f24_drafts"],
            },
            "controlling": {
                "open_alerts": len(ctrl_alerts),
                "critical_alerts": sum(1 for a in ctrl_alerts
                                       if a["severity"] == "critical"),
            },
            "signal_count": len(signals),
            "top_signal": signals[0]["code"] if signals else None,
        })

    actions.sort(key=lambda s: (-s["priority"], s.get("company_name", ""), s["code"]))
    entries.sort(key=lambda e: (-e["attention_score"], e["company"]["legal_name"]))
    return {
        "as_of": as_of.isoformat(),
        "period": {"year": year, "through_month": through_month},
        "horizon_days": horizon_days,
        "companies": entries,
        "actions": actions,
        "counters": {
            "companies": len(entries),
            "critical": sum(1 for a in actions if a["severity"] == "critical"),
            "warning": sum(1 for a in actions if a["severity"] == "warning"),
            "info": sum(1 for a in actions if a["severity"] == "info"),
            "action_required": sum(1 for a in actions if a["action_required"]),
            "companies_needing_attention": sum(1 for e in entries
                                               if e["attention_score"] >= 50),
        },
        "priority": {"formula": PRIORITY_FORMULA, "version": PRIORITY_VERSION},
        "aggregation_note": ("Nessun consolidato: le aziende non sono sommate. "
                             "Ogni riga resta un'entità autonoma con le sue fonti."),
        "limitations": [*treasury.LIMITATIONS, *fiscal.LIMITATIONS,
                        *controlling.LIMITATIONS],
    }


def _health(signals: list[dict], cash: dict, overview: dict) -> dict:
    """Traffic light that is honest about missing data.

    `not_calculable` is a first-class state: an empty dataset never shows green.
    """
    has_economics = overview["quality"]["status"] != "empty"
    has_cash = cash["position"]["status"] == "available" or cash["counters"]["open_items"] > 0
    if any(s["severity"] == "critical" and s["category"] != "data_quality" for s in signals):
        status = "critical"
    elif any(s["severity"] == "warning" and s["category"] != "data_quality" for s in signals):
        status = "attention"
    elif not has_economics and not has_cash:
        status = "not_calculable"
    elif any(s["category"] == "data_quality" for s in signals):
        status = "data_incomplete"
    else:
        status = "ok"
    return {
        "status": status,
        "reason": {
            "critical": "Almeno un segnale critico su cassa o risultato.",
            "attention": "Segnali di attenzione su cassa, crediti o margine.",
            "not_calculable": "Nessuna fonte gestionale né di tesoreria: nulla da valutare.",
            "data_incomplete": "Dati presenti ma incompleti: verde non attribuibile.",
            "ok": "Nessun segnale deterministico attivo sulle fonti disponibili.",
        }[status],
        "has_economics": has_economics,
        "has_cash_data": has_cash,
    }
