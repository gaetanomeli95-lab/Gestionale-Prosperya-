# FISCAL_ARCHITECTURE — registro IVA, liquidazioni, scadenze, bozze F24

Stato di maturità: **FUNCTIONAL** per registro IVA, liquidazione deterministica
mensile/trimestrale, rule set versionati, validazione umana, scadenze e bozze
F24 interne. **INTERNAL** per l'export JSON/CSV. **NOT IMPLEMENTED** per il
tracciato telematico F24 e per la trasmissione. **SANDBOX** per l'impatto sulla
cassa (la posizione bancaria arriva da un provider sandbox).

Modulo: `backend/app/modules/fiscal/`. Frontend: workspace `/fiscal`.
Consumatori: `cockpit` (hub e CFO cockpit), `assistant` (tool di sola lettura).

## 1. La catena non negoziabile

```
fonte autorevole (AdE / normativa, con URL + fingerprint + data di verifica)
  → fiscal_rule_sets + fiscal_tax_codes   regole versionate, effective-dated
  → vat_entries                           fatti IVA canonici, append-only
  → vat_settlements                       calcolo deterministico + traccia
  → validazione umana (fiscal:validate)   mai eseguibile dall'AI
  → fiscal_deadlines                      obbligazione con data statutaria/risolta
  → open_item (treasury)                  esattamente una partita di cassa
  → f24_drafts + f24_lines                documento interno, mai telematico
```

Ogni importo è una stringa decimale o `null`: **mancante, non supportato,
da verificare e zero sono stati distinti**. Nessun numero fiscale è prodotto
da un modello linguistico.

## 2. Rule set versionati (ADR-020)

`fiscal_rule_sets` porta `jurisdiction`, `rule_family`
(`vat_periodic` | `payment_calendar` | `f24_tax_codes` | `f24_format`),
`version`, `effective_from/to`, `status` e la fonte completa (authority, titolo,
URL, data di pubblicazione, data di rilevamento, fingerprint SHA-256,
riferimento normativo). Il payload JSON contiene i parametri della formula
(aliquote di riferimento, soglia di versamento, interessi trimestrali, casi
supportati e dichiarati non supportati).

La risoluzione è per data di competenza: `resolve_rule_set` sceglie la versione
vigente; **se non esiste una regola applicabile il calcolo rifiuta**
(`no_applicable_rule_set`) invece di cadere su un default. Un cambio di norma
arriva come nuova versione del rule set: le versioni esistenti non si
modificano mai (`rule-sets/sync` è idempotente, scope `fiscal:admin`).

Il motore è `rules.py` (funzioni pure, nessun I/O): `compute_settlement`,
`statutory_due_date`, `resolve_due_date` (differimenti sabato/festivi e finestra
1–20 agosto), `period_bounds`, `is_supported_period`. Versioni esposte in ogni
risposta: `fiscal-engine-v1.0`, `vat-settlement-v1.0`, `payment-calendar-v1.0`.

## 3. Registro IVA (append-only)

`vat_entries` registra direzione (`sale`/`purchase`), competenza, imponibile,
IVA, aliquota o natura, detraibilità, documento, controparte, fonte e
`source_ref` per l'idempotenza. La classificazione è *bounded*:

| Condizione | Trattamento |
|---|---|
| operazione ordinaria completa | `supported` |
| natura IVA con imposta zero | `supported` |
| acquisto con `deductible` esplicito | `supported` (indetraibile = escluso dal credito) |
| IVA assente | `insufficient_data` |
| aliquota assente senza natura | `requires_review` |
| acquisto senza detraibilità confermata | `requires_review` |
| natura con imposta non nulla | `requires_review` |

Le voci non `supported` sono **escluse dai totali ma contate e listate**: il
risultato non finge completezza. La verifica umana non modifica la voce
originale — registra un gemello `system_derived` che la sostituisce
(`reverses_entry_id`), così la storia resta integra. Le fatture del workspace
arrivano via `vat-entries/from-invoices` e nascono sempre `requires_review`
(la detraibilità non è mai assunta). L'import bulk è atomico e idempotente
per `source_ref`; uno `source_ref` esistente con contenuto diverso è un
conflitto (si registra una rettifica, non una modifica).

## 4. Liquidazione deterministica

