# Changelog

All notable changes to Prosperya CRM. Format follows Keep a Changelog.

## [Unreleased]

### Added — Financial core: tesoreria, riconciliazione, control hub (2026-09-14)

Stati di maturità dichiarati (nessuna finta completezza): **FUNCTIONAL** per
scadenzario, riconciliazione L1/L2, cassa e cockpit; **SANDBOX** per la
connessione bancaria; **DESIGNED** per triage AI di livello 3 e ingestione
XML/SdI delle fatture proprie dell'azienda gestita.

- Modulo `treasury`: catena canonica `documento → open_item → bank_transaction
  → reconciliation_allocation → cassa` (ADR-016). Tabelle append-only
  (`open_items`, `bank_transactions`, `reconciliation_allocations`,
  `bank_sync_batches`); residuo, incassato e stato partita **derivati** dalle
  allocazioni. Correzioni solo via allocazioni `write_off`/`cancellation` con
  attore e motivazione obbligatoria.
- `BankingProvider` in sola lettura (AIS) con registro versionato e adapter
  `manual/v1` + `sandbox-openbanking/v1` deterministico (rifiuta
  `production`, `is_real_institution=false`, movimenti etichettati come
  simulati). Sync idempotente su `provider_tx_id` e `idempotency_key`.
  Nessuna iniziazione di pagamenti (ADR-017).
- Motore di riconciliazione deterministico e riproducibile: L1 esatto
  (importo al centesimo + riferimento verificato), L1 cumulativo (subset con
  somma esatta, pagamento unico su più fatture), L2 a punteggio pesato con
  soglia 0.60. `auto-apply` limitato ai L1 non ambigui su richiesta
  dell'operatore; ogni L2 richiede approvazione puntuale. Invarianti: nessuna
  sovra-allocazione, coerenza di segno, chiusura senza residuo rifiutata.
- Motore di cassa: posizione (null se manca un saldo, mai zero), scadenzario
  per fasce di ritardo, previsione giorno per giorno 30/60/90 con separazione
  esplicita fatti/ipotesi/formule e data di primo saldo negativo. Warning
  deterministici (`cash_forecast_negative`, `overdue_*`,
  `unreconciled_backlog`, `bank_feed_stale`, `cash_position_unknown`,
  `treasury_not_configured`, `sandbox_bank_data`) con formula ed evidenze.
- Modulo `cockpit` (senza tabelle): **control hub** multi-azienda con action
  center a priorità deterministica versionata e **CFO cockpit** per azienda
  che unisce economia, cassa e pipeline; `health` ammette `not_calculable`
  (ADR-018). Aggiunto `opportunities/service.py` come superficie di lettura
  pubblica per non interrogare tabelle di altri moduli.
- `invoices.due_date` (nullable) come ponte documento → scadenzario: senza
  scadenza nota non si genera alcuna partita e il documento è riportato come
  scartato.
- Primitivi monetari unificati in `app/shared/money.py`; `app/models_all.py`
  come registro unico dei modelli per Alembic e seed.
- Assistant: tool `get_cash_position`, `get_cash_forecast`,
  `get_receivables_aging`, `get_reconciliation_status` sui soli risultati
  verificati; item tipizzati estesi con `WARNING` e `ACTION_REQUIRED`;
  rifiuto esplicito su IVA/F24/imposte/payroll/bandi e su richieste
  dispositive.
- Frontend: pagine `Control hub`, `CFO cockpit` e `Tesoreria` con banco di
  riconciliazione (approvazione umana con evidenze in chiaro), forecast,
  aging e scadenzario; nav e design system estesi con i token esistenti.
- Seed demo dichiaratamente fittizio e sandbox: conto simulato, 5 movimenti
  scriptati (match esatto, cumulativo, fuzzy, commissione non abbinabile) e
  scadenzario con uno scaduto a 45 giorni e concentrazione F24/stipendi che
  rende la cassa negativa — così hub, cockpit e riconciliazione sono
  verificabili end-to-end.
- Test: 30 nuovi casi su isolamento tenant, autorizzazioni, importi come
  stringhe, dato mancante, idempotenza, append-only, casi limite di
  riconciliazione e riproducibilità dei motori (86 test totali verdi).

### Added — Multi-tenancy (2026-09-14)

- `tenants` table + `TenantMixin`; `tenant_id` on every business entity; tenant context dependency (`X-Tenant-Id` honoured for staff roles, client roles locked to their own tenant).
- Client roles `client_admin` / `client_operator` / `client_readonly`; tenant-scoped uniqueness for VAT, service-line codes, pipeline stages, invoice numbering, webhook events.
- Per-tenant billing provider configuration; webhook ingestion resolves the tenant via signature verification.
- Fresh Alembic baseline; seed creates platform org + demo client tenant; tenant switcher in the app shell.

### Added — Controllo di gestione + AI CFO (ported from prototype v0, 2026-09-14)

- `management` module: append-only consuntivi, bounded/atomic/idempotent CSV import, versioned monthly budgets, overview with formula trace, data-quality block, deterministic alerts, previous-year comparison, tenant-wide hub. Money as Decimal / `NUMERIC(20,2)`, serialised as strings; missing data is `null`, never `0`.
- `assistant` module: `AIProvider` protocol, allow-listed tools with per-call re-authorization, typed answer items (FACT/CALCULATION/ASSUMPTION/SUGGESTION), Decimal scenario engine, explicit limitations. Ships with a declared local deterministic mock.
- Frontend pages "Controllo di gestione" (KPI, monthly consuntivo-vs-budget chart, budget editor, cost categories, quality/provenance) and "AI CFO" (chat with typed items, tools used, limitations).
- Login brute-force throttle (per-IP / per-email) + constant-time unknown-email handling.
- UI: lucide icons, funnel chart, KPI accent edges, split-screen branded login.

### Added — Phase 0 foundation

- Repository structure, docs set, `.env.example`, docker-compose, CI workflow.
- FastAPI modular monolith: config, error envelope, structured logging, health.
- JWT auth (argon2id hashing) + centralized RBAC (admin/management/consultant/backoffice/readonly).
- Alembic migrations; seed script with demo data.

### Added — Phase 1 CRM core

- Companies with VAT normalization, duplicate detection (exact + probable), completeness report, soft delete, optimistic concurrency.
- Contacts + company-contact links.
- Leads with one-click conversion → company + contact + opportunity (no retyping).
- Configurable service lines + pipeline stages; opportunities with guarded stage moves (won/lost).
- Tasks, notes, unified activity timeline, append-only audit log.
- Global search, saved-filter-ready list endpoints (paged/sorted/filtered), operational dashboard.

### Added — Billing foundation (provider-independent)

- Invoice domain: drafts, lines, totals, transaction-safe numbering, customer/issuer snapshots, immutability after issue.
- Normalized status machine (internal / provider / SdI axes separated).
- `BillingProvider` interface + versioned adapter registry + `stub-sandbox/v1` test adapter.
- Transactional outbox for sends, submission-key idempotency, `transmission_unknown` + reconciliation, idempotent webhook ingestion, transmission history, provider health/config (admin).
- Contract tests covering the lifecycle end-to-end.

### Docs

- MASTER_SPEC, DISCOVERY, ARCHITECTURE, DATA_MODEL, BRAND_SYSTEM, UX_RULES,
  TEAMSYSTEM_BENCHMARK, SECURITY, IMPORT_STRATEGY, AI_ARCHITECTURE,
  TEST_PLAN, DEPLOYMENT, DECISIONS, BILLING_ARCHITECTURE, INTEGRATIONS.
