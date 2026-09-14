"""Treasury, reconciliation, cash analytics, cockpit/hub and AI tools.

Focus of these tests (the properties that make the numbers trustworthy):
tenant isolation, authorization, Decimal-as-string money, missing data staying
`null`, idempotency, append-only history, reconciliation edge cases
(cumulative payment, partial settlement, over-allocation, direction) and
reproducibility of the deterministic engines.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.treasury import matching
from app.shared.mixins import today

API = "/api/v1"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def demo_company(client, admin_headers) -> str:
    page = client.get(f"{API}/companies?page=1&page_size=200", headers=admin_headers).json()
    match = next(c for c in page["items"] if c["vat_number"] == "01234567890")
    return match["id"]


@pytest.fixture()
def empty_company(client, admin_headers) -> str:
    """A company with no treasury and no management data at all."""
    r = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Vuota {uuid.uuid4().hex[:6]} S.r.l.", "status": "customer"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


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
    return (today() + timedelta(days=offset)).isoformat()


def snapshot(client, headers, company_id: str) -> dict:
    r = client.get(f"{API}/treasury/companies/{company_id}/snapshot", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def suggestions(client, headers, company_id: str) -> dict:
    r = client.get(f"{API}/treasury/companies/{company_id}/reconciliation/suggestions",
                   headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def find_tx(plan: dict, amount: str) -> dict:
    return next(t for t in plan["transactions"] if t["amount"] == amount)


# ---------------------------------------------------------------------------
# Seeded scenario sanity: the demo data is coherent and labelled sandbox
# ---------------------------------------------------------------------------

def test_seeded_scenario_is_sandbox_labelled(client, admin_headers, demo_company):
    accounts = client.get(f"{API}/treasury/companies/{demo_company}/accounts",
                          headers=admin_headers).json()
    assert accounts["accounts"], "il seed deve creare un conto demo"
    account = accounts["accounts"][0]
    assert account["is_real_institution"] is False
    assert account["provider_key"] == "sandbox-openbanking"
    # secrets are never echoed back
    assert "credentials" not in account and account["credentials_configured"] is False
    snap = snapshot(client, admin_headers, demo_company)
    assert any(w["code"] == "sandbox_bank_data" for w in snap["warnings"])


def test_money_travels_as_strings_never_floats(client, admin_headers, demo_company):
    snap = snapshot(client, admin_headers, demo_company)
    assert isinstance(snap["position"]["amount"], str)
    assert isinstance(snap["counters"]["receivable_residual"], str)
    for window in snap["forecast"]["horizons"]:
        for key in ("expected_inflows", "expected_outflows", "net_flow", "projected_balance"):
            assert window[key] is None or isinstance(window[key], str)
    items = client.get(f"{API}/treasury/companies/{demo_company}/open-items",
                       headers=admin_headers).json()["items"]
    assert all(isinstance(i["amount"], str) and isinstance(i["residual"], str) for i in items)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_open_item_import_is_idempotent_and_refuses_divergent_content(
        client, admin_headers, empty_company):
    rows = [{"source_ref": "IMP-1", "direction": "receivable",
             "counterparty_name": "Cliente Uno S.r.l.", "due_date": day(10),
             "amount": "1000.00", "document_number": "1/2026"}]
    first = client.post(f"{API}/treasury/companies/{empty_company}/open-items/import",
                        headers=admin_headers, json={"rows": rows})
    assert first.status_code == 201, first.text
    assert first.json() == {"created": 1, "skipped": 0, "received": 1, "source": "import"}

    replay = client.post(f"{API}/treasury/companies/{empty_company}/open-items/import",
                         headers=admin_headers, json={"rows": rows})
    assert replay.status_code == 201
    assert replay.json()["created"] == 0 and replay.json()["skipped"] == 1

    divergent = [{**rows[0], "amount": "1200.00"}]
    conflict = client.post(f"{API}/treasury/companies/{empty_company}/open-items/import",
                           headers=admin_headers, json={"rows": divergent})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "open_item_conflict"
    # the batch is atomic: nothing from the rejected payload survived
    items = client.get(f"{API}/treasury/companies/{empty_company}/open-items",
                       headers=admin_headers).json()["items"]
    assert [i["amount"] for i in items] == ["1000.00"]


def test_bank_sync_is_idempotent_on_key_and_on_movement_id(
        client, admin_headers, demo_company):
    accounts = client.get(f"{API}/treasury/companies/{demo_company}/accounts",
                          headers=admin_headers).json()["accounts"]
    account_id = accounts[0]["id"]
    before = client.get(f"{API}/treasury/companies/{demo_company}/transactions",
                        headers=admin_headers).json()["counters"]["total"]

    replay = client.post(
        f"{API}/treasury/companies/{demo_company}/accounts/{account_id}/sync",
        headers=admin_headers, json={"idempotency_key": "demo-bank-sync-v1"})
    assert replay.status_code == 201
    assert replay.json()["replayed"] is True

    fresh = client.post(
        f"{API}/treasury/companies/{demo_company}/accounts/{account_id}/sync",
        headers=admin_headers, json={"idempotency_key": f"t-{uuid.uuid4().hex[:8]}"})
    assert fresh.status_code == 201, fresh.text
    body = fresh.json()
    assert body["replayed"] is False
    assert body["inserted_count"] == 0, "provider_tx_id già presenti: nessun duplicato"
    assert body["duplicate_count"] == body["fetched_count"]
    after = client.get(f"{API}/treasury/companies/{demo_company}/transactions",
                       headers=admin_headers).json()["counters"]["total"]
    assert after == before


# ---------------------------------------------------------------------------
# Reconciliation engine
# ---------------------------------------------------------------------------

def test_level1_exact_and_cumulative_are_applied_fuzzy_is_not(
        client, admin_headers, demo_company):
    plan = suggestions(client, admin_headers, demo_company)
    assert plan["engine_version"] == matching.ENGINE_VERSION

    exact = find_tx(plan, "12200.00")
    assert exact["auto_applicable"] is True
    assert exact["suggestions"][0]["method"] == "exact"
    assert exact["suggestions"][0]["confidence"] == "1.00"
    assert any("document_number" in r for r in exact["suggestions"][0]["reasons"])

    cumulative = find_tx(plan, "1500.00")
    assert cumulative["suggestions"][0]["method"] == "exact"
    assert len(cumulative["suggestions"][0]["allocations"]) == 2
    assert sum(Decimal(a["amount"]) for a in cumulative["suggestions"][0]["allocations"]) \
        == Decimal("1500.00")

    fuzzy = find_tx(plan, "8000.00")
    assert fuzzy["auto_applicable"] is False
    assert fuzzy["suggestions"][0]["method"] == "fuzzy"
    assert fuzzy["suggestions"][0]["requires_approval"] is True
    assert Decimal(fuzzy["suggestions"][0]["confidence"]) < Decimal("1.00")

    # a bank fee matches nothing and is never guessed
    assert plan["unmatched_transaction_ids"], "le commissioni non devono generare abbinamenti"

    applied = client.post(
        f"{API}/treasury/companies/{demo_company}/reconciliation/auto-apply",
        headers=admin_headers, json={"limit": 50})
    assert applied.status_code == 201, applied.text
    result = applied.json()
    assert result["applied"] == 3, "12200 esatto, 1500 cumulativo, 3660 esatto"
    assert result["skipped_requiring_approval"] >= 1

    again = client.post(
        f"{API}/treasury/companies/{demo_company}/reconciliation/auto-apply",
        headers=admin_headers, json={"limit": 50})
    assert again.json()["applied"] == 0, "nessuna riapplicazione: i residui sono a zero"

    items = client.get(f"{API}/treasury/companies/{demo_company}/open-items",
                       headers=admin_headers).json()["items"]
    settled = {i["source_ref"]: i for i in items if i["status"] == "settled"}
    assert {"DEMO-FT-45", "DEMO-FT-46", "DEMO-FT-47", "DEMO-ACQ-220"} <= set(settled)
    assert settled["DEMO-FT-45"]["residual"] == "0.00"
    assert settled["DEMO-FT-45"]["allocations"][0]["method"] == "exact"
    # provenance of the decision is kept
    assert settled["DEMO-FT-45"]["allocations"][0]["engine_version"] == matching.ENGINE_VERSION


def test_engine_is_reproducible(client, admin_headers, demo_company):
    first = suggestions(client, admin_headers, demo_company)
    second = suggestions(client, admin_headers, demo_company)
    assert first == second, "lo stesso stato deve produrre gli stessi suggerimenti"


def test_partial_settlement_then_write_off_keeps_history(
        client, admin_headers, empty_company):
    client.post(f"{API}/treasury/companies/{empty_company}/accounts",
                headers=admin_headers, json={
                    "label": "Conto manuale", "provider_key": "manual",
                    "provider_api_version": "v1", "provider_account_id": "MAN-1",
                    "opening_balance": "5000.00", "balance_date": day(0)})
    account_id = client.get(f"{API}/treasury/companies/{empty_company}/accounts",
                            headers=admin_headers).json()["accounts"][0]["id"]
    item = client.post(f"{API}/treasury/companies/{empty_company}/open-items",
                       headers=admin_headers, json={
                           "direction": "receivable", "counterparty_name": "Delta S.r.l.",
                           "due_date": day(5), "amount": "1000.00",
                           "source_ref": "PARTIAL-1"}).json()
    tx = client.post(f"{API}/treasury/companies/{empty_company}/transactions",
                     headers=admin_headers, json={
                         "bank_account_id": account_id, "provider_tx_id": "MAN-TX-1",
                         "value_date": day(0), "amount": "400.00",
                         "description": "ACCONTO DELTA", "counterparty_name": "Delta S.r.l."}).json()

    applied = client.post(f"{API}/treasury/companies/{empty_company}/reconciliation/apply",
                          headers=admin_headers, json={
                              "bank_transaction_id": tx["id"], "method": "manual",
                              "allocations": [{"open_item_id": item["id"], "amount": "400.00"}],
                              "reason": "Acconto parziale confermato dal cliente."})
    assert applied.status_code == 201, applied.text
    state = applied.json()["items"][0]
    assert state["status"] == "partially_settled"
    assert state["settled"] == "400.00" and state["residual"] == "600.00"

    # the movement is now fully allocated: it cannot settle anything else
    exhausted = client.post(f"{API}/treasury/companies/{empty_company}/reconciliation/apply",
                            headers=admin_headers, json={
                                "bank_transaction_id": tx["id"], "method": "manual",
                                "allocations": [{"open_item_id": item["id"], "amount": "100.00"}]})
    assert exhausted.status_code == 409
    assert exhausted.json()["error"]["code"] == "tx_fully_allocated"

    # a fresh movement cannot allocate more than the residual either
    bigger = client.post(f"{API}/treasury/companies/{empty_company}/transactions",
                         headers=admin_headers, json={
                             "bank_account_id": account_id, "provider_tx_id": "MAN-TX-2",
                             "value_date": day(0), "amount": "900.00",
                             "description": "SALDO DELTA",
                             "counterparty_name": "Delta S.r.l."}).json()
    over = client.post(f"{API}/treasury/companies/{empty_company}/reconciliation/apply",
                       headers=admin_headers, json={
                           "bank_transaction_id": bigger["id"], "method": "manual",
                           "allocations": [{"open_item_id": item["id"], "amount": "700.00"}]})
    assert over.status_code in (400, 422)
    assert over.json()["error"]["code"] == "over_allocation"

    closed = client.post(
        f"{API}/treasury/companies/{empty_company}/open-items/{item['id']}/close",
        headers=admin_headers,
        json={"method": "write_off", "reason": "Credito inesigibile: cliente in liquidazione."})
    assert closed.status_code == 200, closed.text
    final = closed.json()
    assert final["status"] == "written_off" and final["residual"] == "0.00"
    assert final["written_off"] == "600.00"
    assert len(final["allocations"]) == 2, "storico conservato: acconto + write-off"

    twice = client.post(
        f"{API}/treasury/companies/{empty_company}/open-items/{item['id']}/close",
        headers=admin_headers, json={"method": "write_off", "reason": "Tentativo ripetuto."})
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "no_residual"


def test_direction_and_closure_rules(client, admin_headers, empty_company):
    client.post(f"{API}/treasury/companies/{empty_company}/accounts",
                headers=admin_headers, json={
                    "label": "Conto manuale 2", "provider_key": "manual",
                    "provider_api_version": "v1", "provider_account_id": "MAN-2"})
    account_id = next(a["id"] for a in client.get(
        f"{API}/treasury/companies/{empty_company}/accounts",
        headers=admin_headers).json()["accounts"] if a["provider_account_id"] == "MAN-2")
    payable = client.post(f"{API}/treasury/companies/{empty_company}/open-items",
                          headers=admin_headers, json={
                              "direction": "payable", "counterparty_name": "Fornitore X",
                              "due_date": day(7), "amount": "250.00",
                              "source_ref": "DIR-1"}).json()
    inflow = client.post(f"{API}/treasury/companies/{empty_company}/transactions",
                         headers=admin_headers, json={
                             "bank_account_id": account_id, "provider_tx_id": "MAN-TX-DIR",
                             "value_date": day(0), "amount": "250.00",
                             "description": "INCASSO"}).json()
    wrong = client.post(f"{API}/treasury/companies/{empty_company}/reconciliation/apply",
                        headers=admin_headers, json={
                            "bank_transaction_id": inflow["id"], "method": "manual",
                            "allocations": [{"open_item_id": payable["id"], "amount": "250.00"}]})
    assert wrong.status_code in (400, 422)
    assert wrong.json()["error"]["code"] == "direction_mismatch"

    # a closure always requires a written reason
    bad = client.post(
        f"{API}/treasury/companies/{empty_company}/open-items/{payable['id']}/close",
        headers=admin_headers, json={"method": "cancellation", "reason": "no"})
    assert bad.status_code == 422


def test_manual_transaction_cannot_be_duplicated(client, admin_headers, empty_company):
    client.post(f"{API}/treasury/companies/{empty_company}/accounts",
                headers=admin_headers, json={
                    "label": "Conto manuale 3", "provider_key": "manual",
                    "provider_api_version": "v1", "provider_account_id": "MAN-3"})
    account_id = next(a["id"] for a in client.get(
        f"{API}/treasury/companies/{empty_company}/accounts",
        headers=admin_headers).json()["accounts"] if a["provider_account_id"] == "MAN-3")
    payload = {"bank_account_id": account_id, "provider_tx_id": "DUP-1",
               "value_date": day(0), "amount": "-100.00", "description": "TEST"}
    assert client.post(f"{API}/treasury/companies/{empty_company}/transactions",
                       headers=admin_headers, json=payload).status_code == 201
    again = client.post(f"{API}/treasury/companies/{empty_company}/transactions",
                        headers=admin_headers, json=payload)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "transaction_exists"


# ---------------------------------------------------------------------------
# Missing data behaviour
# ---------------------------------------------------------------------------

def test_missing_balance_makes_position_null_not_zero(client, admin_headers, empty_company):
    client.post(f"{API}/treasury/companies/{empty_company}/accounts",
                headers=admin_headers, json={
                    "label": "Conto senza saldo", "provider_key": "manual",
                    "provider_api_version": "v1", "provider_account_id": "NOBAL-1"})
    snap = snapshot(client, admin_headers, empty_company)
    assert snap["position"]["amount"] is None
    assert snap["position"]["status"] == "not_calculable"
    assert any(w["code"] == "cash_position_unknown" for w in snap["warnings"])
    # flows may still be computable, projected balances stay null
    for window in snap["forecast"]["horizons"]:
        assert window["projected_balance"] is None


def test_balance_requires_a_date(client, admin_headers, empty_company):
    r = client.post(f"{API}/treasury/companies/{empty_company}/accounts",
                    headers=admin_headers, json={
                        "label": "Conto senza data", "provider_key": "manual",
                        "provider_api_version": "v1", "provider_account_id": "NODATE-1",
                        "opening_balance": "1000.00"})
    assert r.status_code in (400, 422)
    assert r.json()["error"]["code"] == "balance_date_required"


def test_empty_company_is_not_green(client, admin_headers, empty_company):
    hub = client.get(f"{API}/cockpit/hub?year=2026&through_month=6",
                     headers=admin_headers).json()
    entry = next(e for e in hub["companies"] if e["company"]["id"] == empty_company)
    assert entry["health"]["status"] == "not_calculable"
    assert entry["cash"]["position"] is None
    assert entry["economics"]["revenue"] is None


def test_unconfigured_treasury_is_informational_not_an_alert(
        client, admin_headers, empty_company):
    """A setup gap must not compete with real financial problems."""
    snap = snapshot(client, admin_headers, empty_company)
    signal = next(w for w in snap["warnings"] if w["code"] == "treasury_not_configured")
    assert signal["severity"] == "info" and signal["action_required"] is False
    assert not any(w["severity"] in ("critical", "warning") for w in snap["warnings"])


# ---------------------------------------------------------------------------
# Cash forecast + warnings
# ---------------------------------------------------------------------------

def test_forecast_is_fact_assumption_separated_and_flags_negative_cash(
        client, admin_headers, demo_company):
    r = client.get(f"{API}/treasury/companies/{demo_company}/cash-forecast?horizon_days=90",
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    forecast = r.json()
    assert forecast["facts"] and forecast["assumptions"]
    assert any("scadute" in a for a in forecast["assumptions"])
    assert forecast["first_negative_date"] is not None
    assert forecast["days_to_negative"] >= 0
    assert forecast["overdue_excluded"]["count"] >= 1
    assert forecast["formula_version"].startswith("treasury-")

    snap = snapshot(client, admin_headers, demo_company)
    critical = next(w for w in snap["warnings"] if w["code"] == "cash_forecast_negative")
    assert critical["severity"] == "critical" and critical["action_required"] is True
    assert critical["formula"] and critical["evidence"]["days_to_negative"] is not None
    assert any(w["code"] == "overdue_receivables" for w in snap["warnings"])


def test_aging_buckets_sum_to_totals(client, admin_headers, demo_company):
    aging = client.get(f"{API}/treasury/companies/{demo_company}/aging",
                       headers=admin_headers).json()
    for side in ("receivables", "payables"):
        block = aging[side]
        bucket_sum = sum(Decimal(b["amount"]) for b in block["buckets"].values()
                         if b["amount"] is not None)
        assert bucket_sum == Decimal(block["total"] or "0.00")


# ---------------------------------------------------------------------------
# Cockpit / hub
# ---------------------------------------------------------------------------

def test_company_cockpit_composes_domains_with_explanations(
        client, admin_headers, demo_company):
    r = client.get(f"{API}/cockpit/companies/{demo_company}?year=2026&through_month=6",
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    cockpit = r.json()
    assert cockpit["company"]["vat_number"] == "01234567890"
    assert cockpit["management"]["trace"]["formula_version"]
    assert cockpit["treasury"]["position"]["status"] in ("available", "not_calculable")
    assert cockpit["actions"], "il cockpit deve elencare azioni deterministiche"
    assert all(a["formula"] and a["formula_version"] for a in cockpit["actions"])
    priorities = [a["priority"] for a in cockpit["actions"]]
    assert priorities == sorted(priorities, reverse=True)
    assert cockpit["priority"]["version"]
    assert cockpit["limitations"]


def test_hub_ranks_companies_by_attention(client, admin_headers, demo_company):
    r = client.get(f"{API}/cockpit/hub?year=2026&through_month=6", headers=admin_headers)
    assert r.status_code == 200, r.text
    hub = r.json()
    scores = [e["attention_score"] for e in hub["companies"]]
    assert scores == sorted(scores, reverse=True)
    demo = next(e for e in hub["companies"] if e["company"]["id"] == demo_company)
    assert demo["health"]["status"] in ("critical", "attention")
    assert demo["cash"]["first_negative_date"] is not None
    assert hub["counters"]["critical"] >= 1
    assert "consolidato" in hub["aggregation_note"]


# ---------------------------------------------------------------------------
# Authorization + tenant isolation
# ---------------------------------------------------------------------------

def test_readonly_cannot_write_treasury(client, readonly_headers, demo_company):
    assert client.get(f"{API}/treasury/companies/{demo_company}/snapshot",
                      headers=readonly_headers).status_code == 200
    denied = client.post(f"{API}/treasury/companies/{demo_company}/open-items",
                         headers=readonly_headers, json={
                             "direction": "receivable", "counterparty_name": "X S.r.l.",
                             "due_date": day(10), "amount": "10.00"})
    assert denied.status_code == 403
    assert client.post(
        f"{API}/treasury/companies/{demo_company}/reconciliation/auto-apply",
        headers=readonly_headers, json={"limit": 5}).status_code == 403


def test_treasury_requires_authentication(client, demo_company):
    assert client.get(f"{API}/treasury/companies/{demo_company}/snapshot").status_code == 401
    assert client.get(f"{API}/cockpit/hub").status_code == 401


def test_client_tenant_cannot_reach_another_tenant_company(client, demo_company):
    token = client.post(f"{API}/auth/login", json={
        "email": "cliente@demo.example",
        "password": "prosperya-client-dev"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # the company belongs to the platform tenant: existence must not leak
    for path in (f"/treasury/companies/{demo_company}/snapshot",
                 f"/treasury/companies/{demo_company}/open-items",
                 f"/cockpit/companies/{demo_company}"):
        r = client.get(f"{API}{path}", headers=headers)
        assert r.status_code == 404, path
    # even with a spoofed tenant header, a client role stays locked
    spoofed = client.get(f"{API}/treasury/companies/{demo_company}/snapshot",
                         headers={**headers, "X-Tenant-Id": str(uuid.uuid4())})
    assert spoofed.status_code == 404
    hub = client.get(f"{API}/cockpit/hub", headers=headers).json()
    assert all(e["company"]["id"] != demo_company for e in hub["companies"])


def test_staff_switching_tenant_sees_no_foreign_treasury(client, admin_headers, demo_company):
    slug = f"iso-{uuid.uuid4().hex[:6]}"
    other = client.post(f"{API}/tenants", headers=admin_headers,
                        json={"slug": slug, "display_name": "Altro Tenant S.r.l."}).json()
    headers = {**admin_headers, "X-Tenant-Id": other["id"]}
    r = client.get(f"{API}/treasury/companies/{demo_company}/snapshot", headers=headers)
    assert r.status_code == 404
    hub = client.get(f"{API}/cockpit/hub", headers=headers).json()
    assert hub["companies"] == []


# ---------------------------------------------------------------------------
# Append-only enforcement (ORM level)
# ---------------------------------------------------------------------------

def test_financial_history_is_append_only(client, admin_headers, demo_company):
    from app.db import SessionLocal
    from app.modules.treasury.models import BankTransaction, OpenItem

    with SessionLocal() as db:
        item = db.query(OpenItem).filter(OpenItem.source_ref == "DEMO-FT-40").one()
        item.amount = Decimal("1.00")
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()

        tx = db.query(BankTransaction).first()
        with pytest.raises(ValueError, match="append-only"):
            db.delete(tx)
            db.flush()
        db.rollback()

    # the value on the API is untouched
    items = client.get(f"{API}/treasury/companies/{demo_company}/open-items",
                       headers=admin_headers).json()["items"]
    overdue = next(i for i in items if i["source_ref"] == "DEMO-FT-40")
    assert overdue["amount"] == "15000.00"


# ---------------------------------------------------------------------------
# Pure engine unit tests
# ---------------------------------------------------------------------------

def test_counterparty_normalisation_strips_legal_forms():
    assert matching.normalize_counterparty("Rossi S.r.l.") == "rossi"
    assert matching.normalize_counterparty("ROSSI SRL") == "rossi"
    assert matching.normalize_counterparty("Beta Servizi S.p.A.") == "beta servizi"
    assert matching.normalize_counterparty(None) == ""


def test_document_tokens_ignore_noise_and_short_refs():
    assert "12 2026" in matching.document_tokens("FT 12/2026") or \
           "122026" in matching.document_tokens("FT 12/2026")
    assert matching.document_tokens("") == []
    assert all(len(t) >= 3 for t in matching.document_tokens("N. 7/26"))


def test_exact_match_requires_a_reference_not_just_the_amount():
    tx = matching.TxView(
        id="tx", value_date=date(2026, 5, 10), booking_date=date(2026, 5, 10),
        amount=Decimal("1000.00"), unallocated=Decimal("1000.00"),
        description="BONIFICO GENERICO", counterparty_name=None)
    item = matching.ItemView(
        id="item", direction="receivable", counterparty_name="Zeta S.r.l.",
        due_date=date(2026, 5, 12), amount=Decimal("1000.00"),
        residual=Decimal("1000.00"), document_number="FT 99/2026")
    found = matching.suggest_for_transaction(tx, [item])
    assert found, "l'importo identico produce almeno un candidato fuzzy"
    assert found[0].method == "fuzzy", "senza riferimento non è un match esatto"

    with_reference = matching.TxView(
        id="tx2", value_date=date(2026, 5, 10), booking_date=date(2026, 5, 10),
        amount=Decimal("1000.00"), unallocated=Decimal("1000.00"),
        description="SALDO FT 99/2026", counterparty_name="ZETA SRL")
    promoted = matching.suggest_for_transaction(with_reference, [item])
    assert promoted[0].method == "exact" and promoted[0].confidence == Decimal("1.00")


def test_engine_never_matches_across_direction_or_beyond_tolerance():
    tx = matching.TxView(
        id="tx", value_date=date(2026, 5, 10), booking_date=date(2026, 5, 10),
        amount=Decimal("1000.00"), unallocated=Decimal("1000.00"),
        description="SALDO FT 99/2026", counterparty_name="ZETA SRL")
    payable = matching.ItemView(
        id="p", direction="payable", counterparty_name="Zeta S.r.l.",
        due_date=date(2026, 5, 12), amount=Decimal("1000.00"),
        residual=Decimal("1000.00"), document_number="FT 99/2026")
    distant = matching.ItemView(
        id="d", direction="receivable", counterparty_name="Zeta S.r.l.",
        due_date=date(2026, 5, 12), amount=Decimal("5000.00"),
        residual=Decimal("5000.00"), document_number="FT 98/2026")
    assert matching.suggest_for_transaction(tx, [payable, distant]) == []


# ---------------------------------------------------------------------------
# AI assistant reads verified tools only
# ---------------------------------------------------------------------------

def test_assistant_answers_cash_questions_from_treasury_tools(
        client, admin_headers, demo_company):
    r = client.post(f"{API}/assistant/companies/{demo_company}/chat",
                    headers=admin_headers, json={
                        "year": 2026, "through_month": 6,
                        "message": "Qual è la situazione di cassa?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "get_cash_position" in body["tools_used"]
    assert body["mode"] == "mock"
    assert any(i["type"] == "FACT" for i in body["items"])
    assert body["evidence"]["formula_version"]
    assert any("tesoreria" in limitation for limitation in body["limitations"])


def test_assistant_flags_liquidity_risk_as_action_required(
        client, admin_headers, demo_company):
    r = client.post(f"{API}/assistant/companies/{demo_company}/chat",
                    headers=admin_headers, json={
                        "year": 2026, "through_month": 6,
                        "message": "Rischio tensione di cassa nei prossimi 60 giorni?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "get_cash_forecast" in body["tools_used"]
    kinds = {i["type"] for i in body["items"]}
    assert "ACTION_REQUIRED" in kinds or "WARNING" in kinds
    assert "ASSUMPTION" in kinds, "le ipotesi della previsione devono essere esplicite"


def test_assistant_reports_overdue_and_reconciliation_state(
        client, admin_headers, demo_company):
    overdue = client.post(f"{API}/assistant/companies/{demo_company}/chat",
                          headers=admin_headers, json={
                              "year": 2026, "through_month": 6,
                              "message": "Quali crediti sono scaduti?"}).json()
    assert "get_receivables_aging" in overdue["tools_used"]

    reconciliation = client.post(f"{API}/assistant/companies/{demo_company}/chat",
                                 headers=admin_headers, json={
                                     "year": 2026, "through_month": 6,
                                     "message": "Quanti movimenti bancari non riconciliati abbiamo?"}).json()
    assert "get_reconciliation_status" in reconciliation["tools_used"]
    assert any("livello 3" in i["text"].lower() or "DESIGNED" in i["text"]
               for i in reconciliation["items"])


def test_assistant_refuses_fiscal_and_dispositive_requests(
        client, admin_headers, demo_company):
    fiscal = client.post(f"{API}/assistant/companies/{demo_company}/chat",
                         headers=admin_headers, json={
                             "year": 2026, "through_month": 6,
                             "message": "Qual è la situazione IVA prevista e l'F24 da pagare?"}).json()
    assert fiscal["tools_used"] == []
    assert any("IVA" in limitation or "F24" in limitation
               for limitation in fiscal["limitations"])

    payment = client.post(f"{API}/assistant/companies/{demo_company}/chat",
                          headers=admin_headers, json={
                              "year": 2026, "through_month": 6,
                              "message": "Esegui il pagamento del fornitore"}).json()
    assert payment["tools_used"] == []
    assert any("sola lettura" in limitation for limitation in payment["limitations"])
