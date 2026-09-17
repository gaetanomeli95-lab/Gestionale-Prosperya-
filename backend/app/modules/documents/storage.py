"""Document storage abstraction.

Domain code never touches filesystem paths — it stores and retrieves bytes
through a provider using *logical* storage references. The V1 provider is
the local filesystem (dev/demo); S3, Azure Blob, Supabase Storage or
SharePoint can implement the same protocol later without touching the
domain.

Safety rules enforced here:
- filenames are sanitised (display name stays metadata, never a path)
- every resolved path must stay inside the storage root (no traversal)
- content is addressed by checksum — identical bytes are never overwritten
"""
import hashlib
import re
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from app.config import get_settings

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """Strip path separators and unsafe characters. The original filename is
    kept as display metadata on the version row — this is only the on-disk
    fragment."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _SAFE_NAME.sub("_", base).strip("._") or "file"
    return base[:120]


def sha256_stream(stream: BinaryIO) -> tuple[str, int]:
    """Compute sha256 + size while streaming; leaves the stream consumed."""
    h = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 512)
        if not chunk:
            break
        h.update(chunk)
        size += len(chunk)
    return h.hexdigest(), size


class StoredBlob(Protocol):
    """What a provider returns when content is read back."""

    def read(self) -> bytes: ...


class DocumentStorageProvider(Protocol):
    """Provider contract. `ref` is an opaque logical reference the provider
    interprets — never a client-supplied path."""

    key: str

    def store(self, *, ref: str, stream: BinaryIO) -> str: ...
    def open(self, *, ref: str) -> BinaryIO: ...
    def exists(self, *, ref: str) -> bool: ...


def build_ref(*, tenant_id: uuid.UUID, document_id: uuid.UUID,
              version_id: uuid.UUID, checksum: str,
              filename: str) -> str:
    """Logical reference layout: tenant/document/version/checksum_name.
    Hierarchical so a tenant prefix can map to a bucket/prefix later."""
    return (f"{tenant_id}/{document_id}/{version_id}/"
            f"{checksum[:12]}_{sanitize_filename(filename)}")


class LocalFilesystemStorage:
    """V1 provider — writes under `<document_storage_dir>` inside the
    backend working dir (gitignored `storage/`)."""

    key = "local_filesystem"

    def __init__(self, root: Path | None = None):
        self._root = (root or Path(get_settings().document_storage_dir)).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, ref: str) -> Path:
        """Resolve a logical ref to a real path, refusing anything that
        escapes the storage root (traversal, absolute paths, '..')."""
        if not ref or ref.startswith(("/", "\\")) or ".." in ref.split("/"):
            raise ValueError("Invalid storage reference.")
        path = (self._root / ref).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("Storage reference escapes the storage root.")
        return path

    def store(self, *, ref: str, stream: BinaryIO) -> str:
        path = self._resolve(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # Content-addressed: identical ref ⇒ identical bytes. Never
            # silently overwrite stored evidence.
            return ref
        with open(path, "wb") as fh:
            while True:
                chunk = stream.read(1024 * 512)
                if not chunk:
                    break
                fh.write(chunk)
        return ref

    def open(self, *, ref: str) -> BinaryIO:
        return open(self._resolve(ref), "rb")

    def exists(self, *, ref: str) -> bool:
        try:
            return self._resolve(ref).is_file()
        except ValueError:
            return False


_PROVIDERS: dict[str, type] = {"local_filesystem": LocalFilesystemStorage}


def get_storage(provider_key: str | None = None) -> DocumentStorageProvider:
    """Resolve the configured provider. Unknown keys fall back to local —
    the provider key is stored on each version so mixed estates stay
    readable."""
    key = provider_key or get_settings().document_storage_provider
    cls = _PROVIDERS.get(key, LocalFilesystemStorage)
    return cls()
