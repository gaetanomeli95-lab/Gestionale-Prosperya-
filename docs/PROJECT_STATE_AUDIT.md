# Prosperya CRM — Project State Audit

**Date:** 2026-09-24
**Repository:** `gaetanomeli95-lab/Gestionale-Prosperya-`
**Auditor:** consolidation pass, Phase A of the V0.2 mission
**Method:** every claim below was verified against the actual Git objects,
by running the test suite, migrations, build and seed on the merged tree —
not from prior status reports.

---

## 1. Branches and HEAD commits

| Branch | HEAD | Date | Ahead of `main` | Note |
|---|---|---|---|---|
| `main` | `6741863` First-run setup, tenant provisioning, settings, portable launcher | 2026-09-14 | — | **Stale.** Contains only the CRM foundation. |
| `feat/prosperya-financial-core` | `2e9211c` fiscal: core v1 … | 2026-09-15 | +10 | HEAD label is misleading: its last commit is already the first fiscal commit. |
| `feat/prosperya-fiscal-core` | `cc96872` docs: fiscal architecture, ADR-020/021 | 2026-09-16 | +16 | |
| `feat/prosperya-controlling-early-warning` | `c47d09d` feat(controlling): /controlling workspace, migration | 2026-09-17 | +20 | |
| `feat/prosperya-funding-core` | `c45e010` feat(funding): Funding Core V1 | 2026-09-17 | +21 | |
| `feat/prosperya-document-practice-core` | `0af2ca4` feat: document & practice operations core | 2026-09-17 | +22 | **Contains every feature branch.** |
| `demo/giuseppe-preview-v01` | `89d9273` Preview build v0.1: visual redesign, demo dataset, packaging | 2026-09-17 | +21 | Branches off `controlling`, NOT off funding/documents. |
| `rebuild/prosperya-crm-v1` (local only) | `6741863` | — | 0 | Identical to `main`. Never pushed. |

The local clone had **no remote configured**; `origin` was added during this audit.

### 1.1 Topology — the branches are a single linear chain

```
main (6741863)
 └─ financial-core (+10)
     └─ fiscal-core (+6)
         └─ controlling-early-warning (+4)  ──┐
             └─ funding-core (+1)             │
                 └─ document-practice-core (+1)   ← FULL FEATURE TIP
                                              │
                            demo/giuseppe-preview-v01 (+1, packaging + seed + CSS)
```

Verified with `git merge-base --is-ancestor` for every pair. **No two feature
branches diverge from each other.** Each was branched from the previous one's
tip. This is the single most important finding: consolidation is not a
multi-way merge, it is `document-practice-core` + one cherry/merge of the
demo commit.

---

## 2. Functionality actually present per branch

| Area | Backend module(s) | Introduced on | Tests |
|---|---|---|---|
| CRM foundation: companies, contacts, leads, opportunities, pipeline, activities, tasks, notes, users, tenancy, RBAC, audit, setup wizard, settings | `companies contacts leads opportunities activities tasks notes users tenancy auth audit setup search service_lines dashboard` | `main` | `test_auth test_companies test_pipeline_and_leads test_setup_and_settings` |
| **Billing foundation** (provider-agnostic — see §9) | `billing` (+ `billing/providers/{base,registry,stub}`) | `main` (commit `9c10ba9`) | `test_billing` |
| Management control + AI CFO assistant (ported from prototype) | `management assistant` | `main` (`7383ae9`) | `test_management_and_assistant` |
| Treasury: open items, bank movements, reconciliation, cash engine, multi-company control hub, CFO cockpit, contribution margin, break-even, cost centres | `treasury cockpit management` | `financial-core` | `test_treasury_and_cockpit test_contribution_and_cost_centers` |
| Fiscal core v1: VAT registers, versioned settlements, fiscal deadlines, F24 drafts, cockpit signals, assistant tools | `fiscal` | `fiscal-core` | `test_fiscal` |
| Controlling / early warning: CCII rules, debt service, prospective DSCR, BASE/STRESS/UPSIDE scenarios, durable alerts, /controlling workspace | `controlling` | `controlling-early-warning` | `test_controlling` |
| Funding core v1: authorities, programmes (versioned), windows, requirements, deterministic rules engine, company profiles, funding practices, hub signals, /funding UI | `funding` | `funding-core` | `test_funding` |
| Document & practice core: Document/Version/Type/Link/Requirement/Validation, generic Practice, blockers, ClientRequest, deadline→task sync, audit | `documents practices` | `document-practice-core` | `test_documents_practices` |
| Preview: `preview_seed.py` (multi-company demo), PyInstaller spec, Inno Setup script, icon, launcher hardening, CSS token tweaks | — | `demo/giuseppe-preview-v01` | none (seed verified manually, see §10) |

