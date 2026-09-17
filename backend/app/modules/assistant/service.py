"""AI assistant — deterministic, tool-bounded, evidence-carrying.

Ported from the original Prosperya prototype. The provider is an explicit
local deterministic mock: no external AI calls, no credential search, no
arbitrary SQL. Every tool call re-checks tenant/company authorization.
Answers are typed FACT | CALCULATION | ASSUMPTION | SUGGESTION.
"""
import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, ValidationError
from app.modules.cockpit import service as cockpit
from app.modules.companies.models import Company
from app.modules.controlling import scenarios as ctrl_scenarios
from app.modules.controlling import service as controlling
from app.modules.fiscal import service as fiscal
from app.modules.management import service as mgmt
from app.modules.treasury import service as treasury

#: Management tools — read `management.get_overview` only.
MANAGEMENT_TOOLS = frozenset({
    "get_financial_summary", "get_monthly_trend", "get_budget_variance",
    "get_cost_breakdown", "get_data_quality", "get_source_trace",
})
#: Treasury tools — read `treasury.snapshot` only (cash is as-of-today, not
#: period-based: the snapshot carries its own `as_of`).
TREASURY_TOOLS = frozenset({
    "get_cash_position", "get_cash_forecast", "get_receivables_aging",
    "get_reconciliation_status",
})
#: Fiscal tools — read `fiscal.fiscal_snapshot` only. The assistant reports
#: figures the deterministic engine already computed and a human validated;
#: it never calculates, estimates or validates anything fiscal itself.
FISCAL_TOOLS = frozenset({
    "get_fiscal_position", "get_fiscal_deadlines", "get_f24_drafts",
})
#: Controlling tools — read the deterministic controlling snapshot, the
#: persisted alerts and the scenario engine only. The assistant reports
#: signals the engines already produced; it never computes a metric, never
#: declares a state of crisis and never runs detection (a write).
CONTROLLING_TOOLS = frozenset({
    "get_controlling_summary", "get_dscr", "get_12m_continuity",
    "get_early_warning_alerts", "get_debt_service",
    "get_scenario_comparison", "get_controlling_data_quality",
    "get_hub_position",
})
ALLOWED_TOOLS = (MANAGEMENT_TOOLS | TREASURY_TOOLS | FISCAL_TOOLS
                 | CONTROLLING_TOOLS)
SCENARIO_FORMULA_VERSION = "revenue-scenario-v1.0"


@dataclass(frozen=True)
class ToolCall:
    name: str
    parameters: dict


@dataclass(frozen=True)
class ProviderPlan:
    calls: tuple[ToolCall, ...] = ()
    scenario: bool = False
    limitation: str | None = None
    #: True when the question asks for a legal determination ("in crisi?").
    #: The answer reports the detected signals and explicitly declines the
    #: verdict — it never says the company is or is not in crisis.
    legal_notice: bool = False


class AIProvider(Protocol):
    name: str
    mode: str

    def select_tools(self, message: str, year: int, through_month: int) -> ProviderPlan: ...


class LocalDeterministicMock:
    name = "local-deterministic-mock"
    mode = "mock"

    def select_tools(self, message: str, year: int, through_month: int) -> ProviderPlan:
        text = message.strip().lower()
        parameters = {"year": year, "through_month": through_month}
        if not text:
            return ProviderPlan(limitation="Domanda vuota: specificare un indicatore gestionale.")
        if re.search(r"\b(sql|select|delete|drop|update|insert|password|segreti|credenziali)\b", text):
            return ProviderPlan(limitation="Query SQL, credenziali e istruzioni operative non sono supportate.")
        if re.search(r"\b(altre aziende|altra azienda|tutte le aziende|altro workspace|altro tenant)\b", text):
            return ProviderPlan(limitation="Questa chat opera solo sull'azienda e sul periodo selezionati.")
        years = re.findall(r"\b(?:20[0-9]{2}|2100)\b", text)
        if any(int(value) != year for value in years):
            return ProviderPlan(limitation="Il periodo richiesto non coincide con i filtri: aggiornare anno e mese selezionati.")
        if re.search(r"\b(ebitda|utile|imposte|ires|irap|sdi|stipendi|cedolini|bandi)\b", text):
            return ProviderPlan(limitation="Fonti insufficienti: utile civilistico, EBITDA, imposte dirette (IRES/IRAP), payroll e bandi non sono calcolati in questa release.")
        if re.search(r"\b(acconto iva|acconto|quarto trimestre|4° trimestre|dichiarazione|"
                     r"rimborso|rimborsi|compensazion\w*|split payment|reverse charge|"
                     r"plafond|liquidazione di gruppo|regimi speciali)\b", text):
            return ProviderPlan(limitation="Fuori perimetro Fiscal Core V1: acconto IVA, quarto trimestre, dichiarazione annuale, rimborsi, compensazioni e regimi speciali non sono calcolati.")
        if re.search(r"\b(in crisi|stato di crisi|crisi d'impresa|crisi aziendale|"
                     r"falliment\w*|insolven\w*|bancarott\w*|prefalliment\w*)\b", text):
            names = ("get_early_warning_alerts", "get_dscr",
                     "get_12m_continuity", "get_controlling_summary")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names),
                                legal_notice=True)
        if re.search(r"\b(hub|priorit\w*|perch[eé]\b.*\b(prim\w*|attenzione|guardare)|"
                     r"da guardare|action center)\b", text):
            return ProviderPlan((ToolCall("get_hub_position", parameters),))
        if re.search(r"\b(early[ -]?warning|segnal\w*|alert\w*|allert\w*)\b", text):
            names = ("get_early_warning_alerts", "get_controlling_summary")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if re.search(r"\bdscr\b", text):
            names = ("get_dscr", "get_debt_service")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if re.search(r"\b(continuit\w*|runway|12 mesi|dodici mesi|proiezion\w* cassa)\b", text):
            return ProviderPlan((ToolCall("get_12m_continuity", parameters),))
        if re.search(r"\b(mutuo|mutui|leasing|finanziament\w*|rate\b|servizio del debito|"
                     r"debito finanziario|linee di debito)\b", text):
            return ProviderPlan((ToolCall("get_debt_service", parameters),))
        if re.search(r"\b(confront\w* scenari|scenari|stress|upside|scenario base)\b", text):
            return ProviderPlan((ToolCall("get_scenario_comparison", parameters),))
        if re.search(r"\b(controlling|margine di sicurezza|break[ -]?even)\b", text):
            names = ("get_controlling_summary", "get_controlling_data_quality")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if re.search(r"\b(iva|f24|fiscale|liquidazion\w*|erario|codice tributo|"
                     r"scadenz\w* fiscal\w*|versament\w*)\b", text):
            if re.search(r"\b(calcola|calcolare|ricalcola|simula|stima|prevedi|proietta|"
                         r"genera|trasmetti|invia|compila|paga|versa)\b", text):
                return ProviderPlan(limitation="L'assistente non calcola né produce importi fiscali: legge solo risultati già calcolati dal motore deterministico e validati da un operatore. Calcolo, validazione e generazione F24 restano azioni umane nel workspace fiscale.")
            names = ("get_fiscal_position", "get_fiscal_deadlines")
            if re.search(r"\bf24\b", text):
                names = ("get_fiscal_position", "get_fiscal_deadlines", "get_f24_drafts")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if re.search(r"\b(riconcilia\w*|abbinament\w*|movimenti bancari|non riconciliat\w*)\b", text):
            names = ("get_reconciliation_status", "get_cash_position")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if re.search(r"\b(scadut\w*|insolut\w*|crediti|incassi|scadenzario|debiti)\b", text):
            names = ("get_receivables_aging", "get_cash_position")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if re.search(r"\b(previsione|previsto|forecast|tensione|30|60|90 giorni|prossimi giorni)\b", text) \
                and re.search(r"\b(cassa|liquidità|tesoreria|flussi|saldo)\b", text):
            names = ("get_cash_forecast", "get_cash_position")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if re.search(r"\b(cassa|liquidità|tesoreria|saldo|conto corrente|banca)\b", text):
            names = ("get_cash_position", "get_cash_forecast")
            return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))
        if "%" in text or re.search(r"\b(scenario|simula|ipotizza|aumentano|aumentassero)\b", text):
            return ProviderPlan((ToolCall("get_financial_summary", parameters),), scenario=True)
        if re.search(r"\b(pagament\w*|bonific\w*)\b", text):
            return ProviderPlan(limitation="Nessuna operazione dispositiva è supportata: il modulo bancario è in sola lettura.")
        if re.search(r"\b(budget|scostament\w*)\b", text):
            names = ("get_budget_variance", "get_data_quality")
        elif re.search(r"\b(fonti|fonte|traccia|origine|movimenti)\b", text):
            names = ("get_source_trace", "get_data_quality")
        elif re.search(r"\b(qualità|completezza|copertura|mancanti)\b", text):
            names = ("get_data_quality",)
        elif re.search(r"\b(trend|andamento|calo|declino|mensile|mesi|peggiora)\b", text):
            names = ("get_monthly_trend", "get_data_quality")
        elif re.search(r"\b(categorie|categoria|costi|spese)\b", text):
            names = ("get_cost_breakdown", "get_financial_summary")
        elif re.search(r"\b(ricavi|ricavo|margine|risultato|panoramica|situazione|riepilogo)\b", text):
            names = ("get_financial_summary", "get_data_quality")
        else:
            return ProviderPlan(limitation="Domanda ambigua o non supportata dal mock locale. Chiedere ricavi, costi, risultato gestionale, trend, budget, qualità, fonti, cassa, previsione di liquidità, crediti scaduti o riconciliazione.")
        return ProviderPlan(tuple(ToolCall(name, parameters) for name in names))


