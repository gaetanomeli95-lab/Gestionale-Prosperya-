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
