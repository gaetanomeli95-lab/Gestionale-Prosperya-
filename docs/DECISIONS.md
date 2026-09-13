# Architecture Decisions (ADR log)

## ADR-001 — Modular monolith

Single FastAPI app organized in `app/modules/<domain>` (models / schemas /
service / router). Extraction path is preserved by module boundaries and a
provider/registry pattern; microservice complexity deferred until an actual
operational need exists.

## ADR-002 — PostgreSQL 16+ with psycopg; SQLite dev fallback

Production target is current stable PostgreSQL via `psycopg` driver. The dev
machine lacks Docker/PostgreSQL, so `DATABASE_URL` supports
`sqlite:///./dev.db` for local runs and tests. Portable constructs only
(JSON instead of ARRAY/JSONB, portable UUID type). CI should additionally
run the suite against Postgres in docker-compose.

## ADR-003 — Synchronous SQLAlchemy 2.x

Sync sessions keep the domain simple; FastAPI runs handlers in a threadpool.
Revisit only if measured contention requires async.

## ADR-004 — JWT access token now; refresh cookie later

Bearer JWT (HS256, `JWT_SECRET`) returned by `/auth/login`. Deliberate
deferral: httpOnly refresh-cookie rotation, CSRF token and login rate
limiting are scheduled before production. Tracked as a security backlog item.

## ADR-005 — Soft delete + optimistic concurrency

Core entities carry `deleted_at` and `version`. Deletes are archives;
writes require the version the client read (409 `stale_version` otherwise).

## ADR-006 — Custom Prosperya design system, no UI kit

Tokens in `frontend/src/design-system/tokens.css` derived from prosperya.it
(petrol `#315f67`, champagne `#c9b991`, ivory surfaces, dark `#172326`
chrome, Playfair Display + DM Sans). Full control, no framework lock-in.

## ADR-007 — Activity timeline ≠ audit log

`activity_events` = user-facing business narrative. `audit_log` = security
trail with field-level before/after. Separate tables, separate retention
policies possible.

## ADR-008 — Imports via staging, never direct

11-step pipeline (see `docs/IMPORT_STRATEGY.md`): upload → staging → mapping
→ normalize → validate → dedupe → preview → errors → confirm → apply →
audit. Idempotent, provenance-stamped, reversible.

## ADR-009 — Billing is provider-independent (2026-09-13)

Invoices live in Prosperya's DB; providers are transport channels behind
`BillingProvider` + a central registry (`provider_key/api_version`).
Normalized internal state machine; raw provider codes preserved;
`submission_key` idempotency; `transmission_unknown` blocks blind retries;
transactional outbox for sends; webhook ingestion deduped by provider event
id; provider secrets referenced by env-var name only. See
`docs/BILLING_ARCHITECTURE.md`.

## ADR-010 — Stub provider only, no real connector yet

`stub-sandbox/v1` exercises the contract end-to-end (config, health,
idempotent submit, timeout→unknown→reconcile, webhooks) and refuses
`production`. Real adapters (Aruba, Fatture in Cloud, TeamSystem, direct
SdI) land as versioned modules after official docs are verified.

## Open decisions

- Refresh-token strategy + session UX (ADR-004 follow-up).
- FatturaPA XML: generated in-house vs provider-generated — decide at provider selection.
- Job queue tech for outbox dispatch (function now; worker/scheduler later).
- Object storage choice for documents (Phase 2).
- Growth Factors framework configuration model (Phase 4).
