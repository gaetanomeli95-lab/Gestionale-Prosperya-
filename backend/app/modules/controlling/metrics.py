"""Deterministic controlling metrics — pure functions, no I/O, no AI.

Every result carries its formula, its inputs' identity and an explicit
data-quality state. A missing input produces `null` or
`insufficient_data`, never a fabricated number.

Chain: canonical facts (treasury ItemFact / AccountFact, debt-service
lines, management contribution) -> deterministic metrics -> trace ->
warnings -> human interpretation.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.shared.money import money, percentage, ratio, total

ENGINE_VERSION = "controlling-v1.0"
DSCR_FORMULA_VERSION = "dscr-v1.0"
CONTINUITY_FORMULA_VERSION = "continuity-v1.0"
TREND_FORMULA_VERSION = "trend-v1.0"
RUNWAY_FORMULA_VERSION = "runway-v1.0"

#: DSCR target horizon: debt sustainability is prospective, 12 months.
DSCR_TARGET_HORIZON_DAYS = 365

DSCR_FORMULAS = {
    "numerator": ("CFADS proxy = incassi attesi − pagamenti attesi su partite aperte "
                  "nell'orizzonte, al lordo del servizio del debito. Non è il "
                  "flusso di cassa operativo civilistico: è derivato dalle sole "
                  "obbligazioni datate registrate."),
    "denominator": ("Servizio del debito = Σ (quota capitale + interessi) delle rate "
                    "pianificate con scadenza nell'orizzonte, righe non pagate né "
                    "sospese."),
    "dscr": "numeratore / denominatore; null se il denominatore è zero o assente.",
    "horizon_coverage": ("Quota dell'orizzonte target coperta da obbligazioni "
                         "datate: misura l'affidabilità prospettica, non il rischio."),
}

CONTINUITY_FORMULAS = {
    "projected_balance": ("Saldo noto + flussi cumulati. I flussi sono partite "
                          "aperte (CONTRACTED), rate di debito pianificate "
                          "(CONTRACTED) e obbligazioni fiscali validate "
                          "(CONTRACTED); null se il saldo non è noto."),
    "runway": ("Giorni alla prima data con saldo proiettato < 0; 'beyond_horizon' "
               "se mai entro l'orizzonte dei dati; non estrapolato oltre le fonti."),
    "minimum_cash": "Minimo del saldo proiettato giornaliero nell'orizzonte coperto.",
}


@dataclass(frozen=True)
class DebtLineFact:
    """A scheduled debt-service instalment reduced to engine inputs."""

    id: str
    facility_id: str
    facility_name: str
    due_date: date
    principal: Decimal
    interest: Decimal
    status: str  # scheduled | paid | waived

    @property
    def service(self) -> Decimal:
        return self.principal + self.interest


@dataclass(frozen=True)
class FlowFact:
    """One dated, known cash flow used by continuity/DSCR."""

    id: str
    nature: str            # trade_receivable | trade_payable | fiscal | debt_service
    direction: str         # inflow | outflow
    due_date: date
    amount: Decimal
    counterparty_name: str
    source: str            # open_item | debt_service
    certainty: str = "contracted"  # contracted = scheduled real obligation


@dataclass
class MetricResult:
    """Uniform envelope: value + quality + provenance, never bare numbers."""

    status: str            # available | insufficient_data | not_applicable
    value: str | None
    reasons: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"status": self.status, "value": self.value,
                "reasons": self.reasons, "evidence": self.evidence}


# ---------------------------------------------------------------------------
# Profitability complements
# ---------------------------------------------------------------------------

def margin_of_safety(revenue: Decimal | None,
                     break_even_revenue: Decimal | None) -> MetricResult:
    """(revenue - break-even) / revenue — how far sales can fall before loss."""
    if revenue is None or revenue <= 0:
        return MetricResult("insufficient_data", None,
                            ["Ricavi disponibili assenti o nulli: margine di sicurezza non calcolabile."])
    if break_even_revenue is None:
        return MetricResult("insufficient_data", None,
                            ["Break-even non calcolabile: margine di sicurezza non determinabile."])
    if break_even_revenue <= 0:
        return MetricResult("not_applicable", None,
                            ["Nessun costo fisso: il pareggio è a zero, il margine di sicurezza non è significativo."])
    mos_abs = revenue - break_even_revenue
    return MetricResult(
        "available", percentage(mos_abs, revenue),
        evidence={"margin_of_safety_abs": money(mos_abs),
                  "revenue": money(revenue),
                  "break_even_revenue": money(break_even_revenue),
                  "formula": "mos% = (ricavi - ricavi di break-even) / ricavi"})


# ---------------------------------------------------------------------------
# DSCR — debt service coverage, prospective
# ---------------------------------------------------------------------------

def compute_dscr(flows: list[FlowFact], debt_lines: list[DebtLineFact], *,
                 as_of: date,
                 horizon_days: int = DSCR_TARGET_HORIZON_DAYS,
                 opening_balance: Decimal | None = None) -> dict:
    """Forward DSCR over `horizon_days` (default 12 months).

    Honesty rules: if the data window covers less than the target horizon the
    result is labelled `partial` with the effective horizon; if no dated
    obligations exist at all the numerator is `insufficient_data`, not zero;
    if no debt service is scheduled the ratio is `not_applicable` (there is
    nothing to cover) — not "infinite".
    """
    end = as_of + timedelta(days=horizon_days)
    in_flows = [f for f in flows if as_of <= f.due_date <= end]
    sched = [d for d in debt_lines if d.status == "scheduled"
             and as_of <= d.due_date <= end]

    inflows = total([f.amount for f in in_flows if f.direction == "inflow"])
    outflows = total([f.amount for f in in_flows if f.direction == "outflow"
                      and f.nature != "debt_service"])
    service_due = total([d.service for d in sched])

    reasons: list[str] = []
    if not in_flows and not sched:
        return {
            "status": "insufficient_data", "value": None, "horizon_days": horizon_days,
            "as_of": as_of.isoformat(), "horizon_end": end.isoformat(),
            "numerator": None, "denominator": None,
            "reasons": ["Nessuna obbligazione datata nell'orizzonte: né il numeratore "
                        "né il denominatore sono osservabili."],
            "formulas": DSCR_FORMULAS, "formula_version": DSCR_FORMULA_VERSION,
            "engine_version": ENGINE_VERSION,
            "assumptions": _dscr_assumptions(),
            "source_ids": [], "debt_line_ids": [],
        }

    # coverage: share of the target horizon actually spanned by dated flows
    last_flow = max((f.due_date for f in in_flows), default=None)
    last_debt = max((d.due_date for d in sched), default=None)
    covered_until = max(d for d in (last_flow, last_debt) if d is not None)
    coverage_days = max(0, (covered_until - as_of).days)
    coverage_pct = Decimal(coverage_days) / Decimal(horizon_days)
    horizon_state = "full" if coverage_days >= horizon_days - 1 else "partial"
    if horizon_state == "partial":
        reasons.append(
            f"L'orizzonte coperto è di {coverage_days} giorni su {horizon_days}: "
            "il DSCR è calcolato sulle obbligazioni datate disponibili, non "
            "estrapolato a 12 mesi.")

    numerator = None
    if inflows is not None or outflows is not None:
        numerator = (inflows or Decimal("0.00")) - (outflows or Decimal("0.00"))

    status = "available"
    value = None
    if service_due is None or not sched:
        status = "not_applicable"
        reasons.append("Nessuna rata di debito pianificata nell'orizzonte: "
                       "il DSCR non è definito (non significa debito sostenibile).")
    elif numerator is None:
        status = "insufficient_data"
        reasons.append("Nessun flusso datato osservabile: il numeratore è "
                       "sconosciuto, non zero.")
    else:
        value = ratio(numerator, service_due)
        if coverage_pct < Decimal("0.50"):
            status = "partial"
            reasons.append("Copertura dati sotto il 50% dell'orizzonte target: "
                           "il valore descrive solo le obbligazioni registrate.")

    return {
        "status": status, "value": value,
        "horizon_days": horizon_days, "horizon_state": horizon_state,
        "as_of": as_of.isoformat(), "horizon_end": end.isoformat(),
        "covered_until": covered_until.isoformat(),
        "coverage_percent": money(coverage_pct * Decimal("100")),
        "numerator": money(numerator), "denominator": money(service_due),
        "opening_balance": money(opening_balance),
        "components": {
            "expected_inflows": money(inflows),
            "expected_outflows_ex_debt": money(outflows),
            "debt_service_due": money(service_due),
            "instalments_due": len(sched),
        },
        "reasons": reasons,
        "formulas": DSCR_FORMULAS, "formula_version": DSCR_FORMULA_VERSION,
        "engine_version": ENGINE_VERSION,
        "assumptions": _dscr_assumptions(),
        "source_ids": [f.id for f in in_flows],
        "debt_line_ids": [d.id for d in sched],
    }


def _dscr_assumptions() -> list[str]:
    return [
        "Numeratore = flussi netti attesi dalle partite aperte datate "
        "(incassi − pagamenti, servizio del debito escluso): proxy CFADS "
        "gestionale, non un flusso civilistico.",
        "Denominatore = rate pianificate (capitale + interessi) in scadenza "
        "nell'orizzonte: solo debito finanziario registrato.",
        "Ogni obbligazione si presume incassata/pagata alla sua data di "
        "scadenza: nessun modello di ritardo.",
        "Nessuna soglia è presentata come soglia legale universale: le soglie "
        "di attenzione sono parametri operativi dichiarati nelle regole.",
    ]


# ---------------------------------------------------------------------------
# 12-month continuity view
# ---------------------------------------------------------------------------

def continuity_view(flows: list[FlowFact], *, as_of: date,
                    opening_balance: Decimal | None,
                    months: int = 12) -> dict:
    """Month-by-month projection over the next `months` months.

    Facts only: every line is an observed obligation labelled by nature.
    The balance is projected only when the opening cash is known.
    """
    buckets: list[dict] = []
    cumulative = Decimal("0.00")
    min_balance: Decimal | None = None
    min_balance_date: date | None = None
    first_negative: str | None = None
    runway: int | None = None
    month_cursor = date(as_of.year, as_of.month, 1)

    for offset in range(months):
        m = month_cursor.month + offset
        y = month_cursor.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        start = date(y, m, 1)
        end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        inside = [f for f in flows if start <= f.due_date <= end]
        inflow = total([f.amount for f in inside if f.direction == "inflow"]) or Decimal("0.00")
        outflow = total([f.amount for f in inside if f.direction == "outflow"]) or Decimal("0.00")
        by_nature: dict[str, Decimal] = {}
        for f in inside:
            if f.direction == "outflow":
                by_nature[f.nature] = by_nature.get(f.nature, Decimal("0.00")) + f.amount
        cumulative += inflow - outflow
        projected = (opening_balance + cumulative) if opening_balance is not None else None
        if projected is not None:
            if min_balance is None or projected < min_balance:
                min_balance, min_balance_date = projected, end
            if projected < 0 and first_negative is None:
                first_negative = end.isoformat()
                runway = (end - as_of).days
        buckets.append({
            "year": y, "month": m, "label": f"{y}-{m:02d}",
            "inflows": money(inflow), "outflows": money(outflow),
            "net": money(inflow - outflow),
            "outflow_by_nature": {k: money(v) for k, v in sorted(by_nature.items())},
            "projected_balance": money(projected),
            "item_count": len(inside),
            "has_data": bool(inside),
        })

    horizon_end = buckets[-1]["label"] if buckets else None
    issues: list[str] = []
    if opening_balance is None:
        issues.append("Saldo iniziale non noto: i saldi proiettati restano null, "
                      "solo i flussi sono calcolabili.")
    months_with_data = sum(1 for b in buckets if b["has_data"])
    if months_with_data < months:
        issues.append(f"{months - months_with_data} mesi su {months} senza obbligazioni "
                      "datate: la proiezione non estrapola, il vuoto non è zero.")
    return {
        "as_of": as_of.isoformat(), "months": months,
        "currency": "EUR",
        "opening_balance": money(opening_balance),
        "opening_balance_status": "available" if opening_balance is not None else "not_calculable",
        "buckets": buckets,
        "minimum_projected_balance": money(min_balance),
        "minimum_projected_date": min_balance_date.isoformat() if min_balance_date else None,
        "first_negative_date": first_negative,
        "runway_days": runway,
        "runway_status": ("limited" if runway is not None
                          else ("beyond_horizon" if opening_balance is not None
                                else "not_calculable")),
        "coverage": {"months_with_data": months_with_data, "months_total": months,
                     "horizon_end": horizon_end},
        "certainty_model": {
            "actual": "Saldi bancari e movimenti già registrati.",
            "contracted": "Partite aperte, rate di debito e obbligazioni fiscali validate.",
            "forecast": "Somma dei flussi contrattuali per mese: non è una previsione statistica.",
            "assumption": "Incasso/pagamento alla data di scadenza; nessun costo ricorrente non registrato.",
        },
        "formulas": CONTINUITY_FORMULAS,
        "formula_version": CONTINUITY_FORMULA_VERSION,
        "engine_version": ENGINE_VERSION,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Trend / deterioration detection
# ---------------------------------------------------------------------------

def detect_trends(current: dict, previous: dict | None) -> list[dict]:
    """Compare the current controlling snapshot with an explicit prior window.

    Every trend states its comparison basis; absent prior data means
    `no_baseline`, never a guessed direction.
    """
    trends: list[dict] = []

    def delta(metric: str, cur: str | None, prev: str | None,
              good_when: str) -> None:
        if cur is None or prev is None:
            trends.append({"metric": metric, "status": "no_baseline",
                           "current": cur, "previous": prev,
                           "direction": None, "delta": None})
            return
        c, p = Decimal(cur), Decimal(prev)
        d = c - p
        direction = "flat" if d == 0 else ("improving" if (d > 0) == (good_when == "up") else "worsening")
        trends.append({"metric": metric, "status": "available",
                       "current": cur, "previous": prev,
                       "delta": money(d) if metric != "dscr" else ratio(d, Decimal("1")),
                       "direction": direction})

    delta("contribution_margin_percent",
          current.get("contribution_margin_percent"),
          (previous or {}).get("contribution_margin_percent"), "up")
    delta("dscr",
          (current.get("dscr") or {}).get("value"),
          ((previous or {}).get("dscr") or {}).get("value"), "up")
    delta("overdue_receivables",
          current.get("overdue_receivables"),
          (previous or {}).get("overdue_receivables"), "down")
    delta("overdue_payables",
          current.get("overdue_payables"),
          (previous or {}).get("overdue_payables"), "down")

    cur_run = current.get("runway_days")
    prev_run = (previous or {}).get("runway_days")
    if cur_run is not None and prev_run is not None:
        d = cur_run - prev_run
        trends.append({"metric": "cash_runway_days", "status": "available",
                       "current": cur_run, "previous": prev_run, "delta": d,
                       "direction": "worsening" if d < 0 else ("improving" if d > 0 else "flat")})
    else:
        trends.append({"metric": "cash_runway_days", "status": "no_baseline",
                       "current": cur_run, "previous": prev_run,
                       "direction": None, "delta": None})
    return trends
