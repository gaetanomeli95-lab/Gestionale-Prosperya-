import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Database, Layers3, Target, TrendingDown, TrendingUp, Upload } from "lucide-react";
import { api, ApiError } from "../api/client";
import type {
  BudgetRow, CompanyListItem, Contribution, ImportBatch, MgmtCategories,
  MgmtCostCenter, MgmtOverview, Page,
} from "../api/types";
import {
  Badge, Callout, EmptyState, ErrorBanner, KV, Modal, NA, PageHeader, Section, Skeleton, Stat, Tile, toast,
} from "../components/ui";
import { dateTimeIt, money } from "../lib/format";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];
const CSV_TEMPLATE =
  "source_id,date,kind,category,amount,currency\n" +
  "FT-2026-001,2026-01-15,revenue,Vendite,10000.00,EUR\n" +
  "NC-2026-001,2026-01-20,cost,Personale,6000.00,EUR\n";

function Value({ v, suffix = "" }: { v: string | null; suffix?: string }) {
  if (v == null) return <NA />;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}
function Signed({ v, invert = false, suffix = "" }: { v: string | null; invert?: boolean; suffix?: string }) {
  if (v == null) return <NA />;
  const n = Number(v) * (invert ? -1 : 1);
  return <span className={n < 0 ? "neg" : n > 0 ? "pos" : undefined}>{suffix ? `${v}${suffix}` : money(v)}</span>;
}

