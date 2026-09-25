"""Provider catalog — what exists in the Italian e-invoicing market vs. what
Prosperya can actually connect to.

Two different facts, never conflated:

* `ProviderSupportStatus`  — the honest state of *our* support.
* `CatalogEntry`           — research about the *provider*, with the official
                              source and the date it was last verified.

`SUPPORTED_IN_PROSPERYA` is never asserted here by hand: it is derived at
runtime from the adapter registry (an adapter exists and is registered), so a
provider cannot be shown as connected before its adapter ships. The research
facts below mirror docs/INTEGRATIONS.md; update both together.
"""
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from app.modules.billing.providers import registry


class ProviderSupportStatus(StrEnum):
    RESEARCHED = "researched"                        # official docs read, matrix filled
    SUPPORTED_BY_PROVIDER_API = "supported_by_provider_api"  # provider exposes a suitable API
    REQUIRES_PARTNER_AGREEMENT = "requires_partner_agreement"
    REQUIRES_CREDENTIALS = "requires_credentials"    # API is public but needs a paid/activated account
    IMPLEMENTABLE = "implementable"                  # nothing blocks an adapter today
    IN_DEVELOPMENT = "in_development"                # adapter branch exists, not shipped
    SUPPORTED_IN_PROSPERYA = "supported_in_prosperya"  # adapter registered + contract kit green
    UNAVAILABLE = "unavailable"                      # no programmatic integration offered
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CatalogCapabilities:
    """Tri-state per capability: True / False / None (=UNKNOWN from official docs)."""
    outgoing_invoices: bool | None = None
    incoming_invoices: bool | None = None
    credit_notes: bool | None = None
    sdi_status: bool | None = None
    receipt_download: bool | None = None
    xml_download: bool | None = None
    webhooks: bool | None = None
    status_polling: bool | None = None
    sandbox: bool | None = None
    multi_company: bool | None = None
    provider_side_archive: bool | None = None


@dataclass(frozen=True)
class CatalogEntry:
    key: str                       # registry key an adapter would use, e.g. "aruba"
    name: str
    vendor: str
    integration_kind: str          # "public_rest" | "partner_api" | "on_request" | "direct_channel" | "none"
    auth_model: str
    protocol: str
    api_version: str | None
    research_status: ProviderSupportStatus
    capabilities: CatalogCapabilities
    commercial_prerequisites: str
    partner_agreement_required: bool | None
    rate_limits: str | None
    known_limitations: str
    documentation_url: str
    documentation_quality: str     # "high" | "medium" | "low" | "unknown"
    last_verified: str             # ISO date
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Research data (mirrors docs/INTEGRATIONS.md). UNKNOWN is a legitimate value.
# ---------------------------------------------------------------------------

CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        key="stub-sandbox", name="Stub sandbox (test double)", vendor="Prosperya",
        integration_kind="internal", auth_model="none", protocol="in-process", api_version="v1",
        research_status=ProviderSupportStatus.SUPPORTED_IN_PROSPERYA,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=False, credit_notes=False,
                                         sdi_status=True, receipt_download=False, xml_download=False,
                                         webhooks=True, status_polling=True, sandbox=True,
                                         multi_company=True, provider_side_archive=False),
        commercial_prerequisites="none — never transmits anything", partner_agreement_required=False,
        rate_limits=None, known_limitations="Fake provider for contract tests only. Refuses environment=production.",
        documentation_url="app/modules/billing/providers/stub.py", documentation_quality="high",
        last_verified="2026-09-26", tags=("internal",),
    ),
    CatalogEntry(
        key="aruba", name="Aruba Fatturazione Elettronica", vendor="Aruba PEC S.p.A.",
        integration_kind="public_rest",
        auth_model="OAuth2 password grant (signin) + refresh token; Bearer",
        protocol="REST/JSON", api_version="v2 (2.2.0 documented; changelog to 2.5.0)",
        research_status=ProviderSupportStatus.REQUIRES_CREDENTIALS,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=True, credit_notes=True,
                                         sdi_status=True, receipt_download=True, xml_download=True,
                                         webhooks=True, status_polling=True, sandbox=True,
                                         multi_company=True, provider_side_archive=True),
        commercial_prerequisites="Aruba 'Premium' account (or a Base account delegated to a Premium one); "
                                 "demo environment credentials issued by Aruba.",
        partner_agreement_required=False,
        rate_limits="Tiered: Tier 0 = 60 req/hour and 10,000 req/year, up to Tier 6 = 30,000 req/hour. "
                    "Leaky-bucket; excess rejected with HTTP 429, no queuing.",
        known_limitations="Callbacks require accreditation of the receiving endpoint by the Premium user; "
                          "Tier 0 quota is very low for polling-heavy integrations; invoice XML must be produced by the caller "
                          "(FatturaPA), Aruba validates/signs/transmits.",
        documentation_url="https://fatturazioneelettronica.aruba.it/apidoc/v2/docs_EN.html",
        documentation_quality="high", last_verified="2026-09-26",
        notes="Demo env simulates SdI (received invoices, notifications). v1 API still documented; v2 is current.",
        tags=("intermediary", "sdi"),
    ),
    CatalogEntry(
        key="fattureincloud", name="Fatture in Cloud", vendor="TeamSystem S.p.A.",
        integration_kind="public_rest",
        auth_model="OAuth2 Authorization Code (preferred); Device Code on request; manual long-lived token",
        protocol="REST/JSON (OpenAPI 3, official SDKs)", api_version="v2 (spec 2.1.8)",
        research_status=ProviderSupportStatus.REQUIRES_CREDENTIALS,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=True, credit_notes=True,
                                         sdi_status=True, receipt_download=None, xml_download=True,
                                         webhooks=True, status_polling=True, sandbox=False,
                                         multi_company=True, provider_side_archive=True),
        commercial_prerequisites="A Fatture in Cloud company account with e-invoicing enabled; a registered app "
                                 "(client id/secret). Public apps: App Store publication review.",
        partner_agreement_required=False,
        rate_limits="1,000 req/hour per company-app; 40,000 req/month; 300 req per 5 minutes (429 + Retry-After).",
        known_limitations="No dedicated SdI sandbox: testing uses options.dry_run on send. Invoices are FiC "
                          "documents (JSON model), not raw FatturaPA XML upload. Webhook carries only the "
                          "document id — status must be fetched afterwards.",
        documentation_url="https://developers.fattureincloud.it/ (OpenAPI: github.com/fattureincloud/openapi-fattureincloud)",
        documentation_quality="high", last_verified="2026-09-26",
        notes="Webhook event: it.fattureincloud.webhooks.issued_documents.e_invoices.status_update.",
        tags=("intermediary", "sdi", "teamsystem-group"),
    ),
    CatalogEntry(
        key="tsdigital", name="TS Digital Invoice (ex Agyo)", vendor="TeamSystem S.p.A.",
        integration_kind="partner_api",
        auth_model="TS Digital access token (JWT Bearer); technical Id/Secret issued at service purchase",
        protocol="REST/JSON (B2BWrite / B2BRead API guides)", api_version="B2BWrite v7.5.x, Invoices v2 (v1 deprecated)",
        research_status=ProviderSupportStatus.REQUIRES_CREDENTIALS,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=True, credit_notes=None,
                                         sdi_status=True, receipt_download=None, xml_download=True,
                                         webhooks=None, status_polling=True, sandbox=True,
                                         multi_company=True, provider_side_archive=True),
        commercial_prerequisites="TS Digital Invoice subscription; technical credentials (Id/Secret) delivered by e-mail "
                                 "after purchase. No self-service developer signup found.",
        partner_agreement_required=None,
        rate_limits=None,
        known_limitations="Public documentation is partial (API guides on *-api-test.agyo.io reachable; production "
                          "docs host returned 403). Flow types (SDIPA/SDIPR/SELFSEND) are provider-specific. "
                          "Webhook availability UNKNOWN from public docs.",
        documentation_url="https://b2bwrite-api-test.agyo.io/api/docs/index.html ; https://b2bread-api-test.agyo.io/api/docs/index.html",
        documentation_quality="medium", last_verified="2026-09-26",
        tags=("intermediary", "sdi", "teamsystem-group"),
    ),
    CatalogEntry(
        key="zucchetti-digitalhub", name="Digital Hub Zucchetti", vendor="Zucchetti S.p.A.",
        integration_kind="on_request",
        auth_model="Web-service credentials ('utente di servizio') issued with the contract",
        protocol="Web service (details not public)", api_version=None,
        research_status=ProviderSupportStatus.REQUIRES_PARTNER_AGREEMENT,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=True, credit_notes=None,
                                         sdi_status=True, receipt_download=None, xml_download=None,
                                         webhooks=None, status_polling=None, sandbox=None,
                                         multi_company=True, provider_side_archive=True),
        commercial_prerequisites="Digital Hub subscription; web-service documentation is provided by a Zucchetti "
                                 "sales contact or partner, not published.",
        partner_agreement_required=True, rate_limits=None,
        known_limitations="No public API documentation: capabilities beyond send/receive/notifications are UNKNOWN. "
                          "Third-party integration explicitly 'to be verified with your technicians'.",
        documentation_url="https://zucchetti.it/it/cms/soluzioni/obblighi-normativi/fatturazione-elettronica/digital-hub/fatturazione-elettronica-aziende-descrizione.html",
        documentation_quality="low", last_verified="2026-09-26",
        tags=("intermediary", "sdi"),
    ),
    CatalogEntry(
        key="acube", name="A-Cube API (Italy e-invoicing)", vendor="A-Cube S.r.l.",
        integration_kind="public_rest",
        auth_model="JWT (username/password login); API key or OAuth2 also advertised",
        protocol="REST/JSON or FatturaPA XML; OpenAPI", api_version="v1 (docs.acubeapi.com)",
        research_status=ProviderSupportStatus.SUPPORTED_BY_PROVIDER_API,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=True, credit_notes=True,
                                         sdi_status=True, receipt_download=None, xml_download=True,
                                         webhooks=True, status_polling=True, sandbox=True,
                                         multi_company=True, provider_side_archive=True),
        commercial_prerequisites="Free sandbox signup; production account. Legal preservation via partner (Intesi).",
        partner_agreement_required=False,
        rate_limits="Configurable per tenant (advertised); exact figures not in public docs -> UNKNOWN",
        known_limitations="Smaller vendor than the incumbents; commercial continuity to be assessed.",
        documentation_url="https://docs.acubeapi.com/documentation/italy/gov-it/invoices/",
        documentation_quality="high", last_verified="2026-09-26",
        notes="Webhook events include customer-invoice, customer-notification, supplier-invoice; signed requests.",
        tags=("intermediary", "sdi", "api-first"),
    ),
    CatalogEntry(
        key="openapi-sdi", name="Openapi — Fatturazione Elettronica (SDI)", vendor="Openapi S.r.l.",
        integration_kind="public_rest",
        auth_model="Openapi token (console-issued, scoped)",
        protocol="REST/JSON or XML; OAS3, Postman collection", api_version="sdi.openapi.it (current)",
        research_status=ProviderSupportStatus.SUPPORTED_BY_PROVIDER_API,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=True, credit_notes=None,
                                         sdi_status=True, receipt_download=None, xml_download=True,
                                         webhooks=True, status_polling=True, sandbox=True,
                                         multi_company=True, provider_side_archive=True),
        commercial_prerequisites="Openapi console account; pay-per-use.",
        partner_agreement_required=False,
        rate_limits="10,000 req/min (as documented on the console page)",
        known_limitations="Endpoint model (business_registry_configurations, api_configurations) is provider-specific; "
                          "credit-note specifics not verified.",
        documentation_url="https://console.openapi.com/apis/sdi/documentation (sandbox: test.sdi.openapi.it)",
        documentation_quality="medium", last_verified="2026-09-26",
        tags=("intermediary", "sdi", "api-first"),
    ),
    CatalogEntry(
        key="direct-sdi", name="Sistema di Interscambio — canale diretto", vendor="Agenzia delle Entrate",
        integration_kind="direct_channel",
        auth_model="Service agreement signed digitally; X.509 certificates issued after interoperability tests",
        protocol="SdICoop: SOAP with attachments over HTTPS (TLS 1.2); SdIFtp: SFTP; PEC",
        api_version="Specifiche tecniche v1.8 (18/01/2024); SdICoop Trasmissione/Ricezione v3.0",
        research_status=ProviderSupportStatus.RESEARCHED,
        capabilities=CatalogCapabilities(outgoing_invoices=True, incoming_invoices=True, credit_notes=True,
                                         sdi_status=True, receipt_download=True, xml_download=True,
                                         webhooks=True, status_polling=False, sandbox=True,
                                         multi_company=True, provider_side_archive=False),
        commercial_prerequisites="Accreditation of a transmission channel with SdI (accordo di servizio, "
                                 "interoperability tests, certificate). Becoming an 'intermediario' with operational "
                                 "duties: signature, conservazione a norma, 5 MB/file, notification handling.",
        partner_agreement_required=False, rate_limits="Not applicable (channel accreditation, file limits)",
        known_limitations="Not an HTTP/JSON API: SOAP/MTOM or SFTP with SdI-initiated connections; requires "
                          "hosting a receiving endpoint, certificate lifecycle, legal-preservation solution. "
                          "Operational responsibility shifts entirely to Prosperya.",
        documentation_url="https://www.agenziaentrate.gov.it/portale/schede/comunicazioni/fatture-e-corrispettivi/fatture-e-corrispettivi-st/st-invio-di-fatturazione-elettronica-intermediari",
        documentation_quality="high", last_verified="2026-09-26",
        notes="Kept as a future DirectSdiAdapter option only; not preferable by default.",
        tags=("direct", "sdi"),
    ),
)


def effective_status(entry: CatalogEntry) -> ProviderSupportStatus:
    """Runtime truth: an adapter registered for `entry.key` (any version) means
    SUPPORTED_IN_PROSPERYA; otherwise the research status stands — and the
    research status is never allowed to claim support."""
    registered = {r["key"] for r in registry.available_providers()}
    if entry.key in registered:
        return ProviderSupportStatus.SUPPORTED_IN_PROSPERYA
    if entry.research_status == ProviderSupportStatus.SUPPORTED_IN_PROSPERYA:
        return ProviderSupportStatus.UNKNOWN   # data claims support without an adapter: refuse to show it
    return entry.research_status


def catalog() -> list[dict[str, Any]]:
    """Catalog as the UI Integration Center will consume it."""
    registered = {r["key"]: r["api_version"] for r in registry.available_providers()}
    out = []
    for e in CATALOG:
        d = asdict(e)
        d["research_status"] = e.research_status.value
        d["status"] = effective_status(e).value
        d["adapter_registered"] = e.key in registered
        d["adapter_api_version"] = registered.get(e.key)
        d["tags"] = list(e.tags)
        out.append(d)
    return out
