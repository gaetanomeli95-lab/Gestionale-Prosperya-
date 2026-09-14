# MASTER_SPEC — PROSPERYA PLATFORM (codename)

Canonical product specification. Where any other document disagrees with this file, this file wins (update this file deliberately, not accidentally).

## 1. Vision

A **multi-tenant SaaS platform** that a business consultancy firm (codename: "Prosperya") sells to and operates for client companies (mostly Italian S.r.l.). Per tenant: CRM, sales pipeline, invoicing/e-invoicing, management control (controllo di gestione), fiscal planning (IVA, F24 generation), funding-programme matching (finanza agevolata), banking reconciliation (PSD2), HR/payroll support, crisis-of-enterprise indicators (CCII), and AI-assisted workflows.

"Prosperya" is a codename only — the product name, logo, and theme are **configurable per deployment** (white-label ready). Do not hardcode it.

It replaces TeamSystem-class tools, which the firm outgrew: too generic, fragmented data entry, weak pipeline support, no funding-programme logic. TeamSystem defines the *capability floor* (what we must not lose), not the design.

### Product model (decided 2026-09-14)

- **Tenant = client company.** All business data carries `tenant_id`; isolation is enforced in the data layer.
- **Operator roles** (platform-owner staff: admin/consultant/backoffice) can switch the active tenant context.
- **Client roles** (azienda admin/operator/readonly) are locked to their own tenant.
- The consultancy manages many client tenants from one deployment — "consulente che gestisce più Srl", not a per-firm internal CRM.

## 2. Product principles

| # | Principle | Consequence |
|---|---|---|
| P1 | **Deterministic core first** | Eligibility, warnings, deadlines, and dashboards are rule-based code and queries before any AI. AI (Phase 6) is additive and feature-flagged. |
| P2 | **TeamSystem = benchmark, not blueprint** | We match or exceed its capabilities where they matter; we do not clone its UI, data model, or workflows. Every imported concept passes through `TEAMSYSTEM_BENCHMARK.md`'s analysis template. |
| P3 | **Prosperya brand is mandatory** | The CRM uses the token system in `BRAND_SYSTEM.md` (petrol/champagne/ivory, Playfair Display titles, DM Sans body). No generic UI kit look. |
| P4 | **No blind legacy import** | TeamSystem data enters only through the staged, validated, previewed pipeline in `IMPORT_STRATEGY.md`. Nothing is written directly to core tables. |
| P5 | **Human-in-the-loop AI, never authoritative** | AI may suggest, extract, and draft. It never writes to core entities without explicit user confirmation, and every suggestion carries provenance. |
| P6 | **Density-first professional UI** | This is an all-day tool for staff. Information density, keyboard speed, and deadline visibility outrank decoration. See `UX_RULES.md`. |
| P7 | **Soft-delete + optimistic concurrency** | Core entities use `deleted_at`; `companies`, `contacts`, `leads`, `opportunities` carry a `version` column. See `DATA_MODEL.md`. |
| P8 | **Two trails, kept separate** | `activity_events` = user-facing timeline ("what happened on this record"). `audit_log` = security/compliance trail ("who did what, when, from where"). Never conflated (ADR-007). |
| P9 | **Trust over the appearance of precision** | Every financial figure is bound to a company, a currency, a period, a formula version and traceable sources. Missing data is `null`, never `0`. The presence of rows never certifies completeness. "Risultato gestionale disponibile" is not EBITDA, utile civilistico or cash (ADR-013). |
| P10 | **Financial history is append-only** | Consuntivi and budget rows are never updated or deleted; corrections are new versioned rows with provenance. Enforced at ORM level today, at DB-trigger level on PostgreSQL (ADR-014). |
| P12 | **Una sola catena finanziaria canonica** | `documento → open_item → bank_transaction → reconciliation_allocation → cassa/previsione/warning`. Residuo, incassato e stato sono *derivati* dalle allocazioni, non memorizzati: ogni numero è ricostruibile dalle sue fonti. Vietati numeri finanziari duplicati per modulo (ADR-016). |
| P13 | **Determinismo prima dell'AI, approvazione umana sugli atti** | Abbinamenti bancari, cassa, previsioni e warning sono codice puro riproducibile; l'AI legge e spiega risultati verificati. Nessun abbinamento ambiguo viene applicato dal sistema; ogni chiusura di partita porta attore, metodo, evidenze e versione del motore (ADR-017). |
| P11 | **AI answers are typed and evidence-bound** | Every assistant output item is `FACT` / `CALCULATION` / `ASSUMPTION` / `SUGGESTION`, carries the tools used, source ids, formula version and explicit limitations. Tools are allow-listed; the provider never runs SQL or does arithmetic (ADR-015). |

