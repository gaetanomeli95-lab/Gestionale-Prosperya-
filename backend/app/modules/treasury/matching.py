"""Deterministic bank-reconciliation engine (levels 1 and 2).

Pure functions, no database, no AI, no randomness: the same inputs always
produce the same suggestions, and every suggestion carries the evidence that
justifies it. This is what the product decides with — an LLM may later
*explain* a suggestion or triage the leftovers (level 3), but it can never
invent or silently commit a pairing (see `docs/TREASURY_ARCHITECTURE.md`).

Levels
------
* **L1 exact** — residual equals the movement to the cent **and** a strong
  reference is present (document number, VAT/tax code, or an identical
  normalised counterparty name). Confidence 1.00; unambiguous single
  candidates may be applied in bulk by an operator.
* **L1 combination** — one movement settles several items of the same
  counterparty whose residuals sum exactly to the movement (cumulative
  payment). Deterministic subset search, bounded.
* **L2 fuzzy** — weighted deterministic score over amount closeness, due-date
  proximity, name similarity and partial references. Always requires explicit
  human approval.
* **L3 AI-assisted** — NOT implemented. Status: DESIGNED. Unmatched movements
  are returned as such, never guessed.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import combinations

ENGINE_VERSION = "reconciliation-v1.0"

#: Score at or above which a level-2 suggestion is shown at all.
FUZZY_MIN_SCORE = Decimal("0.60")
#: Absolute/relative tolerance for "nearly the same amount" at level 2.
AMOUNT_TOLERANCE_ABS = Decimal("5.00")
AMOUNT_TOLERANCE_PCT = Decimal("0.01")
#: Bounds that keep the combination search cheap and deterministic.
MAX_COMBINATION_ITEMS = 6
MAX_COMBINATION_SIZE = 4
MAX_SUGGESTIONS_PER_TX = 5

_LEGAL_FORMS = (
    "societa a responsabilita limitata", "s r l s", "s r l", "srls", "srl",
    "s p a", "spa", "s n c", "snc", "s a s", "sas", "s c a r l", "scarl",
    "societa cooperativa", "coop", "ss", "sc",
)


def normalize_text(value: str | None) -> str:
    """Uppercase, accent-free, punctuation-free, single-spaced."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", ascii_only).strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def normalize_counterparty(value: str | None) -> str:
    """Normalised name with Italian legal forms removed (RSL/SRL/SPA…)."""
    text = normalize_text(value)
    if not text:
        return ""
    for form in _LEGAL_FORMS:
        text = re.sub(rf"(?:^|\s){re.escape(form)}(?:\s|$)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def document_tokens(document_number: str | None) -> list[str]:
    """Reference tokens worth searching for inside a bank description.

    Returns the normalised full reference plus its numeric core (``12/2026`` ->
    ``12 2026`` -> ``122026`` and ``12``), skipping tokens so short they would
    match by accident.
    """
    normalized = normalize_text(document_number)
    if not normalized:
        return []
    tokens = {normalized, normalized.replace(" ", "")}
    digits = re.findall(r"\d+", normalized)
    if digits:
        tokens.add("".join(digits))
        longest = max(digits, key=len)
        if len(longest) >= 3:
            tokens.add(longest)
    return [t for t in sorted(tokens, key=lambda t: (-len(t), t)) if len(t) >= 3]


@dataclass(frozen=True)
class TxView:
    """A bank movement plus how much of it is still unallocated."""

    id: str
    value_date: date
    booking_date: date
    amount: Decimal                  # signed, as booked
    unallocated: Decimal             # signed residual, same sign as `amount`
    description: str = ""
    counterparty_name: str | None = None

    @property
    def direction(self) -> str:
        """Which kind of open item this movement can settle."""
        return "receivable" if self.amount > 0 else "payable"

    @property
    def haystack(self) -> str:
        return normalize_text(f"{self.description} {self.counterparty_name or ''}")


@dataclass(frozen=True)
class ItemView:
    """An open item plus its residual (both always positive)."""

    id: str
    direction: str
    counterparty_name: str
    due_date: date
    amount: Decimal
    residual: Decimal
    document_number: str | None = None
    counterparty_vat: str | None = None
    document_date: date | None = None


@dataclass(frozen=True)
class SuggestedAllocation:
    open_item_id: str
    amount: Decimal


@dataclass(frozen=True)
class Suggestion:
    bank_transaction_id: str
    allocations: tuple[SuggestedAllocation, ...]
    method: str                      # "exact" | "fuzzy"
    level: int                       # 1 | 2
    confidence: Decimal              # 0.00 .. 1.00
    reasons: tuple[str, ...]
    evidence: dict = field(default_factory=dict)
    engine_version: str = ENGINE_VERSION

    @property
    def is_unambiguous_exact(self) -> bool:
        return self.method == "exact" and self.confidence == Decimal("1.00")


def _reference_hits(tx: TxView, item: ItemView) -> list[str]:
    """Strong, verifiable references found in the movement text."""
    hits: list[str] = []
    haystack = tx.haystack
    compact = haystack.replace(" ", "")
    for token in document_tokens(item.document_number):
        if token in haystack or token in compact:
            hits.append(f"document_number:{item.document_number}")
            break
    vat = normalize_text(item.counterparty_vat).replace(" ", "")
    if len(vat) >= 8 and vat in compact:
        hits.append(f"counterparty_vat:{item.counterparty_vat}")
    item_name = normalize_counterparty(item.counterparty_name)
    tx_name = normalize_counterparty(tx.counterparty_name)
    if item_name and tx_name and item_name == tx_name:
        hits.append("counterparty_name:exact")
    elif item_name and len(item_name) >= 5 and item_name in haystack:
        hits.append("counterparty_name:in_description")
    return hits


def name_similarity(tx: TxView, item: ItemView) -> Decimal:
    """Deterministic 0..1 similarity between counterparty names."""
    item_name = normalize_counterparty(item.counterparty_name)
    if not item_name:
        return Decimal("0.00")
    candidates = [normalize_counterparty(tx.counterparty_name)]
    # Also try the leading words of the description: bank causali often start
    # with the payer's name ("BONIFICO DA ROSSI S ...").
    description = normalize_counterparty(tx.description)
    if description:
        words = description.split()
        candidates.append(" ".join(words[: max(2, len(item_name.split()) + 1)]))
    best = Decimal("0.00")
    for candidate in candidates:
        if not candidate:
            continue
        ratio = Decimal(str(round(SequenceMatcher(None, item_name, candidate).ratio(), 2)))
        best = max(best, ratio)
    return best


def _amount_component(residual: Decimal, movement: Decimal) -> tuple[Decimal, str] | None:
    """Score the amount closeness, or None when the gap disqualifies the pair."""
    if residual == movement:
        return Decimal("0.50"), "importo identico al centesimo"
    gap = abs(residual - movement)
    tolerance = max(AMOUNT_TOLERANCE_ABS, (movement * AMOUNT_TOLERANCE_PCT).copy_abs())
    if gap <= tolerance:
        return Decimal("0.35"), f"scostamento importo {gap} entro tolleranza {tolerance}"
    return None


def _date_component(tx: TxView, item: ItemView) -> tuple[Decimal, str]:
    delta = abs((tx.value_date - item.due_date).days)
    if delta <= 5:
        return Decimal("0.25"), f"data valuta a {delta} giorni dalla scadenza"
    if delta <= 30:
        return Decimal("0.15"), f"data valuta a {delta} giorni dalla scadenza"
    if delta <= 60:
        return Decimal("0.05"), f"data valuta a {delta} giorni dalla scadenza"
    return Decimal("0.00"), f"data valuta distante {delta} giorni dalla scadenza"


def _pair_suggestion(tx: TxView, item: ItemView) -> Suggestion | None:
    """Evaluate one movement against one open item."""
    movement = tx.unallocated.copy_abs()
    if movement <= 0 or item.residual <= 0 or item.direction != tx.direction:
        return None
    references = _reference_hits(tx, item)
    exact_amount = item.residual == movement
    if exact_amount and references:
        return Suggestion(
            bank_transaction_id=tx.id,
            allocations=(SuggestedAllocation(item.id, item.residual),),
            method="exact", level=1, confidence=Decimal("1.00"),
            reasons=("importo identico al centesimo",
                     *(f"riferimento verificato: {r}" for r in references)),
            evidence={"amount": str(movement), "references": references,
                      "residual": str(item.residual),
                      "rule": "residuo == movimento AND riferimento forte presente"},
        )
    amount_part = _amount_component(item.residual, movement)
    if amount_part is None:
        return None
    amount_score, amount_reason = amount_part
    date_score, date_reason = _date_component(tx, item)
    similarity = name_similarity(tx, item)
    if similarity >= Decimal("0.85"):
        name_score, name_reason = Decimal("0.25"), f"nome controparte simile ({similarity})"
    elif similarity >= Decimal("0.70"):
        name_score, name_reason = Decimal("0.15"), f"nome controparte parzialmente simile ({similarity})"
    else:
        name_score, name_reason = Decimal("0.00"), f"nome controparte non comparabile ({similarity})"
    reference_score = Decimal("0.20") if references else Decimal("0.00")
    score = min(Decimal("0.99"), amount_score + date_score + name_score + reference_score)
    if score < FUZZY_MIN_SCORE:
        return None
    reasons = [amount_reason, date_reason, name_reason]
    reasons.extend(f"riferimento parziale: {r}" for r in references)
    return Suggestion(
        bank_transaction_id=tx.id,
        allocations=(SuggestedAllocation(item.id, min(item.residual, movement)),),
        method="fuzzy", level=2, confidence=score,
        reasons=tuple(reasons),
        evidence={
            "score": str(score), "components": {
                "amount": str(amount_score), "date": str(date_score),
                "name": str(name_score), "reference": str(reference_score),
            },
            "name_similarity": str(similarity), "references": references,
            "rule": f"punteggio pesato >= {FUZZY_MIN_SCORE}, approvazione umana obbligatoria",
        },
    )


def _combination_suggestion(tx: TxView, items: list[ItemView]) -> Suggestion | None:
    """One movement settling several items of the same counterparty exactly."""
    movement = tx.unallocated.copy_abs()
    if movement <= 0:
        return None
    tx_name = normalize_counterparty(tx.counterparty_name)
    haystack = tx.haystack
    candidates = [
        item for item in items
        if item.direction == tx.direction and item.residual > 0
        and item.residual != movement
        and (
            (tx_name and normalize_counterparty(item.counterparty_name) == tx_name)
            or (len(normalize_counterparty(item.counterparty_name)) >= 5
                and normalize_counterparty(item.counterparty_name) in haystack)
        )
    ]
    if len(candidates) < 2:
        return None
    candidates = sorted(candidates, key=lambda i: (i.due_date, i.id))[:MAX_COMBINATION_ITEMS]
    for size in range(2, min(MAX_COMBINATION_SIZE, len(candidates)) + 1):
        for combo in combinations(candidates, size):
            if sum((i.residual for i in combo), Decimal("0.00")) == movement:
                return Suggestion(
                    bank_transaction_id=tx.id,
                    allocations=tuple(SuggestedAllocation(i.id, i.residual) for i in combo),
                    method="exact", level=1, confidence=Decimal("1.00"),
                    reasons=(f"pagamento cumulativo: {size} partite della stessa controparte "
                             f"sommano esattamente {movement}",),
                    evidence={
                        "amount": str(movement),
                        "items": [{"open_item_id": i.id, "residual": str(i.residual),
                                   "document_number": i.document_number} for i in combo],
                        "rule": "somma residui == movimento AND controparte coincidente",
                    },
                )
    return None


def suggest_for_transaction(tx: TxView, items: list[ItemView]) -> list[Suggestion]:
    """Ranked suggestions for one movement (best first, bounded)."""
    found: list[Suggestion] = []
    if (combo := _combination_suggestion(tx, items)) is not None:
        found.append(combo)
    for item in items:
        if (suggestion := _pair_suggestion(tx, item)) is not None:
            found.append(suggestion)
    found.sort(key=lambda s: (-s.confidence, s.level, s.allocations[0].open_item_id))
    return found[:MAX_SUGGESTIONS_PER_TX]


def suggest(transactions: list[TxView], items: list[ItemView]) -> dict:
    """Engine entry point.

    Returns suggestions grouped per movement plus the movements for which the
    deterministic rules found nothing — those are candidates for AI-assisted
    triage (level 3, not implemented) or manual work, never for a guess.
    """
    per_tx: list[dict] = []
    unmatched: list[str] = []
    auto_applicable = 0
    for tx in sorted(transactions, key=lambda t: (t.value_date, t.id)):
        suggestions = suggest_for_transaction(tx, items)
        if not suggestions:
            unmatched.append(tx.id)
            continue
        exact = [s for s in suggestions if s.is_unambiguous_exact]
        unambiguous = len(exact) == 1
        if unambiguous:
            auto_applicable += 1
        per_tx.append({
            "bank_transaction_id": tx.id,
            "amount": str(tx.amount),
            "unallocated": str(tx.unallocated),
            "value_date": tx.value_date.isoformat(),
            "description": tx.description,
            "counterparty_name": tx.counterparty_name,
            "auto_applicable": unambiguous,
            "suggestions": [{
                "method": s.method, "level": s.level, "confidence": str(s.confidence),
                "requires_approval": s.method != "exact" or not unambiguous,
                "allocations": [{"open_item_id": a.open_item_id, "amount": str(a.amount)}
                                for a in s.allocations],
                "reasons": list(s.reasons), "evidence": s.evidence,
                "engine_version": s.engine_version,
            } for s in suggestions],
        })
    return {
        "engine_version": ENGINE_VERSION,
        "levels": {
            "1": "Match deterministico esatto (importo al centesimo + riferimento verificato), "
                 "inclusi pagamenti cumulativi con somma esatta.",
            "2": "Punteggio deterministico (importo, data, similarità nome, riferimenti parziali): "
                 "sempre soggetto ad approvazione umana.",
            "3": "Triage assistito da AI sui movimenti residui: DESIGNED, non implementato. "
                 "Nessun abbinamento viene indovinato.",
        },
        "transactions": per_tx,
        "unmatched_transaction_ids": unmatched,
        "counters": {
            "evaluated": len(transactions),
            "with_suggestions": len(per_tx),
            "auto_applicable": auto_applicable,
            "unmatched": len(unmatched),
            "open_items_considered": len(items),
        },
    }
