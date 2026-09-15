"""Fiscal Core V1 — VAT register, settlements, deadlines, F24 drafts.

Focus (the properties that make fiscal numbers defensible):
golden settlement cases against the verified AdE formula, effective-dated
rule resolution (no rule set → refusal, never silent fallback), idempotency
on every write path, append-only VAT register, human-only validation, and
the exactly-once bridge from a validated liability to one treasury open item.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.fiscal import rules

API = "/api/v1"
FISCAL = f"{API}/fiscal"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def demo_company(client, admin_headers) -> str:
    page = client.get(f"{API}/companies?page=1&page_size=200", headers=admin_headers).json()
    match = next(c for c in page["items"] if c["vat_number"] == "01234567890")
    return match["id"]


@pytest.fixture()
def fiscal_company(client, admin_headers) -> str:
    """A clean company: no fiscal data, no treasury items."""
    r = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Fiscale {uuid.uuid4().hex[:6]} S.r.l.", "status": "customer",
        "vat_number": "02" + uuid.uuid4().hex[:9].replace("a", "1").replace("b", "2")
                      .replace("c", "3").replace("d", "4").replace("e", "5").replace("f", "6")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def rules_synced(client, admin_headers):
    """Materialise the verified rule sets. Idempotent — safe per test."""
    r = client.post(f"{FISCAL}/rule-sets/sync", headers=admin_headers)
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


@pytest.fixture()
def backoffice_headers(client, admin_headers) -> dict:
    email = f"bo-{uuid.uuid4().hex[:6]}@prosperya.it"
    r = client.post(f"{API}/users", headers=admin_headers, json={
        "email": email, "full_name": "Back Office", "password": "backoffice-pass-1",
        "role": "backoffice"})
    assert r.status_code == 201, r.text
    token = client.post(f"{API}/auth/login", json={
        "email": email, "password": "backoffice-pass-1"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def add_entry(client, headers, company_id: str, **kw) -> dict:
    r = client.post(f"{FISCAL}/companies/{company_id}/vat-entries",
                    headers=headers, json=kw)
    assert r.status_code == 201, r.text
    return r.json()


def calculate(client, headers, company_id: str, year: int, period_no: int,
              frequency: str = "monthly") -> dict:
    r = client.post(f"{FISCAL}/companies/{company_id}/settlements/calculate",
                    headers=headers,
                    json={"year": year, "period_no": period_no, "frequency": frequency})
    assert r.status_code == 201, r.text
    return r.json()


def validate(client, headers, company_id: str, settlement_id: str, **kw) -> dict:
    r = client.post(f"{FISCAL}/companies/{company_id}/settlements/{settlement_id}/validate",
                    headers=headers, json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def open_items(client, headers, company_id: str) -> list[dict]:
    r = client.get(f"{API}/treasury/companies/{company_id}/open-items", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ---------------------------------------------------------------------------
# Rule sets: provenance, effective dating, admin-only sync
# ---------------------------------------------------------------------------

def test_rule_sets_carry_authoritative_provenance(client, admin_headers, rules_synced):
    r = client.get(f"{FISCAL}/rule-sets", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    families = {rs["rule_family"] for rs in body["rule_sets"]}
    assert {"vat_periodic", "payment_calendar", "f24_format"} <= families
    for rs in body["rule_sets"]:
        src = rs["source"]
        assert src["authority"] and src["url"].startswith("https://")
        assert src["retrieved_at"], "ogni regola deve dichiarare quando è stata verificata"
        assert rs["effective_from"] == "2026-01-01"
    codes = {c["code"] for c in body["tax_codes"]}
    assert {"6001", "6012", "6031", "6033"} <= codes


def test_rule_set_sync_is_idempotent_and_admin_only(
        client, admin_headers, consultant_headers, rules_synced):
    again = client.post(f"{FISCAL}/rule-sets/sync", headers=admin_headers)
    assert again.status_code == 201
    assert again.json()["rule_sets_created"] == [], \
        "le versioni esistenti non vengono mai riscritte"
    assert again.json()["tax_codes_created"] == []
    denied = client.post(f"{FISCAL}/rule-sets/sync", headers=consultant_headers)
    assert denied.status_code == 403, "fiscal:admin è riservato all'admin"


def test_period_before_rules_effective_from_is_refused(
        client, admin_headers, fiscal_company, rules_synced):
    """No silent fallback: a period with no applicable rule set is not computed."""
    r = client.post(f"{FISCAL}/companies/{fiscal_company}/settlements/calculate",
                    headers=admin_headers,
                    json={"year": 2025, "period_no": 6, "frequency": "monthly"})
    assert r.status_code in (400, 422)
    assert r.json()["error"]["code"] == "no_applicable_rule_set"


def test_fourth_quarter_is_out_of_scope(
        client, admin_headers, fiscal_company, rules_synced):
    r = client.post(f"{FISCAL}/companies/{fiscal_company}/settlements/calculate",
                    headers=admin_headers,
                    json={"year": 2026, "period_no": 4, "frequency": "quarterly"})
    assert r.status_code in (400, 422)
    assert r.json()["error"]["code"] == "unsupported_period"


# ---------------------------------------------------------------------------
# VAT register: classification, idempotency, append-only
# ---------------------------------------------------------------------------

def test_entry_classification_is_bounded_and_explicit(
        client, admin_headers, fiscal_company):
    sale = add_entry(client, admin_headers, fiscal_company,
                     direction="sale", competence_date="2026-03-10",
                     taxable_amount="1000.00", vat_amount="220.00", vat_rate="22",
                     source_ref="T-SALE-1")
    assert sale["treatment"] == "supported"

    no_vat = add_entry(client, admin_headers, fiscal_company,
                       direction="sale", competence_date="2026-03-11",
                       taxable_amount="500.00", source_ref="T-NOVAT-1")
    assert no_vat["treatment"] == "insufficient_data"

    purchase = add_entry(client, admin_headers, fiscal_company,
                         direction="purchase", competence_date="2026-03-12",
                         taxable_amount="100.00", vat_amount="22.00", vat_rate="22",
                         source_ref="T-PUR-1")
    assert purchase["treatment"] == "requires_review", \
        "la detraibilità non è mai assunta"

    non_ded = add_entry(client, admin_headers, fiscal_company,
                        direction="purchase", competence_date="2026-03-13",
                        taxable_amount="100.00", vat_amount="22.00", vat_rate="22",
                        deductible=False, source_ref="T-PUR-2")
    assert non_ded["treatment"] == "supported", \
        "indetraibile è un dato completo: entra nel calcolo come esclusa dal credito"

    nature = add_entry(client, admin_headers, fiscal_company,
                       direction="sale", competence_date="2026-03-14",
                       taxable_amount="200.00", vat_amount="0.00", vat_nature="N2",
                       source_ref="T-NAT-1")
    assert nature["treatment"] == "supported"


def test_vat_entry_write_is_idempotent_and_conflicts_on_divergence(
        client, admin_headers, fiscal_company):
    payload = {"direction": "sale", "competence_date": "2026-04-05",
               "taxable_amount": "800.00", "vat_amount": "176.00", "vat_rate": "22",
               "source_ref": "IDEM-1"}
    first = add_entry(client, admin_headers, fiscal_company, **payload)
    assert first["replayed"] is False
    replay = add_entry(client, admin_headers, fiscal_company, **payload)
    assert replay["replayed"] is True and replay["id"] == first["id"]

    divergent = client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries",
                            headers=admin_headers,
                            json={**payload, "vat_amount": "177.00"})
    assert divergent.status_code == 409
    assert divergent.json()["error"]["code"] == "vat_entry_conflict"


def test_vat_import_is_atomic_and_idempotent(client, admin_headers, fiscal_company):
    rows = [
        {"source_ref": "IMP-A", "direction": "sale", "competence_date": "2026-02-03",
         "taxable_amount": "1000.00", "vat_amount": "220.00", "vat_rate": "22"},
        {"source_ref": "IMP-B", "direction": "purchase", "competence_date": "2026-02-04",
         "taxable_amount": "400.00", "vat_amount": "88.00", "vat_rate": "22",
         "deductible": True},
    ]
    first = client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries/import",
                        headers=admin_headers, json={"rows": rows})
    assert first.status_code == 201, first.text
    assert first.json() == {"created": 2, "skipped": 0, "received": 2,
                            "requires_review": 0}

    replay = client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries/import",
                         headers=admin_headers, json={"rows": rows})
    assert replay.json()["created"] == 0 and replay.json()["skipped"] == 2

    # atomicity: one bad row rejects the whole batch
    bad_batch = client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries/import",
                            headers=admin_headers, json={"rows": [
                                {"source_ref": "IMP-C", "direction": "sale",
                                 "competence_date": "2026-02-05",
                                 "taxable_amount": "10.00", "vat_amount": "2.20",
                                 "vat_rate": "22"},
                                {"source_ref": "IMP-D", "direction": "sale",
                                 "competence_date": "not-a-date",
                                 "taxable_amount": "10.00"},
                            ]})
    assert bad_batch.status_code in (400, 422)
    listing = client.get(
        f"{FISCAL}/companies/{fiscal_company}/vat-entries?year=2026",
        headers=admin_headers).json()
    assert {e["source_ref"] for e in listing["entries"]} == {"IMP-A", "IMP-B"}

    dup = client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries/import",
                      headers=admin_headers, json={"rows": [rows[0], rows[0]]})
    assert dup.status_code in (400, 422)
    assert dup.json()["error"]["code"] == "duplicate_source_ref"


def test_vat_register_is_append_only(client, admin_headers, fiscal_company):
    from app.db import SessionLocal
    from app.modules.fiscal.models import VatEntry

    entry = add_entry(client, admin_headers, fiscal_company,
                      direction="sale", competence_date="2026-01-15",
                      taxable_amount="100.00", vat_amount="22.00", vat_rate="22",
                      source_ref="AO-1")
    with SessionLocal() as db:
        row = db.get(VatEntry, uuid.UUID(entry["id"]))
        row.taxable_amount = Decimal("1.00")
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()
        with pytest.raises(ValueError, match="append-only"):
            db.delete(row)
            db.flush()
        db.rollback()


def test_entry_confirmation_is_a_new_immutable_entry(
        client, admin_headers, fiscal_company):
    pending = add_entry(client, admin_headers, fiscal_company,
                        direction="purchase", competence_date="2026-03-20",
                        taxable_amount="300.00", vat_amount="66.00", vat_rate="22",
                        source_ref="CONF-1")
    assert pending["treatment"] == "requires_review"

    confirmed = client.post(
        f"{FISCAL}/companies/{fiscal_company}/vat-entries/{pending['id']}/confirm",
        headers=admin_headers,
        json={"treatment": "supported", "deductible": True,
              "reason": "Fattura di acquisto verificata: IVA detraibile."})
    assert confirmed.status_code == 201, confirmed.text
    twin = confirmed.json()
    assert twin["source"] == "system_derived"
    assert twin["reverses_entry_id"] == pending["id"]
    assert twin["treatment"] == "supported" and twin["deductible"] is True

    again = client.post(
        f"{FISCAL}/companies/{fiscal_company}/vat-entries/{pending['id']}/confirm",
        headers=admin_headers, json={"treatment": "unsupported"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "entry_already_confirmed"

    listing = client.get(
        f"{FISCAL}/companies/{fiscal_company}/vat-entries?year=2026&period_no=3",
        headers=admin_headers).json()
    original = next(e for e in listing["entries"] if e["id"] == pending["id"])
    assert original["superseded"] is True
    assert listing["counters"]["requires_review"] == 0


# ---------------------------------------------------------------------------
# Settlement: golden cases, versioning, human validation
# ---------------------------------------------------------------------------

def test_settlement_golden_case_monthly_payable(
        client, admin_headers, fiscal_company, rules_synced):
    """Debit 2200 − credit 660 = 1540 ≥ 100 → payable, no interest (monthly)."""
    # A first-ever calculation always warns about the untracked prior position;
    # establish a validated February so March is the clean golden path.
    feb = calculate(client, admin_headers, fiscal_company, 2026, 2)
    assert feb["status"] == "review_required"
    assert any(w["code"] == "no_prior_period" for w in feb["warnings"])
    validate(client, admin_headers, fiscal_company, feb["id"],
             note="Posizione di apertura: nessun credito/debito pregresso.")

    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-03-05",
              taxable_amount="10000.00", vat_amount="2200.00", vat_rate="22",
              source_ref="G-S1")
    add_entry(client, admin_headers, fiscal_company,
              direction="purchase", competence_date="2026-03-08",
              taxable_amount="3000.00", vat_amount="660.00", vat_rate="22",
              deductible=True, source_ref="G-P1")

    result = calculate(client, admin_headers, fiscal_company, 2026, 3)
    assert result["status"] == "calculated", result["warnings"]
    assert result["debit_total"] == "2200.00"
    assert result["credit_total"] == "660.00"
    assert result["net_position"] == "1540.00"
    assert result["payable_amount"] == "1540.00"
    assert result["interest_amount"] == "0.00"
    assert result["outcome"] == "payable"
    # provenance: the result names the rule set and lists its sources
    assert result["trace"]["rule_set"]["version"] == "2026.1"
    assert result["trace"]["rule_set"]["source"]["authority"] == "Agenzia delle Entrate"
    assert len(result["trace"]["debit_sources"]) == 1
    assert result["deadline"]["due_date"] == "2026-04-16"
    assert result["deadline"]["status"] == "pending"


def test_settlement_below_minimum_is_carried_forward(
        client, admin_headers, fiscal_company, rules_synced):
    """Net debit < 100 → nothing payable, debit carried to the next period."""
    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-05-10",
              taxable_amount="300.00", vat_amount="66.00", vat_rate="22",
              source_ref="G-SMALL")
    result = calculate(client, admin_headers, fiscal_company, 2026, 5)
    assert result["net_position"] == "66.00"
    assert result["payable_amount"] is None
    assert result["carry_forward_debit"] == "66.00"
    assert result["outcome"] == "carried_forward_debit"
    assert result["deadline"]["amount"] is None


def test_settlement_credit_carries_forward(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="purchase", competence_date="2026-06-02",
              taxable_amount="5000.00", vat_amount="1100.00", vat_rate="22",
              deductible=True, source_ref="G-CRED")
    result = calculate(client, admin_headers, fiscal_company, 2026, 6)
    assert result["net_position"] == "-1100.00"
    assert result["payable_amount"] is None
    assert result["carry_forward_credit"] == "1100.00"
    assert result["outcome"] == "credit"


def test_quarterly_settlement_adds_one_percent_interest(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-02-10",
              taxable_amount="10000.00", vat_amount="2200.00", vat_rate="22",
              source_ref="G-Q1")
    result = calculate(client, admin_headers, fiscal_company, 2026, 1,
                       frequency="quarterly")
    assert result["net_position"] == "2200.00"
    assert result["interest_amount"] == "22.00", "1% sul debito trimestrale"
    assert result["payable_amount"] == "2222.00"
    assert any("quarterly_interest" in r for r in result["trace"]["applied_rules"])
    # Q1 statutory due date 16/05/2026 is a Saturday → Monday 18/05
    assert result["deadline"]["statutory_date"] == "2026-05-16"
    assert result["deadline"]["due_date"] == "2026-05-18"


def test_prior_period_position_flows_into_next_settlement(
        client, admin_headers, fiscal_company, rules_synced):
    """A validated credit of period N reduces the payable of period N+1."""
    add_entry(client, admin_headers, fiscal_company,
              direction="purchase", competence_date="2026-01-10",
              taxable_amount="2000.00", vat_amount="440.00", vat_rate="22",
              deductible=True, source_ref="G-PP-C")
    first = calculate(client, admin_headers, fiscal_company, 2026, 1)
    assert first["carry_forward_credit"] == "440.00"
    validate(client, admin_headers, fiscal_company, first["id"],
             note="Credito verificato.")

    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-02-10",
              taxable_amount="3000.00", vat_amount="660.00", vat_rate="22",
              source_ref="G-PP-S")
    second = calculate(client, admin_headers, fiscal_company, 2026, 2)
    assert second["prior_credit"] == "440.00"
    assert second["net_position"] == "220.00"
    assert second["payable_amount"] == "220.00"
    assert second["trace"]["prior_source"]["status"] == "validated"


def test_blocked_entries_force_review_required_and_exclude_from_totals(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-07-05",
              taxable_amount="1000.00", vat_amount="220.00", vat_rate="22",
              source_ref="B-OK")
    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-07-06",
              taxable_amount="900.00", source_ref="B-PENDING")  # no VAT → insufficient_data
    result = calculate(client, admin_headers, fiscal_company, 2026, 7)
    assert result["status"] == "review_required"
    assert result["debit_total"] == "220.00", "la voce bloccante resta fuori dai totali"
    assert result["unsupported_count"] == 1
    assert any(w["code"] == "unsupported_entries" for w in result["warnings"])

    # validation with a critical warning requires explicit acknowledgement + note
    denied = client.post(
        f"{FISCAL}/companies/{fiscal_company}/settlements/{result['id']}/validate",
        headers=admin_headers, json={})
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "settlement_requires_review"

    no_note = client.post(
        f"{FISCAL}/companies/{fiscal_company}/settlements/{result['id']}/validate",
        headers=admin_headers, json={"acknowledge_warnings": True})
    assert no_note.status_code in (400, 422)
    assert no_note.json()["error"]["code"] == "validation_note_required"

    done = validate(client, admin_headers, fiscal_company, result["id"],
                    acknowledge_warnings=True,
                    note="Voce esclusa consapevolmente: documento non pervenuto.")
    assert done["status"] == "validated"


def test_recalculation_versions_never_overwrites(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-08-03",
              taxable_amount="1000.00", vat_amount="220.00", vat_rate="22",
              source_ref="V-1")
    v1 = calculate(client, admin_headers, fiscal_company, 2026, 8)
    assert v1["version"] == 1

    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-08-10",
              taxable_amount="500.00", vat_amount="110.00", vat_rate="22",
              source_ref="V-2")
    v2 = calculate(client, admin_headers, fiscal_company, 2026, 8)
    assert v2["version"] == 2
    assert v2["debit_total"] == "330.00"

    stale = client.post(
        f"{FISCAL}/companies/{fiscal_company}/settlements/{v1['id']}/validate",
        headers=admin_headers, json={})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "settlement_superseded"


# ---------------------------------------------------------------------------
# Treasury bridge: exactly one cash obligation per validated liability
# ---------------------------------------------------------------------------

def test_validated_settlement_creates_exactly_one_treasury_item(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-09-05",
              taxable_amount="5000.00", vat_amount="1100.00", vat_rate="22",
              source_ref="T-BRIDGE")
    settlement = calculate(client, admin_headers, fiscal_company, 2026, 9)
    validated = validate(client, admin_headers, fiscal_company, settlement["id"],
                         note="Liquidazione verificata.")
    liability = validated["liability"]
    assert liability["created"] is True
    assert liability["amount"] == "1100.00"
    assert liability["due_date"] == "2026-10-16"

    items = [i for i in open_items(client, admin_headers, fiscal_company)
             if i["source"] == "fiscal"]
    assert len(items) == 1
    item = items[0]
    assert item["direction"] == "payable"
    assert item["counterparty_name"] == "Erario — IVA periodica"
    assert item["source_ref"].startswith("vat_settlement:")

    # re-validation is a no-op: no second cash obligation
    again = validate(client, admin_headers, fiscal_company, settlement["id"], note="dup")
    assert again["status"] == "validated"
    items_after = [i for i in open_items(client, admin_headers, fiscal_company)
                   if i["source"] == "fiscal"]
    assert len(items_after) == 1

    deadline = validated["deadline"]
    assert deadline["status"] == "validated"
    assert deadline["open_item_id"] == item["id"]


def test_credit_settlement_creates_no_treasury_item(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="purchase", competence_date="2026-10-05",
              taxable_amount="1000.00", vat_amount="220.00", vat_rate="22",
              deductible=True, source_ref="T-NOPAY")
    settlement = calculate(client, admin_headers, fiscal_company, 2026, 10)
    validated = validate(client, admin_headers, fiscal_company, settlement["id"],
                         note="Credito.")
    assert validated["liability"]["created"] is False
    assert not [i for i in open_items(client, admin_headers, fiscal_company)
                if i["source"] == "fiscal"]


# ---------------------------------------------------------------------------
# F24 drafts: lifecycle, gating, export
# ---------------------------------------------------------------------------

def _validated_payable_settlement(client, headers, company_id: str,
                                  month: int = 11) -> dict:
    add_entry(client, headers, company_id,
              direction="sale", competence_date=f"2026-{month:02d}-05",
              taxable_amount="4000.00", vat_amount="880.00", vat_rate="22",
              source_ref=f"F24-{month}")
    settlement = calculate(client, headers, company_id, 2026, month)
    return validate(client, headers, company_id, settlement["id"], note="ok")


def test_f24_full_lifecycle_and_export_gating(
        client, admin_headers, fiscal_company, rules_synced):
    settlement = _validated_payable_settlement(client, admin_headers, fiscal_company)

    generated = client.post(f"{FISCAL}/companies/{fiscal_company}/f24/generate",
                            headers=admin_headers,
                            json={"settlement_id": settlement["id"]})
    assert generated.status_code == 201, generated.text
    draft = generated.json()
    assert draft["status"] == "validation_required"
    assert draft["balance"] == "880.00"
    assert draft["lines"][0]["tax_code"] == "6011", "codice tributo IVA mensile novembre"
    assert draft["lines"][0]["section"] == "erario"
    assert draft["lines"][0]["explanation"]
    assert draft["transmission"]["supported"] is False

    # idempotent generation
    replay = client.post(f"{FISCAL}/companies/{fiscal_company}/f24/generate",
                         headers=admin_headers,
                         json={"settlement_id": settlement["id"]})
    assert replay.json()["replayed"] is True
    assert replay.json()["id"] == draft["id"]

    # export is gated behind human approval
    early = client.post(f"{FISCAL}/companies/{fiscal_company}/f24/{draft['id']}/export",
                        headers=admin_headers, json={"format": "json"})
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "f24_not_approved"

    val = client.post(f"{FISCAL}/companies/{fiscal_company}/f24/{draft['id']}/validate",
                      headers=admin_headers, json={"note": "Controllato."})
    assert val.status_code == 200 and val.json()["status"] == "validated"

    appr = client.post(f"{FISCAL}/companies/{fiscal_company}/f24/{draft['id']}/approve",
                       headers=admin_headers, json={"note": "Approvato."})
    assert appr.status_code == 200 and appr.json()["status"] == "approved"

    exported = client.post(
        f"{FISCAL}/companies/{fiscal_company}/f24/{draft['id']}/export",
        headers=admin_headers, json={"format": "json"})
    assert exported.status_code == 200
    assert exported.headers["X-Export-Fingerprint"]
    assert "non trasmissibile" in exported.headers["X-Export-Disclaimer"]
    payload = exported.json()
    assert payload["totals"]["balance"] == "880.00"
    assert payload["disclaimer"]
    assert payload["format"] == "prosperya-f24-draft/v1"
    assert payload["lines"][0]["tax_code"] == "6011"

    csv_export = client.post(
        f"{FISCAL}/companies/{fiscal_company}/f24/{draft['id']}/export",
        headers=admin_headers, json={"format": "csv"})
    assert csv_export.status_code == 200
    assert "6011" in csv_export.text


def test_f24_requires_validated_settlement(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="sale", competence_date="2026-12-05",
              taxable_amount="1000.00", vat_amount="220.00", vat_rate="22",
              source_ref="F24-NOTVAL")
    settlement = calculate(client, admin_headers, fiscal_company, 2026, 12)
    r = client.post(f"{FISCAL}/companies/{fiscal_company}/f24/generate",
                    headers=admin_headers, json={"settlement_id": settlement["id"]})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "settlement_not_validated"


# ---------------------------------------------------------------------------
# Snapshot, RBAC, tenant isolation
# ---------------------------------------------------------------------------

def test_snapshot_aggregates_and_warns(
        client, admin_headers, fiscal_company, rules_synced):
    add_entry(client, admin_headers, fiscal_company,
              direction="purchase", competence_date="2026-04-10",
              taxable_amount="100.00", vat_amount="22.00", vat_rate="22",
              source_ref="SNAP-PEND")
    snap = client.get(f"{FISCAL}/companies/{fiscal_company}/snapshot?year=2026",
                      headers=admin_headers).json()
    assert snap["counters"]["pending_entries"] == 1
    assert any(w["code"] == "vat_entries_pending_review" for w in snap["warnings"])
    assert snap["limitations"]
    assert snap["transmission"]["supported"] is False


def test_fiscal_rbac_boundaries(client, admin_headers, readonly_headers,
                                backoffice_headers, fiscal_company, rules_synced):
    # readonly: reads yes, writes no
    assert client.get(f"{FISCAL}/companies/{fiscal_company}/snapshot",
                      headers=readonly_headers).status_code == 200
    denied = client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries",
                         headers=readonly_headers,
                         json={"direction": "sale", "competence_date": "2026-01-10",
                               "taxable_amount": "10.00", "vat_amount": "2.20",
                               "vat_rate": "22"})
    assert denied.status_code == 403

    # backoffice: writes entries but cannot validate (no fiscal:validate)
    entry = client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries",
                        headers=backoffice_headers,
                        json={"direction": "sale", "competence_date": "2026-01-10",
                              "taxable_amount": "1000.00", "vat_amount": "220.00",
                              "vat_rate": "22", "source_ref": "RBAC-1"})
    assert entry.status_code == 201
    settlement = calculate(client, admin_headers, fiscal_company, 2026, 1)
    forbidden = client.post(
        f"{FISCAL}/companies/{fiscal_company}/settlements/{settlement['id']}/validate",
        headers=backoffice_headers, json={"note": "tentativo"})
    assert forbidden.status_code == 403, "la validazione resta un atto riservato"


def test_fiscal_requires_authentication(client, fiscal_company):
    assert client.get(f"{FISCAL}/companies/{fiscal_company}/snapshot").status_code == 401
    assert client.get(f"{FISCAL}/rule-sets").status_code == 401


def test_fiscal_tenant_isolation(client, admin_headers, fiscal_company):
    slug = f"iso-{uuid.uuid4().hex[:6]}"
    other = client.post(f"{API}/tenants", headers=admin_headers,
                        json={"slug": slug, "display_name": "Altro Tenant"}).json()
    headers = {**admin_headers, "X-Tenant-Id": other["id"]}
    assert client.get(f"{FISCAL}/companies/{fiscal_company}/snapshot",
                      headers=headers).status_code == 404
    assert client.post(f"{FISCAL}/companies/{fiscal_company}/vat-entries",
                       headers=headers,
                       json={"direction": "sale", "competence_date": "2026-01-10",
                             "taxable_amount": "10.00"}).status_code == 404


# ---------------------------------------------------------------------------
# Cockpit / hub integration: fiscal signals are deterministic and ranked
# ---------------------------------------------------------------------------

def test_cockpit_exposes_fiscal_area_and_signals(
        client, admin_headers, demo_company):
    """The seeded demo company has validated fiscal obligations: the cockpit
    must surface them with formula + evidence, never as bare numbers."""
    r = client.get(f"{API}/cockpit/companies/{demo_company}?year=2026&through_month=9",
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    cockpit = r.json()
    fiscal = cockpit["fiscal"]
    assert fiscal["engine_version"].startswith("fiscal-engine")
    assert fiscal["counters"]["validated"] >= 2
    assert fiscal["next_obligation"] is not None
    assert fiscal["transmission"]["supported"] is False

    fiscal_signals = [a for a in cockpit["actions"] if a["category"] == "fiscal"]
    assert fiscal_signals, "i segnali fiscali devono entrare nell'action center"
    assert all(a["formula"] and a["formula_version"] for a in fiscal_signals)
    codes = {a["code"] for a in fiscal_signals}
    assert "fiscal_payment_overdue" in codes, \
        "la scadenza di luglio (20/08) è scaduta rispetto alla data demo"


def test_hub_ranks_fiscal_signals_and_flags_liquidity_risk(
        client, admin_headers, demo_company):
    r = client.get(f"{API}/cockpit/hub?year=2026&through_month=9",
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    hub = r.json()
    demo = next(e for e in hub["companies"] if e["company"]["id"] == demo_company)
    assert demo["fiscal"]["open_deadlines"] >= 1
    assert demo["fiscal"]["validated_settlements"] >= 2

    fiscal_actions = [a for a in hub["actions"]
                      if a.get("company_id") == demo_company
                      and a["category"] == "fiscal"]
    assert fiscal_actions
    # the demo forecast goes negative inside the horizon: a validated fiscal
    # obligation falling on a negative-balance day must raise the cross signal
    liquidity = [a for a in fiscal_actions if a["code"] == "fiscal_liquidity_risk"]
    assert liquidity, "obbligazione fiscale validata su saldo proiettato negativo"
    assert liquidity[0]["severity"] == "critical"
    assert liquidity[0]["action_required"] is True
    assert liquidity[0]["evidence"]["uncovered"]


def test_fiscal_signals_do_not_leak_across_tenants(client, admin_headers):
    slug = f"iso-{uuid.uuid4().hex[:6]}"
    other = client.post(f"{API}/tenants", headers=admin_headers,
                        json={"slug": slug, "display_name": "Altro Tenant"}).json()
    headers = {**admin_headers, "X-Tenant-Id": other["id"]}
    hub = client.get(f"{API}/cockpit/hub?year=2026&through_month=9",
                     headers=headers).json()
    assert not [a for a in hub["actions"] if a["category"] == "fiscal"]


# ---------------------------------------------------------------------------
# Pure engine unit tests (golden cases on rules.py)
# ---------------------------------------------------------------------------

def test_compute_settlement_golden_cases():
    payload = {"minimum_payment_amount": "100.00",
               "quarterly": {"interest_rate_percent": "1.00"}}

    def run(debit, credit, prior_credit="0.00", prior_debit="0.00",
            frequency="monthly", q4=False):
        return rules.compute_settlement(
            rules.SettlementInput(
                debit_total=Decimal(debit), credit_total=Decimal(credit),
                prior_credit=Decimal(prior_credit),
                prior_small_debit=Decimal(prior_debit),
                frequency=frequency, is_fourth_quarter=q4),
            payload)

    m = run("2200.00", "660.00")
    assert (m.net_position, m.payable_amount, m.outcome) == \
        (Decimal("1540.00"), Decimal("1540.00"), "payable")

    m = run("100.00", "50.00")
    assert m.payable_amount is None and m.carry_forward_debit == Decimal("50.00")
    assert m.outcome == "carried_forward_debit"

    m = run("100.00", "500.00")
    assert m.carry_forward_credit == Decimal("400.00") and m.outcome == "credit"

    m = run("500.00", "0.00", prior_credit="600.00")
    assert m.net_position == Decimal("-100.00") and m.outcome == "credit"

    m = run("60.00", "0.00", prior_debit="50.00")
    assert m.payable_amount == Decimal("110.00"), \
        "il debito pregresso sotto soglia si somma al netto"

    m = run("2200.00", "0.00", frequency="quarterly")
    assert m.interest_amount == Decimal("22.00")
    assert m.payable_amount == Decimal("2222.00")

    m = run("0.00", "0.00")
    assert m.outcome == "zero" and m.payable_amount is None


def test_due_date_calendar_golden_cases():
    calendar_payload = rules.SEEDED_RULE_SETS[1]["payload"]

    # 16 maggio 2026 è sabato → lunedì 18
    due = rules.resolve_due_date(date(2026, 5, 16), calendar_payload)
    assert due.due_date == date(2026, 5, 18) and due.status == "resolved"
    assert any("weekend_holiday_deferral" in r for r in due.applied_rules)

    # 16 agosto 2026 (domenica) nella finestra 1–20 agosto → 20 agosto
    due = rules.resolve_due_date(date(2026, 8, 16), calendar_payload)
    assert due.due_date == date(2026, 8, 20)
    assert any("august_deferral" in r for r in due.applied_rules)

    # lunedì dell'Angelo 2026 (6 aprile) è festivo → 7 aprile
    due = rules.resolve_due_date(date(2026, 4, 6), calendar_payload)
    assert due.due_date == date(2026, 4, 7)

    # giorno feriale ordinario: nessun differimento
    due = rules.resolve_due_date(date(2026, 6, 16), calendar_payload)
    assert due.due_date == date(2026, 6, 16) and not due.applied_rules


def test_easter_and_holidays():
    assert rules.easter_sunday(2026) == date(2026, 4, 5)
    assert rules.easter_sunday(2027) == date(2027, 3, 28)
    holidays = rules.national_holidays(2026, rules.SEEDED_RULE_SETS[1]["payload"])
    assert date(2026, 4, 6) in holidays      # lunedì dell'Angelo
    assert date(2026, 12, 26) in holidays    # S. Stefano
    assert date(2026, 8, 15) in holidays     # Ferragosto


def test_statutory_due_dates_and_period_bounds():
    vat_payload = rules.SEEDED_RULE_SETS[0]["payload"]
    assert rules.statutory_due_date(2026, 3, "monthly", vat_payload) == date(2026, 4, 16)
    assert rules.statutory_due_date(2026, 12, "monthly", vat_payload) == date(2027, 1, 16)
    assert rules.statutory_due_date(2026, 1, "quarterly", vat_payload) == date(2026, 5, 16)
    assert rules.statutory_due_date(2026, 3, "quarterly", vat_payload) == date(2026, 11, 16)
    assert rules.period_bounds(2026, 2, "monthly") == (date(2026, 2, 1), date(2026, 2, 28))
    assert rules.period_bounds(2026, 1, "quarterly") == (date(2026, 1, 1), date(2026, 3, 31))
    with pytest.raises(ValueError):
        rules.period_bounds(2026, 13, "monthly")


def test_f24_rounding_and_tax_code_selection():
    fmt = rules.SEEDED_RULE_SETS[2]["payload"]
    assert rules.quantize_f24(Decimal("100.005"), fmt) == Decimal("100.01")
    assert rules.quantize_f24(Decimal("100.004"), fmt) == Decimal("100.00")

    class Code:
        def __init__(self, usage, ref):
            self.usage, self.reference_number = usage, ref

    codes = [Code("vat_monthly", 11), Code("vat_quarterly", 1)]
    assert rules.tax_code_for("monthly", 11, codes).reference_number == 11
    assert rules.tax_code_for("quarterly", 1, codes).reference_number == 1
    assert rules.tax_code_for("monthly", 12, codes) is None


def test_supported_period_boundaries():
    vat_payload = rules.SEEDED_RULE_SETS[0]["payload"]
    assert rules.is_supported_period("monthly", 12, vat_payload) == (True, None)
    ok, reason = rules.is_supported_period("quarterly", 4, vat_payload)
    assert ok is False and reason
    assert rules.is_supported_period("quarterly", 3, vat_payload) == (True, None)
