import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, RefreshCw, Upload } from "lucide-react";
import { api, ApiError } from "../api/client";
import type {
  BankAccount, CompanyListItem, OpenItem, Page, SuggestionPlan, TreasurySnapshot,
} from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Modal, Spinner } from "../components/ui";
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

function Val({ v, suffix }: { v: string | null; suffix?: string }) {
  if (v == null) return <span className="tre-null" title="Nessuna evidenza disponibile: non è zero">n.d.</span>;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

function Signed({ v }: { v: string }) {
  const negative = v.startsWith("-");
  return <span className={negative ? "tre-neg" : "tre-pos"}>{money(v)}</span>;
}

/** Inflow/outflow per due date over the selected horizon. Bars are display
 *  only: every amount comes from the backend as a decimal string. */
function FlowChart({ snapshot }: { snapshot: TreasurySnapshot }) {
  const rows = snapshot.forecast.daily.filter((d) => d.inflow !== "0.00" || d.outflow !== "0.00");
  const max = useMemo(
    () => Math.max(1, ...rows.map((d) => Math.max(Number(d.inflow ?? 0), Number(d.outflow ?? 0)))),
    [rows],
  );
  if (!rows.length) return <EmptyState>Nessuna scadenza nell'orizzonte selezionato.</EmptyState>;
  return (
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
    onSuccess: refresh,
    onError: setActionError,
  });

  const autoApply = useMutation({
    mutationFn: () => api.post<{ applied: number; skipped_requiring_approval: number }>(
      `/treasury/companies/${cid}/reconciliation/auto-apply`, { limit: 50 }),
    onSuccess: refresh,
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
    onSuccess: refresh,
    onError: setActionError,
  });

  const importItems = useMutation({
    mutationFn: () => api.post(`/treasury/companies/${cid}/open-items/import`,
                               { rows: JSON.parse(rowsJson) }),
    onSuccess: () => { setShowImport(false); setActionError(null); refresh(); },
    onError: setActionError,
  });

  if (companies.isLoading) return <Spinner />;
  if (companies.error) return <ErrorBanner error={companies.error} />;
  if (!cid) return <EmptyState>Crea prima un'azienda per usare la tesoreria.</EmptyState>;

  const snap = snapshot.data;
  const itemById = new Map((items.data?.items ?? []).map((i) => [i.id, i]));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Tesoreria e riconciliazione</h1>
          <div className="page-head__meta">
            Scadenzario, movimenti bancari, posizione e previsione di cassa — nessun importo stimato.
          </div>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <select className="select" value={cid} onChange={(e) => setCompanyId(e.target.value)} style={{ maxWidth: 260 }}>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <select className="select" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} style={{ width: 130 }}>
            {[30, 60, 90, 180].map((h) => <option key={h} value={h}>{h} giorni</option>)}
          </select>
          <button className="btn btn--ghost" onClick={() => setShowImport(true)}>
            <Upload size={14} /> Importa scadenzario
          </button>
        </div>
      </div>

      {actionError ? (
        <ErrorBanner error={actionError instanceof ApiError ? actionError : new Error("Operazione non riuscita")} />
      ) : null}
      {snapshot.isLoading && <Spinner />}
      {snapshot.error && <ErrorBanner error={snapshot.error} />}

      {snap && (
        <>
          <ActionList actions={snap.warnings.map((w) => ({
            ...w, priority: 0, priority_version: "", company_id: undefined, company_name: undefined,
          }))} />

          <div className="kpi-grid" style={{ marginTop: 16 }}>
            <Card className={`kpi kpi--edge-primary ${snap.position.status === "not_calculable" ? "kpi--alert" : ""}`}>
              <div className="kpi__label">Posizione di cassa</div>
              <div className="kpi__value mono"><Val v={snap.position.amount} /></div>
              <div className="kpi__hint">
                {snap.position.status === "available"
                  ? `saldo al ${dateIt(snap.position.oldest_balance_date)}`
                  : "saldo mancante su almeno un conto"}
              </div>
            </Card>
            <Card className={`kpi kpi--edge-warn ${snap.forecast.first_negative_date ? "kpi--alert" : ""}`}>
              <div className="kpi__label">Cassa proiettata negativa</div>
              <div className="kpi__value mono" style={{ fontSize: "1.2rem" }}>
                {snap.forecast.first_negative_date
                  ? `${snap.forecast.first_negative_date}`
                  : <span className="muted">nessuna data</span>}
              </div>
              <div className="kpi__hint">
                {snap.forecast.days_to_negative != null
                  ? `tra ${snap.forecast.days_to_negative} giorni`
                  : "con le partite aperte a scadenza"}
              </div>
            </Card>
            <Card className="kpi kpi--edge-teal">
              <div className="kpi__label">Crediti aperti</div>
              <div className="kpi__value mono"><Val v={snap.counters.receivable_residual} /></div>
              <div className="kpi__hint">
                scaduti <Val v={snap.aging.receivables.overdue.amount} />
                {snap.aging.receivables.overdue.count > 0 && ` · max ${snap.aging.receivables.overdue.max_days}g`}
              </div>
            </Card>
            <Card className="kpi kpi--edge-accent">
              <div className="kpi__label">Da riconciliare</div>
              <div className="kpi__value">{snap.counters.unreconciled_transactions}</div>
              <div className="kpi__hint">
                <Val v={snap.counters.unreconciled_amount} /> non allocati
              </div>
            </Card>
          </div>

          <div className="grid-2" style={{ marginTop: 16 }}>
            <Card className="card__pad">
              <div className="card__title">Flussi attesi per scadenza</div>
              <FlowChart snapshot={snap} />
              <table className="table" style={{ marginTop: 12 }}>
                <thead>
                  <tr>
                    <th>Orizzonte</th>
                    <th style={{ textAlign: "right" }}>Incassi</th>
                    <th style={{ textAlign: "right" }}>Pagamenti</th>
                    <th style={{ textAlign: "right" }}>Netto</th>
                    <th style={{ textAlign: "right" }}>Saldo proiettato</th>
                  </tr>
                </thead>
                <tbody>
                  {snap.forecast.horizons.map((h) => (
                    <tr key={h.horizon_days} style={{ cursor: "default" }}>
                      <td>{h.horizon_days} giorni <span className="muted">({h.end_date})</span></td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={h.expected_inflows} /></td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={h.expected_outflows} /></td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={h.net_flow} /></td>
                      <td className="mono" style={{ textAlign: "right" }}>
                        {h.projected_balance != null && Number(h.projected_balance) < 0
                          ? <span className="tre-neg">{money(h.projected_balance)}</span>
                          : <Val v={h.projected_balance} />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <details style={{ marginTop: 10 }}>
                <summary className="muted" style={{ fontSize: "0.75rem", cursor: "pointer" }}>
                  Fatti e ipotesi della previsione
                </summary>
                <ul className="mgmt-issues">
                  {snap.forecast.facts.map((f) => <li key={f}><strong>Fatto:</strong> {f}</li>)}
                  {snap.forecast.assumptions.map((a) => <li key={a}><strong>Ipotesi:</strong> {a}</li>)}
                </ul>
              </details>
            </Card>

            <Card className="card__pad">
              <div className="card__title">Conti bancari</div>
              {accounts.data?.accounts.length === 0 ? (
                <EmptyState>Nessun conto configurato per questa azienda.</EmptyState>
              ) : (
                <table className="table">
                  <thead>
                    <tr><th>Conto</th><th>Provider</th><th style={{ textAlign: "right" }}>Saldo</th><th></th></tr>
                  </thead>
                  <tbody>
                    {accounts.data?.accounts.map((a) => (
                      <tr key={a.id} style={{ cursor: "default" }}>
                        <td>
                          <div><Banknote size={13} style={{ verticalAlign: -2, marginRight: 5 }} />{a.label}</div>
                          <div className="muted" style={{ fontSize: "0.72rem" }}>
                            {a.bank_name ?? "banca n.d."}{a.iban_last4 ? ` · ••••${a.iban_last4}` : ""}
                          </div>
                        </td>
                        <td>
                          <div className="mono" style={{ fontSize: "0.72rem" }}>{a.provider_key}</div>
                          {!a.is_real_institution && <Badge tone="warning">sandbox</Badge>}
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          <Val v={a.balance} />
                          <div className="muted" style={{ fontSize: "0.7rem" }}>{dateIt(a.balance_date)}</div>
                        </td>
                        <td>
                          {a.supports_transactions && (
                            <button className="btn btn--ghost btn--sm" disabled={sync.isPending}
                                    onClick={() => { setActionError(null); sync.mutate(a.id); }}>
                              <RefreshCw size={12} /> Sincronizza
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="card__title" style={{ marginTop: 18 }}>Scaduto per fascia</div>
              <table className="table">
                <thead>
                  <tr><th>Fascia</th><th style={{ textAlign: "right" }}>Crediti</th><th style={{ textAlign: "right" }}>Debiti</th></tr>
                </thead>
                <tbody>
                  {Object.keys(snap.aging.receivables.buckets).map((bucket) => (
                    <tr key={bucket} style={{ cursor: "default" }}>
                      <td>{bucket === "current" ? "a scadere" : bucket.replace("d", "").replace("_", "–").replace("plus", "+")}</td>
                      <td className="mono" style={{ textAlign: "right" }}>
                        <Val v={snap.aging.receivables.buckets[bucket].amount} />
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>
                        <Val v={snap.aging.payables.buckets[bucket].amount} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>

          <Card className="card__pad" style={{ marginTop: 16 }}>
            <div className="card__title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>
                Banco di riconciliazione
                {plan.data && <span className="muted" style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>
                  {" "}· motore <span className="mono">{plan.data.engine_version}</span>
                </span>}
              </span>
              <button className="btn btn--primary btn--sm"
                      disabled={autoApply.isPending || !plan.data?.counters.auto_applicable}
                      onClick={() => { setActionError(null); autoApply.mutate(); }}>
                {autoApply.isPending
                  ? "Applicazione…"
                  : `Applica ${plan.data?.counters.auto_applicable ?? 0} match esatti`}
              </button>
            </div>
            {plan.isLoading && <Spinner />}
            {plan.data && plan.data.transactions.length === 0 && (
              <EmptyState>
                Nessun abbinamento proposto: {plan.data.counters.unmatched} movimenti senza corrispondenza
                deterministica restano in lavorazione manuale.
              </EmptyState>
            )}
            <div className="rec">
              {plan.data?.transactions.map((tx) => (
                <div className="rec__tx" key={tx.bank_transaction_id}>
                  <div className="rec__head">
                    <div>
                      <strong className="mono"><Signed v={tx.amount} /></strong>{" "}
                      <span className="muted">{tx.value_date}</span>{" "}
                      {tx.counterparty_name && <span>· {tx.counterparty_name}</span>}
                      <div className="rec__desc">{tx.description}</div>
                    </div>
                    <div>
                      {tx.auto_applicable
                        ? <Badge tone="success">esatto non ambiguo</Badge>
                        : <Badge tone="warning">richiede approvazione</Badge>}
                    </div>
                  </div>
                  {tx.suggestions.map((s, i) => (
                    <div className={`rec__sugg rec__sugg--${s.method}`} key={i}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <span>
                          <strong>Livello {s.level}</strong> · {s.method === "exact" ? "esatto" : "punteggio"}{" "}
                          <span className="mono">conf. {s.confidence}</span>
                        </span>
                        <span className="mono muted" style={{ fontSize: "0.7rem" }}>{s.engine_version}</span>
                      </div>
                      <ul className="rec__reasons">
                        {s.allocations.map((a) => {
                          const item = itemById.get(a.open_item_id);
                          return (
                            <li key={a.open_item_id}>
                              {money(a.amount)} →{" "}
                              {item
                                ? `${item.counterparty_name} · ${item.document_number ?? item.source_ref} (scad. ${item.due_date}, residuo ${money(item.residual)})`
                                : a.open_item_id}
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
                        <span className="muted" style={{ fontSize: "0.72rem", alignSelf: "center" }}>
                          l'approvazione registra operatore, metodo, evidenze e versione del motore
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            {plan.data && (
              <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
                {plan.data.approval_policy} · Livello 3 (triage AI): {plan.data.levels["3"]}
              </div>
            )}
          </Card>

          <Card className="card__pad" style={{ marginTop: 16 }}>
            <div className="card__title">Scadenzario · {items.data?.counters.open ?? 0} partite aperte</div>
            {items.data?.items.length === 0 ? (
              <EmptyState>Nessuna partita: importare lo scadenzario o inserire una partita manuale.</EmptyState>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Controparte</th><th>Documento</th><th>Scadenza</th>
                    <th style={{ textAlign: "right" }}>Importo</th>
                    <th style={{ textAlign: "right" }}>Residuo</th>
                    <th>Stato</th><th>Origine</th>
                  </tr>
                </thead>
                <tbody>
                  {items.data?.items.map((i) => (
                    <tr key={i.id} style={{ cursor: "default" }}>
                      <td>
                        {i.counterparty_name}
                        <div className="muted" style={{ fontSize: "0.72rem" }}>
                          {i.direction === "receivable" ? "credito" : "debito"}
                          {i.counterparty_vat ? ` · ${i.counterparty_vat}` : ""}
                        </div>
                      </td>
                      <td className="mono" style={{ fontSize: "0.75rem" }}>{i.document_number ?? "—"}</td>
                      <td>
                        {i.due_date}
                        {i.is_overdue && <span className="tre-neg"> · +{i.days_overdue}g</span>}
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>{money(i.amount)}</td>
                      <td className="mono" style={{ textAlign: "right" }}>{money(i.residual)}</td>
                      <td><Badge tone={
                        i.status === "settled" ? "success"
                          : i.status === "partially_settled" ? "info"
                            : i.status === "open" ? (i.is_overdue ? "danger" : "primary") : "neutral"
                      }>{i.status.replaceAll("_", " ")}</Badge></td>
                      <td className="muted" style={{ fontSize: "0.72rem" }}>{i.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card className="card__pad" style={{ marginTop: 16 }}>
            <div className="card__title">Qualità, provenienza e limitazioni</div>
            <ul className="mgmt-issues">
              {snap.position.issues.map((i) => <li key={i}>{i}</li>)}
              {snap.limitations.map((l) => <li key={l}>{l}</li>)}
            </ul>
            <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
              Formule <span className="mono">{snap.formula_version}</span> · riconciliazione{" "}
              <span className="mono">{snap.reconciliation.engine_version}</span> ·
              livelli attivi {snap.reconciliation.levels_implemented.join(", ")} ·
              livello 3 {snap.reconciliation.level_3_ai_triage}
            </div>
          </Card>
        </>
      )}

      {showImport && (
        <Modal
          title="Importa scadenzario (JSON)"
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
          <div className="alert alert--info">
            Import atomico e idempotente per <span className="mono">source_ref</span>: righe identiche già
            presenti vengono ignorate, righe con contenuto diverso sullo stesso riferimento vengono rifiutate.
            Importi come stringhe decimali, solo EUR. Le partite non sono modificabili: si chiudono con
            incasso, write-off o annullamento tracciati.
          </div>
          <textarea className="textarea mono" rows={14} value={rowsJson}
                    onChange={(e) => setRowsJson(e.target.value)} spellCheck={false} />
        </Modal>
      )}
    </>
  );
}
