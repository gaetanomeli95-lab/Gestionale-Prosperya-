from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.companies.models import Company, CompanyStatus
from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyListItem,
    CompanyOut,
    CompanyUpdate,
    DuplicateCheckResponse,
)
from app.modules.companies.service import completeness, find_duplicates, normalize_vat
from app.modules.users.models import User
from app.shared.events import diff_changes, record_activity, record_audit
from app.shared.mixins import utcnow
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/companies", tags=["companies"])


def _get_company_or_404(db: Session, company_id: UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.deleted_at is not None:
        raise NotFoundError("Company not found.")
    return company


@router.get("", response_model=Page[CompanyListItem])
def list_companies(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: str | None = None,
    status: CompanyStatus | None = None,
    owner_id: UUID | None = None,
    unassigned: bool = False,
    sort: str = "legal_name",
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("companies:read")),
):
    stmt = select(Company).where(Company.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Company.legal_name.ilike(like),
                Company.trading_name.ilike(like),
                Company.vat_number.ilike(like),
                Company.email.ilike(like),
                Company.city.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(Company.status == status)
    if owner_id:
        stmt = stmt.where(Company.owner_id == owner_id)
    if unassigned:
        stmt = stmt.where(Company.owner_id.is_(None))
    sort_col = {
        "legal_name": Company.legal_name,
        "updated_at": Company.updated_at.desc(),
        "created_at": Company.created_at.desc(),
    }.get(sort, Company.legal_name)
    return paginate(db, stmt.order_by(sort_col), PageParams(page, page_size), CompanyListItem)


@router.post("/check-duplicates", response_model=DuplicateCheckResponse)
def check_duplicates(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("companies:read")),
):
    matches = find_duplicates(
        db,
        vat_number=payload.vat_number,
        tax_code=payload.tax_code,
        pec=payload.pec,
        legal_name=payload.legal_name,
    )
    return DuplicateCheckResponse(matches=matches)


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("companies:write")),
):
    vat = normalize_vat(payload.vat_number)
    matches = find_duplicates(
        db, vat_number=vat, tax_code=payload.tax_code, pec=payload.pec
    )
    exact = [m for m in matches if m.kind in {"vat", "tax_code", "pec"}]
    if exact and not payload.confirm_duplicate:
        raise ConflictError(
            "A company with the same identifier already exists.",
            code="duplicate_company",
            details={"matches": [m.model_dump(mode="json") for m in exact]},
        )
    data = payload.model_dump(exclude={"confirm_duplicate"})
    data["vat_number"] = vat
    if data.get("tax_code"):
        data["tax_code"] = data["tax_code"].upper()
    company = Company(**data, created_by_id=actor.id)
    db.add(company)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError(
            "A company with this identifier already exists.",
            code="duplicate_company",
        ) from None
    record_activity(
        db, actor_id=actor.id, event_type="company.created",
        entity_type="company", entity_id=company.id,
        summary=f"Company “{company.legal_name}” created",
    )
    record_audit(db, actor_id=actor.id, action="company.create", entity_type="company", entity_id=company.id)
    db.commit()
    return CompanyOut.model_validate(company)


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("companies:read")),
):
    return CompanyOut.model_validate(_get_company_or_404(db, company_id))


@router.get("/{company_id}/completeness")
def company_completeness(
    company_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("companies:read")),
):
    return completeness(_get_company_or_404(db, company_id))


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("companies:write")),
):
    company = _get_company_or_404(db, company_id)
    if payload.version != company.version:
        raise ConflictError(
            "This record was modified by someone else. Reload and try again.",
            code="stale_version",
        )
    before = {c.name: getattr(company, c.name) for c in Company.__table__.columns}
    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "vat_number" in data:
        data["vat_number"] = normalize_vat(data["vat_number"])
        if data["vat_number"]:
            clash = find_duplicates(db, vat_number=data["vat_number"], exclude_id=company.id)
            if any(m.kind == "vat" for m in clash):
                raise ConflictError(
                    "Another company already uses this VAT number.",
                    code="duplicate_company",
                    details={"matches": [m.model_dump(mode="json") for m in clash]},
                )
    if data.get("tax_code"):
        data["tax_code"] = data["tax_code"].upper()
    for k, v in data.items():
        setattr(company, k, v)
    company.version += 1
    after = {c.name: getattr(company, c.name) for c in Company.__table__.columns}
    changes = diff_changes(before, after)
    if changes:
        record_activity(
            db, actor_id=actor.id, event_type="company.updated",
            entity_type="company", entity_id=company.id,
            summary=f"Company “{company.legal_name}” updated",
            payload={"fields": sorted(changes)},
        )
        record_audit(
            db, actor_id=actor.id, action="company.update", entity_type="company",
            entity_id=company.id, changes=changes,
        )
    db.commit()
    return CompanyOut.model_validate(company)


@router.delete("/{company_id}", status_code=204)
def delete_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("companies:write")),
):
    company = _get_company_or_404(db, company_id)
    company.deleted_at = utcnow()
    company.version += 1
    record_activity(
        db, actor_id=actor.id, event_type="company.deleted",
        entity_type="company", entity_id=company.id,
        summary=f"Company “{company.legal_name}” archived",
    )
    record_audit(db, actor_id=actor.id, action="company.delete", entity_type="company", entity_id=company.id)
    db.commit()
