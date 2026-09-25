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
| `JWT_SECRET` | ≥ 32 random bytes (`python -c "import secrets; print(secrets.token_urlsafe(48))"`); the app refuses to start in production with a short/placeholder value; rotate on compromise |
| `CORS_ORIGINS` | comma-separated allowed origins |
| `ARGON2_COST_PROFILE` | `standard` (default). `fast` is for the test suite only and is refused in production |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | consumed by `docker-compose.yml` for the local database; keep in sync with `DATABASE_URL` |
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

## Python dependency reproducibility (decided 2026-09-26)

Two layers, both committed:

| File | Role | Edited by |
|---|---|---|
| `backend/requirements.txt`, `backend/requirements-dev.txt` | **Intent**: direct dependencies with compatible ranges (`fastapi>=0.115,<1.0`). Small, readable. | humans |
| `backend/requirements.lock.txt`, `backend/requirements-dev.lock.txt` | **Resolution**: every transitive package pinned `==` with sha256 hashes. Generated. | `pip-compile` only |

Consumers of the lock: CI (`pip install --require-hashes -r requirements-dev.lock.txt`),
the backend `Dockerfile` (`requirements.lock.txt`), and future preview
packaging. Developers may install either; installing the lock is what CI
does, so prefer it when debugging a CI-only failure.

Why pip-tools and not `pip freeze`: freeze captures whatever happens to be in
a venv (including tooling like pip-tools itself and platform-specific
wheels); `pip-compile` resolves from the intent files only, is
deterministic, and `--generate-hashes` protects against tampered artefacts.
Why not Poetry/uv: no `pyproject.toml` packaging exists yet and adding a
second toolchain buys nothing today. Revisit when the backend is packaged.

Update process:

```bash
cd backend
pip install "pip-tools>=7.4,<8"
# edit requirements*.txt (intent), then:
pip-compile --generate-hashes --strip-extras --output-file requirements.lock.txt requirements.txt
pip-compile --generate-hashes --strip-extras --output-file requirements-dev.lock.txt requirements-dev.txt
pip install --require-hashes -r requirements-dev.lock.txt
pytest                      # the lock is part of the change under review
```

Bumping everything to the newest allowed versions: add `--upgrade`. Bumping
one package: `--upgrade-package sqlalchemy`. Never hand-edit a lock file.
