# Architecture Decisions (ADR log)

## ADR-001 — Modular monolith

Single FastAPI app organized in `app/modules/<domain>` (models / schemas /
service / router). Extraction path is preserved by module boundaries and a
provider/registry pattern; microservice complexity deferred until an actual
operational need exists.

## ADR-002 — PostgreSQL 16+ with psycopg; SQLite dev fallback

Production target is current stable PostgreSQL via `psycopg` driver. The dev
machine lacks Docker/PostgreSQL, so `DATABASE_URL` supports
`sqlite:///./dev.db` for local runs and tests. Portable constructs only
(JSON instead of ARRAY/JSONB, portable UUID type). CI should additionally
run the suite against Postgres in docker-compose.

## ADR-003 — Synchronous SQLAlchemy 2.x

Sync sessions keep the domain simple; FastAPI runs handlers in a threadpool.
Revisit only if measured contention requires async.

## ADR-004 — JWT access token now; refresh cookie later

Bearer JWT (HS256, `JWT_SECRET`) returned by `/auth/login`. Deliberate
deferral: httpOnly refresh-cookie rotation, CSRF token and login rate
limiting are scheduled before production. Tracked as a security backlog item.

## ADR-005 — Soft delete + optimistic concurrency

Core entities carry `deleted_at` and `version`. Deletes are archives;
writes require the version the client read (409 `stale_version` otherwise).

## ADR-006 — Custom Prosperya design system, no UI kit

Tokens in `frontend/src/design-system/tokens.css` derived from prosperya.it
(petrol `#315f67`, champagne `#c9b991`, ivory surfaces, dark `#172326`
chrome, Playfair Display + DM Sans). Full control, no framework lock-in.

## ADR-007 — Activity timeline ≠ audit log

`activity_events` = user-facing business narrative. `audit_log` = security
trail with field-level before/after. Separate tables, separate retention
policies possible.

## ADR-008 — Imports via staging, never direct

11-step pipeline (see `docs/IMPORT_STRATEGY.md`): upload → staging → mapping
→ normalize → validate → dedupe → preview → errors → confirm → apply →
audit. Idempotent, provenance-stamped, reversible.

## ADR-009 — Billing is provider-independent (2026-09-13)

Invoices live in Prosperya's DB; providers are transport channels behind
`BillingProvider` + a central registry (`provider_key/api_version`).
Normalized internal state machine; raw provider codes preserved;
`submission_key` idempotency; `transmission_unknown` blocks blind retries;
transactional outbox for sends; webhook ingestion deduped by provider event
id; provider secrets referenced by env-var name only. See
`docs/BILLING_ARCHITECTURE.md`.

## ADR-010 — Stub provider only, no real connector yet

`stub-sandbox/v1` exercises the contract end-to-end (config, health,
idempotent submit, timeout→unknown→reconcile, webhooks) and refuses
`production`. Real adapters (Aruba, Fatture in Cloud, TeamSystem, direct
SdI) land as versioned modules after official docs are verified.

## ADR-011 — Multi-tenant by `tenant_id`, not separate databases (2026-09-14)

The product is a SaaS sold to client companies (S.r.l.), operated by the
consultancy. Isolation is logical: every tenant-owned table carries a
non-nullable `tenant_id` FK; every read/write path filters on the active
tenant context injected by the `tenant` dependency. Staff roles
(admin/consultant/backoffice) may switch tenant context; client roles are
locked to their own tenant. Rejected alternatives: schema-per-tenant and
DB-per-tenant (operationally heavy, no benefit at this scale);
PG Row-Level Security alone (SQLite-incompatible; may be added later as
defence-in-depth on top of explicit filtering).

## ADR-012 — "Prosperya" is a theme/codename, not the product (2026-09-14)

Product will be marketed under a different name and possibly white-labelled.
`APP_NAME` env var + token-level theming keep naming out of code paths.
Default theme remains the Prosperya-derived palette.

## ADR-013 — Management dataset, not general-ledger accounting (2026-09-14)

