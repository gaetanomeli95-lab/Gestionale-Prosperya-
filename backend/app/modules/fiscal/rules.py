"""Versioned fiscal rules: seeded content, resolution and pure calculations.

Everything in this file is either
(a) **verified rule data** carrying its authoritative source, or
(b) **pure arithmetic/calendar code** that consumes that data.

No fiscal constant is hardcoded elsewhere in the application. A calculation
always names the rule set it used (`rule_set_id` + `version`), so any number
can be reproduced later — including after a law change, because a new version
supersedes the old one instead of editing it.

Sources verified on 2026-09-14 (see `SEEDED_RULE_SETS` for the per-rule
provenance and `docs/FISCAL_ARCHITECTURE.md` for the discussion):

* Agenzia delle Entrate — "Versamento Iva periodica (mensile o trimestrale) —
  Che cos'è" (last updated 30/07/2026): settlement formula, €100 threshold,
  carry-forward behaviour, November/January exceptions.
* Agenzia delle Entrate — "F24 IVA Periodica — Come e quando si versa":
  monthly and quarterly due dates, 1% quarterly interest, option thresholds.
* D.L. 13/05/2011 n. 70, art. 7, comma 1, lett. h): payments falling on a
  Saturday or a holiday move to the first following working day.
* D.L. 04/07/2006 n. 223, art. 37, comma 11-bis (quoted verbatim in AdE
  Circolare n. 9 del 02/05/2024): payments due between 1 and 20 August may be
  made by 20 August with no surcharge.
* Legge 27/05/1949 n. 260 + Presidenza del Consiglio (Dipartimento per il
  Cerimoniale dello Stato): current national holidays.
* Agenzia delle Entrate — "Ricerca guidata codici tributo": F24 VAT tax codes.
* Agenzia delle Entrate — "Avvertenze per la compilazione del Mod. F24":
  amounts always carry two decimals, third decimal rounded half-up.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

ENGINE_VERSION = "fiscal-engine-v1.0"
VAT_FORMULA_VERSION = "vat-settlement-v1.0"
DUE_DATE_FORMULA_VERSION = "payment-calendar-v1.0"
JURISDICTION = "IT"

#: Earliest period the seeded rule sets are declared valid for. Periods before
#: this date have **no applicable rule set** and the engine refuses to compute
#: them rather than applying today's rules to the past.
SUPPORTED_FROM = date(2026, 1, 1)

RETRIEVED_AT = date(2026, 9, 14)

# ---------------------------------------------------------------------------
# Seeded rule sets — verified content + provenance
# ---------------------------------------------------------------------------

SEEDED_RULE_SETS: list[dict] = [
    {
        "code": "IT-IVA-PERIODICA",
        "rule_family": "vat_periodic",
        "version": "2026.1",
        "effective_from": SUPPORTED_FROM,
        "effective_to": None,
        "source_authority": "Agenzia delle Entrate",
        "source_title": "F24 IVA Periodica — Versamento Iva periodica (mensile o trimestrale): "
                        "che cos'è / come e quando si versa",
        "source_url": "https://www.agenziaentrate.gov.it/portale/schede/pagamenti/f24ivap10/"
                      "cosa-versivaperiodica",
        "source_published_at": date(2026, 7, 30),   # "Ultimo aggiornamento" della pagina
        "legal_reference": "D.P.R. 633/1972 e D.P.R. 100/1998 (liquidazioni periodiche); "
                           "art. 7 D.P.R. 542/1999 (opzione trimestrale)",
        "notes": "Regole verificate sulle pagine ufficiali AdE aggiornate al 30/07/2026. "
                 "L'efficacia anteriore al 2026 non è stata verificata: i periodi "
                 "precedenti restano fuori perimetro e il motore rifiuta di calcolarli.",
        "payload": {
            "formula": {
                "id": VAT_FORMULA_VERSION,
                "steps": [
                    "IVA esigibile nel periodo sulle operazioni attive (IVA a debito)",
                    "meno IVA sugli acquisti del periodo per cui è esercitata la detrazione "
                    "(IVA a credito)",
                    "meno eventuale credito d'imposta del periodo precedente",
                    "più eventuale debito d'imposta del periodo precedente di importo "
                    "inferiore alla soglia minima di versamento",
                ],
                "quote": "Iva esigibile nel mese (o trimestre) ... meno Iva risultante dalle "
                         "annotazioni eseguite nei registri relativi ai beni e ai servizi "
                         "acquistati ... sottrarre l'eventuale credito d'imposta del periodo "
                         "precedente; sommare l'eventuale debito d'imposta del periodo "
                         "precedente di importo inferiore a 100 euro",
            },
            "minimum_payment_amount": "100.00",
            "minimum_payment_rule": "A debito si versa se l'importo è pari o superiore a 100 euro; "
                                    "altrimenti si riporta in aumento al periodo successivo.",
            "credit_rule": "L'importo a credito si computa in detrazione nel periodo successivo.",
            "deferred_small_amount_rule": "Il versamento dell'importo che non supera 100 euro va "
                                          "effettuato entro il 16 novembre dello stesso anno e "
                                          "quello relativo al mese di dicembre entro il 16 gennaio "
                                          "dell'anno successivo.",
            "monthly": {
                "due_day": 16,
                "due_month_offset": 1,
                "rule": "Contribuenti mensili: liquidazione e versamento entro il giorno 16 del "
                        "mese successivo.",
            },
            "quarterly": {
                "due_day": 16,
                "due_month_offset": 2,
                "fourth_quarter": {
                    "supported": False,
                    "reason": "Il quarto trimestre si versa in sede di conguaglio annuale "
                              "(entro il 16 marzo dell'anno successivo, con possibilità dei "
                              "maggiori termini legati alla dichiarazione dei redditi): "
                              "dipende dalla dichiarazione annuale, fuori perimetro v1.",
                },
                "interest_rate_percent": "1.00",
                "interest_rule": "In caso di versamento trimestrale l'eventuale debito d'imposta "
                                 "deve essere maggiorato dell'1% a titolo di interesse.",
                "option_thresholds": {
                    "services_or_professionals": "500000.00",
                    "other_activities": "800000.00",
                    "rule": "L'opzione trimestrale richiede un volume d'affari dell'anno solare "
                            "precedente non superiore a 500.000 euro (servizi/professionisti) "
                            "o 800.000 euro (altre attività).",
                },
                "special_regimes_supported": False,
                "special_regimes_note": "Trimestrali 'speciali' (distributori di carburanti, "
                                        "autotrasportatori, servizi al pubblico, arti e "
                                        "professioni sanitarie): scadenze e interessi diversi, "
                                        "non implementati.",
            },
            "supported_cases": [
                "Liquidazione mensile di soggetto passivo ordinario",
                "Liquidazione trimestrale per opzione (primi tre trimestri), con interesse 1%",
            ],
            "unsupported_cases": [
                "Quarto trimestre dei soggetti trimestrali (conguaglio annuale)",
                "Trimestrali speciali ex art. 74 D.P.R. 633/1972",
                "Acconto IVA di dicembre",
                "Liquidazione IVA di gruppo, split payment, reverse charge, plafond esportatori, "
                "regimi speciali (agricoltura, editoria, agenzie di viaggio), ventilazione",
                "Rimborsi e compensazioni orizzontali",
            ],
        },
    },
    {
        "code": "IT-CALENDARIO-VERSAMENTI",
        "rule_family": "payment_calendar",
        "version": "2026.1",
        "effective_from": SUPPORTED_FROM,
        "effective_to": None,
        "source_authority": "Normattiva / Agenzia delle Entrate",
        "source_title": "D.L. 70/2011 art. 7 c.1 lett. h) (differimento sabato/festivi) e "
                        "D.L. 223/2006 art. 37 c.11-bis (differimento 1–20 agosto), "
                        "quest'ultimo richiamato in AdE Circolare n. 9 del 02/05/2024",
        "source_url": "https://www.agenziaentrate.gov.it/portale/documents/20143/370225/"
                      "articolo+7+del+Dl+70+2011+semplificazione+fiscale_articolo_7_dl_70_2011.pdf/"
                      "5aa7cd68-4970-937e-0acb-4db865ca1bdd",
        "source_published_at": date(2024, 5, 2),
        "legal_reference": "D.L. 13/05/2011 n. 70 art. 7 c.1 lett. h); "
                           "D.L. 04/07/2006 n. 223 art. 37 c.11-bis; "
                           "L. 27/05/1949 n. 260 (giorni festivi)",
        "notes": "Il calendario copre le sole festività nazionali. Le festività del santo "
                 "patrono sono locali e non sono modellate: se una scadenza cade su una "
                 "festività locale il differimento reale non è calcolabile e la scadenza "
                 "viene marcata 'review_required'.",
        "payload": {
            "weekend_holiday_deferral": {
                "enabled": True,
                "quote": "i versamenti e gli adempimenti, anche se solo telematici, previsti da "
                         "norme riguardanti l'Amministrazione economico-finanziaria che scadono "
                         "il sabato o in un giorno festivo sono sempre rinviati al primo giorno "
                         "lavorativo successivo",
                "non_working_weekdays": [5, 6],  # sabato, domenica (Python weekday())
            },
            "august_deferral": {
                "enabled": True,
                "window_start": "08-01",
                "window_end": "08-20",
                "deferred_to": "08-20",
                "quote": "il versamento delle somme ... che hanno scadenza dal 1º al 20 agosto di "
                         "ogni anno, possono essere effettuati entro il giorno 20 dello stesso "
                         "mese, senza alcuna maggiorazione",
            },
            "national_holidays": {
                "fixed": ["01-01", "01-06", "04-25", "05-01", "06-02", "08-15",
                          "11-01", "12-08", "12-25", "12-26"],
                "movable": ["easter_monday"],
                "source": "L. 260/1949 e elenco vigente pubblicato dalla Presidenza del "
                          "Consiglio dei Ministri — Dipartimento per il Cerimoniale dello Stato",
                "source_url": "https://presidenza.governo.it/ufficio_cerimoniale/cerimoniale/"
                              "giornate.html",
                "local_patron_saint_modelled": False,
            },
        },
    },
    {
        "code": "IT-F24-FORMATO",
        "rule_family": "f24_format",
        "version": "2026.1",
        "effective_from": SUPPORTED_FROM,
        "effective_to": None,
        "source_authority": "Agenzia delle Entrate",
        "source_title": "Avvertenze per la compilazione del Mod. F24 — rappresentazione degli importi",
        "source_url": "https://www.agenziaentrate.gov.it/portale/documents/20143/334200/"
                      "Istruzioni+per+la+compilazione++F24+Ordinario_Mod_F24+avvertenze.pdf/"
                      "64bf30a0-44d7-88a9-578f-6963e9406657",
        "source_published_at": None,
        "legal_reference": "Istruzioni ufficiali modello F24",
        "notes": "Regola di rappresentazione, non di calcolo: gli importi restano Decimal a due "
                 "decimali in tutto il motore.",
        "payload": {
            "amount_decimals": 2,
            "rounding": "half_up_on_third_decimal",
            "quote": "Gli importi devono sempre essere indicati con le prime due cifre decimali "
                     "anche nel caso che tali cifre siano pari a zero. In presenza di più cifre "
                     "decimali occorre procedere all'arrotondamento della seconda cifra decimale: "
                     "se la terza cifra è uguale o superiore a 5 per eccesso, se inferiore a 5 "
                     "per difetto.",
            "transmission_supported": False,
            "transmission_note": "Nessun formato telematico F24 è implementato: l'invio richiede "
                                 "canale Entratel/CBI autorizzato e specifica tecnica ufficiale "
                                 "verificata.",
        },
    },
]

#: F24 tax codes actually needed by the supported flows. Every entry was read
#: from the Agenzia delle Entrate "Ricerca guidata codici tributo" service.
TAX_CODE_SOURCE = {
    "authority": "Agenzia delle Entrate",
    "title": "Ricerca guidata codici tributo — sezione Erario (IVA)",
    "url": "https://www1.agenziaentrate.gov.it/servizi/codici/ricerca/elencoTributi.php?Q3=IVA",
}
MONTH_NAMES_IT = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                  "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

SEEDED_TAX_CODES: list[dict] = [
    *[
        {
            "code": f"60{month:02d}",
            "description": f"Versamento IVA mensile {MONTH_NAMES_IT[month]}",
            "section": "erario",
            "usage": "vat_monthly",
            "reference_number": month,
            "requires_reference_period": False,
            "notes": "Il mese di riferimento è implicito nel codice tributo; il campo "
                     "'rateazione/regione/prov./mese rif.' non va compilato.",
        }
        for month in range(1, 13)
    ],
    {
        "code": "6031", "description": "Versamento IVA trimestrale 1 trimestre",
        "section": "erario", "usage": "vat_quarterly", "reference_number": 1,
        "requires_reference_period": False,
        "notes": "Esempio ufficiale di compilazione: 'rateazione/regione/prov./mese rif.' "
                 "non va compilato; 'anno di riferimento' è l'anno d'imposta.",
    },
    {
        "code": "6032", "description": "Versamento IVA trimestrale 2 trimestre",
        "section": "erario", "usage": "vat_quarterly", "reference_number": 2,
        "requires_reference_period": False, "notes": None,
    },
    {
        "code": "6033", "description": "Versamento IVA trimestrale 3 trimestre",
        "section": "erario", "usage": "vat_quarterly", "reference_number": 3,
        "requires_reference_period": False,
        "notes": "L'IVA dovuta per il trimestre è maggiorata dell'1% a titolo di interessi e "
                 "versata con questo stesso codice tributo.",
    },
    {
        "code": "6034", "description": "Versamento IVA quarto trimestre",
        "section": "erario", "usage": "vat_quarterly_fourth", "reference_number": 4,
        "requires_reference_period": False,
        "notes": "Registrato per completezza: il quarto trimestre dipende dal conguaglio "
                 "annuale e NON è calcolato da questa versione del motore.",
    },
    {
        "code": "6013", "description": "Acconto per IVA mensile",
        "section": "erario", "usage": "vat_advance", "reference_number": None,
        "requires_reference_period": False,
        "notes": "Registrato per completezza: l'acconto IVA di dicembre non è calcolato.",
    },
    {
        "code": "6099", "description": "Versamento IVA sulla base della dichiarazione annuale",
        "section": "erario", "usage": "vat_annual", "reference_number": None,
        "requires_reference_period": False,
        "notes": "Registrato per completezza: la dichiarazione annuale non è implementata.",
    },
]


# ---------------------------------------------------------------------------
# Calendar rules (pure)
# ---------------------------------------------------------------------------

def easter_sunday(year: int) -> date:
    """Gregorian Easter (Anonymous/Meeus algorithm).

    Pure arithmetic, not a fiscal rule: it only locates Easter Monday, which
    L. 260/1949 lists among the holidays.
    """
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lunar = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lunar) // 451
    month = (h + lunar - 7 * m + 114) // 31
    day = ((h + lunar - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def national_holidays(year: int, payload: dict) -> set[date]:
    """National holidays for a year, from the rule payload."""
    holidays: set[date] = set()
    block = payload.get("national_holidays", {})
    for entry in block.get("fixed", []):
        month, day = (int(part) for part in entry.split("-"))
        holidays.add(date(year, month, day))
    if "easter_monday" in block.get("movable", []):
        holidays.add(easter_sunday(year) + timedelta(days=1))
    return holidays


@dataclass(frozen=True)
class DueDateResult:
    """A resolved (or deliberately unresolved) payment due date."""

    statutory_date: date
    due_date: date | None
    status: str                 # "resolved" | "review_required"
    reason: str | None
    applied_rules: tuple[str, ...]
    formula_version: str = DUE_DATE_FORMULA_VERSION


def resolve_due_date(statutory: date, calendar_payload: dict) -> DueDateResult:
    """Apply the verified deferral rules to a statutory due date.

    Order matters and follows the sources: the August window (art. 37 c.11-bis
    D.L. 223/2006) moves the date to 20 August first, then the Saturday/holiday
    rule (art. 7 c.1 lett. h) D.L. 70/2011) moves it to the next working day.
    """
    applied: list[str] = []
    current = statutory

    august = calendar_payload.get("august_deferral", {})
    if august.get("enabled"):
        start_month, start_day = (int(p) for p in august["window_start"].split("-"))
        end_month, end_day = (int(p) for p in august["window_end"].split("-"))
        target_month, target_day = (int(p) for p in august["deferred_to"].split("-"))
        window_start = date(current.year, start_month, start_day)
        window_end = date(current.year, end_month, end_day)
        if window_start <= current <= window_end:
            current = date(current.year, target_month, target_day)
            applied.append("august_deferral:D.L. 223/2006 art. 37 c.11-bis")

    weekend = calendar_payload.get("weekend_holiday_deferral", {})
    if weekend.get("enabled"):
        non_working = set(weekend.get("non_working_weekdays", [5, 6]))
        holidays = national_holidays(current.year, calendar_payload)
        guard = 0
        while current.weekday() in non_working or current in holidays:
            current += timedelta(days=1)
            guard += 1
            if current.year != statutory.year:
                holidays = national_holidays(current.year, calendar_payload)
            if guard > 10:
                return DueDateResult(
                    statutory_date=statutory, due_date=None, status="review_required",
                    reason="Differimento non risolvibile con le regole note: verificare "
                           "manualmente il primo giorno lavorativo utile.",
                    applied_rules=tuple(applied),
                )
        if guard:
            applied.append("weekend_holiday_deferral:D.L. 70/2011 art. 7 c.1 lett. h)")

    reason = None
    if not calendar_payload.get("national_holidays", {}).get("local_patron_saint_modelled", False):
        reason = ("Il calendario copre le festività nazionali; le festività locali del santo "
                  "patrono non sono modellate.")
    return DueDateResult(statutory_date=statutory, due_date=current, status="resolved",
                         reason=reason, applied_rules=tuple(applied))


def period_bounds(year: int, period_no: int, frequency: str) -> tuple[date, date]:
    """Calendar bounds of a VAT period."""
    if frequency == "monthly":
        if not 1 <= period_no <= 12:
            raise ValueError("Periodo mensile fuori intervallo 1..12.")
        last = calendar.monthrange(year, period_no)[1]
        return date(year, period_no, 1), date(year, period_no, last)
    if frequency == "quarterly":
        if not 1 <= period_no <= 4:
            raise ValueError("Trimestre fuori intervallo 1..4.")
        first_month = (period_no - 1) * 3 + 1
        last_month = first_month + 2
        last = calendar.monthrange(year, last_month)[1]
        return date(year, first_month, 1), date(year, last_month, last)
    raise ValueError("Frequenza non supportata: monthly | quarterly.")


def period_label(year: int, period_no: int, frequency: str) -> str:
    if frequency == "monthly":
        return f"{MONTH_NAMES_IT[period_no]} {year}"
    return f"{period_no}° trimestre {year}"


def statutory_due_date(year: int, period_no: int, frequency: str, vat_payload: dict) -> date:
    """Statutory (pre-deferral) due date of the periodic VAT payment."""
    block = vat_payload["monthly"] if frequency == "monthly" else vat_payload["quarterly"]
    _, end = period_bounds(year, period_no, frequency)
    month = end.month + int(block["due_month_offset"])
    target_year = year + (month - 1) // 12
    target_month = (month - 1) % 12 + 1
    return date(target_year, target_month, int(block["due_day"]))


# ---------------------------------------------------------------------------
# Settlement arithmetic (pure)
# ---------------------------------------------------------------------------

CENT = Decimal("0.01")


def quantize_f24(amount: Decimal, format_payload: dict) -> Decimal:
    """Round to the F24 representation (two decimals, half-up on the third)."""
    decimals = int(format_payload.get("amount_decimals", 2))
    return amount.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SettlementInput:
    """Everything the settlement formula needs, already filtered."""

    debit_total: Decimal
    credit_total: Decimal
    prior_credit: Decimal
    prior_small_debit: Decimal
    frequency: str
    is_fourth_quarter: bool


@dataclass(frozen=True)
class SettlementMath:
    net_position: Decimal
    interest_amount: Decimal
    payable_amount: Decimal | None
    carry_forward_credit: Decimal | None
    carry_forward_debit: Decimal | None
    outcome: str                    # payable | carried_forward_debit | credit | zero
    applied_rules: tuple[str, ...]


def compute_settlement(data: SettlementInput, vat_payload: dict) -> SettlementMath:
    """Apply the verified periodic VAT formula.

    Steps, in the order stated by the Agenzia delle Entrate page:
    VAT debit − VAT credit − prior period credit + prior period small debit.
    Then: a debit at or above the minimum is payable; below it is carried
    forward; a credit is deducted in the next period. For quarterly taxpayers
    the payable debit carries the 1% interest.
    """
    applied = [VAT_FORMULA_VERSION]
    minimum = Decimal(vat_payload["minimum_payment_amount"])
    net = (data.debit_total - data.credit_total - data.prior_credit
           + data.prior_small_debit).quantize(CENT)

    interest = Decimal("0.00")
    payable: Decimal | None = None
    carry_credit: Decimal | None = None
    carry_debit: Decimal | None = None

    if net > 0:
        if net >= minimum:
            if data.frequency == "quarterly":
                rate = Decimal(vat_payload["quarterly"]["interest_rate_percent"])
                interest = (net * rate / Decimal(100)).quantize(CENT)
                applied.append("quarterly_interest:1% (AdE — F24 IVA periodica)")
            payable = (net + interest).quantize(CENT)
            outcome = "payable"
            applied.append(f"minimum_payment:>= {minimum}")
        else:
            carry_debit = net
            outcome = "carried_forward_debit"
            applied.append(f"minimum_payment:< {minimum} → riporto in aumento")
    elif net < 0:
        carry_credit = -net
        outcome = "credit"
        applied.append("credit_rule:detrazione nel periodo successivo")
    else:
        outcome = "zero"

    return SettlementMath(
        net_position=net, interest_amount=interest, payable_amount=payable,
        carry_forward_credit=carry_credit, carry_forward_debit=carry_debit,
        outcome=outcome, applied_rules=tuple(applied),
    )


def tax_code_for(frequency: str, period_no: int, codes: list) -> object | None:
    """Pick the F24 tax code for a period from the registry rows."""
    usage = "vat_monthly" if frequency == "monthly" else "vat_quarterly"
    for row in codes:
        if row.usage == usage and row.reference_number == period_no:
            return row
    return None


def is_supported_period(frequency: str, period_no: int, vat_payload: dict) -> tuple[bool, str | None]:
    """Whether the engine may compute this period at all."""
    if frequency == "monthly":
        return True, None
    if period_no == 4:
        block = vat_payload["quarterly"]["fourth_quarter"]
        if not block.get("supported", False):
            return False, block["reason"]
    return True, None
