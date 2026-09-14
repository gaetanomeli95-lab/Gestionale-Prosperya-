def test_login_success(client):
    r = client.post("/api/v1/auth/login", json={
        "email": "admin@prosperya.it", "password": "prosperya-admin-dev",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["user"]["email"] == "admin@prosperya.it"
    assert body["user"]["role"] == "admin"


def test_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={
        "email": "admin@prosperya.it", "password": "wrong-password",
    })
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_login_throttle_blocks_brute_force(client, monkeypatch):
    from app.config import get_settings
    from app.modules.auth import router as auth_router

    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_attempts", 3)
    auth_router._login_attempts.clear()
    for _ in range(3):
        r = client.post("/api/v1/auth/login", json={
            "email": "brute@prosperya.it", "password": "nope-nope-nope"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={
        "email": "brute@prosperya.it", "password": "nope-nope-nope"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"
    auth_router._login_attempts.clear()


def test_login_unknown_email_same_response_as_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={
        "email": "nobody@prosperya.it", "password": "whatever-password"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_me_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_with_token(client, admin_headers):
    r = client.get("/api/v1/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
