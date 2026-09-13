"""Company domain logic: normalization, duplicate detection, completeness."""
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.companies.schemas import DuplicateMatch

_VAT_STRIP = re.compile(r"[^0-9A-Za-z]")


def normalize_vat(vat: str | None) -> str | None:
    """Uppercase, strip separators. Keeps the IT prefix if present."""
    if not vat:
        return None
    cleaned = _VAT_STRIP.sub("", vat).upper()
    return cleaned or None


def find_duplicates(
    db: Session,
    *,
    vat_number: str | None = None,
    tax_code: str | None = None,
    pec: str | None = None,
    legal_name: str | None = None,
    exclude_id=None,
) -> list[DuplicateMatch]:
    """Exact-identifier matches + a normalized-name probable match."""
    matches: list[DuplicateMatch] = []
    seen: set = set()

    def add(kind: str, company: Company, detail: str) -> None:
        key = (company.id, kind)
        if key in seen:
            return
        seen.add(key)
        matches.append(
            DuplicateMatch(kind=kind, company_id=company.id, legal_name=company.legal_name, detail=detail)
        )

    base = select(Company).where(Company.deleted_at.is_(None))
    if exclude_id is not None:
        base = base.where(Company.id != exclude_id)

    vat = normalize_vat(vat_number)
    if vat:
        for c in db.scalars(base.where(Company.vat_number == vat)):
            add("vat", c, f"VAT {vat}")
    if tax_code:
        tc = tax_code.strip().upper()
        for c in db.scalars(base.where(func.upper(Company.tax_code) == tc)):
            add("tax_code", c, f"Tax code {tc}")
    if pec:
        p = pec.strip().lower()
        for c in db.scalars(base.where(func.lower(Company.pec) == p)):
            add("pec", c, f"PEC {p}")
    if legal_name:
        normalized = " ".join(legal_name.lower().split())
        like = f"%{normalized}%"
        stmt = base.where(
            func.lower(func.trim(Company.legal_name)).like(like)
            | func.lower(func.trim(Company.trading_name)).like(like)
        )
        for c in db.scalars(stmt.limit(5)):
            add("name", c, "Similar legal/trading name")
    return matches


COMPANY_COMPLETENESS_FIELDS = [
    "legal_name", "vat_number", "status", "owner_id",
    "city", "region", "country",
    "email", "phone",
]


def completeness(company: Company) -> dict:
    """Transparent completeness: every missing field is named explicitly."""
    missing = [f for f in COMPANY_COMPLETENESS_FIELDS if getattr(company, f) in (None, "", [])]
    total = len(COMPANY_COMPLETENESS_FIELDS)
    return {
        "score": round((total - len(missing)) / total * 100),
        "missing_fields": missing,
        "required_fields": COMPANY_COMPLETENESS_FIELDS,
    }