provider: AIProvider = LocalDeterministicMock()


def execute_tool(db: Session, *, tenant_id, company: Company, call: ToolCall,
                 year: int, through_month: int) -> dict:
    if call.name not in ALLOWED_TOOLS:
        raise ValidationError("Strumento AI non consentito.", code="ai_tool_forbidden")
    params = call.parameters or {}
    if params.get("year") != year or params.get("through_month") != through_month:
        raise ValidationError("Lo strumento non può cambiare il periodo selezionato.",
                              code="ai_tool_params")
    if company.tenant_id != tenant_id:
        raise ForbiddenError("Confine aziendale non valido.", code="ai_scope")
    if call.name in TREASURY_TOOLS:
        return _execute_treasury_tool(db, tenant_id=tenant_id, company=company,
                                      call=call, year=year, through_month=through_month)
    if call.name in FISCAL_TOOLS:
        return _execute_fiscal_tool(db, tenant_id=tenant_id, company=company,
                                    call=call, year=year, through_month=through_month)
    if call.name in CONTROLLING_TOOLS:
        return _execute_controlling_tool(db, tenant_id=tenant_id, company=company,
                                         call=call, year=year,
                                         through_month=through_month)
    overview = mgmt.get_overview(db, tenant_id=tenant_id, company_id=company.id,
                                 year=year, through_month=through_month)
    evidence = {
        "company_id": str(company.id), "tenant_id": str(tenant_id),
        "period": overview["period"], "currency": overview["currency"],
        "formula_version": overview["trace"]["formula_version"],
        "formulas": overview["trace"]["formulas"], "quality": overview["quality"],
        "source_ids": overview["trace"]["source_ids"],
        "source_count": overview["trace"]["source_count"],
        "budget_version_ids": overview["trace"]["budget_version_ids"],
    }
    if call.name == "get_financial_summary":
        data = {key: overview[key] for key in ("revenue", "costs", "result", "margin", "margin_percent")}
    elif call.name == "get_monthly_trend":
        data = {"monthly": overview["monthly"], "comparison": overview["comparison"],
                "alerts": overview["alerts"]}
        evidence["comparison_source_ids"] = overview["comparison"]["source_ids"]
    elif call.name == "get_budget_variance":
        data = overview["budget"]
    elif call.name == "get_cost_breakdown":
        data = {"cost_categories": overview["cost_categories"], "costs": overview["costs"]}
    elif call.name == "get_data_quality":
        data = overview["quality"]
    else:
        actuals = mgmt.get_actuals(db, tenant_id=tenant_id, company_id=company.id,
                                   year=year, through_month=through_month)
        data = {"rows": actuals["rows"][:50], "source_count": len(actuals["rows"]),
                "truncated": len(actuals["rows"]) > 50}
    return {"data": data, "evidence": evidence}


