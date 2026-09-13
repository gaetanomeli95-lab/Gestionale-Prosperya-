# Import Strategy

Data import is a strategic capability (TeamSystem exports, CSV/XLSX, future
external sources). Nothing is imported directly into production tables.

## Pipeline (11 steps)

1. **Upload** — file stored in staging area; metadata recorded (uploader, source, timestamp).
2. **Staging** — rows land in `import_batches` / `import_rows` (designed; not yet implemented).
3. **Column mapping** — user maps source columns to CRM fields; mapping is saved per source type.
4. **Normalization** — VAT uppercase/stripped, dates parsed, phones normalized, enums mapped.
5. **Validation** — per-row errors collected (never fail the whole batch silently).
6. **Duplicate detection** — exact identifiers (VAT, tax code, PEC, email) + probable matches (normalized name).
7. **Preview** — counts: new / duplicates / conflicts / invalid; sample rows.
8. **Error report** — downloadable per-row diagnostics.
9. **User confirmation** — explicit apply step.
10. **Import** — idempotent apply (safe to re-run), provenance stamped on every record.
11. **Audit trail** — batch, actor, mapping, decisions recorded.

## Rules

- **Provenance**: `source`/`source_detail` on imported records (e.g. `teamsystem-export-2026-09`).
- **No blind overwrite**: if an existing CRM record conflicts with import data, the conflict is surfaced — never silently overwritten. Merge policies are documented per entity before enabling.
- **Imported ≠ authoritative**: legacy rows may be wrong; confidence/status markers allow review queues.
- **Historical billing documents**: imported invoices are created with `status=imported` — they are *never* transmittable to SdI again.
- **Rollback**: each batch keeps a row-level manifest so a controlled reversal is possible.

## TeamSystem mapping

When TeamSystem exports arrive, each entity gets a mapping analysis in
`docs/TEAMSYSTEM_BENCHMARK.md` before any import code is written.
