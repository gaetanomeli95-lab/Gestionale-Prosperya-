"""Application configuration. All values overridable via environment / .env."""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: HS256 keys must be at least as long as the hash output (RFC 7518 §3.2).
JWT_SECRET_MIN_BYTES = 32
#: Well-known placeholder secrets that must never reach production.
_PLACEHOLDER_SECRETS = frozenset({
    "change-me-in-production",
    "change-me-use-32+-random-bytes",
    "secret", "changeme", "password",
})


class InsecureConfigurationError(RuntimeError):
    """Raised at startup when a production deployment is misconfigured."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Prosperya CRM"
    environment: str = "development"  # development | test | production

    # PostgreSQL in production/dev-with-docker; sqlite only as local fallback.
    database_url: str = "sqlite:///./dev.db"

    jwt_secret: str = "change-me-in-production"  # noqa: S105 — dev default, refused in production
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    # Login brute-force throttle (attempts per IP / per email in a 5-min window). 0 disables.
    login_max_attempts: int = 30
    # Argon2id cost profile: "standard" (pwdlib recommended, ~0.8 s/verify) or
    # "fast" (test-only, ~0.03 s). "fast" is refused in production. Hashes
    # embed their own parameters, so mixing profiles never breaks verification.
    argon2_cost_profile: str = "standard"

    @property
    def jwt_secret_problems(self) -> list[str]:
        """Why the current JWT secret would be unsafe for production (empty = fine)."""
        problems = []
        if len(self.jwt_secret.encode("utf-8")) < JWT_SECRET_MIN_BYTES:
            problems.append(f"JWT_SECRET shorter than {JWT_SECRET_MIN_BYTES} bytes")
        if self.jwt_secret.lower() in _PLACEHOLDER_SECRETS:
            problems.append("JWT_SECRET is a well-known placeholder")
        return problems

    @model_validator(mode="after")
    def _refuse_insecure_production(self) -> "Settings":
        if not self.is_production:
            return self
        problems = list(self.jwt_secret_problems)
        if self.argon2_cost_profile != "standard":  # noqa: S105
            problems.append("argon2_cost_profile must be 'standard' in production")
        if problems:
            # Never echo the secret itself.
            raise InsecureConfigurationError(
                "Refusing to start in production: " + "; ".join(problems)
                + ". Generate a secret with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return self

    # Comma-separated list of allowed CORS origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    seed_admin_email: str = "admin@prosperya.it"
    seed_admin_password: str = "prosperya-admin-dev"  # noqa: S105 — dev seed only

    # Billing issuer identity — snapshotted onto invoices at finalize time.
    billing_issuer_name: str = "Prosperya S.r.l."
    billing_issuer_vat: str = "07415020820"
    billing_issuer_tax_code: str = "07415020820"
    billing_issuer_address: str = "Via Torino, 8"
    billing_issuer_city: str = "Altavilla Milicia"
    billing_issuer_postal_code: str = "90010"
    billing_issuer_country: str = "Italia"
    billing_issuer_pec: str = ""

    # Document storage — logical provider key + local root for the V1
    # filesystem provider. Domain code never sees real paths.
    document_storage_provider: str = "local_filesystem"
    document_storage_dir: str = "storage/documents"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
