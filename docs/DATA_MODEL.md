# DATA_MODEL — PROSPERYA CRM

Entity-by-entity reference for the Phase 0/1 schema. Entities marked **〔designed, not yet implemented〕** are Phase 2+; their shape is agreed here but no migration exists yet.

## 0. Global conventions

| Convention | Value |
|---|---|
| Primary key | `id UUID` (uuid4, app-generated) on every table |
| Timestamps | `created_at`, `updated_at` (timestamptz, server defaults) on every table |
| Soft delete | `deleted_at timestamptz NULL` on core entities; `NULL` = live. Queries exclude deleted rows via the shared `not_deleted()` clause |
| Optimistic concurrency | `version INT NOT NULL DEFAULT 1` on `companies`, `contacts`, `leads`, `opportunities`; incremented on every update; client must send current version |
| Polymorphic links | `entity_type VARCHAR + entity_id UUID` (no real FK) — used by `notes`, `documents`, `deadlines`, `activity_events`. Accepted trade-off for a single timeline pattern; integrity enforced in the service layer |
| Enums | Stored as `VARCHAR` codes (English), validated in Pydantic, localized in frontend |
| Actor tracking | `created_by`, `updated_by → users.id` where business-relevant |

---

## Phase 0/1 — implemented

### `users`

Staff accounts. **Key fields:** `email` (citext, unique, not soft-deleted — accounts are deactivated not deleted), `full_name`, `password_hash` (argon2id via pwdlib), `role` ∈ {`admin`,`management`,`consultant`,`backoffice`,`readonly`}, `is_active BOOL`, `last_login_at`. **Indexes:** `UNIQUE(email)`. **Invariants:** at least one active admin must exist (service-layer check on deactivate/role-change); `password_hash` never leaves the service layer.

### `companies`

The client/prospect registry (anagrafica). **Key fields:** `name`, `legal_name`, `vat_number` (normalized: uppercased, spaces stripped, `IT` prefix preserved), `tax_code` (codice fiscale), `company_type` ∈ {`client`,`prospect`,`partner`,`supplier`}, `status` ∈ {`active`,`inactive`,`archived`}, `sector`, `ateco_code`, `country`, `region`, `city`, `address`, `website`, `phone`, `email`, `employee_band`, `revenue_band`, `owner_id → users` (relationship owner), `source` (e.g. `manual`,`import:teamsystem`), `custom_fields JSONB`. **Indexes:** `UNIQUE(vat_number)` on normalized value — partial unique `WHERE deleted_at IS NULL AND vat_number IS NOT NULL`; `(company_type, status)`; `(owner_id)`; trigram index on `name` (PG; skipped on SQLite). **Soft delete + version:** yes/yes. **Invariants:** `vat_number` unique among live rows — conflicts raise `DUPLICATE_VAT_NUMBER`; foreign companies may lack VAT → uniqueness applies only when present (pending Q4).

### `contacts`

People. **Key fields:** `first_name`, `last_name`, `email`, `phone`, `mobile`, `role_title`, `is_primary` (per company, via link), `owner_id → users`, `notes_free`, `deleted_at`, `version`. **Indexes:** `(last_name, first_name)`, `(email)`. **Invariants:** a contact exists independently of companies (consultants, referents); linkage is via `company_contacts`.

### `company_contacts`

Link table, many-to-many with attributes. **Fields:** `company_id → companies`, `contact_id → contacts`, `relationship` ∈ {`legal_rep`,`decision_maker`,`referent`,`administrative`,`other`}, `is_primary BOOL`, `valid_from`, `valid_to`. **Indexes:** `UNIQUE(company_id, contact_id, relationship)`, `(contact_id)`. **Invariants:** max one `is_primary` per company (enforced in service; partial unique index on PG).

### `leads`

Pre-qualification prospects. **Key fields:** `company_name` (free text — may not be a `companies` row yet), `contact_name`, `email`, `phone`, `source` ∈ {`referral`,`website`,`event`,`cold`,`import`,`other`}, `service_line_id → service_lines`, `status` ∈ {`new`,`contacted`,`qualified`,`converted`,`lost`}, `estimated_value NUMERIC`, `owner_id → users`, `qualified_at`, `converted_company_id → companies NULL`, `converted_at`, `deleted_at`, `version`. **Indexes:** `(status)`, `(owner_id)`, `(created_at)`. **Invariants:** `status='converted'` requires `converted_company_id`; conversion creates/links company + contact + optional opportunity in one transaction and writes an `activity_events` entry.

### `pipeline_stages`

Ordered pipeline definition (seeded, admin-editable). **Fields:** `name`, `position INT`, `is_won BOOL`, `is_lost BOOL`, `probability INT` (default win %), `is_active`. **Indexes:** `UNIQUE(position)` among active. **Invariants:** exactly the stages drive board order; `is_won`/`is_lost` are terminal.

