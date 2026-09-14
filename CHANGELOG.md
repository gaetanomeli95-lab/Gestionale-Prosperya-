# Changelog

All notable changes to Prosperya CRM. Format follows Keep a Changelog.

## [Unreleased]

### Added — Multi-tenancy (2026-09-14)

- `tenants` table + `TenantMixin`; `tenant_id` on every business entity; tenant context dependency (`X-Tenant-Id` honoured for staff roles, client roles locked to their own tenant).
- Client roles `client_admin` / `client_operator` / `client_readonly`; tenant-scoped uniqueness for VAT, service-line codes, pipeline stages, invoice numbering, webhook events.
- Per-tenant billing provider configuration; webhook ingestion resolves the tenant via signature verification.
- Fresh Alembic baseline; seed creates platform org + demo client tenant; tenant switcher in the app shell.

### Added — Controllo di gestione + AI CFO (ported from prototype v0, 2026-09-14)

- `management` module: append-only consuntivi, bounded/atomic/idempotent CSV import, versioned monthly budgets, overview with formula trace, data-quality block, deterministic alerts, previous-year comparison, tenant-wide hub. Money as Decimal / `NUMERIC(20,2)`, serialised as strings; missing data is `null`, never `0`.
- `assistant` module: `AIProvider` protocol, allow-listed tools with per-call re-authorization, typed answer items (FACT/CALCULATION/ASSUMPTION/SUGGESTION), Decimal scenario engine, explicit limitations. Ships with a declared local deterministic mock.
- Frontend pages "Controllo di gestione" (KPI, monthly consuntivo-vs-budget chart, budget editor, cost categories, quality/provenance) and "AI CFO" (chat with typed items, tools used, limitations).
- Login brute-force throttle (per-IP / per-email) + constant-time unknown-email handling.
- UI: lucide icons, funnel chart, KPI accent edges, split-screen branded login.

### Added — Phase 0 foundation

- Repository structure, docs set, `.env.example`, docker-compose, CI workflow.
- FastAPI modular monolith: config, error envelope, structured logging, health.
- JWT auth (argon2id hashing) + centralized RBAC (admin/management/consultant/backoffice/readonly).
- Alembic migrations; seed script with demo data.

### Added — Phase 1 CRM core

- Companies with VAT normalization, duplicate detection (exact + probable), completeness report, soft delete, optimistic concurrency.
- Contacts + company-contact links.
- Leads with one-click conversion → company + contact + opportunity (no retyping).
- Configurable service lines + pipeline stages; opportunities with guarded stage moves (won/lost).
- Tasks, notes, unified activity timeline, append-only audit log.
- Global search, saved-filter-ready list endpoints (paged/sorted/filtered), operational dashboard.

### Added — Billing foundation (provider-independent)

- Invoice domain: drafts, lines, totals, transaction-safe numbering, customer/issuer snapshots, immutability after issue.
- Normalized status machine (internal / provider / SdI axes separated).
- `BillingProvider` interface + versioned adapter registry + `stub-sandbox/v1` test adapter.
- Transactional outbox for sends, submission-key idempotency, `transmission_unknown` + reconciliation, idempotent webhook ingestion, transmission history, provider health/config (admin).
- Contract tests covering the lifecycle end-to-end.

### Docs

- MASTER_SPEC, DISCOVERY, ARCHITECTURE, DATA_MODEL, BRAND_SYSTEM, UX_RULES,
  TEAMSYSTEM_BENCHMARK, SECURITY, IMPORT_STRATEGY, AI_ARCHITECTURE,
  TEST_PLAN, DEPLOYMENT, DECISIONS, BILLING_ARCHITECTURE, INTEGRATIONS.
