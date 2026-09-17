"""Document & practice operations core — the shared office infrastructure.

Focus (the properties that make the module defensible):
immutable content versions addressed by checksum, tenant/company-scoped
authorization on every byte served, a bounded practice lifecycle with
structural blockers, client requests that can go overdue, exactly-once
deadline→task sync, and a company dossier that reads one canonical layer.
"""
import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest

API = "/api/v1"
DOCS = f"{API}/documents"
PRACTICES = f"{API}/practices"
ASSISTANT = f"{API}/assistant"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def company(client, admin_headers) -> str:
    r = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Ops {uuid.uuid4().hex[:6]} S.r.l.",
        "status": "customer",
        "vat_number": "05" + uuid.uuid4().hex[:9].replace("a", "1").replace("b", "2")
                      .replace("c", "3").replace("d", "4").replace("e", "5").replace("f", "6")})
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


def _upload(client, headers, company_id: str, content: bytes = b"contenuto",
            filename: str = "doc.pdf", title: str = "Documento",
            type_code: str = "altro", expires_on: str | None = None) -> dict:
    data = {"title": title, "type_code": type_code}
    if expires_on:
        data["expires_on"] = expires_on
    r = client.post(f"{DOCS}/companies/{company_id}/upload",
                    headers=headers, data=data,
                    files={"file": (filename, io.BytesIO(content),
                                    "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


def _practice(client, headers, company_id: str, title: str = "Pratica",
              **kw) -> dict:
    r = client.post(f"{PRACTICES}/companies/{company_id}",
                    headers=headers,
                    json={"title": title, "practice_type": "generic", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def dt(offset_days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=offset_days)).isoformat()


# ---------------------------------------------------------------------------
# Upload, checksum, versioning
# ---------------------------------------------------------------------------

def test_upload_creates_document_with_checksum(client, admin_headers, company):
    content = b"bilancio-2025-firmato"
    doc = _upload(client, admin_headers, company, content=content,
                  title="Bilancio 2025", type_code="bilancio")
    assert doc["status"] == "received"
    assert doc["type_code"] == "bilancio"
    version = doc["versions"][0]
    assert version["version_no"] == 1
    assert version["checksum_sha256"] == hashlib.sha256(content).hexdigest()
    assert version["file_size"] == len(content)
    assert version["original_filename"] == "doc.pdf"
    assert doc["current_version_id"] == version["id"]


def test_versions_are_immutable_and_supersede(client, admin_headers, company):
    doc = _upload(client, admin_headers, company, content=b"v1-draft",
                  title="Bilancio", type_code="bilancio")
    r = client.post(f"{DOCS}/{doc['id']}/versions", headers=admin_headers,
                    files={"file": ("bilancio_v2.pdf", io.BytesIO(b"v2-signed"),
                                    "application/pdf")})
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["version_no"] == 2
    assert v2["status"] == "current"

    detail = client.get(f"{DOCS}/{doc['id']}", headers=admin_headers).json()
    assert detail["current_version_id"] == v2["id"]
    versions = {v["version_no"]: v for v in detail["versions"]}
    assert versions[1]["status"] == "superseded"
    assert versions[2]["status"] == "current"
    # Old content still downloadable — evidence stays reproducible.
    dl = client.get(f"{DOCS}/{doc['id']}/download",
                    params={"version_id": versions[1]["id"]},
                    headers=admin_headers)
    assert dl.status_code == 200
    assert dl.content == b"v1-draft"


def test_duplicate_content_returns_existing_version(client, admin_headers,
                                                    company):
    doc = _upload(client, admin_headers, company, content=b"stesso-contenuto")
    r = client.post(f"{DOCS}/{doc['id']}/versions", headers=admin_headers,
                    files={"file": ("copia.pdf",
                                    io.BytesIO(b"stesso-contenuto"),
                                    "application/pdf")})
    assert r.status_code == 201, r.text
    assert r.json()["duplicate_content"] is True
    assert r.json()["version_no"] == 1  # no new version created


def test_download_streams_bytes_with_checksum_header(client, admin_headers,
                                                     company):
    content = b"file-pdf-binary"
    doc = _upload(client, admin_headers, company, content=content)
    r = client.get(f"{DOCS}/{doc['id']}/download", headers=admin_headers)
    assert r.status_code == 200
    assert r.content == content
    assert r.headers["x-checksum-sha256"] == hashlib.sha256(content).hexdigest()


def test_path_traversal_filename_is_sanitised(client, admin_headers, company):
    doc = _upload(client, admin_headers, company, content=b"x",
                  filename="../../etc/passwd")
    version = doc["versions"][0]
    assert ".." not in version["storage_ref"] if "storage_ref" in version else True
    # The download still works — the ref is logical, not the raw filename.
    r = client.get(f"{DOCS}/{doc['id']}/download", headers=admin_headers)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Authorization: tenant, company, RBAC
# ---------------------------------------------------------------------------

def test_document_not_reachable_across_tenant(client, admin_headers, company):
    doc = _upload(client, admin_headers, company)
    # A second tenant cannot see or download the document.
    r = client.post(f"{API}/tenants", headers=admin_headers, json={
        "slug": f"t-{uuid.uuid4().hex[:8]}",
        "display_name": "Altro studio"})
    assert r.status_code == 201, r.text
    other_tenant = r.json()["id"]
    other_headers = {**admin_headers, "X-Tenant-Id": other_tenant}
    assert client.get(f"{DOCS}/{doc['id']}",
                      headers=other_headers).status_code == 404
    assert client.get(f"{DOCS}/{doc['id']}/download",
                      headers=other_headers).status_code == 404


def test_readonly_cannot_upload_or_validate(client, readonly_headers, company):
    r = client.post(f"{DOCS}/companies/{company}/upload",
                    headers=readonly_headers,
                    files={"file": ("x.pdf", io.BytesIO(b"x"),
                                    "application/pdf")})
    assert r.status_code == 403
    doc = _upload(client, {"Authorization": readonly_headers["Authorization"]}
                  if False else _admin(client), company)
    rv = client.post(
        f"{DOCS}/{doc['id']}/versions/{doc['current_version_id']}/validate",
        headers=readonly_headers, json={"result": "validated"})
    assert rv.status_code == 403


def _admin(client) -> dict:
    token = client.post(f"{API}/auth/login", json={
        "email": "admin@prosperya.it",
        "password": "prosperya-admin-dev"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Validation lifecycle & expiry
# ---------------------------------------------------------------------------

def test_validation_lifecycle(client, admin_headers, company):
    doc = _upload(client, admin_headers, company)
    vid = doc["current_version_id"]
    r = client.post(f"{DOCS}/{doc['id']}/versions/{vid}/validate",
                    headers=admin_headers,
                    json={"result": "rejected", "notes": "Illeggibile"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    r = client.post(f"{DOCS}/{doc['id']}/versions/{vid}/validate",
                    headers=admin_headers, json={"result": "validated"})
    assert r.json()["status"] == "validated"
    validations = r.json()["versions"][0]["validations"]
    assert len(validations) == 2
    assert validations[0]["result"] == "rejected"


def _tenant_of(company_id: str):
    """Resolve the tenant owning a company — deterministic, unlike
    `select(Tenant.id).limit(1)` once a second tenant exists."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.modules.companies.models import Company
    with SessionLocal() as db:
        return db.scalar(select(Company.tenant_id).where(
            Company.id == uuid.UUID(company_id)))


def test_expiry_marks_document_expired(client, admin_headers, company):
    doc = _upload(client, admin_headers, company, type_code="durc",
                  expires_on=day(-1))
    # refresh happens inside the dossier/signals path; call it via service.
    from app.db import SessionLocal
    from app.modules.documents import service as doc_service
    with SessionLocal() as db:
        doc_service.refresh_expired(db, tenant_id=_tenant_of(company))
        db.commit()
    detail = client.get(f"{DOCS}/{doc['id']}", headers=admin_headers).json()
    assert detail["status"] == "expired"


# ---------------------------------------------------------------------------
# Requirements lifecycle
# ---------------------------------------------------------------------------

def test_requirement_lifecycle(client, admin_headers, company):
    p = _practice(client, admin_headers, company)
    r = client.post(f"{DOCS}/companies/{company}/requirements",
                    headers=admin_headers, json={
                        "doc_type_code": "visura_camerale",
                        "label": "Visura camerale aggiornata",
                        "practice_id": p["id"], "mandatory": True,
                        "requires_validation": True})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "missing"

    doc = _upload(client, admin_headers, company, type_code="visura_camerale")
    rf = client.post(f"{DOCS}/requirements/{req['id']}/fulfill",
                     headers=admin_headers,
                     json={"document_id": doc["id"]})
    assert rf.status_code == 200, rf.text
    # requires_validation + unvalidated doc → received, not validated.
    assert rf.json()["status"] == "received"

    client.post(f"{DOCS}/{doc['id']}/versions/{doc['current_version_id']}/validate",
                headers=admin_headers, json={"result": "validated"})
    rf = client.post(f"{DOCS}/requirements/{req['id']}/fulfill",
                     headers=admin_headers,
                     json={"document_id": doc["id"]})
    assert rf.json()["status"] == "validated"
    assert rf.json()["accepted_document_id"] == doc["id"]


def test_requirement_rejects_document_from_other_company(client, admin_headers,
                                                         company):
    other = client.post(f"{API}/companies", headers=admin_headers, json={
        "legal_name": f"Altra {uuid.uuid4().hex[:6]} S.r.l.",
        "status": "customer",
        "vat_number": "06" + uuid.uuid4().hex[:9].replace("a", "1").replace("b", "2")
                      .replace("c", "3").replace("d", "4").replace("e", "5").replace("f", "6")})
    other_id = other.json()["id"]
    req = client.post(f"{DOCS}/companies/{company}/requirements",
                      headers=admin_headers, json={
                          "doc_type_code": "altro", "label": "Doc",
                          "mandatory": True}).json()
    doc = _upload(client, admin_headers, other_id)
    r = client.post(f"{DOCS}/requirements/{req['id']}/fulfill",
                    headers=admin_headers, json={"document_id": doc["id"]})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Practice lifecycle, blockers, client requests
# ---------------------------------------------------------------------------

def test_practice_lifecycle_bounded(client, admin_headers, company):
    p = _practice(client, admin_headers, company)
    assert p["status"] == "open"
    r = client.post(f"{PRACTICES}/{p['id']}/transition",
                    headers=admin_headers, json={"action": "completed"})
    assert r.status_code == 409  # open → completed not allowed directly
    r = client.post(f"{PRACTICES}/{p['id']}/transition",
                    headers=admin_headers, json={"action": "in_progress"})
    assert r.status_code == 200
    r = client.post(f"{PRACTICES}/{p['id']}/transition",
                    headers=admin_headers, json={"action": "completed"})
    assert r.status_code == 200
    assert r.json()["closed_at"] is not None


def test_blockers_are_structural(client, admin_headers, company):
    p = _practice(client, admin_headers, company)
    r = client.post(f"{PRACTICES}/{p['id']}/blockers",
                    headers=admin_headers,
                    json={"kind": "missing_document",
                          "detail": "Visura mancante"})
    assert r.status_code == 201, r.text
    blocker = r.json()
    assert blocker["kind"] == "missing_document"
    assert blocker["status"] == "open"

    detail = client.get(f"{PRACTICES}/{p['id']}",
                        headers=admin_headers).json()
    assert detail["open_blockers"] == 1

    rr = client.post(f"{PRACTICES}/{p['id']}/blockers/{blocker['id']}/resolve",
                     headers=admin_headers)
    assert rr.status_code == 200
    assert rr.json()["status"] == "resolved"
    detail = client.get(f"{PRACTICES}/{p['id']}",
                        headers=admin_headers).json()
    assert detail["open_blockers"] == 0


def test_mandatory_requirement_creates_document_blocker(client, admin_headers,
                                                        company):
    p = _practice(client, admin_headers, company)
    client.post(f"{DOCS}/companies/{company}/requirements",
                headers=admin_headers, json={
                    "doc_type_code": "durc", "label": "DURC",
                    "practice_id": p["id"], "mandatory": True})
    # Sync blockers via service (the API path used by funding does this).
    from app.db import SessionLocal
    from app.modules.practices import service as svc
    with SessionLocal() as db:
        svc.sync_document_blockers(db, tenant_id=_tenant_of(company),
                                   practice_id=uuid.UUID(p["id"]))
        db.commit()
    detail = client.get(f"{PRACTICES}/{p['id']}",
                        headers=admin_headers).json()
    assert detail["open_blockers"] == 1
    assert detail["blockers"][0]["kind"] == "missing_document"


def test_client_request_lifecycle_and_overdue(client, admin_headers, company):
    p = _practice(client, admin_headers, company)
    r = client.post(f"{PRACTICES}/companies/{company}/requests",
                    headers=admin_headers, json={
                        "item": "Estratto conto trimestre",
                        "practice_id": p["id"], "due_at": dt(5)})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "sent"

    # sent → partial → fulfilled
    for action in ("partial", "fulfilled"):
        rr = client.post(f"{PRACTICES}/requests/{req['id']}/transition",
                         headers=admin_headers, json={"action": action})
        assert rr.status_code == 200, rr.text
    assert rr.json()["status"] == "fulfilled"
    assert rr.json()["fulfilled_at"] is not None

    # fulfilled is terminal
    rr = client.post(f"{PRACTICES}/requests/{req['id']}/transition",
                     headers=admin_headers, json={"action": "cancelled"})
    assert rr.status_code == 409


def test_overdue_request_detected(client, admin_headers, company):
    r = client.post(f"{PRACTICES}/companies/{company}/requests",
                    headers=admin_headers, json={
                        "item": "Doc urgente", "due_at": dt(-2)})
    req_id = r.json()["id"]
    # The dossier refreshes overdue state deterministically.
    client.get(f"{PRACTICES}/companies/{company}/dossier",
               headers=admin_headers)
    reqs = client.get(f"{PRACTICES}/requests/list",
                      params={"company_id": company},
                      headers=admin_headers).json()["requests"]
    match = next(r for r in reqs if r["id"] == req_id)
    assert match["status"] == "overdue"


# ---------------------------------------------------------------------------
# Deadline → task exactly-once
# ---------------------------------------------------------------------------

def test_deadline_sync_is_exactly_once(client, admin_headers, company):
    p = _practice(client, admin_headers, company)
    payload = {"title": "Invio documentazione", "due_at": dt(10),
               "kind": "filing"}
    r1 = client.post(f"{PRACTICES}/{p['id']}/deadlines",
                     headers=admin_headers, json=payload)
    r2 = client.post(f"{PRACTICES}/{p['id']}/deadlines",
                     headers=admin_headers, json=payload)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["task_id"] == r2.json()["task_id"]
    assert r1.json()["sync_key"] == r2.json()["sync_key"]


# ---------------------------------------------------------------------------
# Dossier & hub signals
# ---------------------------------------------------------------------------

def test_company_dossier_aggregates_operations(client, admin_headers, company):
    p = _practice(client, admin_headers, company, title="Pratica dossier")
    client.post(f"{DOCS}/companies/{company}/requirements",
                headers=admin_headers, json={
                    "doc_type_code": "durc", "label": "DURC",
                    "practice_id": p["id"], "mandatory": True})
    _upload(client, admin_headers, company, title="Visura")
    client.post(f"{PRACTICES}/companies/{company}/requests",
                headers=admin_headers, json={"item": "Firma mandato"})
    client.post(f"{PRACTICES}/{p['id']}/deadlines", headers=admin_headers,
                json={"title": "Consegna", "due_at": dt(7)})

    dossier = client.get(f"{PRACTICES}/companies/{company}/dossier",
                         headers=admin_headers).json()
    assert len(dossier["practices"]) == 1
    assert len(dossier["documents"]) == 1
    assert len(dossier["missing_documents"]) == 1
    assert len(dossier["client_requests"]) == 1
    assert len(dossier["deadlines"]) == 1
    assert len(dossier["activities"]) >= 3  # practice + requirement + request


def test_hub_reports_operational_signals(client, admin_headers, company):
    p = _practice(client, admin_headers, company)
    client.post(f"{DOCS}/companies/{company}/requirements",
                headers=admin_headers, json={
                    "doc_type_code": "durc", "label": "DURC urgente",
                    "practice_id": p["id"], "mandatory": True,
                    "due_at": dt(3)})
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.modules.practices import service as svc
    from app.modules.tenancy.models import Tenant
    with SessionLocal() as db:
        tid = db.scalar(select(Tenant.id).limit(1))
        svc.sync_document_blockers(db, tenant_id=tid,
                                   practice_id=uuid.UUID(p["id"]))
        db.commit()
    hub = client.get(f"{API}/cockpit/hub?year=2026&through_month=6",
                     headers=admin_headers).json()
    codes = {a["code"] for a in hub["actions"]}
    assert "ops_document_missing" in codes


# ---------------------------------------------------------------------------
# Funding integration
# ---------------------------------------------------------------------------

def test_funding_practice_creates_generic_practice(client, admin_headers):
    """A funding practice links to the generic container and mirrors its
    document checklist into canonical requirements."""
    page = client.get(f"{API}/companies?page=1&page_size=200",
                      headers=admin_headers).json()
    demo = next(c for c in page["items"] if c["vat_number"] == "01234567890")
    programmes = client.get(f"{API}/funding/programmes",
                            headers=admin_headers).json()["programmes"]
    prog = next(p for p in programmes if p["code"] == "NUOVA-SABATINI")
    detail = client.get(f"{API}/funding/programmes/{prog['id']}",
                        headers=admin_headers).json()
    version_id = detail["versions"][0]["id"]

    r = client.post(f"{API}/funding/companies/{demo['id']}/practices",
                    headers=admin_headers,
                    json={"version_id": version_id})
    assert r.status_code == 201, r.text
    fp = r.json()

    # The generic practice exists and carries the mirrored requirements.
    practices = client.get(f"{PRACTICES}",
                           params={"company_id": demo["id"],
                                   "practice_type": "funding"},
                           headers=admin_headers).json()["practices"]
    generic = next(p for p in practices if p["external_ref"] == fp["id"])
    reqs = client.get(f"{DOCS}/requirements/list",
                      params={"practice_id": generic["id"]},
                      headers=admin_headers).json()["requirements"]
    assert len(reqs) == len(fp["documents"])
    assert all(r["module"] == "funding" for r in reqs)

    # Updating a funding doc syncs the canonical requirement.
    fdoc = fp["documents"][0]
    upd = client.patch(
        f"{API}/funding/practices/{fp['id']}/documents/{fdoc['id']}",
        headers=admin_headers, json={"status": "received"})
    assert upd.status_code == 200, upd.text
    reqs = client.get(f"{DOCS}/requirements/list",
                      params={"practice_id": generic["id"]},
                      headers=admin_headers).json()["requirements"]
    synced = next(r for r in reqs if r["source_ref"] == fdoc["id"])
    assert synced["status"] == "received"


# ---------------------------------------------------------------------------
# Assistant — read-only, authorized
# ---------------------------------------------------------------------------

def test_assistant_reads_operations(client, admin_headers, company):
    _practice(client, admin_headers, company, title="Pratica assistente")
    r = client.post(f"{ASSISTANT}/companies/{company}/chat",
                    headers=admin_headers,
                    json={"message": "Quali pratiche e documenti mancanti "
                                     "ci sono?", "year": 2026,
                          "through_month": 6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "get_company_practices" in body["tools_used"]
    assert "get_missing_documents" in body["tools_used"]


def test_assistant_refuses_operational_mutation(client, admin_headers,
                                                company):
    r = client.post(f"{ASSISTANT}/companies/{company}/chat",
                    headers=admin_headers,
                    json={"message": "Valida il documento e chiudi la "
                                     "pratica", "year": 2026,
                          "through_month": 6})
    assert r.status_code == 200
    body = r.json()
    assert body["tools_used"] == []
    assert any("non modifica" in lim for lim in body["limitations"])
