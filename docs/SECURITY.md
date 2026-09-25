# Security

## Authentication

- Email + password → short-lived JWT access token (HS256, `JWT_SECRET`).
- Passwords hashed with **argon2id** (pwdlib recommended profile).
- `GET /auth/me` resolves the user from the token; disabled accounts are rejected.
- Hardening backlog: httpOnly refresh-token cookie, token rotation, login rate limiting, password policy + reset flow. Tracked in `docs/DECISIONS.md` (ADR-004).

## Authorization (RBAC)

Backend is authoritative — the frontend only hides UI for ergonomics.
Roles: `admin`, `management`, `consultant`, `backoffice`, `readonly`.
Scopes are `<domain>:<action>` strings resolved centrally in `app/core/rbac.py`.

| Scope | admin | management | consultant | backoffice | readonly |
|---|---|---|---|---|---|
| all business `:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| business `:write` | ✓ | ✓ | ✓ | tasks/notes/contacts/billing only | — |
| `users:write` | ✓ | — | — | — | — |
| `billing:submit` | ✓ | ✓ | — | — | — |
| `billing:admin` | ✓ | — | — | — | — |

## Data protection

- Soft delete (`deleted_at`) on business entities; physical deletion is admin/audited only.
- Optimistic concurrency via `version` — stale writes return `stale_version` 409.
- Optimistic locking + guarded invoice state machine prevent illegal transitions.
- Audit log: append-only `audit_log` (actor, action, entity, before/after changes); never editable via UI.
- Billing secrets: only `credentials_ref` env/secret-manager key names are stored — never raw secrets; never serialized to the frontend.

## Transport / appsec checklist

- CORS restricted to `CORS_ORIGINS`.
- Request validation via Pydantic on every endpoint; consistent error envelope (no stack traces to clients).
- Secure file upload rules (type/size allowlist) required when document upload lands (Phase 2).
- Production must run behind HTTPS; set `ENVIRONMENT=production` (docs disabled).
- Rate limiting at the edge/reverse proxy (roadmap).
- Dependency monitoring via CI (`pip-audit`/`npm audit` recommended — see `docs/TEST_PLAN.md`).

## GDPR notes (Italy/EU)

Data minimisation, purpose-aware access via RBAC, auditability, retention and
export paths are designed in. Architecture alone is not legal compliance —
privacy review required before production use (see `docs/DECISIONS.md`).

## Verified state after Phase B–F (2026-09-24)

What the code actually enforces today — every line below is backed by a test.

### Secrets and configuration

- `JWT_SECRET` must be ≥ 32 bytes (HS256, RFC 7518 §3.2) and not a known
  placeholder. `Settings` exposes `jwt_secret_problems`; in
  `ENVIRONMENT=production` the process **refuses to start** with a weak or
  placeholder secret and never echoes the value (`test_config_security.py`).
- The first-run `.env` generator (`bootstrap._ensure_env`) uses
  `secrets.token_urlsafe(48)` — 64 URL-safe characters — verified against the
  same policy.
- Passwords: Argon2id via pwdlib. `ARGON2_COST_PROFILE=fast` exists for the
  test suite only and is refused in production; hashes embed their
  parameters, so profiles interoperate.
- Provider credentials are never stored in the database
  (`BillingProviderConfig.credentials_ref` names an environment/secret-manager
  key). Health checks are tested not to leak them.

### Authorization — backend is authoritative

`test_rbac_tenancy.py` (27 tests) proves, per representative resource:
401 without/with a garbage token; 403 for `readonly` on writes and for
`consultant`/`readonly` on user management; a deactivated user is locked out
even with a still-valid token; elevated actions require `users:write`.

### Tenant isolation — application-level (ADR-011, ADR-024)

Isolation is enforced by `get_tenant_ctx` + `scope()` / `get_owned()` on every
tenant-scoped query, not by the database. Verified: client roles cannot read
or mutate another tenant's entity by guessing its id (404, never 403 — no
existence leak) and cannot switch tenant via `X-Tenant-Id`; staff switching
partitions lists, detail reads and the audit log; invalid/unknown tenant
headers are rejected (403).

**PostgreSQL Row-Level Security is not enabled.** `docs/PG_RLS_BLUEPRINT.sql`
is a blueprint; ADR-024 lists the prerequisites (per-transaction
`SET LOCAL app.tenant_id`, non-owner runtime role, PostgreSQL-only preview).
Do not describe RLS as active in any user-facing material.

### Integrity guarantees at the database

- One live operational task per `(tenant_id, sync_key)` — partial unique index
  `uq_tasks_tenant_sync_key`; the service survives the race by adopting the
  winner (`test_exactly_once.py`).
- Every ORM foreign key exists in the target database
  (`test_schema_parity.py`); the `documents.current_version_id` FK that
  PostgreSQL schemas were missing is restored by migration `a7c1e3f9b2d4`.

### Audit

Practice lifecycle, document requirement creation/update/**fulfilment**,
client requests, deadline sync, funding decisions, controlling alert
transitions and provider configuration write `ActivityEvent`/`audit_log`
rows; the audit log is tenant-partitioned (tested). Not yet audited
consistently: user/permission changes across all paths — tracked in
`PROJECT_STATE_AUDIT.md`.
