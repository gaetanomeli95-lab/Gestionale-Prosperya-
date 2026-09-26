# Prosperya UI Kit — regole vincolanti (Fase H)

Fonte di verità visiva: `frontend/src/design-system/tokens.css`, `app.css` e i componenti in
`frontend/src/components/ui.tsx`. Le pagine **compongono** il kit; non inventano classi né stili.

## Principio

**Potente sotto, semplicissimo in mano.** Ogni schermata risponde a UNA domanda, dichiarata nel
`PageHeader` (`question`). Poche azioni deliberate; dettagli secondari nascosti finché non servono
(`<details>`, `Drawer`, tab). Mai "righe di database": ogni lista dice *perché* una riga conta.

## Regole hard (verificate in review)

1. **Zero `style={{…}}` inline** nelle pagine, tranne `width` calcolate a runtime (barre/grafici).
   Usare le utility: `.stack .cluster .grid-auto .grid-2-1 .grid-1-2 .mt-* .mb-* .text-xs .right .strong .muted .truncate .nowrap .w-full`.
2. **Zero stringhe di stato in inglese** a schermo: `StatusBadge`, `statusLabel()`, `Dot` o mappe locali in italiano.
3. **Zero `<Spinner/>` a pagina intera** dove esiste layout: usare `Skeleton` (`kind="stats" | "table" | "lines"`) al posto del contenuto che sta caricando.
4. **Ogni pagina** inizia con `PageHeader` (eyebrow = sezione, title, `question`, `actions`). Le pagine principali (Hub, Panoramica, Cockpit, Fisco, Controlling, Funding, Pratiche, Documenti, Tesoreria, Fatturazione) usano `hero`.
5. **Numeri**: sempre `.num` / `.td--num` / `.th--num` (tabulari, a destra). Valori assenti → `<NA/>`, mai `0` finto. Negativo `.neg`, positivo `.pos`.
6. **Card**: `Section` (title/actions/footer) per i blocchi; `Stat` per i KPI (un solo `hero` per pagina); `Tile` per fatti densi; `Row`/`.rows` per liste ricche; `KV` per coppie chiave/valore; `Progress` per copertura/avanzamento.
7. **Tabelle**: dentro `Section flush` con `table table--flush`; prima colonna con `.table__primary` + `.table__sub`; intestazioni numeriche `.th--num`. Tabelle non cliccabili → `table--static`.
8. **Feedback**: `Callout` (info/warning/danger/success/neutral) al posto di `.alert`; `toast("…")` dopo ogni mutazione riuscita; `ErrorBanner` per errori API.
9. **Overlay**: `Modal` (title, subtitle, size) per creare/confermare; `Drawer` per vedere dettagli senza lasciare la pagina.
10. **Tab**: componente `Tabs` con `count` (e `tone` danger/warning quando il conteggio è un problema).
11. **Vuoti**: `EmptyState` con `title`, testo utile e `action` (cosa fare adesso).
12. **Bottoni**: una sola azione primaria per vista (`btn--primary`), il resto `btn--ghost`/`btn--sm`; azioni distruttive `btn--danger` con conferma.
13. **Form**: `Field` (label associata, hint, error con `role="alert"`), `.form-grid` + `.span-2`, sezioni con `.form-section` / `.form-section__title`, checkbox con `.check`.
14. **Accessibilità**: heading `h1` unico per pagina; `aria-label` su select/filtri senza label visibile; tab con `role="tab"` + `aria-selected`; righe cliccabili con tastiera.
15. **Testo UI in italiano**, codici/API in inglese. Tono: sobrio, preciso, mai gergo tecnico (niente id, niente `snake_case`, niente nomi di formula in vista primaria — vanno in tooltip/`<details>`).

## Anatomia standard di una pagina

```tsx
<PageHeader hero eyebrow="Finanza e fisco" title="Tesoreria"
  question="Quanta cassa ho, quando finisce, e cosa devo incassare o pagare prima." actions={…} />
<div className="stat-grid">  <Stat hero …/> <Stat …/> <Stat …/> <Stat …/> </div>
<div className="grid-2-1">
  <Section title="Da fare ora" actions={…}> <div className="rows">…<Row …/></div> </Section>
  <Section title="Dettaglio"> <KV columns={1} items={…}/> </Section>
</div>
<Section title="Movimenti" flush> <table className="table table--flush">…</table> </Section>
<details className="mt-4"><summary className="eyebrow eyebrow--muted">Metodo e limitazioni</summary>…</details>
```

## Selettori protetti dai test (non cambiare testo/ruolo)

- Heading: `Aziende`, `Contatti`, `Pipeline commerciale`, `Pratiche`, `Documenti`, `/attivit/i`, `/finanza agevolata/i`, `/controlling/i`.
- Dialog: `Nuova azienda` (label `ragione sociale`, `forma giuridica`, bottone `crea azienda`), `Nuovo contatto` (label `nome`, `cognome`, `email`, `ruolo nell'azienda`, `referente principale`, bottone `Crea`), dialog `/scadenza/i` (label `titolo`, `data`, bottone `crea scadenza`).
- Bottoni: `/nuova azienda/i`, `/nuovo contatto/i`, `Crea` (pratiche), `Aggiungi scadenza a <titolo>`, `/aggiungi requisito/i`.
- Placeholder `/nuova pratica/i`; label `/cerca per nome/i` (Contatti), `Azienda` (Documenti), form `/nuovo requisito/i` con label `tipo documento`, `descrizione`, `pratica`.
- Tab: `Contatti`, `Dossier` (Company detail), `Programmi`, `Pratiche` (Funding), `Early warning`, `Scenari` (Controlling).
- Testi: `nessun contatto collegato`, `1 contatto collegato`, `Documenti mancanti (N)`, `2 anagrafiche` (span separato), columnheader `Ragione sociale`, nessun prefisso id pratica visibile.
- Login: label `/email/i`, `/password/i`, bottone `/accedi/i`.
