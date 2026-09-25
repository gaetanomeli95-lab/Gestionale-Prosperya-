# External Integrations Registry

Source of truth for every external provider Prosperya talks to or has
researched. Technical facts come **only from current official documentation**
(developer portals, API references, official PDFs, official SDK repos), with
the URL and the date they were last verified. `UNKNOWN` is a legitimate value
and is preferred over a guess.

Machine-readable mirror: `backend/app/modules/billing/providers/catalog.py`
(served by `GET /api/v1/billing/providers/catalog`). Update both together.

---

## 1. Support status model

| Status | Meaning | Who sets it |
|---|---|---|
| `RESEARCHED` | official docs read, matrix filled, no decision | this document |
| `SUPPORTED_BY_PROVIDER_API` | provider exposes a programmatic integration suitable for an external CRM | this document |
| `REQUIRES_PARTNER_AGREEMENT` | integration exists but docs/credentials only via commercial/partner channel | this document |
| `REQUIRES_CREDENTIALS` | public docs, but a paid/activated account is needed to test | this document |
| `IMPLEMENTABLE` | nothing blocks an adapter today (docs + sandbox + credentials in hand) | this document |
| `IN_DEVELOPMENT` | adapter branch exists, contract kit not yet green | this document |
| `SUPPORTED_IN_PROSPERYA` | **derived at runtime**: adapter registered in `providers/registry.py` **and** `TestContractKit` green | never by hand |
| `UNAVAILABLE` | no programmatic integration offered | this document |
| `UNKNOWN` | not established by official documentation | default |

`effective_status()` refuses data that claims `SUPPORTED_IN_PROSPERYA` without
a registered adapter (it downgrades it to `UNKNOWN`). Tests:
`test_provider_catalog.py`.

Capabilities are **tri-state** (`true` / `false` / `UNKNOWN`) and per provider;
the core adapts to `ProviderCapabilities` instead of assuming parity.

---

## 2. Compatibility matrix (verified 2026-09-26)

Legend: ✓ documented yes · ✗ documented no · ? UNKNOWN from official docs

