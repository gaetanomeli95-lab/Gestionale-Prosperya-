# Changelog

All notable changes to Prosperya CRM. Format follows Keep a Changelog.

## [Unreleased]

### Changed — Consolidamento, hardening e validazione PostgreSQL (Phase B–F, 2026-09-24)

Stato: **integrazione completata** su `integration/prosperya-v02` — tutta la
catena di feature branch (financial → fiscal → controlling → funding →
documents) più il branch demo, verificata su PostgreSQL 16.15.

Correzioni (tutte con test di regressione):

- **db**: il registro ORM non dipende più dall'ordine di import
  (`Mapper.before_configured` in `app.db`); `NoReferencedTableError` /
  `InvalidRequestError` su import parziali eliminati.
- **db/PostgreSQL**: il listener `PRAGMA foreign_keys` girava su ogni
  dialetto e lasciava le transazioni psycopg in stato abortito — ogni nuova
  connessione PostgreSQL falliva alla prima query. Registrato solo per SQLite.
- **db/PostgreSQL**: `documents.current_version_id` non aveva la foreign key
  su PostgreSQL (FK `use_alter` senza nome, omessa dalla migrazione
  generata). Migrazione `a7c1e3f9b2d4` la ripristina; test di parità
  ORM↔DB.
- **practices**: exactly-once scadenza→task garantito dal database (indice
  unico parziale `uq_tasks_tenant_sync_key`, migrazione `b3d2f0a1c5e7`);
  il servizio adotta il vincitore in caso di gara.
- **funding/practices**: `approved → closed` portava la pratica operativa a
  `cancelled`; ora conserva l'esito. `practice_id` esposto nell'API
  (ADR-023).
- **documents**: creare/aggiornare/soddisfare un requisito documentale
  collegato a una pratica sincronizza i blocker della pratica (prima solo il
  percorso funding lo faceva); il soddisfacimento è auditato.
- **auth/config**: policy `JWT_SECRET` (≥ 32 byte, no placeholder), avvio
  rifiutato in produzione se violata; profilo Argon2 `fast` solo per i test
  e rifiutato in produzione.

Infrastruttura e test:

- `docker-compose.yml` con PostgreSQL `16.15-alpine` pinnato, credenziali da
  `.env`, healthcheck, volume nominato; `.env.example` PostgreSQL-first.
- Suite backend **207 → 285 test**, runtime **541 s → 136 s** (SQLite in
  memoria + Argon2 fast). Stessa suite verde su PostgreSQL
  (`TEST_DATABASE_URL`).
- Nuove suite: RBAC/tenancy trasversale, exactly-once, contratto billing +
  conformance kit, config security, registro ORM, parità schema.
- Frontend: Vitest + Testing Library (15 test componenti) e Playwright con
  5 flussi smoke contro backend reale (`scripts/e2e_server.py`).
- CI: gate rapido (ruff, SQLite, tsc, Vitest, build) + job PostgreSQL
  (migrazioni empty→head→base→head, doppio seed, suite completa) + E2E.
- Workspace: 51 radici di file di ricerca ST-9000 estranei al CRM spostate
  fuori dal repository; `.gitignore` con guardie mirate.

Decisioni: ADR-023 (pratica finanziata ↔ pratica operativa), ADR-024 (RLS
rinviata con prerequisiti).
### Added — Controlling & Early Warning: servizio del debito, regole CCII, alert durevoli, scenari (2026-09-16)

Stato: **FUNCTIONAL** per anagrafica debito, metriche deterministiche,
regole early-warning versionate, alert con ciclo di vita umano e scenari
bounded. **NOT IMPLEMENTED** per la determinazione dello stato di crisi
(fuori perimetro legale) e per banche dati esterne.

- `debt_facilities` + `debt_service_lines`: linee di debito e rate
  pianificate con transizioni tracciate (`scheduled → paid | waived`,
  motivazione obbligatoria per la sospensione). Il servizio del debito non
  è un `open_item`: nessun doppio conteggio con lo scadenzario.
- Metriche pure (`controlling-v1.0`): DSCR prospettico su obbligazioni
  datate (denominatore assente → `not_applicable`, mai «infinito»),
  continuità 12 mesi con runway e primo giorno negativo, margine di
  sicurezza, trend con baseline esplicita (`no_baseline`, mai direzione
  indovinata).