Frontend pages present at the tip (21): Login, Setup, Dashboard, Companies,
CompanyDetail, Contacts, Leads, Pipeline, Tasks, Documents, Practices,
Treasury, Fiscal, Controlling (+ sub-folder), Funding, Management, Cockpit,
Hub, Billing, Assistant, Settings.

---

## 3. Functionality missing from `main`

Everything from §2 except the first three rows. Concretely `main` lacks:
treasury, cockpit/hub, fiscal, controlling, funding, documents, practices,
preview packaging, demo dataset, and 6 of the 8 Alembic migrations.

`main` is ~22 commits behind the real product. It should not be used as the
baseline for anything.

---

## 4. Overlapping implementations

None found at the module level — each domain lives in exactly one module and
the chain topology prevented parallel reimplementation.

Two soft overlaps worth watching (not bugs today):

- `funding_company_profiles` vs `companies`: the funding module keeps a
  per-company eligibility profile keyed to `companies.id`. This is a
  legitimate 1:1 extension, **not** a duplicate company entity — but any
  future "company master data" work must treat `companies` as the only
  source of truth.
- `practices` (generic, document-practice-core) vs `funding_practices`
  (funding-core). Funding practices were written one commit *before* the
  generic Practice domain existed. They are separate tables. Consolidation
  target: funding practices should become a specialisation of / link to the
  generic Practice (see §13, integration risk R3).

---

## 5. Conflicting implementations

None. The demo commit merged onto the feature tip with **zero conflicts**
(`git merge --no-ff` → "Automatic merge went well"). Files touched by both
sides (`bootstrap.py`, `launcher.py`, `.gitignore`, `AppShell.tsx`) merged
automatically and the merged tree passes the full suite.

---

## 6. Database migration graph

Single linear chain, **one head**, verified with `alembic heads`:

```
d67ce06be2f0  initial_schema                                  (main)
6250868682c8  management_control_tenant_fks                   (main)
c0cdade466e9  treasury_open_items_bank_movements_reconciliation (financial)
241a5cddffba  management_cost_nature_and_cost_centre          (financial)
f1a2b3c4d5e6  fiscal_core_v1                                  (fiscal)
3995df39ccc4  controlling_early_warning                       (controlling)
11baf798143b  funding_core                                    (funding)
fddef49e1556  document_practice_core                          (documents)  ← HEAD
```

Verified on an empty SQLite database:

- `upgrade head` from empty: OK
- `downgrade base`: OK (all 8 revisions have working `downgrade()`)
- `upgrade head` again: OK, `current` = `fddef49e1556`

The demo branch adds **no** migration; it only depends on schema up to
`3995df39ccc4`. Its seed runs cleanly against the full head schema.

Not yet verified: the same cycle on **PostgreSQL** (no Postgres/Docker on the
audit machine). Production targets Postgres (`config.py` comment, `psycopg`
in requirements). This is a Phase F item.

---

## 7. Backend architecture (as found)

- **FastAPI modular monolith**, Python 3.12, SQLAlchemy 2.x, Alembic,
  Pydantic v2, PyJWT + argon2 (`pwdlib`).
