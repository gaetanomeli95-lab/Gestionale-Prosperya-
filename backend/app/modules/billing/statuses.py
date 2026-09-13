"""Normalized electronic-invoicing statuses.

Three distinct axes are kept separate:

* ``InvoiceStatus`` — Prosperya's internal workflow state (authoritative).
* ``provider_status`` — the raw status string/code returned by the provider,
  preserved verbatim on the invoice and in transmission events.
* ``sdi_status`` — the normalized SdI outcome where the provider exposes it
  (delivered / rejected / failed), never guessed.

Payment status is a different domain concept and is NOT mixed into
transmission status.
"""
from enum import StrEnum


class InvoiceStatus(StrEnum):
    DRAFT = "draft"                            # editable working document
    READY_TO_SEND = "ready_to_send"            # finalized + numbered, not yet sent
    QUEUED = "queued"                          # submission intention persisted (outbox)
    TRANSMITTING = "transmitting"              # provider call in flight
    SENT_TO_PROVIDER = "sent_to_provider"      # provider accepted the submission
    SUBMITTED_TO_SDI = "submitted_to_sdi"      # provider confirms SdI hand-off
    DELIVERED = "delivered"                    # SdI delivered to recipient
    ACCEPTED = "accepted"                      # esito positivo where applicable
    REJECTED = "rejected"                      # SdI/provider rejection (scartata)
    DELIVERY_FAILED = "delivery_failed"        # SdI could not deliver (impossibilità)
    TRANSMISSION_UNKNOWN = "transmission_unknown"  # outcome unknowable — NEVER blind-retry
    REQUIRES_RECONCILIATION = "requires_reconciliation"
    CREDITED = "credited"                      # covered by a credit note
    CANCELLED = "cancelled"
    IMPORTED = "imported"                      # historical document — never transmits


# Statuses in which the fiscal document must be treated as immutable.
# READY_TO_SEND is immutable too: the fiscal number is already assigned at
# finalize — changing contents afterwards would corrupt the numbering chain.
IMMUTABLE_STATUSES = frozenset({
    InvoiceStatus.READY_TO_SEND,
    InvoiceStatus.QUEUED,
    InvoiceStatus.TRANSMITTING,
    InvoiceStatus.SENT_TO_PROVIDER,
    InvoiceStatus.SUBMITTED_TO_SDI,
    InvoiceStatus.DELIVERED,
    InvoiceStatus.ACCEPTED,
    InvoiceStatus.REJECTED,
    InvoiceStatus.DELIVERY_FAILED,
    InvoiceStatus.TRANSMISSION_UNKNOWN,
    InvoiceStatus.REQUIRES_RECONCILIATION,
    InvoiceStatus.CREDITED,
    InvoiceStatus.CANCELLED,
    InvoiceStatus.IMPORTED,
})

# Statuses that still allow a (controlled) retransmission path.
RESUBMITTABLE_STATUSES = frozenset({
    InvoiceStatus.READY_TO_SEND,
    InvoiceStatus.REJECTED,          # scartata: correct + resubmit with same number
    InvoiceStatus.DELIVERY_FAILED,
    InvoiceStatus.REQUIRES_RECONCILIATION,  # only after successful reconciliation
})

# Guarded transition map. The service layer refuses anything outside this.
ALLOWED_TRANSITIONS: dict[InvoiceStatus, frozenset[InvoiceStatus]] = {
    InvoiceStatus.DRAFT: frozenset({InvoiceStatus.READY_TO_SEND, InvoiceStatus.CANCELLED}),
    InvoiceStatus.READY_TO_SEND: frozenset({
        InvoiceStatus.QUEUED, InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED,
    }),
    InvoiceStatus.QUEUED: frozenset({
        InvoiceStatus.TRANSMITTING, InvoiceStatus.READY_TO_SEND,
    }),
    InvoiceStatus.TRANSMITTING: frozenset({
        InvoiceStatus.SENT_TO_PROVIDER, InvoiceStatus.TRANSMISSION_UNKNOWN,
        InvoiceStatus.DELIVERY_FAILED, InvoiceStatus.READY_TO_SEND,
    }),
    InvoiceStatus.SENT_TO_PROVIDER: frozenset({
        InvoiceStatus.SUBMITTED_TO_SDI, InvoiceStatus.TRANSMISSION_UNKNOWN,
        InvoiceStatus.DELIVERY_FAILED, InvoiceStatus.REJECTED,
    }),
    InvoiceStatus.SUBMITTED_TO_SDI: frozenset({
        InvoiceStatus.DELIVERED, InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED,
        InvoiceStatus.DELIVERY_FAILED, InvoiceStatus.TRANSMISSION_UNKNOWN,
    }),
    InvoiceStatus.DELIVERED: frozenset({InvoiceStatus.CREDITED, InvoiceStatus.ACCEPTED}),
    InvoiceStatus.ACCEPTED: frozenset({InvoiceStatus.CREDITED}),
    InvoiceStatus.REJECTED: frozenset({InvoiceStatus.READY_TO_SEND, InvoiceStatus.CANCELLED}),
    InvoiceStatus.DELIVERY_FAILED: frozenset({InvoiceStatus.READY_TO_SEND, InvoiceStatus.CANCELLED}),
    # Reconciliation can resolve an unknown state directly to any real
    # outcome — the transmission event log records what was actually learned.
    InvoiceStatus.TRANSMISSION_UNKNOWN: frozenset({
        InvoiceStatus.REQUIRES_RECONCILIATION,
        InvoiceStatus.READY_TO_SEND, InvoiceStatus.SENT_TO_PROVIDER,
        InvoiceStatus.SUBMITTED_TO_SDI, InvoiceStatus.DELIVERED,
        InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED, InvoiceStatus.DELIVERY_FAILED,
    }),
    InvoiceStatus.REQUIRES_RECONCILIATION: frozenset({
        InvoiceStatus.READY_TO_SEND, InvoiceStatus.SENT_TO_PROVIDER,
        InvoiceStatus.SUBMITTED_TO_SDI, InvoiceStatus.DELIVERED,
        InvoiceStatus.REJECTED, InvoiceStatus.DELIVERY_FAILED,
    }),
    InvoiceStatus.CREDITED: frozenset(),
    InvoiceStatus.CANCELLED: frozenset(),
    InvoiceStatus.IMPORTED: frozenset(),
}


class SdiStatus(StrEnum):
    """Normalized SdI outcome axis, where the provider exposes it."""

    UNKNOWN = "unknown"
    NOT_SENT = "not_sent"
    SUBMITTED = "submitted"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    REJECTED = "rejected"


class PaymentStatus(StrEnum):
    """Separate axis — never merged with transmission status."""

    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    WRITTEN_OFF = "written_off"


class ProviderHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTHENTICATION_ERROR = "authentication_error"
    CONFIGURATION_ERROR = "configuration_error"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
