# TEAMSYSTEM_BENCHMARK — PROSPERYA CRM

How we use TeamSystem: as the **capability floor and the migration source** — never as a design template. This file defines the analysis framework every TeamSystem-derived feature must pass through, plus worked examples.

> **Status caveat:** the worked analyses in §3 are **hypotheses** based on generic knowledge of TeamSystem-class ERPs. They must be validated against real TeamSystem material (screens, exports, workflows) before Phase 4. Assumption-marked claims carry ⚠.

## 1. Benchmark framework

When a TeamSystem capability is identified as relevant:

1. **Document** it with the analysis template (§2) — one file-section per feature, appended below.
2. **Decide** one of: `adopt` (redesigned for Prosperya), `adapt` (partial), `reject` (out of scope), `defer` (later phase).
3. **Design** the Prosperya version against our data model and UX rules — not against TeamSystem's UI.
4. **Plan migration**: which TeamSystem fields map to which entities, what validation they must pass (`IMPORT_STRATEGY.md`).

Hard rules:
- We do not reproduce TeamSystem UI patterns, menu structures, or terminology where they conflict with `UX_RULES.md` or Prosperya's language (Italian advisory vocabulary, e.g. *pratica*, *bando*, *scadenza*).
- Every migrated concept gets a dedupe/validation strategy — TeamSystem data quality is assumed dirty until proven otherwise.
- Anything TeamSystem does that no Prosperya workflow needs is rejected, even if "standard".

## 2. Analysis template (required)

```
### Feature: <name>
| Field | Content |
|---|---|
| Feature | What TeamSystem calls it / what it does |
| Business purpose | The real job it does for Prosperya (Jobs-to-be-done) |
| Strengths | What TeamSystem does well that we must match or exceed |
| Weaknesses | Known friction: UX, data model, workflow gaps |
| Data quality risk | Expected dirtiness of extracted data (dupes, free text, nulls) |
| Prosperya redesign | How it works in PROSPERYA CRM (entities, screens, rules) |
| Migration | Source tables/exports → target entities; transform + validate notes |
| Acceptance | Testable criteria for "we matched/exceeded the benchmark" |
| Decision | adopt / adapt / reject / defer — owner, date |
```

## 3. Worked analyses (hypotheses — pending real source material)

### Feature: Anagrafica clienti (client registry)

| Field | Content |
|---|---|
| Feature | Central company registry shared across TeamSystem modules (contabilità, fatturazione, CRM-lite) ⚠ |
| Business purpose | Single source of truth for "who is this client" — identity, fiscal data, contacts, status |
| Strengths | Rich fiscal fields (P.IVA, CF, SDI code, ATECO) ⚠; mature dedupe at data-entry ⚠; wide adoption means our field coverage must not regress |
| Weaknesses | Registry optimized for invoicing, not advisory relationships ⚠; ownership/segmentation weak; contact persons secondary; no soft-delete/history visibility ⚠ |
| Data quality risk | **High**: duplicate records per P.IVA variant, inconsistent ATECO, free-text cities, dead records never archived |
| Prosperya redesign | `companies` + `company_contacts` + `contacts`; normalized unique `vat_number`; `company_type`/`status` lifecycle; `owner_id`; soft-delete; timeline on every record |
| Migration | TeamSystem anagrafica export → staging → normalize VAT/CF → dedupe on (vat_number, tax_code, name-fuzzy) → preview → confirm. Unmatched/ambiguous rows go to error queue, never auto-merge |
| Acceptance | Every migrated client resolvable to one `companies` row; zero unreviewed duplicates; fiscal fields survive round-trip; record page shows full identity in header per `UX_RULES.md` |
| Decision | **adopt** (redesigned) — foundation of Phase 1 |

### Feature: Scadenzario (deadline register)

| Field | Content |
|---|---|
| Feature | Deadline/installment register driven mainly by accounting events (invoices, payments) ⚠ |
| Business purpose | Nothing with a date gets missed — filings, bandi cutoffs, renewals, internal tasks |
| Strengths | Reliable single chronological list; mature reminder concept ⚠ |
| Weaknesses | Deadline scope limited to accounting events ⚠; weak ownership; no severity model; no linkage to advisory entities like bandi or practices ⚠ |
| Data quality risk | **Medium**: dates reliable, titles terse/accounting-coded, linkage to client may be implicit |
| Prosperya redesign | `deadlines` as a first-class cross-entity register synced from tasks, bandi (`closes_at`), applications, opportunities, documents, plus manual entries; severity levels; owner; per-record alert strips (`UX_RULES.md` §6) |
| Migration | Scadenzario export → map rows to `deadlines` with `entity_type='manual'` + source ref where the originating entity can't be resolved; title normalization pass in staging |
| Acceptance | Every TeamSystem deadline present in PROSPERYA register post-migration; deadlines board shows owner+severity; overdue visibility per `UX_RULES.md`; no deadline exists only in a spreadsheet |
| Decision | **adapt** — same job, wider scope, better UX |

### Feature: Gestione documentale (document management)

| Field | Content |
|---|---|
| Feature | Document attachment/archiving on client records and invoices ⚠ |
| Business purpose | Contracts, deliverables, fiscal docs findable on the record they belong to |
| Strengths | Documents attached to the right master record ⚠; category conventions mature |
| Weaknesses | Storage tied to TeamSystem install; metadata shallow ⚠; no cross-entity search; versioning weak; extraction path unclear ⚠ |
| Data quality risk | **High**: binary extraction feasibility unknown (Q1); filenames unstructured; categories free-text |
| Prosperya redesign | `documents` metadata Phase 1; storage backend Phase 2 (local → S3-compatible); category enum; `entity_type/entity_id` linking; supersede workflow; upload validation (`SECURITY.md` §5) |
| Migration | Two-phase: (a) migrate document *metadata* + file inventory during Phase 4; (b) bulk binary extraction depends on TeamSystem export access — unresolved until Q1 answered. Fallback: files stay in TeamSystem read-only archive with links |
| Acceptance | Every document findable from its owning record; metadata fields populated; download works post-Phase-2; no orphaned files unaccounted in audit |
| Decision | **adapt** — pending Q1 (export access) for the binary path |

## 4. Pending real material

To convert hypotheses into decisions we need: TeamSystem screen walkthroughs, a real export sample (anagrafica, scadenzario, document list), module list actually licensed by Prosperya, and user interviews on daily TeamSystem workflows. Target: before Phase 4 kickoff.
