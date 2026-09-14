import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, ShieldAlert, Upload } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { BudgetRow, CompanyListItem, ImportBatch, MgmtOverview, Page } from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Modal, Spinner } from "../components/ui";
import { dateTimeIt, money } from "../lib/format";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];
const CSV_TEMPLATE =
  "source_id,date,kind,category,amount,currency\n" +
  "FT-2026-001,2026-01-15,revenue,Vendite,10000.00,EUR\n" +
  "NC-2026-001,2026-01-20,cost,Personale,6000.00,EUR\n";

function Value({ v, suffix = "" }: { v: string | null; suffix?: string }) {
  if (v == null) return <span className="mgmt-null" title="Nessuna evidenza: non è zero">n.d.</span>;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

function Alerts({ alerts }: { alerts: MgmtOverview["alerts"] }) {
  if (!alerts.length) return null;
  const icon = { info: Info, warning: AlertTriangle, danger: ShieldAlert };
  return (
    <div className="mgmt-alerts">
      {alerts.map((a) => {
        const Icon = icon[a.severity];
        return (
          <div key={a.code} className={`alert alert--${a.severity === "info" ? "info" : a.severity}`}>
            <Icon size={14} style={{ marginRight: 6, verticalAlign: -2 }} />
            <strong>{a.title}</strong> — {a.message}
            {a.formula && <span className="mono muted" style={{ marginLeft: 8, fontSize: "0.72rem" }}>{a.formula}</span>}
          </div>
        );
      })}
    </div>
  );
}

function MonthlyChart({ monthly }: { monthly: MgmtOverview["monthly"] }) {
  const max = useMemo(
    () => Math.max(1, ...monthly.flatMap((m) => [m.revenue, m.costs, m.budget_revenue].map((v) => (v ? Number(v) : 0)))),
    [monthly],
  );
  return (
    <div className="mchart">
      {monthly.map((m) => (
        <div className="mchart__col" key={m.month}>
          <div className="mchart__bars">
            {m.budget_revenue && (
              <div className="mchart__budget" style={{ bottom: `${(Number(m.budget_revenue) / max) * 100}%` }} title={`Budget ricavi ${money(m.budget_revenue)}`} />
            )}
            <div className="mchart__bar mchart__bar--rev" style={{ height: `${m.revenue ? (Number(m.revenue) / max) * 100 : 0}%` }} title={`Ricavi ${money(m.revenue)}`} />
            <div className="mchart__bar mchart__bar--cost" style={{ height: `${m.costs ? (Number(m.costs) / max) * 100 : 0}%` }} title={`Costi ${money(m.costs)}`} />
          </div>
          <div className="mchart__label">{MONTHS[m.month]}</div>
        </div>
      ))}
      <div className="mchart__legend">
        <span><i className="mchart__swatch mchart__bar--rev" /> Ricavi</span>
        <span><i className="mchart__swatch mchart__bar--cost" /> Costi</span>
        <span><i className="mchart__swatch mchart__swatch--budget" /> Budget ricavi</span>
      </div>
    </div>
  );
}

export default function ManagementPage() {
  const qc = useQueryClient();
  const [companyId, setCompanyId] = useState<string>("");
  const [year, setYear] = useState(2026);
  const [month, setMonth] = useState(6);
  const [showImport, setShowImport] = useState(false);
  const [csv, setCsv] = useState(CSV_TEMPLATE);
  const [importError, setImportError] = useState<unknown>(null);

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });
  const cid = companyId || companies.data?.items[0]?.id || "";

  const overview = useQuery({
    queryKey: ["mgmt", cid, year, month],
    queryFn: () => api.get<MgmtOverview>(`/management/companies/${cid}/overview?year=${year}&through_month=${month}`),
    enabled: !!cid,
  });
  const imports = useQuery({
    queryKey: ["mgmt-imports", cid],
    queryFn: () => api.get<ImportBatch[]>(`/management/companies/${cid}/imports`),
    enabled: !!cid,
  });
  const budgets = useQuery({
    queryKey: ["mgmt-budgets", cid, year],
    queryFn: () => api.get<BudgetRow[]>(`/management/companies/${cid}/budgets?year=${year}`),
    enabled: !!cid,
  });

  const doImport = useMutation({
    mutationFn: () =>
      api.post<ImportBatch>(`/management/companies/${cid}/imports`, {
        filename: `import-${Date.now()}.csv`,
        csv_content: csv,
        idempotency_key: `ui-${crypto.randomUUID()}`,
      }),
    onSuccess: () => {
      setShowImport(false);
      setImportError(null);
      qc.invalidateQueries({ queryKey: ["mgmt", cid] });
      qc.invalidateQueries({ queryKey: ["mgmt-imports", cid] });
    },
    onError: (e) => setImportError(e),
  });

  const saveBudget = useMutation({
    mutationFn: (b: { month: number; revenue: string; costs: string }) =>
      api.put(`/management/companies/${cid}/budgets`, {
        year, month: b.month,
        revenue: b.revenue.trim() || null,
        costs: b.costs.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mgmt", cid] });
      qc.invalidateQueries({ queryKey: ["mgmt-budgets", cid, year] });
    },
  });

  if (companies.isLoading) return <Spinner />;
  if (companies.error) return <ErrorBanner error={companies.error} />;
  if (!cid) return <EmptyState>Crea prima un'azienda per usare il controllo di gestione.</EmptyState>;

  const ov = overview.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Controllo di gestione</h1>
          <div className="page-head__meta">
            Consuntivi, budget e scostamenti — solo dati disponibili, mai stimati.
          </div>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <select className="select" value={cid} onChange={(e) => setCompanyId(e.target.value)} style={{ maxWidth: 260 }}>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90 }}>
            {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
          </select>
          <select className="select" value={month} onChange={(e) => setMonth(Number(e.target.value))} style={{ width: 120 }}>
            {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>Gen–{m}</option>)}
          </select>
          <button className="btn btn--primary" onClick={() => setShowImport(true)}>
            <Upload size={14} /> Importa CSV
          </button>
        </div>
      </div>

      {overview.isLoading && <Spinner />}
      {overview.error && <ErrorBanner error={overview.error} />}
      {ov && (
        <>
          <Alerts alerts={ov.alerts} />

          <div className="kpi-grid">
            <Card className="kpi kpi--edge-primary">
              <div className="kpi__label">Ricavi disponibili</div>
              <div className="kpi__value mono"><Value v={ov.revenue} /></div>
              <div className="kpi__hint">{ov.period.label}</div>
            </Card>
            <Card className="kpi kpi--edge-warn">
              <div className="kpi__label">Costi disponibili</div>
              <div className="kpi__value mono"><Value v={ov.costs} /></div>
              <div className="kpi__hint">
                vs budget: <Value v={ov.budget.cost_variance} />
              </div>
            </Card>
            <Card className={`kpi kpi--edge-teal ${ov.result && Number(ov.result) < 0 ? "kpi--alert" : ""}`}>
              <div className="kpi__label">Risultato gestionale</div>
              <div className="kpi__value mono"><Value v={ov.result} /></div>
              <div className="kpi__hint">margine <Value v={ov.margin_percent} suffix="%" /> · non è EBITDA</div>
            </Card>
            <Card className="kpi kpi--edge-accent">
              <div className="kpi__label">Copertura dati</div>
              <div className="kpi__value">{ov.quality.covered_months}<span className="muted" style={{ fontSize: "1rem" }}>/{ov.quality.expected_months}</span></div>
              <div className="kpi__hint">
                <Badge tone={ov.quality.status === "empty" ? "neutral" : "warning"}>
                  {ov.quality.status === "empty" ? "nessuna fonte" : "parziale"}
                </Badge>{" "}
                {ov.trace.source_count} fonti
              </div>
            </Card>
          </div>

          <div className="grid-2">
            <Card className="card__pad">
              <div className="card__title">Andamento mensile · consuntivo vs budget</div>
              <MonthlyChart monthly={ov.monthly} />
            </Card>
            <Card className="card__pad">
              <div className="card__title">Budget vs consuntivo</div>
              <table className="table">
                <thead>
                  <tr><th></th><th style={{ textAlign: "right" }}>Budget</th><th style={{ textAlign: "right" }}>Consuntivo</th><th style={{ textAlign: "right" }}>Scostamento</th></tr>
                </thead>
                <tbody>
                  {(["revenue", "costs", "result"] as const).map((k) => {
                    const variance = ov.budget[`${k === "costs" ? "cost" : k}_variance` as keyof typeof ov.budget] as string | null;
                    const bad = variance != null && ((k === "costs" && Number(variance) > 0) || (k !== "costs" && Number(variance) < 0));
                    return (
                      <tr key={k} style={{ cursor: "default" }}>
                        <td>{{ revenue: "Ricavi", costs: "Costi", result: "Risultato" }[k]}</td>
                        <td className="mono" style={{ textAlign: "right" }}><Value v={ov.budget[k]} /></td>
                        <td className="mono" style={{ textAlign: "right" }}><Value v={ov[k]} /></td>
                        <td className="mono" style={{ textAlign: "right", color: bad ? "var(--pys-danger-600)" : variance ? "var(--pys-success-600)" : undefined }}>
                          <Value v={variance} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="card__title" style={{ marginTop: 18 }}>Confronto {ov.comparison.period.label}</div>
              <div className="dl">
                <dt>Ricavi anno prec.</dt><dd className="mono"><Value v={ov.comparison.revenue} /></dd>
                <dt>Δ ricavi</dt><dd className="mono"><Value v={ov.comparison.revenue_change_percent} suffix="%" /></dd>
                <dt>Δ costi</dt><dd className="mono"><Value v={ov.comparison.cost_change_percent} suffix="%" /></dd>
              </div>
            </Card>
          </div>

          <div className="grid-2" style={{ marginTop: 16 }}>
            <Card className="card__pad">
              <div className="card__title">Costi per categoria</div>
              {ov.cost_categories.length === 0 ? (
                <EmptyState>Nessun costo disponibile nel periodo.</EmptyState>
              ) : (
                <div className="funnel">
                  {ov.cost_categories.map((c, i) => {
                    const max = Number(ov.cost_categories[0].amount);
                    return (
                      <div className="funnel__row" key={c.category}>
                        <span className="funnel__label">{c.category}</span>
                        <div className="funnel__track">
                          <div className="funnel__bar" style={{ width: `${(Number(c.amount) / max) * 100}%`, background: i % 2 ? "#a89056" : "#3f7a83" }} />
                        </div>
                        <span className="funnel__meta mono">{money(c.amount)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
            <Card className="card__pad">
              <div className="card__title">Budget mensile {year} <span className="muted" style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>· versionato, mai sovrascritto</span></div>
              <BudgetEditor rows={budgets.data ?? []} through={month} onSave={(b) => saveBudget.mutate(b)} busy={saveBudget.isPending} />
            </Card>
          </div>

          <Card className="card__pad">
            <div className="card__title">Qualità e provenienza</div>
            <ul className="mgmt-issues">
              {ov.quality.issues.map((i) => <li key={i}>{i}</li>)}
            </ul>
            <div className="muted" style={{ fontSize: "0.75rem", marginTop: 8 }}>
              Formula <span className="mono">{ov.trace.formula_version}</span> · {ov.trace.source_count} fonti tracciate ·{" "}
              {imports.data?.length ?? 0} import
              {imports.data?.[0] && <> · ultimo {dateTimeIt(imports.data[0].created_at)} ({imports.data[0].filename}, {imports.data[0].row_count} righe)</>}
            </div>
          </Card>
        </>
      )}

      {showImport && (
        <Modal
          title="Importa consuntivi (CSV)"
          onClose={() => setShowImport(false)}
          footer={
            <>
              <button className="btn btn--ghost" onClick={() => setShowImport(false)}>Annulla</button>
              <button className="btn btn--primary" disabled={doImport.isPending} onClick={() => doImport.mutate()}>
                {doImport.isPending ? "Importazione…" : "Importa"}
              </button>
            </>
          }
        >
          {importError ? <ErrorBanner error={importError instanceof ApiError ? importError : new Error("Import fallito")} /> : null}
          <div className="alert alert--info">
            Intestazione richiesta: <span className="mono">source_id,date,kind,category,amount,currency</span>.
            Import atomico e idempotente: <span className="mono">source_id</span> già presenti con lo stesso contenuto vengono ignorati, con contenuto diverso vengono rifiutati.
            Solo EUR. Le righe importate non sono modificabili: le correzioni avvengono con nuovi import tracciati.
          </div>
          <textarea className="textarea mono" rows={12} value={csv} onChange={(e) => setCsv(e.target.value)} spellCheck={false} />
        </Modal>
      )}
    </>
  );
}

function BudgetEditor({ rows, through, onSave, busy }: {
  rows: BudgetRow[]; through: number; busy: boolean;
  onSave: (b: { month: number; revenue: string; costs: string }) => void;
}) {
  const [draft, setDraft] = useState<Record<number, { revenue: string; costs: string }>>({});
  const byMonth = Object.fromEntries(rows.map((r) => [r.month, r]));
  return (
    <table className="table">
      <thead><tr><th>Mese</th><th>Ricavi</th><th>Costi</th><th>v.</th><th></th></tr></thead>
      <tbody>
        {Array.from({ length: through }, (_, i) => i + 1).map((m) => {
          const cur = byMonth[m];
          const d = draft[m] ?? { revenue: cur?.revenue ?? "", costs: cur?.costs ?? "" };
          const dirty = d.revenue !== (cur?.revenue ?? "") || d.costs !== (cur?.costs ?? "");
          return (
            <tr key={m} style={{ cursor: "default" }}>
              <td>{MONTHS[m]}</td>
              <td><input className="input mono" style={{ padding: "3px 6px" }} value={d.revenue} placeholder="n.d." onChange={(e) => setDraft({ ...draft, [m]: { ...d, revenue: e.target.value } })} /></td>
              <td><input className="input mono" style={{ padding: "3px 6px" }} value={d.costs} placeholder="n.d." onChange={(e) => setDraft({ ...draft, [m]: { ...d, costs: e.target.value } })} /></td>
              <td className="mono muted">{cur ? `v${cur.version}` : "—"}</td>
              <td>
                <button className="btn btn--ghost btn--sm" disabled={!dirty || busy || (!d.revenue && !d.costs)}
                        onClick={() => { onSave({ month: m, revenue: d.revenue, costs: d.costs }); const n = { ...draft }; delete n[m]; setDraft(n); }}>
                  Salva
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
