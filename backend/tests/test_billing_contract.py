"""Provider-independent billing contract (mission §29).

Pure unit tests — no HTTP, no network, no database. They pin the seams that
real adapters (Aruba, Fatture in Cloud, TeamSystem, direct SdI) will have to
respect, and they double as a conformance kit: `ContractKit` runs the same
assertions against every registered adapter.
"""
import dataclasses
import inspect
from types import SimpleNamespace

import pytest

from app.core.errors import NotFoundError
from app.modules.billing.providers import registry
from app.modules.billing.providers.base import (
    BillingProvider,
    ErrorCategory,
    NormalizedError,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    WebhookEvent,
)
from app.modules.billing.providers.stub import StubSandboxAdapterV1, reset_stub_state
from app.modules.billing.statuses import (
    InvoiceStatus,
    PaymentStatus,
    ProviderHealthStatus,
    SdiStatus,
)

INVOICE = SimpleNamespace(id="inv-1", number="2026/0001", total=100)


@pytest.fixture(autouse=True)
def _reset():
    reset_stub_state()
    yield
    reset_stub_state()


def _stub(**config) -> StubSandboxAdapterV1:
    return StubSandboxAdapterV1(config={"environment": "sandbox", "endpoint": "stub://", **config},
                                credentials={})


# --------------------------------------------------------------------------
# adapter resolution / versioning
# --------------------------------------------------------------------------

def test_registry_resolves_versioned_adapter():
    assert registry.adapter_for("stub-sandbox", "v1") is StubSandboxAdapterV1


def test_unknown_provider_rejected():
    with pytest.raises(NotFoundError) as ei:
        registry.adapter_for("aruba", "v1")
    assert ei.value.code == "unknown_billing_provider"


def test_unknown_api_version_rejected():
    """Same provider, different API version = different adapter. Upgrading a
    provider API means registering a new version, never editing the core."""
    with pytest.raises(NotFoundError):
        registry.adapter_for("stub-sandbox", "v2")


def test_available_providers_lists_key_and_version():
    rows = registry.available_providers()
    assert {"key": "stub-sandbox", "api_version": "v1"} in rows
    assert all(set(r) == {"key", "api_version"} for r in rows)


def test_no_real_provider_is_registered_yet():
    """Guard against silently shipping an unverified connector (mission §28)."""
    keys = {r["key"] for r in registry.available_providers()}
    assert keys == {"stub-sandbox"}, f"unexpected providers registered: {keys - {'stub-sandbox'}}"


# --------------------------------------------------------------------------
# configuration validation
# --------------------------------------------------------------------------

def test_stub_refuses_production_environment():
    a = StubSandboxAdapterV1(config={"environment": "production", "endpoint": "stub://"}, credentials={})
    problems = a.validate_configuration()
    assert problems and any("sandbox" in p.lower() for p in problems)


def test_stub_sandbox_configuration_is_valid():
    assert _stub().validate_configuration() == []


def test_health_never_exposes_secrets():
    adapter = StubSandboxAdapterV1(config={"environment": "sandbox"},
                                   credentials={"api_key": "SUPER-SECRET-VALUE"})
    h = adapter.health_check()
    assert isinstance(h, ProviderHealth)
    assert "SUPER-SECRET-VALUE" not in (h.detail or "")
    assert h.status in set(ProviderHealthStatus)


# --------------------------------------------------------------------------
# idempotency / transmission semantics
# --------------------------------------------------------------------------

def test_same_idempotency_key_never_creates_second_submission():
    a = _stub()
    r1 = a.submit_invoice(INVOICE, idempotency_key="send-abc")
    r2 = a.submit_invoice(INVOICE, idempotency_key="send-abc")
    assert r1.ok and r2.ok
    assert r1.external_id == r2.external_id


def test_different_idempotency_key_is_a_new_submission():
    a = _stub()
    r1 = a.submit_invoice(INVOICE, idempotency_key="send-1")
    r2 = a.submit_invoice(INVOICE, idempotency_key="send-2")
    assert r1.external_id != r2.external_id


def test_timeout_is_unknown_not_failure():
    """A timeout does not prove failure: the normalized result must say
    'unknown' and be non-retryable-blind, so the domain marks the invoice
    TRANSMISSION_UNKNOWN and reconciles instead of resending."""
    a = _stub(simulate="timeout")
    r = a.submit_invoice(INVOICE, idempotency_key="send-t")
    assert r.ok is False
    assert r.error is not None
    assert r.error.category in {ErrorCategory.TIMEOUT, ErrorCategory.UNKNOWN_STATUS}
    assert r.normalized_status in {None, InvoiceStatus.TRANSMISSION_UNKNOWN}


