"""Deterministic treasury analytics: cash position, forecast, aging, warnings.

Pure functions over plain dataclasses — no database, no AI, no randomness.
Every number is reproducible from its inputs and labelled as **FACT**,
**CALCULATION** or **ASSUMPTION** (the AI layer may only read these results).

Non-negotiable rules encoded here:

* a missing balance makes the position `null`, never `0`;
* overdue items are **never** assumed collected: they are reported separately
  and excluded from projected inflows, with the assumption stated in writing;
* the forecast projects only real dated obligations (open items) plus an
  explicit opening balance — no trend extrapolation, no invented recurring
  costs;
* when an indicator cannot be computed the status is
  `not_calculable` with the reason, never a green light.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.shared.money import money, total

FORMULA_VERSION = "treasury-v1.0"
#: A bank feed older than this is stale enough to distrust the position.
STALE_BALANCE_DAYS = 3
#: Buckets (in days) reported by the forecast.
DEFAULT_HORIZONS = (30, 60, 90)
MAX_HORIZON_DAYS = 365

FORMULAS = {
    "cash_position": "Somma dei saldi contabili noti dei conti attivi; null se un conto non ha saldo.",
    "open_residual": "Importo partita - allocazioni di incasso/pagamento - write-off; le partite annullate valgono 0.",
    "expected_inflows": "Somma dei residui delle partite receivable con scadenza nella finestra.",
    "expected_outflows": "Somma dei residui delle partite payable con scadenza nella finestra.",
    "net_flow": "Incassi attesi - pagamenti attesi nella finestra.",
    "projected_balance": "Saldo noto + flusso netto cumulato alla data; null se il saldo non è noto.",
    "first_negative_day": "Prima data in cui il saldo proiettato scende sotto zero; null se mai o se il saldo non è noto.",
    "overdue": "Partite con residuo > 0 e scadenza anteriore alla data di analisi; escluse dalle proiezioni.",
    "dso_proxy": "Non calcolato: richiede ricavi di competenza certificati. Deliberatamente assente.",
}


@dataclass(frozen=True)
class AccountFact:
    """What is known about one bank account at analysis time."""

    id: str
    label: str
    bank_name: str | None
    iban_last4: str | None
    provider_key: str
    is_real_institution: bool
    connection_status: str
    balance_amount: Decimal | None
    balance_date: date | None
    balance_source: str
    last_sync_at: date | None
    currency: str = "EUR"


@dataclass(frozen=True)
class ItemFact:
    """An open item reduced to what the analytics need."""

    id: str
    direction: str                 # receivable | payable
    counterparty_name: str
    document_number: str | None
    due_date: date
    amount: Decimal
    residual: Decimal
    status: str
    source: str
    invoice_id: str | None = None

    def days_overdue(self, as_of: date) -> int:
        return max(0, (as_of - self.due_date).days)


@dataclass(frozen=True)
class UnreconciledFact:
    """A bank movement still carrying an unallocated residual."""

    id: str
    value_date: date
    amount: Decimal
    unallocated: Decimal
    description: str = ""
    counterparty_name: str | None = None


@dataclass
class Warning:
    code: str
    severity: str                  # critical | warning | info
    category: str                  # treasury | financial | data_quality
    title: str
    message: str
    formula: str
    evidence: dict = field(default_factory=dict)
    action_required: bool = False

    def as_dict(self) -> dict:
        return {
            "code": self.code, "severity": self.severity, "category": self.category,
            "title": self.title, "message": self.message, "formula": self.formula,
            "evidence": self.evidence, "action_required": self.action_required,
            "formula_version": FORMULA_VERSION,
        }


# ---------------------------------------------------------------------------
# Cash position
# ---------------------------------------------------------------------------

def build_position(accounts: list[AccountFact], *, as_of: date) -> dict:
    """Known cash today. `amount` is null unless **every** active account has a
    balance — a partial sum would look precise and be wrong."""
    known = [a for a in accounts if a.balance_amount is not None and a.balance_date is not None]
    missing = [a for a in accounts if a.balance_amount is None or a.balance_date is None]
    amount = total([a.balance_amount for a in known]) if accounts and not missing else None
    oldest = min((a.balance_date for a in known), default=None)
    staleness = (as_of - oldest).days if oldest else None
    issues: list[str] = []
    if not accounts:
        issues.append("Nessun conto bancario configurato: posizione di cassa non determinabile.")
    if missing:
        issues.append(f"{len(missing)} conto/i senza saldo noto: totale non determinabile, non assunto pari a zero.")
    if staleness is not None and staleness > STALE_BALANCE_DAYS:
        issues.append(f"Saldo più vecchio di {staleness} giorni: verificare l'aggiornamento del feed bancario.")
    if any(not a.is_real_institution for a in accounts):
        issues.append("Almeno un conto usa un provider sandbox: i movimenti sono simulati, non bancari reali.")
    return {
        "as_of": as_of.isoformat(),
        "currency": "EUR",
        "amount": money(amount),
        "status": "available" if amount is not None else "not_calculable",
        "oldest_balance_date": oldest.isoformat() if oldest else None,
        "staleness_days": staleness,
        "accounts": [{
            "id": a.id, "label": a.label, "bank_name": a.bank_name,
            "iban_last4": a.iban_last4, "provider_key": a.provider_key,
            "is_real_institution": a.is_real_institution,
            "connection_status": a.connection_status,
            "balance": money(a.balance_amount),
            "balance_date": a.balance_date.isoformat() if a.balance_date else None,
            "balance_source": a.balance_source,
            "last_sync_at": a.last_sync_at.isoformat() if a.last_sync_at else None,
        } for a in accounts],
        "issues": issues,
        "formula": FORMULAS["cash_position"],
        "formula_version": FORMULA_VERSION,
    }


# ---------------------------------------------------------------------------
# Aging (scadenzario)
# ---------------------------------------------------------------------------

def build_aging(items: list[ItemFact], *, as_of: date) -> dict:
    """Residuals split by direction and by how far past due they are."""
    buckets = (("current", None), ("d1_30", (1, 30)), ("d31_60", (31, 60)),
               ("d61_90", (61, 90)), ("d90_plus", (91, None)))

    def side(direction: str) -> dict:
        rows = [i for i in items if i.direction == direction and i.residual > 0]
        out: dict = {"total": money(total([i.residual for i in rows])), "count": len(rows), "buckets": {}}
        for name, window in buckets:
            if window is None:
                selected = [i for i in rows if i.due_date >= as_of]
            else:
                low, high = window
                selected = [i for i in rows
                            if i.days_overdue(as_of) >= low
                            and (high is None or i.days_overdue(as_of) <= high)]
            out["buckets"][name] = {
                "amount": money(total([i.residual for i in selected])),
                "count": len(selected),
            }
        overdue = [i for i in rows if i.due_date < as_of]
        out["overdue"] = {
            "amount": money(total([i.residual for i in overdue])),
            "count": len(overdue),
            "max_days": max((i.days_overdue(as_of) for i in overdue), default=0),
            "items": [{
                "id": i.id, "counterparty_name": i.counterparty_name,
                "document_number": i.document_number, "due_date": i.due_date.isoformat(),
                "residual": money(i.residual), "days_overdue": i.days_overdue(as_of),
                "source": i.source, "invoice_id": i.invoice_id,
            } for i in sorted(overdue, key=lambda i: i.due_date)[:20]],
        }
        return out

    return {
        "as_of": as_of.isoformat(), "currency": "EUR",
        "receivables": side("receivable"), "payables": side("payable"),
        "formula": FORMULAS["open_residual"],
        "formula_version": FORMULA_VERSION,
    }


# ---------------------------------------------------------------------------
# Cash forecast
# ---------------------------------------------------------------------------

def build_forecast(position: dict, items: list[ItemFact], *, as_of: date,
                   horizon_days: int = 90) -> dict:
    """Day-by-day projection over dated obligations only.

    Facts are the residuals with their due dates; the only assumptions are the
    ones listed in `assumptions` — there is no trend, seasonality or
    behavioural model, deliberately.
    """
    horizon_days = max(1, min(int(horizon_days), MAX_HORIZON_DAYS))
    opening = Decimal(position["amount"]) if position["amount"] is not None else None
    live = [i for i in items if i.residual > 0]
    overdue = [i for i in live if i.due_date < as_of]
    inside = [i for i in live if as_of <= i.due_date <= as_of + timedelta(days=horizon_days)]

    daily: list[dict] = []
    cumulative = Decimal("0.00")
    first_negative: str | None = None
    for offset in range(0, horizon_days + 1):
        day = as_of + timedelta(days=offset)
        due_today = [i for i in inside if i.due_date == day]
        inflow = total([i.residual for i in due_today if i.direction == "receivable"]) or Decimal("0.00")
        outflow = total([i.residual for i in due_today if i.direction == "payable"]) or Decimal("0.00")
        cumulative += inflow - outflow
        projected = opening + cumulative if opening is not None else None
        if projected is not None and projected < 0 and first_negative is None:
            first_negative = day.isoformat()
        if due_today or offset == horizon_days:
            daily.append({
                "date": day.isoformat(), "inflow": money(inflow), "outflow": money(outflow),
                "net_cumulative": money(cumulative), "projected_balance": money(projected),
            })

    def window(days: int) -> dict:
        end = as_of + timedelta(days=days)
        selected = [i for i in inside if i.due_date <= end]
        inflow = total([i.residual for i in selected if i.direction == "receivable"])
        outflow = total([i.residual for i in selected if i.direction == "payable"])
        net = (inflow or Decimal("0.00")) - (outflow or Decimal("0.00")) if (inflow or outflow) else None
        return {
            "horizon_days": days, "end_date": end.isoformat(),
            "expected_inflows": money(inflow), "expected_outflows": money(outflow),
            "net_flow": money(net),
            "projected_balance": money(opening + net) if opening is not None and net is not None
            else (money(opening) if opening is not None and net is None else None),
            "item_count": len(selected),
        }

    horizons = [window(d) for d in DEFAULT_HORIZONS if d <= horizon_days]
    if horizon_days not in DEFAULT_HORIZONS:
        horizons.append(window(horizon_days))

    issues = list(position["issues"])
    if opening is None:
        issues.append("Saldo iniziale non noto: le proiezioni di saldo restano null, solo i flussi sono calcolabili.")
    if not live:
        issues.append("Nessuna partita aperta: nessun flusso atteso da dati reali.")
    return {
        "as_of": as_of.isoformat(), "currency": "EUR",
        "horizon_days": horizon_days,
        "opening_balance": money(opening),
        "opening_balance_status": position["status"],
        "horizons": horizons,
        "daily": daily,
        "first_negative_date": first_negative,
        "days_to_negative": ((date.fromisoformat(first_negative) - as_of).days
                             if first_negative else None),
        "overdue_excluded": {
            "receivable": money(total([i.residual for i in overdue if i.direction == "receivable"])),
            "payable": money(total([i.residual for i in overdue if i.direction == "payable"])),
            "count": len(overdue),
        },
        "facts": [
            "Partite aperte con scadenza contrattuale e residuo calcolato dalle allocazioni.",
            "Saldo iniziale dai saldi bancari noti alla data indicata.",
        ],
        "assumptions": [
            "Ogni partita è incassata/pagata esattamente alla data di scadenza: nessun modello di ritardo.",
            "Le partite già scadute NON sono considerate incassate e restano escluse dalle proiezioni.",
            "Non sono modellati IVA, F24, stipendi, rate di finanziamento o costi ricorrenti "
            "che non siano già presenti come partite aperte.",
            "Nessuna estrapolazione di trend: la previsione non è un budget di tesoreria approvato.",
        ],
        "formulas": {k: FORMULAS[k] for k in
                     ("expected_inflows", "expected_outflows", "net_flow",
                      "projected_balance", "first_negative_day", "overdue")},
        "formula_version": FORMULA_VERSION,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

def derive_warnings(*, position: dict, forecast: dict, aging: dict,
                    unreconciled: list[UnreconciledFact], as_of: date,
                    overdue_threshold: Decimal = Decimal("1000.00"),
                    unreconciled_age_days: int = 10) -> list[dict]:
    """Deterministic treasury warnings. Never green when data is missing."""
    warnings: list[Warning] = []

    if forecast["first_negative_date"] is not None:
        warnings.append(Warning(
            code="cash_forecast_negative", severity="critical", category="treasury",
            title="Cassa proiettata negativa",
            message=(f"Con le partite aperte a scadenza, il saldo proiettato diventa negativo il "
                     f"{forecast['first_negative_date']} (tra {forecast['days_to_negative']} giorni)."),
            formula=FORMULAS["first_negative_day"],
            evidence={"first_negative_date": forecast["first_negative_date"],
                      "days_to_negative": forecast["days_to_negative"],
                      "opening_balance": forecast["opening_balance"],
                      "horizon_days": forecast["horizon_days"]},
            action_required=True,
        ))

    no_accounts = not position["accounts"]
    no_items = (aging["receivables"]["count"] + aging["payables"]["count"]) == 0
    if no_accounts and no_items:
        # Nothing has been set up yet: that is a configuration gap, not a
        # financial problem — it must not outrank a real alert in the hub.
        warnings.append(Warning(
            code="treasury_not_configured", severity="info", category="data_quality",
            title="Tesoreria non configurata",
            message="Nessun conto bancario e nessuna partita aperta: gli indicatori di cassa non sono calcolabili.",
            formula="conti attivi = 0 AND partite aperte = 0",
            evidence={"issues": position["issues"]},
        ))
    elif position["status"] == "not_calculable":
        detail = ("Nessun conto bancario configurato" if no_accounts
                  else "Manca il saldo di almeno un conto")
        warnings.append(Warning(
            code="cash_position_unknown", severity="warning", category="data_quality",
            title="Posizione di cassa non determinabile",
            message=f"{detail}: nessun totale viene stimato e nessun valore è assunto pari a zero.",
            formula=FORMULAS["cash_position"],
            evidence={"issues": position["issues"], "accounts": len(position["accounts"]),
                      "open_items": aging["receivables"]["count"] + aging["payables"]["count"]},
            action_required=True,
        ))
    elif (position["staleness_days"] or 0) > STALE_BALANCE_DAYS:
        warnings.append(Warning(
            code="bank_feed_stale", severity="warning", category="data_quality",
            title="Feed bancario non aggiornato",
            message=(f"Il saldo più vecchio risale a {position['staleness_days']} giorni: "
                     f"gli indicatori di cassa possono essere superati."),
            formula=f"oggi - min(balance_date) > {STALE_BALANCE_DAYS} giorni",
            evidence={"staleness_days": position["staleness_days"],
                      "oldest_balance_date": position["oldest_balance_date"]},
        ))

    for direction, label in (("receivables", "Crediti scaduti"), ("payables", "Debiti scaduti")):
        overdue = aging[direction]["overdue"]
        if overdue["amount"] is None or Decimal(overdue["amount"]) < overdue_threshold:
            continue
        warnings.append(Warning(
            code=f"overdue_{direction}", severity="warning", category="financial",
            title=label,
            message=(f"{overdue['count']} partite scadute per {overdue['amount']} EUR; "
                     f"massimo ritardo {overdue['max_days']} giorni."),
            formula=FORMULAS["overdue"],
            evidence={"amount": overdue["amount"], "count": overdue["count"],
                      "max_days": overdue["max_days"],
                      "items": overdue["items"][:5],
                      "threshold": str(overdue_threshold)},
            action_required=direction == "receivables",
        ))

    stale_unreconciled = [u for u in unreconciled
                          if (as_of - u.value_date).days >= unreconciled_age_days]
    if stale_unreconciled:
        warnings.append(Warning(
            code="unreconciled_backlog", severity="warning", category="data_quality",
            title="Movimenti bancari non riconciliati",
            message=(f"{len(stale_unreconciled)} movimenti con residuo non allocato da almeno "
                     f"{unreconciled_age_days} giorni: gli indicatori di incasso sono incompleti."),
            formula="movimenti con residuo non allocato e data valuta <= oggi - soglia",
            evidence={"count": len(stale_unreconciled),
                      "total_unallocated": money(total([u.unallocated.copy_abs()
                                                        for u in stale_unreconciled])),
                      "oldest_value_date": min(u.value_date for u in stale_unreconciled).isoformat()},
            action_required=True,
        ))

    if any(not a["is_real_institution"] for a in position["accounts"]):
        warnings.append(Warning(
            code="sandbox_bank_data", severity="info", category="data_quality",
            title="Dati bancari sandbox",
            message="I movimenti provengono da un provider sandbox simulato: non usarli per decisioni reali.",
            formula="provider bancario con is_real_institution = false",
            evidence={"accounts": [a["label"] for a in position["accounts"]
                                   if not a["is_real_institution"]]},
        ))
    return [w.as_dict() for w in warnings]
