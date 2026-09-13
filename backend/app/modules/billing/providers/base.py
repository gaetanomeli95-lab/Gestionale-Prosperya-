"""Provider-independent billing contract.

The CRM domain speaks ONLY to this interface. Provider-specific request
schemas, authentication models, proprietary status codes and webhook
payloads live inside the adapter implementing this contract — never in
the domain, routers or frontend.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.modules.billing.statuses import InvoiceStatus, ProviderHealthStatus, SdiStatus


class ErrorCategory(StrEnum):
    """Normalized failure taxonomy — adapters MUST map provider errors
    into one of these categories so the UI can react safely."""

    VALIDATION = "validation"              # refused before transmission
    AUTHENTICATION = "authentication"
    CONFIGURATION = "configuration"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    MALFORMED_RESPONSE = "malformed_response"
    REJECTED = "rejected"                  # business/fiscal rejection
    UNKNOWN_STATUS = "unknown_status"      # provider returned a state we can't map
    TEMPORARY = "temporary"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class NormalizedError:
    category: ErrorCategory
    message: str                # safe, user-displayable
    retryable: bool = False
    technical_detail: str | None = None   # logs only — may contain provider internals


@dataclass(frozen=True)
class ProviderCapabilities:
    """What the configured provider+version can actually do. The app adapts
    to this instead of assuming feature parity across providers."""

    supports_outgoing_invoices: bool = True
    supports_incoming_invoices: bool = False
    supports_webhooks: bool = False
    supports_status_polling: bool = True
    supports_credit_notes: bool = False
    supports_receipt_download: bool = False
    supports_xml_download: bool = False
    supports_sandbox: bool = False
    supports_idempotency_keys: bool = False


@dataclass(frozen=True)
class ProviderResult:
    """Normalized result of any provider operation."""

    ok: bool
    external_id: str | None = None                    # provider-side document id
    normalized_status: InvoiceStatus | None = None
    provider_status: str | None = None                # raw code, preserved verbatim
    sdi_status: SdiStatus | None = None
    sdi_identifier: str | None = None                 # identificativo SdI where exposed
    error: NormalizedError | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # sanitized provider payload


@dataclass(frozen=True)
class ProviderHealth:
    status: ProviderHealthStatus
    detail: str | None = None          # safe summary — NEVER secrets
    api_version: str | None = None
    environment: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """A verified, normalized inbound provider event."""

    provider_event_id: str
    external_id: str | None
    normalized_status: InvoiceStatus | None
    provider_status: str | None = None
    sdi_status: SdiStatus | None = None
    occurred_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class BillingProvider(ABC):
    """Stable internal contract every e-invoicing adapter must implement.

    Implementations are versioned per provider API (e.g. ``ArubaAdapterV1``);
    upgrading a provider API means adding a new adapter version, not
    touching the domain.
    """

    #: registry key, e.g. "aruba"
    key: str
    #: adapter version label, e.g. "v1"
    api_version: str

    def __init__(self, config: dict[str, Any], credentials: dict[str, str]):
        self.config = config
        self.credentials = credentials

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def validate_configuration(self) -> list[str]:
        """Return a list of configuration problems ([] means valid)."""

    @abstractmethod
    def health_check(self) -> ProviderHealth: ...

    @abstractmethod
    def submit_invoice(self, invoice: "Any", *, idempotency_key: str) -> ProviderResult:
        """Submit a finalized invoice. MUST honour the idempotency key so a
        retried submission of the same send-intention cannot create a
        duplicate fiscal document at the provider."""

    @abstractmethod
    def get_invoice_status(self, external_id: str) -> ProviderResult:
        """Poll/normalize current status for reconciliation."""

    def retrieve_notifications(self) -> list[WebhookEvent]:
        """Polling-based notification retrieval where webhooks are absent."""
        return []

    def download_xml(self, external_id: str) -> bytes | None:
        return None

    def download_receipt(self, external_id: str) -> bytes | None:
        return None

    def create_credit_note(self, invoice: "Any", *, idempotency_key: str) -> ProviderResult:
        return ProviderResult(
            ok=False,
            error=NormalizedError(
                category=ErrorCategory.PERMANENT,
                message="This provider does not support credit notes.",
            ),
        )

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
        """Verify authenticity and normalize. Return None if the request is
        not a genuine provider event (caller responds 400/401)."""
        return None
