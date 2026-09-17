"""Early-warning rule seeds + pure evaluation.

SEPARATION OF CONCERNS (ADR-022): these are **legal/organizational** signals
anchored to the Codice della crisi (D.Lgs. 14/2019, as reshaped by D.Lgs.
83/2022) — not management KPIs. They never conclude "the company is in
crisis": they surface *segnali da verificare* with evidence and the rule
version that fired.

Honesty rules:
- thresholds are declared `statutory` only when anchored to a verified norm,
  otherwise `operational` (a working parameter, explicitly not law);
- a rule returns `unsupported` when the required data type does not exist and
  `insufficient_data` when it exists but is absent;
- nothing here produces a judicial determination.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.shared.money import money

EW_FORMULA_VERSION = "early-warning-v1.0"
ENGINE_VERSION = "controlling-v1.0"

NORMATTIVA_CCII = ("https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:"
                   "decreto.legislativo:2019-01-12;14")

#: Categories that classify an open payable as personnel/payroll exposure.
PAYROLL_CATEGORIES = frozenset({"payroll", "personale", "retribuzioni", "contributi"})
#: Categories that classify an open payable as financial exposure.
FINANCIAL_CATEGORIES = frozenset({"finanziario", "banca", "debito_finanziario"})


@dataclass(frozen=True)
class EwFacts:
    """Everything the evaluator needs — assembled by the service, never by rules."""

    as_of: date
    overdue_payroll_amount: Decimal | None      # payables payroll-category overdue
    overdue_payroll_count: int
    overdue_payroll_max_days: int
    payroll_items_configured: bool              # any payable ever categorised payroll
    overdue_supplier_amount: Decimal | None     # trade payables overdue (non-fiscal, non-fin)
    supplier_payable_total: Decimal | None      # all trade payables open
    overdue_supplier_max_days: int
    overdue_financial_amount: Decimal | None    # debt lines + financial payables overdue
    overdue_financial_count: int
    overdue_public_amount: Decimal | None       # fiscal-source open items overdue
    overdue_public_count: int
    dscr_value: Decimal | None
    dscr_status: str                            # available | partial | not_applicable | insufficient_data
    first_negative_date: str | None
    days_to_negative: int | None
    opening_balance_status: str                 # available | not_calculable
    source_ids: dict


def seed_definitions() -> list[dict]:
    """The verified rules loaded by `rules_seed.ensure_rules`. Effective-dated
    from 2026-01-01; a regulatory change must arrive as a new version."""
    return [
        {
            "code": "EW-FIN-OVERDUE", "version": 1, "category": "ccii_legal",
            "title": "Esposizione verso intermediari finanziari scaduta",
            "description": (
                "Rate di debito o partite finanziarie scadute e non regolate: "
                "indice di possibile squilibrio finanziario da verificare."),
            "legal_reference": (
                "D.Lgs. 14/2019 (CCII), artt. 3 e 25-nonies: obbligo di assetti "
                "adeguati e rilevazione di squilibri; la soglia è un parametro "
                "operativo, non un valore di legge."),
            "source_authority": "Normattiva — Codice della crisi d'impresa",
            "source_url": NORMATTIVA_CCII,
            "params": {"min_days_overdue": {"value": 1, "kind": "operational"}},
            "data_requirements": ["debt_service_lines", "open_items(financial)"],
            "formula": ("rate/prestiti scaduti (scheduled, due_date < as_of) con "
                        "ritardo >= soglia → segnale"),
        },
        {
            "code": "EW-PAYROLL-OVERDUE", "version": 1, "category": "ccii_legal",
            "title": "Debiti verso personale/previdenziali scaduti",
            "description": (
                "Retribuzioni o contributi scaduti oltre la soglia operativa: "
                "segnale qualificato verso dipendenti ed enti previdenziali."),
            "legal_reference": (
                "D.Lgs. 14/2019, artt. 3 e 25-nonies: debiti verso dipendenti e "
                "previdenziali sono tra gli squilibri rilevanti; soglie "
                "quantitative correnti da verificare sul testo vigente."),
            "source_authority": "Normattiva — Codice della crisi d'impresa",
            "source_url": NORMATTIVA_CCII,
            "params": {"min_days_overdue": {"value": 30, "kind": "operational"}},
            "data_requirements": ["open_items(payroll)"],
            "formula": ("partite payable di categoria personale/payroll scadute "
                        "da >= soglia giorni → segnale"),
        },
        {
            "code": "EW-SUPPLIER-OVERDUE", "version": 1, "category": "organizational",
            "title": "Tensione sull'esposizione commerciale",
            "description": (
                "Quota rilevante dei debiti commerciali scaduta oltre la soglia: "
                "possibile tensione di liquidità verso la filiera."),
            "legal_reference": (
                "D.Lgs. 14/2019 art. 3: assetti adeguati a rilevare tempestivamente "
                "gli squilibri; percentuali operative, non normative."),
            "source_authority": "Normattiva — Codice della crisi d'impresa",
            "source_url": NORMATTIVA_CCII,
            "params": {"min_days_overdue": {"value": 30, "kind": "operational"},
                       "min_share_percent": {"value": 30, "kind": "operational"}},
            "data_requirements": ["open_items(trade_payable)"],
            "formula": ("debiti commerciali scaduti > soglia giorni / totale debiti "
                        "commerciali aperti >= soglia % → segnale"),
        },
        {
            "code": "EW-PUBLIC-CREDITOR", "version": 1, "category": "ccii_legal",
            "title": "Obbligazioni fiscali scadute non versate",
            "description": (
                "Versamenti fiscali validati e scaduti senza regolazione: "
                "esposizione verso creditori pubblici qualificati."),
            "legal_reference": (
                "D.Lgs. 14/2019, artt. 3 e 25-nonies: debiti tributari scaduti "
                "tra gli squilibri da monitorare; soglia operativa, non il "
                "valore normativo vigente."),
            "source_authority": "Normattiva — Codice della crisi d'impresa",
            "source_url": NORMATTIVA_CCII,
            "params": {"min_amount": {"value": "100.00", "kind": "operational"}},
            "data_requirements": ["open_items(fiscal)", "fiscal_deadlines(validated)"],
            "formula": ("obbligazioni fiscali validate scadute con residuo > 0 "
                        "e importo >= soglia → segnale"),
        },
        {
            "code": "EW-DSCR-12M", "version": 1, "category": "organizational",
            "title": "Sostenibilità prospettica del debito sotto osservazione",
            "description": (
                "Il DSCR prospettico calcolato sulle obbligazioni datate è "
                "sotto la soglia operativa di attenzione."),
            "legal_reference": (
                "D.Lgs. 14/2019 art. 3 e art. 13 co. 2 (indicatori tra cui il "
                "DSCR): la soglia è parametro operativo — la determinazione di "
                "stato di crisi spetta agli organi competenti."),
            "source_authority": "Normattiva — Codice della crisi d'impresa",
            "source_url": NORMATTIVA_CCII,
            "params": {"dscr_min": {"value": "1.0", "kind": "operational"}},
            "data_requirements": ["debt_service_lines", "open_items"],
            "formula": "DSCR(orizzonte coperto) < soglia → segnale",
        },
        {
            "code": "EW-CONTINUITY-12M", "version": 1, "category": "organizational",
            "title": "Continuità 12 mesi: cassa proiettata negativa",
            "description": (
                "La proiezione sulle obbligazioni datate porta la cassa sotto "
                "zero entro 12 mesi: tensione sulla continuità aziendale da "
                "verificare."),
            "legal_reference": (
                "D.Lgs. 14/2019 art. 3: continuità prospettica almeno 12 mesi "
                "tra gli obiettivi degli assetti adeguati."),
            "source_authority": "Normattiva — Codice della crisi d'impresa",
            "source_url": NORMATTIVA_CCII,
            "params": {},
            "data_requirements": ["bank_accounts(balance)", "open_items",
                                  "debt_service_lines"],
            "formula": "saldo proiettato < 0 entro 365 giorni → segnale",
        },
    ]


def _param(rule: dict, name: str, default) -> Decimal:
    entry = (rule.get("params") or {}).get(name)
    return Decimal(str(entry["value"])) if entry else Decimal(str(default))


def evaluate(rule: dict, facts: EwFacts) -> dict:
    """One rule → one evaluation. Pure, deterministic, explainable.

    Returns {state, signal?}: state ∈ fired | not_fired | insufficient_data |
    unsupported; a `fired` evaluation carries title/message/evidence.
    """
    code = rule["code"]
    base = {"rule_code": code, "rule_version": rule["version"],
            "formula_version": rule["formula_version"],
            "category": rule["category"]}

    if code == "EW-FIN-OVERDUE":
        if not facts.payroll_items_configured and facts.overdue_financial_count == 0 \
                and facts.overdue_financial_amount is None:
            return {**base, "state": "unsupported",
                    "reason": "Nessuna rata di debito né partita finanziaria registrata."}
        min_days = int(_param(rule, "min_days_overdue", 1))
        if facts.overdue_financial_amount is not None and facts.overdue_financial_count > 0:
            return {**base, "state": "fired",
                    "severity": "critical", "title": rule["title"],
                    "message": (f"{facts.overdue_financial_count} esposizioni finanziarie "
                                f"scadute per {money(facts.overdue_financial_amount)} EUR."),
                    "evidence": {"overdue_amount": money(facts.overdue_financial_amount),
                                 "count": facts.overdue_financial_count,
                                 "min_days_overdue": min_days,
                                 **facts.source_ids.get(code, {})}}
        return {**base, "state": "not_fired"}

    if code == "EW-PAYROLL-OVERDUE":
        if not facts.payroll_items_configured:
            return {**base, "state": "unsupported",
                    "reason": ("Nessuna partita categorizzata 'personale/payroll': "
                               "il dato non esiste in questo workspace.")}
        if facts.overdue_payroll_amount is None:
            return {**base, "state": "insufficient_data",
                    "reason": "Categorie payroll presenti ma nessuna partita aperta osservata."}
        min_days = int(_param(rule, "min_days_overdue", 30))
        if facts.overdue_payroll_max_days >= min_days and facts.overdue_payroll_count > 0:
            return {**base, "state": "fired", "severity": "critical",
                    "title": rule["title"],
                    "message": (f"{facts.overdue_payroll_count} debiti verso personale/"
                                f"previdenziali scaduti da almeno {min_days} giorni "
                                f"({money(facts.overdue_payroll_amount)} EUR)."),
                    "evidence": {"overdue_amount": money(facts.overdue_payroll_amount),
                                 "count": facts.overdue_payroll_count,
                                 "max_days_overdue": facts.overdue_payroll_max_days,
                                 **facts.source_ids.get(code, {})}}
        return {**base, "state": "not_fired"}

    if code == "EW-SUPPLIER-OVERDUE":
        if facts.supplier_payable_total is None:
            return {**base, "state": "insufficient_data",
                    "reason": "Nessun debito commerciale aperto registrato."}
        if facts.supplier_payable_total <= 0 or facts.overdue_supplier_amount is None:
            return {**base, "state": "not_fired"}
        min_days = int(_param(rule, "min_days_overdue", 30))
        min_share = _param(rule, "min_share_percent", 30)
        share = facts.overdue_supplier_amount / facts.supplier_payable_total * Decimal("100")
        if facts.overdue_supplier_max_days >= min_days and share >= min_share:
            return {**base, "state": "fired", "severity": "warning",
                    "title": rule["title"],
                    "message": (f"{money(share)}% dei debiti commerciali è scaduto da "
                                f"oltre {min_days} giorni ({money(facts.overdue_supplier_amount)} EUR)."),
                    "evidence": {"overdue_amount": money(facts.overdue_supplier_amount),
                                 "share_percent": money(share),
                                 "total_open": money(facts.supplier_payable_total),
                                 "max_days_overdue": facts.overdue_supplier_max_days,
                                 "thresholds": {"min_days_overdue": min_days,
                                                "min_share_percent": money(min_share)},
                                 **facts.source_ids.get(code, {})}}
        return {**base, "state": "not_fired"}

    if code == "EW-PUBLIC-CREDITOR":
        if facts.overdue_public_amount is None:
            return {**base, "state": "insufficient_data",
                    "reason": "Nessuna obbligazione fiscale registrata."}
        min_amount = _param(rule, "min_amount", 100)
        if facts.overdue_public_count > 0 and facts.overdue_public_amount >= min_amount:
            return {**base, "state": "fired", "severity": "critical",
                    "title": rule["title"],
                    "message": (f"{facts.overdue_public_count} obbligazioni fiscali "
                                f"validate scadute per {money(facts.overdue_public_amount)} EUR."),
                    "evidence": {"overdue_amount": money(facts.overdue_public_amount),
                                 "count": facts.overdue_public_count,
                                 "min_amount": money(min_amount),
                                 **facts.source_ids.get(code, {})}}
        return {**base, "state": "not_fired"}

    if code == "EW-DSCR-12M":
        if facts.dscr_status in ("insufficient_data", "not_applicable"):
            state = ("insufficient_data" if facts.dscr_status == "insufficient_data"
                     else "unsupported")
            return {**base, "state": state,
                    "reason": ("DSCR non calcolabile sui dati disponibili."
                               if facts.dscr_status == "insufficient_data"
                               else "Nessun debito finanziario pianificato: regola non applicabile.")}
        threshold = _param(rule, "dscr_min", "1.0")
        if facts.dscr_value is not None and facts.dscr_value < threshold:
            return {**base, "state": "fired", "severity": "warning",
                    "title": rule["title"],
                    "message": (f"DSCR prospettico {facts.dscr_value} sotto la soglia "
                                f"operativa {threshold}: il servizio del debito supera "
                                "i flussi attesi registrati."),
                    "evidence": {"dscr": str(facts.dscr_value), "threshold": str(threshold),
                                 "dscr_status": facts.dscr_status,
                                 **facts.source_ids.get(code, {})}}
        return {**base, "state": "not_fired"}

    if code == "EW-CONTINUITY-12M":
        if facts.opening_balance_status != "available":
            return {**base, "state": "insufficient_data",
                    "reason": "Saldo iniziale non noto: la continuità prospettica non è calcolabile."}
        if facts.first_negative_date is not None:
            return {**base, "state": "fired", "severity": "critical",
                    "title": rule["title"],
                    "message": (f"Saldo proiettato negativo il {facts.first_negative_date} "
                                f"(tra {facts.days_to_negative} giorni) sulle obbligazioni "
                                "datate registrate."),
                    "evidence": {"first_negative_date": facts.first_negative_date,
                                 "days_to_negative": facts.days_to_negative,
                                 **facts.source_ids.get(code, {})}}
        return {**base, "state": "not_fired"}

    return {**base, "state": "unsupported", "reason": "Regola sconosciuta al motore."}
