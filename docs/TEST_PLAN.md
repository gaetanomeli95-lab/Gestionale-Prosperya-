# Test Plan

## Pyramid

| Layer | Tools | Scope |
|---|---|---|
| Backend unit/domain | pytest | rules, normalization, dedupe, state machines, numbering |
| Backend API | pytest + FastAPI TestClient | endpoints, auth, RBAC, error envelope, pagination |
| DB/integration | pytest (SQLite CI / Postgres compose) | constraints, FK, transactions, migrations |
| Billing contract | pytest vs stub adapter | idempotency, unknown states, webhook dedupe, immutability |
| Frontend component | vitest (planned) | forms, tables, guards |
| E2E | Playwright (planned) | login → create → convert → invoice flows |

## Critical coverage (implemented)

- auth: login ok/wrong password/me/guarded routes
- companies: VAT normalization, exact-duplicate 409 with matches, probable-match check endpoint, pagination, soft-delete, stale-version 409, completeness report
- leads: conversion creates company+contact+opportunity in one transaction; double conversion blocked
- pipeline: stage move → won sets status+closed_at; task completion timestamp
- RBAC: readonly read-only enforced server-side; consultant cannot submit invoices
- timeline: activity events recorded on entity changes
- billing: totals, finalize numbering sequential, immutability, idempotent send via submission key, timeout → `transmission_unknown` → reconcile resolves, webhook dedupe/out-of-order/unverified, imported invoices never retransmit, provider config + health

## Acceptance gate (run before milestones)

- `pytest` green; `ruff check` clean
- `tsc -b` + `vite build` clean
- Alembic upgrade from empty DB
- API + frontend boot

## Planned

- Playwright critical flows (create company, duplicate VAT blocked, lead convert, invoice send)
- Migration test in CI against Postgres container
- Frontend vitest setup for forms/validation
