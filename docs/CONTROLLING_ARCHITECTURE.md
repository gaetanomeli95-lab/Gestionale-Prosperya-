# CONTROLLING_ARCHITECTURE — servizio del debito, early warning CCII, scenari

Stato di maturità: **FUNCTIONAL** per anagrafica debito, rate pianificate,
metriche deterministiche (DSCR prospettico, continuità 12 mesi, margine di
sicurezza, trend), regole early-warning versionate, alert durevoli con ciclo
di vita umano e scenari bounded. **NOT IMPLEMENTED** per la determinazione
dello stato di crisi (fuori perimetro: spetta agli organi competenti) e per
l'integrazione con banche dati esterne (Cerved, Camere di Commercio).

Modulo: `backend/app/modules/controlling/`. Consumatori: `cockpit` (hub e
CFO cockpit leggono gli alert persistiti). Frontend: workspace dedicato in
roadmap.

## 1. La catena non negoziabile

```
fonte autorevole (Normattiva / CCII, con URL + data di verifica)
  → early_warning_rules          regole versionate, effective-dated
  → fatti canonici               open_items (residui), debt_service_lines,
                                 obbligazioni fiscali validate, saldi noti
  → metrics.py / ew.py           motori puri, nessun I/O
  → POST /alerts/evaluate        detection = scrittura esplicita
  → controlling_alerts           alert durevole, dedupe_key, ciclo umano
  → cockpit / hub                sola lettura degli alert persistiti
```

Ogni importo è una stringa decimale o `null`. `fired`, `not_fired`,
`insufficient_data` e `unsupported` sono stati distinti: una regola che non
può verificarsi non è una regola che non è scattata.

## 2. Servizio del debito (non è tesoreria)

`debt_facilities` (mutuo, finanziamento, leasing, fido pianificato) è dato di
riferimento mutabile come le categorie gestionali. `debt_service_lines` è la
rata pianificata: `scheduled → paid | waived` con transizioni tracciate
(`settled_on`, `status_note` obbligatoria per la sospensione).

Una rata **non** è un `open_item`: è un fatto contrattuale, non una partita
commerciale. Entra nei flussi dei motori come `nature='debt_service'` senza
doppio conteggio con lo scadenzario.

## 3. Metriche deterministiche (`metrics.py`)

| Metrica | Formula | Onestà |
|---|---|---|
| DSCR prospettico | (incassi − pagamenti su partite aperte) / rate in scadenza, orizzonte 365gg | denominatore assente → `not_applicable`; numeratore non osservabile → `insufficient_data`; copertura < 50% → `partial` |
| Continuità 12 mesi | saldo noto + flussi datati cumulati per mese | saldo ignoto → proiezioni `null`, `runway_status='not_calculable'` |
| Margine di sicurezza | (ricavi − break-even) / ricavi | break-even non calcolabile → `insufficient_data` |
| Trend | confronto con finestra precedente esplicita | baseline assente → `no_baseline` |

Ogni risultato porta `formulas`, `formula_version`, `engine_version`,
`assumptions` e gli id delle fonti (`source_ids`, `debt_line_ids`).

## 4. Regole early-warning (`ew.py`, ADR-022)

Sei regole seed, effective-dated dal 2026-01-01, categoria `ccii_legal` o
`organizational`:

| Codice | Condizione | Severità |
|---|---|---|
| `EW-FIN-OVERDUE` | rate o partite finanziarie scadute | critical |
| `EW-PAYROLL-OVERDUE` | debiti personale/previdenziali scaduti ≥ soglia | critical |
| `EW-SUPPLIER-OVERDUE` | quota debiti commerciali scaduti ≥ soglia % | warning |
| `EW-PUBLIC-CREDITOR` | obbligazioni fiscali validate scadute ≥ soglia | critical |
| `EW-DSCR-12M` | DSCR prospettico < soglia operativa | warning |
| `EW-CONTINUITY-12M` | saldo proiettato < 0 entro 365 giorni | critical |

Ogni parametro dichiara `kind: statutory | operational`. Le soglie correnti
sono **tutte operative**: nessun valore è presentato come di legge senza
verifica sul testo vigente. `data_requirements` dichiara quali fonti servono;
se il tipo di dato non esiste → `unsupported`.

