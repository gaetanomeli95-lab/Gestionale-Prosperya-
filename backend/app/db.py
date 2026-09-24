"""Database engine, session factory and declarative base."""
import importlib

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapper, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def load_model_registry() -> None:
    """Import every ORM model module so `Base.metadata` is complete.

    Cross-module foreign keys are declared as strings ("invoices.id") and are
    only resolved when SQLAlchemy configures mappers or sorts tables. If a
    process imports a single model module and then touches the ORM, the
    referenced table may not be in the metadata yet and SQLAlchemy raises
    NoReferencedTableError. Calling this makes the registry complete
    regardless of import order. Idempotent and cheap after the first call.
    """
    importlib.import_module("app.models_all")


@event.listens_for(Mapper, "before_configured", once=True)
def _ensure_registry_before_mapper_configuration() -> None:
    # Fires exactly once, right before the first mapper configuration in the
    # process (first query / flush / relationship access). Loading the full
    # registry here removes the import-order dependency for every ORM path.
    load_model_registry()


def _make_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine()


@event.listens_for(engine, "connect")
def _sqlite_fk_pragma(dbapi_connection, connection_record):
    """Enforce foreign keys on SQLite (no-op elsewhere)."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:  # noqa: BLE001, S110 — pragma is best-effort; non-sqlite drivers may not support it
        pass


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
