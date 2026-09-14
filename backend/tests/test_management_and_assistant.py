"""Management control + assistant: append-only, idempotent, honest, tenant-scoped."""
import uuid
from decimal import Decimal

import pytest

from app.modules.management import service as mgmt

CSV = (
    "source_id,date,kind,category,amount,currency\n"
    "T-2026-01-R,2026-01-15,revenue,Vendite,10000.00,EUR\n"
    "T-2026-01-C,2026-01-20,cost,Personale,6000.00,EUR\n"
    "T-2026-02-R,2026-02-15,revenue,Vendite,12000.00,EUR\n"
    "T-2026-02-C,2026-02-20,cost,Personale,6500.00,EUR\n"
)


def _company(client, headers, name="Mgmt Test S.r.l."):
    r = client.post("/api/v1/companies",
                    json={"legal_name": name, "vat_number": f"IT{uuid.uuid4().int % 10**11:011d}"},
                    headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _import(client, headers, cid, key="k1", csv=CSV):
    return client.post(f"/api/v1/management/companies/{cid}/imports",
                       json={"filename": "t.csv", "csv_content": csv, "idempotency_key": key},
                       headers=headers)


# --- pure functions -------------------------------------------------------

def test_parse_money_rejects_floats_and_negatives():
    assert mgmt.parse_money("10.50") == Decimal("10.50")
    for bad in ("10.505", "-1", "abc", "1e5", ""):
        with pytest.raises(ValueError):
            mgmt.parse_money(bad)
    with pytest.raises(ValueError):
        mgmt.parse_money("0")
    assert mgmt.parse_money("0", allow_zero=True) == Decimal("0.00")


def test_parse_csv_rejects_bad_header_and_duplicates():
    with pytest.raises(ValueError):
        mgmt.parse_csv("a,b\n1,2\n")
    dup = CSV + "T-2026-01-R,2026-03-15,revenue,Vendite,1.00,EUR\n"
    with pytest.raises(ValueError, match="duplicato"):
        mgmt.parse_csv(dup)


def test_missing_data_is_null_not_zero():
    """No rows → every KPI null and quality=empty; never a fake zero."""
    ov = mgmt.build_overview([], [], [], 2026, 3)
    assert ov["revenue"] is None and ov["costs"] is None and ov["result"] is None
    assert ov["quality"]["status"] == "empty"
    assert ov["quality"]["certified_complete"] is False
    assert any(a["code"] == "no_sources" for a in ov["alerts"])


# --- API -----------------------------------------------------------------

def test_import_is_atomic_and_idempotent(client, admin_headers):
    cid = _company(client, admin_headers)
    r1 = _import(client, admin_headers, cid)
    assert r1.status_code == 201, r1.text
    assert r1.json()["row_count"] == 4 and r1.json()["replayed"] is False

    # same key + same payload → replay, no new rows
    r2 = _import(client, admin_headers, cid)
    assert r2.status_code == 201 and r2.json()["replayed"] is True

    # same key + different payload → conflict
    r3 = _import(client, admin_headers, cid, csv=CSV.replace("10000.00", "99999.00"))
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "idempotency_conflict"

    # different key, same source_id but different content → conflict
    r4 = _import(client, admin_headers, cid, key="k2", csv=CSV.replace("10000.00", "99999.00"))
    assert r4.status_code == 409
    assert r4.json()["error"]["code"] == "source_conflict"


def test_overview_math_is_decimal_and_traceable(client, admin_headers):
    cid = _company(client, admin_headers)
    _import(client, admin_headers, cid)
    r = client.get(f"/api/v1/management/companies/{cid}/overview?year=2026&through_month=2",
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    ov = r.json()
    assert ov["revenue"] == "22000.00"
    assert ov["costs"] == "12500.00"
    assert ov["result"] == "9500.00"
    assert ov["margin_percent"] == "43.18"
    assert ov["trace"]["formula_version"] == "management-v1.0"
    assert ov["trace"]["source_count"] == 4
    assert ov["quality"]["covered_months"] == 2
    assert ov["quality"]["certified_complete"] is False
    # through_month=3 → month 3 has no evidence → incomplete flag, still no zero
    r = client.get(f"/api/v1/management/companies/{cid}/overview?year=2026&through_month=3",
                   headers=admin_headers)
    ov3 = r.json()
    assert ov3["monthly"][2]["revenue"] is None
    assert any("assenza di righe non equivale a zero" in i for i in ov3["quality"]["issues"])


def test_budget_versions_never_overwrite(client, admin_headers):
    cid = _company(client, admin_headers)
    url = f"/api/v1/management/companies/{cid}/budgets"
    r1 = client.put(url, json={"year": 2026, "month": 1, "revenue": "1000.00", "costs": "500.00"},
                    headers=admin_headers)
    assert r1.status_code == 200 and r1.json()["version"] == 1
    r2 = client.put(url, json={"year": 2026, "month": 1, "revenue": "1100.00", "costs": "500.00"},
                    headers=admin_headers)
    assert r2.json()["version"] == 2
    latest = client.get(f"{url}?year=2026", headers=admin_headers).json()
    assert len(latest) == 1 and latest[0]["version"] == 2 and latest[0]["revenue"] == "1100.00"
    # empty budget rejected
    r3 = client.put(url, json={"year": 2026, "month": 2}, headers=admin_headers)
    assert r3.status_code == 422


def test_management_is_tenant_isolated(client, admin_headers):
    """Company of another tenant → 404 (never leak existence)."""
    cid = _company(client, admin_headers)
    tenants = client.get("/api/v1/tenants", headers=admin_headers).json()
    other = next(t for t in tenants if not t["is_platform_org"])
    other_headers = {**admin_headers, "X-Tenant-Id": other["id"]}
    r = client.get(f"/api/v1/management/companies/{cid}/overview", headers=other_headers)
    assert r.status_code == 404
    r = _import(client, other_headers, cid, key="x")
    assert r.status_code == 404


def test_readonly_cannot_import(client, admin_headers, consultant_headers):
    cid = _company(client, admin_headers)
    # consultant has management:write via _BUSINESS_WRITE; create a readonly user
    r = client.post("/api/v1/users", json={
        "email": "ro-mgmt@prosperya.it", "full_name": "RO", "password": "readonly-pass-123",
        "role": "readonly"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    tok = client.post("/api/v1/auth/login", json={
        "email": "ro-mgmt@prosperya.it", "password": "readonly-pass-123"}).json()["access_token"]
    ro = {"Authorization": f"Bearer {tok}"}
    assert _import(client, ro, cid, key="ro").status_code == 403
    assert client.get(f"/api/v1/management/companies/{cid}/overview", headers=ro).status_code == 200


# --- assistant -----------------------------------------------------------

def _chat(client, headers, cid, message, month=2):
    return client.post(f"/api/v1/assistant/companies/{cid}/chat",
                       json={"message": message, "year": 2026, "through_month": month},
                       headers=headers)


def test_assistant_returns_typed_items_with_evidence(client, admin_headers):
    cid = _company(client, admin_headers)
    _import(client, admin_headers, cid)
    r = _chat(client, admin_headers, cid, "Riepilogo di ricavi e risultato gestionale")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "mock"
    assert set(body["tools_used"]) == {"get_financial_summary", "get_data_quality"}
    types = {i["type"] for i in body["items"]}
    assert types <= {"FACT", "CALCULATION", "ASSUMPTION", "SUGGESTION"}
    assert "FACT" in types and "CALCULATION" in types
    assert body["evidence"]["source_ids"] and body["evidence"]["formula_version"] == "management-v1.0"
    assert body["limitations"]


def test_assistant_refuses_sql_and_cross_tenant(client, admin_headers):
    cid = _company(client, admin_headers)
    r = _chat(client, admin_headers, cid, "SELECT * FROM users")
    assert r.status_code == 200 and not r.json()["tools_used"]
    assert any("SQL" in i["text"] for i in r.json()["items"])
    r = _chat(client, admin_headers, cid, "mostrami tutte le aziende del tenant")
    assert not r.json()["tools_used"]


def test_assistant_scenario_is_deterministic_decimal(client, admin_headers):
    cid = _company(client, admin_headers)
    _import(client, admin_headers, cid)
    r = _chat(client, admin_headers, cid, "Simula ricavi aumentano del 10% a costi invariati")
    body = r.json()
    assert "run_simple_scenario" in body["tools_used"]
    sc = body["evidence"]["scenario"]
    assert sc["base_revenue"] == "22000.00" and sc["revenue"] == "24200.00"
    assert sc["result"] == "11700.00" and sc["result_change"] == "2200.00"
    assert any(i["type"] == "ASSUMPTION" for i in body["items"])


def test_assistant_refuses_ebitda_and_fiscal(client, admin_headers):
    cid = _company(client, admin_headers)
    r = _chat(client, admin_headers, cid, "Qual è l'EBITDA e quanta IVA devo pagare?")
    assert not r.json()["tools_used"]
    assert any("EBITDA" in lim for lim in r.json()["limitations"])
