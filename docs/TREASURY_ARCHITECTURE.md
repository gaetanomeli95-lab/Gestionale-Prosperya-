# TREASURY_ARCHITECTURE — scadenzario, banca, riconciliazione, cassa

Stato di maturità (vedi §7 per la definizione): **FUNCTIONAL** per scadenzario,
riconciliazione L1/L2, posizione e previsione di cassa; **SANDBOX** per la
connessione bancaria; **DESIGNED** per il triage AI di livello 3 e per
l'ingestione delle fatture elettroniche dell'azienda gestita.

Modulo: `backend/app/modules/treasury/`. Consumatori: `cockpit` (hub e CFO
cockpit), `assistant` (tool di sola lettura).

## 1. La catena canonica del dato finanziario

Il requisito è che ogni numero derivato sappia rispondere a *da dove viene*.
La catena implementata è:

```
documento (fattura / registrazione manuale / import)
  → open_item            quanto è dovuto, da chi, entro quando
  → bank_transaction     cosa si è effettivamente mosso sul conto
  → reconciliation_allocation   quale movimento chiude quale partita, con quale metodo e prova
  → posizione di cassa · scadenzario · previsione · warning
```

Tabelle (tutte con `tenant_id` + `company_id` non nullable):

| Tabella | Ruolo | Mutabilità |
|---|---|---|
| `bank_accounts` | conto del cliente + saldo noto e sua provenienza | mutabile (saldo/sync sono snapshot) |
| `bank_transactions` | movimento bancario, importo **con segno** | **append-only** |
| `open_items` | partita a credito/debito con scadenza | **append-only** |
| `reconciliation_allocations` | legame movimento ↔ partita con evidenze | **append-only** |
| `bank_sync_batches` | esito di ogni refresh da provider | **append-only** |

Non si memorizza mai ciò che è derivabile: **residuo, incassato e stato della
partita sono calcolati dalle allocazioni** (`service.item_state`), così ogni
numero è ricostruibile dalle sue fonti. Un dato errato non si corregge
modificando la riga: si chiude con un'allocazione `cancellation` (partita
sbagliata) o `write_off` (credito inesigibile), con attore e motivazione
obbligatoria.

### Convenzione di scope (ADR-016)

`company_id` identifica l'azienda **soggetto** del ledger, la stessa chiave
usata da `management`: il cockpit unisce economia e cassa senza duplicare
anagrafiche. Le fatture emesse dal workspace verso quell'azienda diventano
partite `payable` (`source="invoice"`), perché dal ledger dell'azienda sono un
debito. L'ingestione delle fatture **attive e passive proprie** dell'azienda
gestita (XML/SdI) non è implementata: oggi lo scadenzario arriva da import
idempotente o inserimento manuale, e l'API lo dichiara in `limitations`.

## 2. Astrazione bancaria (nessun vincolo a un PSD2 specifico)

`providers/base.py` definisce `BankingProvider`: `connect_account`,
`refresh_accounts`, `get_balances`, `refresh_transactions`,
`connection_status`, `revoke_connection`. Il dominio parla **solo** con questa
interfaccia; forme dei payload, consensi e autenticazioni restano negli
adapter, versionati per API (`key/api_version`) e risolti dal registro
(`providers/registry.py`) — mai con `if provider == "..."`.

Deliberatamente **sola lettura (AIS)**: nessuna iniziazione di pagamenti.
Muovere denaro è un'azione irreversibile legalmente sensibile e resta fuori
perimetro (MASTER_SPEC §3.1).

Adapter inclusi:

- `manual/v1` — conti alimentati a mano o da file: declina ogni operazione
  remota invece di finta riuscita;
- `sandbox-openbanking/v1` — simulatore **deterministico** (scriptabile) che
  rifiuta l'ambiente `production`.

