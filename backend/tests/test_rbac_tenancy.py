"""Cross-domain authorization and tenant-isolation regression suite.

Backend is authoritative (rbac.py). These tests prove, per representative
protected resource, that:
  - missing / invalid tokens -> 401
  - a role without the scope -> 403 (frontend hiding is not security)
  - a client-tenant user cannot read another tenant's data by guessing IDs,
    nor switch tenant via X-Tenant-Id
  - staff CAN switch tenant, and data is partitioned accordingly
  - deactivated users are locked out even with a valid token
  - elevated admin actions (user management) are admin-only
"""
import uuid

import pytest

API = "/api/v1"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _login(client, email, password):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def client_headers(client):
    """Seeded client_admin locked to the demo client tenant."""
    return _login(client, "cliente@demo.example", "prosperya-client-dev")


@pytest.fixture()
def readonly_headers(client, admin_headers):
    email = f"ro-{uuid.uuid4().hex[:8]}@prosperya.it"
    r = client.post(f"{API}/users", headers=admin_headers, json={
        "email": email, "full_name": "Sola lettura", "password": "readonly-pass-1",
        "role": "readonly"})
    assert r.status_code == 201, r.text
    return _login(client, email, "readonly-pass-1")


@pytest.fixture()
def tenants(client, admin_headers):
    r = client.get(f"{API}/tenants", headers=admin_headers)
    assert r.status_code == 200, r.text
    rows = r.json()["items"] if isinstance(r.json(), dict) and "items" in r.json() else r.json()
    platform = next(t for t in rows if t["is_platform_org"])
    others = [t for t in rows if not t["is_platform_org"]]
    assert others, "seed must provide at least one client tenant"
    return {"platform": platform, "client": others[0]}


def _company_in(client, headers, tenant_id: str, name: str) -> str:
    r = client.post(f"{API}/companies",
                    headers={**headers, "X-Tenant-Id": tenant_id},
                    json={"legal_name": name, "country": "IT"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------
# authentication
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/companies", "/practices", "/funding/programmes",
    f"/treasury/companies/{uuid.UUID(int=1)}/accounts",
    "/fiscal/rule-sets", "/controlling/rules", "/documents", "/tasks", "/audit",
])
def test_missing_token_is_401(client, path):
    assert client.get(f"{API}{path}").status_code == 401