- `early_warning_rules`: sei regole CCII versionate ed effective-dated con
  fonte Normattiva; ogni parametro è `statutory` o `operational` — le
  soglie correnti sono tutte operative, dichiarate tali (ADR-022).
- `controlling_alerts`: alert durevoli con `dedupe_key` — detection
  idempotente, auto-risoluzione quando la condizione rientra, riapertura
  con evidenza della decisione precedente. Ciclo umano auditato:
  acknowledge/resolve/dismiss (dismiss con motivazione obbligatoria).
- Scenari `BASE`/`STRESS`/`UPSIDE`/custom con bound dichiarati: ricalcolo
  deterministico su copie dei fatti, ipotesi ripetute verbatim nell'output,
  consuntivi storici mai modificati.
- Cockpit/hub: categoria `early_warning` (peso 14, tra tesoreria e
  fiscale), alert persistiti nell'action center con regola e versione che
  ha sparato; il cockpit legge soltanto — la detection resta una scrittura.
- Seed sandbox: mutuo con rata scaduta (→ `EW-FIN-OVERDUE` critical) e
  rate future, leasing trimestrale, detection iniziale.
- Nuovi endpoint: `GET /controlling/rules`, `POST /controlling/rules/sync`,
  `GET/POST/PATCH …/facilities`, `POST …/instalments`,
  `POST …/instalments/{id}/settle`, `GET …/snapshot`,
  `POST …/alerts/evaluate`, `GET …/alerts`,
  `POST …/alerts/{id}/acknowledge|resolve|dismiss`,
  `GET …/scenarios/presets`, `POST …/scenarios/run`.
- Frontend `/controlling` (2026-09-17): workspace a 7 tab — Panoramica,
  Redditività, Liquidità & continuità 12 mesi, Debito & DSCR con
  drill-down (numeratore/denominatore, versioni formula/forecast,
  copertura fonti), Early Warning con lifecycle auditato e «Rivaluta
  segnali» solo su azione esplicita, Scenari con confronto delta KPI,
  Data Quality. Stati `insufficient_data`/`not_applicable`/`partial` mai
  resi come €0; nessuna dicitura di «crisi».
- Cockpit CFO: blocco compatto «Controlling & early warning» con alert e
  drill-down; Control Hub: colonna EW + «Perché ora»
  (`signal_count` + `top_signal`) per spiegare la priorità.
- Assistant: 8 tool read-only controlling (`get_controlling_summary`,
  `get_dscr`, `get_12m_continuity`, `get_early_warning_alerts`,
  `get_debt_service`, `get_scenario_comparison`,
  `get_controlling_data_quality`, `get_hub_position`) — nessun ricalcolo
  AI, evidence obbligatoria, `legal_notice` su domande di crisi.
- Migration `3995df39ccc4_controlling_early_warning`: 4 tabelle
  (`early_warning_rules`, `controlling_alerts`, `debt_facilities`,
  `debt_service_lines`) con vincoli e indici; `alembic check` pulito.

### Added — Fiscal Core V1: registro IVA, liquidazioni, F24 interni (2026-09-16)

Stato: **FUNCTIONAL** per registro IVA, liquidazione deterministica
mensile/trimestrale, validazione umana, scadenze e bozze F24 interne;
**INTERNAL** per l'export JSON/CSV; **NOT IMPLEMENTED** per tracciato
telematico e trasmissione F24.

- `fiscal_rule_sets` + `fiscal_tax_codes`: regole versionate ed effective-dated
  con fonte autorevole completa (authority, URL, fingerprint, data di
  rilevamento). Senza regola vigente il calcolo **rifiuta**, mai fallback
  (ADR-020). Motore puro `fiscal-engine-v1.0` / `vat-settlement-v1.0` /
  `payment-calendar-v1.0` (sabato/festivi, agosto).
- Registro IVA append-only con classificazione bounded: `supported`,
  `unsupported`, `requires_review`, `insufficient_data` — voci escluse dai
  totali ma contate e listate; la verifica umana è una voce `system_derived`
  che sostituisce l'originale. Import bulk atomico e idempotente per
  `source_ref`; derivazione da fatture del workspace sempre `requires_review`.
- Liquidazioni versionate (ricalcolo = nuova versione, mai overwrite), traccia
  completa: rule set, passaggi, fonti di debito/credito per singola voce,
  esclusioni con motivo, scadenza statutaria e risolta. Validazione umana
  (`fiscal:validate`) con nota obbligatoria su segnalazioni critiche.
