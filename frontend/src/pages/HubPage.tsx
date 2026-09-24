import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { api } from "../api/client";
import type { ActionSignal, Hub, HubEntry } from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { money } from "../lib/format";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];

const HEALTH_LABEL: Record<HubEntry["health"]["status"], string> = {
  critical: "Critica",
  attention: "Attenzione",
  data_incomplete: "Dati incompleti",
  not_calculable: "Non valutabile",
  ok: "Nessun segnale",
};

/** Decimal string or the explicit "no evidence" marker — never a fake 0. */
function Val({ v, suffix }: { v: string | null; suffix?: string }) {
  if (v == null) return <span className="tre-null" title="Nessuna evidenza disponibile: non è zero">n.d.</span>;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

function Health({ health }: { health: HubEntry["health"] }) {
  return (
    <span className={`health health--${health.status}`} title={health.reason}>
      <i className="health__dot" />
      {HEALTH_LABEL[health.status]}
    </span>
  );
}

export function ActionList({ actions, onOpen }: {
  actions: ActionSignal[];
  onOpen?: (companyId: string) => void;
}) {
  const icon = { critical: ShieldAlert, warning: AlertTriangle, info: Info };
  if (!actions.length) {
    return <EmptyState>Nessun segnale deterministico attivo sulle fonti disponibili.</EmptyState>;
  }
  return (
    <div className="hub__actions">
      {actions.map((a, i) => {
        const Icon = icon[a.severity];
        return (
          <div className={`action action--${a.severity}`} key={`${a.company_id ?? "x"}-${a.code}-${i}`}>
            <i className="action__edge" />
            <div>
              {a.company_name && (
                <div className="action__company">
                  {onOpen ? (
                    <a role="button" tabIndex={0}
                       onClick={() => a.company_id && onOpen(a.company_id)}
                       onKeyDown={(e) => e.key === "Enter" && a.company_id && onOpen(a.company_id)}>
                      {a.company_name}
                    </a>
                  ) : a.company_name}
                </div>
              )}
              <div className="action__title">
                <Icon size={13} style={{ marginRight: 5, verticalAlign: -2 }} />
                {a.title}
              </div>
              <div className="action__msg">{a.message}</div>
              <div className="action__formula mono">
                {a.formula} · {a.formula_version}
              </div>
            </div>
            <div className="action__side">
              {a.action_required && <Badge tone="warning">azione richiesta</Badge>}
              <span className="muted mono" style={{ fontSize: "0.7rem" }}>p{a.priority}</span>
              <span className="muted" style={{ fontSize: "0.7rem" }}>{a.category}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function HubPage() {
  const navigate = useNavigate();
  const [year, setYear] = useState(2026);
  const [month, setMonth] = useState(6);
  const [onlyActionable, setOnlyActionable] = useState(false);

  const hub = useQuery({
    queryKey: ["hub", year, month],
    queryFn: () => api.get<Hub>(`/cockpit/hub?year=${year}&through_month=${month}`),
  });

  if (hub.isLoading) return <Spinner />;
  if (hub.error) return <ErrorBanner error={hub.error} />;
  const data = hub.data!;
  const actions = onlyActionable ? data.actions.filter((a) => a.action_required) : data.actions;
  const open = (companyId: string) => navigate(`/cockpit/${companyId}`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Control hub</h1>
          <div className="page-head__meta">
            Quale azienda guardare per prima, e perché — solo segnali deterministici con formula e fonti.
          </div>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90 }}>
            {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
          </select>
          <select className="select" value={month} onChange={(e) => setMonth(Number(e.target.value))} style={{ width: 120 }}>
            {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>Gen–{m}</option>)}
          </select>
        </div>
      </div>

      <div className="kpi-grid">
        <Card className="kpi kpi--edge-primary">
          <div className="kpi__label">Aziende gestite</div>
          <div className="kpi__value">{data.counters.companies}</div>
          <div className="kpi__hint">{data.counters.companies_needing_attention} richiedono attenzione</div>
        </Card>
        <Card className={`kpi ${data.counters.critical ? "kpi--hero kpi--edge-danger kpi--alert" : "kpi--edge-warn"}`}>
          <div className="kpi__label">Segnali critici</div>
          <div className="kpi__value">{data.counters.critical}</div>
          <div className="kpi__hint">{data.counters.warning} attenzione · {data.counters.info} informativi</div>
        </Card>
        <Card className="kpi kpi--edge-teal">
          <div className="kpi__label">Azioni da decidere</div>
          <div className="kpi__value">{data.counters.action_required}</div>
          <div className="kpi__hint">approvazione umana richiesta</div>
        </Card>
        <Card className="kpi kpi--edge-accent">
          <div className="kpi__label">Data di analisi</div>
          <div className="kpi__value" style={{ fontSize: "1.1rem" }}>{data.as_of}</div>
          <div className="kpi__hint">orizzonte cassa {data.horizon_days} giorni</div>
        </Card>
      </div>

      <Card className="card__pad">
        <div className="card__title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Action center · priorità deterministica</span>
          <label className="muted" style={{ fontSize: "0.75rem", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>
            <input type="checkbox" checked={onlyActionable} onChange={(e) => setOnlyActionable(e.target.checked)} />{" "}
            solo azioni richieste
          </label>
        </div>
        <ActionList actions={actions} onOpen={open} />
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
          {data.priority.formula} · <span className="mono">{data.priority.version}</span>
        </div>
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Portafoglio aziende</div>
        {data.companies.length === 0 ? (
          <EmptyState>Nessuna azienda in questo workspace.</EmptyState>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Azienda</th>
                <th>Stato</th>
                <th style={{ textAlign: "right" }}>EW</th>
                <th style={{ textAlign: "right" }}>Cassa</th>
                <th style={{ textAlign: "right" }}>Cassa negativa</th>
                <th style={{ textAlign: "right" }}>Crediti scaduti</th>
                <th style={{ textAlign: "right" }}>Risultato gest.</th>
                <th style={{ textAlign: "right" }}>Copertura</th>
                <th style={{ textAlign: "right" }}>Scadenza IVA</th>
                <th style={{ textAlign: "right" }}>Da riconciliare</th>
                <th>Perché ora</th>
              </tr>
            </thead>
            <tbody>
              {data.companies.map((e) => (
                <tr key={e.company.id} onClick={() => open(e.company.id)}>
                  <td>
                    <div>{e.company.legal_name}</div>
                    <div className="muted" style={{ fontSize: "0.72rem" }}>
                      {e.company.vat_number ?? "P.IVA n.d."}{e.company.region ? ` · ${e.company.region}` : ""}
                    </div>
                  </td>
                  <td><Health health={e.health} /></td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {e.controlling.open_alerts > 0 ? (
                      <Badge tone={e.controlling.critical_alerts > 0 ? "danger" : "warning"}>
                        {e.controlling.open_alerts}
                        {e.controlling.critical_alerts > 0 ? ` (${e.controlling.critical_alerts} crit.)` : ""}
                      </Badge>
                    ) : <span className="muted">0</span>}
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}><Val v={e.cash.position} /></td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {e.cash.first_negative_date ? (
                      <span className="tre-neg">{e.cash.first_negative_date} ({e.cash.days_to_negative}g)</span>
                    ) : <span className="muted">—</span>}
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    <Val v={e.cash.overdue_receivables} />
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}><Val v={e.economics.result} /></td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {e.economics.covered_months}/{e.economics.expected_months}
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {e.fiscal.next_obligation?.due_date ? (
                      <>
                        {e.fiscal.next_obligation.due_date}
                        <div className="muted" style={{ fontSize: "0.7rem" }}>
                          <Val v={e.fiscal.next_obligation.amount} />
                        </div>
                      </>
                    ) : e.fiscal.pending_entries > 0 ? (
                      <span className="muted">{e.fiscal.pending_entries} voci da verificare</span>
                    ) : <span className="muted">—</span>}
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {e.cash.unreconciled_transactions || <span className="muted">0</span>}
                  </td>
                  <td style={{ fontSize: "0.72rem", maxWidth: 220 }}>
                    {e.top_signal
                      ? <span title={e.top_signal}>{e.signal_count} segnali · {e.top_signal}</span>
                      : <span className="muted">{e.signal_count} segnali</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>{data.aggregation_note}</div>
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Limitazioni dichiarate</div>
        <ul className="mgmt-issues">
          {data.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </Card>
    </>
  );
}
