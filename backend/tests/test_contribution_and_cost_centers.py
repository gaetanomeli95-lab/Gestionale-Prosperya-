"""Contribution margin, break-even and cost-centre classification.

The properties under test are the honest ones: the engine refuses to split
costs it was not told how to classify, break-even is `not_calculable` with a
reason instead of a comfortable number, the Decimal arithmetic is exact, and
reclassifying reference data never rewrites the append-only consuntivi.
"""
import uuid
from decimal import Decimal

API = "/api/v1"
YEAR, MONTH = 2026, 6


def _company(client, admin_headers, vat: str) -> str:
    page = client.get(f"{API}/companies?page=1&page_size=200", headers=admin_headers).json()
    return next(c["id"] for c in page["items"] if c["vat_number"] == vat)


def _fresh_company(client, admin_headers) -> str:
    r = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Contribuzione {uuid.uuid4().hex[:6]} S.r.l.", "status": "customer"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _import(client, admin_headers, company_id: str, rows: list[tuple[str, str, str, str]],
            key: str) -> None:
    csv = "source_id,date,kind,category,amount,currency\n" + "".join(
        f"{sid},{date},{kind_category[0]},{kind_category[1]},{amount},EUR\n"
        for sid, date, kind_category, amount in rows)
    r = client.post(f"{API}/management/companies/{company_id}/imports",
                    headers=admin_headers, json={
                        "filename": f"{key}.csv", "csv_content": csv,
                        "idempotency_key": key})
    assert r.status_code == 201, r.text