def _execute_treasury_tool(db: Session, *, tenant_id, company: Company, call: ToolCall,
                           year: int, through_month: int) -> dict:
    """Read the deterministic treasury snapshot. No arithmetic happens here.

    Cash is an as-of-today measure, so the tool reports its own `as_of` while
    still carrying the selected management period for traceability.
    """
    snapshot = treasury.snapshot(db, tenant_id=tenant_id, company_id=company.id)
    position, forecast, ageing = snapshot["position"], snapshot["forecast"], snapshot["aging"]
    evidence = {
        "company_id": str(company.id), "tenant_id": str(tenant_id),
        "period": {"year": year, "through_month": through_month,
                   "label": f"as_of {snapshot['as_of']}"},
        "as_of": snapshot["as_of"], "currency": snapshot["currency"],
        "formula_version": snapshot["formula_version"],
        "formulas": {k: v for k, v in forecast["formulas"].items()},
        "quality": {
            "status": position["status"],
            "certified_complete": False,
            "issues": position["issues"],
            "accounts": len(position["accounts"]),
            "unreconciled_transactions": snapshot["counters"]["unreconciled_transactions"],
        },
        "source_ids": [item["id"] for item in ageing["receivables"]["overdue"]["items"]],
        "counters": snapshot["counters"],
        "limitations": snapshot["limitations"],
    }
    if call.name == "get_cash_position":
        data = {"position": position, "warnings": [w for w in snapshot["warnings"]
                                                   if w["category"] in ("treasury", "data_quality")]}
    elif call.name == "get_cash_forecast":
        data = {"forecast": forecast,
                "warnings": [w for w in snapshot["warnings"] if w["code"] == "cash_forecast_negative"]}
        evidence["assumptions"] = forecast["assumptions"]
    elif call.name == "get_receivables_aging":
        data = {"aging": ageing,
                "warnings": [w for w in snapshot["warnings"] if w["code"].startswith("overdue_")]}
    else:  # get_reconciliation_status
        data = {"counters": snapshot["counters"], "reconciliation": snapshot["reconciliation"],
                "warnings": [w for w in snapshot["warnings"]
                             if w["code"] in ("unreconciled_backlog", "bank_feed_stale",
                                              "sandbox_bank_data")]}
    return {"data": data, "evidence": evidence}


def _execute_fiscal_tool(db: Session, *, tenant_id, company: Company, call: ToolCall,
                         year: int, through_month: int) -> dict:
    """Read the deterministic fiscal snapshot. No arithmetic happens here.

    Every figure reported was produced by the fiscal engine and — where it is
    a liability — validated by a human. Missing data stays missing: the tool
    never treats an absent value as zero.
    """
    snapshot = fiscal.fiscal_snapshot(db, tenant_id=tenant_id, company_id=company.id,
                                      year=year)
    evidence = {
        "company_id": str(company.id), "tenant_id": str(tenant_id),
        "period": {"year": year, "through_month": through_month,
                   "label": f"anno fiscale {snapshot['year']}"},
        "as_of": snapshot["as_of"], "currency": snapshot["currency"],
        "formula_version": snapshot["engine_version"],
        "formulas": {},
        "quality": {
            "status": "available" if snapshot["counters"]["periods"] else "empty",
            "certified_complete": False,
            "issues": [w["title"] for w in snapshot["warnings"]],
            "pending_entries": snapshot["counters"]["pending_entries"],
        },
        "source_ids": [row["id"] for row in snapshot["deadlines"]],
        "counters": snapshot["counters"],
        "limitations": snapshot["limitations"],
    }
    if call.name == "get_fiscal_position":
        data = {"latest_settlement": snapshot["latest_settlement"],
                "next_obligation": fiscal.next_obligation(snapshot),
                "counters": snapshot["counters"],
                "warnings": snapshot["warnings"]}
    elif call.name == "get_fiscal_deadlines":
        data = {"deadlines": snapshot["deadlines"],
                "warnings": [w for w in snapshot["warnings"]
                             if w["code"].startswith("fiscal_")]}
    else:  # get_f24_drafts
        data = {"f24_drafts": snapshot["f24_drafts"],
                "transmission": snapshot["transmission"],
                "warnings": []}
    return {"data": data, "evidence": evidence}