## 5. Alert durevoli

`controlling_alerts` persiste l'esito della detection con `dedupe_key` =
codice regola: la riesecuzione aggiorna evidenza e `detected_at` dello stesso
alert, mai duplicati. Ciclo di vita:

```
open → acknowledged → resolved | dismissed
         ↑ condizione rientrata → resolved (resolution_kind='auto')
         ↑ condizione di nuovo vera dopo resolve/dismiss → reopen
           (la decisione umana precedente resta in evidence)
```

`dismiss` richiede motivazione obbligatoria; ogni transizione è auditata.
Il cockpit legge solo `open`/`acknowledged`: la detection resta una
scrittura dietro `controlling:write`.

## 6. Scenari (`scenarios.py`)

`BASE` / `STRESS` / `UPSIDE` / custom con bound dichiarati (`BOUNDS`). Le
ipotesi trasformano **copie** dei fatti: ritardo incassi e fornitori
spostano le date, delta su ricavi/costi variabili/servizio del debito
riscala gli importi, `fixed_cost_monthly_delta` aggiunge righe esplicite
`source='scenario_assumption'`. Stessi motori, stesse formule: l'output
ripete le ipotesi verbatim. I consuntivi storici non sono mai toccati.

## 7. API

| Endpoint | Scope | Note |
|---|---|---|
| `GET /controlling/rules` | `controlling:read` | regole vigenti con fonti |
| `POST /controlling/rules/sync` | `controlling:admin` | idempotente, mai edit in place |
| `GET/POST …/facilities`, `PATCH …/facilities/{id}` | read/write | anagrafica debito |
| `POST …/facilities/{id}/instalments` | write | rata pianificata |
| `POST …/instalments/{id}/settle` | write | `paid`/`waived` tracciati |
| `GET …/snapshot` | read | metriche + valutazioni live + alert |
| `POST …/alerts/evaluate` | write | detection idempotente |
| `GET …/alerts`, `POST …/alerts/{id}/acknowledge|resolve|dismiss` | read/write | ciclo umano |
| `GET …/scenarios/presets`, `POST …/scenarios/run` | read | ricalcolo, nessuna scrittura |

## 8. Seed sandbox

`_seed_controlling` (deterministico, idempotente, date relative a oggi):
mutuo con 2 rate pagate, 1 scaduta (→ `EW-FIN-OVERDUE` critical) e 6 future;
leasing trimestrale; una detection iniziale per rendere visibile il ciclo
degli alert.

## 9. Frontend (`/controlling`)

Workspace a 7 tab (`ControllingPage.tsx` + `controlling/{shared,sections,scenarios}.tsx`):
Panoramica, Redditività, Liquidità & continuità 12 mesi, Debito & DSCR,
Early Warning, Scenari, Data Quality. Regole UX vincolanti:

- `insufficient_data` / `not_applicable` / `partial` sono stati di primo
  livello: mai resi come €0, sempre con ragione esplicita.
- Drill-down DSCR: valore, orizzonte, numeratore/denominatore, versione
  formula, versione forecast, assunzioni, copertura fonti.
- Lifecycle alert con azioni umane auditabili (acknowledge / resolve /
  dismiss) e "Rivaluta segnali" solo su azione esplicita — mai detection
  silenziosa al caricamento.
- Scenari: confronto BASE vs STRESS/UPSIDE/custom con delta KPI; le
  ipotesi sono ripetute verbatim nell'output.
- Nessuna dicitura di "crisi": i segnali early-warning sono evidenze
  gestionali, non determinazioni legali.

Integrazioni: blocco compatto "Controlling & early warning" nel cockpit
CFO (`CockpitPage.tsx`) con drill-down; colonna EW + "Perché ora"
(`signal_count` + `top_signal`) nell'hub (`HubPage.tsx`). Assistant:
8 tool read-only (`get_controlling_summary`, `get_dscr`,
`get_12m_continuity`, `get_early_warning_alerts`, `get_debt_service`,
`get_scenario_comparison`, `get_controlling_data_quality`,
`get_hub_position`) — nessun ricalcolo AI, evidence obbligatoria,
`legal_notice` su domande di crisi.