## 3. Module list

| Module | Domain | Phase |
|---|---|---|
| `users` | Users, roles, RBAC | 0 |
| `companies` | Client/prospect registry (anagrafica) | 1 |
| `contacts` | People, linked to companies via `company_contacts` | 1 |
| `leads` | Pre-qualification prospects | 1 |
| `opportunities` | Sales pipeline on `pipeline_stages` | 1 |
| `tasks` | Work items with deadlines | 1 |
| `notes` | Notes & communication timeline entries | 1 |
| `activity` | `activity_events` user-facing timeline | 1 |
| `audit` | `audit_log` security trail | 0 |
| `service_lines` | Prosperya service catalogue (ref data) | 1 |
| `documents` | Document metadata (storage in Phase 2) | 1 |
| `funding` | `funding_programmes` (bandi) + `funding_applications` | 1 schema / 2 features |
| `deadlines` | Cross-entity deadline register | 1 |
| `practices` | Engagements / pratiche delivered to clients | 2 |
| `calendar` | Calendar views over tasks/deadlines | 2 |
| `search` | Global search, saved views | 2–3 |
| `dashboards` | KPI dashboards | 3 |
| `eligibility` | Deterministic eligibility engine vs. bandi criteria | 3 |
| `assessments` | Growth Factors assessments | 3 |
| `warnings` | Warnings engine (staleness, missing data, deadline risk) | 3 |
| `imports` | CSV/XLSX/TeamSystem staged import | 4 |
| `ai` | Feature-flagged AI assistance | 6 |
| `tenancy` | `tenants` (client companies), tenant context, white-label branding | 0 |
| `management` | Controllo di gestione: consuntivi append-only, import CSV idempotente, budget versionati, overview con qualità/trace/alert, hub multi-azienda (ported from prototype v0, 2026-09-14) | 1 ✅ |
| `assistant` | AI CFO deterministico: provider protocol, tool allow-list, item tipizzati, scenario engine Decimal (ported from prototype v0) | 1 ✅ (mock) |
| `treasury` | Scadenzario (crediti/debiti), conti e movimenti bancari via `BankingProvider` (AIS, sandbox), riconciliazione deterministica L1/L2 con approvazione umana, posizione e previsione di cassa 30/60/90, warning tracciati | 7 ✅ (banca SANDBOX) |
| `cockpit` | Control hub multi-azienda con action center prioritizzato + CFO cockpit per azienda; nessuna tabella propria, compone `management`/`treasury`/`opportunities` | 7 ✅ |
| `controlling` | Centri di costo avanzati, break-even, DSCR/CCII crisis indices (extends `management`) | 7 |
| `fiscal` | Liquidazione IVA, tax simulation (IRES/IRAP), F24 XML export | 7 |
| ~~`banking`~~ | Assorbito da `treasury` (2026-09-14): conti, movimenti e riconciliazione vivono nella stessa catena del dato finanziario. Resta da aggiungere un adapter PSD2 reale accanto a `sandbox-openbanking/v1` | 7 (adapter reale aperto) |
| `hr` | Employees, presenze, payroll simulation, contributi (calc tool, human-validated) | 8 |
| `agents` | Orchestrated AI agents over deterministic calculators | 8 |

## 3.1 Legal/compliance constraints on ERP features

- **Banking**: account information only (AIS). The platform reads balances and movements; **payment initiation is out of scope** — moving money is an irreversible, legally sensitive act (ADR-017).
- **F24**: the platform *generates* F24 XML (Entratel/CBI tracciato). Submission stays with the client/intermediario — we never transmit on their behalf.
- **Payroll (LUL)**: calculation is a tool; legal responsibility stays with the client company's authorized professional (Legge 12/1979). Product surfaces must carry a human-validation disclaimer.
- **Crisis indicators (CCII)**: deterministic CNDCEC-style calculations (DSCR 6-month, sectoral indices); output is advisory, clearly labelled.
- **AI**: never computes taxes/amounts in natural language — deterministic Python calculators only; AI interprets and drafts (P1, P5).

## 3.2 Schermata primaria