def _execute_controlling_tool(db: Session, *, tenant_id, company: Company,
                              call: ToolCall, year: int, through_month: int) -> dict:
    """Read the deterministic controlling outputs. No arithmetic happens here.

    Every figure was produced by `controlling` engines on canonical facts;
    the scenario comparison re-runs the same engine on transformed copies —
    the assistant never recomputes anything itself.
    """
    snapshot = controlling.controlling_snapshot(db, tenant_id=tenant_id,
                                                company_id=company.id)
    evidence = {
        "company_id": str(company.id), "tenant_id": str(tenant_id),
        "period": {"year": year, "through_month": through_month,
                   "label": f"as_of {snapshot['as_of']}"},
        "as_of": snapshot["as_of"], "currency": snapshot["currency"],
        "formula_version": snapshot["engine_version"],
        "formula_versions": snapshot["formula_versions"],
        "formulas": {**snapshot["dscr"].get("formulas", {}),
                     **snapshot["continuity"].get("formulas", {})},
        "quality": {
            "status": ("available" if snapshot["counters"]["open_items"]
                       or snapshot["counters"]["debt_lines_scheduled"]
                       else "empty"),
            "certified_complete": False,
            "opening_balance_status": snapshot["opening_balance_status"],
            "dscr_status": snapshot["dscr"]["status"],
            "runway_status": snapshot["continuity"]["runway_status"],
            "issues": snapshot["continuity"].get("issues", []),
        },
        "source_ids": snapshot["dscr"].get("source_ids", []),
        "limitations": snapshot["limitations"],
    }
    if call.name == "get_controlling_summary":
        data = {
            "dscr": snapshot["dscr"], "continuity": {
                k: snapshot["continuity"][k] for k in (
                    "opening_balance", "opening_balance_status",
                    "minimum_projected_balance", "minimum_projected_date",
                    "first_negative_date", "runway_days", "runway_status",
                    "coverage")},
            "margin_of_safety": snapshot["profitability"]["margin_of_safety"],
            "contribution": {
                k: snapshot["profitability"]["contribution"].get(k) for k in (
                    "revenue", "variable_costs", "fixed_costs",
                    "contribution_margin", "contribution_margin_percent",
                    "break_even_revenue", "break_even_status")},
            "trends": snapshot["trends"],
            "counters": snapshot["counters"],
            "alerts_open": [a for a in snapshot["alerts"]
                            if a["status"] in ("open", "acknowledged")],
        }
    elif call.name == "get_dscr":
        data = {"dscr": snapshot["dscr"]}
    elif call.name == "get_12m_continuity":
        data = {"continuity": snapshot["continuity"]}
    elif call.name == "get_early_warning_alerts":
        data = {"alerts": snapshot["alerts"],
                "evaluations": snapshot["evaluations"],
                "counters": snapshot["counters"]}
        evidence["rule_versions"] = {
            e["rule_code"]: e["rule_version"] for e in snapshot["evaluations"]}
    elif call.name == "get_debt_service":
        facilities = controlling.list_facilities(db, tenant_id=tenant_id,
                                                 company_id=company.id)
        data = {"facilities": facilities["facilities"],
                "counters": facilities["counters"]}
        evidence["source_ids"] = [
            ln["id"] for f in facilities["facilities"]
            for ln in f.get("lines", [])]
    elif call.name == "get_scenario_comparison":
        results = {}
        for key, preset in ctrl_scenarios.PRESETS.items():
            results[key] = controlling.run_scenario(
                db, tenant_id=tenant_id, company_id=company.id,
                raw={"label": preset.label,
                     "revenue_change_pct": str(preset.revenue_change_pct),
                     "collection_delay_days": preset.collection_delay_days,
                     "supplier_delay_days": preset.supplier_delay_days,
                     "fixed_cost_monthly_delta": str(preset.fixed_cost_monthly_delta),
                     "variable_cost_change_pct": str(preset.variable_cost_change_pct),
                     "debt_service_change_pct": str(preset.debt_service_change_pct)})
        data = {"scenarios": results,
                "bounds": {k: list(v) for k, v in ctrl_scenarios.BOUNDS.items()}}
        evidence["assumptions"] = {k: r["assumptions"] for k, r in results.items()}
        evidence["scenario_formula_version"] = ctrl_scenarios.SCENARIO_FORMULA_VERSION
    elif call.name == "get_controlling_data_quality":
        data = {"opening_balance_status": snapshot["opening_balance_status"],
                "dscr_status": snapshot["dscr"]["status"],
                "dscr_reasons": snapshot["dscr"].get("reasons", []),
                "continuity_issues": snapshot["continuity"].get("issues", []),
                "continuity_coverage": snapshot["continuity"]["coverage"],
                "evaluations": [{"rule_code": e["rule_code"], "state": e["state"],
                                 "reason": e.get("reason")}
                                for e in snapshot["evaluations"]],
                "counters": snapshot["counters"],
                "limitations": snapshot["limitations"]}
    else:  # get_hub_position — why this company ranks where it ranks
        hub = cockpit.hub(db, tenant_id=tenant_id, year=year,
                          through_month=through_month)
        entry = next((e for e in hub["companies"]
                      if e["company"]["id"] == str(company.id)), None)
        company_signals = [a for a in hub["actions"]
                           if a.get("company_id") == str(company.id)]
        rank = (hub["companies"].index(entry) + 1) if entry else None
        data = {"rank": rank, "companies": len(hub["companies"]),
                "entry": entry, "signals": company_signals,
                "priority": hub["priority"],
                "aggregation_note": hub["aggregation_note"]}
        evidence["priority_version"] = hub["priority"]["version"]
    return {"data": data, "evidence": evidence}


def parse_scenario_percentage(message: str) -> Decimal:
    text = re.sub(r"([+-])\s+([0-9])", r"\1\2", message.strip().lower())
    percentages = re.findall(r"[+-]?[0-9]+(?:[.,][0-9]+)?\s*%", text)
    if len(percentages) != 1:
        raise ValueError("Specificare una sola variazione percentuale dei ricavi, con costi invariati.")
    pattern = (
        r"\bricavi\s*(?:(?:aumentano|aumentassero|crescono|crescessero|aumento)\s*(?:del|di)?\s*|"
        r"(?:diminuiscono|diminuissero|calano|calassero)\s*(?:del|di)?\s*|"
        r"(?:a|di|del)\s*)?(?P<percent>[+-]?[0-9]{1,4}(?:[.,][0-9]{1,2})?)\s*%"
    )
    match = re.search(pattern, text)
    if match is None:
        raise ValueError("Scenario supportato: 'ricavi aumentano del 5%' oppure 'ricavi +5,5%'; nessun altro driver.")
    before, after = text[:match.start()], text[match.end():]
    before = re.sub(r"\b(se|e|i|gli|simula|uno|un|scenario|ipotizza|ipotizzando|cosa|succede|succederebbe|con|che)\b", " ", before)
    after = re.sub(r"\b(?:con\s+)?(?:i\s+)?costi\s+(?:invariati|costanti|fermi)\b", " ", after)
    after = re.sub(r"\b(a|parità|di|costi|che|cosa|succede|succederebbe|al|risultato|gestionale|e|i|con)\b", " ", after)
    if re.sub(r"[\s,;:.!?()]+", "", before + after):
        raise ValueError("Scenario ambiguo o con driver aggiuntivi: supportata solo la variazione dei ricavi a costi invariati.")
    value = Decimal(match.group("percent").replace(",", "."))
    decreasing = re.search(r"\b(diminuiscono|diminuissero|calano|calassero)\b", match.group(0)) is not None
    increasing = re.search(r"\b(aumentano|aumentassero|crescono|crescessero|aumento)\b", match.group(0)) is not None
    if (increasing and value < 0) or (decreasing and match.group("percent").startswith("+")):
        raise ValueError("Il segno della percentuale contraddice la variazione richiesta.")
    if decreasing:
        value = -abs(value)
    if not value.is_finite() or value < Decimal("-100") or value > Decimal("1000"):
        raise ValueError("Variazione fuori intervallo supportato: da -100% a +1000%.")
    return value


