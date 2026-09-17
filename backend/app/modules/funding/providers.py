"""Source ingestion interface — the only way funding data enters the system.

V1 ships two providers:
  - ManualProvider: an operator enters a verified official notice.
  - StructuredImportProvider: a validated JSON payload (e.g. curated export).

Both produce the same canonical payload consumed by
`service.create_programme`. No web scraping, no AI extraction in V1 —
those are future providers behind this same interface, and they will
still require human verification before a version becomes usable.
"""
from dataclasses import dataclass, field
from typing import Protocol


class SourceProvider(Protocol):
    """A provider turns an external artefact into a canonical programme
    payload. It never writes to the database — the service layer does."""

    name: str

    def build(self, artefact: dict) -> dict:
        """Return a payload shaped like `schemas.ProgrammeCreate`."""
        ...


@dataclass
class ManualProvider:
    """Operator-entered notice: the artefact IS the payload."""

    name: str = "manual"

    def build(self, artefact: dict) -> dict:
        required = {"code", "title"}
        missing = required - set(artefact)
        if missing:
            raise ValueError(f"Campi obbligatori mancanti: {sorted(missing)}")
        return artefact


@dataclass
class StructuredImportProvider:
    """Validated JSON import — e.g. a curated export prepared offline.

    The artefact must carry `programmes: [...]`; each entry is passed
    through unchanged after a shape check.
    """

    name: str = "structured_import"
    required_keys: frozenset = field(
        default_factory=lambda: frozenset({"code", "title", "version"}))

    def build(self, artefact: dict) -> dict:
        missing = self.required_keys - set(artefact)
        if missing:
            raise ValueError(
                f"Payload strutturato incompleto: {sorted(missing)}")
        return artefact


PROVIDERS: dict[str, SourceProvider] = {
    p.name: p for p in (ManualProvider(), StructuredImportProvider())
}


def get_provider(name: str) -> SourceProvider:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"Provider sconosciuto: {name}. "
                         f"Disponibili: {sorted(PROVIDERS)}")
    return provider
