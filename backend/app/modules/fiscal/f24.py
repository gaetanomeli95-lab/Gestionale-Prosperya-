"""F24 draft renderers — internal export only.

These renderers produce a **human-readable / machine-inspectable** copy of an
approved draft. They are deliberately NOT a telematic F24: the official
Entratel/CBI record layout is a technical specification that must be
implemented from the official document and validated against the official
checker before it may be called an "F24 file". Until then, exporting means
JSON or CSV for review and manual transcription.
"""
import csv
import hashlib
import io
import json
from decimal import Decimal

from app.modules.fiscal.models import F24Draft
from app.shared.money import money

EXPORT_FORMATS = ("json", "csv")


def _canonical_payload(draft: F24Draft) -> dict:
    """Stable, deterministic representation used for fingerprinting."""
    return {
        "format": "prosperya-f24-draft/v1",
        "disclaimer": ("Bozza interna Prosperya: NON è un modello F24 telematico "
                       "e non può essere trasmessa all'Agenzia delle Entrate."),
        "taxpayer": draft.taxpayer_snapshot,
        "due_date": draft.due_date.isoformat() if draft.due_date else None,
        "currency": draft.currency,
        "totals": {
            "debit": money(draft.total_debit),
            "credit": money(draft.total_credit),
            "balance": money(draft.balance),
        },
        "lines": [
            {
                "section": line.section,
                "tax_code": line.tax_code,
                "tax_code_description": line.tax_code_description,
                "reference_year": line.reference_year,
                "reference_period": line.reference_period,
                "debit_amount": money(line.debit_amount),
                "credit_amount": money(line.credit_amount),
                "origin_kind": line.origin_kind,
                "explanation": line.explanation,
            }
            for line in sorted(draft.lines, key=lambda row: row.position)
        ],
    }


def fingerprint(draft: F24Draft) -> str:
    canonical = json.dumps(_canonical_payload(draft), sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_json(draft: F24Draft) -> str:
    return json.dumps(_canonical_payload(draft), ensure_ascii=False, indent=2)


def render_csv(draft: F24Draft) -> str:
    """Flat row-per-line export for spreadsheet review."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["sezione", "codice_tributo", "descrizione", "anno_riferimento",
                     "mese_rif", "importi_a_debito", "importi_a_credito",
                     "scadenza", "provenienza", "spiegazione"])
    for line in sorted(draft.lines, key=lambda row: row.position):
        writer.writerow([
            line.section, line.tax_code, line.tax_code_description or "",
            line.reference_year, line.reference_period or "",
            _it_amount(line.debit_amount), _it_amount(line.credit_amount),
            draft.due_date.isoformat() if draft.due_date else "",
            line.origin_kind, line.explanation or "",
        ])
    writer.writerow([])
    writer.writerow(["TOTALE", "", "", "", "",
                     _it_amount(draft.total_debit), _it_amount(draft.total_credit),
                     "", "", "Bozza interna — non trasmissibile"])
    return buffer.getvalue()


def _it_amount(value: Decimal | None) -> str:
    if value is None:
        return ""
    return money(value).replace(".", ",")


def render(draft: F24Draft, fmt: str) -> tuple[str, str, str]:
    """Return (content, media_type, fingerprint) for a supported format."""
    if fmt == "json":
        return render_json(draft), "application/json", fingerprint(draft)
    if fmt == "csv":
        return render_csv(draft), "text/csv", fingerprint(draft)
    raise ValueError(f"Formato export non supportato: {fmt}. Disponibili: {EXPORT_FORMATS}.")