Ported from the abandoned prototype (`PROGRAMMA PROSPERYA` v0). Consuntivi are
normalised management rows (`revenue`/`cost`, category, date, amount); the
"risultato gestionale disponibile" is `ricavi − costi` over *available*
rows. It is explicitly **not** EBITDA, utile civilistico, or cash: invoices and
monthly aggregates do not prove competenza economica, ratei, risconti,
ammortamenti, or completeness. Every overview carries `quality`
(`covered_months`, `certified_complete=false`, `issues[]`) and `trace`
(`formula_version`, `source_ids`, `budget_version_ids`). Missing evidence is
`null`, never `0`. Rejected: labelling the figure EBITDA/utile to look
familiar to clients — false precision is worse than a missing number.

## ADR-014 — Append-only financial history, idempotent imports (2026-09-14)

`import_batches`, `actuals`, `budget_versions` reject UPDATE/DELETE at the
ORM (`before_update`/`before_delete` listeners). Budgets are versioned per
(company, year, month); reads pick the latest version. CSV import is bounded
(1 MiB / 5000 rows), atomic (`begin_nested` + company row lock), idempotent
(`idempotency_key` + `payload_hash`: same → replay, different → 409), and
duplicate-safe (`source_id` + `source_hash`: same content ignored, different
content → 409). On PostgreSQL the same guarantees are to be enforced with
`BEFORE UPDATE OR DELETE` triggers and a non-owner runtime role (see the
prototype's `0001_security.sql` — kept as blueprint for the PG hardening
migration in Phase 5).

## ADR-015 — Deterministic assistant with typed items (2026-09-14)

Ported from the prototype. `assistant` exposes an `AIProvider` Protocol whose
only job is `select_tools(message) → ProviderPlan`. The plan is validated
against an allow-list (`get_financial_summary`, `get_monthly_trend`,
`get_budget_variance`, `get_cost_breakdown`, `get_data_quality`,
`get_source_trace`); tools cannot change the selected period and re-check
tenant/company ownership. All arithmetic (incl. the revenue scenario engine)
is Decimal Python — the provider never computes. Answers are lists of
`{type: FACT|CALCULATION|ASSUMPTION|SUGGESTION, text}` plus `tools_used`,
`evidence` and `limitations`. The shipped provider is
`local-deterministic-mock` and says so in every response; a real LLM
provider (ADR-004/06 of `AI_ARCHITECTURE.md`) plugs into the same Protocol
later without touching tools or rendering. Rejected: agentic frameworks and
vector DBs at this stage — no requirement justifies them.

## ADR-016 — Catena finanziaria canonica in `treasury` (2026-09-14)

Requisito del committente: controllo di gestione, allineamento bancario e
tesoreria su molte S.r.l. da un unico ambiente. Invece di numeri duplicati per
modulo, il dato finanziario segue una sola catena tracciabile:
`documento → open_item → bank_transaction → reconciliation_allocation →
posizione/previsione/warning` (vedi `docs/TREASURY_ARCHITECTURE.md`).

Decisioni vincolanti:

- **Scope `(tenant_id, company_id)`** con `company_id` = azienda *soggetto*,
  la stessa chiave di `management`: il cockpit unisce economia e cassa senza
  duplicare anagrafiche. Ambiguità risolta esplicitamente: le fatture emesse
  dal workspace verso l'azienda diventano partite `payable`; l'ingestione
  XML/SdI delle fatture proprie dell'azienda è DESIGNED, non implementata, e
  l'API lo dichiara in `limitations`.
- **Append-only** su `bank_transactions`, `open_items`,
  `reconciliation_allocations`, `bank_sync_batches` (listener ORM come
  ADR-014). Le correzioni sono nuove allocazioni `cancellation`/`write_off`
  con attore e motivazione obbligatoria.
- **Derivato, non memorizzato**: residuo, incassato e stato partita si
  calcolano dalle allocazioni, così ogni numero è ricostruibile.
- `invoices.due_date` aggiunto (nullable): senza scadenza nota la tesoreria
  **non** genera partite e riporta il documento come scartato, invece di
  inventare una data.
- Primitivi monetari unificati in `app/shared/money.py` (Decimal dentro,
  stringhe decimali sul filo, `None` per dato assente); `management` li
  re-esporta per non spezzare i chiamanti.