Entrambi dichiarano `capabilities.is_real_institution = False` e ogni batch di
sync registra `environment="sandbox"`: l'interfaccia etichetta i movimenti
come simulati e non può presentarli come dati di produzione. Gli adapter reali
(GoCardless/Nordigen, Tink, Yapily, flussi CBI) si aggiungono come moduli
versionati senza toccare il dominio. I segreti non stanno mai in database:
`credentials_ref` è il **nome** di una variabile d'ambiente/segreto.

Idempotenza del sync su due livelli: `provider_tx_id` unico per conto (lo
stesso movimento non entra due volte) e `idempotency_key` unica per batch
(ripetere una chiave restituisce il batch originale).

## 3. Motore di riconciliazione

`matching.py` è composto da funzioni **pure**: nessun DB, nessuna AI, nessuna
casualità. Gli stessi input producono gli stessi suggerimenti — proprietà
verificata da un test di riproducibilità.

| Livello | Regola | Confidenza | Applicazione |
|---|---|---|---|
| **L1 esatto** | residuo == movimento al centesimo **e** riferimento forte verificato (numero documento, P.IVA/CF, nome controparte identico normalizzato) | `1.00` | applicabile in blocco da un operatore se il candidato è unico |
| **L1 cumulativo** | un movimento chiude più partite della stessa controparte la cui somma dei residui è esatta (ricerca subset limitata e deterministica) | `1.00` | come sopra |
| **L2 punteggio** | somma pesata di: importo (identico 0.50 / entro tolleranza 0.35), vicinanza alla scadenza (0.25 / 0.15 / 0.05), similarità nome (0.25 / 0.15), riferimento parziale (0.20); soglia 0.60 | `< 1.00` | **sempre** approvazione umana puntuale |
| **L3 triage AI** | analisi dei movimenti residui | — | **DESIGNED, non implementato** |

Normalizzazioni: accenti e punteggiatura rimossi, forme giuridiche italiane
(`S.r.l.`, `SPA`, `SNC`…) eliminate dai nomi, token di riferimento con lunghezza
minima 3 per non agganciare numeri casuali. Similarità nomi con
`difflib.SequenceMatcher` (stdlib, deterministico).

Regole non negoziabili:

- il sistema **non applica nulla da sé**: `POST /reconciliation/auto-apply`
  applica solo L1 esatti e non ambigui, ed è un atto dell'operatore;
- un abbinamento L2 richiede `POST /reconciliation/apply` con il metodo
  `fuzzy`, e registra attore, confidenza, evidenze e versione del motore;
- nessuna sovra-allocazione: l'importo non può superare né il residuo della
  partita né il non allocato del movimento; il segno deve essere coerente con
  la direzione (un incasso non chiude un debito);
- i movimenti senza corrispondenza deterministica restano `unmatched` — non
  vengono indovinati.

Casi coperti: 1 movimento → N partite, N movimenti → 1 partita, pagamenti
parziali, chiusure senza movimento (write-off/annullamento), commissioni e
pagamenti fiscali non abbinabili (restano da classificare).

## 4. Motore di cassa

`analytics.py`, anch'esso puro, produce tre oggetti e i loro warning:

- **Posizione** — somma dei saldi noti dei conti attivi. Se **un solo** conto
  non ha saldo, il totale è `null`: una somma parziale sembrerebbe precisa e
  sarebbe falsa. Riporta la data del saldo più vecchio (`staleness_days`).
- **Scadenzario (aging)** — residui per direzione e fasce di ritardo
  (`current`, 1–30, 31–60, 61–90, 90+), con l'elenco degli scaduti.
- **Previsione** — proiezione giorno per giorno su **sole obbligazioni datate
  reali** (partite aperte) più il saldo iniziale noto. Nessun trend, nessuna
  stagionalità, nessun costo ricorrente inventato.

Ogni previsione separa esplicitamente:

- `facts` — residui e scadenze contrattuali, saldo bancario alla data;
- `assumptions` — «ogni partita è incassata/pagata alla scadenza», «le partite
  già scadute **non** sono considerate incassate e restano escluse», «IVA, F24,
  stipendi e rate non sono modellati se non presenti come partite»;