| | **Aruba** | **Fatture in Cloud** | **TS Digital Invoice** | **Zucchetti Digital Hub** | **A-Cube** | **Openapi SDI** | **Direct SdI (AdE)** |
|---|---|---|---|---|---|---|---|
| Vendor | Aruba PEC S.p.A. | TeamSystem S.p.A. | TeamSystem S.p.A. | Zucchetti S.p.A. | A-Cube S.r.l. | Openapi S.r.l. | Agenzia delle Entrate |
| Integration available | ✓ | ✓ | ✓ | ✓ (on request) | ✓ | ✓ | ✓ (channel accreditation) |
| Public API docs | ✓ | ✓ | partial (test hosts public; prod docs 403) | ✗ (sent by sales/partner) | ✓ | ✓ | ✓ (specs PDF) |
| Private/partner API | – | – | credentials only after purchase | ✓ | – | – | – |
| Auth model | OAuth2 password grant + refresh, Bearer | OAuth2 Auth Code (preferred), Device Code (on request), manual long-lived token | JWT Bearer, Id/Secret issued with service | web-service user/password issued with contract | JWT login; API key / OAuth2 advertised | console-issued scoped token | digitally signed service agreement + X.509 certs after interoperability tests |
| Protocol | REST/JSON | REST/JSON, OpenAPI 3, official SDKs | REST/JSON (B2BWrite/B2BRead) | web service (unspecified) | REST JSON **or** FatturaPA XML, OpenAPI | REST JSON/XML, OAS3 | SOAP w/ attachments + MTOM over HTTPS (SdICoop) · SFTP (SdIFtp) · PEC |
| Sandbox / test env | ✓ demo env **with SdI simulation** | ✗ no SdI sandbox — `options.dry_run` on send | ✓ `*-api-test.agyo.io` | ? | ✓ free sandbox | ✓ `test.sdi.openapi.it` | ✓ test env after accreditation |
| Outgoing invoices | ✓ (XML upload, signed or unsigned) | ✓ (FiC document model → send) | ✓ (XML upload v2) | ✓ | ✓ | ✓ | ✓ |
| Incoming invoices | ✓ | ✓ | ✓ (eRicevi) | ✓ | ✓ | ✓ | ✓ |
| Credit notes | ✓ (TD04 is an invoice type) | ✓ (`issued_documents.credit_notes`) | ? | ? | ✓ | ? | ✓ |
| SdI status retrieval | ✓ (`findInvoices`, `getInvoiceDetail`, notifications) | ✓ (`ei_status` on Get Issued Document) | ✓ (B2BRead) | ✓ (notifications via WS) | ✓ | ✓ (`/invoices_notifications`) | ✓ (RC/NS/MC/… notifications) |
| Receipt (ricevuta) retrieval | ✓ (notification detail/zip) | ? | ? | ? | ? | ? | ✓ |
| XML retrieval | ✓ (`download`, `getInvoiceZip`) | ✓ | ✓ | ? | ✓ | ✓ (`/invoices_download`) | ✓ |
| Webhooks / events | ✓ callbacks (endpoint accreditation, 10 retries / 3 h) | ✓ (`…e_invoices.status_update`, id only) | ? | ? | ✓ signed webhooks, retries | ✓ | ✓ (SdI **pushes** to your endpoint — mandatory) |
| Polling | ✓ | ✓ | ✓ | ? | ✓ | ✓ | ✗ (push model) |
| Multi-company | ✓ multicedenti (Premium + delegations) | ✓ company-scoped (`/c/{company_id}`) | ✓ | ✓ (Master + aziende) | ✓ Business Registry Configurations | ✓ | ✓ (intermediary) |
| Rate limits | Tier 0: 60 req/h, 10k/year … Tier 6: 30k req/h; leaky bucket, 429 no queue | 1,000/h per company-app; 40k/month; 300 per 5 min; 429/403 + Retry-After | ? | ? | configurable per tenant (figures ?) | 10,000 req/min (console) | n/a (5 MB/file; 1 file per SOAP call) |
| Commercial prerequisites | **Premium** account (or Base delegated to Premium); demo credentials from Aruba | FiC company with e-invoicing; registered app (client id/secret); App Store review for public apps | TS Digital Invoice subscription; Id/Secret by e-mail | Digital Hub contract; docs from sales/partner | free sandbox; production account; preservation via Intesi | console account, pay-per-use | accreditation as channel/intermediary; conservazione a norma; signature |
| Partner agreement required | ✗ | ✗ | ? | ✓ | ✗ | ✗ | ✗ (accreditation, not commercial) |
| API version | v2 (2.2.0 doc; changelog → 2.5.0, 22/06/2026) | v2 (OpenAPI 2.1.8) | B2BWrite v7.5.x, Invoices v2 (v1 deprecated) | ? | v1 | current | Specifiche tecniche v1.8 (18/01/2024); SdICoop v3.0 |
| Deprecation / version policy | v1 still documented, v2 current; dated changelog | changelog + roadmap published; v1 sunset guide | "v1 deprecated, will be dismissed" (undated) | ? | ? | ? | provvedimenti AdE, versioned PDFs |
| Documentation quality | high | high | medium | low | high | medium | high (but SOAP/PDF) |
| Known technical limitations | Tier 0 quota tiny for polling; callbacks need endpoint accreditation; caller builds FatturaPA XML | no SdI sandbox; JSON document model not raw XML; webhook needs follow-up GET | provider-specific flow types SDIPA/SDIPR/SELFSEND; webhook support unknown | everything beyond send/receive unknown | smaller vendor | provider-specific config entities | not HTTP/JSON; host a receiving endpoint; certificate lifecycle; full operational responsibility |
| **Status** | `REQUIRES_CREDENTIALS` | `REQUIRES_CREDENTIALS` | `REQUIRES_CREDENTIALS` | `REQUIRES_PARTNER_AGREEMENT` | `SUPPORTED_BY_PROVIDER_API` | `SUPPORTED_BY_PROVIDER_API` | `RESEARCHED` |
| Last verified | 2026-09-26 | 2026-09-26 | 2026-09-26 | 2026-09-26 | 2026-09-26 | 2026-09-26 | 2026-09-26 |

### Sources

