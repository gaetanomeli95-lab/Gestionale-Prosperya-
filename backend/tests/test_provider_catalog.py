"""Provider catalog / support-status model (Phase G0).

The catalog must never make a provider look connected before its adapter
exists, and the research data must stay internally consistent.
"""
import dataclasses
import datetime as dt

import pytest

from app.modules.billing.providers import catalog as cat
from app.modules.billing.providers.catalog import (
    CATALOG,
    CatalogCapabilities,
    CatalogEntry,
    ProviderSupportStatus,
    effective_status,
)

API = "/api/v1"


def test_only_registered_adapters_are_supported_in_prosperya():
    supported = {e["key"] for e in cat.catalog() if e["status"] == "supported_in_prosperya"}
    assert supported == {"stub-sandbox"}, supported


def test_real_providers_are_not_shown_as_supported():
    for e in cat.catalog():
        if e["key"] != "stub-sandbox":
            assert e["status"] != "supported_in_prosperya", e["key"]
            assert e["adapter_registered"] is False


def test_data_cannot_claim_support_without_an_adapter():
    """Even if someone edits the data to say 'supported', the runtime refuses."""
    fake = dataclasses.replace(CATALOG[1], key="not-registered-provider",
                               research_status=ProviderSupportStatus.SUPPORTED_IN_PROSPERYA)
    assert effective_status(fake) == ProviderSupportStatus.UNKNOWN


def test_every_entry_has_source_and_recent_verification_date():
    for e in CATALOG:
        assert e.documentation_url, e.key
        d = dt.date.fromisoformat(e.last_verified)
        assert d <= dt.datetime.now(dt.UTC).date() + dt.timedelta(days=1)   # local-vs-UTC edge
        assert e.documentation_quality in {"high", "medium", "low", "unknown"}


def test_capabilities_are_tri_state():
    """UNKNOWN (None) is a legitimate value — never fabricated True/False."""
    for e in CATALOG:
        for f in dataclasses.fields(CatalogCapabilities):
            assert getattr(e.capabilities, f.name) in (True, False, None), (e.key, f.name)


def test_keys_are_unique_and_registry_compatible():
    keys = [e.key for e in CATALOG]
    assert len(keys) == len(set(keys))
    assert all(k == k.lower() and " " not in k for k in keys)


def test_direct_sdi_is_research_only():
    e = next(e for e in CATALOG if e.key == "direct-sdi")
    assert e.research_status == ProviderSupportStatus.RESEARCHED
    assert e.integration_kind == "direct_channel"


def test_catalog_endpoint_requires_auth_and_returns_statuses(client, admin_headers, consultant_headers):
    assert client.get(f"{API}/billing/providers/catalog").status_code == 401
    r = client.get(f"{API}/billing/providers/catalog", headers=consultant_headers)   # billing:read suffices
    assert r.status_code == 200, r.text
    rows = r.json()["providers"]
    assert {p["key"] for p in rows} >= {"aruba", "fattureincloud", "tsdigital", "zucchetti-digitalhub",
                                        "acube", "openapi-sdi", "direct-sdi", "stub-sandbox"}
    statuses = {p["status"] for p in rows}
    assert statuses <= {s.value for s in ProviderSupportStatus}
    for p in rows:
        assert "adapter_registered" in p and "last_verified" in p and "documentation_url" in p


@pytest.mark.parametrize("field", ["commercial_prerequisites", "known_limitations", "auth_model"])
def test_research_fields_are_filled(field):
    for e in CATALOG:
        assert getattr(e, field), (e.key, field)


def test_catalog_entry_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        CATALOG[0].name = "x"   # type: ignore[misc]


def test_catalog_entry_type_used():
    assert all(isinstance(e, CatalogEntry) for e in CATALOG)