def run_simple_scenario(summary: dict, change_percent: Decimal) -> dict:
    if not isinstance(change_percent, Decimal) or not change_percent.is_finite():
        raise ValueError("La variazione dello scenario deve essere Decimal finito.")
    if change_percent.as_tuple().exponent < -2 or not Decimal("-100") <= change_percent <= Decimal("1000"):
        raise ValueError("Variazione percentuale non supportata.")
    base_revenue, base_costs = summary.get("revenue"), summary.get("costs")
    if base_revenue is None or base_costs is None:
        raise ValueError("Ricavi o costi mancanti: impossibile calcolare lo scenario senza inventare dati.")
    if not all(re.fullmatch(r"[0-9]{1,30}(?:\.[0-9]{1,2})?", v) for v in (base_revenue, base_costs)):
        raise ValueError("Importi base non validi per lo scenario.")
    revenue, costs = Decimal(base_revenue), Decimal(base_costs)
    with localcontext() as context:
        context.prec = 50
        scenario_revenue = Decimal(mgmt.money(revenue * (Decimal("1") + change_percent / Decimal("100"))))
        base_result = revenue - costs
        scenario_result = scenario_revenue - costs
        return {
            "formula_version": SCENARIO_FORMULA_VERSION,
            "change_percent": mgmt.money(change_percent), "base_revenue": mgmt.money(revenue),
            "base_costs": mgmt.money(costs), "base_result": mgmt.money(base_result),
            "revenue": mgmt.money(scenario_revenue), "costs": mgmt.money(costs),
            "result": mgmt.money(scenario_result),
            "result_change": mgmt.money(scenario_result - base_result),
            "margin_percent": mgmt.percentage(scenario_result, scenario_revenue),
            "formulas": {"revenue": "Arrotonda a 2 decimali HALF_UP(ricavi disponibili * (1 + variazione_percentuale / 100))",
                         "result": "Ricavi scenario - costi disponibili invariati",
                         "result_change": "Risultato scenario - risultato gestionale disponibile di base"},
            "assumptions": ["Costi mantenuti invariati per ipotesi esplicita dello scenario.",
                            "Stesso periodo e stesse fonti parziali: non è previsione né budget approvato.",
                            "Nessun effetto modellato su volumi, prezzi, imposte, capitale circolante o capacità."],
        }


def item(kind: str, text: str) -> dict:
    return {"type": kind, "text": text}


def _render_warnings(warnings: list[dict]) -> list[dict]:
    """Deterministic warnings become typed items — never reworded numbers."""
    items = []
    for warning in warnings:
        kind = "ACTION_REQUIRED" if warning["action_required"] else "WARNING"
        items.append(item(kind, f"{warning['title']}: {warning['message']} "
                                f"[regola: {warning['formula']}]"))
    return items


def render_treasury(name: str, result: dict) -> list[dict]:
    data, evidence = result["data"], result["evidence"]
    currency, as_of = evidence["currency"], evidence["as_of"]
    if name == "get_cash_position":
        position = data["position"]
        items = []
        if position["amount"] is not None:
            items.append(item("FACT", f"Posizione di cassa al {as_of}: {position['amount']} {currency} "
                                      f"su {len(position['accounts'])} conto/i; saldo più vecchio del "
                                      f"{position['oldest_balance_date']}."))
        else:
            items.append(item("FACT", f"Posizione di cassa al {as_of} non determinabile: "
                                      f"manca il saldo di almeno un conto. Nessun valore è assunto pari a zero."))
        for account in position["accounts"]:
            suffix = "" if account["is_real_institution"] else " (provider sandbox simulato)"
            items.append(item("FACT", f"{account['label']}: saldo "
                                      f"{account['balance'] if account['balance'] is not None else 'non disponibile'} "
                                      f"{currency} al {account['balance_date'] or 'data assente'}{suffix}."))
        return [*items, *_render_warnings(data["warnings"])]
    if name == "get_cash_forecast":
        forecast = data["forecast"]
        items = [item("FACT", f"Saldo iniziale al {as_of}: "
                              f"{forecast['opening_balance'] or 'non determinabile'} {currency}.")]
        for window in forecast["horizons"]:
            items.append(item("CALCULATION",
                              f"Orizzonte {window['horizon_days']} giorni (al {window['end_date']}): "
                              f"incassi attesi {window['expected_inflows'] or 'n.d.'} {currency}, "
                              f"pagamenti attesi {window['expected_outflows'] or 'n.d.'} {currency}, "
                              f"flusso netto {window['net_flow'] or 'n.d.'} {currency}, "
                              f"saldo proiettato {window['projected_balance'] or 'n.d.'} {currency} "
                              f"su {window['item_count']} partite."))
        excluded = forecast["overdue_excluded"]
        if excluded["count"]:
            items.append(item("ASSUMPTION",
                              f"{excluded['count']} partite già scadute "
                              f"(crediti {excluded['receivable'] or 'n.d.'} {currency}, "
                              f"debiti {excluded['payable'] or 'n.d.'} {currency}) NON sono "
                              f"considerate incassate e restano fuori dalla proiezione."))
        for assumption in forecast["assumptions"]:
            items.append(item("ASSUMPTION", assumption))
        return [*items, *_render_warnings(data["warnings"])]
    if name == "get_receivables_aging":
        ageing = data["aging"]
        items = []
        for side, title in (("receivables", "Crediti"), ("payables", "Debiti")):
            block = ageing[side]
            items.append(item("FACT", f"{title} aperti al {as_of}: "
                                      f"{block['total'] or 'nessuno'} {currency} su {block['count']} partite; "
                                      f"scaduti {block['overdue']['amount'] or '0.00'} {currency} "
                                      f"({block['overdue']['count']} partite, max "
                                      f"{block['overdue']['max_days']} giorni)."))
            for bucket, amount in block["buckets"].items():
                if amount["count"]:
                    items.append(item("FACT", f"{title} fascia {bucket}: {amount['amount']} {currency} "
                                              f"su {amount['count']} partite."))
        return [*items, *_render_warnings(data["warnings"])]
    counters, reconciliation = data["counters"], data["reconciliation"]
    items = [
        item("FACT", f"Movimenti bancari non riconciliati: {counters['unreconciled_transactions']} "
                     f"per {counters['unreconciled_amount'] or '0.00'} {currency}."),
        item("FACT", f"Partite aperte: {counters['open_items']}, di cui scadute "
                     f"{counters['overdue_items']}."),
        item("FACT", f"Motore di riconciliazione {reconciliation['engine_version']}: livelli "
                     f"{reconciliation['levels_implemented']} deterministici attivi; "
                     f"livello 3 (triage AI) {reconciliation['level_3_ai_triage']}."),
        item("SUGGESTION", "I movimenti non riconciliati rendono incompleti gli indicatori di incasso: "
                           "completare la riconciliazione prima di decidere."),
    ]
    return [*items, *_render_warnings(data["warnings"])]


