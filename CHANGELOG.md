# Changelog

All notable changes to Prosperya CRM. Format follows Keep a Changelog.

## [Unreleased]

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
