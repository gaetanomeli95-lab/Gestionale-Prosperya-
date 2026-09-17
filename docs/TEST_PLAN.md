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
- treasury: open items idempotent import, deterministic reconciliation L1/L2 with human approval, cash position + forecast with explicit `not_calculable`, aging, provider sandbox
- fiscal: golden settlement cases (payable/carry-forward/credit/quarterly+interest), effective-dated rule resolution (no applicable rule → refusal), entry classification bounded, append-only register + system_derived confirmations, settlement versioning, human-only validation (note+ack on critical), exactly-once treasury open item, deadline deferral calendar, F24 lifecycle + export gating, tenant/company isolation, fiscal RBAC, cockpit/hub fiscal signals + liquidity-risk cross signal, assistant read-only tools + refusal on calculation/out-of-scope
- controlling: debt facilities + instalment lifecycle (settle paid/waived, no treasury double-count), DSCR/continuity/margin-of-safety refuse on missing data (null, never zero), versioned effective-dated EW rules with provenance, idempotent detection by dedupe_key, auto-resolution on cleared condition, human-audited alert lifecycle (acknowledge/resolve/dismiss), scenario re-run with verbatim assumptions, tenant/company isolation, controlling RBAC, cockpit/hub early-warning signals, assistant read-only tools (no recalculation, no legal crisis determination)

## E2E acceptance flow — controlling (manual, demo tenant `cliente-demo`)

1. Login → azienda demo → `/controlling`: tab Panoramica mostra DSCR, continuità 12 mesi, contatori alert; stati `insufficient_data`/`not_applicable` mai resi come €0.
2. Tab Debito: crea facility → aggiungi rata → settle `paid`/`waived` → la rata non compare come open item in tesoreria.
3. Tab Early Warning: "Rivaluta segnali" → alert `EW-FIN-OVERDUE` (critical) dal seed; acknowledge → resolve con nota → dismissed; ogni transizione richiede conferma e resta auditata.
4. Tab Scenari: esegui BASE poi STRESS → tabella comparativa con delta KPI; le ipotesi sono ripetute verbatim.
5. Cockpit azienda: blocco "Controlling & early warning" con alert e link al workspace; Hub: colonna EW + "Perché ora" (n. segnali + top signal).
6. Assistant: "com'è il DSCR?" → tool read-only con evidence; "l'azienda è in crisi?" → risposta con `legal_notice`, nessuna determinazione; "perché questa azienda è prima nell'hub?" → `get_hub_position` con ragioni deterministiche.

## Acceptance gate (run before milestones)

- `pytest` green; `ruff check` clean
- `tsc -b` + `vite build` clean
- Alembic upgrade from empty DB
- API + frontend boot

## Planned

- Playwright critical flows (create company, duplicate VAT blocked, lead convert, invoice send)
- Migration test in CI against Postgres container
- Frontend vitest setup for forms/validation