def render_fiscal(name: str, result: dict) -> list[dict]:
    """Fiscal answers are typed and evidence-backed: every figure names the
    engine version and the human validation that produced it."""
    data, evidence = result["data"], result["evidence"]
    currency, as_of = evidence["currency"], evidence["as_of"]
    if name == "get_fiscal_position":
        items = []
        latest = data["latest_settlement"]
        if latest is None:
            items.append(item("FACT", "Nessuna liquidazione IVA calcolata per l'anno selezionato: "
                                      "nessun importo è assunto pari a zero."))
        else:
            period_label = latest["period"]["label"] if latest["period"] else "n.d."
            items.append(item("FACT", f"Ultima liquidazione ({period_label}, v{latest['version']}, "
                                      f"stato {latest['status']}): posizione netta "
                                      f"{latest['net_position'] or 'n.d.'} {currency}, "
                                      f"versamento {latest['payable_amount'] or 'non dovuto'} {currency}."))
            if latest["status"] == "validated":
                items.append(item("FACT", "Liquidazione validata da un operatore: "
                                          "l'importo non è una stima del modello."))
        obligation = data["next_obligation"]
        if obligation is not None:
            items.append(item("FACT", f"Prossima obbligazione validata: {obligation['amount']} "
                                      f"{currency} in scadenza il {obligation['due_date']}."))
        counters = data["counters"]
        items.append(item("FACT", f"Periodi tracciati {counters['periods']}, liquidazioni "
                                  f"validate {counters['validated']}, voci IVA da verificare "
                                  f"{counters['pending_entries']}, bozze F24 {counters['f24_drafts']}."))
        return [*items, *_render_warnings(data["warnings"])]
    if name == "get_fiscal_deadlines":
        items = []
        if not data["deadlines"]:
            items.append(item("FACT", f"Nessuna scadenza fiscale registrata al {as_of}."))
        for row in data["deadlines"]:
            items.append(item("FACT", f"{row['kind']}: {row['amount'] or 'n.d.'} {currency}, "
                                      f"scadenza {row['due_date'] or 'da confermare'} "
                                      f"(statutaria {row['statutory_date'] or 'n.d.'}), "
                                      f"stato {row['status']}."))
        return [*items, *_render_warnings(data["warnings"])]
    # get_f24_drafts
    items = []
    if not data["f24_drafts"]:
        items.append(item("FACT", "Nessuna bozza F24 generata: si genera solo da una "
                                  "liquidazione validata con importo a debito."))
    for draft in data["f24_drafts"]:
        items.append(item("FACT", f"Bozza F24 {draft['id'][:8]}: saldo {draft['balance']} "
                                  f"{currency}, scadenza {draft['due_date'] or 'n.d.'}, "
                                  f"stato {draft['status']}."))
    items.append(item("FACT", f"Trasmissione telematica: {data['transmission']['note']}"))
    return items