- `app/modules/<domain>/{models,schemas,service,router}.py` — 26 modules,
  consistent layout.
- `app/shared/` — money primitives, mixins (`TenantMixin`, `PrimaryKeyMixin`,
  `TimestampMixin`), `today()`.
- `app/models_all.py` — single import surface for the ORM registry
  (see technical debt T1).
- `app/core/rbac.py` — 8 roles: `admin management consultant backoffice
  readonly client_admin client_operator client_readonly`; scope-based
  (`domain:action`) permission checks on the server side via dependency
  injection (`role_allows`). Client roles are locked to their company.
- **Multi-tenancy** via `TenantMixin` + tenant FK on all domain tables
  (`6250868682c8` migration). A `PG_RLS_BLUEPRINT.sql` exists in docs but RLS
  is not enforced in the SQLite dev path.
- `app/bootstrap.py` + `launcher.py` — Windows portable launcher: locates
  data dir, writes `.env`, runs migrations, seeds preview, serves the built
  frontend from the same process.
- `app/seed.py` (~800 lines) — base seed incl. fiscal/treasury sandbox
  scenarios; `app/preview_seed.py` (422 lines) — multi-company demo.
- Assistant module: deterministic tools (cash, aging, reconciliation,
  fiscal) exposed to an AI layer; the AI provider is abstracted
  (`docs/AI_ARCHITECTURE.md`).

## 8. Frontend architecture (as found)

- **React 18 + TypeScript + Vite 5**, react-router 6, TanStack Query 5,
  react-hook-form + zod, lucide icons. **No UI framework** (no MUI/Bootstrap/
  Tailwind) — a hand-written design system in `src/design-system/`
  (`tokens.css`, `app.css`) plus `src/components/`.
- `tsc -b && vite build` passes. Bundle: one 565 kB JS chunk (no
  code-splitting) — a warning, not a blocker.
- **No frontend tests exist** (0 `*.test.*` / `*.spec.*` files).
- Auth stored client-side (`src/auth/`), API layer in `src/api/`.

---

## 9. Billing foundation — already provider-agnostic

