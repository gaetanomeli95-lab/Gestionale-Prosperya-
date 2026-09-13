# External Integrations Registry

One entry per provider adapter. **Do not invent provider documentation
details** — when a real adapter is implemented, fill this from *current
official sources* and record the verification date.

## Electronic invoicing providers

### stub-sandbox / v1 (built-in test adapter)

| Field | Value |
|---|---|
| Provider name | Stub Sandbox (internal — NOT a real provider) |
| Official documentation | n/a — internal contract double |
| Configured API version | v1 |
| Authentication | shared `webhook_token` via `credentials_ref` env var |
| Capabilities | outgoing invoices, webhooks, status polling, credit notes, XML download, sandbox, idempotency keys |
| Sandbox availability | always (it IS a sandbox) |
| Webhook availability | yes (`X-Stub-Token` header verification) |
| Rate limits | none |
| Known limitations | in-memory state — resets per process; refuses `production` environment |
| Implemented | 2026-09-13 |
| Docs last verified | n/a |
| Deprecation | none — dev/test only, must never be active in production config |
| Migration notes | — |

### aruba — NOT IMPLEMENTED

Placeholder. Implement only after provider selection and verification of
current Aruba API documentation (auth model, endpoints, webhook support,
sandbox availability). Registry key reserved: `aruba`.

### fatture_in_cloud — NOT IMPLEMENTED

Placeholder. Registry key reserved: `fatture-in-cloud`.

### teamsystem — NOT IMPLEMENTED

Placeholder. Registry key reserved: `teamsystem`. TeamSystem integration
knowledge is a *benchmark source*, not a blueprint — see
`docs/TEAMSYSTEM_BENCHMARK.md`.

### direct_sdi — NOT IMPLEMENTED

Placeholder for a future direct Sistema di Interscambio adapter.
Prerequisites: accreditation, certificates, current FatturaPA technical
specs, production infrastructure review. Registry key reserved: `direct-sdi`.

## Calendar / email / other providers

None yet. All future integrations follow the same rule: adapter behind an
internal interface, capabilities declared, secrets outside the DB, contract
tests before release.
