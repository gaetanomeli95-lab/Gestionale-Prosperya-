import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, CalendarClock, GitMerge, RefreshCw, Upload, Wallet } from "lucide-react";
import { api, ApiError } from "../api/client";
import type {
  BankAccount, CompanyListItem, OpenItem, Page, SuggestionPlan, TreasurySnapshot,
} from "../api/types";
import {
  Badge, Callout, EmptyState, ErrorBanner, Modal, NA, PageHeader, Row, Section, Skeleton, Stat, toast,
} from "../components/ui";
import { dateIt, money } from "../lib/format";
import { ActionList } from "./HubPage";

const ITEMS_TEMPLATE = JSON.stringify(
  [{
    source_ref: "SC-2026-001", direction: "receivable",
    counterparty_name: "Cliente Esempio S.r.l.", counterparty_vat: "01234567890",
    document_number: "FT 101/2026", document_date: "2026-09-01",
    due_date: "2026-10-31", amount: "2440.00",
  }],
  null, 2,
);

/** Italian labels for open-item statuses and origins (codes stay English in the API). */
const ITEM_STATUS: Record<string, { label: string; tone: string }> = {
  open: { label: "Aperta", tone: "primary" },
  partially_settled: { label: "Parzialmente regolata", tone: "info" },
  settled: { label: "Regolata", tone: "success" },
  written_off: { label: "Stralciata", tone: "neutral" },
  cancelled: { label: "Annullata", tone: "neutral" },
};
const SOURCE_LABEL: Record<string, string> = { invoice: "Fattura", manual: "Manuale", import: "Import" };
const CONNECTION_LABEL: Record<string, { label: string; tone: string }> = {
  connected: { label: "Connesso", tone: "success" },
  healthy: { label: "Connesso", tone: "success" },
  degraded: { label: "Degradato", tone: "warning" },
  error: { label: "Errore", tone: "danger" },
  unavailable: { label: "Non disponibile", tone: "danger" },
  not_configured: { label: "Non configurato", tone: "neutral" },
  manual: { label: "Manuale", tone: "neutral" },
};

/** Decimal string or the explicit "no evidence" marker — never a fake 0. */
function Val({ v }: { v: string | null | undefined }) {
  if (v == null) return <NA />;
  return <>{money(v)}</>;
}

function Signed({ v }: { v: string | null | undefined }) {
  if (v == null) return <NA />;
  const negative = v.startsWith("-");
  return <span className={negative ? "neg" : "pos"}>{money(v)}</span>;
}

function bucketLabel(bucket: string): string {
  if (bucket === "current") return "A scadere";
  return bucket.replace("d", "").replace("_", "–").replace("plus", "+") + " giorni";
}

/** Inflow/outflow per due date over the selected horizon. Bars are display
 *  only: every amount comes from the backend as a decimal string. */
function FlowChart({ snapshot }: { snapshot: TreasurySnapshot }) {
  const rows = snapshot.forecast.daily.filter((d) => d.inflow !== "0.00" || d.outflow !== "0.00");
  const max = useMemo(
    () => Math.max(1, ...rows.map((d) => Math.max(Number(d.inflow ?? 0), Number(d.outflow ?? 0)))),
    [rows],
  );
  if (!rows.length) {
    return (
      <EmptyState title="Nessuna scadenza nell'orizzonte">
        Allunga l'orizzonte o importa lo scadenzario per vedere i flussi attesi.
      </EmptyState>
    );
  }
  return (
    <>
      <div className="bars">
        {rows.slice(0, 24).map((d) => (
          <div className="bars__col" key={d.date}>
            <div className="bars__stack">
              <div className="bars__in" style={{ height: `${(Number(d.inflow ?? 0) / max) * 100}%` }}
                   title={`Incassi attesi ${money(d.inflow)} · saldo proiettato ${money(d.projected_balance)}`} />
              <div className="bars__out" style={{ height: `${(Number(d.outflow ?? 0) / max) * 100}%` }}
                   title={`Pagamenti attesi ${money(d.outflow)}`} />
            </div>
            <div className="bars__label">{d.date.slice(5)}</div>
          </div>
        ))}
      </div>
      <div className="cluster mt-3 text-xs muted">
        <span className="dot dot--primary"><i />Incassi attesi</span>
        <span className="dot dot--accent"><i />Pagamenti attesi</span>
      </div>
    </>
  );
}