def _contribution(client, headers, company_id: str) -> dict:
    r = client.get(
        f"{API}/management/companies/{company_id}/contribution?year={YEAR}&through_month={MONTH}",
        headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _categories(client, headers, company_id: str) -> dict:
    r = client.get(f"{API}/management/companies/{company_id}/categories", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_seeded_demo_has_calculable_break_even(client, admin_headers):
    company = _company(client, admin_headers, "01234567890")
    data = _contribution(client, admin_headers, company)
    assert data["status"] == "available"
    assert data["quality"]["classification_complete"] is True

    revenue = Decimal(data["revenue"])
    variable = Decimal(data["variable_costs"])
    fixed = Decimal(data["fixed_costs"])
    contribution = Decimal(data["contribution_margin"])
    assert contribution == revenue - variable, "margine = ricavi - costi variabili"

    ratio = Decimal(data["contribution_margin_ratio"])
    assert ratio == (contribution / revenue).quantize(Decimal("0.0001"))
    assert data["break_even_status"] == "available"
    assert Decimal(data["break_even_revenue"]) == (fixed / ratio).quantize(Decimal("0.01"))
    assert data["trace"]["formula_version"] == "contribution-v1.0"
    assert data["trace"]["formulas"]["break_even_revenue"]

    # cost centres are attributed, and revenue is not silently double-counted
    names = {c["name"] for c in data["cost_centers"]}
    assert "Produzione e delivery (demo)" in names
    assert "Struttura e amministrazione (demo)" in names
    total_center_costs = sum(Decimal(c["costs"]) for c in data["cost_centers"]
                             if c["costs"] is not None)
    assert total_center_costs == variable + fixed


def test_unclassified_costs_block_the_split_and_break_even(client, admin_headers):
    company = _fresh_company(client, admin_headers)
    _import(client, admin_headers, company, [
        ("R1", "2026-01-15", ("revenue", "Vendite"), "10000"),
        ("C1", "2026-01-20", ("cost", "Materiali"), "4000"),
        ("C2", "2026-02-01", ("cost", "Affitto"), "1000"),
    ], f"contrib-{uuid.uuid4().hex[:8]}")

    data = _contribution(client, admin_headers, company)
    assert data["status"] == "not_calculable"
    assert data["variable_costs"] is None and data["fixed_costs"] is None
    assert data["contribution_margin"] is None
    assert data["break_even_revenue"] is None
    assert data["break_even_status"] == "not_calculable"
    assert {c["category"] for c in data["unclassified_costs"]} == {"Materiali", "Affitto"}
    assert any("non classificate" in reason for reason in data["reasons"])
    # the revenue itself is still reported: only the split is withheld
    assert data["revenue"] == "10000.00"


def test_classification_enables_exact_break_even(client, admin_headers):
    company = _fresh_company(client, admin_headers)
    _import(client, admin_headers, company, [
        ("R1", "2026-01-15", ("revenue", "Vendite"), "10000"),
        ("C1", "2026-01-20", ("cost", "Materiali"), "4000"),
        ("C2", "2026-02-01", ("cost", "Affitto"), "1200"),
    ], f"contrib-{uuid.uuid4().hex[:8]}")

    center = client.post(f"{API}/management/companies/{company}/cost-centers",
                         headers=admin_headers,
                         json={"code": "CDC-1", "name": "Produzione"})
    assert center.status_code == 201, center.text
    duplicate = client.post(f"{API}/management/companies/{company}/cost-centers",
                            headers=admin_headers,
                            json={"code": "CDC-1", "name": "Doppione"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "cost_center_exists"

    by_name = {c["name"]: c for c in _categories(client, admin_headers, company)["categories"]}
    for name, nature in (("Materiali", "variable"), ("Affitto", "fixed")):
        r = client.patch(
            f"{API}/management/companies/{company}/categories/{by_name[name]['id']}",
            headers=admin_headers,
            json={"cost_nature": nature, "cost_center_id": center.json()["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["cost_nature"] == nature
        assert r.json()["cost_center_code"] == "CDC-1"

    data = _contribution(client, admin_headers, company)
    assert data["status"] == "available"
    assert data["variable_costs"] == "4000.00" and data["fixed_costs"] == "1200.00"
    assert data["contribution_margin"] == "6000.00"
    assert data["contribution_margin_percent"] == "60.00"
    assert data["contribution_margin_ratio"] == "0.6000"
    # 1200 / 0.6 = 2000.00 exactly
    assert data["break_even_revenue"] == "2000.00"
    assert Decimal(data["break_even_coverage"]) == Decimal("5.0000")
    assert data["alerts"] == [], "pareggio superato: nessun alert"


def test_break_even_alert_when_coverage_below_one(client, admin_headers):
    company = _fresh_company(client, admin_headers)
    _import(client, admin_headers, company, [
        ("R1", "2026-01-15", ("revenue", "Vendite"), "10000"),
        ("C1", "2026-01-20", ("cost", "Materiali"), "8000"),
        ("C2", "2026-02-01", ("cost", "Affitto"), "5000"),
    ], f"contrib-{uuid.uuid4().hex[:8]}")
    by_name = {c["name"]: c for c in _categories(client, admin_headers, company)["categories"]}
    for name, nature in (("Materiali", "variable"), ("Affitto", "fixed")):
        client.patch(f"{API}/management/companies/{company}/categories/{by_name[name]['id']}",
                     headers=admin_headers, json={"cost_nature": nature})

    data = _contribution(client, admin_headers, company)
    # CM = 2000 su 10000 -> ratio 0.2 -> break-even 25000 > ricavi 10000
    assert data["break_even_revenue"] == "25000.00"
    assert Decimal(data["break_even_coverage"]) < Decimal("1")
    alert = next(a for a in data["alerts"] if a["code"] == "break_even_not_reached")
    assert alert["severity"] == "warning" and alert["formula"]

    cockpit = client.get(f"{API}/cockpit/companies/{company}?year={YEAR}&through_month={MONTH}",
                         headers=admin_headers).json()
    assert any(a["code"] == "break_even_not_reached" for a in cockpit["actions"])
    assert cockpit["contribution"]["break_even_revenue"] == "25000.00"


def test_negative_contribution_has_no_break_even(client, admin_headers):
    company = _fresh_company(client, admin_headers)
    _import(client, admin_headers, company, [
        ("R1", "2026-01-15", ("revenue", "Vendite"), "1000"),
        ("C1", "2026-01-20", ("cost", "Materiali"), "1500"),
        ("C2", "2026-02-01", ("cost", "Affitto"), "300"),
    ], f"contrib-{uuid.uuid4().hex[:8]}")
    by_name = {c["name"]: c for c in _categories(client, admin_headers, company)["categories"]}
    for name, nature in (("Materiali", "variable"), ("Affitto", "fixed")):
        client.patch(f"{API}/management/companies/{company}/categories/{by_name[name]['id']}",
                     headers=admin_headers, json={"cost_nature": nature})

    data = _contribution(client, admin_headers, company)
    assert data["contribution_margin"] == "-500.00"
    assert data["break_even_revenue"] is None
    assert data["break_even_status"] == "not_calculable"
    assert any("non positivo" in reason for reason in data["reasons"])


def test_classification_rules_and_isolation(client, admin_headers):
    company = _fresh_company(client, admin_headers)
    _import(client, admin_headers, company, [
        ("R1", "2026-01-15", ("revenue", "Vendite"), "1000"),
        ("C1", "2026-01-20", ("cost", "Materiali"), "400"),
    ], f"contrib-{uuid.uuid4().hex[:8]}")
    cats = {c["name"]: c for c in _categories(client, admin_headers, company)["categories"]}

    # a revenue category has no fixed/variable nature
    bad = client.patch(f"{API}/management/companies/{company}/categories/{cats['Vendite']['id']}",
                       headers=admin_headers, json={"cost_nature": "fixed"})
    assert bad.status_code in (400, 422)
    assert bad.json()["error"]["code"] == "nature_on_revenue"

    # invalid nature is refused by schema validation
    assert client.patch(
        f"{API}/management/companies/{company}/categories/{cats['Materiali']['id']}",
        headers=admin_headers, json={"cost_nature": "semi-variable"}).status_code == 422

    # a cost centre of another company cannot be attached
    other = _fresh_company(client, admin_headers)
    foreign = client.post(f"{API}/management/companies/{other}/cost-centers",
                          headers=admin_headers,
                          json={"code": "CDC-X", "name": "Altrove"}).json()
    denied = client.patch(
        f"{API}/management/companies/{company}/categories/{cats['Materiali']['id']}",
        headers=admin_headers,
        json={"cost_nature": "variable", "cost_center_id": foreign["id"]})
    assert denied.status_code in (400, 422)
    assert denied.json()["error"]["code"] == "invalid_cost_center"

    # a category of another company is not reachable (no cross-company leak)
    other_cat = _categories(client, admin_headers, other)
    assert other_cat["categories"] == []
    unknown = client.patch(
        f"{API}/management/companies/{other}/categories/{cats['Materiali']['id']}",
        headers=admin_headers, json={"cost_nature": "variable"})
    assert unknown.status_code == 404


def test_reclassification_is_audited_and_does_not_touch_history(client, admin_headers):
    company = _fresh_company(client, admin_headers)
    _import(client, admin_headers, company, [
        ("R1", "2026-01-15", ("revenue", "Vendite"), "1000"),
        ("C1", "2026-01-20", ("cost", "Materiali"), "400"),
    ], f"contrib-{uuid.uuid4().hex[:8]}")
    cats = {c["name"]: c for c in _categories(client, admin_headers, company)["categories"]}
    before = client.get(f"{API}/management/companies/{company}/actuals?year={YEAR}",
                        headers=admin_headers).json()

    path = f"{API}/management/companies/{company}/categories/{cats['Materiali']['id']}"
    assert client.patch(path, headers=admin_headers,
                        json={"cost_nature": "variable"}).status_code == 200
    assert client.patch(path, headers=admin_headers,
                        json={"cost_nature": "fixed"}).status_code == 200
    # clearing the classification is legitimate and puts the engine back to unknown
    assert client.patch(path, headers=admin_headers, json={}).json()["cost_nature"] is None
    assert _contribution(client, admin_headers, company)["status"] == "not_calculable"

    after = client.get(f"{API}/management/companies/{company}/actuals?year={YEAR}",
                       headers=admin_headers).json()
    assert after["rows"] == before["rows"], "lo storico consuntivi resta immutato"

    audit = client.get(f"{API}/audit?page=1&page_size=50", headers=admin_headers).json()
    actions = [row["action"] for row in audit["items"]]
    assert "management.category.classify" in actions


def test_readonly_cannot_classify(client, admin_headers):
    company = _company(client, admin_headers, "01234567890")
    email = f"ro-cls-{uuid.uuid4().hex[:6]}@prosperya.it"
    client.post(f"{API}/users", headers=admin_headers, json={
        "email": email, "full_name": "Sola lettura", "password": "readonly-pass-1",
        "role": "readonly"})
    token = client.post(f"{API}/auth/login", json={
        "email": email, "password": "readonly-pass-1"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert _contribution(client, headers, company)["status"] == "available"
    category = _categories(client, headers, company)["categories"][0]["id"]
    denied = client.patch(f"{API}/management/companies/{company}/categories/{category}",
                          headers=headers, json={"cost_nature": "fixed"})
    assert denied.status_code == 403
    assert client.post(f"{API}/management/companies/{company}/cost-centers",
                       headers=headers,
                       json={"code": "NO", "name": "Vietato"}).status_code == 403
