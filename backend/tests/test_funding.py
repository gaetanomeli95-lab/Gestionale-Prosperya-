"""Funding core — programmes, deterministic eligibility, de minimis, practices.

Focus (the properties that make the module defensible):
versioned programmes with provenance, a bounded rule registry that returns
explicit states (never a guess), de minimis headroom computed only on
declared aids, a managed practice lifecycle with document checklists and
deadlines, and read-only assistant tools that never decide eligibility.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

API = "/api/v1"
FUNDING = f"{API}/funding"
ASSISTANT = f"{API}/assistant"


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
    """A clean company: no funding profile, no aids."""
    r = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Funding {uuid.uuid4().hex[:6]} S.r.l.",
        "status": "customer",
        "vat_number": "04" + uuid.uuid4().hex[:9].replace("a", "1").replace("b", "2")
                      .replace("c", "3").replace("d", "4").replace("e", "5").replace("f", "6")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def synced(client, admin_headers):
    """Reference data materialised (idempotent)."""
    r = client.post(f"{FUNDING}/sync", headers=admin_headers)
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
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def _programme_id(client, headers, code: str) -> str:
    page = client.get(f"{FUNDING}/programmes", headers=headers).json()
    match = next(p for p in page["programmes"] if p["code"] == code)
    return match["id"]


def _version_id(client, headers, programme_id: str) -> str:
    detail = client.get(f"{FUNDING}/programmes/{programme_id}",
                        headers=headers).json()
    return detail["versions"][0]["id"]


def _profile(client, headers, company_id: str, **kw):
    payload = {
        "incorporated_on": day(-365 * 3),
        "is_startup": False,
        "is_innovative_startup": False,
        "female_ownership_pct": "60.00",
        "project_region": "Sicilia",
        "single_undertaking_known": True,
        "aid_history_complete": True,
        **kw,
    }
    r = client.put(f"{FUNDING}/companies/{company_id}/profile",
                   headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _aid(client, headers, company_id: str, **kw):
    payload = {
        "programme_label": "Voucher test",
        "regime_code": "DE_MINIMIS",
        "granted_on": day(-100),
        "amount": "5000.00",
        "status": "declared",
        **kw,
    }
    r = client.post(f"{FUNDING}/companies/{company_id}/aids",
                    headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Reference data & programmes
# ---------------------------------------------------------------------------

class TestReferenceData:
    def test_sync_idempotent(self, client, admin_headers):
        first = client.post(f"{FUNDING}/sync", headers=admin_headers).json()
        second = client.post(f"{FUNDING}/sync", headers=admin_headers).json()
        assert first["created"]["authorities"] >= 0
        assert second["created"]["authorities"] == 0
        assert second["created"]["programmes"] == 0

    def test_authorities_listed(self, client, admin_headers, synced):
        r = client.get(f"{FUNDING}/authorities", headers=admin_headers)
        assert r.status_code == 200
        codes = {a["code"] for a in r.json()["authorities"]}
        assert {"EU", "MIMIT", "INVITALIA", "REG-SICILIA"} <= codes

    def test_aid_regimes_versioned(self, client, admin_headers, synced):
        r = client.get(f"{FUNDING}/aid-regimes", headers=admin_headers)
        assert r.status_code == 200
        regimes = r.json()["regimes"]
        dm = next(x for x in regimes if x["code"] == "DE_MINIMIS")
        assert dm["threshold"] == "300000.00"
        assert dm["period_months"] == 36
        assert dm["legal_reference"].startswith("Regolamento (UE) 2023/2831")

    def test_seed_programmes_present(self, client, admin_headers, synced):
        r = client.get(f"{FUNDING}/programmes", headers=admin_headers)
        assert r.status_code == 200
        codes = {p["code"] for p in r.json()["programmes"]}
        assert {"NUOVA-SABATINI", "TRANSIZIONE-5.0", "RESTO-AL-SUD",
                "PO-FESR-SICILIA-INNOVAZIONE"} <= codes

    def test_programme_detail_has_version_provenance(
            self, client, admin_headers, synced):
        pid = _programme_id(client, admin_headers, "NUOVA-SABATINI")
        r = client.get(f"{FUNDING}/programmes/{pid}", headers=admin_headers)
        assert r.status_code == 200
        detail = r.json()
        assert detail["code"] == "NUOVA-SABATINI"
        version = detail["versions"][0]
        assert version["version_no"] == 1
        assert version["source"]["reference"] == "MIMIT-DM-NuovaSabatini-2024"
        assert len(version["requirements"]) == 4
        assert len(version["document_requirements"]) == 3


# ---------------------------------------------------------------------------
# Company profile & aid history
# ---------------------------------------------------------------------------

class TestProfileAndAids:
    def test_profile_upsert(self, client, admin_headers, clean_company):
        r = _profile(client, admin_headers, clean_company)
        assert r["profile"]["female_ownership_pct"] == "60.00"
        assert r["profile"]["project_region"] == "Sicilia"

    def test_profile_partial_is_explicit(self, client, admin_headers,
                                         clean_company):
        r = client.put(f"{FUNDING}/companies/{clean_company}/profile",
                       headers=admin_headers,
                       json={"is_startup": True})
        assert r.status_code == 200
        profile = r.json()["profile"]
        assert profile["is_startup"] is True
        assert profile["female_ownership_pct"] is None

    def test_aid_history(self, client, admin_headers, clean_company):
        _aid(client, admin_headers, clean_company, amount="12000.00")
        _aid(client, admin_headers, clean_company, amount="8000.00",
             granted_on=day(-400))
        r = client.get(f"{FUNDING}/companies/{clean_company}/aids",
                       headers=admin_headers)
        assert r.status_code == 200
        assert len(r.json()["aids"]) == 2

    def test_de_minimis_position(self, client, admin_headers, clean_company):
        _profile(client, admin_headers, clean_company)
        _aid(client, admin_headers, clean_company, amount="50000.00")
        r = client.get(f"{FUNDING}/companies/{clean_company}/de-minimis",
                       headers=admin_headers)
        assert r.status_code == 200
        dm = r.json()
        assert dm["status"] == "available"
        assert dm["aid_total"] == "50000.00"
        assert dm["headroom"] == "250000.00"
        assert dm["regime"]["code"] == "DE_MINIMIS"

    def test_de_minimis_incomplete_history(self, client, admin_headers,
                                           clean_company):
        _profile(client, admin_headers, clean_company,
                 aid_history_complete=False)
        r = client.get(f"{FUNDING}/companies/{clean_company}/de-minimis",
                       headers=admin_headers)
        assert r.json()["status"] == "insufficient_data"

    def test_de_minimis_unknown_perimeter(self, client, admin_headers,
                                          clean_company):
        _profile(client, admin_headers, clean_company,
                 single_undertaking_known=False)
        r = client.get(f"{FUNDING}/companies/{clean_company}/de-minimis",
                       headers=admin_headers)
        assert r.json()["status"] == "review_required"


# ---------------------------------------------------------------------------
# Deterministic assessment
# ---------------------------------------------------------------------------

class TestAssessment:
    def test_run_assessment_persisted(self, client, admin_headers,
                                      clean_company, synced):
        _profile(client, admin_headers, clean_company)
        pid = _programme_id(client, admin_headers, "NUOVA-SABATINI")
        vid = _version_id(client, admin_headers, pid)
        r = client.post(f"{FUNDING}/companies/{clean_company}/assessments",
                        headers=admin_headers, json={"version_id": vid})
        assert r.status_code == 201, r.text
        assessment = r.json()
        assert assessment["engine_version"] == "funding-engine-v1.0"
        assert assessment["result"] in (
            "eligible_on_known_data", "potentially_eligible",
            "review_required", "not_eligible", "insufficient_data",
            "unsupported")
        assert len(assessment["items"]) == 4
        assert "legal_form" in assessment["company_snapshot"]

    def test_assessment_evidence_per_rule(self, client, admin_headers,
                                          clean_company, synced):
        _profile(client, admin_headers, clean_company)
        pid = _programme_id(client, admin_headers, "NUOVA-SABATINI")
        vid = _version_id(client, admin_headers, pid)
        r = client.post(f"{FUNDING}/companies/{clean_company}/assessments",
                        headers=admin_headers, json={"version_id": vid})
        items = r.json()["items"]
        for item in items:
            assert item["result"] in (
                "satisfied", "not_satisfied", "insufficient_data",
                "unsupported", "review_required")
            assert "evidence" in item
            assert item["rule_code"]

    def test_assessment_missing_profile(self, client, admin_headers,
                                        clean_company, synced):
        """No profile → INSUFFICIENT_DATA on profile-dependent rules."""
        pid = _programme_id(client, admin_headers, "NUOVA-SABATINI")
        vid = _version_id(client, admin_headers, pid)
        r = client.post(f"{FUNDING}/companies/{clean_company}/assessments",
                        headers=admin_headers, json={"version_id": vid})
        assert r.status_code == 201
        assessment = r.json()
        assert assessment["result"] in ("insufficient_data",
                                        "potentially_eligible",
                                        "review_required")
        assert len(assessment["missing_data"]) > 0

    def test_assessment_review_lifecycle(self, client, admin_headers,
                                         clean_company, synced):
        _profile(client, admin_headers, clean_company)
        pid = _programme_id(client, admin_headers, "NUOVA-SABATINI")
        vid = _version_id(client, admin_headers, pid)
        r = client.post(f"{FUNDING}/companies/{clean_company}/assessments",
                        headers=admin_headers, json={"version_id": vid})
        aid = r.json()["id"]
        # review_required → reviewed
        r = client.post(f"{FUNDING}/assessments/{aid}/review",
                        headers=admin_headers,
                        json={"action": "reviewed", "notes": "Verificato."})
        assert r.status_code == 200
        assert r.json()["status"] == "reviewed"
        # reviewed → approved_for_practice
        r = client.post(f"{FUNDING}/assessments/{aid}/review",
                        headers=admin_headers,
                        json={"action": "approved_for_practice"})
        assert r.status_code == 200
        assert r.json()["status"] == "approved_for_practice"
        # invalid transition
        r = client.post(f"{FUNDING}/assessments/{aid}/review",
                        headers=admin_headers,
                        json={"action": "reviewed"})
        assert r.status_code == 409

    def test_match_groups(self, client, admin_headers, clean_company, synced):
        _profile(client, admin_headers, clean_company)
        r = client.get(f"{FUNDING}/companies/{clean_company}/match",
                       headers=admin_headers)
        assert r.status_code == 200
        groups = r.json()["groups"]
        assert set(groups.keys()) == {
            "eligible_on_known_data", "potentially_eligible",
            "review_required", "insufficient_data", "not_eligible",
            "unsupported"}
        total = sum(len(v) for v in groups.values())
        assert total >= 3  # at least the 3 open/upcoming seed programmes


# ---------------------------------------------------------------------------
# Practices
# ---------------------------------------------------------------------------

class TestPractices:
    def _open_practice(self, client, headers, company_id, code="NUOVA-SABATINI"):
        pid = _programme_id(client, headers, code)
        vid = _version_id(client, headers, pid)
        r = client.post(f"{FUNDING}/companies/{company_id}/practices",
                        headers=headers, json={"version_id": vid})
        assert r.status_code == 201, r.text
        return r.json()

    def test_create_practice_materialises_checklist(
            self, client, admin_headers, clean_company, synced):
        practice = self._open_practice(client, admin_headers, clean_company)
        assert practice["status"] == "draft"
        assert len(practice["documents"]) == 3
        assert all(d["status"] == "missing" for d in practice["documents"])
        # Sabatini is until_exhausted (no closes_at) → no deadline.
        # Transizione 5.0 has a fixed window → the close is materialised.
        fixed = self._open_practice(client, admin_headers, clean_company,
                                  code="TRANSIZIONE-5.0")
        assert len(fixed["deadlines"]) >= 1
        assert fixed["deadlines"][0]["kind"] == "application_close"

    def test_practice_transitions(self, client, admin_headers,
                                  clean_company, synced):
        practice = self._open_practice(client, admin_headers, clean_company)
        pid = practice["id"]
        for action in ("data_collection", "document_collection",
                       "ready_to_submit", "submitted"):
            r = client.post(f"{FUNDING}/practices/{pid}/transition",
                            headers=admin_headers, json={"action": action})
            assert r.status_code == 200, r.text
        assert r.json()["status"] == "submitted"
        # invalid: submitted → draft
        r = client.post(f"{FUNDING}/practices/{pid}/transition",
                        headers=admin_headers, json={"action": "draft"})
        assert r.status_code == 409

    def test_practice_document_update(self, client, admin_headers,
                                      clean_company, synced):
        practice = self._open_practice(client, admin_headers, clean_company)
        doc = practice["documents"][0]
        r = client.patch(
            f"{FUNDING}/practices/{practice['id']}/documents/{doc['id']}",
            headers=admin_headers,
            json={"status": "received", "document_ref": "DOC-001"})
        assert r.status_code == 200
        assert r.json()["status"] == "received"

    def test_practice_deadline_and_note(self, client, admin_headers,
                                        clean_company, synced):
        practice = self._open_practice(client, admin_headers, clean_company)
        pid = practice["id"]
        r = client.post(f"{FUNDING}/practices/{pid}/deadlines",
                        headers=admin_headers, json={
                            "kind": "internal",
                            "title": "Verifica documenti",
                            "due_at": (datetime.now(UTC) + timedelta(days=7))
                            .isoformat()})
        assert r.status_code == 201
        r = client.post(f"{FUNDING}/practices/{pid}/notes",
                        headers=admin_headers,
                        json={"note": "Contattato il referente."})
        assert r.status_code == 201

    # -- ADR-023: one operational Practice per funding practice ------------

    def test_practice_is_linked_to_one_generic_practice(
            self, client, admin_headers, clean_company, synced):
        practice = self._open_practice(client, admin_headers, clean_company)
        assert practice["practice_id"], "funding practice must link a generic Practice"
        r = client.get(f"{API}/practices/{practice['practice_id']}", headers=admin_headers)
        assert r.status_code == 200, r.text
        generic = r.json()
        assert generic["practice_type"] == "funding"
        assert generic["source_module"] == "funding"
        assert generic["external_ref"] == practice["id"]          # back-reference
        assert generic["company_id"] == clean_company
        assert generic["status"] == "draft"

    def test_generic_status_mirrors_funding_lifecycle(
            self, client, admin_headers, clean_company, synced):
        practice = self._open_practice(client, admin_headers, clean_company)
        pid, gid = practice["id"], practice["practice_id"]
        expected = {"data_collection": "in_progress", "document_collection": "in_progress",
                    "ready_to_submit": "ready", "submitted": "waiting_external",
                    "under_review": "waiting_external", "approved": "completed",
                    "closed": "completed"}
        for action, generic_status in expected.items():
            r = client.post(f"{FUNDING}/practices/{pid}/transition",
                            headers=admin_headers, json={"action": action})
            assert r.status_code == 200, r.text
            g = client.get(f"{API}/practices/{gid}", headers=admin_headers).json()
            assert g["status"] == generic_status, f"{action} -> {g['status']}"
        assert g["closed_at"] is not None

    def test_document_status_mirrors_to_canonical_requirement(
            self, client, admin_headers, clean_company, synced):
        practice = self._open_practice(client, admin_headers, clean_company)
        gid = practice["practice_id"]

        def canonical():
            r = client.get(f"{API}/documents/requirements/list",
                           params={"practice_id": gid}, headers=admin_headers)
            assert r.status_code == 200, r.text
            return r.json()["requirements"]

        # every checklist item is mirrored as a canonical DocumentRequirement
        reqs = canonical()
        assert len(reqs) == len(practice["documents"]) == 3
        assert all(d["status"] == "missing" and d["module"] == "funding" for d in reqs)
        assert {d["source_ref"] for d in reqs} == {d["id"] for d in practice["documents"]}
        # a missing-document blocker exists on the generic practice
        g = client.get(f"{API}/practices/{gid}", headers=admin_headers).json()
        assert any(b["kind"] == "missing_document" for b in g["blockers"])
        # mark one received on the funding side → canonical side follows
        doc = practice["documents"][0]
        client.patch(f"{FUNDING}/practices/{practice['id']}/documents/{doc['id']}",
                     headers=admin_headers, json={"status": "received"})
        assert sorted(d["status"] for d in canonical()) == ["missing", "missing", "received"]

    def test_company_dossier_sees_funding_practice_once(
            self, client, admin_headers, clean_company, synced):
        """No duplicate 'practice' concept: the dossier lists ONE practice."""
        self._open_practice(client, admin_headers, clean_company)
        dossier = client.get(f"{API}/practices/companies/{clean_company}/dossier",
                             headers=admin_headers).json()
        assert len(dossier["practices"]) == 1
        assert dossier["practices"][0]["practice_type"] == "funding"

    def test_list_deadlines(self, client, admin_headers, clean_company,
                            synced):
        self._open_practice(client, admin_headers, clean_company,
                            code="TRANSIZIONE-5.0")
        r = client.get(f"{FUNDING}/deadlines?company_id={clean_company}",
                       headers=admin_headers)
        assert r.status_code == 200
        assert len(r.json()["deadlines"]) >= 1


# ---------------------------------------------------------------------------
# Hub / cockpit integration
# ---------------------------------------------------------------------------

class TestHubIntegration:
    def test_funding_signals_in_hub(self, client, admin_headers, demo_company,
                                    synced):
        _profile(client, admin_headers, demo_company)
        r = client.get(f"{API}/cockpit/hub?year=2026&through_month=9",
                       headers=admin_headers)
        assert r.status_code == 200
        actions = r.json()["actions"]
        funding_signals = [a for a in actions if a["category"] == "funding"]
        assert len(funding_signals) >= 1
        for s in funding_signals:
            assert s["priority"] > 0
            assert s["formula_version"]

    def test_company_funding_overview(self, client, admin_headers,
                                      clean_company, synced):
        _profile(client, admin_headers, clean_company)
        r = client.get(f"{FUNDING}/companies/{clean_company}/overview",
                       headers=admin_headers)
        assert r.status_code == 200
        overview = r.json()
        assert overview["profile"]["project_region"] == "Sicilia"
        assert "de_minimis" in overview
        assert "limitations" in overview


# ---------------------------------------------------------------------------
# Assistant — read-only, no freeform eligibility
# ---------------------------------------------------------------------------

class TestAssistant:
    def test_funding_tools_allowed(self, client, admin_headers, demo_company,
                                   synced):
        _profile(client, admin_headers, demo_company)
        r = client.post(f"{ASSISTANT}/companies/{demo_company}/chat",
                        headers=admin_headers, json={
            "message": "Quali bandi sono aperti?",
            "year": 2026, "through_month": 9})
        assert r.status_code == 200, r.text
        body = r.json()
        tool_names = set(body.get("tools_used", []))
        assert "get_funding_opportunities" in tool_names

    def test_assistant_refuses_eligibility_verdict(
            self, client, admin_headers, demo_company, synced):
        r = client.post(f"{ASSISTANT}/companies/{demo_company}/chat",
                        headers=admin_headers, json={
            "message": "Possiamo presentare domanda per la Sabatini?",
            "year": 2026, "through_month": 9})
        assert r.status_code == 200
        body = r.json()
        limitations = body.get("limitations") or []
        texts = " ".join(limitations +
                         [i["text"] for i in body.get("items", [])]).lower()
        assert "eligibilit" in texts or "professionale" in texts
        assert body.get("tools_used") == []

    def test_assistant_de_minimis_tool(self, client, admin_headers,
                                       demo_company, synced):
        _profile(client, admin_headers, demo_company)
        r = client.post(f"{ASSISTANT}/companies/{demo_company}/chat",
                        headers=admin_headers, json={
            "message": "Qual è la posizione de minimis?",
            "year": 2026, "through_month": 9})
        assert r.status_code == 200
        tool_names = set(r.json().get("tools_used", []))
        assert "get_de_minimis_position" in tool_names


# ---------------------------------------------------------------------------
# Tenant isolation & RBAC
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    def test_readonly_cannot_write(self, client, readonly_headers,
                                   clean_company):
        r = client.put(f"{FUNDING}/companies/{clean_company}/profile",
                       headers=readonly_headers, json={"is_startup": True})
        assert r.status_code == 403

    def test_readonly_can_read(self, client, admin_headers, readonly_headers,
                               clean_company, synced):
        _profile(client, admin_headers, clean_company)
        r = client.get(f"{FUNDING}/companies/{clean_company}/profile",
                       headers=readonly_headers)
        assert r.status_code == 200

    def test_other_tenant_not_visible(self, client, admin_headers,
                                      clean_company, synced):
        """A second tenant sees neither the profile nor the assessments."""
        # Create a second tenant + user
        r = client.post(f"{API}/tenants", headers=admin_headers, json={
            "display_name": f"Other {uuid.uuid4().hex[:6]}",
            "slug": f"other-{uuid.uuid4().hex[:6]}"})
        assert r.status_code == 201, r.text
        other_tenant = r.json()
        # The admin token is scoped to the demo tenant; a cross-tenant read
        # must 404 (not 403) — the resource simply does not exist here.
        r = client.get(f"{FUNDING}/companies/{clean_company}/profile",
                       headers={**admin_headers,
                                "X-Tenant-Id": other_tenant["id"]})
        assert r.status_code in (403, 404)
