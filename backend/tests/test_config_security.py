"""Configuration hardening (audit T4): JWT secret policy and hash profile guard."""
import re

import pytest

from app.config import JWT_SECRET_MIN_BYTES, InsecureConfigurationError, Settings
from app.core.security import hash_password, verify_password

STRONG = "a" * 48


def _settings(**kw) -> Settings:
    """Hermetic Settings: ignore .env AND the conftest environment overrides."""
    kw.setdefault("password_hash_profile", "standard")
    return Settings(_env_file=None, **kw)


def test_dev_accepts_placeholder_secret_but_reports_problems():
    s = _settings(environment="development", jwt_secret="change-me-in-production")
    assert "placeholder" in " ".join(s.jwt_secret_problems)


def test_strong_secret_has_no_problems():
    assert _settings(environment="development", jwt_secret=STRONG).jwt_secret_problems == []


@pytest.mark.parametrize("secret", ["change-me-in-production", "hunter2-xyz", "x" * (JWT_SECRET_MIN_BYTES - 1)])
def test_production_refuses_weak_secret(secret):
    with pytest.raises(InsecureConfigurationError) as ei:
        _settings(environment="production", jwt_secret=secret)
    assert secret not in str(ei.value)          # never echo the secret


def test_production_refuses_fast_hash_profile():
    with pytest.raises(InsecureConfigurationError, match="PASSWORD_HASH_PROFILE"):
        _settings(environment="production", jwt_secret=STRONG, password_hash_profile="fast")


def test_production_accepts_strong_config():
    s = _settings(environment="production", jwt_secret=STRONG)
    assert s.is_production and s.jwt_secret_problems == []


def test_bootstrap_generated_secret_is_strong():
    """The first-run .env generator must emit a secret that passes the policy."""
    import secrets as _s
    generated = _s.token_urlsafe(48)               # same call bootstrap._ensure_env uses
    s = _settings(environment="production", jwt_secret=generated)
    assert len(generated.encode()) >= JWT_SECRET_MIN_BYTES and s.jwt_secret_problems == []


def test_hash_is_argon2id_and_roundtrips():
    h = hash_password("pw")
    assert h.startswith("$argon2id$")
    assert verify_password("pw", h) and not verify_password("nope", h)


def test_fast_profile_verifies_standard_hash():
    """Hashes carry their parameters: a fast context verifies a standard hash."""
    from pwdlib import PasswordHash
    standard = PasswordHash.recommended().hash("pw")
    assert re.match(r"\$argon2id\$v=19\$m=65536,t=3,p=4\$", standard)
    assert verify_password("pw", standard)


def test_malformed_hash_fails_closed():
    assert verify_password("pw", "not-a-hash") is False