def render_controlling(name: str, result: dict) -> list[dict]:
    """Controlling answers: signals and metrics the engines produced, with
    their versions. The assistant explains — it never declares a state of
    crisis and never recomputes a value."""
    data, evidence = result["data"], result["evidence"]
    currency, as_of = evidence["currency"], evidence["as_of"]
    if name == "get_controlling_summary":
        items = []
        dscr = data["dscr"]
        items.append(item(
            "CALCULATION",
            f"DSCR prospettico ({dscr['horizon_days']} giorni, al {as_of}): "
            f"{dscr['value'] if dscr['value'] is not None else 'non calcolabile'} "
            f"— stato {dscr['status']}; numeratore "
            f"{dscr.get('numerator') or 'n.d.'} {currency}, denominatore "
            f"{dscr.get('denominator') or 'n.d.'} {currency} "
            f"[{dscr['formula_version']}]."))
        cont = data["continuity"]
        items.append(item(
            "CALCULATION",
            f"Continuità 12 mesi: saldo minimo proiettato "
            f"{cont['minimum_projected_balance'] or 'n.d.'} {currency} "
            f"({cont['minimum_projected_date'] or 'n.d.'}), runway "
            f"{cont['runway_status']}"
            + (f" — prima data negativa {cont['first_negative_date']}"
               if cont["first_negative_date"] else "") + "."))
        mos = data["margin_of_safety"]
        items.append(item(
            "CALCULATION",
            f"Margine di sicurezza: {mos['value'] + '%' if mos['value'] else mos['status']}"
            + (f" ({'; '.join(mos['reasons'])})" if mos["reasons"] else "") + "."))
        contrib = data["contribution"]
        if contrib.get("contribution_margin") is not None:
            items.append(item(
                "FACT",
                f"Margine di contribuzione {contrib['contribution_margin']} {currency} "
                f"({contrib.get('contribution_margin_percent') or 'n.d.'}%); "
                f"break-even {contrib.get('break_even_revenue') or 'n.d.'} {currency}."))
        open_count = len(data["alerts_open"])
        items.append(item(
            "FACT",
            f"Alert early-warning attivi: {open_count} "
            f"(regole valutate {data['counters']['rules_active']}, "
            f"scattate {data['counters']['rules_fired']})."))
        return items
    if name == "get_dscr":
        dscr = data["dscr"]
        items = [item(
            "CALCULATION",
            f"DSCR prospettico = {dscr['value'] if dscr['value'] is not None else 'non calcolabile'} "
            f"(stato {dscr['status']}, orizzonte {dscr['horizon_days']} giorni "
            f"fino al {dscr['horizon_end']}).")]
        items.append(item(
            "FACT",
            f"Numeratore (CFADS proxy) {dscr.get('numerator') or 'n.d.'} {currency} "
            f"= incassi attesi {dscr['components']['expected_inflows'] or 'n.d.'} "
            f"− pagamenti attesi {dscr['components']['expected_outflows_ex_debt'] or 'n.d.'}; "
            f"denominatore (servizio del debito) "
            f"{dscr.get('denominator') or 'n.d.'} {currency} su "
            f"{dscr['components']['instalments_due']} rate."))
        for reason in dscr.get("reasons", []):
            items.append(item("WARNING", reason))
        for assumption in dscr.get("assumptions", []):
            items.append(item("ASSUMPTION", assumption))
        items.append(item("FACT", f"Formula {dscr['formula_version']}, motore "
                                  f"{dscr['engine_version']}: il DSCR è un proxy "
                                  "gestionale, non una determinazione legale."))
        return items
    if name == "get_12m_continuity":
        cont = data["continuity"]
        items = [item(
            "FACT",
            f"Saldo iniziale al {as_of}: "
            f"{cont['opening_balance'] or 'non determinabile'} {currency} "
            f"({cont['opening_balance_status']}).")]
        for bucket in cont["buckets"]:
            if not bucket["has_data"]:
                continue
            items.append(item(
                "CALCULATION",
                f"{bucket['label']}: incassi {bucket['inflows']} {currency}, "
                f"uscite {bucket['outflows']} {currency} "
                f"({', '.join(f'{k} {v}' for k, v in bucket['outflow_by_nature'].items())}), "
                f"saldo proiettato {bucket['projected_balance'] or 'n.d.'} {currency}."))
        items.append(item(
            "CALCULATION",
            f"Minimo proiettato {cont['minimum_projected_balance'] or 'n.d.'} "
            f"{currency}; runway {cont['runway_status']}"
            + (f", prima data negativa {cont['first_negative_date']}"
               if cont["first_negative_date"] else "") + "."))
        for issue in cont.get("issues", []):
            items.append(item("WARNING", issue))
        return items
    if name == "get_early_warning_alerts":
        items = []
        if not data["alerts"]:
            items.append(item("FACT", "Nessun alert early-warning registrato: la "
                                      "detection è una valutazione esplicita "
                                      "(Rivaluta segnali nel workspace)."))
        for alert in data["alerts"]:
            kind = "ACTION_REQUIRED" if alert["severity"] == "critical" else "WARNING"
            items.append(item(
                kind,
                f"{alert['rule_code']} v{alert['rule_version']} "
                f"[{alert['status']}]: {alert['title']} — {alert['message']} "
                f"(rilevato il {alert['detected_at']})."))
        for evaluation in data["evaluations"]:
            if evaluation["state"] in ("insufficient_data", "unsupported"):
                items.append(item("FACT", f"{evaluation['rule_code']}: "
                                          f"{evaluation['state']} — "
                                          f"{evaluation.get('reason', '')}"))
        return items
    if name == "get_debt_service":
        items = []
        if not data["facilities"]:
            items.append(item("FACT", "Nessuna linea di debito registrata."))
        for facility in data["facilities"]:
            items.append(item(
                "FACT",
                f"{facility['name']} ({facility['facility_type']}"
                f"{', ' + facility['lender_name'] if facility['lender_name'] else ''}): "
                f"residuo {facility['outstanding_principal'] or 'n.d.'} {currency}, "
                f"{facility['scheduled_count']} rate pianificate per "
                f"{facility['scheduled_service'] or 'n.d.'} {currency}."))
            for line in facility.get("lines", []):
                if line["status"] == "scheduled":
                    items.append(item(
                        "FACT",
                        f"Rata {line['instalment_no']} del {line['due_date']}: "
                        f"{line['service']} {currency} "
                        f"(capitale {line['principal']}, interessi {line['interest']})."))
        return items
    if name == "get_scenario_comparison":
        items = []
        for scenario in data["scenarios"].values():
            prof = scenario["profitability"]
            items.append(item(
                "CALCULATION",
                f"{scenario['label']}: DSCR "
                f"{scenario['dscr']['value'] if scenario['dscr']['value'] is not None else scenario['dscr']['status']}, "
                f"cassa minima {scenario['continuity']['minimum_projected_balance'] or 'n.d.'} "
                f"{currency}, runway {scenario['continuity']['runway_status']}, "
                f"margine contribuzione {prof['contribution_margin'] or 'n.d.'} {currency}, "
                f"break-even {prof['break_even_revenue'] or 'n.d.'} {currency}."))
        items.append(item(
            "ASSUMPTION",
            "Simulazioni deterministiche su copie dei dati: i consuntivi "
            "storici non cambiano. Ipotesi complete nelle evidenze."))
        return items
    if name == "get_controlling_data_quality":
        items = [item(
            "FACT",
            f"Saldo iniziale: {data['opening_balance_status']}; DSCR: "
            f"{data['dscr_status']}; copertura continuità "
            f"{data['continuity_coverage']['months_with_data']}/"
            f"{data['continuity_coverage']['months_total']} mesi.")]
        for evaluation in data["evaluations"]:
            if evaluation["state"] != "fired":
                items.append(item("FACT", f"{evaluation['rule_code']}: "
                                          f"{evaluation['state']}"
                                          + (f" — {evaluation['reason']}"
                                             if evaluation.get("reason") else "")))
        for issue in data["continuity_issues"]:
            items.append(item("WARNING", issue))
        return items
    # get_hub_position
    if data["entry"] is None:
        return [item("FACT", "Azienda non presente nella vista hub del periodo.")]
    entry = data["entry"]
    items = [item(
        "FACT",
        f"Posizione {data['rank']} su {data['companies']} nel Control hub "
        f"(attenzione {entry['attention_score']}, stato {entry['health']['status']}: "
        f"{entry['health']['reason']}).")]
    for signal in data["signals"]:
        kind = "ACTION_REQUIRED" if signal["action_required"] else "WARNING"
        items.append(item(
            kind,
            f"{signal['code']} [{signal['category']}, priorità {signal['priority']}]: "
            f"{signal['title']} — {signal['message']}"))
    items.append(item("FACT", f"Ranking deterministico: {data['priority']['formula']} "
                              f"[{data['priority']['version']}]."))
    return items


def render_tool(name: str, result: dict) -> list[dict]:
    if name in TREASURY_TOOLS:
        return render_treasury(name, result)
    if name in FISCAL_TOOLS:
        return render_fiscal(name, result)
    if name in CONTROLLING_TOOLS:
        return render_controlling(name, result)
    data, evidence = result["data"], result["evidence"]
    label, currency = evidence["period"]["label"], evidence["currency"]
    if name == "get_financial_summary":
        items = []
        for key, title in (("revenue", "Ricavi disponibili"), ("costs", "Costi disponibili")):
            items.append(item("FACT", f"{label}: {title} {data[key]} {currency}." if data[key] is not None
                              else f"{label}: {title} non determinabili, fonti mancanti."))
        if data["result"] is not None:
            items.append(item("CALCULATION", f"Risultato gestionale disponibile: {data['result']} {currency} = ricavi disponibili - costi disponibili; non è EBITDA né utile civilistico."))
        if data["margin_percent"] is not None:
            items.append(item("CALCULATION", f"Margine gestionale disponibile: {data['margin_percent']}% = risultato disponibile / ricavi disponibili × 100."))
        return items
    if name == "get_monthly_trend":
        items = []
        for month in data["monthly"]:
            values = ", ".join(
                f"{title} {month[key]} {currency}" if month[key] is not None else f"{title} non determinabili"
                for key, title in (("revenue", "ricavi"), ("costs", "costi")))
            items.append(item("FACT", f"Mese {month['month']}: {values}; importi disponibili."))
        for alert in data["alerts"]:
            items.append(item("CALCULATION", f"{alert['title']}: {alert['message']}"))
        comparison = data["comparison"]
        if comparison["revenue_change_percent"] is not None:
            items.append(item("CALCULATION", f"Variazione ricavi disponibili rispetto a {comparison['period']['label']}: {comparison['revenue_change_percent']}%; stessi mesi di calendario."))
        return items
    if name == "get_budget_variance":
        items = []
        for key, title in (("revenue", "ricavi"), ("costs", "costi"), ("result", "risultato")):
            kind = "CALCULATION" if key == "result" else "FACT"
            items.append(item(kind, f"Budget {title}, {label}: {data[key]} {currency}." if data[key] is not None
                              else f"Budget {title}, {label}: componente o mesi mancanti, valore non determinabile."))
        for key, title in (("revenue_variance", "ricavi"), ("cost_variance", "costi"), ("result_variance", "risultato")):
            if data[key] is not None:
                items.append(item("CALCULATION", f"Scostamento {title}: {data[key]} {currency} = consuntivo disponibile - budget dello stesso periodo."))
        return items
    if name == "get_cost_breakdown":
        if not data["cost_categories"]:
            return [item("FACT", "Nessuna fonte di costo disponibile nel periodo selezionato.")]
        return [item("FACT", f"{label}, categoria {category['category']}: {category['amount']} {currency} di costi disponibili.")
                for category in data["cost_categories"]]
    if name == "get_data_quality":
        return [item("FACT", f"Copertura osservata: {data['covered_months']} mesi su {data['expected_months']}; stato {data['status']}. Non certifica completezza."),
                *[item("FACT", issue) for issue in data["issues"]]]
    items = [item("FACT", f"Fonti disponibili nel periodo: {data['source_count']}; riferimenti di dettaglio nelle evidenze.")]
    if data["truncated"]:
        items.append(item("FACT", "Dettaglio limitato alle prime fonti; usare il registro consuntivi per l'elenco completo."))
    return items


