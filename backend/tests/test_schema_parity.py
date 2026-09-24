"""Schema parity: every ForeignKey the ORM declares must exist in the DB that
the test suite runs against (SQLite by default, PostgreSQL via
TEST_DATABASE_URL). Catches migrations that silently drop constraints on one
dialect — e.g. the unnamed use_alter FK on documents.current_version_id that
PostgreSQL databases were missing until a7c1e3f9b2d4.

The suite creates its schema with metadata.create_all, so this test compares
the ORM against *itself* on SQLite; it becomes a real migration check when
the CI job runs the suite on PostgreSQL after `alembic upgrade head`.
"""
from sqlalchemy import inspect

from app.db import Base, engine


def _orm_fks() -> set[tuple[str, tuple[str, ...], str]]:
    out = set()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_key_constraints:
            out.add((table.name, tuple(c.name for c in fk.columns), fk.referred_table.name))
    return out


def _db_fks() -> set[tuple[str, tuple[str, ...], str]]:
    insp = inspect(engine)
    out = set()
    for table in insp.get_table_names():
        for fk in insp.get_foreign_keys(table):
            out.add((table, tuple(fk["constrained_columns"]), fk["referred_table"]))
    return out


def test_every_orm_foreign_key_exists_in_database():
    missing = _orm_fks() - _db_fks()
    assert not missing, f"FKs declared by ORM but absent in {engine.dialect.name}: {sorted(missing)}"


def test_circular_document_fk_is_named():
    fk = next(fk for fk in Base.metadata.tables["documents"].foreign_key_constraints
              if [c.name for c in fk.columns] == ["current_version_id"])
    assert fk.use_alter and fk.name == "documents_current_version_id_fkey"
