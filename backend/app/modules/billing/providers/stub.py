"""Stub sandbox adapter — a *fake* provider used to develop and test the
provider-independent contract end-to-end before any real connector exists.

It is explicitly NOT a real invoicing provider:
* ``environment`` must be ``sandbox`` — it refuses ``production`` config;
* submissions are recorded in-memory keyed by the idempotency key, proving
  that retries cannot duplicate a fiscal submission;
* it can be driven to simulate timeout / unknown-status / rejection paths
  via config flags, so contract tests cover failure semantics.

Never register a real provider here. Real adapters (Aruba, Fatture in
Cloud, TeamSystem, direct SdI) each get their own versioned module once
current official documentation has been verified.
"""
import hashlib
import uuid
from typing import Any

from app.modules.billing.providers.base import (
    BillingProvider,
    ErrorCategory,
    NormalizedError,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    WebhookEvent,
)
from app.modules.billing.providers.registry import register
from app.modules.billing.statuses import (
    InvoiceStatus,
    ProviderHealthStatus,
    SdiStatus,
)

#: in-memory fake provider state — per adapter instance, tests reset it.
_SUBMISSIONS: dict[str, dict[str, Any]] = {}


def reset_stub_state() -> None:
    _SUBMISSIONS.clear()


def _record_submission(idempotency_key: str) -> dict:
    if idempotency_key not in _SUBMISSIONS:
        external = f"STUB-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:12].upper()}"
        _SUBMISSIONS[idempotency_key] = {
            "external_id": external, "status": "CONSEGNATA", "attempts": 0,
        }
    return _SUBMISSIONS[idempotency_key]


@register
class StubSandboxAdapterV1(BillingProvider):
    key = "stub-sandbox"
    api_version = "v1"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_outgoing_invoices=True,
            supports_incoming_invoices=False,
            supports_webhooks=True,
            supports_status_polling=True,
            supports_credit_notes=True,
            supports_xml_download=True,
            supports_sandbox=True,
            supports_idempotency_keys=True,
        )

    # -- configuration / health -------------------------------------------------

    def validate_configuration(self) -> list[str]:
        problems = []
        if self.config.get("environment") != "sandbox":
            problems.append("Stub adapter only supports the 'sandbox' environment.")
        if "endpoint" not in self.config:
            problems.append("Missing 'endpoint' configuration value.")
        return problems

    def health_check(self) -> ProviderHealth:
        problems = self.validate_configuration()
        if problems:
            return ProviderHealth(
                status=ProviderHealthStatus.CONFIGURATION_ERROR,
                detail="; ".join(problems),
                api_version=self.api_version,
                environment=self.config.get("environment"),
            )
        return ProviderHealth(
            status=ProviderHealthStatus.HEALTHY,
            detail="Stub provider operational.",
            api_version=self.api_version,
            environment="sandbox",
        )

    # -- outgoing invoices ------------------------------------------------------

    def submit_invoice(self, invoice: Any, *, idempotency_key: str) -> ProviderResult:
        simulate = self.config.get("simulate")  # test hook
        if simulate == "timeout":
            # The provider DID process the submission — only the response
            # was lost. Recording it makes reconciliation possible and
            # proves retries of the same key can't duplicate the document.
            _record_submission(idempotency_key)
            return ProviderResult(
                ok=False,
                error=NormalizedError(
                    category=ErrorCategory.TIMEOUT,
                    message="The provider did not respond in time. "
                            "The invoice state is unknown and must be reconciled before retrying.",
                    retryable=False,   # unknown outcome — never blind-retry
                    technical_detail="simulated timeout",
                ),
            )
        if simulate == "reject":
            return ProviderResult(
                ok=False,
                normalized_status=InvoiceStatus.REJECTED,
                provider_status="SCARTATA",
                sdi_status=SdiStatus.REJECTED,
                error=NormalizedError(
                    category=ErrorCategory.REJECTED,
                    message="Invoice rejected: simulated provider validation failure.",
                ),
            )

        # Idempotent submission: same key → same external reference.
        record = _record_submission(idempotency_key)
        record["attempts"] += 1

        return ProviderResult(
            ok=True,
            external_id=record["external_id"],
            normalized_status=InvoiceStatus.DELIVERED
            if self.config.get("auto_deliver", True)
            else InvoiceStatus.SENT_TO_PROVIDER,
            provider_status=record["status"],
            sdi_status=SdiStatus.DELIVERED,
            sdi_identifier=f"SDI-{uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key).hex[:10]}",
            raw={"stub": True},
        )

    def get_invoice_status(self, reference: str) -> ProviderResult:
        # reference may be the provider external id OR the idempotency key
        # (used when the response carrying the external id was lost).
        record = _SUBMISSIONS.get(reference)
        if record is None:
            record = next(
                (r for r in _SUBMISSIONS.values() if r["external_id"] == reference),
                None,
            )
        if record is not None:
            return ProviderResult(
                ok=True,
                external_id=record["external_id"],
                normalized_status=InvoiceStatus.DELIVERED,
                provider_status=record["status"],
                sdi_status=SdiStatus.DELIVERED,
            )
        if self.config.get("simulate") == "unknown_status":
            return ProviderResult(
                ok=False,
                error=NormalizedError(
                    category=ErrorCategory.UNKNOWN_STATUS,
                    message="The provider returned a status the CRM cannot map.",
                    technical_detail="simulated unknown status",
                ),
            )
        return ProviderResult(
            ok=False,
            error=NormalizedError(
                category=ErrorCategory.VALIDATION,
                message="Unknown external invoice reference.",
            ),
        )

    # -- webhooks ---------------------------------------------------------------

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
        """Stub verification: requires the shared token header. Real adapters
        implement signature verification per provider docs."""
        import json

        token = headers.get("x-stub-token") or headers.get("X-Stub-Token")
        if token != self.credentials.get("webhook_token"):
            return None
        try:
            data = json.loads(body)
        except ValueError:
            return None
        event_id = data.get("event_id")
        if not event_id:
            return None
        return WebhookEvent(
            provider_event_id=str(event_id),
            external_id=data.get("external_id"),
            normalized_status=_STUB_STATUS_MAP.get(data.get("status")),
            provider_status=data.get("status"),
            sdi_status=_STUB_SDI_MAP.get(data.get("status")),
            raw={"stub": True},
        )


_STUB_STATUS_MAP = {
    "CONSEGNATA": InvoiceStatus.DELIVERED,
    "INOLTRATA": InvoiceStatus.SUBMITTED_TO_SDI,
    "SCARTATA": InvoiceStatus.REJECTED,
    "MANCATA_CONSEGNA": InvoiceStatus.DELIVERY_FAILED,
}
_STUB_SDI_MAP = {
    "CONSEGNATA": SdiStatus.DELIVERED,
    "INOLTRATA": SdiStatus.SUBMITTED,
    "SCARTATA": SdiStatus.REJECTED,
    "MANCATA_CONSEGNA": SdiStatus.DELIVERY_FAILED,
}