def chat(db: Session, *, tenant_id, company: Company, message: str,
         year: int, through_month: int,
         selected_provider: AIProvider | None = None) -> dict:
    if company.tenant_id != tenant_id:
        raise ForbiddenError("Contesto aziendale non valido.", code="ai_scope")
    selected_provider = selected_provider or provider
    plan = selected_provider.select_tools(message, year, through_month)
    response = {
        "provider": selected_provider.name, "mode": selected_provider.mode,
        "items": [], "tools_used": [],
        "evidence": {"company_id": str(company.id), "tenant_id": str(tenant_id),
                     "period": {"year": year, "through_month": through_month},
                     "formula_version": mgmt.FORMULA_VERSION, "tools": [],
                     "source_ids": [], "formulas": {},
                     "quality": {"status": "not_evaluated", "certified_complete": False}},
        "limitations": ["Provider mock locale deterministico: nessuna chiamata AI esterna e nessuna ricerca di credenziali.",
                        "Fonti non certificate complete; risultato gestionale disponibile, non EBITDA, utile o cassa.",
                        "Cassa e scadenzario provengono dai motori deterministici di tesoreria: "
                        "nessun importo è calcolato dal modello linguistico.",
                        "I dati fiscali (IVA, F24) sono letti dal motore deterministico e riportano "
                        "solo risultati già calcolati e validati da un operatore: l'assistente non "
                        "calcola, non stima e non valida importi fiscali. IRES/IRAP, acconto IVA, "
                        "quarto trimestre, dichiarazione, payroll e bandi restano fuori perimetro.",
                        "Gli indicatori di controlling (DSCR, continuità, early warning) sono letti "
                        "dai motori deterministici: l'assistente non ricalcola metriche, non esegue "
                        "la detection e non determina mai uno stato di crisi — riporta i segnali "
                        "rilevati con regola, versione ed evidenza."],
    }
    if plan.limitation:
        response["limitations"].append(plan.limitation)
        response["items"].append(item("SUGGESTION", plan.limitation))
        return response
    if plan.legal_notice:
        notice = ("Il sistema non determina lo stato di crisi: riporta i "
                  "segnali early-warning rilevati, gli indicatori di liquidità "
                  "e la qualità dei dati. La valutazione di crisi d'impresa "
                  "spetta agli organi competenti.")
        response["limitations"].append(notice)
        response["items"].append(item("WARNING", notice))
    if (not plan.calls or len(plan.calls) > len(ALLOWED_TOOLS)
            or len({call.name for call in plan.calls}) != len(plan.calls)):
        raise ValidationError("Piano strumenti AI non valido.", code="ai_plan_invalid")
    change_percent = None
    if plan.scenario:
        if tuple(call.name for call in plan.calls) != ("get_financial_summary",):
            raise ValidationError("Piano scenario non consentito.", code="ai_plan_invalid")
        try:
            change_percent = parse_scenario_percentage(message)
        except ValueError as exc:
            response["limitations"].append(str(exc))
            response["items"].append(item("SUGGESTION", str(exc)))
            return response
    results = {}
    for call in plan.calls:
        result = execute_tool(db, tenant_id=tenant_id, company=company, call=call,
                              year=year, through_month=through_month)
        results[call.name] = result
        response["tools_used"].append(call.name)
        tool_evidence = {"tool": call.name, **result["evidence"]}
        if call.name == "get_source_trace":
            tool_evidence["rows"] = result["data"]["rows"]
        response["evidence"]["tools"].append(tool_evidence)
        if not plan.scenario:
            response["items"].extend(render_tool(call.name, result))
    primary = next(iter(results.values()))["evidence"]
    response["evidence"].update(
        {key: primary[key] for key in ("period", "currency", "quality", "source_ids", "formulas")})
    if plan.scenario:
        try:
            scenario = run_simple_scenario(results["get_financial_summary"]["data"], change_percent)
        except ValueError as exc:
            response["limitations"].append(str(exc))
            response["items"].append(item("SUGGESTION", str(exc)))
            return response
        response["tools_used"].append("run_simple_scenario")
        response["evidence"]["scenario"] = scenario
        response["items"].extend(render_tool("get_financial_summary", results["get_financial_summary"]))
        response["items"].append(item("ASSUMPTION", f"Variazione ricavi richiesta: {scenario['change_percent']}%; costi invariati. Non è una previsione."))
        response["items"].append(item("CALCULATION", f"Scenario: ricavi {scenario['revenue']} {primary['currency']}, costi invariati {scenario['costs']} {primary['currency']}, risultato gestionale {scenario['result']} {primary['currency']}; variazione risultato {scenario['result_change']} {primary['currency']}."))
    response["items"].append(item("SUGGESTION", "Verificare copertura e riconciliazione delle fonti prima di assumere decisioni gestionali."))
    return response


AnswerItemType = Literal[
    "FACT", "CALCULATION", "ASSUMPTION", "SUGGESTION", "WARNING", "ACTION_REQUIRED",
]