### `opportunities`

Deals in the pipeline. **Key fields:** `title`, `company_id → companies`, `contact_id → contacts NULL`, `service_line_id → service_lines`, `stage_id → pipeline_stages`, `value NUMERIC`, `probability INT` (defaults from stage, overridable), `expected_close_date`, `status` ∈ {`open`,`won`,`lost`}, `lost_reason`, `owner_id → users`, `closed_at`, `deleted_at`, `version`. **Indexes:** `(stage_id)`, `(company_id)`, `(owner_id, status)`, `(expected_close_date)`. **Invariants:** `status` derives from stage terminus — service layer keeps them consistent; moving to a won/lost stage sets `closed_at` and writes activity event.

### `tasks`

Work items. **Key fields:** `title`, `description`, `entity_type`/`entity_id` (optional polymorphic anchor), `assignee_id → users`, `created_by → users`, `priority` ∈ {`low`,`medium`,`high`,`urgent`}, `status` ∈ {`open`,`in_progress`,`done`,`cancelled`}, `due_at`, `completed_at`. **Indexes:** `(assignee_id, status)`, `(due_at) WHERE status IN ('open','in_progress')`. **Invariants:** `due_at` drives the deadlines register (a `deadlines` row is synced by the service layer — deadline is the read model, task is the work item).

### `notes`

Notes & communication log entries on any record. **Fields:** `entity_type` ∈ {`company`,`contact`,`lead`,`opportunity`,`funding_application`,`practice`,`task`}, `entity_id`, `kind` ∈ {`note`,`call`,`email`,`meeting`,`whatsapp`,`other`}, `body`, `occurred_at`, `author_id → users`, `pinned BOOL`, `deleted_at`. **Indexes:** `(entity_type, entity_id, occurred_at DESC)`. **Invariants:** notes feed the record timeline together with `activity_events` (timeline = union, rendered in `occurred_at` order).

### `activity_events`

User-facing record timeline ("what happened here"). **Fields:** `entity_type`, `entity_id`, `event_type` (e.g. `created`,`stage_changed`,`field_updated`,`note_added`,`converted`,`imported`), `actor_id → users NULL` (NULL = system/import), `summary VARCHAR` (rendered as-is), `data JSONB` (diff payload: `{field: [old,new]}`), `occurred_at`. **Indexes:** `(entity_type, entity_id, occurred_at DESC)`, `(actor_id)`. **Invariants:** append-only — never updated or deleted; written by services, not routers; distinct from `audit_log` (ADR-007).

### `audit_log`

Security/compliance trail. **Fields:** `actor_id → users NULL`, `action` (`auth.login`,`auth.login_failed`,`create`,`update`,`delete`,`restore`,`export`,`import.confirm`,`permission.denied`, …), `entity_type`, `entity_id NULL`, `ip INET`, `user_agent`, `request_id`, `metadata JSONB`, `occurred_at`. **Indexes:** `(actor_id, occurred_at)`, `(entity_type, entity_id)`, `(action, occurred_at)`. **Invariants:** append-only, no FK enforcement on `entity_id` (target may later be hard-deleted), retention per `SECURITY.md` §8.

### `service_lines`

Prosperya service catalogue (ref data, seeded). **Fields:** `code` unique (`startup`,`finanza_agevolata`,`governance`,`growth_factors`,`business_plan`,`internationalization`,`debt_restructuring`,`brands_patents`,`rd`,`real_estate`,`newco`,`other`), `name`, `description`, `is_active`, `position`. **Invariants:** referenced by leads, opportunities, practices, funding_applications; deactivation instead of deletion preserves history.

### `documents`

Document **metadata only** (binary storage lands Phase 2 — `storage_key` reserved). **Fields:** `entity_type`, `entity_id`, `filename`, `mime_type`, `size_bytes`, `storage_key VARCHAR NULL`, `category` ∈ {`contract`,`deliverable`,`identity`,`fiscal`,`bando`,`correspondence`,`other`}, `status` ∈ {`draft`,`active`,`superseded`,`archived`}, `uploaded_by → users`, `uploaded_at`, `deleted_at`. **Indexes:** `(entity_type, entity_id)`, `(category)`. **Invariants:** upload validation rules in `SECURITY.md` §5; download/stream endpoints arrive with the storage backend.

### `funding_programmes`