Contrary to what the mission brief anticipated, the provider-abstraction for
electronic invoicing **already exists on `main`** (`9c10ba9`, "billing
foundation"):

- `BillingProvider(ABC)` with `capabilities() validate_configuration()
  health_check() submit_invoice(..., idempotency_key) get_invoice_status()
  retrieve_notifications() download_xml() download_receipt()
  create_credit_note(..., idempotency_key) verify_webhook()`.
- `registry.py`: `register()`, `adapter_for(provider_key, api_version)`
  (**versioned adapters**), `available_providers()`, `get_active_provider()`.
- `stub.py`: in-memory adapter with idempotency-key tracking.
- `statuses.py`: **three separate state machines** — `InvoiceStatus`
  (15 states incl. `TRANSMISSION_UNKNOWN`, `REQUIRES_RECONCILIATION`,
  `QUEUED` outbox), `SdiStatus`, `PaymentStatus` — plus
  `ProviderHealthStatus`. Comment in code: "NEVER blind-retry".
- `BillingProviderConfig` model per tenant.

What is **missing** for Phase G: real adapters (Aruba / Fatture in Cloud /
TeamSystem / direct SdI), the provider-registry UI with SUPPORTED / IN
DEVELOPMENT / NOT INSTALLED states, `docs/INTEGRATIONS.md` per-provider
verification dates, and webhook duplicate handling tests.

---

## 10. Test status (measured, not reported)

Merged tree `integration/prosperya-v02` @ `c68bbee`:

```
207 passed, 0 failed, 382 warnings   in 541 s (9 min 01 s)
```

| File | Purpose |
|---|---|
| test_auth | login, tokens |
| test_billing | invoice lifecycle, stub provider, idempotency |
| test_companies | CRUD, tenancy |
| test_contribution_and_cost_centers | margins, break-even |
| test_controlling | CCII rules, DSCR, scenarios, alerts |
| test_documents_practices | document/practice lifecycle, blockers, deadline→task |
| test_fiscal | golden VAT cases, idempotency, append-only, F24, exactly-once |
| test_funding | rules engine, programmes, eligibility |
| test_management_and_assistant | management control, assistant tools |
| test_pipeline_and_leads | leads → opportunities → pipeline |
| test_setup_and_settings | first-run wizard, tenant provisioning |
| test_treasury_and_cockpit | open items, reconciliation, cockpit |

Test DB: SQLite (`tests/conftest.py` sets `DATABASE_URL=sqlite:///./test.db`,
`drop_all`/`create_all` per test). Warnings: `httpx`/starlette testclient
deprecation; **JWT HMAC key 30 bytes < 32 recommended** (test fixture secret —
must be checked for the generated production `.env`, see T4).

Preview seed verified separately: `alembic upgrade head` → `seed()` →
`seed_preview()` → both re-run → **69 tables, 9 companies, 3 users,
2 tenants, 26 open items, 13 VAT entries, 4 funding programmes, 4 practices,
3 documents**; second run inserted nothing (idempotent).

The "207 tests" figure from the previous report is therefore accurate — but
it is the count on the **feature tip**, not on `main` (`main` has 4 test
files only).

---

## 11. Build status

| Step | Result |
|---|---|
| `pip install -r requirements-dev.txt` | OK (fastapi 0.141, sqlalchemy 2.1, alembic 1.20) |
| `pytest` | 207/207 |
| `alembic upgrade/downgrade/upgrade` (SQLite) | OK |
| `alembic upgrade` (PostgreSQL) | **not run** — no Postgres on audit machine |
| `npm ci && npm run build` (`tsc -b && vite build`) | OK, 1 chunk-size warning |
| `ruff` | not run yet |
| Windows preview `.exe` | not rebuilt (per mission §29) |

CI: one workflow `.github/workflows/ci.yml` exists (contents to be reviewed
in Phase F).

---

## 12. Technical debt discovered

| # | Item | Severity | Where |
|---|---|---|---|
| T1 | ORM registry is import-order dependent: any code path that opens a session without importing `app.models_all` first crashes with `NoReferencedTableError` (reproduced during audit on `open_items.invoice_id → invoices`). `bootstrap.py` and `seed.py` do it right, but nothing enforces it. | Medium | `app/models_all.py`, `app/db.py` |
| T2 | Test suite takes **9 minutes** for 207 tests (~2.6 s/test). Root cause is `drop_all`/`create_all` of 69 tables per test on SQLite + argon2 hashing per login. Will get worse linearly. | Medium | `tests/conftest.py` |
| T3 | Zero frontend tests. 21 pages, ~0 automated coverage. | High | `frontend/` |
| T4 | JWT secret length warning (30 bytes). Verify the secret generated by `bootstrap._ensure_env` for the preview `.env` is ≥ 32 bytes / high-entropy. | Medium | `app/bootstrap.py`, `app/core/security` |
| T5 | ~~`funding_practices` disjoint from generic `practices`~~ **Withdrawn in Phase E**: the link already existed and was wired in `funding/practices.py` (the audit grepped the wrong file). Gaps that were real — link not exposed by API, no tests, `approved→closed` flipping the generic practice to `cancelled` — fixed. See ADR-023. | — | `funding/practices.py` |
| T6 | Single 565 kB JS bundle, no route-level code splitting. | Low | `frontend/vite.config.ts` |
| T7 | `feat/prosperya-financial-core` HEAD commit is a *fiscal* commit — branch naming drift; harmless but confusing. | Low | git |
| T8 | Local working copy contains ~50 **untracked files from an unrelated project** (BrainBee ST-9000 reverse-engineering: `bbz_disasm.py`, `analysis_output/`, `cab_files/`, `msi_streams/`, `setup_payload.bin`, …). They do not collide with tracked paths and are not ignored. **Must be moved out before any `git add -A`.** | High (process) | repo root |
| T9 | `PG_RLS_BLUEPRINT.sql` documents row-level security but nothing applies it; tenant isolation currently relies solely on application-level filters. | Medium | `docs/`, `app/core` |
| T10 | Starlette `TestClient`+`httpx` deprecation — will break on a future Starlette major. | Low | tests |
| T11 | `.venv` and `node_modules` correctly git-ignored; no lockfile pinning for Python (`>=` ranges) — reproducibility risk. | Low | `requirements*.txt` |

## 13. Integration risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Postgres behaviour unverified.** SQLite passes everything, but Postgres enforces FK/enum/type strictness differently. Migration `downgrade` paths in particular may hide Postgres-only issues. | Run the full migration cycle + test suite against a Postgres container in Phase F before any preview build. |
| R2 | Demo seed hard-codes `demo@prosperya.it / Prosperya-Demo-2026` into the generated `.env` when `PROSPERYA_PREVIEW=1`. Fine for demo; must never leak into a non-preview build. | Guard already exists (`preview` flag); add a test. |
| R3 | Funding practices vs generic practices (T5): cross-module flows "Funding application → practice → documents → deadlines" will need a link table or refactor. | Design decision in Phase E; document in `DECISIONS.md`. |
| R4 | No frontend tests (T3): UX rework in Phase H has no regression net. | Add smoke/E2E tests for the critical flows *before* redesign. |
| R5 | Untracked foreign files in the working tree (T8). | Move to a separate folder before any commit that stages broadly. |
| R6 | `main` is stale; anyone branching from `main` will re-diverge. | After V0.2 stabilises, fast-forward `main` to the integration branch (or PR). |

## 14. Recommended consolidation strategy — and what was already done

**Strategy: adopt `feat/prosperya-document-practice-core` as the base and
merge the single demo commit on top.** Because the feature branches form a
strict chain, no rebasing, cherry-picking or conflict resolution is needed,
and the entire commit history (22 commits, ADRs, changelog entries) is
preserved intact.

Executed during this audit:

1. `git remote add origin …` and `git fetch --all`.
2. `git checkout -b integration/prosperya-v02 origin/feat/prosperya-document-practice-core`
3. `git merge --no-ff origin/demo/giuseppe-preview-v01` → clean → committed
   as `c68bbee`.
4. Verified on `c68bbee`: 207/207 tests, single Alembic head with full
   up/down/up cycle, frontend build, preview seed idempotent.

Nothing was pushed. `main` was not touched. No feature branch was modified.

Next steps (Phases B–F, in order):

1. Move the foreign untracked files out of the repo folder (T8, R5).
2. Postgres migration + test run (R1).
3. Speed up the test fixture (T2) — session-scoped schema with per-test
   transaction rollback — before adding the next ~100 tests.
4. Decide funding-practice ↔ generic-practice relationship (R3) and record
   ADR.
5. Frontend smoke tests for the 5 critical flows (R4).
6. Only then: Phase G (real billing adapters + registry UI) and Phase H (UX).

---

## 15. Phase B–F outcome (2026-09-24)

Branch `integration/prosperya-v02`. `main` untouched. Every item below is
committed with tests.

### Repository
- 51 ST-9000 research roots (212 files, 254 MB) moved to
  `DIAGNOSTIC/research/st9000/` — verified untracked, unreferenced, no
  collisions; targeted `.gitignore` rules added (T8 ✓).
- `.devin/` (agent config) ignored.

### Database
- `docker-compose.yml`: `postgres:16.15-alpine`, env-driven credentials,
  healthcheck, named volume, optional `full` profile; `.env.example`
  PostgreSQL-first.
- **Validated on PostgreSQL 16.15**: empty → head → base → head; seed +
  preview seed idempotent (54 tables, counts identical to SQLite); **full
  suite green on PostgreSQL**.
- Two PostgreSQL-only defects found and fixed (invisible on SQLite):
  1. the SQLite FK `PRAGMA` connect-listener ran on every dialect and left
     psycopg transactions aborted → every new connection failed on its first
     statement; now registered only for SQLite.
  2. `documents.current_version_id` had **no foreign key** on PostgreSQL —
     unnamed `use_alter` FK omitted by the generated migration, inlined by
     SQLite; named in the model + migration `a7c1e3f9b2d4` (idempotent both
     dialects) + `test_schema_parity.py`.
- `tasks.sync_key` exactly-once made a **database guarantee** (partial unique
  index, migration `b3d2f0a1c5e7`, service adopts the winner on conflict).
- Alembic: single head `b3d2f0a1c5e7` (10 revisions).

### Backend
- T1 ✓ root cause: nothing forced the full model registry before mapper
  configuration; `Mapper.before_configured` hook in `app.db` +
  `load_model_registry()`; regression tests in clean subprocesses incl. a
  causality test that removes the hook.
- T2 ✓ **541 s → 136 s (−75 %)** on this laptop; cause was Argon2 at
  recommended cost per login (~0.8 s × hundreds) and a file DB on an
  AV-scanned disk, not schema setup. Fixed with the test-only
  `ARGON2_COST_PROFILE=fast` and in-memory SQLite; isolation unchanged.
- T4 ✓ JWT policy in `Settings` (≥ 32 bytes, no placeholders), production
  refuses to start on violation, generator verified.
- Cross-module fix: generic `DocumentRequirement` create/update/fulfil now
  syncs practice blockers (previously only the funding path did); fulfilment
  audited.
- New suites: `test_rbac_tenancy` (27), `test_exactly_once` (5),
  `test_billing_contract` (23, conformance kit runs on every registered
  adapter), `test_config_security` (11), `test_orm_registry` (5),
  `test_schema_parity` (2), ADR-023 link tests (4), blocker sync (1).
- **207 → 285 backend tests**, all green on SQLite and PostgreSQL.

### Frontend
- T3 ✓ Vitest + Testing Library: 15 component tests (login, operational
  states, API client). Playwright: **5 smoke flows green** against the real
  backend (disposable seeded SQLite via `scripts/e2e_server.py`).
- UI gaps surfaced by the flows (for Phase H): company-detail *Contatti* tab
  is a placeholder; form labels not associated to inputs (a11y + testability);
  practice deadlines and document requirements/validation not creatable from
  the UI; funding practice list shows id prefixes instead of programme title;
  `/practices` and `/documents` routes exist but are absent from the sidebar.

### Architecture decisions
- ADR-023 funding practice ↔ operational practice (link 1:1 + one-way
  deterministic mirror; inheritance rejected).
- ADR-024 RLS deferred with explicit prerequisites.

### CI
Fast gate (ruff, SQLite tests, tsc, Vitest, build) + PostgreSQL job
(migrations round-trip, single-head check, double seed, full suite) + E2E
job with report artefact.

### Remaining technical debt (prioritised)
1. **Postgres-side RLS** — prerequisites in ADR-024 (session `SET LOCAL`,
   runtime role). Medium.
2. **Frontend a11y/testability**: `htmlFor` on labels, list contacts on the
   company detail; blocks deeper component tests. Medium — do at the start of
   Phase H, not after.
3. `sync_deadline_task` race is simulated, not exercised with two real
   PostgreSQL sessions. Low.
4. `httpx`/Starlette TestClient deprecation (T10). Low.
5. Python dependency ranges unpinned (T11) — add a lock (pip-tools/uv) before
   packaging V0.2. Medium.
6. Single 565 kB JS chunk (T6). Low.
7. User/permission changes not uniformly audited (§23). Medium.
8. Dev machine: no Docker; PostgreSQL validated with portable 16.15 binaries
   (`Desktop\_pgportable`, outside the repo). CI is the reproducible path.