`calculate_settlement` aggrega le voci del periodo (con le conferme che
sostituiscono gli originali), applica il riporto dal periodo precedente
(credito, debito sotto soglia), calcola posizione netta, versamento e riporti
a nuovo con `Decimal`, e scrive la traccia completa nel campo `trace`:
rule set usato, versione formula, passaggi, regole applicate, **fonti di debito
e di credito a livello di singola voce**, voci escluse con motivo, risoluzione
della scadenza.

- Esiti: `calculated` | `review_required` (se esiste una segnalazione
  warning/critical) | `validated` | `superseded`.
- Il ricalcolo crea una **nuova versione** (`version` +1) e marca la precedente
  `superseded`: niente viene sovrascritto, e la versione vecchia resta
  ispezionabile via `GET /settlements/{id}`.
- `GET /companies/{id}/settlements/{settlement_id}` restituisce il dettaglio
  completo con traccia (usato dal tab Liquidazioni del workspace).

### Validazione umana

`POST /settlements/{id}/validate` richiede lo scope `fiscal:validate`
(backoffice e AI esclusi). Con segnalazioni critiche serve
`acknowledge_warnings` **più una nota di motivazione obbligatoria**. Validare
una versione superseded è un conflitto: si valida solo l'ultima.

## 5. Scadenze

`_upsert_deadline` mantiene una scadenza per (azienda, tipo, periodo) con data
statutaria e data risolta dal calendario dei differimenti. Se il differimento
non è risolvibile con le regole note, `due_date_status = review_required`:
la data non viene inventata. Una scadenza già validata non viene riscritta dal
ricalcolo: viene cancellata e sostituita, così il legame con la tesoreria resta
tracciato.

## 6. Ponte con la tesoreria: exactly-once

Alla validazione, `sync_fiscal_liability` crea **una** partita aperta
`payable` verso "Erario — IVA periodica" con `source_ref =
vat_settlement:<period_id>`. La chiave rende l'operazione idempotente:
ri-validazione, ricalcolo, rigenerazione F24 e re-seed non duplicano mai
l'obbligazione. La previsione di cassa la conta una volta sola
(`test_validated_settlement_creates_exactly_one_treasury_item`).

## 7. Bozze F24 (ADR-021)

`POST /f24/generate` accetta solo una liquidazione **validata** con importo a
debito: codice tributo dalla tabella `fiscal_tax_codes` (es. 6001 mensile,
6031 trimestrale), sezione, anno/periodo di riferimento, e su ogni riga
`origin_settlement_id` + `rule_reference` + spiegazione testuale del calcolo.
Ciclo di vita: `generated/validation_required → validated → approved →
exported`, ogni transizione umana e permissionata.

L'export (`POST /f24/{id}/export`, formati `json`/`csv`, richiede bozza
approvata) produce un **documento interno di lavoro** con fingerprint e header
`X-Export-Disclaimer: Bozza interna - non trasmissibile`. Non è un tracciato
Entratel/CBI: la specifica tecnica ufficiale non è implementata né verificata,
e **nessun F24 viene trasmesso** — la trasmissione resta all'intermediario.

## 8. Integrazione con cockpit, hub e assistente

- `fiscal_snapshot` compone periodi, ultima liquidazione, scadenze, bozze,
  contatori, voci da verificare e warning deterministici — un'unica lettura
  condivisa da workspace, cockpit, hub e AI.
- Il cockpit aggiunge il segnale incrociato `fiscal_liquidity_risk`
  (obbligazione validata che cade su un giorno con saldo proiettato negativo):
  deterministico, formula `fiscal-engine-v1.0+treasury-forecast`.
- L'assistente ha tre tool allow-listed (`get_fiscal_position`,
  `get_fiscal_deadlines`, `get_f24_drafts`) che leggono lo snapshot; rifiuta
  richieste di calcolo ("calcola l'IVA") e aree fuori perimetro (acconto,
  4° trimestre, dichiarazione, rimborsi, compensazioni, regimi speciali).

## 9. Perimetro dichiarato (LIMITATIONS)

Supportato: liquidazione IVA mensile e trimestrale per opzione, primi tre
trimestri. **Non** calcolati: quarto trimestre, acconto di dicembre,
trimestrali speciali, IVA di gruppo, split payment, reverse charge, plafond,
regimi speciali, dichiarazione annuale, rimborsi, compensazioni. Festività
locali del santo patrono non modellate. Nessuna ingestione XML/SdI.
