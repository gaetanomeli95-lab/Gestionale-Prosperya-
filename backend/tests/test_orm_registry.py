"""Regression tests for the ORM model registry (audit item T1).

Cross-module foreign keys are declared as strings. Before the fix, a fresh
process that imported a *single* model module and then used the ORM crashed
with `NoReferencedTableError` (reproduced on `open_items.invoice_id ->
invoices`). Each test below runs in a clean interpreter so the import order
is really under test and not polluted by the rest of the suite.
"""
import os
import subprocess
import sys
import textwrap

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(snippet: str) -> subprocess.CompletedProcess:
    env = {**os.environ,
           "DATABASE_URL": "sqlite://",   # in-memory, no file side effects
           "JWT_SECRET": "regression-secret-with-32-plus-bytes!!",
           "ENVIRONMENT": "test"}
    return subprocess.run([sys.executable, "-c", textwrap.dedent(snippet)],  # noqa: S603 — fixed interpreter, literal snippets
                          cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("module", [
    # Verified reproduction: without the before_configured hook this raises
    # InvalidRequestError "expression 'User' failed to locate a name".
    "app.modules.companies.models",
    "app.modules.treasury.models",     # open_items -> invoices (billing): the audit crash
])
def test_single_model_import_then_mapper_configuration_is_safe(module):
    r = _run(f"""
        import {module}
        from sqlalchemy.orm import configure_mappers
        from app.db import Base
        configure_mappers()          # raised before the fix for modules with string relationships
        assert "invoices" in Base.metadata.tables, "registry not fully loaded"
        assert "companies" in Base.metadata.tables
        print("OK", len(Base.metadata.tables))
    """)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("OK")


def test_hook_is_what_fixes_it():
    """Prove causality: removing the hook re-introduces the failure."""
    r = _run("""
        import sqlalchemy.orm as o, sqlalchemy.event as ev
        import app.db as d
        ev.remove(o.Mapper, "before_configured", d._ensure_registry_before_mapper_configuration)
        import app.modules.companies.models
        try:
            o.configure_mappers()
            print("UNEXPECTED: no error")
        except Exception as e:
            print("EXPECTED", type(e).__name__)
    """)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("EXPECTED InvalidRequestError"), r.stdout


def test_partial_import_then_create_all_and_flush():
    """create_all bypasses mapper configuration, so callers load the registry
    explicitly via load_model_registry(); the flush then exercises the hook."""
    r = _run("""
        import uuid
        import app.modules.treasury.models
        from app.db import Base, SessionLocal, engine, load_model_registry
        load_model_registry()
        Base.metadata.create_all(bind=engine)
        from app.modules.tenancy.models import Tenant
        with SessionLocal() as db:
            db.add(Tenant(display_name="t", slug="t-" + uuid.uuid4().hex[:6]))
            db.flush()
        print("OK", len(Base.metadata.tables))
    """)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("OK")


def test_registry_lists_every_models_module():
    """models_all must not go stale: every modules/*/models.py must be listed."""
    import app.models_all as reg
    modules_dir = os.path.join(BACKEND, "app", "modules")
    expected = {f"app.modules.{d}.models" for d in os.listdir(modules_dir)
                if os.path.isfile(os.path.join(modules_dir, d, "models.py"))}
    with open(reg.__file__, encoding="utf-8") as fh:
        listed = {line.split()[1] for line in fh if line.startswith("import app.modules.")}
    assert expected == listed, f"missing from models_all: {expected - listed}; extra: {listed - expected}"