- **Aruba** — API Docs v2: <https://fatturazioneelettronica.aruba.it/apidoc/v2/docs_EN.html> (chapters 2 environments, 5 auth, 7.3 tiering, 14 callbacks, 15 SdI simulation); v1: <https://fatturazioneelettronica.aruba.it/apidoc/docs_EN.html>; Premium account manual: <https://guide.pec.it/fatturazione-elettronica/manuale-account-premium.pdf>.
- **Fatture in Cloud** — <https://developers.fattureincloud.it/docs/basics/authentication/>, `/docs/basics/limits-and-quotas/`, `/docs/guides/e-invoice-management/`, `/docs/webhooks/notification-types/`; OpenAPI: <https://github.com/fattureincloud/openapi-fattureincloud>; API terms: `/docs/legal/terms/`.
- **TS Digital Invoice** — <https://b2bwrite-api-test.agyo.io/api/docs/index.html>, <https://b2bread-api-test.agyo.io/api/docs/index.html>; product sheet: <https://www.teamsystem.com/store/pdf/Infoscheda_TS_Digital_Invoice.pdf>; portal: <https://appdev.teamsystemdigital.com/portale/>.
- **Zucchetti Digital Hub** — <https://zucchetti.it/it/cms/soluzioni/obblighi-normativi/fatturazione-elettronica/digital-hub/fatturazione-elettronica-aziende-descrizione.html> (FAQ "Non ho un gestionale Zucchetti…"); help: <https://help.zucchetti.it/cms/kb/soluzioni/fatturazione-elettronica/digital-hub>.
- **A-Cube** — <https://docs.acubeapi.com/documentation/italy/gov-it/invoices/>, `/webhooks`, `/configurations`; product page <https://www.acubeapi.com/prodotti/api-e-invoicing-italia>.
- **Openapi** — <https://console.openapi.com/apis/sdi/documentation>, FAQ <https://console.openapi.com/it/apis/sdi/faq>.
- **Direct SdI** — Specifiche tecniche v1.8 (Allegato A, 18/01/2024) and SdICoop/SdIFtp instructions from <https://www.agenziaentrate.gov.it/portale/schede/comunicazioni/fatture-e-corrispettivi/fatture-e-corrispettivi-st/st-invio-di-fatturazione-elettronica-intermediari>; accreditation guide "Accreditamento e richiesta codici destinatario v1.0".

Providers **not** listed because no programmatic integration for an external CRM was found in official material within this pass: Danea Easyfatt (desktop, exports XML / hands off to TS Digital), InfoCert Legalinvoice and Namirial (e-invoicing sold as web apps / via partners; API access not documented publicly — to be re-checked with the vendors if ever relevant).

---

## 3. Assessment against the current `BillingProvider` abstraction

The existing contract (`providers/base.py`) is sufficient for every provider above **without changing the domain**:

| Contract member | Aruba | FiC | TS Digital | A-Cube | Openapi | Direct SdI |
|---|---|---|---|---|---|---|
| `submit_invoice(idempotency_key)` | upload XML; our key ↔ Aruba `requestId`/`uploadFileName` | create document + `send` (dry_run in test); our key ↔ FiC document id | upload v2 | `POST /invoices` | `POST /invoices` | SOAP `RiceviFile` |
| `get_invoice_status` | `getInvoiceDetail` | `Get Issued Document.ei_status` | B2BRead | `GET /invoices/{uuid}` | `GET /invoices` | derived from received notifications |
| `retrieve_notifications` (polling) | `getNotifications` | polling on documents | B2BRead | list notifications | `/invoices_notifications` | n/a (push) |
| `verify_webhook` | callback IPs + accreditation | subscription verification handshake | ? | HTTP Signature / token | ? | SOAP `RicevutaConsegna`… inbound endpoint |
| `download_xml` / `download_receipt` | ✓ / ✓ | ✓ / ? | ✓ / ? | ✓ / ? | ✓ / ? | ✓ / ✓ |
| `create_credit_note` | same as invoice, TD04 | credit-note document | ? | ✓ | ? | TD04 |
| `capabilities` | all true | `supports_sandbox=false` | several `None` → adapter declares false | mostly true | mostly true | `supports_status_polling=false` |

Two **small, general** extensions are recommended before the first real adapter (not provider-specific, and the stub keeps passing):

1. `ProviderCapabilities.supports_dry_run: bool = False` — FiC's `options.dry_run`, and any provider without an SdI sandbox, need a first-class "validate without transmitting" flag so the domain can offer a safe "verifica" action. Today the only alternative is abusing `environment`.
2. `ProviderResult.retry_after_seconds: int | None` — Aruba (429), FiC (429/403 + `Retry-After`) and Openapi expose back-off hints; the outbox dispatcher should honour them instead of a fixed schedule. Non-breaking (defaults to `None`).

Everything else (flow types, business registry configurations, multicedenti, callback accreditation) is provider-internal and stays inside the adapter. **No provider model leaks into the core.**

---

## 4. Direct SdI — high-level findings

Channels (Specifiche tecniche v1.8 §1.2): PEC (≤ 30 MB, multiple files), **SdICoop** web service (SOAP with attachments, MTOM, HTTPS/TLS 1.2, one file ≤ 5 MB per call), **SdIFtp** (SFTP, SdI-initiated get/put, meant for high-volume "nodi"), and the AdE web portal.

Accreditation: digitally signed *accordo di servizio*, interoperability tests, then an electronic certificate for the calling system; SdIFtp additionally requires a hosted SFTP node with DR contacts and a 15-day setup window. Notifications (RC, NS, MC, DT, …) are **pushed by SdI** to the accredited receiving service — Prosperya would have to expose and operate an inbound SOAP endpoint 24/7.

