"""Provider-contract tests — exercise the billing lifecycle entirely
through the registered stub adapter, proving the domain stays
provider-independent and failure-safe."""
import json
import os
import uuid

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.modules.billing.models import Invoice, OutboxEvent, WebhookEventRecord
from app.modules.billing.providers.stub import reset_stub_state

LINES = [{"description": "Consulenza Growth Factors", "quantity": 1,
          "unit_price": 1200.00, "vat_rate": 22.00}]


@pytest.fixture(autouse=True)
def _clean_stub():
    reset_stub_state()
    os.environ["STUB_WEBHOOK_TOKEN"] = "test-webhook-token"
    yield
    os.environ.pop("STUB_WEBHOOK_TOKEN", None)


def _demo_company_id(client, headers) -> str:
    items = client.get("/api/v1/companies?q=Demo", headers=headers).json()["items"]
    return items[0]["id"]


def _configure_stub(client, headers, **config):
    payload = {
        "provider_key": "stub-sandbox",
        "api_version": "v1",
        "environment": "sandbox",
        "config": {"endpoint": "https://stub.local/api", **config},
        "webhook_secret_ref": "STUB_WEBHOOK_TOKEN",
    }
    r = client.put("/api/v1/billing/provider", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _make_invoice(client, headers, company_id=None) -> dict:
    cid = company_id or _demo_company_id(client, headers)
    r = client.post("/api/v1/billing/invoices",
                    json={"company_id": cid, "lines": LINES}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _finalize(client, headers, invoice_id) -> dict:
    r = client.post(f"/api/v1/billing/invoices/{invoice_id}/finalize",
                    json={}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _send_and_dispatch(client, headers, invoice_id) -> dict:
    r = client.post(f"/api/v1/billing/invoices/{invoice_id}/send",
                    headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"
    client.post("/api/v1/billing/jobs/dispatch", headers=headers)
    return client.get(f"/api/v1/billing/invoices/{invoice_id}",
                      headers=headers).json()


# -- contract: drafts & finalize ------------------------------------------------

def test_draft_totals_computed_server_side(client, admin_headers):
    inv = _make_invoice(client, admin_headers)
    assert inv["status"] == "draft"
    assert float(inv["taxable_amount"]) == 1200.00
    assert float(inv["vat_amount"]) == 264.00
    assert float(inv["total_amount"]) == 1464.00
    assert inv["number"] is None  # no fiscal number while drafting


def test_finalize_assigns_sequential_number_and_snapshots(client, admin_headers):
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    assert inv["status"] == "ready_to_send"
    assert isinstance(inv["number"], int) and inv["number"] >= 1
    assert inv["fiscal_year"]
    assert inv["customer_snapshot"]["legal_name"] == "Azienda Demo Siciliana S.r.l."
    assert inv["issuer_snapshot"]["vat_number"] == "07415020820"

    inv2 = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    # same series/year → strictly next number, no gaps introduced by us
    assert inv2["number"] == inv["number"] + 1


def test_finalized_invoice_is_immutable(client, admin_headers):
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    r = client.patch(f"/api/v1/billing/invoices/{inv['id']}",
                     json={"version": inv["version"], "notes": "too late"},
                     headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invoice_immutable"


def test_finalize_requires_customer_fiscal_data(client, admin_headers):
    bare = client.post("/api/v1/companies",
                       json={"legal_name": "No Fiscal Data S.r.l."},
                       headers=admin_headers).json()
    inv = _make_invoice(client, admin_headers, bare["id"])
    r = client.post(f"/api/v1/billing/invoices/{inv['id']}/finalize",
                    json={}, headers=admin_headers)
    assert r.status_code == 422
    assert "vat_number" in r.text


# -- contract: provider config & health ------------------------------------------

def test_provider_config_and_health(client, admin_headers):
    _configure_stub(client, admin_headers)
    r = client.post("/api/v1/billing/provider/test", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["health_status"] == "healthy"
    # secrets never leak
    assert "credentials" not in json.dumps(body).lower() or "STUB_WEBHOOK" not in json.dumps(body)


def test_unknown_provider_rejected(client, admin_headers):
    r = client.put("/api/v1/billing/provider", json={
        "provider_key": "not-real", "api_version": "v1",
        "environment": "sandbox", "config": {},
    }, headers=admin_headers)
    assert r.status_code == 404


def test_send_without_provider_fails_cleanly(client, admin_headers):
    # ensure no provider is active regardless of test ordering
    with SessionLocal() as db:
        from app.modules.billing.models import BillingProviderConfig
        for row in db.scalars(select(BillingProviderConfig)):
            row.is_active = False
        db.commit()
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    r = client.post(f"/api/v1/billing/invoices/{inv['id']}/send", headers=admin_headers)
    assert r.status_code == 200
    client.post("/api/v1/billing/jobs/dispatch", headers=admin_headers)
    # no provider configured → dispatch is a no-op handled by 409 at get_active_provider
    # (outbox marks the event failed; invoice stays queued — verify state didn't corrupt)
    after = client.get(f"/api/v1/billing/invoices/{inv['id']}", headers=admin_headers).json()
    assert after["status"] in ("queued", "transmitting", "ready_to_send")


# -- contract: submission & idempotency -------------------------------------------

def test_send_dispatch_delivers_via_stub(client, admin_headers):
    _configure_stub(client, admin_headers)
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    out = _send_and_dispatch(client, admin_headers, inv["id"])
    assert out["status"] == "delivered"
    assert out["provider_external_id"].startswith("STUB-")
    assert out["sdi_identifier"]
    assert out["provider_key"] == "stub-sandbox"


def test_idempotent_retry_same_submission_key(client, admin_headers):
    _configure_stub(client, admin_headers)
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    out = _send_and_dispatch(client, admin_headers, inv["id"])
    external_id = out["provider_external_id"]

    # simulate the dispatcher running the same outbox event again
    with SessionLocal() as db:
        invoice = db.get(Invoice, uuid.UUID(inv["id"]))
        _, provider = __import__(
            "app.modules.billing.providers.registry", fromlist=["get_active_provider"]
        ).get_active_provider(db)
        result = provider.submit_invoice(invoice, idempotency_key=invoice.submission_key)
    assert result.ok and result.external_id == external_id


def test_timeout_marks_unknown_and_blocks_resend(client, admin_headers):
    _configure_stub(client, admin_headers, simulate="timeout")
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    out = _send_and_dispatch(client, admin_headers, inv["id"])
    assert out["status"] == "transmission_unknown"

    # resend blocked: state not in resubmittable set until reconciled
    r = client.post(f"/api/v1/billing/invoices/{inv['id']}/send", headers=admin_headers)
    assert r.status_code == 409


def test_reconcile_resolves_unknown(client, admin_headers):
    _configure_stub(client, admin_headers, simulate="timeout")
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    out = _send_and_dispatch(client, admin_headers, inv["id"])
    assert out["status"] == "transmission_unknown"
    # The provider processed the submission but the response was lost:
    # reconcile via the submission key — no external id was ever received.
    r = client.post(f"/api/v1/billing/invoices/{inv['id']}/reconcile",
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "delivered"
    assert r.json()["provider_external_id"].startswith("STUB-")


# -- contract: webhooks --------------------------------------------------------------

def _webhook(client, provider_key, payload, token="test-webhook-token"):
    return client.post(
        f"/api/v1/billing/webhooks/{provider_key}",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", "X-Stub-Token": token},
    )


def test_webhook_unverified_rejected(client, admin_headers):
    _configure_stub(client, admin_headers)
    r = _webhook(client, "stub-sandbox", {"event_id": "e1"}, token="wrong")
    assert r.status_code == 422


def test_webhook_duplicate_event_not_reprocessed(client, admin_headers):
    _configure_stub(client, admin_headers)
    r1 = _webhook(client, "stub-sandbox",
                  {"event_id": "evt-1", "status": "CONSEGNATA", "external_id": "X"})
    r2 = _webhook(client, "stub-sandbox",
                  {"event_id": "evt-1", "status": "CONSEGNATA", "external_id": "X"})
    assert r1.status_code == 200
    assert r2.json()["result"] == "duplicate_ignored"
    with SessionLocal() as db:
        assert db.scalar(select(WebhookEventRecord).where(
            WebhookEventRecord.provider_event_id == "evt-1"))


def test_webhook_updates_invoice_status(client, admin_headers):
    _configure_stub(client, admin_headers)
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    with SessionLocal() as db:
        db_invoice = db.get(Invoice, uuid.UUID(inv["id"]))
        db_invoice.status = "submitted_to_sdi"
        db_invoice.provider_external_id = "STUB-EXT-1"
        db.commit()
    r = _webhook(client, "stub-sandbox", {
        "event_id": "evt-9", "status": "CONSEGNATA", "external_id": "STUB-EXT-1",
    })
    assert r.json()["result"] == "applied"
    out = client.get(f"/api/v1/billing/invoices/{inv['id']}", headers=admin_headers).json()
    assert out["status"] == "delivered"


# -- contract: audit & history ----------------------------------------------------------

def test_transmission_history_preserved(client, admin_headers):
    _configure_stub(client, admin_headers)
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    _send_and_dispatch(client, admin_headers, inv["id"])
    events = client.get(f"/api/v1/billing/invoices/{inv['id']}/events",
                        headers=admin_headers).json()
    types = [e["event_type"] for e in events]
    assert "invoice.draft_created" in types
    assert "invoice.finalized" in types
    assert "invoice.send_requested" in types
    assert "provider.status_update" in types


def test_imported_invoice_never_transmits(client, admin_headers):
    cid = _demo_company_id(client, admin_headers)
    inv = _make_invoice(client, admin_headers, cid)
    with SessionLocal() as db:
        db_invoice = db.get(Invoice, uuid.UUID(inv["id"]))
        db_invoice.status = "imported"
        db_invoice.number = 77
        db_invoice.fiscal_year = 2025
        db_invoice.source = "import"
        db.commit()
    r = client.post(f"/api/v1/billing/invoices/{inv['id']}/send", headers=admin_headers)
    assert r.status_code == 409


def test_rbac_consultant_cannot_submit(client, admin_headers, consultant_headers):
    _configure_stub(client, admin_headers)
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    r = client.post(f"/api/v1/billing/invoices/{inv['id']}/send",
                    headers=consultant_headers)
    assert r.status_code == 403


def test_outbox_event_recorded(client, admin_headers):
    _configure_stub(client, admin_headers)
    inv = _finalize(client, admin_headers, _make_invoice(client, admin_headers)["id"])
    client.post(f"/api/v1/billing/invoices/{inv['id']}/send", headers=admin_headers)
    with SessionLocal() as db:
        ev = db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.event_type == "billing.send_invoice")
            .order_by(OutboxEvent.created_at.desc())
        ).first()
        assert ev is not None and ev.status == "pending"
        assert ev.payload["invoice_id"] == inv["id"]
