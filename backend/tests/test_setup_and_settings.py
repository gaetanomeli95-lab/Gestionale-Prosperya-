"""First-run setup, tenant provisioning, password change."""
import uuid


def test_setup_closed_when_users_exist(client):
    assert client.get("/api/v1/setup/status").json() == {"needs_setup": False}
    r = client.post("/api/v1/setup", json={
        "company_name": "Xyz S.r.l.", "admin_name": "A", "admin_email": "admin@example.com",
        "admin_password": "0123456789ab"})
    assert r.status_code == 409


def test_new_tenant_is_provisioned_with_defaults(client, admin_headers):
    slug = f"t-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/v1/tenants", json={"slug": slug, "display_name": "Nuovo Cliente S.r.l."},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    h = {**admin_headers, "X-Tenant-Id": r.json()["id"]}
    stages = client.get("/api/v1/service-lines/pipeline-stages", headers=h).json()
    assert len(stages) >= 4 and any(s["is_won"] for s in stages) and any(s["is_lost"] for s in stages)
    assert client.get("/api/v1/service-lines", headers=h).json()
    # lead conversion works out of the box
    lead = client.post("/api/v1/leads", headers=h, json={
        "company_name": "Prospect", "contact_name": "Anna Verdi", "source": "website"}).json()
    r = client.post(f"/api/v1/leads/{lead['id']}/convert", headers=h, json={"create_opportunity": True})
    assert r.status_code == 200, r.text


def test_change_password_flow(client, admin_headers):
    email = f"pw-{uuid.uuid4().hex[:6]}@prosperya.it"
    r = client.post("/api/v1/users", headers=admin_headers, json={
        "email": email, "full_name": "PW", "password": "old-password-1", "role": "consultant"})
    assert r.status_code == 201, r.text
    def login(pwd):
        return client.post("/api/v1/auth/login", json={"email": email, "password": pwd})

    h = {"Authorization": f"Bearer {login('old-password-1').json()['access_token']}"}
    r = client.post("/api/v1/auth/change-password", headers=h, json={
        "current_password": "wrong-password", "new_password": "new-password-12"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/change-password", headers=h, json={
        "current_password": "old-password-1", "new_password": "new-password-12"})
    assert r.status_code == 204
    assert login("old-password-1").status_code == 401
    assert login("new-password-12").status_code == 200


def test_client_admin_manages_only_own_tenant_users(client, admin_headers):
    tok = client.post("/api/v1/auth/login", json={
        "email": "cliente@demo.example", "password": "prosperya-client-dev"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    # can create a colleague in own tenant
    r = client.post("/api/v1/users", headers=h, json={
        "email": f"c-{uuid.uuid4().hex[:6]}@demo.example", "full_name": "Collega",
        "password": "collega-pass-1", "role": "client_operator", "tenant_id": me["tenant_id"]})
    assert r.status_code == 201, r.text
    # cannot assign staff roles
    r = client.post("/api/v1/users", headers=h, json={
        "email": f"s-{uuid.uuid4().hex[:6]}@demo.example", "full_name": "Sneaky",
        "password": "sneaky-pass-12", "role": "admin", "tenant_id": me["tenant_id"]})
    assert r.status_code in (403, 422)
    # only sees own tenant's users
    users = client.get("/api/v1/users?page_size=200", headers=h).json()["items"]
    assert all(u["tenant_id"] == me["tenant_id"] for u in users)
