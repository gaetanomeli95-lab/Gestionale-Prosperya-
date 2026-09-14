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
from app.modules.companies.models import Company
from app.modules.management import service as mgmt

ALLOWED_TOOLS = frozenset({
    "get_financial_summary", "get_monthly_trend", "get_budget_variance",
    "get_cost_breakdown", "get_data_quality", "get_source_trace",
})
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
        if re.search(r"\b(ebitda|utile|imposte|fiscale|iva|cassa|liquidità|pagamenti|sdi|stipendi)\b", text):
            return ProviderPlan(limitation="Le fonti gestionali non consentono di calcolare utile, EBITDA, imposte o cassa né eseguire operazioni.")
        if "%" in text or re.search(r"\b(scenario|simula|ipotizza|aumentano|aumentassero)\b", text):
            return ProviderPlan((ToolCall("get_financial_summary", parameters),), scenario=True)
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
            return ProviderPlan(limitation="Domanda ambigua o non supportata dal mock locale. Chiedere ricavi, costi, risultato gestionale, trend, budget, qualità o fonti.")
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


def render_tool(name: str, result: dict) -> list[dict]:
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
                        "Fonti non certificate complete; risultato gestionale disponibile, non EBITDA, utile o cassa."],
    }
    if plan.limitation:
        response["limitations"].append(plan.limitation)
        response["items"].append(item("SUGGESTION", plan.limitation))
        return response
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


AnswerItemType = Literal["FACT", "CALCULATION", "ASSUMPTION", "SUGGESTION"]