Respinto: tabelle separate per crediti e debiti (stessa semantica, doppio
codice); saldi "parziali" quando manca il saldo di un conto (falsa precisione).

## ADR-017 — Banking in sola lettura, riconciliazione deterministica con approvazione umana (2026-09-14)

`BankingProvider` (AIS: conti, saldi, movimenti) con registro versionato
`key/api_version`, adapter `manual/v1` e `sandbox-openbanking/v1`
(deterministico, rifiuta `production`, `is_real_institution=False`). Nessuna
iniziazione di pagamenti: azione irreversibile legalmente sensibile, fuori
perimetro. Segreti solo via `credentials_ref` (nome di env var). Sync
idempotente su `provider_tx_id` (per conto) e `idempotency_key` (per batch).

Il motore di abbinamento è **codice puro e riproducibile**: livello 1 esatto
(importo al centesimo + riferimento verificato, inclusi pagamenti cumulativi
con somma esatta) e livello 2 a punteggio pesato (importo, data, similarità
nome, riferimenti parziali, soglia 0.60). Il livello 3 assistito da AI è
DESIGNED e non implementato: i movimenti non abbinati restano `unmatched`,
mai indovinati.

Il sistema non applica nulla da sé: `auto-apply` riguarda solo i livelli 1 non
ambigui ed è un atto dell'operatore; ogni livello 2 richiede approvazione
puntuale. Ogni allocazione registra metodo, confidenza, evidenze,
`engine_version` e approvatore. Invarianti applicati: nessuna
sovra-allocazione (né sul movimento né sulla partita), coerenza di segno tra
movimento e direzione della partita.

Respinto: auto-riconciliazione "intelligente" senza revisione (rischio di
chiudere partite sbagliate in modo irreversibile); LLM come classificatore
primario dei movimenti.

## ADR-018 — Priorità del control hub deterministica e versionata (2026-09-14)

La schermata primaria del consulente è il **control hub** multi-azienda con un
action center ordinato. L'ordine è un fatto di prodotto, quindi è codice
documentato e versionato (`cockpit-priority-v1.0`):
`peso(severità) + peso(categoria) + 20 se richiede azione umana`, tie-break
alfabetico per riproducibilità. La cassa pesa più del margine; la qualità del
dato non supera mai un problema reale ma non viene nascosta; un gap di setup
è `info`, non un allarme.

Il modulo `cockpit` non possiede tabelle: compone `management`, `treasury` e
`opportunities` tramite le loro funzioni pubbliche (aggiunta
`opportunities/service.py` per non interrogare tabelle di altri moduli).
`health` ammette `not_calculable`: senza fonti non esiste un verde. L'AI può
spiegare i segnali, non crearli né riordinarli.

## ADR-019 — Classificazione come dato di riferimento, indicatori derivati (2026-09-14)

Giuseppe chiede un controllo di gestione «che abbia come obiettivo fare
utili»: servono margine di contribuzione, break-even e centri di costo. Il
problema architetturale è che i consuntivi sono append-only (ADR-014) e la
classificazione dei costi cambia nel tempo.

Decisione: la classificazione vive su `management_categories`
(`cost_nature` ∈ {fixed, variable} nullable, `cost_center_id`), **non** sulle
righe di consuntivo. Margine di contribuzione, break-even e ripartizione per
centro di costo sono **derivati al momento della lettura**: riclassificare non
riscrive la storia, l'audit registra chi ha cambiato cosa, e i vecchi numeri
restano ricostruibili dalla coppia (fonti, classificazione corrente).

Rifiuti deliberati:

- con **anche una sola** categoria di costo non classificata, costi
  variabili e fissi sono `null` e lo stato è `not_calculable` con l'elenco
  delle categorie mancanti: una ripartizione parziale sottostimerebbe i costi
  sembrando precisa;
- `cost_nature` resta nullable perché *non classificato* è uno stato reale;
- se l'indice di margine non è positivo il break-even **non esiste** e viene
  detto, invece di produrre un numero rassicurante;
