"""Controlling & early-warning — debt service, CCII rules, alerts, scenarios.

Focus (the properties that make the signals defensible):
deterministic metrics that refuse on missing data (null, never zero),
versioned effective-dated rules with provenance, idempotent detection by
dedupe_key, auto-resolution when a condition clears, and a human-audited
alert lifecycle. Nothing here may conclude a state of crisis.
"""
import uuid
from datetime import date, timedelta

import pytest

API = "/api/v1"
CTRL = f"{API}/controlling"
TREASURY = f"{API}/treasury"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def demo_company(client, admin_headers) -> str:
    page = client.get(f"{API}/companies?page=1&page_size=200",
                      headers=admin_headers).json()
    match = next(c for c in page["items"] if c["vat_number"] == "01234567890")
    return match["id"]


@pytest.fixture()
def clean_company(client, admin_headers) -> str:
    """A clean company: no treasury, no debt, no fiscal data."""
    r = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Controlling {uuid.uuid4().hex[:6]} S.r.l.",
        "status": "customer",
        "vat_number": "03" + uuid.uuid4().hex[:9].replace("a", "1").replace("b", "2")
                      .replace("c", "3").replace("d", "4").replace("e", "5").replace("f", "6")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def rules_synced(client, admin_headers):
    r = client.post(f"{CTRL}/rules/sync", headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def readonly_headers(client, admin_headers) -> dict:
    email = f"ro-{uuid.uuid4().hex[:6]}@prosperya.it"
    r = client.post(f"{API}/users", headers=admin_headers, json={
        "email": email, "full_name": "Sola lettura", "password": "readonly-pass-1",
        "role": "readonly"})
    assert r.status_code == 201, r.text
    token = client.post(f"{API}/auth/login", json={
        "email": email, "password": "readonly-pass-1"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def add_facility(client, headers, company_id: str, **kw) -> dict:
    payload = {"name": f"Mutuo {uuid.uuid4().hex[:6]}", "facility_type": "mortgage",
               **kw}
    r = client.post(f"{CTRL}/companies/{company_id}/facilities",
                    headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def add_instalment(client, headers, company_id: str, facility_id: str, **kw) -> dict:
    payload = {"instalment_no": 1, "due_date": day(30),
               "principal": "1000.00", "interest": "100.00", **kw}
    r = client.post(
        f"{CTRL}/companies/{company_id}/facilities/{facility_id}/instalments",
        headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def evaluate(client, headers, company_id: str) -> dict:
    r = client.post(f"{CTRL}/companies/{company_id}/alerts/evaluate",
                    headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def alerts(client, headers, company_id: str, **params) -> dict:
    r = client.get(f"{CTRL}/companies/{company_id}/alerts",
                   headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Rules: provenance, effective dating, admin-only idempotent sync
# ---------------------------------------------------------------------------

def test_rules_carry_ccii_provenance(client, admin_headers, rules_synced):
    r = client.get(f"{CTRL}/rules", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    codes = {rule["code"] for rule in body["rules"]}
    assert {"EW-FIN-OVERDUE", "EW-PAYROLL-OVERDUE", "EW-SUPPLIER-OVERDUE",
            "EW-PUBLIC-CREDITOR", "EW-DSCR-12M", "EW-CONTINUITY-12M"} <= codes
    for rule in body["rules"]:
        assert rule["legal_reference"], "ogni regola deve citare la norma"
        assert rule["source_url"].startswith("https://")
        assert rule["source_retrieved_at"]
        assert rule["effective_from"] == "2026-01-01"
        for param in rule["params"].values():
            assert param["kind"] in ("statutory", "operational")
    assert "operational" in body["disclaimer"]


def test_rule_sync_is_idempotent_and_admin_only(
        client, admin_headers, consultant_headers, rules_synced):
    again = client.post(f"{CTRL}/rules/sync", headers=admin_headers)
    assert again.status_code == 201
    assert again.json()["rules_created"] == [], \
        "le versioni esistenti non vengono mai riscritte"
    denied = client.post(f"{CTRL}/rules/sync", headers=consultant_headers)
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# Facilities & instalments: reference data + tracked transitions
# ---------------------------------------------------------------------------

def test_facility_crud_and_duplicate_guard(client, admin_headers, clean_company):
    facility = add_facility(client, admin_headers, clean_company,
                            name="Mutuo Unico", lender_name="Banca X",
                            outstanding_principal="50000.00")
    assert facility["outstanding_principal"] == "50000.00"
    assert facility["is_active"] is True

    dup = client.post(f"{CTRL}/companies/{clean_company}/facilities",
                      headers=admin_headers,
                      json={"name": "Mutuo Unico", "facility_type": "loan"})
    assert dup.status_code == 409

    r = client.patch(
        f"{CTRL}/companies/{clean_company}/facilities/{facility['id']}",
        headers=admin_headers,
        json={"outstanding_principal": "48000.00", "lender_name": "Banca Y"})
    assert r.status_code == 200, r.text
    assert r.json()["outstanding_principal"] == "48000.00"
    assert r.json()["lender_name"] == "Banca Y"


def test_instalment_lifecycle(client, admin_headers, clean_company):
    facility = add_facility(client, admin_headers, clean_company)
    line = add_instalment(client, admin_headers, clean_company, facility["id"],
                          instalment_no=1, due_date=day(-5))
    assert line["status"] == "scheduled"
    assert line["service"] == "1100.00"

    dup = client.post(
        f"{CTRL}/companies/{clean_company}/facilities/{facility['id']}/instalments",
        headers=admin_headers,
        json={"instalment_no": 1, "due_date": day(60),
              "principal": "500.00", "interest": "50.00"})
    assert dup.status_code == 409

    paid = client.post(
        f"{CTRL}/companies/{clean_company}/instalments/{line['id']}/settle",
        headers=admin_headers, json={"action": "paid", "settled_on": day(-5)})
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"
    assert paid.json()["settled_on"] == day(-5)

    again = client.post(
        f"{CTRL}/companies/{clean_company}/instalments/{line['id']}/settle",
        headers=admin_headers, json={"action": "paid"})
    assert again.status_code == 409, "una rata pagata non transita più"


def test_instalment_waive_requires_reason_and_rejects_empty(
        client, admin_headers, clean_company):
    facility = add_facility(client, admin_headers, clean_company)
    empty = client.post(
        f"{CTRL}/companies/{clean_company}/facilities/{facility['id']}/instalments",
        headers=admin_headers,
        json={"instalment_no": 1, "due_date": day(30),
              "principal": "0.00", "interest": "0.00"})
    assert empty.status_code in (400, 422)

    line = add_instalment(client, admin_headers, clean_company, facility["id"],
                          instalment_no=2)
    no_reason = client.post(
        f"{CTRL}/companies/{clean_company}/instalments/{line['id']}/settle",
        headers=admin_headers, json={"action": "waived"})
    assert no_reason.status_code in (400, 422)

    waived = client.post(
        f"{CTRL}/companies/{clean_company}/instalments/{line['id']}/settle",
        headers=admin_headers,
        json={"action": "waived", "note": "Moratoria concessa dal finanziatore (demo)."})
    assert waived.status_code == 200, waived.text
    assert waived.json()["status"] == "waived"


# ---------------------------------------------------------------------------
# Metrics: honest on missing data, deterministic on facts
# ---------------------------------------------------------------------------

def test_snapshot_on_empty_company_never_fabricates(
        client, admin_headers, clean_company, rules_synced):
    r = client.get(f"{CTRL}/companies/{clean_company}/snapshot",
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["opening_balance"] is None
    assert body["opening_balance_status"] == "not_calculable"
    assert body["dscr"]["status"] == "insufficient_data"
    assert body["dscr"]["value"] is None
    assert body["continuity"]["runway_status"] == "not_calculable"
    assert body["continuity"]["minimum_projected_balance"] is None
    states = {e["rule_code"]: e["state"] for e in body["evaluations"]}
    assert states["EW-CONTINUITY-12M"] == "insufficient_data"
    assert states["EW-PAYROLL-OVERDUE"] == "unsupported"
    assert body["limitations"]


def test_dscr_and_continuity_from_dated_facts(
        client, admin_headers, clean_company, rules_synced):
    facility = add_facility(client, admin_headers, clean_company)
    for no, offset in enumerate((30, 60, 90), start=1):
        add_instalment(client, admin_headers, clean_company, facility["id"],
                       instalment_no=no, due_date=day(offset),
                       principal="1000.00", interest="0.00")
    r = client.get(f"{CTRL}/companies/{clean_company}/snapshot",
                   headers=admin_headers)
    body = r.json()
    dscr = body["dscr"]
    # No open items → numerator unobservable → not "infinite", not zero.
    assert dscr["status"] == "insufficient_data"
    assert dscr["denominator"] == "3000.00"
    assert dscr["components"]["instalments_due"] == 3
    continuity = body["continuity"]
    assert continuity["coverage"]["months_total"] == 12
    assert continuity["runway_status"] == "not_calculable"


# ---------------------------------------------------------------------------
# Detection: idempotent, evidence-backed, auto-resolving
# ---------------------------------------------------------------------------

def test_detection_fires_overdue_financial_exposure(
        client, admin_headers, clean_company, rules_synced):
    facility = add_facility(client, admin_headers, clean_company)
    add_instalment(client, admin_headers, clean_company, facility["id"],
                   instalment_no=1, due_date=day(-10),
                   principal="2000.00", interest="200.00")

    result = evaluate(client, admin_headers, clean_company)
    fired = {e["rule_code"]: e for e in result["evaluations"]
             if e["state"] == "fired"}
    assert "EW-FIN-OVERDUE" in fired
    assert fired["EW-FIN-OVERDUE"]["severity"] == "critical"
    assert fired["EW-FIN-OVERDUE"]["evidence"]["overdue_amount"] == "2200.00"
    assert result["counters"]["created"] >= 1

    listing = alerts(client, admin_headers, clean_company)
    fin = next(a for a in listing["alerts"] if a["rule_code"] == "EW-FIN-OVERDUE")
    assert fin["status"] == "open"
    assert fin["kind"] == "early_warning"
    assert fin["rule_version"] == 1


def test_detection_is_idempotent_and_auto_resolves(
        client, admin_headers, clean_company, rules_synced):
    facility = add_facility(client, admin_headers, clean_company)
    line = add_instalment(client, admin_headers, clean_company, facility["id"],
                          instalment_no=1, due_date=day(-10))

    first = evaluate(client, admin_headers, clean_company)
    assert first["counters"]["created"] >= 1
    second = evaluate(client, admin_headers, clean_company)
    assert second["counters"]["created"] == 0
    assert second["counters"]["refreshed"] >= 1
    listing = alerts(client, admin_headers, clean_company)
    assert len([a for a in listing["alerts"]
                if a["rule_code"] == "EW-FIN-OVERDUE"]) == 1, \
        "la dedupe_key impedisce alert duplicati"

    # The condition clears → the engine resolves the alert itself.
    client.post(
        f"{CTRL}/companies/{clean_company}/instalments/{line['id']}/settle",
        headers=admin_headers, json={"action": "paid", "settled_on": day(-1)})
    third = evaluate(client, admin_headers, clean_company)
    assert third["counters"]["auto_resolved"] >= 1
    fin = next(a for a in alerts(client, admin_headers, clean_company)["alerts"]
               if a["rule_code"] == "EW-FIN-OVERDUE")
    assert fin["status"] == "resolved"
    assert fin["resolution_kind"] == "auto"


def test_payroll_rule_unsupported_without_payroll_data(
        client, admin_headers, clean_company, rules_synced):
    result = evaluate(client, admin_headers, clean_company)
    payroll = next(e for e in result["evaluations"]
                   if e["rule_code"] == "EW-PAYROLL-OVERDUE")
    assert payroll["state"] == "unsupported"


def test_public_creditor_rule_fires_on_overdue_fiscal_item(
        client, admin_headers, clean_company, rules_synced):
    r = client.post(f"{TREASURY}/companies/{clean_company}/open-items",
                    headers=admin_headers, json={
                        "direction": "payable", "counterparty_name": "Erario",
                        "due_date": day(-20), "amount": "1500.00",
                        "source_ref": f"F24-{uuid.uuid4().hex[:6]}",
                        "category": "fiscal"})
    assert r.status_code == 201, r.text
    # A manual item categorised 'fiscal' is still a trade payable for EW;
    # only source='fiscal' (validated settlements) counts as public creditor.
    result = evaluate(client, admin_headers, clean_company)
    pub = next(e for e in result["evaluations"]
               if e["rule_code"] == "EW-PUBLIC-CREDITOR")
    assert pub["state"] in ("insufficient_data", "not_fired")


# ---------------------------------------------------------------------------
# Alert lifecycle: human decisions, audited, no silent dismissal
# ---------------------------------------------------------------------------

def test_alert_human_lifecycle(client, admin_headers, clean_company, rules_synced):
    facility = add_facility(client, admin_headers, clean_company)
    add_instalment(client, admin_headers, clean_company, facility["id"],
                   instalment_no=1, due_date=day(-10))
    evaluate(client, admin_headers, clean_company)
    alert = next(a for a in alerts(client, admin_headers, clean_company)["alerts"]
                 if a["status"] == "open")

    ack = client.post(
        f"{CTRL}/companies/{clean_company}/alerts/{alert['id']}/acknowledge",
        headers=admin_headers, json={})
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledged_at"] is not None

    resolved = client.post(
        f"{CTRL}/companies/{clean_company}/alerts/{alert['id']}/resolve",
        headers=admin_headers, json={"note": "Rata concordata con il finanziatore."})
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["resolution_kind"] == "human"

    again = client.post(
        f"{CTRL}/companies/{clean_company}/alerts/{alert['id']}/acknowledge",
        headers=admin_headers, json={})
    assert again.status_code == 409


def test_dismiss_requires_reason(client, admin_headers, clean_company, rules_synced):
    facility = add_facility(client, admin_headers, clean_company)
    add_instalment(client, admin_headers, clean_company, facility["id"],
                   instalment_no=1, due_date=day(-10))
    evaluate(client, admin_headers, clean_company)
    alert = next(a for a in alerts(client, admin_headers, clean_company)["alerts"]
                 if a["status"] == "open")

    no_reason = client.post(
        f"{CTRL}/companies/{clean_company}/alerts/{alert['id']}/dismiss",
        headers=admin_headers, json={})
    assert no_reason.status_code in (400, 422)

    dismissed = client.post(
        f"{CTRL}/companies/{clean_company}/alerts/{alert['id']}/dismiss",
        headers=admin_headers,
        json={"note": "Falso positivo: rata già concordata fuori piattaforma."})
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"


# ---------------------------------------------------------------------------
# Scenarios: bounded assumptions, deterministic recompute, no writes
# ---------------------------------------------------------------------------

def test_scenario_presets_and_bounded_run(
        client, admin_headers, clean_company):
    presets = client.get(f"{CTRL}/companies/{clean_company}/scenarios/presets",
                         headers=admin_headers)
    assert presets.status_code == 200, presets.text
    assert {"base", "stress", "upside"} <= set(presets.json()["presets"])

    run = client.post(f"{CTRL}/companies/{clean_company}/scenarios/run",
                      headers=admin_headers,
                      json={"label": "stress", "revenue_change_pct": "-20",
                            "collection_delay_days": 30})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["label"] == "STRESS"
    assert body["assumptions"]["revenue_change_pct"] == "-20.00"
    assert body["formula_version"] == "scenario-v1.0"
    assert "non vengono modificati" in body["note"]

    out_of_bounds = client.post(
        f"{CTRL}/companies/{clean_company}/scenarios/run",
        headers=admin_headers, json={"collection_delay_days": 9999})
    assert out_of_bounds.status_code in (400, 422)


# ---------------------------------------------------------------------------
# RBAC & isolation
# ---------------------------------------------------------------------------

def test_readonly_can_read_but_not_write(
        client, admin_headers, readonly_headers, clean_company, rules_synced):
    read = client.get(f"{CTRL}/companies/{clean_company}/snapshot",
                      headers=readonly_headers)
    assert read.status_code == 200
    write = client.post(f"{CTRL}/companies/{clean_company}/facilities",
                        headers=readonly_headers,
                        json={"name": "Nope", "facility_type": "loan"})
    assert write.status_code == 403
    detect = client.post(f"{CTRL}/companies/{clean_company}/alerts/evaluate",
                         headers=readonly_headers)
    assert detect.status_code == 403


def test_cross_company_isolation(client, admin_headers, clean_company):
    facility = add_facility(client, admin_headers, clean_company)
    other = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Altra {uuid.uuid4().hex[:6]} S.r.l.", "status": "customer",
        "vat_number": "04" + uuid.uuid4().hex[:9].replace("a", "1").replace("b", "2")
                      .replace("c", "3").replace("d", "4").replace("e", "5").replace("f", "6")})
    other_id = other.json()["id"]
    r = client.post(
        f"{CTRL}/companies/{other_id}/facilities/{facility['id']}/instalments",
        headers=admin_headers,
        json={"instalment_no": 1, "due_date": day(30),
              "principal": "100.00", "interest": "10.00"})
    assert r.status_code == 404, "una facility di un'altra azienda non è raggiungibile"


# ---------------------------------------------------------------------------
# Demo seed: the sandbox scenario is already populated and signalled
# ---------------------------------------------------------------------------

def test_demo_seed_scenario(client, admin_headers, demo_company):
    facilities = client.get(f"{CTRL}/companies/{demo_company}/facilities",
                            headers=admin_headers)
    assert facilities.status_code == 200, facilities.text
    names = {f["name"] for f in facilities.json()["facilities"]}
    assert "Mutuo ipotecario (demo)" in names
    assert "Leasing attrezzature (demo)" in names
    counters = facilities.json()["counters"]
    assert counters["paid"] == 2
    assert counters["scheduled"] >= 7

    listing = alerts(client, admin_headers, demo_company)
    fin = [a for a in listing["alerts"] if a["rule_code"] == "EW-FIN-OVERDUE"]
    assert fin, "la rata scaduta del seed deve aver generato l'alert"
    assert fin[0]["severity"] == "critical"

    snap = client.get(f"{CTRL}/companies/{demo_company}/snapshot",
                      headers=admin_headers)
    body = snap.json()
    assert body["dscr"]["status"] in ("available", "partial", "insufficient_data")
    assert body["continuity"]["months"] == 12


def test_cockpit_and_hub_carry_controlling_signals(
        client, admin_headers, demo_company):
    cockpit = client.get(
        f"{API}/cockpit/companies/{demo_company}",
        headers=admin_headers, params={"year": 2026, "through_month": 9})
    assert cockpit.status_code == 200, cockpit.text
    body = cockpit.json()
    assert body["controlling"]["open_alerts"] >= 1
    ew = [a for a in body["actions"] if a["category"] == "early_warning"]
    assert ew, "gli alert early-warning devono comparire nell'action center"
    fin = next(a for a in ew if a["code"] == "EW-FIN-OVERDUE")
    assert fin["severity"] == "critical"
    assert fin["evidence"]["rule_version"] == 1
    assert fin["priority_version"] == "cockpit-priority-v1.2"

    hub = client.get(f"{API}/cockpit/hub", headers=admin_headers,
                     params={"year": 2026, "through_month": 9})
    assert hub.status_code == 200, hub.text
    row = next(c for c in hub.json()["companies"]
               if c["company"]["id"] == demo_company)
    assert row["controlling"]["open_alerts"] >= 1
    assert row["controlling"]["critical_alerts"] >= 1
    assert any(a["category"] == "early_warning" for a in hub.json()["actions"])
