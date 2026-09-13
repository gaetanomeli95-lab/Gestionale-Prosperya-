# Deployment

## Environments

| Env | Purpose | DB |
|---|---|---|
| local | developer machine | SQLite fallback or dockerized Postgres 16 |
| staging | pre-production | PostgreSQL 16 |
| production | Prosperya operations | PostgreSQL 16 (managed or self-hosted) |

## Environment variables

See `.env.example`. Key vars:

| Var | Notes |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…` in prod; `sqlite:///./dev.db` local fallback |
| `JWT_SECRET` | ≥32 random bytes; rotate on compromise |
| `CORS_ORIGINS` | comma-separated allowed origins |
| `ENVIRONMENT` | `development` / `test` / `production` (prod disables /docs) |
| `BILLING_ISSUER_*` | issuer identity snapshotted onto invoices |
| `*_CREDENTIALS` refs | billing provider secrets — referenced by name, JSON blob in env/secret manager |

## Startup sequence (production)

1. `alembic upgrade head`
2. `uvicorn app.main:app` behind HTTPS reverse proxy
3. frontend static build served by the same or a static host
4. `GET /health` for liveness

## Backups & recovery

- PostgreSQL: scheduled `pg_dump` / managed snapshots; restore rehearsed periodically.
- Document/object storage (Phase 2): provider-side versioning + backup.
- Migrations: tested `upgrade head` from empty DB in CI; downgrades reviewed per migration.
- Billing: transmission events and webhook raw payloads are part of the DB backup — provider-side loss does not lose Prosperya's fiscal records.

## Observability

- Structured app logs (module + level + message); request errors carry a stable `code`.
- Health endpoint `/health`; billing provider health via `/billing/provider/test`.
- Future: error monitoring (Sentry-class), metrics, alert on `transmission_unknown` backlog.

## Rollback

- App rollback: redeploy previous build; migrations must remain backward compatible within a release window.
- Billing provider rollback: activate the previous `billing_provider_configs` row — historical invoices keep their original provider references.
