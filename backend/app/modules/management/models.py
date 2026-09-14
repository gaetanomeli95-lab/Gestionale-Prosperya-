"""Management control (controllo di gestione) — append-only financial data.

Ported from the original Prosperya prototype and adapted to the tenant model:
every record is scoped by (tenant_id, company_id). Financial history is
append-only — corrections happen via new rows/versions with provenance.
"""
import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.mixins import GUID, PrimaryKeyMixin, TenantMixin, TimestampMixin


def _check(condition: str) -> CheckConstraint:
    suffix = hashlib.sha256(condition.encode("ascii")).hexdigest()[:12]
    return CheckConstraint(condition, name=f"ck_{condition.split()[0]}_{suffix}")


class ManagementScope(TenantMixin, TimestampMixin):
    company_id: Mapped[object] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ManagementCategory(ManagementScope, PrimaryKeyMixin, Base):
    __tablename__ = "management_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "kind", "name",
                         name="uq_category_scope_kind_name"),
        _check("kind IN ('revenue', 'cost')"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)


class CostCenter(ManagementScope, PrimaryKeyMixin, Base):
    __tablename__ = "cost_centers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "code",
                         name="uq_cost_center_scope_code"),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class ImportBatch(ManagementScope, PrimaryKeyMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "idempotency_key",
                         name="uq_import_scope_idempotency"),
        _check("row_count >= 0 AND duplicate_count >= 0"),
    )

    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[object] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    origin: Mapped[str] = mapped_column(String(40), nullable=False, default="csv_import")


class Actual(ManagementScope, PrimaryKeyMixin, Base):
    __tablename__ = "actuals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "source_id",
                         name="uq_actual_scope_source"),
        ForeignKeyConstraint(
            ["import_batch_id"], ["import_batches.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["category_id"], ["management_categories.id"], ondelete="RESTRICT"
        ),
        _check("kind IN ('revenue', 'cost')"),
        _check("amount > 0 AND amount < 1000000000000000000"),
        _check("currency = 'EUR'"),
    )

    import_batch_id: Mapped[object] = mapped_column(GUID(), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    category_id: Mapped[object] = mapped_column(GUID(), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    cost_center_id: Mapped[object | None] = mapped_column(GUID(), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class BudgetVersion(ManagementScope, PrimaryKeyMixin, Base):
    __tablename__ = "budget_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "year", "month", "version",
                         name="uq_budget_scope_month_version"),
        _check("year BETWEEN 2000 AND 2100"),
        _check("month BETWEEN 1 AND 12"),
        _check("version > 0"),
        _check("revenue IS NULL OR (revenue >= 0 AND revenue < 1000000000000000000)"),
        _check("costs IS NULL OR (costs >= 0 AND costs < 1000000000000000000)"),
        _check("revenue IS NOT NULL OR costs IS NOT NULL"),
        _check("currency = 'EUR'"),
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    costs: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    actor_id: Mapped[object] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)


def _reject_mutation(mapper, connection, target) -> None:
    raise ValueError(
        "Lo storico finanziario è append-only: creare una nuova versione con provenienza."
    )


for _model in (ImportBatch, Actual, BudgetVersion):
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)
