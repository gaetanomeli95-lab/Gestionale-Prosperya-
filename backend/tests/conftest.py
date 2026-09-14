import contextlib
import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["ENVIRONMENT"] = "test"
os.environ["LOGIN_MAX_ATTEMPTS"] = "0"  # fixtures log in per-test; throttle covered by test_auth

import pytest
from fastapi.testclient import TestClient

from app.db import (
    Base,
    SessionLocal,
    engine,
)
from app.main import app
from app.seed import seed


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    yield
    Base.metadata.drop_all(bind=engine)
    with contextlib.suppress(OSError):
        os.remove("test.db")


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def admin_headers(client):
    r = client.post("/api/v1/auth/login", json={
        "email": "admin@prosperya.it",
        "password": "prosperya-admin-dev",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def consultant_headers(client):
    r = client.post("/api/v1/auth/login", json={
        "email": "consulente@prosperya.it",
        "password": "prosperya-demo-dev",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
