import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  AlertsResponse, CompanyListItem, ControllingAlert, ControllingSnapshot,
  DebtFacility, DebtLine, DetectionResult, EwRulesResponse, FacilitiesResponse,
  Page, ScenarioPresets, ScenarioResult,
} from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { money } from "../lib/format";
import {
  DebtTab, EarlyWarningTab,
} from "./controlling/sections";
import {
  FacilityModal, InstalmentModal, QualityTab, ScenariosTab, SettleModal,
  TransitionModal,
} from "./controlling/scenarios";
import { Metric, MetricBadge, NATURE_LABEL, RUNWAY_LABEL, Val } from "./controlling/shared";

const WRITE_ROLES = ["admin", "management", "consultant", "backoffice", "client_admin", "client_operator"];

type Tab = "panoramica" | "redditivita" | "liquidita" | "debito" | "early_warning" | "scenari" | "qualita";

const TABS: { key: Tab; label: string }[] = [
  { key: "panoramica", label: "Panoramica" },
  { key: "redditivita", label: "Redditività" },
  { key: "liquidita", label: "Liquidità & continuità" },
  { key: "debito", label: "Debito & DSCR" },
  { key: "early_warning", label: "Early warning" },
  { key: "scenari", label: "Scenari" },
  { key: "qualita", label: "Data quality" },
];

