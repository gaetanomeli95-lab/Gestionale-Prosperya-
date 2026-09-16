"""Deterministic scenario engine — BASE / STRESS / UPSIDE / custom.

Scenarios transform **copies** of the canonical facts (dated flows, debt
lines, contribution inputs) by explicit, bounded assumptions and re-run the
same pure engines. Historical actuals are never touched: a scenario is a
recompute, not a write.

Every output repeats the assumptions verbatim so a result can always be
explained as "inputs + this assumption set + this formula version".
"""
from dataclasses import dataclass, field, replace
from datetime import timedelta
from decimal import Decimal

from app.modules.controlling.metrics import (
    DebtLineFact, FlowFact, compute_dscr, continuity_view, margin_of_safety)
from app.shared.money import CENT, money, parse_signed_money

SCENARIO_FORMULA_VERSION = "scenario-v1.0"

BOUNDS = {
    "revenue_change_pct": (-100, 200),
    "collection_delay_days": (-365, 365),
    "supplier_delay_days": (-365, 365),
    "fixed_cost_monthly_delta": (-1_000_000, 1_000_000),
    "variable_cost_change_pct": (-100, 200),
    "debt_service_change_pct": (-100, 200),
}


@dataclass(frozen=True)
class ScenarioAssumptions:
    revenue_change_pct: Decimal = Decimal("0")
    collection_delay_days: int = 0        # + delays receivable due dates
    supplier_delay_days: int = 0          # + delays trade payable due dates
    fixed_cost_monthly_delta: Decimal = Decimal("0")  # extra monthly outflow
    variable_cost_change_pct: Decimal = Decimal("0")
    debt_service_change_pct: Decimal = Decimal("0")
    label: str = "SCENARIO"

    def describe(self) -> list[str]:
        out = [f"Scenario '{self.label}' — trasformazioni sulle fonti datate:"]
        out.append(f"  ricavi/incassi attesi: {self.revenue_change_pct}%")
        out.append(f"  ritardo incassi: {self.collection_delay_days} giorni")
        out.append(f"  slittamento fornitori: {self.supplier_delay_days} giorni")
        out.append(f"  delta costi fissi: {money(self.fixed_cost_monthly_delta)} EUR/mese")
        out.append(f"  costi variabili: {self.variable_cost_change_pct}%")
        out.append(f"  servizio del debito: {self.debt_service_change_pct}%")
        return out


PRESETS = {
    "base": ScenarioAssumptions(label="BASE"),
    "stress": ScenarioAssumptions(
        label="STRESS",
        revenue_change_pct=Decimal("-20"), collection_delay_days=30,
        supplier_delay_days=-15, variable_cost_change_pct=Decimal("10")),
    "upside": ScenarioAssumptions(
        label="UPSIDE",
        revenue_change_pct=Decimal("10"), collection_delay_days=-10,
        fixed_cost_monthly_delta=Decimal("-500")),
}


def parse_assumptions(raw: dict) -> ScenarioAssumptions:
    """Validate the API payload into a bounded assumption set."""
    def pct(name: str) -> Decimal:
        value = parse_signed_money(str(raw.get(name, "0")), allow_zero=True)
        lo, hi = BOUNDS[name]
        if not Decimal(lo) <= value <= Decimal(hi):
            raise ValueError(f"{name} fuori intervallo {lo}..{hi}.")
        return value

    def days(name: str) -> int:
        value = int(raw.get(name, 0))
        lo, hi = BOUNDS[name]
        if not lo <= value <= hi:
            raise ValueError(f"{name} fuori intervallo {lo}..{hi} giorni.")
        return value

    return ScenarioAssumptions(
        revenue_change_pct=pct("revenue_change_pct"),
        collection_delay_days=days("collection_delay_days"),
        supplier_delay_days=days("supplier_delay_days"),
        fixed_cost_monthly_delta=parse_signed_money(
            str(raw.get("fixed_cost_monthly_delta", "0")), allow_zero=True),
        variable_cost_change_pct=pct("variable_cost_change_pct"),
        debt_service_change_pct=pct("debt_service_change_pct"),
        label=str(raw.get("label", "SCENARIO")).upper()[:20],
    )


