# DISCOVERY — PROSPERYA CRM

Business analysis underpinning the spec (spec §51). Status: initial discovery complete; open questions tracked in §9.

## 1. Business understanding

**Prosperya S.r.l.** (P.IVA 07415020820), Altavilla Milicia (Palermo), is a business advisory firm. Its service lines:

| Service line | Notes for CRM design |
|---|---|
| Startup advisory & NewCo creation | Drives lead → opportunity → engagement flow |
| Finanza agevolata (grants / subsidised funding) | Requires funding-programme (bandi) registry, eligibility checks, application tracking, deadline discipline |
| Governance & control | Recurring engagements; ties to tasks/deadlines |
| Growth Factors assessments | Proprietary assessment instrument → dedicated module (Phase 3) |
| Business planning | Document-heavy deliverables |
| Internationalisation (Italy / EU / Mediterranean) | Multi-country data on companies; tags/segmentation |
| Debt restructuring | Sensitive data; strict access control |
| Brands & patents | Deadline-heavy (renewals) |
| R&D advisory | Links to funding programmes |
| Real estate management | Separate company/contact segment |

The firm runs on **TeamSystem** today. Pain points reported: fragmented client data, no real pipeline, deadlines managed in spreadsheets alongside the tool, no concept of bandi eligibility, and heavy re-keying of known data. TeamSystem defines the capability floor; its UX and data model are explicitly not being cloned (see `TEAMSYSTEM_BENCHMARK.md`).

## 2. Objectives

1. One authoritative client registry (companies + contacts) with dedupe and auditability.
2. A visible commercial pipeline (lead → opportunity → engagement) with stage discipline.
3. Deadline safety: every obligation (bandi, filings, renewals, tasks) lands in one deadline register with warnings.
4. Funding workflow support: bandi registry → deterministic eligibility → application tracking.
5. Zero data loss on migration: staged, previewed, auditable import from TeamSystem.
6. A UI staff can work in all day: dense, fast, keyboard-friendly, unmistakably Prosperya.

## 3. User types

| Role | Who | Primary needs |
|---|---|---|
| `admin` | Partner / IT owner | User management, configuration, imports, everything |
| `management` | Partners, practice leads | Full portfolio view, dashboards, pipeline oversight, approvals |
| `consultant` | Advisors delivering work | Their clients, opportunities, tasks, deadlines, documents |
| `backoffice` | Admin staff | Registry hygiene, documents, deadlines, application paperwork, executing imports |
| `readonly` | External collaborators / auditors | Read access, no mutation |

Full capability matrix: `SECURITY.md` §3.

## 4. Core workflows

1. **New client intake** — lead created (source, service interest) → qualified → converted to company + contact + opportunity. Rule: the system must pre-fill everything already known (`UX_RULES.md` "never retype").
2. **Opportunity → engagement** — opportunity moves through `pipeline_stages`; on *won*, a practice/engagement (Phase 2) is created carrying company, service line, owner.
3. **Bando match** — funding programme published/updated → eligibility engine (Phase 3) evaluates company attributes vs. programme criteria → candidate applications proposed → `funding_application` opened → tracked to submission and outcome. Every step deadline-driven.
4. **Deadline operation** — anything with a date (task due, bando close, document renewal, application milestone) surfaces in the deadlines register and calendar; warnings engine flags risk.
5. **Document lifecycle** — upload → metadata + classification → link to entities → review → archive. Storage backend arrives Phase 2; metadata schema exists Phase 1.
6. **Migration** — TeamSystem extract → staged import → mapping → dedupe → preview → confirm (`IMPORT_STRATEGY.md`).

## 5. Bounded modules

See `MASTER_SPEC.md` §3 for the canonical list and phase assignment. Boundary rule: modules communicate through their `service.py` API or via IDs/foreign keys — never by importing another module's SQLAlchemy internals in a query. Cross-module reads go through the owning service.

## 6. Preliminary entity map

```
users ──┬─< tasks (assignee)          pipeline_stages ─< opportunities >─ companies
        ├─< activity_events (actor)         ▲                  │
        └─< audit_log (actor)               │                  │
                                            │                  │
companies ──< company_contacts >── contacts │                  │
   │  └─< leads                            │                  │
   ├─< opportunities                       │                  │
   ├─< notes (polymorphic: entity_type/id) │                  │
   ├─< documents ──────────────────────────┘                  │
   ├─< funding_applications >── funding_programmes            │
   └─< deadlines (polymorphic)                                │
                                                              │
service_lines ─< opportunities, practices, funding_apps ──────┘
```

Polymorphic links (`notes`, `deadlines`, `documents`, `activity_events`) use `(entity_type, entity_id)` pairs, not real FKs — accepted trade-off, documented in `DATA_MODEL.md` and ADR context.

## 7. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TeamSystem extract quality unknown (inconsistent VAT numbers, missing emails, free-text categories) | High | High | Staged import with validation report; no direct writes (P4) |
| Scope creep vs. TeamSystem feature surface | Medium | High | Benchmark template forces per-feature decision; phases gate scope |
| SQLite/PG divergence | Medium | Medium | CI runs tests on both; PG-only features need documented guard (ADR-002) |
| Deadline misses = business damage | Low | High | Deadlines are first-class entities Phase 1, not UI afterthought; warnings engine Phase 3 |
| AI pressure before deterministic core exists | Medium | Medium | P1 + P5; AI flag defaults off |
| Single-dev bus factor during greenfield | — | Medium | This documentation set is the mitigation |

## 8. Assumptions

- Single-tenant: one Prosperya organization; no multi-tenancy requirement.
- Staff count is small (< 50 users); PostgreSQL sizing accordingly.
- UI language Italian; enum codes in English.
- No public-facing surface; auth is staff-only.
- Document storage: local filesystem dev → object storage (S3-compatible) in deployment; metadata in DB either way.
- Email integration (sending) is out of scope for phases 0–4; notes record communications manually.

## 9. Unresolved questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| Q1 | Actual TeamSystem export format(s) available (CSV, XLSX, DB dump, API?) | Admin | Phase 4 planning |
| Q2 | Retention periods for personal data & documents per GDPR/contract terms | Legal review | Phase 5 |
| Q3 | Which Growth Factors assessment version/questionnaire is canonical | Management | Phase 3 |
| Q4 | Required fields per service line (e.g. is VAT mandatory for foreign companies?) | Management | Phase 1 hardening |
| Q5 | Numbering scheme for practices/applications (sequential? per-year?) | Backoffice | Phase 2 |
| Q6 | Hosting target: on-prem, EU cloud, managed PG? | Admin | Phase 5 |

## 10. Tech choices (summary — rationale in `DECISIONS.md`)

Python 3.12 · FastAPI · SQLAlchemy 2.x sync · Pydantic v2 · Alembic · PostgreSQL 16 (psycopg) with SQLite dev fallback · PyJWT + argon2id (pwdlib) · modular monolith · Vite + React 18 + TS · TanStack Query v5 · react-hook-form + zod · custom token-driven design system · Playwright E2E.

## 11. Roadmap

Phase table in `MASTER_SPEC.md` §4 is canonical. Discovery confirms phase order: registry and deadlines must precede eligibility and migration; AI strictly last.
