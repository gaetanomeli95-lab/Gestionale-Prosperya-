"""Central provider registry.

Provider selection is resolved HERE — never via ``if provider == "aruba"``
conditionals scattered through the codebase. Each registered key identifies
a provider + adapter API version (e.g. ``stub-sandbox/v1``).
"""
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.modules.billing.providers.base import BillingProvider

_REGISTRY: dict[str, type[BillingProvider]] = {}


def register(cls: type[BillingProvider]) -> type[BillingProvider]:
    """Class decorator: ``@register`` adds ``cls.key/cls.api_version``."""
    key = f"{cls.key}/{cls.api_version}"
    _REGISTRY[key] = cls
    return cls


def adapter_for(provider_key: str, api_version: str) -> type[BillingProvider]:
    cls = _REGISTRY.get(f"{provider_key}/{api_version}")
    if cls is None:
        raise NotFoundError(
            f"No billing adapter registered for '{provider_key}' api '{api_version}'.",
            code="unknown_billing_provider",
        )
    return cls


def available_providers() -> list[dict[str, Any]]:
    return [
        {"key": cls.key, "api_version": cls.api_version}
        for cls in _REGISTRY.values()
    ]


def _resolve_credentials(config) -> dict[str, str]:
    """Secrets are NEVER stored in the database. The config row holds a
    ``credentials_ref`` — the name of an env var / secret-manager key whose
    value is a JSON object of credentials."""
    if not config.credentials_ref:
        return {}
    import json

    raw = os.environ.get(config.credentials_ref, "")
    if not raw:
        return {}
    try:
        return dict(json.loads(raw))
    except ValueError:
        return {}


def get_active_provider(db: Session) -> tuple[Any, "Any"]:
    """Return (config_row, adapter_instance) for the active provider."""
    from app.modules.billing.models import BillingProviderConfig

    config = db.scalar(
        select(BillingProviderConfig).where(BillingProviderConfig.is_active.is_(True))
    )
    if config is None:
        raise ConflictError(
            "No electronic invoicing provider is configured.",
            code="no_billing_provider",
        )
    cls = adapter_for(config.provider_key, config.api_version)
    adapter_config = {"environment": config.environment, **(config.config or {})}
    return config, cls(config=adapter_config, credentials=_resolve_credentials(config))


# Built-in adapters register themselves at import time.
from app.modules.billing.providers import stub as _stub  # noqa: F401, E402 — self-registers on import
