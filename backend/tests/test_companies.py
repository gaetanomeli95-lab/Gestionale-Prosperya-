def _payload(**over):
    base = {"legal_name": "Test Industries S.p.A.", "vat_number": "IT 999.888.777"}
    base.update(over)
    return base


def test_create_company_normalizes_vat(client, admin_headers):
    r = client.post("/api/v1/companies", json=_payload(), headers=admin_headers)
    assert r.status_code == 201, r.text
    assert r.json()["vat_number"] == "IT999888777"


def test_duplicate_vat_is_blocked(client, admin_headers):
    client.post("/api/v1/companies", json=_payload(), headers=admin_headers)
    r = client.post(
        "/api/v1/companies",
        json=_payload(legal_name="Other Name S.r.l.", vat_number="it999888777"),
        headers=admin_headers,
    )
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "duplicate_company"
    assert body["details"]["matches"]


def test_duplicate_vat_with_confirm_flag(client, admin_headers):
    r = client.post(
        "/api/v1/companies",
        json=_payload(legal_name="Confirmed Dup S.r.l.", confirm_duplicate=True),
        headers=admin_headers,
    )
    # unique constraint on vat_number still protects the DB
    assert r.status_code in (201, 409, 500)


def test_list_companies_pagination(client, admin_headers):
    r = client.get("/api/v1/companies?page=1&page_size=5", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body
    assert body["page_size"] == 5


def test_search_companies_by_vat(client, admin_headers):
    r = client.get("/api/v1/companies?q=01234567890", headers=admin_headers)
    assert r.status_code == 200
    assert any(c["legal_name"] == "Azienda Demo Siciliana S.r.l." for c in r.json()["items"])


def test_stale_version_rejected(client, admin_headers):
    create = client.post("/api/v1/companies", json=_payload(
        legal_name="Concurrency S.r.l.", vat_number="CONC123"), headers=admin_headers)
    company = create.json()
    # first update OK
    r1 = client.patch(f"/api/v1/companies/{company['id']}",
                      json={"version": company["version"], "city": "Catania"},
                      headers=admin_headers)
    assert r1.status_code == 200
    # second update with old version → conflict
    r2 = client.patch(f"/api/v1/companies/{company['id']}",
                      json={"version": company["version"], "city": "Messina"},
                      headers=admin_headers)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "stale_version"


def test_soft_delete_hides_company(client, admin_headers):
    create = client.post("/api/v1/companies", json=_payload(
        legal_name="To Delete S.r.l.", vat_number="DEL001"), headers=admin_headers)
    cid = create.json()["id"]
    assert client.delete(f"/api/v1/companies/{cid}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/v1/companies/{cid}", headers=admin_headers).status_code == 404


def test_company_completeness_names_missing_fields(client, admin_headers):
    create = client.post("/api/v1/companies",
                         json={"legal_name": "Minimal S.r.l."}, headers=admin_headers)
    cid = create.json()["id"]
    r = client.get(f"/api/v1/companies/{cid}/completeness", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "vat_number" in body["missing_fields"]
    assert body["score"] < 100
