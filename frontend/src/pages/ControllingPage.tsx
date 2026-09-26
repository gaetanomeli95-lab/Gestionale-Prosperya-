import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle, ArrowRight, Gauge, Info, Layers, ShieldAlert, Sparkles, TrendingDown, Wallet,
} from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  AlertsResponse, CompanyListItem, ControllingAlert, ControllingSnapshot,
  DebtFacility, DebtLine, DetectionResult, EwRulesResponse, FacilitiesResponse,
  Page, ScenarioPresets, ScenarioResult,
} from "../api/types";
import {
  Badge, Callout, Dot, EmptyState, ErrorBanner, KV, NA, PageHeader, Row, Section, Skeleton,
  Stat, Tabs, Tile, toast,
} from "../components/ui";
import { dateIt, money } from "../lib/format";
import { DebtTab, EarlyWarningTab } from "./controlling/sections";
import {
  FacilityModal, InstalmentModal, QualityTab, ScenariosTab, SettleModal, TransitionModal,
} from "./controlling/scenarios";
import {
  CERTAINTY_LABEL, CERTAINTY_TONE, KIND_LABEL, Metric, MetricBadge, NATURE_LABEL, Reasons,
  RUNWAY_LABEL, SEVERITY_LABEL, SEVERITY_TONE, Val, trendLabel,
} from "./controlling/shared";

const WRITE_ROLES = ["admin", "management", "consultant", "backoffice", "client_admin", "client_operator"];

type Tab = "panoramica" | "redditivita" | "liquidita" | "debito" | "early_warning" | "scenari" | "qualita";

const SEVERITY_ICON = { critical: ShieldAlert, warning: AlertTriangle, info: Info };

