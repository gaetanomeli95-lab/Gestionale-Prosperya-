# MASTER_SPEC — PROSPERYA CRM

Canonical product specification. Where any other document disagrees with this file, this file wins (update this file deliberately, not accidentally).

## 1. Vision

A single internal platform where Prosperya S.r.l. runs its advisory business: who the clients are, what we are selling them, which engagements are open, which public funding programmes (*bandi*) they are eligible for, what deadlines are coming, and where every document and decision lives — with a complete audit trail.

It replaces TeamSystem, which the firm outgrew: too generic, fragmented data entry, weak pipeline support, no funding-programme logic. TeamSystem defines the *capability floor* (what we must not lose), not the design.

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

## 5. Non-negotiable constraints

- PostgreSQL 16 is the production target; SQLite is dev/test fallback only (no Docker on dev machine). All migrations must run on both; no SQLite-only or PG-only features in core paths without a documented guard.
- SQLAlchemy 2.x **synchronous** (ADR-003). Do not introduce async ORM.
- Access-token-only auth is acceptable through Phase 0–4; the refresh-token httpOnly cookie design is documented in `SECURITY.md` and lands in Phase 5 (ADR-004).
- Italian UI copy is the default; entity enums are stored in English codes, localized in the frontend.
- GDPR applies (EU/Italy): personal data minimization, auditability, retention, and export duties are documented in `SECURITY.md` §8.

## 6. Reading order for new contributors

1. This file → 2. `DISCOVERY.md` → 3. `ARCHITECTURE.md` → 4. `DATA_MODEL.md` → 5. `BRAND_SYSTEM.md` + `UX_RULES.md` → 6. domain docs as needed (`SECURITY`, `IMPORT_STRATEGY`, `AI_ARCHITECTURE`) → 7. `DECISIONS.md` before changing anything structural.