export default function TreasuryPage() {
  const qc = useQueryClient();
  const [companyId, setCompanyId] = useState("");
  const [horizon, setHorizon] = useState(90);
  const [showImport, setShowImport] = useState(false);
  const [rowsJson, setRowsJson] = useState(ITEMS_TEMPLATE);
  const [actionError, setActionError] = useState<unknown>(null);

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });
  const cid = companyId || companies.data?.items[0]?.id || "";

  const snapshot = useQuery({
    queryKey: ["treasury", cid, horizon],
    queryFn: () => api.get<TreasurySnapshot>(`/treasury/companies/${cid}/snapshot?horizon_days=${horizon}`),
    enabled: !!cid,
  });
  const accounts = useQuery({
    queryKey: ["treasury-accounts", cid],
    queryFn: () => api.get<{ accounts: BankAccount[] }>(`/treasury/companies/${cid}/accounts`),
    enabled: !!cid,
  });
  const items = useQuery({
    queryKey: ["treasury-items", cid],
    queryFn: () => api.get<{ items: OpenItem[]; counters: Record<string, number> }>(
      `/treasury/companies/${cid}/open-items`),
    enabled: !!cid,
  });
  const plan = useQuery({
    queryKey: ["treasury-suggestions", cid],
    queryFn: () => api.get<SuggestionPlan>(`/treasury/companies/${cid}/reconciliation/suggestions`),
    enabled: !!cid,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["treasury", cid] });
    qc.invalidateQueries({ queryKey: ["treasury-accounts", cid] });
    qc.invalidateQueries({ queryKey: ["treasury-items", cid] });
    qc.invalidateQueries({ queryKey: ["treasury-suggestions", cid] });
    qc.invalidateQueries({ queryKey: ["hub"] });
  };

  const sync = useMutation({
    mutationFn: (accountId: string) =>
      api.post(`/treasury/companies/${cid}/accounts/${accountId}/sync`, {
        idempotency_key: `ui-${crypto.randomUUID()}`,
      }),
    onSuccess: () => { refresh(); toast("Sincronizzazione completata"); },
    onError: setActionError,
  });

  const autoApply = useMutation({
    mutationFn: () => api.post<{ applied: number; skipped_requiring_approval: number }>(
      `/treasury/companies/${cid}/reconciliation/auto-apply`, { limit: 50 }),
    onSuccess: (r) => {
      refresh();
      toast(`${r.applied} abbinamenti applicati${r.skipped_requiring_approval ? ` · ${r.skipped_requiring_approval} in attesa di approvazione` : ""}`);
    },
    onError: setActionError,
  });

  const approve = useMutation({
    mutationFn: (payload: {
      bank_transaction_id: string; method: "exact" | "fuzzy";
      confidence: string; allocations: { open_item_id: string; amount: string }[];
      evidence: Record<string, unknown>;
    }) => api.post(`/treasury/companies/${cid}/reconciliation/apply`, {
      ...payload,
      reason: "Abbinamento approvato dall'operatore dopo revisione delle evidenze.",
    }),
    onSuccess: () => { refresh(); toast("Abbinamento approvato"); },
    onError: setActionError,
  });

  const importItems = useMutation({
    mutationFn: () => api.post(`/treasury/companies/${cid}/open-items/import`,
                               { rows: JSON.parse(rowsJson) }),
    onSuccess: () => { setShowImport(false); setActionError(null); refresh(); toast("Scadenzario importato"); },
    onError: setActionError,
  });

  const snap = snapshot.data;
  const itemById = new Map((items.data?.items ?? []).map((i) => [i.id, i]));
  const openItems = items.data?.items ?? [];
  const overdueCount = openItems.filter((i) => i.is_overdue).length;

  const header = (
    <PageHeader
      hero
      eyebrow="Finanza e fisco"
      title="Tesoreria"
      question="Quanta cassa ho, quando finisce, e cosa devo incassare o pagare prima?"
      actions={cid ? (
        <>
          <select className="select" aria-label="Azienda" value={cid} onChange={(e) => setCompanyId(e.target.value)}>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <select className="select" aria-label="Orizzonte" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {[30, 60, 90, 180].map((h) => <option key={h} value={h}>{h} giorni</option>)}
          </select>
          <button className="btn btn--ghost" onClick={() => setShowImport(true)}>
            <Upload size={14} /> Importa scadenzario
          </button>
        </>
      ) : undefined}
    />
  );

  if (companies.isLoading) return <>{header}<Skeleton kind="stats" rows={4} /><Skeleton kind="table" rows={6} /></>;
  if (companies.error) return <>{header}<ErrorBanner error={companies.error} /></>;
  if (!cid) {
    return (
      <>
        {header}
        <EmptyState title="Nessuna azienda nel workspace" icon={<Wallet size={20} strokeWidth={1.8} />}
                    action={<a className="btn btn--primary" href="/companies">Crea la prima azienda</a>}>
          La tesoreria si legge per azienda: conti, scadenzario e riconciliazione partono da un'anagrafica.
        </EmptyState>
      </>
    );
  }

  return (
    <>
      {header}

      {actionError ? (
        <div className="mb-3">
          <ErrorBanner error={actionError instanceof ApiError ? actionError : new Error("Operazione non riuscita")} />
        </div>
      ) : null}
      {snapshot.error && <ErrorBanner error={snapshot.error} />}
      {snapshot.isLoading && (
        <>
          <Skeleton kind="stats" rows={4} />
          <div className="grid-2-1">
            <Skeleton kind="lines" rows={6} />
            <Skeleton kind="lines" rows={4} />
          </div>
        </>
      )}

      {snap && (
        <>
          <div className="stat-grid">
            <Stat
              hero
              icon={<Wallet size={14} />}
              label="Posizione di cassa"
              value={<Val v={snap.position.amount} />}
              hint={snap.position.status === "available"
                ? `saldo al ${dateIt(snap.position.oldest_balance_date)} · ${snap.counters.accounts} ${snap.counters.accounts === 1 ? "conto" : "conti"}`
                : "saldo mancante su almeno un conto"}
            />
            <Stat
              icon={<CalendarClock size={14} />}
              label="Cassa negativa dal"
              value={snap.forecast.first_negative_date
                ? <span className="num">{dateIt(snap.forecast.first_negative_date)}</span>
                : <span className="muted">mai</span>}
              hint={snap.forecast.days_to_negative != null
                ? `tra ${snap.forecast.days_to_negative} giorni con le partite a scadenza`
                : `nessun saldo negativo nei prossimi ${horizon} giorni`}
              tone={snap.forecast.first_negative_date ? "danger" : undefined}
            />
            <Stat
              icon={<Banknote size={14} />}
              label="Crediti da incassare"
              value={<Val v={snap.counters.receivable_residual} />}
              hint={<>scaduti <Val v={snap.aging.receivables.overdue.amount} />{snap.aging.receivables.overdue.count > 0 && ` · fino a ${snap.aging.receivables.overdue.max_days} giorni`}</>}
              tone={snap.aging.receivables.overdue.count > 0 ? "warn" : undefined}
            />
            <Stat
              icon={<GitMerge size={14} />}
              label="Movimenti da riconciliare"
              value={snap.counters.unreconciled_transactions}
              hint={<><Val v={snap.counters.unreconciled_amount} /> non allocati</>}
              tone={snap.counters.unreconciled_transactions > 0 ? "warn" : undefined}
            />
          </div>

          {snap.warnings.length > 0 && (
            <Section title="Segnali sulla cassa" className="mb-3">
              <ActionList actions={snap.warnings.map((w) => ({
                ...w, priority: 0, priority_version: "", company_id: undefined, company_name: undefined,
              }))} />
            </Section>
          )}

          <div className="grid-2-1">
            <div className="stack">
              <Section title="Flussi attesi per scadenza">
                <FlowChart snapshot={snap} />
              </Section>
              <Section title="Saldo proiettato per orizzonte" flush>
                <table className="table table--flush table--static">
                  <thead>
                    <tr>
                      <th>Orizzonte</th>
                      <th className="th--num">Incassi</th>
                      <th className="th--num">Pagamenti</th>
                      <th className="th--num">Netto</th>
                      <th className="th--num">Saldo proiettato</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snap.forecast.horizons.map((h) => (
                      <tr key={h.horizon_days}>
                        <td>
                          <div className="table__primary">{h.horizon_days} giorni</div>
                          <div className="table__sub">fino al {dateIt(h.end_date)} · {h.item_count} partite</div>
                        </td>
                        <td className="td--num"><Val v={h.expected_inflows} /></td>
                        <td className="td--num"><Val v={h.expected_outflows} /></td>
                        <td className="td--num"><Signed v={h.net_flow} /></td>
                        <td className="td--num strong">
                          {h.projected_balance != null && Number(h.projected_balance) < 0
                            ? <span className="neg">{money(h.projected_balance)}</span>
                            : <Val v={h.projected_balance} />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            </div>

            <div className="stack">
              <Section title="Conti bancari">
                {accounts.isLoading && <Skeleton rows={3} />}
                {accounts.data?.accounts.length === 0 ? (
                  <EmptyState title="Nessun conto collegato">
                    Senza un conto la posizione di cassa non è calcolabile.
                  </EmptyState>
                ) : (
                  <div className="rows">
                    {accounts.data?.accounts.map((a) => {
                      const conn = CONNECTION_LABEL[a.connection_status] ?? { label: a.connection_status.replaceAll("_", " "), tone: "neutral" };
                      return (
                        <Row
                          key={a.id}
                          leading={<Banknote size={16} />}
                          title={<span className="cluster">{a.label}{!a.is_real_institution && <Badge tone="warning" dot={false}>Sandbox</Badge>}</span>}
                          sub={<span className="cluster">
                            <span>{a.bank_name ?? "banca n.d."}{a.iban_last4 ? ` · ••••${a.iban_last4}` : ""}</span>
                            <span className={`dot dot--${conn.tone}`}><i />{conn.label}</span>
                          </span>}
                          trailing={<div className="right">
                            <div className="num strong"><Val v={a.balance} /></div>
                            <div className="text-xs muted">{a.balance_date ? `al ${dateIt(a.balance_date)}` : "saldo n.d."}</div>
                            {a.supports_transactions && (
                              <button className="btn btn--ghost btn--sm mt-1" disabled={sync.isPending}
                                      onClick={() => { setActionError(null); sync.mutate(a.id); }}>
                                <RefreshCw size={12} /> Sincronizza
                              </button>
                            )}
                          </div>}
                        />
                      );
                    })}
                  </div>
                )}
              </Section>

              <Section title="Scaduto per fascia" flush>
                <table className="table table--flush table--static table--dense">
                  <thead>
                    <tr><th>Fascia</th><th className="th--num">Crediti</th><th className="th--num">Debiti</th></tr>
                  </thead>
                  <tbody>
                    {Object.keys(snap.aging.receivables.buckets).map((bucket) => (
                      <tr key={bucket}>
                        <td>{bucketLabel(bucket)}</td>
                        <td className="td--num"><Val v={snap.aging.receivables.buckets[bucket].amount} /></td>
                        <td className="td--num"><Val v={snap.aging.payables.buckets[bucket]?.amount} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            </div>
          </div>

          <Section
            className="mt-4"
            title="Da incassare e pagare"
            actions={items.data && (
              <span className="text-xs muted">
                {items.data.counters.open ?? 0} partite aperte{overdueCount > 0 && <> · <span className="neg strong">{overdueCount} scadute</span></>}
              </span>
            )}
            flush
          >
            {items.isLoading && <Skeleton kind="table" rows={5} />}
            {items.data && openItems.length === 0 ? (
              <EmptyState title="Nessuna partita aperta"
                          action={<button className="btn btn--primary btn--sm" onClick={() => setShowImport(true)}><Upload size={12} /> Importa scadenzario</button>}>
                Importa lo scadenzario per vedere cosa incassare e pagare, e da quando.
              </EmptyState>
            ) : items.data ? (
              <table className="table table--flush table--static">
                <thead>
                  <tr>
                    <th>Controparte</th><th>Documento</th><th>Scadenza</th>
                    <th className="th--num">Importo</th>
                    <th className="th--num">Residuo</th>
                    <th>Stato</th><th>Origine</th>
                  </tr>
                </thead>
                <tbody>
                  {openItems.map((i) => {
                    const st = ITEM_STATUS[i.status] ?? { label: i.status.replaceAll("_", " "), tone: "neutral" };
                    return (
                      <tr key={i.id}>
                        <td>
                          <div className="table__primary">{i.counterparty_name}</div>
                          <div className="table__sub">
                            {i.direction === "receivable" ? "Credito" : "Debito"}
                            {i.counterparty_vat ? ` · P.IVA ${i.counterparty_vat}` : ""}
                          </div>
                        </td>
                        <td className="num">{i.document_number ?? <span className="muted">—</span>}</td>
                        <td className="num nowrap">
                          {dateIt(i.due_date)}
                          {i.is_overdue && <div className="table__sub neg">scaduta da {i.days_overdue} giorni</div>}
                        </td>
                        <td className="td--num">{money(i.amount)}</td>
                        <td className="td--num strong">{money(i.residual)}</td>
                        <td><Badge tone={i.status === "open" && i.is_overdue ? "danger" : st.tone}>{st.label}</Badge></td>
                        <td className="muted text-xs">{SOURCE_LABEL[i.source] ?? i.source}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </Section>

          <Section
            className="mt-4"
            title={<>Banco di riconciliazione{plan.data && <span className="muted text-xs"> · {plan.data.counters.with_suggestions} proposte su {plan.data.counters.evaluated} movimenti</span>}</>}
            actions={
              <button className="btn btn--primary btn--sm"
                      disabled={autoApply.isPending || !plan.data?.counters.auto_applicable}
                      onClick={() => { setActionError(null); autoApply.mutate(); }}>
                {autoApply.isPending
                  ? "Applicazione…"
                  : `Applica ${plan.data?.counters.auto_applicable ?? 0} abbinamenti esatti`}
              </button>
            }
            footer={plan.data && (
              <span className="text-xs muted">{plan.data.approval_policy} · Livello 3 (triage AI): {plan.data.levels["3"]}</span>
            )}
          >
            {plan.isLoading && <Skeleton rows={4} />}
            {plan.data && plan.data.transactions.length === 0 && (
              <EmptyState title="Nessun abbinamento proposto" icon={<GitMerge size={20} strokeWidth={1.8} />}>
                {plan.data.counters.unmatched} movimenti senza corrispondenza deterministica restano in lavorazione manuale.
              </EmptyState>
            )}
            <div className="rec">
              {plan.data?.transactions.map((tx) => (
                <div className="rec__tx" key={tx.bank_transaction_id}>
                  <div className="rec__head">
                    <div>
                      <span className="num strong"><Signed v={tx.amount} /></span>{" "}
                      <span className="muted">{dateIt(tx.value_date)}</span>{" "}
                      {tx.counterparty_name && <span>· {tx.counterparty_name}</span>}
                      <div className="rec__desc">{tx.description}</div>
                    </div>
                    <div>
                      {tx.auto_applicable
                        ? <Badge tone="success">Esatto, non ambiguo</Badge>
                        : <Badge tone="warning">Richiede approvazione</Badge>}
                    </div>
                  </div>
                  {tx.suggestions.map((s, i) => (
                    <div className={`rec__sugg rec__sugg--${s.method}`} key={i}>
                      <div className="cluster cluster--between">
                        <span>
                          <span className="strong">Livello {s.level}</span> · {s.method === "exact" ? "abbinamento esatto" : "abbinamento per punteggio"}{" "}
                          <span className="num muted">confidenza {s.confidence}</span>
                        </span>
                        <span className="num muted text-xs" title="Versione del motore">{s.engine_version}</span>
                      </div>
                      <ul className="rec__reasons">
                        {s.allocations.map((a) => {
                          const item = itemById.get(a.open_item_id);
                          return (
                            <li key={a.open_item_id}>
                              <span className="num">{money(a.amount)}</span> →{" "}
                              {item
                                ? `${item.counterparty_name} · ${item.document_number ?? item.source_ref} (scad. ${dateIt(item.due_date)}, residuo ${money(item.residual)})`
                                : "partita non più aperta"}
                            </li>
                          );
                        })}
                        {s.reasons.map((r) => <li key={r} className="muted">{r}</li>)}
                      </ul>
                      <div className="rec__actions">
                        <button className="btn btn--primary btn--sm" disabled={approve.isPending}
                                onClick={() => {
                                  setActionError(null);
                                  approve.mutate({
                                    bank_transaction_id: tx.bank_transaction_id,
                                    method: s.method, confidence: s.confidence,
                                    allocations: s.allocations, evidence: s.evidence,
                                  });
                                }}>
                          Approva abbinamento
                        </button>
                        <span className="muted text-xs">
                          registra operatore, metodo, evidenze e versione del motore
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Section>

          <details className="mt-4">
            <summary className="eyebrow eyebrow--muted">
              Metodo, qualità dei dati e limitazioni ({snap.position.issues.length + snap.limitations.length})
            </summary>
            <Section tone="section" className="mt-1">
              <ul className="mgmt-issues">
                {snap.forecast.facts.map((f) => <li key={f}><span className="strong">Fatto:</span> {f}</li>)}
                {snap.forecast.assumptions.map((a) => <li key={a}><span className="strong">Ipotesi:</span> {a}</li>)}
                {snap.position.issues.map((i) => <li key={i}>{i}</li>)}
                {snap.limitations.map((l) => <li key={l}>{l}</li>)}
              </ul>
              <div className="muted text-xs mt-3">
                Formule <span className="num">{snap.formula_version}</span> · riconciliazione{" "}
                <span className="num">{snap.reconciliation.engine_version}</span> ·
                livelli attivi {snap.reconciliation.levels_implemented.join(", ")} ·
                livello 3 {snap.reconciliation.level_3_ai_triage}
              </div>
            </Section>
          </details>
        </>
      )}

      {showImport && (
        <Modal
          title="Importa scadenzario"
          subtitle="Righe JSON: partite a credito e a debito con scadenza e importo."
          onClose={() => setShowImport(false)}
          footer={
            <>
              <button className="btn btn--ghost" onClick={() => setShowImport(false)}>Annulla</button>
              <button className="btn btn--primary" disabled={importItems.isPending}
                      onClick={() => { setActionError(null); importItems.mutate(); }}>
                {importItems.isPending ? "Importazione…" : "Importa"}
              </button>
            </>
          }
        >
          {actionError ? (
            <ErrorBanner error={actionError instanceof ApiError ? actionError : new Error("Import non riuscito")} />
          ) : null}
          <Callout tone="info" title="Import atomico e idempotente">
            Righe identiche già presenti vengono ignorate; righe con contenuto diverso sullo stesso riferimento
            vengono rifiutate. Importi come stringhe decimali, solo EUR. Le partite non si modificano: si chiudono
            con incasso, stralcio o annullamento tracciati.
          </Callout>
          <textarea className="textarea num mt-3" rows={14} value={rowsJson} aria-label="Righe da importare"
                    onChange={(e) => setRowsJson(e.target.value)} spellCheck={false} />
        </Modal>
      )}
    </>
  );
}
