"""Disposable backend for end-to-end tests (Playwright).

Starts the real API on a throw-away SQLite database, migrated with Alembic
and seeded with the demo dataset, using the test-only fast Argon2 profile.
Never used for anything but automated E2E.

    python scripts/e2e_server.py            # port 8000 by default
    E2E_PORT=8010 python scripts/e2e_server.py
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

DB = BACKEND / "e2e.db"
if DB.exists():
    DB.unlink()

os.environ.update({
    "DATABASE_URL": f"sqlite:///{DB.as_posix()}",
    "ENVIRONMENT": "test",
    "JWT_SECRET": "e2e-only-secret-with-at-least-32-bytes!!",
    "ARGON2_COST_PROFILE": "fast",
    "LOGIN_MAX_ATTEMPTS": "0",
    "CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
})

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")

import app.models_all  # noqa: E402, F401
from app.db import SessionLocal  # noqa: E402
from app.seed import seed  # noqa: E402

with SessionLocal() as db:
    seed(db)

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8000")), log_level="warning")
