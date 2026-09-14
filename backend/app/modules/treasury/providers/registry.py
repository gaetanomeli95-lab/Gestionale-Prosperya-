"""Central banking-provider registry.

Provider selection is resolved HERE, never with `if provider == "..."`
scattered around. Keys identify provider + adapter API version, e.g.
``sandbox-openbanking/v1``.
"""
import json
import os
from typing import Any

from app.core.errors import NotFoundError
from app.modules.treasury.providers.base import BankingProvider

_REGISTRY: dict[str, type[BankingProvider]] = {}


def register(cls: type[BankingProvider]) -> type[BankingProvider]:
    _REGISTRY[f"{cls.key}/{cls.api_version}"] = cls
    return cls


def adapter_for(provider_key: str, api_version: str) -> type[BankingProvider]:
    cls = _REGISTRY.get(f"{provider_key}/{api_version}")
    if cls is None:
        raise NotFoundError(
            f"Nessun adapter bancario registrato per '{provider_key}' api '{api_version}'.",
            code="unknown_banking_provider",
        )
    return cls


def available_providers() -> list[dict[str, Any]]:
    return [
        {
            "key": cls.key,
            "api_version": cls.api_version,
            "is_real_institution": cls({"environment": "sandbox"}, {}).capabilities.is_real_institution,
        }
        for cls in _REGISTRY.values()
    ]


def resolve_credentials(credentials_ref: str | None) -> dict[str, str]:
    """Secrets are NEVER stored in the database: the account row holds the
    *name* of an env var / secret-manager key containing a JSON object."""
    if not credentials_ref:
        return {}
    raw = os.environ.get(credentials_ref, "")
    if not raw:
        return {}
    try:
        return dict(json.loads(raw))
    except ValueError:
        return {}


def provider_for_account(account) -> BankingProvider:
    """Instantiate the adapter configured on a `BankAccount` row."""
    cls = adapter_for(account.provider_key, account.provider_api_version or "v1")
    config = {
        "environment": "sandbox",
        "provider_account_id": account.provider_account_id,
        "seed": account.provider_account_id,
        **(account.config or {}),
    }
    return cls(config=config, credentials=resolve_credentials(account.credentials_ref))


# Built-in adapters self-register on import.
from app.modules.treasury.providers import sandbox as _sandbox  # noqa: F401, E402