Operational responsibilities that today sit with an intermediary would move to Prosperya: qualified signature where required, conservazione a norma (DPCM 3/12/2013), certificate lifecycle, file naming rules, error/notification handling, and being the *soggetto trasmittente* of record.

Conclusion: technically feasible, **not preferable by default**. Keep `DirectSdiAdapter` as an architectural option (`integration_kind=direct_channel`); revisit only if volumes or provider economics justify running an accredited node.

---

## 5. Integration Center — data/UI concept (not built yet)

Route: **Impostazioni → Integrazioni → Fatturazione elettronica**. Data: `GET /billing/providers/catalog` + `GET /billing/provider` (tenant config/health).

```
┌ Fatturazione elettronica ─────────────────────────────────────────────┐
│ Provider              Stato Prosperya            Connessione (tenant) │
│ Aruba                 ● Richiede credenziali     — non configurato    │
│ Fatture in Cloud      ● Richiede credenziali     — non configurato    │
│ A-Cube                ● API disponibile          —                    │
│ TS Digital Invoice    ● Richiede credenziali     —                    │
│ Zucchetti Digital Hub ● Richiede accordo partner —                    │
│ SdI diretto           ● Studiato                 —                    │
│ Stub sandbox          ● Connettore Prosperya     ✓ sandbox · v1 · ok  │
└───────────────────────────────────────────────────────────────────────┘
Card provider: capabilities (✓/✗/?), versione API adapter, ultimo health check,
configurazione (credentials_ref, environment), link alla documentazione
ufficiale + data verifica.
```

Two badges, always both: **"Il provider esiste"** (research status) and **"Prosperya ha un connettore funzionante"** (`adapter_registered` + health). A provider without a registered adapter can never show the second.

---

## 6. Candidate first adapters (for review — no implementation yet)

| Criterion | Aruba | Fatture in Cloud | A-Cube | Openapi |
|---|---|---|---|---|
| Official API quality | high, REST, dated changelog | high, OpenAPI + SDKs | high, OpenAPI | medium |
| Sandbox with SdI simulation | **yes** | **no** (dry_run only) | yes | yes |
| Docs quality | high | high | high | medium |
| Feature completeness for our contract | full (incl. receipts) | full except receipts (?) | full except receipts (?) | credit notes ? |
| Webhooks | yes, needs endpoint accreditation | yes, id-only + fetch | yes, signed | yes |
| Ease of testing | demo env, but Premium credentials needed | needs a FiC account; no SdI test | free sandbox signup | free sandbox |
| Maintainability | incumbent, versioned | incumbent, SDKs, roadmap | smaller vendor | smaller vendor |
| Commercial/access | Premium account | FiC account + app registration | account | account |
| Fit for Prosperya (consultancy handling many client companies) | multicedenti + delegations designed for intermediaries | company-scoped; clients often already on FiC (TeamSystem group) | multi-company by design | multi-company |

**Engineering recommendation**: two strongest candidates, for different reasons —
- **Aruba** if the priority is a realistic end-to-end test against a simulated SdI and an intermediary-style multi-company model; cost: obtaining Premium/demo credentials, low Tier-0 quota.
- **Fatture in Cloud** if the priority is reaching client companies already using it and the best developer ergonomics; cost: no SdI sandbox (contract tests must rely on `dry_run` + mocked webhooks).
- **A-Cube** is the fastest to *start* (free sandbox, XML-native, webhooks) and a good second adapter to prove multi-provider independence; weigh vendor size.

Not implementable now: **Zucchetti Digital Hub** (documentation only via sales/partner), **TS Digital Invoice** (credentials only after purchase, partial public docs), **Direct SdI** (accreditation + operational burden).

---

## 7. Adapter entries (implementation records)

### stub-sandbox / v1 (built-in test adapter)

| Field | Value |
|---|---|
| Provider name | Stub Sandbox (internal — NOT a real provider) |
| Official documentation | n/a — internal contract double |
| Configured API version | v1 |
| Authentication | shared `webhook_token` via `credentials_ref` env var |
| Capabilities | outgoing invoices, webhooks, status polling, credit notes, XML download, sandbox, idempotency keys |
| Rate limits | none |
| Known limitations | in-memory state — resets per process; refuses `production` environment |
| Implemented | 2026-09-13 |
| Deprecation | none — dev/test only, must never be active in production config |

Real adapters get their own section here when implemented: provider, API version, auth, sandbox, webhook handling, rate-limit strategy, known limitations, implementation date, docs verification date, deprecation notices, migration notes.