- Ponte tesoreria **exactly-once**: una liquidazione validata crea una sola
  partita `payable` (`source_ref = vat_settlement:<periodo>`); la previsione
  di cassa non la conta mai due volte.
- Bozze F24 con ciclo umano `validation_required → validated → approved →
  exported`, righe con provenienza alla liquidazione e riferimento normativo.
  Export JSON/CSV etichettato interno/non telematico con fingerprint; nessuna
  trasmissione (ADR-021).
- Frontend: workspace `/fiscal` (Panoramica, Registro IVA, Liquidazioni con
  tracciabilità completa, F24, Scadenze, Tracciabilità e regole), sezione
  fiscale nel CFO cockpit con drill-down, colonna scadenza IVA nel Control
  hub, segnale critico `fiscal_liquidity_risk` (obbligazione validata su
  giorno a saldo proiettato negativo).
- Assistente: tool di sola lettura `get_fiscal_position`,
  `get_fiscal_deadlines`, `get_f24_drafts` backed dallo snapshot
  deterministico; rifiuto su richieste di calcolo e su aree fuori perimetro
  (acconto IVA, 4° trimestre, dichiarazione, rimborsi, compensazioni, regimi
  speciali).
- Seed sandbox: scenario fiscale deterministico (luglio scaduto, agosto in
  scadenza, settembre scoperto in previsione, ottobre con voce da verificare).
- Nuovi endpoint: `GET /fiscal/rule-sets`, `POST /fiscal/rule-sets/sync`,
  `GET/POST /fiscal/companies/{id}/vat-entries`, `POST …/import`,
  `POST …/from-invoices`, `POST …/{entry_id}/confirm`,
  `POST …/settlements/calculate`, `GET …/settlements`,
  `GET …/settlements/{id}`, `POST …/{id}/validate`, `GET …/deadlines`,
  `POST …/f24/generate`, `GET …/f24/{id}`, `POST …/f24/{id}/validate|approve|export`,
  `GET …/snapshot`.

### Added — Margine di contribuzione, break-even e centri di costo (2026-09-14)

Stato: **FUNCTIONAL**. Risponde al requisito «controllo di gestione che abbia
come obiettivo fare utili» restando fedele al principio che un numero
parziale non si presenta come risultato.

- `management_categories` acquisisce `cost_nature` (`fixed`/`variable`,
  nullable) e `cost_center_id`; `cost_centers` acquisisce `is_active`
  (disattivazione invece di cancellazione). La classificazione è dato di
  riferimento **modificabile**: i consuntivi restano append-only e gli
  indicatori sono derivati alla lettura, così riclassificare non riscrive la
  storia e l'audit registra chi ha cambiato cosa (ADR-019).
- Motore `contribution-v1.0`: costi variabili e fissi, margine di
  contribuzione e sua percentuale, indice di margine, ricavi di break-even,
  copertura del pareggio e ripartizione per centro di costo (con voce
  esplicita «non attribuiti»). Rifiuti dichiarati: con anche una sola
  categoria di costo non classificata i totali sono `null` e lo stato è
  `not_calculable` con l'elenco delle categorie mancanti; con indice di
  margine non positivo il break-even non esiste; senza costi fissi la
  copertura è dichiarata non significativa.
- Nuovi endpoint: `GET/POST /management/companies/{id}/cost-centers`,
  `GET /management/companies/{id}/categories`,
  `PATCH /management/companies/{id}/categories/{category_id}` (classifica o
  azzera, audita), `GET /management/companies/{id}/contribution`.
- Cockpit e hub includono i segnali `break_even_not_reached` (warning) e
  `costs_unclassified` (info) e riportano margine di contribuzione e
  break-even per azienda.
- Frontend: card «Margine di contribuzione e break-even» con ripartizione per
  centro di costo, editor di classificazione fisso/variabile con assegnazione
  del centro, creazione centri di costo; il CFO cockpit mostra gli stessi
  indicatori con le rispettive formule.
- Migrazione `241a5cddffba` reversibile in batch mode (ALTER su PostgreSQL,
  copia tabella su SQLite) così FK e CHECK esistono su entrambi i dialetti.
- Seed demo: costo fisso di struttura, due centri di costo e classificazione,
  tutti con chiavi idempotenti proprie (funzionano anche su database già
  popolati); 8 nuovi test (94 totali verdi).

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