def apply(flows: list[FlowFact], debt_lines: list[DebtLineFact], *,
          a: ScenarioAssumptions, as_of) -> tuple[list[FlowFact], list[DebtLineFact]]:
    """Transform copies of the facts. Returns new lists — inputs untouched."""
    pct_factor = Decimal("1") + a.revenue_change_pct / Decimal("100")
    debt_factor = Decimal("1") + a.debt_service_change_pct / Decimal("100")

    new_flows: list[FlowFact] = []
    for f in flows:
        if f.direction == "inflow":
            new_flows.append(replace(
                f, due_date=f.due_date + timedelta(days=a.collection_delay_days),
                amount=(f.amount * pct_factor).quantize(CENT)))
        elif f.nature == "trade_payable":
            new_flows.append(replace(
                f, due_date=f.due_date + timedelta(days=a.supplier_delay_days)))
        else:
            new_flows.append(f)  # fiscal obligations and debt stay contractual

    new_debt = [replace(d,
                        principal=(d.principal * debt_factor).quantize(CENT),
                        interest=(d.interest * debt_factor).quantize(CENT))
                for d in debt_lines]

    if a.fixed_cost_monthly_delta != 0:
        # one extra monthly outflow line per month in the horizon
        for offset in range(12):
            month = as_of.month + offset + 1
            year = as_of.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            from datetime import date as _date
            due = _date(year, month, min(15, 28))
            new_flows.append(FlowFact(
                id=f"scenario-fixed-{year}-{month:02d}", nature="fixed_cost",
                direction="outflow", due_date=due,
                amount=a.fixed_cost_monthly_delta.copy_abs(),
                counterparty_name="Costi fissi ricorrenti (ipotesi scenario)",
                source="scenario_assumption",
                certainty="assumption" if a.fixed_cost_monthly_delta > 0 else "assumption"))
    return new_flows, new_debt


def run(flows: list[FlowFact], debt_lines: list[DebtLineFact], *,
        contribution: dict, assumptions: ScenarioAssumptions, as_of,
        opening_balance: Decimal | None, horizon_days: int = 365,
        months: int = 12) -> dict:
    """Re-run the controlling metrics under the assumption set.

    The contribution margin is recomputed from the scenario revenue/variable
    deltas; break-even follows the same formula as the base engine.
    """
    new_flows, new_debt = apply(flows, debt_lines, a=assumptions, as_of=as_of)

    # --- recompute contribution under scenario deltas (same formulas) -------
    revenue = Decimal(contribution["revenue"]) if contribution.get("revenue") else None
    variable = Decimal(contribution["variable_costs"]) if contribution.get("variable_costs") else None
    fixed = Decimal(contribution["fixed_costs"]) if contribution.get("fixed_costs") else None
    months_elapsed = contribution.get("months_elapsed") or 1
    scen_revenue = scen_variable = scen_margin = scen_be = None
    if revenue is not None:
        scen_revenue = (revenue * (Decimal("1") + assumptions.revenue_change_pct / 100)).quantize(CENT)
    if variable is not None:
        scen_variable = (variable * (Decimal("1") + assumptions.variable_cost_change_pct / 100)).quantize(CENT)
    if fixed is not None and assumptions.fixed_cost_monthly_delta != 0:
        fixed = fixed + assumptions.fixed_cost_monthly_delta * Decimal(months_elapsed)
    if scen_revenue is not None and scen_variable is not None:
        scen_margin = scen_revenue - scen_variable
        if scen_revenue > 0 and fixed is not None and scen_margin > 0:
            scen_be = (fixed / (scen_margin / scen_revenue)).quantize(CENT)

    dscr = compute_dscr(new_flows, new_debt, as_of=as_of,
                        horizon_days=horizon_days, opening_balance=opening_balance)
    continuity = continuity_view(new_flows, as_of=as_of,
                                 opening_balance=opening_balance, months=months)
    mos = margin_of_safety(scen_revenue, scen_be)

    return {
        "label": assumptions.label,
        "assumptions": {
            "revenue_change_pct": str(assumptions.revenue_change_pct),
            "collection_delay_days": assumptions.collection_delay_days,
            "supplier_delay_days": assumptions.supplier_delay_days,
            "fixed_cost_monthly_delta": money(assumptions.fixed_cost_monthly_delta),
            "variable_cost_change_pct": str(assumptions.variable_cost_change_pct),
            "debt_service_change_pct": str(assumptions.debt_service_change_pct),
        },
        "profitability": {
            "revenue": money(scen_revenue), "variable_costs": money(scen_variable),
            "fixed_costs": money(fixed), "contribution_margin": money(scen_margin),
            "contribution_margin_percent": (
                money(scen_margin / scen_revenue * 100)
                if scen_margin is not None and scen_revenue and scen_revenue > 0 else None),
            "break_even_revenue": money(scen_be),
            "margin_of_safety_percent": mos.value,
        },
        "dscr": dscr,
        "continuity": {
            "minimum_projected_balance": continuity["minimum_projected_balance"],
            "first_negative_date": continuity["first_negative_date"],
            "runway_days": continuity["runway_days"],
            "runway_status": continuity["runway_status"],
        },
        "note": ("Ricalcolo deterministico delle fonti trasformate: i consuntivi "
                 "storici non vengono modificati."),
        "formula_version": SCENARIO_FORMULA_VERSION,
    }
