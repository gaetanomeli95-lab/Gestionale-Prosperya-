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

## ADR-011 — Multi-tenant by `tenant_id`, not separate databases (2026-09-14)

The product is a SaaS sold to client companies (S.r.l.), operated by the
consultancy. Isolation is logical: every tenant-owned table carries a
non-nullable `tenant_id` FK; every read/write path filters on the active
tenant context injected by the `tenant` dependency. Staff roles
(admin/consultant/backoffice) may switch tenant context; client roles are
locked to their own tenant. Rejected alternatives: schema-per-tenant and
DB-per-tenant (operationally heavy, no benefit at this scale);
PG Row-Level Security alone (SQLite-incompatible; may be added later as
defence-in-depth on top of explicit filtering).

## ADR-012 — "Prosperya" is a theme/codename, not the product (2026-09-14)

Product will be marketed under a different name and possibly white-labelled.
`APP_NAME` env var + token-level theming keep naming out of code paths.
Default theme remains the Prosperya-derived palette.

## ADR-013 — Management dataset, not general-ledger accounting (2026-09-14)

Ported from the abandoned prototype (`PROGRAMMA PROSPERYA` v0). Consuntivi are
normalised management rows (`revenue`/`cost`, category, date, amount); the
"risultato gestionale disponibile" is `ricavi − costi` over *available*
rows. It is explicitly **not** EBITDA, utile civilistico, or cash: invoices and
monthly aggregates do not prove competenza economica, ratei, risconti,
ammortamenti, or completeness. Every overview carries `quality`
(`covered_months`, `certified_complete=false`, `issues[]`) and `trace`
(`formula_version`, `source_ids`, `budget_version_ids`). Missing evidence is
`null`, never `0`. Rejected: labelling the figure EBITDA/utile to look
familiar to clients — false precision is worse than a missing number.

## ADR-014 — Append-only financial history, idempotent imports (2026-09-14)

`import_batches`, `actuals`, `budget_versions` reject UPDATE/DELETE at the
ORM (`before_update`/`before_delete` listeners). Budgets are versioned per
(company, year, month); reads pick the latest version. CSV import is bounded
(1 MiB / 5000 rows), atomic (`begin_nested` + company row lock), idempotent
(`idempotency_key` + `payload_hash`: same → replay, different → 409), and
duplicate-safe (`source_id` + `source_hash`: same content ignored, different
content → 409). On PostgreSQL the same guarantees are to be enforced with
`BEFORE UPDATE OR DELETE` triggers and a non-owner runtime role (see the
prototype's `0001_security.sql` — kept as blueprint for the PG hardening
migration in Phase 5).

## ADR-015 — Deterministic assistant with typed items (2026-09-14)

Ported from the prototype. `assistant` exposes an `AIProvider` Protocol whose
only job is `select_tools(message) → ProviderPlan`. The plan is validated
against an allow-list (`get_financial_summary`, `get_monthly_trend`,
`get_budget_variance`, `get_cost_breakdown`, `get_data_quality`,
`get_source_trace`); tools cannot change the selected period and re-check
tenant/company ownership. All arithmetic (incl. the revenue scenario engine)
is Decimal Python — the provider never computes. Answers are lists of
`{type: FACT|CALCULATION|ASSUMPTION|SUGGESTION, text}` plus `tools_used`,
`evidence` and `limitations`. The shipped provider is
`local-deterministic-mock` and says so in every response; a real LLM
provider (ADR-004/06 of `AI_ARCHITECTURE.md`) plugs into the same Protocol
later without touching tools or rendering. Rejected: agentic frameworks and
vector DBs at this stage — no requirement justifies them.

## Open decisions

- Refresh-token strategy + session UX (ADR-004 follow-up).
- FatturaPA XML: generated in-house vs provider-generated — decide at provider selection.
- Job queue tech for outbox dispatch (function now; worker/scheduler later).
- Object storage choice for documents (Phase 2).
- Growth Factors framework configuration model (Phase 4).
