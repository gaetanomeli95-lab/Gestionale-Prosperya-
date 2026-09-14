"""Provider-independent banking contract (account information only).

The treasury domain speaks ONLY to this interface. PSD2/open-banking
aggregators, CBI flows, bank CSV exports and manual entry are all adapters
behind it — provider payload shapes, auth dances and consent lifecycles never
leak into the domain, routers or frontend.

Deliberately **read-only**: no payment initiation. Moving money is a legally
sensitive irreversible action and is out of scope (MASTER_SPEC §3.1).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


class BankErrorCategory(StrEnum):
    """Normalized failure taxonomy — adapters MUST map provider errors here."""

    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    CONSENT_EXPIRED = "consent_expired"        # PSD2 consent must be renewed
    CONSENT_REVOKED = "consent_revoked"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    MALFORMED_RESPONSE = "malformed_response"
    NOT_SUPPORTED = "not_supported"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class BankError:
    category: BankErrorCategory
    message: str                      # safe, user-displayable
    retryable: bool = False
    technical_detail: str | None = None   # logs only


@dataclass(frozen=True)
class BankCapabilities:
    supports_balances: bool = True
    supports_transactions: bool = True
    supports_consent_renewal: bool = False
    supports_sandbox: bool = False
    # True only for adapters talking to a real institution. The UI must label
    # everything else as sandbox/simulated data.
    is_real_institution: bool = False
    max_history_days: int = 90


@dataclass(frozen=True)
class ProviderAccount:
    """An account as described by the provider."""

    provider_account_id: str
    label: str
    bank_name: str | None = None
    iban_last4: str | None = None
    currency: str = "EUR"


@dataclass(frozen=True)
class ProviderBalance:
    provider_account_id: str
    amount: Decimal
    balance_date: date
    currency: str = "EUR"
    kind: str = "booked"              # booked | available — never mixed silently


@dataclass(frozen=True)
class ProviderTransaction:
    """A movement as described by the provider.

    `provider_tx_id` must be stable across refreshes: it is the idempotency
    anchor that makes re-syncing safe.
    """

    provider_tx_id: str
    booking_date: date
    value_date: date
    amount: Decimal                   # signed: negative = outflow
    description: str = ""
    counterparty_name: str | None = None
    counterparty_iban_last4: str | None = None
    currency: str = "EUR"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectionState:
    status: str                       # matches models.ConnectionStatus
    detail: str | None = None
    expires_at: str | None = None
    environment: str | None = None


@dataclass(frozen=True)
class BankResult:
    """Normalized result of any banking operation."""

    ok: bool
    accounts: tuple[ProviderAccount, ...] = ()
    balances: tuple[ProviderBalance, ...] = ()
    transactions: tuple[ProviderTransaction, ...] = ()
    connection: ConnectionState | None = None
    error: BankError | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class BankingProvider(ABC):
    """Stable internal contract every banking adapter must implement.

    Adapters are versioned per provider API (``key/api_version``); a provider
    API upgrade means a new adapter version, never a domain change.
    """

    key: str
    api_version: str

    def __init__(self, config: dict[str, Any], credentials: dict[str, str]):
        self.config = config
        self.credentials = credentials

    @property
    def environment(self) -> str:
        return str(self.config.get("environment", "sandbox"))

    @property
    @abstractmethod
    def capabilities(self) -> BankCapabilities: ...

    @abstractmethod
    def validate_configuration(self) -> list[str]:
        """Return configuration problems ([] means valid)."""

    @abstractmethod
    def connect_account(self, *, reference: str) -> BankResult:
        """Start/confirm an account-information consent for one account."""

    @abstractmethod
    def refresh_accounts(self) -> BankResult:
        """List the accounts reachable with the current consent."""

    @abstractmethod
    def get_balances(self, provider_account_id: str) -> BankResult: ...

    @abstractmethod
    def refresh_transactions(self, provider_account_id: str, *,
                             date_from: date, date_to: date) -> BankResult:
        """Return movements in the window. MUST be repeatable: the same window
        yields the same `provider_tx_id` values."""

    @abstractmethod
    def connection_status(self) -> BankResult: ...

    def revoke_connection(self) -> BankResult:
        return BankResult(
            ok=False,
            error=BankError(
                category=BankErrorCategory.NOT_SUPPORTED,
                message="Questo provider bancario non supporta la revoca programmatica.",
            ),
        )
