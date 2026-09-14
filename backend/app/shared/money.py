"""Canonical monetary primitives — Decimal in, decimal strings out.

Single source of truth for every module that touches money (MASTER_SPEC §5):
`Decimal` + `NUMERIC(20,2)` in the database, **strings** on the wire, and a
missing value is `None` (never `0`). Arithmetic runs in a high-precision
local context so intermediate divisions cannot silently lose cents.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

CENT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999999999.99")
_UNSIGNED = r"[0-9]{1,18}(?:\.[0-9]{1,2})?"


def parse_money(value: str, *, allow_zero: bool = False) -> Decimal:
    """Parse a non-negative decimal string. Raises ValueError on anything else."""
    import re

    if not isinstance(value, str) or not re.fullmatch(_UNSIGNED, value):
        raise ValueError("Importo richiesto come stringa decimale, massimo 18 cifre intere e 2 decimali.")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Importo decimale non valido.") from exc
    if not amount.is_finite() or amount > MAX_MONEY or amount < 0 or (not allow_zero and amount == 0):
        raise ValueError("L'importo deve essere positivo, finito e rappresentabile in NUMERIC(20,2).")
    return amount.quantize(CENT)


def parse_signed_money(value: str, *, allow_zero: bool = False) -> Decimal:
    """Parse a signed decimal string — bank movements are negative on outflow."""
    import re

    if not isinstance(value, str) or not re.fullmatch(rf"-?{_UNSIGNED}", value):
        raise ValueError("Importo richiesto come stringa decimale con segno opzionale.")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Importo decimale non valido.") from exc
    if not amount.is_finite() or abs(amount) > MAX_MONEY or (not allow_zero and amount == 0):
        raise ValueError("L'importo deve essere finito, non nullo e rappresentabile in NUMERIC(20,2).")
    return amount.quantize(CENT)


def money(value: Decimal | None) -> str | None:
    """Serialise for the wire: fixed 2-decimal string, or None if unknown."""
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 50
        return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    """Subtraction that propagates unknowns instead of assuming zero."""
    return None if left is None or right is None else left - right


def total(values: list[Decimal]) -> Decimal | None:
    """Sum of observed values; None when nothing was observed at all."""
    return sum(values, Decimal("0.00")) if values else None


def percentage(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 50
        return money(numerator / denominator * Decimal("100"))


def ratio(numerator: Decimal | None, denominator: Decimal | None, *, places: str = "0.01") -> str | None:
    """Dimensionless ratio (e.g. coverage indices) as a fixed-precision string."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 50
        return format((numerator / denominator).quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")
