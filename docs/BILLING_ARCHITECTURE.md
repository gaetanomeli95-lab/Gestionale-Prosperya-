# Billing & Electronic Invoicing Architecture

Status: **foundation implemented (provider-independent)** — no real provider
connector exists yet by design. See `docs/INTEGRATIONS.md`.

## 1. Layering

```
CRM modules / frontend
        ↓
billing domain      (app/modules/billing — invoices, lines, statuses, events)
        ↓
BillingProvider     (providers/base.py — the ONLY contract the domain speaks)
        ↓
versioned adapters  (providers/<name>/vN.py, resolved via providers/registry.py)
        ↓
external provider → SdI        (or, future: DirectSdiAdapter → SdI)
```

The domain never sees provider request schemas, auth models, proprietary
status codes or webhook payloads. Adapters normalize everything into
`ProviderResult` / `WebhookEvent` / `NormalizedError`.

## 2. Prosperya owns the data

`invoices` rows exist independently of any provider. Provider identifiers
(`provider_key`, `provider_api_version`, `provider_external_id`,
`sdi_identifier`, `sdi_filename`) are *transmission metadata* — they never
replace the internal UUID or the fiscal number.

Historical invoices survive provider replacement: switching the active row
in `billing_provider_configs` affects only future operations; every past
`invoice_transmission_events` row keeps which provider/version produced it.

## 3. Status model — three axes, never merged

| Axis | Column | Owner |
|---|---|---|
| Internal workflow | `invoices.status` | Prosperya (guarded transitions) |
| Provider | `invoices.provider_status` | raw provider code, verbatim |
| SdI | `invoices.sdi_status` | normalized `SdiStatus` where exposed |
| Payment | `invoices.payment_status` | separate domain — see §30 of the addendum |

Internal states: `draft → ready_to_send → queued → transmitting →
sent_to_provider → submitted_to_sdi → delivered/accepted`, plus
`rejected`, `delivery_failed`, `transmission_unknown`,
`requires_reconciliation`, `credited`, `cancelled`, `imported`.

`ALLOWED_TRANSITIONS` in `statuses.py` is the guard table. When a provider
reports a state several steps ahead (synchronous "delivered"), the service
walks the intermediate states so `invoice_transmission_events` stays a
truthful history.

## 4. Numbering

`invoice_sequences (series, fiscal_year) → last_number`, incremented with
`SELECT … FOR UPDATE` inside the finalize transaction. Drafts have **no**
fiscal number; `(series, fiscal_year, number)` is unique. Numbers are
assigned only at `POST /billing/invoices/{id}/finalize`.

## 5. Immutability & snapshots

* Only `draft` invoices are editable (`IMMUTABLE_STATUSES` guard).
* Finalize freezes `customer_snapshot` (from the company record) and
  `issuer_snapshot` (from `BILLING_ISSUER_*` settings) — later CRM edits
  never rewrite issued documents.
* Corrections after issue → credit note / controlled reissue workflow
  (rejected `scartata` invoices may re-enter `ready_to_send`).

## 6. Send flow — never fake success

```
SEND click → request_send()
    → status=queued, submission_key persisted (once per intention)
    → outbox_events row in the SAME transaction
Worker/dispatcher → dispatch_pending_sends()
    → provider.submit_invoice(invoice, idempotency_key=submission_key)
    → _apply_provider_result() maps the normalized result
```

* **Retry safety**: retries reuse the same `submission_key`; adapters must
  honour it (`supports_idempotency_keys` capability).
* **Ambiguous outcomes** (timeout, unmapped status, malformed response) →
  `transmission_unknown`. Resend is *blocked* until `reconcile_invoice`
  resolves the real state via `get_invoice_status` — queried by external
  id, falling back to the submission key when the response was lost.
* **No automatic provider failover** for fiscal submissions — ever.

## 7. Webhooks

`POST /api/v1/billing/webhooks/{provider_key}` is unauthenticated at the
HTTP layer; the *adapter* verifies authenticity (signature/token).
`webhook_events (provider_key, provider_event_id)` is unique → duplicate
deliveries return `duplicate_ignored`. Out-of-order events are stored with
`ignored_out_of_order` instead of corrupting the state machine.

## 8. Polling fallback

`reconcile_invoice` + `retrieve_notifications` cover providers without
webhooks. Only invoices in transitional/unresolved states are polled —
never the full history.

## 9. Configuration & secrets

* One active `billing_provider_configs` row; `PUT /billing/provider`
  validates that the `provider_key/api_version` pair is registered.
* Secrets are **never** stored: `credentials_ref` / `webhook_secret_ref`
  name an env var or secret-manager key holding a JSON credential blob.
* API responses expose metadata only (`credentials_configured: bool`).
* `POST /billing/provider/test` runs the adapter health check.

## 10. RBAC

| Scope | Roles |
|---|---|
| `billing:read` | all business roles |
| `billing:write` | consultant, backoffice, management, admin (draft create/edit) |
| `billing:submit` | management, admin (finalize / send / reconcile) |
| `billing:admin` | admin (provider config, dispatch, health) |

## 11. Reliability strategy

* **Transactional outbox** for send intentions (`outbox_events`) — commit
  and external call can't diverge.
* **Idempotent webhooks** via unique provider event ids.
* **Append-only transmission log** for every state change and provider
  interaction.
* **Audit log** on create/update/finalize/send/provider-change.
* Normalized `ErrorCategory` taxonomy so users get actionable messages
  ("customer VAT number is missing") while provider internals stay in logs.

## 12. Future: direct SdI

`providers/direct_sdi/` is a deliberate empty slot. Implementing it requires
accreditation, certificates and verified Agenzia delle Entrate docs — when
built, it will be just another adapter version in the registry. Nothing in
the domain or CRM changes.

## 13. What is deliberately NOT built yet

* Real provider adapters (waiting for provider selection + official docs).
* FatturaPA XML generation (needs official XSD validation work).
* Received-invoice ingestion (architecture allows it: `supports_incoming_invoices`).
* Credit note entity (contract supports it: `create_credit_note`).
* Payment tracking (`payment_status` column reserved).
* Async worker (outbox dispatcher is a service function; a scheduler can
  call `dispatch_pending_sends` unchanged).

## Provider catalog and support status (Phase G0, 2026-09-26)

`providers/catalog.py` separates two facts the UI must never conflate: what a
provider *offers* (research, with official source + verification date) and
whether Prosperya *has a working connector* for it. `ProviderSupportStatus`
enumerates the honest states; `SUPPORTED_IN_PROSPERYA` is derived from the
adapter registry at runtime and cannot be asserted by data. Capabilities are
tri-state (`true`/`false`/`UNKNOWN`). Served by `GET /billing/providers/catalog`
for the future Integration Center (Impostazioni → Integrazioni → Fatturazione
elettronica). The full matrix, sources, Direct-SdI assessment and first-adapter
candidates live in `docs/INTEGRATIONS.md`.

Contract extensions added after the provider research, all non-breaking:
`ProviderCapabilities.supports_dry_run / supports_multi_company /
supports_provider_side_archive` and `ProviderResult.retry_after_seconds`
(honour provider back-off hints in the outbox instead of a fixed schedule).
