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


def test_me_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_with_token(client, admin_headers):
    r = client.get("/api/v1/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
