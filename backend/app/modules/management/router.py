"""Management-control API — consuntivi, budget, import e overview.

Every figure is a decimal string or null; missing evidence is never zero.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.companies.models import Company
from app.modules.management import service
from app.modules.management.models import ImportBatch
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/management", tags=["management"])


def _company_or_404(db: Session, company_id: UUID, ctx: TenantContext) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != ctx.tenant_id or company.deleted_at is not None:
        raise NotFoundError("Company not found.")
    return company


class ImportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=180, strict=True)
    csv_content: str = Field(min_length=1, max_length=service.MAX_CSV_BYTES, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128,
                                 pattern=r"^[A-Za-z0-9_.:-]+$", strict=True)

    @field_validator("csv_content")
    @classmethod
    def bounded_utf8(cls, value: str) -> str:
        service.csv_payload_bytes(value)
        return value

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if any(c in value for c in ("/", "\\")) or any(ord(c) < 32 for c in value):
            raise ValueError("Nome file non valido.")
        return value


class BudgetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=2000, le=2100, strict=True)
    month: int = Field(ge=1, le=12, strict=True)
    revenue: str | None = Field(default=None, strict=True)
    costs: str | None = Field(default=None, strict=True)

    @field_validator("revenue", "costs")
    @classmethod
    def valid_amount(cls, value: str | None) -> str | None:
        return service.money(service.parse_money(value, allow_zero=True)) if value is not None else None


@router.get("/companies/{company_id}/overview")
def overview(
    company_id: UUID,
    year: int = Query(2026, ge=2000, le=2100),
    through_month: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("management:read")),
):
    company = _company_or_404(db, company_id, ctx)
    return service.get_overview(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                year=year, through_month=through_month)


@router.get("/companies/{company_id}/actuals")
def actuals(
    company_id: UUID,
    year: int = Query(2026, ge=2000, le=2100),
    through_month: int = Query(12, ge=1, le=12),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("management:read")),
):
    company = _company_or_404(db, company_id, ctx)
    return service.get_actuals(db, tenant_id=ctx.tenant_id, company_id=company.id,
                               year=year, through_month=through_month)


@router.get("/companies/{company_id}/imports")
def imports(
    company_id: UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("management:read")),
):
    company = _company_or_404(db, company_id, ctx)
    rows = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == ctx.tenant_id, ImportBatch.company_id == company.id)
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id)
    ).all()
    return [service.batch_data(row) for row in rows]


@router.post("/companies/{company_id}/imports", status_code=201)
def import_actuals(
    company_id: UUID,
    payload: ImportPayload,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("management:write")),
):
    company = _company_or_404(db, company_id, ctx)
    result = service.import_actuals(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        filename=payload.filename, csv_content=payload.csv_content,
        idempotency_key=payload.idempotency_key)
    db.commit()
    return result


@router.get("/companies/{company_id}/budgets")
def budgets(
    company_id: UUID,
    year: int = Query(2026, ge=2000, le=2100),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("management:read")),
):
    company = _company_or_404(db, company_id, ctx)
    return service.get_budgets(db, tenant_id=ctx.tenant_id, company_id=company.id, year=year)


@router.put("/companies/{company_id}/budgets")
def save_budget(
    company_id: UUID,
    payload: BudgetPayload,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("management:write")),
):
    company = _company_or_404(db, company_id, ctx)
    result = service.save_budget(
        db, tenant_id=ctx.tenant_id, company=company, actor_id=actor.id,
        year=payload.year, month=payload.month,
        revenue=payload.revenue, costs=payload.costs)
    db.commit()
    return result


@router.get("/hub")
def hub(
    year: int = Query(2026, ge=2000, le=2100),
    through_month: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("management:read")),
):
    """Tenant-wide aggregate across companies. Non-consolidated: intercompany
    items are not eliminated — the totals object says so explicitly."""
    companies = db.scalars(
        select(Company)
        .where(Company.tenant_id == ctx.tenant_id, Company.deleted_at.is_(None))
        .order_by(Company.legal_name)
    ).all()
    entries, alerts = [], []
    for company in companies:
        overview = service.get_overview(db, tenant_id=ctx.tenant_id, company_id=company.id,
                                        year=year, through_month=through_month)
        entries.append({"company": {"id": str(company.id), "name": company.legal_name,
                                    "currency": "EUR"}, "overview": overview})
        alerts.extend({**alert, "company_id": str(company.id),
                       "company_name": company.legal_name} for alert in overview["alerts"])
    return {"companies": entries, "totals": _aggregate(entries), "alerts": alerts}


def _aggregate(entries: list[dict]) -> dict:
    totals = {"currency": "EUR", "revenue": None, "costs": None, "result": None,
              "margin": None, "margin_percent": None,
              "quality": "partial" if entries else "empty", "company_count": len(entries),
              "issues": ["Aggregati gestionali disponibili, non consolidati: "
                         "operazioni infragruppo non eliminate."]}
    if not entries:
        return totals
    from decimal import Decimal
    for component in ("revenue", "costs", "result"):
        values = [entry["overview"][component] for entry in entries]
        if all(value is not None for value in values):
            totals[component] = service.money(
                sum((Decimal(v) for v in values), Decimal("0.00")))
        else:
            totals["issues"].append(
                f"{component}: componente mancante in almeno un'azienda, totale null.")
    totals["margin"] = totals["result"]
    totals["margin_percent"] = service.percentage(
        Decimal(totals["result"]) if totals["result"] is not None else None,
        Decimal(totals["revenue"]) if totals["revenue"] is not None else None,
    )
    return totals