const SEVERITY_LABEL: Record<string, string> = {
  critical: "critico", warning: "attenzione", info: "informativo",
};
const KIND_LABEL: Record<string, string> = {
  early_warning: "CCII / early warning", management: "gestionale",
};

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
    onSuccess: () => { setActionError(null); refresh(); },
    onError,
  });
  const transition = useMutation({
    mutationFn: (payload: { alertId: string; action: string; note?: string }) =>
      api.post<ControllingAlert>(
        `/controlling/companies/${cid}/alerts/${payload.alertId}/${payload.action}`,
        payload.note ? { note: payload.note } : {}),
    onSuccess: () => { setTransitionFor(null); setActionError(null); refresh(); },
    onError,
  });
  const createFacility = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<DebtFacility>(`/controlling/companies/${cid}/facilities`, payload),
    onSuccess: () => { setShowFacility(false); setActionError(null); refresh(); },
    onError,
  });
  const addInstalment = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<DebtLine>(
        `/controlling/companies/${cid}/facilities/${instalmentFor!.id}/instalments`, payload),
    onSuccess: () => { setInstalmentFor(null); setActionError(null); refresh(); },
    onError,
  });
  const settle = useMutation({
    mutationFn: (payload: { action: string; settled_on?: string; note?: string }) =>
      api.post<DebtLine>(
        `/controlling/companies/${cid}/instalments/${settleFor!.id}/settle`, payload),
    onSuccess: () => { setSettleFor(null); setActionError(null); refresh(); },
    onError,
  });
  const runScenario = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<ScenarioResult>(`/controlling/companies/${cid}/scenarios/run`, payload),
    onSuccess: (r) => {
      setScenarioResult(r);
      setScenarioResults((prev) => ({ ...prev, [r.label]: r }));
      setActionError(null);
    },
    onError,
  });

  if (companies.isLoading) return <Spinner />;
  if (companies.error) return <ErrorBanner error={companies.error} />;
  const snap = snapshot.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Controlling & early warning</h1>
          <div className="page-head__meta">
            Indicatori deterministici su obbligazioni datate: DSCR, continuità 12 mesi,
            segnali CCII. Nessun valore è una determinazione legale.
          </div>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <select className="select" value={cid} onChange={(e) => setCompany(e.target.value)} style={{ maxWidth: 280 }}>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <Link className="btn btn--ghost" to={`/cockpit/${cid}`}>Cockpit</Link>
        </div>
      </div>

      {actionError != null && <ErrorBanner error={actionError} />}
      {snapshot.error && <ErrorBanner error={snapshot.error} />}

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key}
                  className={`tab${tab === t.key ? " tab--active" : ""}`}
                  onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {snapshot.isLoading && <Spinner />}
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
  return (
    <>
      <div className="kpi-grid">
        <Card className={`kpi kpi--edge-primary ${snap.dscr.status === "available" && snap.dscr.value && Number(snap.dscr.value) < 1 ? "kpi--alert" : ""}`}>
          <div className="kpi__label">DSCR prospettico · {snap.dscr.horizon_days}g</div>
          <div className="kpi__value mono">{snap.dscr.value ?? "n.d."}</div>
          <div className="kpi__hint">
            <MetricBadge status={snap.dscr.status} /> · {snap.dscr.formula_version}
          </div>
        </Card>
        <Card className={`kpi kpi--edge-teal ${snap.continuity.first_negative_date ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Cassa minima proiettata</div>
          <div className="kpi__value mono"><Val v={snap.continuity.minimum_projected_balance} /></div>
          <div className="kpi__hint">
            {snap.continuity.first_negative_date
              ? <span className="tre-neg">negativa dal {snap.continuity.first_negative_date}</span>
              : `runway ${RUNWAY_LABEL[snap.continuity.runway_status]}`}
          </div>
        </Card>
        <Card className="kpi kpi--edge-accent">
          <div className="kpi__label">Margine di sicurezza</div>
          <div className="kpi__value mono">
            {snap.profitability.margin_of_safety.value != null
              ? `${snap.profitability.margin_of_safety.value}%` : "n.d."}
          </div>
          <div className="kpi__hint"><MetricBadge status={snap.profitability.margin_of_safety.status} /></div>
        </Card>
        <Card className={`kpi kpi--edge-warn ${snap.counters.alerts_open ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Segnali early warning</div>
          <div className="kpi__value">{snap.counters.alerts_open}</div>
          <div className="kpi__hint">
            {snap.counters.rules_fired} regole scattate su {snap.counters.rules_active} attive
          </div>
        </Card>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <Card className="card__pad">
          <div className="card__title">
            Segnali attivi
            <a role="button" className="muted" style={{ fontWeight: 400, fontSize: "0.72rem", marginLeft: 8, cursor: "pointer" }}
               onClick={() => go("early_warning")}>apri early warning →</a>
          </div>
          {openAlerts.length === 0 ? (
            <EmptyState>Nessun segnale aperto. La detection è un'azione esplicita (Rivaluta segnali).</EmptyState>
          ) : (
            <div className="hub__actions">
              {openAlerts.map((a) => (
                <div className={`action action--${a.severity}`} key={a.id}>
                  <i className="action__edge" />
                  <div>
                    <div className="action__title">
                      <ShieldAlert size={13} style={{ marginRight: 5, verticalAlign: -2 }} />
                      {a.title}
                    </div>
                    <div className="action__msg">{a.message}</div>
                    <div className="action__formula mono">
                      {a.rule_code} v{a.rule_version} · {a.formula_version} · rilevato il {a.detected_at}
                    </div>
                  </div>
                  <div className="action__side">
                    <Badge tone={a.severity === "critical" ? "danger" : "warning"}>
                      {SEVERITY_LABEL[a.severity]}
                    </Badge>
                    <span className="muted" style={{ fontSize: "0.7rem" }}>{KIND_LABEL[a.kind]}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="card__pad">
          <div className="card__title">Quadro sintetico</div>
          <div className="dl">
            <dt>Saldo iniziale (cassa nota)</dt>
            <dd className="mono">
              <Val v={snap.opening_balance} />{" "}
              <MetricBadge status={snap.opening_balance_status} />
            </dd>
            <dt>Crediti scaduti</dt>
            <dd className="mono"><Val v={overdueRec?.current as string | null} /></dd>
            <dt>Debiti scaduti</dt>
            <dd className="mono"><Val v={overduePay?.current as string | null} /></dd>
            <dt>Rate pianificate</dt>
            <dd className="mono">{snap.counters.debt_lines_scheduled}</dd>
            <dt>Partite aperte</dt>
            <dd className="mono">{snap.counters.open_items}</dd>
            <dt>Copertura continuità</dt>
            <dd className="mono">
              {snap.continuity.coverage.months_with_data}/{snap.continuity.coverage.months_total} mesi con obbligazioni datate
            </dd>
          </div>
          <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
            Motore <span className="mono">{snap.engine_version}</span> · formule{" "}
            <span className="mono">{Object.values(snap.formula_versions).join(" / ")}</span>
          </div>
        </Card>
      </div>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Limitazioni dichiarate</div>
        <ul className="mgmt-issues">
          {snap.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------------------
// Redditività
// ---------------------------------------------------------------------------

function ProfitabilityTab({ snap }: { snap: ControllingSnapshot }) {
  const c = snap.profitability.contribution;
  const mos = snap.profitability.margin_of_safety;
  return (
    <div className="grid-2">
      <Card className="card__pad">
        <div className="card__title">Margine di contribuzione · {c.period.label}</div>
        <div className="dl">
          <dt>Ricavi</dt><dd className="mono"><Val v={c.revenue} /></dd>
          <dt>Costi variabili</dt><dd className="mono"><Val v={c.variable_costs} /></dd>
          <dt>Costi fissi</dt><dd className="mono"><Val v={c.fixed_costs} /></dd>
          <dt>Margine di contribuzione</dt>
          <dd className="mono">
            <Val v={c.contribution_margin} />
            {c.contribution_margin_percent && <span className="muted"> ({c.contribution_margin_percent}%)</span>}
          </dd>
          <dt>Ricavi di break-even</dt>
          <dd className="mono">
            <Val v={c.break_even_revenue} />{" "}
            {c.break_even_status === "not_calculable" && <Badge tone="neutral">non calcolabile</Badge>}
          </dd>
          <Metric label="Margine di sicurezza" m={mos} suffix="%" />
        </div>
        {c.reasons.length > 0 && (
          <ul className="mgmt-issues">{c.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        )}
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
          Formula <span className="mono">{c.trace.formula_version}</span> · {c.trace.source_count} fonti tracciate
        </div>
      </Card>

      <Card className="card__pad">
        <div className="card__title">Trend vs mese precedente</div>
        <table className="table">
          <thead>
            <tr><th>Metrica</th><th style={{ textAlign: "right" }}>Attuale</th>
                <th style={{ textAlign: "right" }}>Precedente</th><th style={{ textAlign: "right" }}>Delta</th>
                <th>Direzione</th></tr>
          </thead>
          <tbody>
            {snap.trends.map((t) => (
              <tr key={t.metric} style={{ cursor: "default" }}>
                <td className="mono" style={{ fontSize: "0.78rem" }}>{t.metric}</td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {t.current != null ? String(t.current) : <span className="tre-null">n.d.</span>}
                </td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {t.previous != null ? String(t.previous) : <span className="tre-null">n.d.</span>}
                </td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {t.delta != null ? String(t.delta) : <span className="muted">—</span>}
                </td>
                <td>
                  {t.status === "no_baseline"
                    ? <Badge tone="neutral">nessun baseline</Badge>
                    : <Badge tone={t.direction === "worsening" ? "danger"
                                   : t.direction === "improving" ? "success" : "neutral"}>
                        {t.direction === "worsening" ? "in peggioramento"
                         : t.direction === "improving" ? "in miglioramento" : "stabile"}
                      </Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
          Il confronto usa solo il mese precedente come baseline esplicita; senza baseline il trend non è stimato.
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Liquidità & continuità 12 mesi
// ---------------------------------------------------------------------------

function ContinuityTab({ snap }: { snap: ControllingSnapshot }) {
  const cont = snap.continuity;
  return (
    <>
      <div className="kpi-grid">
        <Card className="kpi kpi--edge-primary">
          <div className="kpi__label">Saldo iniziale</div>
          <div className="kpi__value mono"><Val v={cont.opening_balance} /></div>
          <div className="kpi__hint"><MetricBadge status={cont.opening_balance_status} /></div>
        </Card>
        <Card className={`kpi kpi--edge-teal ${cont.first_negative_date ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Minimo proiettato</div>
          <div className="kpi__value mono"><Val v={cont.minimum_projected_balance} /></div>
          <div className="kpi__hint">{cont.minimum_projected_date ?? "—"}</div>
        </Card>
        <Card className={`kpi kpi--edge-warn ${cont.first_negative_date ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Prima data negativa</div>
          <div className="kpi__value" style={{ fontSize: "1.1rem" }}>
            {cont.first_negative_date ?? "mai nell'orizzonte"}
          </div>
          <div className="kpi__hint">
            {cont.runway_days != null ? `tra ${cont.runway_days} giorni` : RUNWAY_LABEL[cont.runway_status]}
          </div>
        </Card>
        <Card className="kpi kpi--edge-accent">
          <div className="kpi__label">Copertura dati</div>
          <div className="kpi__value">{cont.coverage.months_with_data}/{cont.coverage.months_total}</div>
          <div className="kpi__hint">mesi con obbligazioni datate</div>
        </Card>
      </div>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Proiezione mensile su obbligazioni datate</div>
        <table className="table">
          <thead>
            <tr>
              <th>Mese</th>
              <th style={{ textAlign: "right" }}>Incassi</th>
              <th style={{ textAlign: "right" }}>Uscite</th>
              <th>Dettaglio uscite</th>
              <th style={{ textAlign: "right" }}>Netto</th>
              <th style={{ textAlign: "right" }}>Saldo proiettato</th>
            </tr>
          </thead>
          <tbody>
            {cont.buckets.map((b) => (
              <tr key={b.label} style={{ cursor: "default" }}
                  className={!b.has_data ? "muted" : undefined}>
                <td className="mono">{b.label}</td>
                <td className="mono" style={{ textAlign: "right" }}><Val v={b.inflows} /></td>
                <td className="mono" style={{ textAlign: "right" }}><Val v={b.outflows} /></td>
                <td style={{ fontSize: "0.75rem" }}>
                  {Object.entries(b.outflow_by_nature).map(([k, v]) => (
                    <div key={k} className="muted">{NATURE_LABEL[k] ?? k}: {money(v)}</div>
                  ))}
                  {!b.has_data && <span className="muted">nessuna obbligazione datata</span>}
                </td>
                <td className="mono" style={{ textAlign: "right" }}><Val v={b.net} /></td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {b.projected_balance != null
                    ? <span className={Number(b.projected_balance) < 0 ? "tre-neg" : ""}>{money(b.projected_balance)}</span>
                    : <span className="tre-null" title="Saldo iniziale non noto">n.d.</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {cont.issues.length > 0 && (
          <ul className="mgmt-issues" style={{ marginTop: 10 }}>
            {cont.issues.map((i) => <li key={i}>{i}</li>)}
          </ul>
        )}
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Modello di certezza dei dati</div>
        <div className="dl">
          {Object.entries(cont.certainty_model).map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt>
                <Badge tone={{ actual: "success", contracted: "primary",
                              forecast: "info", assumption: "warning" }[k] ?? "neutral"}>{k}</Badge>
              </dt>
              <dd>{v}</dd>
            </div>
          ))}
        </div>
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
          Formula <span className="mono">{cont.formula_version}</span> · motore{" "}
          <span className="mono">{cont.engine_version}</span>
        </div>
      </Card>
    </>
  );
}