Bandi registry. **Fields:** `title`, `code`, `issuer` (ente erogatore), `level` ∈ {`eu`,`national`,`regional`,`local`,`private`}, `description`, `funding_type` ∈ {`grant`,`subsidised_loan`,`tax_credit`,`guarantee`,`mixed`}, `max_amount NUMERIC`, `funding_rate NUMERIC` (% covered), `opens_at`, `closes_at`, `eligibility_criteria JSONB` (structured rules for the Phase 3 engine), `requirements TEXT`, `url`, `status` ∈ {`draft`,`published`,`open`,`closed`,`archived`}, `deleted_at`. **Indexes:** `(status, closes_at)`, `(level)`. **Invariants:** `closes_at` feeds `deadlines`; `eligibility_criteria` schema is versioned (`criteria_version` field) so rule changes don't retro-change old evaluations.

### `funding_applications`

A company's application to a programme (domanda). **Fields:** `programme_id → funding_programmes`, `company_id → companies`, `service_line_id → service_lines NULL`, `practice_id NULL` (Phase 2 link), `status` ∈ {`draft`,`preparing`,`submitted`,`under_review`,`approved`,`rejected`,`withdrawn`,`funded`}, `requested_amount NUMERIC`, `approved_amount NUMERIC NULL`, `owner_id → users`, `submitted_at`, `outcome_at`, `deleted_at`. **Indexes:** `(programme_id, status)`, `(company_id)`, `(owner_id, status)`. **Invariants:** status transitions validated in service (e.g. `submitted` requires `submitted_at`); every transition → `activity_events` + relevant `deadlines` (submission cutoff).

### `deadlines`

Cross-entity deadline register — the single "what's due" surface. **Fields:** `entity_type` ∈ {`task`,`funding_programme`,`funding_application`,`opportunity`,`practice`,`document`,`manual`}, `entity_id NULL` (NULL for manual), `title`, `due_at`, `severity` ∈ {`info`,`normal`,`important`,`critical`}, `status` ∈ {`open`,`done`,`dismissed`}, `owner_id → users NULL`, `notes`, `deleted_at`. **Indexes:** `(due_at) WHERE status='open'` — the hot index for the deadlines board; `(entity_type, entity_id)`; `(owner_id, status)`. **Invariants:** entity-sourced deadlines are synced by owning services (create/update/complete mirrors source state); manual deadlines are free-standing.

---

## Phase 2+ — 〔designed, not yet implemented〕

### `practices` *(Phase 2)*
Delivered engagements (pratiche). `code` (sequential per year — pending Q5), `company_id`, `service_line_id`, `opportunity_id NULL` (origin), `status` ∈ {`active`,`suspended`,`closed`,`cancelled`}, `owner_id`, `opened_at`, `closed_at`, `deleted_at`, `version`.

### `growth_factor_assessments` *(Phase 3)*
Prosperya Growth Factors instrument. `company_id`, `assessed_by → users`, `assessed_at`, `questionnaire_version`, `scores JSONB` (per-dimension), `overall_score NUMERIC`, `status` ∈ {`draft`,`final`}. Immutable once `final` (new revision = new row).

### `eligibility_runs` + `eligibility_results` *(Phase 3)*
Deterministic engine output. `eligibility_runs`: `programme_id`, `criteria_version`, `run_at`, `run_by`. `eligibility_results`: `run_id`, `company_id`, `eligible BOOL`, `score`, `matched JSONB`, `failed JSONB` — fully reproducible from `(criteria_version, company snapshot)`.

### `warnings` *(Phase 3)*
Warnings engine output. `entity_type`, `entity_id`, `rule_code`, `severity`, `message`, `raised_at`, `resolved_at NULL`, `resolved_by`. Materialized by a periodic job from deterministic rules (staleness, missing VAT, deadline at risk).

### `saved_views` *(Phase 2–3)*
User-saved list configurations. `owner_id`, `entity_type`, `name`, `config JSONB` (filters/sort/columns), `is_shared BOOL`.

### `import_batches` + `import_rows` *(Phase 4)*
Staging tables for the 11-step pipeline (`IMPORT_STRATEGY.md`). `import_batches`: `filename`, `source_type` ∈ {`csv`,`xlsx`,`teamsystem`}, `status` (per pipeline step), `mapping JSONB`, `stats JSONB`, `created_by`, `confirmed_at`. `import_rows`: `batch_id`, `row_index`, `raw JSONB`, `normalized JSONB`, `status` ∈ {`pending`,`valid`,`error`,`duplicate`,`imported`,`skipped`}, `error JSONB`, `result_entity_type`/`result_entity_id`. Provenance: every imported row sets `source='import:<batch_id>'` on the target entity.

### `refresh_tokens` *(Phase 5, ADR-004 follow-up)*
Server-side refresh sessions. `user_id`, `token_hash` (refresh token stored hashed), `expires_at`, `revoked_at`, `ip`, `user_agent`. Enables revocation list and rotation for the httpOnly-cookie design in `SECURITY.md` §2.
