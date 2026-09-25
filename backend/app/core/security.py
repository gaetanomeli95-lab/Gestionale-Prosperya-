"""Password hashing (argon2id via pwdlib) and JWT access tokens."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config import get_settings


def _build_password_hash() -> PasswordHash:
    """Argon2id in both profiles; only the cost parameters differ.

    'fast' exists so the test suite does not spend ~0.8 s per login on a
    laptop. It is refused in production by Settings validation. Because
    Argon2 encodes its parameters inside the hash string, a 'fast' context
    still verifies 'standard' hashes and vice versa.
    """
    if get_settings().argon2_cost_profile == "fast":
        return PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8 * 1024, parallelism=1),))
    return PasswordHash.recommended()


_password_hash = _build_password_hash()


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _password_hash.verify(plain, hashed)
    except Exception:  # noqa: BLE001 — any malformed hash must fail closed
        return False


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID:
    """Return the user id or raise UnauthorizedError."""
    from app.core.errors import UnauthorizedError

    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token.")
        return UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired token.") from None