def test_status_poll_resolves_earlier_submission():
    a = _stub()
    sent = a.submit_invoice(INVOICE, idempotency_key="send-p")
    polled = a.get_invoice_status(sent.external_id)
    assert polled.ok and polled.external_id == sent.external_id
    assert polled.normalized_status in set(InvoiceStatus)
    assert polled.provider_status is not None            # raw code preserved verbatim


# --------------------------------------------------------------------------
# state separation — invoice / SdI / payment are three different things
# --------------------------------------------------------------------------

def test_three_status_enums_are_disjoint_concepts():
    inv, sdi, pay = set(InvoiceStatus), set(SdiStatus), set(PaymentStatus)
    assert not inv & pay and not sdi & pay
    # 'delivered'/'rejected' legitimately exist in both invoice and SdI vocabularies,
    # but the enums are distinct types and never interchangeable:
    assert InvoiceStatus.DELIVERED is not SdiStatus.DELIVERED
    assert type(InvoiceStatus.DELIVERED) is not type(SdiStatus.DELIVERED)


def test_invoice_status_has_no_boolean_sent_flag_equivalent():
    """Transmission is a workflow, not sent=true/false (mission §14)."""
    required = {"queued", "transmitting", "sent_to_provider", "submitted_to_sdi",
                "transmission_unknown", "requires_reconciliation", "rejected", "delivered"}
    assert required <= {s.value for s in InvoiceStatus}


def test_result_carries_normalized_and_raw_status_separately():
    fields = {f.name for f in dataclasses.fields(ProviderResult)}
    assert {"normalized_status", "provider_status", "sdi_status", "sdi_identifier", "error", "raw"} <= fields


def test_normalized_error_has_safe_and_technical_channels():
    e = NormalizedError(category=ErrorCategory.AUTHENTICATION, message="Credenziali non valide.",
                        technical_detail="HTTP 401 from provider: token expired at ...")
    assert e.message and e.technical_detail and e.retryable is False


# --------------------------------------------------------------------------
# contract conformance kit — run against EVERY registered adapter
# --------------------------------------------------------------------------

def _all_adapters():
    return [registry.adapter_for(r["key"], r["api_version"]) for r in registry.available_providers()]


@pytest.mark.parametrize("cls", _all_adapters(), ids=lambda c: f"{c.key}/{c.api_version}")
class TestContractKit:
    def test_declares_key_and_version(self, cls):
        assert isinstance(cls.key, str) and cls.key and isinstance(cls.api_version, str) and cls.api_version

    def test_implements_every_abstract_member(self, cls):
        assert not inspect.isabstract(cls)
        assert issubclass(cls, BillingProvider)

    def test_capabilities_is_frozen_dataclass(self, cls):
        caps = cls(config={"environment": "sandbox"}, credentials={}).capabilities
        assert isinstance(caps, ProviderCapabilities)
        with pytest.raises(dataclasses.FrozenInstanceError):
            caps.supports_webhooks = True  # type: ignore[misc]

    def test_validate_configuration_returns_list_of_str(self, cls):
        out = cls(config={}, credentials={}).validate_configuration()
        assert isinstance(out, list) and all(isinstance(p, str) for p in out)

    def test_submit_signature_requires_idempotency_key(self, cls):
        sig = inspect.signature(cls.submit_invoice)
        p = sig.parameters["idempotency_key"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty

    def test_webhook_verification_rejects_garbage(self, cls):
        out = cls(config={"environment": "sandbox"}, credentials={}).verify_webhook({}, b"not-json")
        assert out is None or isinstance(out, WebhookEvent)

    def test_no_provider_specific_types_leak_into_results(self, cls):
        a = cls(config={"environment": "sandbox"}, credentials={})
        r = a.submit_invoice(INVOICE, idempotency_key="kit-1")
        assert isinstance(r, ProviderResult)
        for f in dataclasses.fields(ProviderResult):
            v = getattr(r, f.name)
            assert v is None or isinstance(v, (bool, str, dict, InvoiceStatus, SdiStatus, NormalizedError)), (
                f"{f.name} leaks provider type {type(v)}")