- `formulas` + `formula_version` — riproducibilità del calcolo.

Se il saldo iniziale non è noto, i flussi restano calcolabili e i **saldi
proiettati sono `null`**: mai zero.

### Warning deterministici

| Codice | Severità | Significato |
|---|---|---|
| `cash_forecast_negative` | critical | data in cui il saldo proiettato scende sotto zero |
| `overdue_receivables` / `overdue_payables` | warning | scaduto oltre soglia, con ritardo massimo |
| `unreconciled_backlog` | warning | movimenti non allocati da ≥ 10 giorni: indicatori incompleti |
| `bank_feed_stale` | warning | saldo più vecchio di 3 giorni |
| `cash_position_unknown` | warning | posizione non determinabile (manca un saldo o un conto) |
| `treasury_not_configured` | info | nessun conto e nessuna partita: gap di setup, non un problema finanziario |
| `sandbox_bank_data` | info | i movimenti provengono da un provider simulato |

Non esiste uno stato "verde" per assenza di dati: senza fonti lo stato è
`not_calculable` con la ragione.

## 5. Hub e CFO cockpit

`modules/cockpit` non possiede tabelle: compone `management` (economia),
`treasury` (cassa) e `opportunities` (commerciale) in due viste.

- `GET /cockpit/hub` — una riga per azienda con `attention_score` e un
  **action center** ordinato: risponde a «quale azienda guardo per prima, e
  perché». Nessun consolidato: le aziende non vengono sommate.
- `GET /cockpit/companies/{id}` — cockpit della singola azienda.

La priorità è deterministica e documentata:
`peso(severità) + peso(categoria) + 20 se richiede azione umana`, con
tie-break alfabetico (`cockpit-priority-v1.0`). La cassa pesa più del margine,
la qualità del dato non supera mai un problema reale ma non viene nascosta.

Ogni segnale porta `formula`, `formula_version`, `evidence` e
`action_required`: l'AI può spiegarlo, non può crearlo né riordinarlo.

## 6. Superficie AI

`assistant` guadagna quattro tool in sola lettura sullo snapshot verificato:
`get_cash_position`, `get_cash_forecast`, `get_receivables_aging`,
`get_reconciliation_status`. Gli item tipizzati si estendono con `WARNING` e
`ACTION_REQUIRED`. Il provider resta `local-deterministic-mock` e lo dichiara;
nessun importo è prodotto dal modello linguistico e le domande su IVA, F24,
imposte, payroll o bandi ricevono una limitazione esplicita invece di una
risposta inventata.

## 7. Stati di maturità usati in questo documento

- **DESIGNED** — progettato e documentato, nessun codice.
- **SCAFFOLDED** — struttura presente, comportamento incompleto.
- **SANDBOX** — funziona solo con adapter simulati, etichettati come tali.
- **PARTIAL** — utile in produzione su un sottoinsieme dei casi.
- **FUNCTIONAL** — flusso completo end-to-end con test.
- **PRODUCTION-READY** — in più: hardening, integrazione reale verificata,
  backup/ripristino provati.

## 8. Limiti dichiarati (da non spacciare per implementati)

- Nessuna connessione a un istituto reale: solo adapter `manual` e `sandbox`.
- Nessuna iniziazione di pagamenti (per scelta architetturale).
- Nessuna ingestione XML/SdI delle fatture proprie dell'azienda gestita.
- Nessun calcolo fiscale (IVA, IRES/IRAP, F24) né payroll: gli importi
  corrispondenti esistono solo come partite inserite a mano.
- Livello 3 di riconciliazione (AI) non implementato.
- Il residuo di una partita non riconciliata resta nei flussi futuri anche se
  l'incasso è già arrivato in banca ma non ancora allocato: per questo esiste
  il warning `unreconciled_backlog`.