- se non ci sono costi fissi il break-even è 0 e la copertura è dichiarata non
  significativa anziché mostrata come rapporto.

Il motore ha la sua `formula_version` (`contribution-v1.0`) e le formule sono
esposte nella risposta. Il cockpit mappa `break_even_not_reached` (warning) e
`costs_unclassified` (info) come segnali deterministici.

Respinto: dedurre la natura del costo dal nome della categoria (euristica
invisibile); scrivere la classificazione sugli `actuals` (renderebbe la
riclassificazione una riscrittura di storia).

## ADR-020 — Motore fiscale a regole versionate e effective-dated (2026-09-15)

La liquidazione IVA è un numero legalmente sensibile: deve poter rispondere a
«quale regola, in quale versione, su quali dati ha prodotto questo importo».

Decisione: le regole fiscali non vivono nel codice ma in `fiscal_rule_sets`,
tabelle versionate con `effective_from/to`, stato e fonte autorevole completa
(authority, URL, data di rilevamento, fingerprint, riferimento normativo). Il
motore puro (`fiscal/rules.py`, nessun I/O) riceve il payload del rule set
vigente alla data di competenza e calcola; il rule-set id e la versione della
formula sono registrati sulla liquidazione.

Conseguenze deliberate:

- **nessuna regola applicabile → nessun calcolo** (`no_applicable_rule_set`),
  mai un fallback silenzioso sui valori correnti;
- un cambio normativo arriva come nuova versione del rule set: le versioni
  esistenti non si modificano, così una liquidazione del 2026 resta
  riproducibile con le regole del 2026 anche dopo un aggiornamento;
- il perimetro supportato è dichiarato nel payload (`supported_cases` /
  `unsupported_cases`) e riportato a UI e AI: 4° trimestre, acconto IVA,
  dichiarazione, rimborsi, compensazioni e regimi speciali sono rifiutati, non
  stimati;
- il registro IVA è append-only: la verifica umana di una voce dubbia è una
  nuova voce `system_derived` che la sostituisce, non una modifica;
- la liquidazione è versionata: il ricalcolo supersede, non sovrascrive;
- solo l'umano valida (`fiscal:validate`); con segnalazioni critiche servono
  `acknowledge_warnings` e nota obbligatoria.

Respinto: regole hard-coded con flag per anno (non spiega la fonte); calcolo
assistito dall'AI (viola la catena non negoziabile); edit in place delle voci
IVA (distrugge la provenienza).

## ADR-021 — Bozza F24 interna, confine esplicito con il telematico (2026-09-15)

Il modulo produce **bozze F24 interne** per revisione: righe con codice
tributo, sezione, periodo/anno di riferimento, importi e provenienza
(`origin_settlement_id`, riferimento normativo, spiegazione testuale). Ciclo di
vita umano: `validation_required → validated → approved → exported`.

Decisione sul confine:

- l'export JSON/CSV è un **documento interno di lavoro**, non un tracciato
  telematico: nessun record layout Entratel/CBI è implementato né verificato
  contro la specifica ufficiale corrente;
- ogni export porta fingerprint SHA-256 e il disclaimer `Bozza interna - non
  trasmissibile` nell'header HTTP; la UI etichetta gli export come interni;
- **nessuna trasmissione**: la presentazione dell'F24 resta al cliente o al
  suo intermediario; la piattaforma non agisce mai per loro conto;
- la generazione richiede una liquidazione **validata** con importo a debito:
  un documento fiscale non esce da un numero che un umano non ha approvato;
- la generazione è idempotente per liquidazione: rigenerare non produce
  duplicati né doppie partite di tesoreria.

Respinto: generare un file "compatibile F24" senza validazione ufficiale del
tracciato (un formato quasi-giusto è peggio di nessun formato); trasmissione
automatica (fuori perimetro legale e di prodotto).

## Open decisions

- Refresh-token strategy + session UX (ADR-004 follow-up).
- FatturaPA XML: generated in-house vs provider-generated — decide at provider selection.
- Job queue tech for outbox dispatch (function now; worker/scheduler later).
- Object storage choice for documents (Phase 2).
- Growth Factors framework configuration model (Phase 4).