La vista d'ingresso del consulente è il **control hub** (`/hub`): una riga per
azienda ordinata per `attention_score` più un action center che risponde a
«quale azienda guardo per prima, e perché». Ogni voce è un segnale
deterministico con formula, versione ed evidenze; nessun consolidato tra
aziende. Da lì si apre il **CFO cockpit** della singola azienda
(`/cockpit/:id`), che unisce anagrafica, economia gestionale, cassa e pipeline
commerciale (ADR-018). La dashboard CRM resta come vista operativa, non come
centro di controllo.

## 4. Phase roadmap

| Phase | Name | Scope | Exit gate |
|---|---|---|---|
| **0** | Foundation | Repo, CI, FastAPI skeleton, auth (JWT + RBAC), users, audit_log, Alembic baseline, design tokens + app shell, health checks | Login works; roles enforced; `GET /health` green; tokens render the branded shell |
| **1** | Commercial core | companies, contacts + link, leads, pipeline_stages, opportunities, tasks, notes, activity_events, service_lines, documents (metadata), funding schema, deadlines; global search v1 | Full CRUD on core entities; record pages per `UX_RULES.md`; soft-delete + version conflicts handled |
| **2** | Operations | practices/engagements, calendar, document storage backend, deadlines UI, saved views, dashboards v1 | Staff can run a client engagement end-to-end |
| **3** | Intelligence | deterministic eligibility engine, Growth Factors assessments, warnings engine, dashboards v2, saved views everywhere | Eligibility output reproducible from rules alone |
| **4** | Migration | import system (CSV/XLSX, TeamSystem extracts), dedupe, provenance, preview+confirm | A real TeamSystem extract imports clean with audit trail |
| **5** | Hardening & rollout | refresh-cookie hardening (ADR-004 follow-up), rate limits, security review, E2E suite green, deployment + backups, performance pass | Production deploy with restore-tested backups |
| **6** | AI assistance | provider abstraction + feature flags, document-extraction review flow, suggestion UX with provenance | AI features ship behind `AI_ENABLED` flag, off by default |
| **7** | Advisory core | `controlling` (CdC, budget, break-even, DSCR/CCII), `fiscal` (IVA ledger, F24 XML, IRES/IRAP sim), `banking` (PSD2 provider abstraction + 3-level reconciliation) | Deterministic numbers reproducible from data; F24 validates against tracciato |
| **8** | Extended ops + agents | `hr` (employees, payroll sim), `agents` (orchestration over calculators), realtime updates | Payroll outputs require human confirmation; agents never write core data unreviewed |

## 5. Non-negotiable constraints

- **Every business entity is tenant-scoped.** `tenant_id` is a non-nullable FK on all tenant-owned tables; every list/get/write path filters by the active tenant. Cross-tenant access is impossible by construction (ADR-011). Postgres RLS may be added later as a second line of defence.
- Product name/branding configurable via `APP_NAME` + theme tokens — "Prosperya" is the default theme, not the product name (ADR-012).
- PostgreSQL 16 is the production target; SQLite is dev/test fallback only (no Docker on dev machine). All migrations must run on both; no SQLite-only or PG-only features in core paths without a documented guard.
- SQLAlchemy 2.x **synchronous** (ADR-003). Do not introduce async ORM.
- Access-token-only auth is acceptable through Phase 0–4; the refresh-token httpOnly cookie design is documented in `SECURITY.md` and lands in Phase 5 (ADR-004).
- Italian UI copy is the default; entity enums are stored in English codes, localized in the frontend.
- **Money**: Python `Decimal` + `NUMERIC(20,2)`; JSON monetary values are **strings**. Frontend converts to `Number` only for display/chart coordinates, never for business calculations. V1 supports EUR only — no implicit FX.
- **Login throttle**: per-IP and per-email sliding window (`LOGIN_MAX_ATTEMPTS`, default 30/5 min); unknown-email logins verify against a dummy Argon2 hash to keep timing constant.
- GDPR applies (EU/Italy): personal data minimization, auditability, retention, and export duties are documented in `SECURITY.md` §8.

## 6. Reading order for new contributors

1. This file → 2. `DISCOVERY.md` → 3. `ARCHITECTURE.md` → 4. `DATA_MODEL.md` → 5. `BRAND_SYSTEM.md` + `UX_RULES.md` → 6. domain docs as needed (`SECURITY`, `IMPORT_STRATEGY`, `AI_ARCHITECTURE`) → 7. `DECISIONS.md` before changing anything structural.