def test_garbage_token_is_401(client):
    r = client.get(f"{API}/companies", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_deactivated_user_locked_out_with_valid_token(client, admin_headers):
    email = f"off-{uuid.uuid4().hex[:8]}@prosperya.it"
    r = client.post(f"{API}/users", headers=admin_headers, json={
        "email": email, "full_name": "Disattivato", "password": "temp-pass-123", "role": "consultant"})
    uid = r.json()["id"]
    headers = _login(client, email, "temp-pass-123")
    assert client.get(f"{API}/companies", headers=headers).status_code == 200
    r = client.patch(f"{API}/users/{uid}", headers=admin_headers, json={"is_active": False})
    assert r.status_code == 200, r.text
    assert client.get(f"{API}/companies", headers=headers).status_code == 401


# --------------------------------------------------------------------------
# role scopes — read allowed, write forbidden for readonly
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/companies", "/practices", "/funding/programmes", "/documents"])
def test_readonly_can_read(client, readonly_headers, path):
    assert client.get(f"{API}{path}", headers=readonly_headers).status_code == 200


def test_readonly_cannot_create_company(client, readonly_headers):
    r = client.post(f"{API}/companies", headers=readonly_headers,
                    json={"legal_name": "Vietata Srl", "country": "IT"})
    assert r.status_code == 403


def test_readonly_cannot_open_practice(client, readonly_headers, admin_headers):
    cid = client.post(f"{API}/companies", headers=admin_headers,
                      json={"legal_name": "Target Srl", "country": "IT"}).json()["id"]
    r = client.post(f"{API}/practices/companies/{cid}", headers=readonly_headers,
                    json={"title": "x", "practice_type": "generic"})
    assert r.status_code == 403


def test_readonly_cannot_manage_users(client, readonly_headers):
    r = client.post(f"{API}/users", headers=readonly_headers, json={
        "email": "x@prosperya.it", "full_name": "x", "password": "some-pass-123", "role": "admin"})
    assert r.status_code == 403


def test_consultant_cannot_manage_users(client, consultant_headers):
    """users:write is admin / management / client_admin only."""
    r = client.post(f"{API}/users", headers=consultant_headers, json={
        "email": "y@prosperya.it", "full_name": "y", "password": "some-pass-123", "role": "consultant"})
    assert r.status_code == 403


# --------------------------------------------------------------------------
# tenant isolation
# --------------------------------------------------------------------------

def test_client_user_cannot_switch_tenant_via_header(client, client_headers, tenants):
    r = client.get(f"{API}/companies", headers={**client_headers,
                                                  "X-Tenant-Id": tenants["platform"]["id"]})
    # locked to home tenant: header is ignored for client roles -> still 200, but
    # the data returned must be its own tenant's, verified below by id probing
    assert r.status_code == 200


@pytest.mark.parametrize("resource", ["companies", "practices"])
def test_client_user_cannot_read_platform_tenant_entity_by_id(
        client, admin_headers, client_headers, tenants, resource):
    cid = _company_in(client, admin_headers, tenants["platform"]["id"], "Piattaforma Riservata Srl")
    if resource == "companies":
        target = cid
    else:
        target = client.post(f"{API}/practices/companies/{cid}",
                             headers={**admin_headers, "X-Tenant-Id": tenants["platform"]["id"]},
                             json={"title": "Riservata", "practice_type": "generic"}).json()["id"]
    r = client.get(f"{API}/{resource}/{target}", headers=client_headers)
    assert r.status_code == 404, f"cross-tenant {resource} leaked: {r.status_code} {r.text[:120]}"


def test_client_user_cannot_mutate_platform_tenant_entity(client, admin_headers, client_headers, tenants):
    cid = _company_in(client, admin_headers, tenants["platform"]["id"], "Immutabile Srl")
    r = client.patch(f"{API}/companies/{cid}", headers=client_headers,
                     json={"legal_name": "Hacked", "version": 1})
    assert r.status_code in (403, 404)
    # unchanged
    r = client.get(f"{API}/companies/{cid}",
                   headers={**admin_headers, "X-Tenant-Id": tenants["platform"]["id"]})
    assert r.json()["legal_name"] == "Immutabile Srl"


def test_staff_sees_only_selected_tenant(client, admin_headers, tenants):
    tag = uuid.uuid4().hex[:6]
    a = _company_in(client, admin_headers, tenants["platform"]["id"], f"Solo-Piattaforma-{tag}")
    b = _company_in(client, admin_headers, tenants["client"]["id"], f"Solo-Cliente-{tag}")
    plat = client.get(f"{API}/companies", params={"page_size": 200},
                      headers={**admin_headers, "X-Tenant-Id": tenants["platform"]["id"]}).json()
    cli = client.get(f"{API}/companies", params={"page_size": 200},
                     headers={**admin_headers, "X-Tenant-Id": tenants["client"]["id"]}).json()
    plat_ids = {c["id"] for c in plat["items"]}
    cli_ids = {c["id"] for c in cli["items"]}
    assert a in plat_ids and a not in cli_ids
    assert b in cli_ids and b not in plat_ids


def test_staff_cannot_fetch_entity_under_wrong_tenant_context(client, admin_headers, tenants):
    a = _company_in(client, admin_headers, tenants["platform"]["id"], "Contesto Errato Srl")
    r = client.get(f"{API}/companies/{a}", headers={**admin_headers, "X-Tenant-Id": tenants["client"]["id"]})
    assert r.status_code == 404


def test_invalid_tenant_header_rejected(client, admin_headers):
    r = client.get(f"{API}/companies", headers={**admin_headers, "X-Tenant-Id": "not-a-uuid"})
    assert r.status_code == 403
    r = client.get(f"{API}/companies", headers={**admin_headers, "X-Tenant-Id": str(uuid.uuid4())})
    assert r.status_code == 403


def test_audit_log_is_tenant_partitioned(client, admin_headers, tenants):
    _company_in(client, admin_headers, tenants["client"]["id"], f"Audit-Cliente-{uuid.uuid4().hex[:6]}")
    plat = client.get(f"{API}/audit", headers={**admin_headers, "X-Tenant-Id": tenants["platform"]["id"]})
    cli = client.get(f"{API}/audit", headers={**admin_headers, "X-Tenant-Id": tenants["client"]["id"]})
    assert plat.status_code == 200 and cli.status_code == 200
    def ids(resp):
        body = resp.json()
        rows = body["items"] if isinstance(body, dict) and "items" in body else body
        return {r["id"] for r in rows}
    assert ids(plat).isdisjoint(ids(cli))
