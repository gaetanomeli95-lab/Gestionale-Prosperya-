"""Server-side pagination helpers and generic envelope."""
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class PageParams:
    def __init__(self, page: int = 1, page_size: int = 25):
        self.page = max(page, 1)
        self.page_size = min(max(page_size, 1), 200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


def paginate(db: Session, stmt, params: PageParams, item_schema=None):
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset(params.offset).limit(params.page_size)).all()
    items = [item_schema.model_validate(r) for r in rows] if item_schema is not None else list(rows)
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}
