# Test Plan

## Pyramid

| Layer | Tools | Scope | Where |
|---|---|---|---|
| Backend unit/domain | pytest | rules, normalization, dedupe, state machines, numbering | `backend/tests` |
| Backend API | pytest + FastAPI TestClient | endpoints, auth, RBAC, tenancy, error envelope, pagination | `backend/tests` |
| DB / migrations | pytest + Alembic on **PostgreSQL** (CI job) and SQLite | constraints, FK parity, up/down/up, seed idempotency | `test_schema_parity.py`, CI `backend-postgres` |
| Billing contract | pytest vs stub adapter + conformance kit | adapter resolution/versioning, idempotency, unknown states, status separation | `test_billing_contract.py`, `test_billing.py` |
| Frontend component | **Vitest + Testing Library (jsdom)** | forms, API client, loading/empty/error/permission states | `frontend/src/**/*.test.tsx` |
| E2E smoke | **Playwright** vs real backend (disposable SQLite + seed) | 5 critical business flows | `frontend/e2e/*.spec.ts` |

## Database dialect strategy (decided 2026-09-24)

PostgreSQL is the production target. SQLite is a convenience, and it hides
real defects — two were found in Phase B–F only by running PostgreSQL (a
poisoned connection from a SQLite PRAGMA, and a foreign key silently missing
from PostgreSQL schemas). Therefore:

1. **Local fast loop**: `pytest` runs against **in-memory SQLite** with the
   test-only Argon2 `fast` profile — ~2 min for the full suite on a laptop
   (was 9 min). Isolation is unchanged: schema once per session, seeded
   baseline, tests create their own entities.
2. **Same suite on PostgreSQL**: `TEST_DATABASE_URL=postgresql+psycopg://…`
   runs the identical tests on PostgreSQL. CI job `backend-postgres` does
   this on every push after `alembic upgrade head`, plus the migration cycle
   (empty → head → base → head) and the double seed (`scripts/seed_check.py`).
3. **Parity guards** run on both: `test_schema_parity.py` asserts every ORM
   foreign key exists in the target database; `test_orm_registry.py` proves
   the model registry does not depend on import order.
4. Anything that behaves differently between dialects is a **bug to fix on
   the PostgreSQL side**, never a reason to weaken a constraint so SQLite
   passes.

Run locally against PostgreSQL:

```bash
docker compose up -d db
TEST_DATABASE_URL=postgresql+psycopg://prosperya:prosperya-dev-only@localhost:5432/prosperya pytest
```

## Test-only knobs (never in production)

| Variable | Test value | Why |
|---|---|---|
| `ARGON2_COST_PROFILE` | `fast` | Argon2id t=1/m=8MiB instead of pwdlib recommended; same algorithm, ~25× faster login. Refused when `ENVIRONMENT=production`. |
| `LOGIN_MAX_ATTEMPTS` | `0` | fixtures log in per test; throttle is covered by `test_auth` |
| `DATABASE_URL` | `sqlite://` | in-memory, `StaticPool` so TestClient threads share the connection |

## Frontend tests

- `npm test` — Vitest component tests. Rules: query by **role / label /
  accessible name**, never by CSS class or DOM nesting, so tests survive the
  Phase H redesign. Fetch is mocked via `src/test/utils.tsx::mockApi`
  (unmocked calls fail loudly).
- `npm run test:e2e` — Playwright. Starts `backend/scripts/e2e_server.py`
  (Alembic head + demo seed on a throw-away SQLite file, fast Argon2) and the
  Vite dev server. Set `E2E_PYTHON` to your venv interpreter.

### The five smoke flows

| Flow | File | Covers | Known UI gaps hit |
|---|---|---|---|
| 1 CRM | `flow1-crm.spec.ts` | login → aziende → crea azienda (dialog) → dettaglio → contatto → opportunità → pipeline | company-detail *Contatti* tab is a placeholder; form labels not associated to inputs |
| 2 Practice | `flow2-practice.spec.ts` | pratica dal form → scadenza→task (exactly-once) → requisito documentale → dossier → coda attività | practice deadlines not creatable from UI |
| 3 Documents | `flow3-documents.spec.ts` | requisito → richiesta cliente → upload → fulfil → validazione → blocker risolto → dossier | requirement/validation only via API |
| 4 Funding | `flow4-funding.spec.ts` | programmi → match (unknown legit) → assessment → pratica finanziata → link Practice (ADR-023) → dossier | funding practice list shows id prefix, not programme title |
| 5 Controlling | `flow5-controlling.spec.ts` | facility + rata → scenari BASE/STRESS/UPSIDE → evaluate alert (idempotente, explainable) → tab EW/Scenari | — |
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

## Acceptance gate (automated in CI)

| Gate | Job |
|---|---|
| `ruff check app tests alembic scripts` | backend-fast |
| `pytest` on in-memory SQLite | backend-fast |
| `tsc -b`, `vitest run`, `vite build` | frontend |
| Alembic empty → head → base → head on PostgreSQL 16.15, single head | backend-postgres |
| Seed + preview seed twice, idempotent | backend-postgres |
| Full `pytest` on PostgreSQL (`TEST_DATABASE_URL`) | backend-postgres |
| 5 Playwright smoke flows | e2e |

## Still planned

- Frontend component coverage for forms with validation (needs label↔input association first, Phase H).
- Contract tests for the first real billing adapter (Phase G) — `TestContractKit` already runs on every registered adapter.
- Concurrency test for `sync_deadline_task` on PostgreSQL with two real sessions (the race is currently simulated).