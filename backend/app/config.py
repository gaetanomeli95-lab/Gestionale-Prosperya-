"""Application configuration. All values overridable via environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Prosperya CRM"
    environment: str = "development"  # development | test | production

    # PostgreSQL in production/dev-with-docker; sqlite only as local fallback.
    database_url: str = "sqlite:///./dev.db"

    jwt_secret: str = "change-me-in-production"  # noqa: S105 — dev default, must be overridden in prod
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    # Login brute-force throttle (attempts per IP / per email in a 5-min window). 0 disables.
    login_max_attempts: int = 30

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
