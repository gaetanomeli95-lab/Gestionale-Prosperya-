"""Deterministic eligibility rule engine.

Every requirement carries a `rule_code` resolved against RULE_REGISTRY.
Each evaluator receives the company facts + declared funding profile and
returns a RuleOutcome: result + evidence. Unknown codes → UNSUPPORTED.
Missing facts → INSUFFICIENT_DATA. Never a guess, never a boolean.

Engine version is stamped on every assessment for reproducibility.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.shared.mixins import today

ENGINE_VERSION = "funding-engine-v1.0"


@dataclass(frozen=True)
class CompanyFacts:
    """Canonical facts the rules read — Company + declared funding profile.

    `None` means "not known": evaluators must return INSUFFICIENT_DATA,
    never assume a value.
    """

    legal_form: str | None = None
    ateco_code: str | None = None
    region: str | None = None
    province: str | None = None
    size_band: str | None = None
    employee_count: int | None = None
    revenue_eur: Decimal | None = None
    incorporated_on: date | None = None
    is_startup: bool | None = None
    is_innovative_startup: bool | None = None
    female_ownership_pct: Decimal | None = None
    youth_ownership_pct: Decimal | None = None
    project_region: str | None = None
    project_location: str | None = None
    single_undertaking_known: bool | None = None
    aid_history_complete: bool | None = None
    aid_total_eur: Decimal | None = None       # de minimis window total
    aid_window_months: int | None = None
    aid_threshold_eur: Decimal | None = None   # regime threshold in force


@dataclass(frozen=True)
class RuleOutcome:
    result: str                       # RuleResult value
    evidence: dict = field(default_factory=dict)


def _need(value: Any, fact_name: str) -> RuleOutcome | None:
    """Return an INSUFFICIENT_DATA outcome when `value` is unknown."""
    if value is None:
        return RuleOutcome(
            "insufficient_data",
            {"missing": fact_name,
             "reason": f"Dato aziendale non disponibile: {fact_name}."})
    return None


def _norm(value: str | None) -> str | None:
    return value.strip().lower() if isinstance(value, str) else None


# --- evaluators --------------------------------------------------------------

def _legal_form_in(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.legal_form, "legal_form"):
        return miss
    allowed = {_norm(v) for v in p.get("values", [])}
    ok = _norm(f.legal_form) in allowed
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"company.legal_form": f.legal_form,
         "rule": f"legal_form IN {sorted(allowed)}"})


def _ateco_in(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.ateco_code, "ateco_code"):
        return miss
    prefixes = [str(v) for v in p.get("values", [])]
    ok = any(f.ateco_code.startswith(px) for px in prefixes)
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"company.ateco_code": f.ateco_code,
         "rule": f"ateco startswith {prefixes}"})


def _ateco_not_in(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.ateco_code, "ateco_code"):
        return miss
    prefixes = [str(v) for v in p.get("values", [])]
    ok = not any(f.ateco_code.startswith(px) for px in prefixes)
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"company.ateco_code": f.ateco_code,
         "rule": f"ateco NOT startswith {prefixes}"})


def _region_in(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.region, "region"):
        return miss
    allowed = {_norm(v) for v in p.get("values", [])}
    ok = _norm(f.region) in allowed
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"company.region": f.region,
         "rule": f"registered_office_region IN {sorted(allowed)}"})


def _project_location_in(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.project_region, "project_region"):
        return miss
    allowed = {_norm(v) for v in p.get("values", [])}
    ok = _norm(f.project_region) in allowed
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"profile.project_region": f.project_region,
         "rule": f"project_region IN {sorted(allowed)}"})


def _company_age(f: CompanyFacts, p: dict, *, maximum: bool) -> RuleOutcome:
    if miss := _need(f.incorporated_on, "incorporated_on"):
        return miss
    key = "max_years" if maximum else "min_years"
    years = p.get(key)
    if years is None:
        return RuleOutcome("unsupported", {"reason": f"parametro {key} assente"})
    age_days = (today() - f.incorporated_on).days
    age_years = Decimal(age_days) / Decimal("365.25")
    limit = Decimal(str(years))
    ok = age_years <= limit if maximum else age_years >= limit
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"profile.incorporated_on": f.incorporated_on.isoformat(),
         "age_years": str(age_years.quantize(Decimal("0.01"))),
         "rule": f"age {'<=' if maximum else '>='} {years} years"})


def _employees_max(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.employee_count, "employee_count"):
        return miss
    limit = p.get("max")
    if limit is None:
        return RuleOutcome("unsupported", {"reason": "parametro max assente"})
    ok = f.employee_count <= int(limit)
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"company.employee_count": f.employee_count,
         "rule": f"employees <= {limit}"})


def _turnover_max(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.revenue_eur, "revenue_eur"):
        return miss
    limit = p.get("max")
    if limit is None:
        return RuleOutcome("unsupported", {"reason": "parametro max assente"})
    ok = f.revenue_eur <= Decimal(str(limit))
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"company.revenue_eur": str(f.revenue_eur),
         "rule": f"turnover <= {limit} EUR"})


def _sme_required(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.size_band, "size_band"):
        return miss
    if f.size_band == "unknown":
        return RuleOutcome(
            "insufficient_data",
            {"missing": "size_band",
             "reason": "Dimensione azienda non classificata."})
    ok = f.size_band in ("micro", "small", "medium")
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"company.size_band": f.size_band,
         "rule": "size_band IN (micro, small, medium)"})


def _startup_required(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.is_startup, "is_startup"):
        return miss
    ok = f.is_startup is True
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"profile.is_startup": f.is_startup, "rule": "is_startup = true"})


def _female_ownership_min(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.female_ownership_pct, "female_ownership_pct"):
        return miss
    minimum = Decimal(str(p.get("min_pct", "50")))
    ok = f.female_ownership_pct >= minimum
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"profile.female_ownership_pct": str(f.female_ownership_pct),
         "rule": f"female_ownership >= {minimum}%"})


def _youth_ownership_min(f: CompanyFacts, p: dict) -> RuleOutcome:
    if miss := _need(f.youth_ownership_pct, "youth_ownership_pct"):
        return miss
    minimum = Decimal(str(p.get("min_pct", "50")))
    ok = f.youth_ownership_pct >= minimum
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"profile.youth_ownership_pct": str(f.youth_ownership_pct),
         "rule": f"youth_ownership >= {minimum}%"})


def _date_condition(f: CompanyFacts, p: dict) -> RuleOutcome:
    """Generic date guard on the assessment date (e.g. 'not before X')."""
    ref = p.get("on_or_after") or p.get("on_or_before")
    if ref is None:
        return RuleOutcome("unsupported",
                           {"reason": "parametro data assente"})
    ref_date = date.fromisoformat(str(ref))
    now = today()
    if p.get("on_or_after") is not None:
        ok = now >= ref_date
        rule = f"assessment_date >= {ref}"
    else:
        ok = now <= ref_date
        rule = f"assessment_date <= {ref}"
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"assessment_date": now.isoformat(), "rule": rule})


def _de_minimis_headroom(f: CompanyFacts, p: dict) -> RuleOutcome:
    """De minimis headroom vs the regime threshold in force.

    Requires: declared aid history completeness + known single-undertaking
    perimeter. Missing either → INSUFFICIENT_DATA / REVIEW_REQUIRED.
    """
    if f.single_undertaking_known is not True:
        return RuleOutcome(
            "review_required",
            {"missing": "single_undertaking_known",
             "reason": ("Perimetro di impresa unica non verificato: il "
                        "cumulo de minimis potrebbe includere entità collegate.")})
    if f.aid_history_complete is not True:
        return RuleOutcome(
            "insufficient_data",
            {"missing": "aid_history_complete",
             "reason": "Storico aiuti non dichiarato completo."})
    if f.aid_threshold_eur is None or f.aid_total_eur is None:
        return RuleOutcome(
            "insufficient_data",
            {"missing": "aid_regime",
             "reason": "Regime de minimis o totale aiuti non determinabile."})
    requested = Decimal(str(p.get("requested_amount", "0")))
    headroom = f.aid_threshold_eur - f.aid_total_eur
    ok = headroom >= requested
    return RuleOutcome(
        "satisfied" if ok else "not_satisfied",
        {"aid_total_eur": str(f.aid_total_eur),
         "threshold_eur": str(f.aid_threshold_eur),
         "requested_amount": str(requested),
         "headroom_eur": str(headroom),
         "rule": f"aid_total + requested <= threshold "
                 f"({f.aid_window_months}m window)"})


def _document_required(f: CompanyFacts, p: dict) -> RuleOutcome:
    """A document requirement is never auto-satisfied: it becomes a checklist
    item at practice level. At assessment time it is REVIEW_REQUIRED."""
    return RuleOutcome(
        "review_required",
        {"reason": "Requisito documentale: verificato nella checklist pratica.",
         "doc_type": p.get("doc_type")})


def _custom_review_required(f: CompanyFacts, p: dict) -> RuleOutcome:
    return RuleOutcome(
        "review_required",
        {"reason": p.get("reason",
                         "Regola non interamente decidibile a macchina: "
                         "richiesta valutazione professionale.")})


def _aid_regime_condition(f: CompanyFacts, p: dict) -> RuleOutcome:
    """Placeholder for regime-specific conditions beyond de minimis headroom —
    a human must confirm the regime applies to the case."""
    return RuleOutcome(
        "review_required",
        {"reason": "Condizione sul regime di aiuto: conferma professionale "
                   "richiesta.",
         "regime": p.get("regime")})


#: Bounded registry — extend here, never inline. Unknown code → UNSUPPORTED.
RULE_REGISTRY: dict[str, Callable[[CompanyFacts, dict], RuleOutcome]] = {
    "LEGAL_FORM_IN": _legal_form_in,
    "ATECO_IN": _ateco_in,
    "ATECO_NOT_IN": _ateco_not_in,
    "REGION_IN": _region_in,
    "PROJECT_LOCATION_IN": _project_location_in,
    "COMPANY_AGE_MAX": lambda f, p: _company_age(f, p, maximum=True),
    "COMPANY_AGE_MIN": lambda f, p: _company_age(f, p, maximum=False),
    "EMPLOYEES_MAX": _employees_max,
    "TURNOVER_MAX": _turnover_max,
    "SME_REQUIRED": _sme_required,
    "STARTUP_REQUIRED": _startup_required,
    "FEMALE_OWNERSHIP_MIN": _female_ownership_min,
    "YOUTH_OWNERSHIP_MIN": _youth_ownership_min,
    "DATE_CONDITION": _date_condition,
    "AID_REGIME_CONDITION": _aid_regime_condition,
    "DE_MINIMIS_HEADROOM": _de_minimis_headroom,
    "DOCUMENT_REQUIRED": _document_required,
    "CUSTOM_REVIEW_REQUIRED": _custom_review_required,
}


def evaluate(rule_code: str, params: dict, facts: CompanyFacts) -> RuleOutcome:
    """Evaluate one requirement. Unknown codes are UNSUPPORTED, not guessed."""
    evaluator = RULE_REGISTRY.get(rule_code)
    if evaluator is None:
        return RuleOutcome(
            "unsupported",
            {"rule_code": rule_code,
             "reason": "Regola non presente nel registry deterministico."})
    return evaluator(facts, params or {})


def overall_result(items: list[RuleOutcome], mandatory: list[bool]) -> str:
    """Aggregate per-requirement outcomes into the assessment result.

    Order of precedence (a failure is never masked by missing data):
      any mandatory NOT_SATISFIED → NOT_ELIGIBLE
      any UNSUPPORTED             → UNSUPPORTED
      any REVIEW_REQUIRED         → REVIEW_REQUIRED
      any INSUFFICIENT_DATA       → POTENTIALLY_ELIGIBLE if something is
                                    already SATISFIED else INSUFFICIENT_DATA
      all SATISFIED               → ELIGIBLE_ON_KNOWN_DATA
    """
    results = [o.result for o in items]
    if any(r == "not_satisfied" and m for r, m in zip(results, mandatory, strict=True)):
        return "not_eligible"
    if "unsupported" in results:
        return "unsupported"
    if "review_required" in results:
        return "review_required"
    if "insufficient_data" in results:
        return ("potentially_eligible" if "satisfied" in results
                else "insufficient_data")
    return "eligible_on_known_data"
