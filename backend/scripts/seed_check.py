"""Seed + idempotency check against the configured DATABASE_URL.

    python -m scripts.verify_seed            # base seed, run twice
    PROSPERYA_PREVIEW=1 python -m scripts.verify_seed   # + preview dataset

Prints row counts per non-empty table and asserts the second run inserted
nothing. Works on SQLite and PostgreSQL. Never runs in production.
"""
import os
import sys

from sqlalchemy import inspect, text

import app.models_all  # noqa: F401
from app.config import get_settings
from app.db import SessionLocal, engine


def _counts(db) -> dict[str, int]:
    names = inspect(engine).get_table_names()
    out = {}
    for t in names:
        if t.startswith("alembic"):
            continue
        n = db.execute(text(f'select count(*) from "{t}"')).scalar()  # noqa: S608 — names come from the inspector
        if n:
            out[t] = n
    return out


def main() -> int:
    if get_settings().is_production:
        print("Refusing to seed in production.", file=sys.stderr)
        return 1
    from app.seed import seed
    preview = os.environ.get("PROSPERYA_PREVIEW") == "1"
    if preview:
        from app.preview_seed import seed_preview

    def run():
        with SessionLocal() as db:
            seed(db)
        if preview:
            with SessionLocal() as db:
                seed_preview(db)

    run()
    with SessionLocal() as db:
        first = _counts(db)
    run()
    with SessionLocal() as db:
        second = _counts(db)

    print(f"dialect={engine.dialect.name}  tables_with_rows={len(first)}")
    for t, n in sorted(first.items()):
        print(f"  {t:40s} {n}")
    diff = {t: (first.get(t, 0), second.get(t, 0)) for t in set(first) | set(second)
            if first.get(t, 0) != second.get(t, 0)}
    if diff:
        print("NOT IDEMPOTENT:", diff, file=sys.stderr)
        return 2
    print("idempotent: second run inserted nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