function Alerts({ alerts }: { alerts: MgmtOverview["alerts"] }) {
  if (!alerts.length) return null;
  return (
    <div className="stack stack--sm mb-4">
      {alerts.map((a) => (
        <Callout key={a.code} tone={a.severity === "info" ? "info" : a.severity} title={a.title}>
          {a.message}
          {a.formula && <details className="mt-1"><summary className="text-2xs muted">formula</summary><span className="mono text-xs">{a.formula}</span></details>}
        </Callout>
      ))}
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
  const contribution = useQuery({
    queryKey: ["mgmt-contribution", cid, year, month],
    queryFn: () => api.get<Contribution>(
      `/management/companies/${cid}/contribution?year=${year}&through_month=${month}`),
    enabled: !!cid,
  });
  const categories = useQuery({
    queryKey: ["mgmt-categories", cid],
    queryFn: () => api.get<MgmtCategories>(`/management/companies/${cid}/categories`),
    enabled: !!cid,
  });
  const costCenters = useQuery({
    queryKey: ["mgmt-cost-centers", cid],
    queryFn: () => api.get<MgmtCostCenter[]>(`/management/companies/${cid}/cost-centers`),
    enabled: !!cid,
  });

  const classify = useMutation({
    mutationFn: (p: { id: string; cost_nature: string | null; cost_center_id: string | null }) =>
      api.patch(`/management/companies/${cid}/categories/${p.id}`, {
        cost_nature: p.cost_nature, cost_center_id: p.cost_center_id,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mgmt-categories", cid] });
      qc.invalidateQueries({ queryKey: ["mgmt-contribution", cid] });
      qc.invalidateQueries({ queryKey: ["hub"] });
      toast("Classificazione aggiornata");
    },
  });
  const addCostCenter = useMutation({
    mutationFn: (p: { code: string; name: string }) =>
      api.post(`/management/companies/${cid}/cost-centers`, p),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mgmt-cost-centers", cid] }); toast("Centro di costo creato"); },
  });

  const doImport = useMutation({
    mutationFn: () =>
      api.post<ImportBatch>(`/management/companies/${cid}/imports`, {
        filename: `import-${Date.now()}.csv`,
        csv_content: csv,
        idempotency_key: `ui-${crypto.randomUUID()}`,
      }),
    onSuccess: (b) => {
      setShowImport(false);
      setImportError(null);
      qc.invalidateQueries({ queryKey: ["mgmt", cid] });
      qc.invalidateQueries({ queryKey: ["mgmt-imports", cid] });
      toast(`Import completato · ${b.row_count} righe`);
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
      toast("Budget salvato (nuova versione)");
    },
  });

  if (companies.isLoading) return <><Skeleton rows={2} /><Skeleton kind="stats" rows={4} /></>;
  if (companies.error) return <ErrorBanner error={companies.error} />;

  const ov = overview.data;
  const resultNeg = ov?.result != null && Number(ov.result) < 0;
  const companyName = companies.data?.items.find((c) => c.id === cid)?.legal_name;

  return (
    <>
      <PageHeader
        hero
        eyebrow={<>Finanza e fisco{companyName ? ` · ${companyName}` : ""}</>}
        title="Controllo di gestione"
        question="Ricavi, costi e margini stanno andando come previsto? Solo dati disponibili, mai stimati."
        actions={
          <>
            <select className="select" value={cid} onChange={(e) => setCompanyId(e.target.value)} aria-label="Azienda">
              {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
            </select>
            <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Anno">
              {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
            </select>
            <select className="select" value={month} onChange={(e) => setMonth(Number(e.target.value))} aria-label="Periodo">
              {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>Gen–{m}</option>)}
            </select>
            <button className="btn btn--primary" onClick={() => setShowImport(true)} disabled={!cid}>
              <Upload size={14} /> Importa consuntivi
            </button>
          </>
        }
      />

      {!cid && (
        <EmptyState title="Nessuna azienda nel workspace" action={<a className="btn btn--primary btn--sm" href="/companies">Crea la prima azienda</a>}>
          Il controllo di gestione lavora sui consuntivi di un'azienda.
        </EmptyState>
      )}

      {overview.isLoading && <><Skeleton kind="stats" rows={4} /><Skeleton rows={6} /></>}
      {overview.error && <ErrorBanner error={overview.error} />}
      {ov && (
        <>
          <Alerts alerts={ov.alerts} />

          <div className="stat-grid">
            <Stat hero icon={resultNeg ? <TrendingDown size={14} /> : <TrendingUp size={14} />} label="Risultato gestionale"
                  value={<Signed v={ov.result} />} hint={<>Margine <Value v={ov.margin_percent} suffix="%" /> · non è EBITDA · {ov.period.label}</>} />
            <Stat icon={<BarChart3 size={14} />} label="Ricavi disponibili" value={<Value v={ov.revenue} />}
                  hint={<>vs budget <Signed v={ov.budget.revenue_variance} /></>} />
            <Stat icon={<Layers3 size={14} />} label="Costi disponibili" value={<Value v={ov.costs} />}
                  hint={<>vs budget <Signed v={ov.budget.cost_variance} invert /></>} />
            <Stat icon={<Database size={14} />} label="Copertura dati"
                  value={<>{ov.quality.covered_months}<span className="muted text-sm">/{ov.quality.expected_months}</span></>}
                  hint={<><Badge tone={ov.quality.status === "empty" ? "neutral" : "warning"}>{ov.quality.status === "empty" ? "Nessuna fonte" : "Parziale"}</Badge> {ov.trace.source_count} fonti</>}
                  tone={ov.quality.status === "empty" ? "warn" : undefined} />
          </div>

          <div className="grid-2">
            <Section title="Andamento mensile · consuntivo vs budget">
              <MonthlyChart monthly={ov.monthly} />
            </Section>
            <Section title="Budget vs consuntivo" flush
                     footer={<>Confronto con {ov.comparison.period.label}: ricavi <Value v={ov.comparison.revenue} /> · Δ ricavi <Signed v={ov.comparison.revenue_change_percent} suffix="%" /> · Δ costi <Signed v={ov.comparison.cost_change_percent} invert suffix="%" /></>}>
              <table className="table table--flush table--static">
                <thead>
                  <tr><th></th><th className="th--num">Budget</th><th className="th--num">Consuntivo</th><th className="th--num">Scostamento</th></tr>
                </thead>
                <tbody>
                  {(["revenue", "costs", "result"] as const).map((k) => {
                    const variance = ov.budget[`${k === "costs" ? "cost" : k}_variance` as keyof typeof ov.budget] as string | null;
                    return (
                      <tr key={k}>
                        <td className="table__primary">{{ revenue: "Ricavi", costs: "Costi", result: "Risultato" }[k]}</td>
                        <td className="td--num"><Value v={ov.budget[k]} /></td>
                        <td className="td--num"><Value v={ov[k]} /></td>
                        <td className="td--num"><Signed v={variance} invert={k === "costs"} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Section>
          </div>

          <div className="grid-2 mt-4">
            <Section title="Costi per categoria">
              {ov.cost_categories.length === 0 ? (
                <EmptyState title="Nessun costo nel periodo">Importa i consuntivi per vedere la distribuzione dei costi.</EmptyState>
              ) : (
                <div className="funnel">
                  {ov.cost_categories.map((c, i) => {
                    const max = Number(ov.cost_categories[0].amount);
                    return (
                      <div className="funnel__row" key={c.category}>
                        <span className="funnel__label">{c.category}</span>
                        <div className="funnel__track">
                          <div className={`funnel__bar ${i % 2 ? "mchart__bar--cost" : "mchart__bar--rev"}`} style={{ width: `${(Number(c.amount) / max) * 100}%` }} />
                        </div>
                        <span className="funnel__meta num">{money(c.amount)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </Section>
            <Section title={`Budget mensile ${year}`} flush footer="Versionato: ogni salvataggio crea una nuova versione, nulla viene sovrascritto.">
              <BudgetEditor rows={budgets.data ?? []} through={month} onSave={(b) => saveBudget.mutate(b)} busy={saveBudget.isPending} />
            </Section>
          </div>

          <div className="grid-2 mt-4">
            <Section title="Margine di contribuzione e break-even"
                     footer={contribution.data ? <>Formula <span className="mono">{contribution.data.trace.formula_version}</span> · break-even = costi fissi / indice di margine · non è un margine civilistico</> : undefined}>
              {contribution.isLoading && <Skeleton rows={5} />}
              {contribution.data && (
                <>
                  <div className="grid-auto grid-auto--sm">
                    <Tile label="Ricavi" value={<Value v={contribution.data.revenue} />} />
                    <Tile label="Costi variabili" value={<Value v={contribution.data.variable_costs} />} />
                    <Tile label="Costi fissi" value={<Value v={contribution.data.fixed_costs} />} />
                    <Tile label="Margine di contribuzione" value={<Value v={contribution.data.contribution_margin} />}
                          hint={contribution.data.contribution_margin_percent ? `${contribution.data.contribution_margin_percent}% dei ricavi` : undefined} icon={<Target size={12} />} />
                    <Tile label="Break-even" value={<Value v={contribution.data.break_even_revenue} />} hint="ricavi di pareggio" />
                    <Tile label="Copertura pareggio"
                          value={contribution.data.break_even_coverage ? `${(Number(contribution.data.break_even_coverage) * 100).toFixed(1)}%` : <NA />}
                          tone={contribution.data.break_even_coverage ? (Number(contribution.data.break_even_coverage) < 1 ? "danger" : "success") : undefined} />
                  </div>
                  {contribution.data.reasons.length > 0 && (
                    <Callout tone="neutral" title="Perché alcuni valori mancano">
                      <ul className="mgmt-issues">{contribution.data.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                    </Callout>
                  )}
                  {contribution.data.cost_centers.length > 0 && (
                    <>
                      <div className="card__title mt-4">Per centro di costo</div>
                      <table className="table table--dense table--static">
                        <thead>
                          <tr><th>Centro</th><th className="th--num">Ricavi</th><th className="th--num">Costi</th><th className="th--num">Risultato</th></tr>
                        </thead>
                        <tbody>
                          {contribution.data.cost_centers.map((c) => (
                            <tr key={c.cost_center_id ?? "unassigned"}>
                              <td className="table__primary">{c.code ? `${c.code} · ${c.name}` : c.name}</td>
                              <td className="td--num"><Value v={c.revenue} /></td>
                              <td className="td--num"><Value v={c.costs} /></td>
                              <td className="td--num"><Signed v={c.result} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  )}
                </>
              )}
            </Section>

            <Section title="Classificazione costi e centri di costo" footer={categories.data?.note}>
              <CostCenterForm busy={addCostCenter.isPending} onAdd={(p) => addCostCenter.mutate(p)} />
              {categories.data?.categories.length === 0 ? (
                <EmptyState title="Nessuna categoria">Importa prima i consuntivi: le categorie compaiono dai dati.</EmptyState>
              ) : (
                <table className="table table--dense table--static">
                  <thead>
                    <tr><th>Categoria</th><th>Tipo</th><th>Natura</th><th>Centro di costo</th></tr>
                  </thead>
                  <tbody>
                    {categories.data?.categories.map((c) => (
                      <tr key={c.id}>
                        <td className="table__primary">{c.name}</td>
                        <td><Badge tone={c.kind === "revenue" ? "success" : "neutral"}>{c.kind === "revenue" ? "Ricavo" : "Costo"}</Badge></td>
                        <td>
                          {c.kind === "cost" ? (
                            <select className="select select--sm" aria-label={`Natura del costo ${c.name}`}
                                    value={c.cost_nature ?? ""} disabled={classify.isPending}
                                    onChange={(e) => classify.mutate({
                                      id: c.id, cost_nature: e.target.value || null,
                                      cost_center_id: c.cost_center_id,
                                    })}>
                              <option value="">Non classificato</option>
                              <option value="variable">Variabile</option>
                              <option value="fixed">Fisso</option>
                            </select>
                          ) : <span className="muted">—</span>}
                        </td>
                        <td>
                          <select className="select select--sm" aria-label={`Centro di costo per ${c.name}`}
                                  value={c.cost_center_id ?? ""} disabled={classify.isPending}
                                  onChange={(e) => classify.mutate({
                                    id: c.id, cost_nature: c.cost_nature,
                                    cost_center_id: e.target.value || null,
                                  })}>
                            <option value="">Non attribuito</option>
                            {costCenters.data?.filter((cc) => cc.is_active).map((cc) => (
                              <option key={cc.id} value={cc.id}>{cc.code} · {cc.name}</option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
          </div>

          <details className="mt-4">
            <summary className="eyebrow eyebrow--muted">Qualità e provenienza dei dati ({ov.quality.issues.length})</summary>
            <Section tone="section" className="mt-2">
              <ul className="mgmt-issues">{ov.quality.issues.map((i) => <li key={i}>{i}</li>)}</ul>
              <KV columns={3} items={[
                { k: "Formula", v: <span className="mono">{ov.trace.formula_version}</span> },
                { k: "Fonti tracciate", v: ov.trace.source_count },
                { k: "Import", v: <>{imports.data?.length ?? 0}{imports.data?.[0] && <> · ultimo {dateTimeIt(imports.data[0].created_at)} ({imports.data[0].filename}, {imports.data[0].row_count} righe)</>}</> },
              ]} />
            </Section>
          </details>
        </>
      )}

      {showImport && (
        <Modal
          title="Importa consuntivi"
          subtitle="CSV atomico e idempotente · solo EUR · le correzioni avvengono con nuovi import tracciati"
          size="lg"
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
          <Callout tone="info" title="Formato atteso">
            Intestazione <span className="mono">source_id,date,kind,category,amount,currency</span>. Righe con <span className="mono">source_id</span> già presente e stesso contenuto vengono ignorate; con contenuto diverso vengono rifiutate.
          </Callout>
          <textarea className="textarea mono" rows={12} value={csv} onChange={(e) => setCsv(e.target.value)} spellCheck={false} aria-label="Contenuto CSV" />
        </Modal>
      )}
    </>
  );
}

function CostCenterForm({ onAdd, busy }: {
  onAdd: (p: { code: string; name: string }) => void; busy: boolean;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const valid = /^[A-Za-z0-9_.\-]+$/.test(code) && name.trim().length >= 2;
  return (
    <div className="toolbar">
      <input className="input input--sm mono" placeholder="Codice (es. CDC-PROD)"
             value={code} onChange={(e) => setCode(e.target.value)} aria-label="Codice centro di costo" />
      <input className="input input--sm" placeholder="Nome (es. Produzione)"
             value={name} onChange={(e) => setName(e.target.value)} aria-label="Nome centro di costo" />
      <button className="btn btn--ghost btn--sm nowrap" disabled={!valid || busy}
              onClick={() => { onAdd({ code, name: name.trim() }); setCode(""); setName(""); }}>
        + Centro di costo
      </button>
    </div>
  );
}

function BudgetEditor({ rows, through, onSave, busy }: {
  rows: BudgetRow[]; through: number; busy: boolean;
  onSave: (b: { month: number; revenue: string; costs: string }) => void;
}) {
  const [draft, setDraft] = useState<Record<number, { revenue: string; costs: string }>>({});
  const byMonth = Object.fromEntries(rows.map((r) => [r.month, r]));
  return (
    <table className="table table--flush table--dense table--static">
      <thead><tr><th>Mese</th><th className="th--num">Ricavi</th><th className="th--num">Costi</th><th>Versione</th><th></th></tr></thead>
      <tbody>
        {Array.from({ length: through }, (_, i) => i + 1).map((m) => {
          const cur = byMonth[m];
          const d = draft[m] ?? { revenue: cur?.revenue ?? "", costs: cur?.costs ?? "" };
          const dirty = d.revenue !== (cur?.revenue ?? "") || d.costs !== (cur?.costs ?? "");
          return (
            <tr key={m} className={dirty ? "is-selected" : undefined}>
              <td className="table__primary">{MONTHS[m]}</td>
              <td><input className="input input--sm input--num" value={d.revenue} placeholder="n.d." aria-label={`Budget ricavi ${MONTHS[m]}`} onChange={(e) => setDraft({ ...draft, [m]: { ...d, revenue: e.target.value } })} /></td>
              <td><input className="input input--sm input--num" value={d.costs} placeholder="n.d." aria-label={`Budget costi ${MONTHS[m]}`} onChange={(e) => setDraft({ ...draft, [m]: { ...d, costs: e.target.value } })} /></td>
              <td className="muted text-xs">{cur ? `v${cur.version}` : "—"}</td>
              <td className="right">
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