export default function ControllingPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>("panoramica");
  const [actionError, setActionError] = useState<unknown>(null);
  const [transitionFor, setTransitionFor] = useState<{ alert: ControllingAlert; action: "resolve" | "dismiss" } | null>(null);
  const [showFacility, setShowFacility] = useState(false);
  const [instalmentFor, setInstalmentFor] = useState<DebtFacility | null>(null);
  const [settleFor, setSettleFor] = useState<DebtLine | null>(null);
  const [scenarioResult, setScenarioResult] = useState<ScenarioResult | null>(null);
  const [scenarioResults, setScenarioResults] = useState<Record<string, ScenarioResult>>({});
  const [scenarioForm, setScenarioForm] = useState<Record<string, string>>({
    label: "CUSTOM", revenue_change_pct: "0", collection_delay_days: "0",
    supplier_delay_days: "0", fixed_cost_monthly_delta: "0",
    variable_cost_change_pct: "0", debt_service_change_pct: "0",
  });

  const canWrite = !!user && WRITE_ROLES.includes(user.role);

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });
  const cid = params.get("company") || companies.data?.items[0]?.id || "";
  const setCompany = (id: string) => setParams(id ? { company: id } : {});

  const snapshot = useQuery({
    queryKey: ["controlling", cid],
    queryFn: () => api.get<ControllingSnapshot>(`/controlling/companies/${cid}/snapshot`),
    enabled: !!cid,
  });
  const facilities = useQuery({
    queryKey: ["controlling-facilities", cid],
    queryFn: () => api.get<FacilitiesResponse>(`/controlling/companies/${cid}/facilities`),
    enabled: !!cid && tab === "debito",
  });
  const alerts = useQuery({
    queryKey: ["controlling-alerts", cid],
    queryFn: () => api.get<AlertsResponse>(`/controlling/companies/${cid}/alerts`),
    enabled: !!cid && tab === "early_warning",
  });
  const rules = useQuery({
    queryKey: ["controlling-rules"],
    queryFn: () => api.get<EwRulesResponse>("/controlling/rules"),
    enabled: tab === "early_warning",
  });
  const presets = useQuery({
    queryKey: ["controlling-presets", cid],
    queryFn: () => api.get<ScenarioPresets>(`/controlling/companies/${cid}/scenarios/presets`),
    enabled: !!cid && tab === "scenari",
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["controlling", cid] });
    qc.invalidateQueries({ queryKey: ["controlling-facilities", cid] });
    qc.invalidateQueries({ queryKey: ["controlling-alerts", cid] });
    qc.invalidateQueries({ queryKey: ["hub"] });
    qc.invalidateQueries({ queryKey: ["cockpit"] });
  };
  const onError = (e: unknown) => setActionError(e);

  const evaluate = useMutation({
    mutationFn: () => api.post<DetectionResult>(`/controlling/companies/${cid}/alerts/evaluate`),
    onSuccess: (r) => {
      setActionError(null); refresh();
      toast(`Segnali rivalutati: ${r.counters.created} nuovi, ${r.counters.auto_resolved} risolti automaticamente`);
    },
    onError,
  });
  const transition = useMutation({
    mutationFn: (payload: { alertId: string; action: string; note?: string }) =>
      api.post<ControllingAlert>(
        `/controlling/companies/${cid}/alerts/${payload.alertId}/${payload.action}`,
        payload.note ? { note: payload.note } : {}),
    onSuccess: (_r, payload) => {
      setTransitionFor(null); setActionError(null); refresh();
      toast(payload.action === "acknowledge" ? "Segnale preso in carico"
        : payload.action === "resolve" ? "Segnale risolto" : "Segnale archiviato");
    },
    onError,
  });
  const createFacility = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<DebtFacility>(`/controlling/companies/${cid}/facilities`, payload),
    onSuccess: () => { setShowFacility(false); setActionError(null); refresh(); toast("Linea di debito creata"); },
    onError,
  });
  const addInstalment = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<DebtLine>(
        `/controlling/companies/${cid}/facilities/${instalmentFor!.id}/instalments`, payload),
    onSuccess: () => { setInstalmentFor(null); setActionError(null); refresh(); toast("Rata aggiunta"); },
    onError,
  });
  const settle = useMutation({
    mutationFn: (payload: { action: string; settled_on?: string; note?: string }) =>
      api.post<DebtLine>(
        `/controlling/companies/${cid}/instalments/${settleFor!.id}/settle`, payload),
    onSuccess: () => { setSettleFor(null); setActionError(null); refresh(); toast("Rata regolata"); },
    onError,
  });
  const runScenario = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<ScenarioResult>(`/controlling/companies/${cid}/scenarios/run`, payload),
    onSuccess: (r) => {
      setScenarioResult(r);
      setScenarioResults((prev) => ({ ...prev, [r.label]: r }));
      setActionError(null);
      toast(`Scenario ${r.label} ricalcolato`, "info");
    },
    onError,
  });

  if (companies.error) return <ErrorBanner error={companies.error} />;
  const snap = snapshot.data;
  const openAlerts = snap?.counters.alerts_open ?? 0;
  const criticalOpen = snap?.alerts.some((a) => a.severity === "critical" && (a.status === "open" || a.status === "acknowledged")) ?? false;
  const qualityIssues = snap?.continuity.issues.length ?? 0;

  const tabs: { key: Tab; label: string; count?: number; tone?: string }[] = [
    { key: "panoramica", label: "Panoramica" },
    { key: "redditivita", label: "Redditività" },
    { key: "liquidita", label: "Liquidità & continuità" },
    { key: "debito", label: "Debito & DSCR", count: snap ? snap.counters.debt_lines_scheduled : undefined },
    { key: "early_warning", label: "Early warning", count: snap ? openAlerts : undefined,
      tone: openAlerts > 0 ? (criticalOpen ? "danger" : "warning") : undefined },
    { key: "scenari", label: "Scenari", count: Object.keys(scenarioResults).length || undefined },
    { key: "qualita", label: "Data quality", count: snap ? qualityIssues : undefined, tone: qualityIssues > 0 ? "warning" : undefined },
  ];

  return (
    <>
      <PageHeader
        hero
        eyebrow={snap ? `Finanza e controllo · analisi al ${dateIt(snap.as_of)}` : "Finanza e controllo"}
        title="Controlling & early warning"
        question="Cosa sta cambiando e perché? DSCR, continuità a 12 mesi e segnali CCII calcolati solo su obbligazioni datate."
        actions={
          <>
            <select className="select" value={cid} onChange={(e) => setCompany(e.target.value)} aria-label="Azienda"
                    disabled={companies.isLoading}>
              {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
            </select>
            {cid && <Link className="btn btn--ghost" to={`/cockpit/${cid}`}>Cockpit <ArrowRight size={14} /></Link>}
          </>
        }
      />

      {actionError != null && <div className="mb-4"><ErrorBanner error={actionError} /></div>}
      {snapshot.error && <div className="mb-4"><ErrorBanner error={snapshot.error} /></div>}

      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {(companies.isLoading || snapshot.isLoading) && (
        <>
          <Skeleton kind="stats" rows={4} />
          <Section><Skeleton kind="table" rows={5} /></Section>
        </>
      )}

      {!companies.isLoading && !cid && (
        <Section>
          <EmptyState title="Nessuna azienda nel workspace"
                      action={<Link className="btn btn--primary" to="/companies">Vai alle aziende</Link>}>
            Il controlling lavora per singola azienda: crea la prima anagrafica per iniziare.
          </EmptyState>
        </Section>
      )}

      {snap && (
        <>
          {tab === "panoramica" && <OverviewTab snap={snap} go={setTab} />}
          {tab === "redditivita" && <ProfitabilityTab snap={snap} />}
          {tab === "liquidita" && <ContinuityTab snap={snap} />}
          {tab === "debito" && (
            <DebtTab snap={snap} facilities={facilities.data} canWrite={canWrite}
                     onNewFacility={() => setShowFacility(true)}
                     onAddInstalment={setInstalmentFor}
                     onSettle={setSettleFor} />
          )}
          {tab === "early_warning" && (
            <EarlyWarningTab snap={snap} alerts={alerts.data} rules={rules.data}
                             canWrite={canWrite}
                             evaluating={evaluate.isPending}
                             onEvaluate={() => evaluate.mutate()}
                             onTransition={(alert, action) =>
                               action === "acknowledge"
                                 ? transition.mutate({ alertId: alert.id, action })
                                 : setTransitionFor({ alert, action })} />
          )}
          {tab === "scenari" && (
            <ScenariosTab presets={presets.data} canWrite={canWrite}
                          form={scenarioForm} setForm={setScenarioForm}
                          result={scenarioResult} results={scenarioResults}
                          running={runScenario.isPending}
                          onRun={(payload) => runScenario.mutate(payload)} />
          )}
          {tab === "qualita" && <QualityTab snap={snap} />}

          <div className="mt-5">
            <Callout tone="neutral">
              Nessun valore è una determinazione legale. Indicatori e segnali sono calcoli deterministici
              su dati dichiarati; le decisioni restano in capo all'operatore.
            </Callout>
          </div>
        </>
      )}

      {transitionFor && (
        <TransitionModal alert={transitionFor.alert} action={transitionFor.action}
                         pending={transition.isPending}
                         onClose={() => setTransitionFor(null)}
                         onSubmit={(note) => transition.mutate({
                           alertId: transitionFor.alert.id,
                           action: transitionFor.action, note })} />
      )}
      {showFacility && (
        <FacilityModal pending={createFacility.isPending}
                       onClose={() => setShowFacility(false)}
                       onSubmit={(p) => createFacility.mutate(p)} />
      )}
      {instalmentFor && (
        <InstalmentModal facility={instalmentFor} pending={addInstalment.isPending}
                         onClose={() => setInstalmentFor(null)}
                         onSubmit={(p) => addInstalment.mutate(p)} />
      )}
      {settleFor && (
        <SettleModal line={settleFor} pending={settle.isPending}
                     onClose={() => setSettleFor(null)}
                     onSubmit={(p) => settle.mutate(p)} />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Panoramica
// ---------------------------------------------------------------------------

function OverviewTab({ snap, go }: { snap: ControllingSnapshot; go: (t: Tab) => void }) {
  const openAlerts = snap.alerts.filter((a) => a.status === "open" || a.status === "acknowledged");
  const overdueRec = snap.trends.find((t) => t.metric === "overdue_receivables");
  const overduePay = snap.trends.find((t) => t.metric === "overdue_payables");
  const dscrLow = snap.dscr.value != null && Number(snap.dscr.value) < 1;
  const mos = snap.profitability.margin_of_safety;
  return (
    <>
      <div className="stat-grid">
        <Stat
          hero
          icon={<Gauge size={14} />}
          label={`DSCR prospettico · ${snap.dscr.horizon_days} giorni`}
          value={snap.dscr.value != null ? <span className="num">{snap.dscr.value}</span> : <NA />}
          hint={
            <span className="cluster">
              <MetricBadge status={snap.dscr.status} />
              {dscrLow ? "· sotto 1,0: il flusso non copre il servizio del debito" : snap.dscr.value != null ? "· copre il servizio del debito" : null}
            </span>
          }
          onClick={() => go("debito")}
        />
        <Stat
          icon={<Wallet size={14} />}
          label="Cassa minima proiettata"
          value={<Val v={snap.continuity.minimum_projected_balance} />}
          tone={snap.continuity.first_negative_date ? "danger" : undefined}
          hint={snap.continuity.first_negative_date
            ? `negativa dal ${dateIt(snap.continuity.first_negative_date)}`
            : `autonomia ${RUNWAY_LABEL[snap.continuity.runway_status]}`}
          onClick={() => go("liquidita")}
        />
        <Stat
          icon={<TrendingDown size={14} />}
          label="Margine di sicurezza"
          value={mos.value != null ? <span className="num">{mos.value}%</span> : <NA />}
          tone={mos.value != null && Number(mos.value) < 0 ? "danger" : undefined}
          hint={<MetricBadge status={mos.status} />}
          onClick={() => go("redditivita")}
        />
        <Stat
          icon={<ShieldAlert size={14} />}
          label="Segnali early warning"
          value={<span className="num">{snap.counters.alerts_open}</span>}
          tone={snap.counters.alerts_open > 0 ? "warn" : undefined}
          hint={`${snap.counters.rules_fired} regole scattate su ${snap.counters.rules_active} attive`}
          onClick={() => go("early_warning")}
        />
      </div>

      <div className="grid-2-1">
        <Section
          title="Segnali attivi"
          actions={
            <button className="btn btn--ghost btn--sm" onClick={() => go("early_warning")}>
              Gestisci <ArrowRight size={12} />
            </button>
          }
        >
          {openAlerts.length === 0 ? (
            <EmptyState title="Nessun segnale aperto" icon={<Sparkles size={20} strokeWidth={1.8} />}
                        action={<button className="btn btn--ghost btn--sm" onClick={() => go("early_warning")}>Apri early warning</button>}>
              La detection è un'azione esplicita: rivaluta i segnali dalla scheda Early warning per
              applicare le regole ai dati di oggi.
            </EmptyState>
          ) : (
            <div className="rows">
              {openAlerts.map((a) => {
                const Icon = SEVERITY_ICON[a.severity];
                return (
                  <Row
                    key={a.id}
                    tone={a.severity === "critical" ? "critical" : a.severity === "warning" ? "warning" : "info"}
                    leading={<Icon size={16} />}
                    title={a.title}
                    sub={<>{a.message}<div className="mt-1">{KIND_LABEL[a.kind]} · rilevato il {dateIt(a.detected_at)}</div></>}
                    trailing={<Badge tone={SEVERITY_TONE[a.severity]}>{SEVERITY_LABEL[a.severity]}</Badge>}
                    onClick={() => go("early_warning")}
                  />
                );
              })}
            </div>
          )}
        </Section>

        <Section
          title="Quadro sintetico"
          footer={<>Motore <span className="mono">{snap.engine_version}</span> · formule <span className="mono">{Object.values(snap.formula_versions).join(" / ")}</span></>}
        >
          <KV columns={1} items={[
            { k: "Saldo iniziale (cassa nota)", v: <span className="cluster"><Val v={snap.opening_balance} /><MetricBadge status={snap.opening_balance_status} /></span> },
            { k: "Crediti scaduti", v: <Val v={overdueRec?.current as string | null | undefined} /> },
            { k: "Debiti scaduti", v: <Val v={overduePay?.current as string | null | undefined} /> },
            { k: "Rate pianificate", v: <span className="num">{snap.counters.debt_lines_scheduled}</span> },
            { k: "Partite aperte", v: <span className="num">{snap.counters.open_items}</span> },
            { k: "Copertura continuità", v: <span className="num">{snap.continuity.coverage.months_with_data}/{snap.continuity.coverage.months_total} mesi con obbligazioni datate</span> },
          ]} />
        </Section>
      </div>

      <details className="mt-4">
        <summary className="eyebrow eyebrow--muted">Limitazioni dichiarate ({snap.limitations.length})</summary>
        <div className="mt-3"><Section tone="section"><Reasons items={snap.limitations} /></Section></div>
      </details>
    </>
  );
}

// ---------------------------------------------------------------------------
// Redditività
// ---------------------------------------------------------------------------

const DIRECTION_LABEL: Record<string, string> = {
  worsening: "in peggioramento", improving: "in miglioramento", flat: "stabile",
};
const DIRECTION_TONE: Record<string, string> = {
  worsening: "danger", improving: "success", flat: "neutral",
};

function TrendVal({ v }: { v: string | number | null }) {
  if (v == null) return <NA />;
  return <span className="num">{String(v)}</span>;
}

function ProfitabilityTab({ snap }: { snap: ControllingSnapshot }) {
  const c = snap.profitability.contribution;
  const mos = snap.profitability.margin_of_safety;
  return (
    <div className="grid-1-2">
      <Section
        title={<>Margine di contribuzione · {c.period.label}</>}
        footer={<>Formula <span className="mono">{c.trace.formula_version}</span> · {c.trace.source_count} fonti tracciate · non è un margine civilistico</>}
      >
        <div className="grid-auto grid-auto--sm">
          <Tile label="Ricavi" value={<Val v={c.revenue} />} />
          <Tile label="Costi variabili" value={<Val v={c.variable_costs} />} />
          <Tile label="Costi fissi" value={<Val v={c.fixed_costs} />} />
          <Tile label="Margine di contribuzione" value={<Val v={c.contribution_margin} />}
                tone={c.contribution_margin != null && Number(c.contribution_margin) < 0 ? "danger" : undefined}
                hint={c.contribution_margin_percent ? `${c.contribution_margin_percent}% dei ricavi` : undefined} />
          <Tile label="Ricavi di break-even" value={<Val v={c.break_even_revenue} />}
                tone={c.break_even_status === "not_calculable" ? "muted" : undefined}
                hint={c.break_even_status === "not_calculable" ? "non calcolabile con i dati attuali" : undefined} />
          <Metric label="Margine di sicurezza" m={mos} suffix="%" />
        </div>
        {c.reasons.length > 0 && <div className="mt-3"><Reasons items={c.reasons} /></div>}
      </Section>

      <Section
        title="Trend vs mese precedente"
        footer="Il confronto usa solo il mese precedente come baseline esplicita; senza baseline il trend non è stimato."
        flush
      >
        <table className="table table--flush table--static">
          <thead>
            <tr>
              <th>Indicatore</th>
              <th className="th--num">Attuale</th>
              <th className="th--num">Precedente</th>
              <th className="th--num">Delta</th>
              <th>Direzione</th>
            </tr>
          </thead>
          <tbody>
            {snap.trends.map((t) => (
              <tr key={t.metric}>
                <td>
                  <div className="table__primary">{trendLabel(t.metric)}</div>
                  <div className="table__sub mono">{t.metric}</div>
                </td>
                <td className="td--num"><TrendVal v={t.current} /></td>
                <td className="td--num"><TrendVal v={t.previous} /></td>
                <td className="td--num">{t.delta != null ? <span className="num">{String(t.delta)}</span> : <span className="muted">—</span>}</td>
                <td>
                  {t.status === "no_baseline" || !t.direction
                    ? <Dot tone="neutral">nessun baseline</Dot>
                    : <Dot tone={DIRECTION_TONE[t.direction]}>{DIRECTION_LABEL[t.direction]}</Dot>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Liquidità & continuità 12 mesi
// ---------------------------------------------------------------------------

function ContinuityTab({ snap }: { snap: ControllingSnapshot }) {
  const cont = snap.continuity;
  const negative = !!cont.first_negative_date;
  return (
    <>
      <div className="stat-grid">
        <Stat
          hero
          icon={<Wallet size={14} />}
          label="Minimo proiettato"
          value={<Val v={cont.minimum_projected_balance} />}
          hint={cont.minimum_projected_date ? `raggiunto il ${dateIt(cont.minimum_projected_date)}` : "data non determinabile"}
        />
        <Stat
          icon={<Layers size={14} />}
          label="Saldo iniziale"
          value={<Val v={cont.opening_balance} />}
          hint={<MetricBadge status={cont.opening_balance_status} />}
        />
        <Stat
          icon={<AlertTriangle size={14} />}
          label="Prima data negativa"
          tone={negative ? "danger" : "success"}
          value={cont.first_negative_date ? <span className="num">{dateIt(cont.first_negative_date)}</span> : "mai"}
          hint={cont.runway_days != null ? `tra ${cont.runway_days} giorni` : `autonomia ${RUNWAY_LABEL[cont.runway_status]}`}
        />
        <Stat
          icon={<Gauge size={14} />}
          label="Copertura dati"
          value={<span className="num">{cont.coverage.months_with_data}/{cont.coverage.months_total}</span>}
          hint="mesi con obbligazioni datate"
          tone={cont.coverage.months_with_data < cont.coverage.months_total ? "warn" : undefined}
        />
      </div>

      <Section
        title="Proiezione mensile su obbligazioni datate"
        footer={<>Formula <span className="mono">{cont.formula_version}</span> · motore <span className="mono">{cont.engine_version}</span></>}
        flush
      >
        <table className="table table--flush table--static">
          <thead>
            <tr>
              <th>Mese</th>
              <th className="th--num">Incassi</th>
              <th className="th--num">Uscite</th>
              <th>Dettaglio uscite</th>
              <th className="th--num">Netto</th>
              <th className="th--num">Saldo proiettato</th>
            </tr>
          </thead>
          <tbody>
            {cont.buckets.map((b) => (
              <tr key={b.label} className={!b.has_data ? "muted" : undefined}>
                <td>
                  <div className="table__primary">{b.label}</div>
                  <div className="table__sub">{b.has_data ? `${b.item_count} obbligazioni` : "nessuna obbligazione datata"}</div>
                </td>
                <td className="td--num"><Val v={b.inflows} /></td>
                <td className="td--num"><Val v={b.outflows} /></td>
                <td className="text-xs">
                  {Object.entries(b.outflow_by_nature).map(([k, v]) => (
                    <div key={k} className="muted">{NATURE_LABEL[k] ?? k}: <span className="num">{money(v)}</span></div>
                  ))}
                </td>
                <td className="td--num"><Val v={b.net} /></td>
                <td className="td--num">
                  {b.projected_balance != null
                    ? <Val v={b.projected_balance} />
                    : <NA title="Saldo iniziale non noto" />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {cont.issues.length > 0 && (
          <div className="section__body"><Callout tone="warning" title="Problemi rilevati"><Reasons items={cont.issues} /></Callout></div>
        )}
      </Section>

      <details className="mt-4">
        <summary className="eyebrow eyebrow--muted">Modello di certezza dei dati</summary>
        <div className="mt-3">
          <Section tone="section">
            <KV columns={1} items={Object.entries(cont.certainty_model).map(([k, v]) => ({
              k: <Badge tone={CERTAINTY_TONE[k] ?? "neutral"} dot={false}>{CERTAINTY_LABEL[k] ?? k}</Badge>, v,
            }))} />
          </Section>
        </div>
      </details>
    </>
  );
}
