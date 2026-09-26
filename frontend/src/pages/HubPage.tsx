import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowRight, Building2, CalendarClock, Info, ShieldAlert, Siren, Sparkles } from "lucide-react";
import { api } from "../api/client";
import type { ActionSignal, Hub, HubEntry } from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner, Stat } from "../components/ui";
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

const CATEGORY_LABEL: Record<string, string> = {
  treasury: "Tesoreria", early_warning: "Early warning", fiscal: "Fisco", controlling: "Controlling",
  management: "Controllo di gestione", billing: "Fatturazione", funding: "Finanza agevolata",
  practices: "Pratiche", documents: "Documenti", data_quality: "Qualità dati",
};

export function ActionList({ actions, onOpen }: {
  actions: ActionSignal[];
  onOpen?: (companyId: string) => void;
}) {
  const icon = { critical: ShieldAlert, warning: AlertTriangle, info: Info };
  if (!actions.length) {
    return (
      <EmptyState title="Nessun segnale attivo" icon={<Sparkles size={20} strokeWidth={1.8} />}>
        Sulle fonti disponibili non emerge nulla che richieda un intervento deterministico.
      </EmptyState>
    );
  }
  return (
    <div className="hub__actions">
      {actions.map((a, i) => {
        const Icon = icon[a.severity];
        const clickable = Boolean(onOpen && a.company_id);
        const open = () => clickable && onOpen!(a.company_id!);
        return (
          <div
            className={`action action--${a.severity}${clickable ? " action--link" : ""}`}
            key={`${a.company_id ?? "x"}-${a.code}-${i}`}
            onClick={open}
            onKeyDown={(e) => e.key === "Enter" && open()}
            role={clickable ? "link" : undefined}
            tabIndex={clickable ? 0 : undefined}
            aria-label={clickable ? `${a.title} — apri il cockpit di ${a.company_name}` : undefined}
          >
            <i className="action__edge" />
            <div>
              {a.company_name && <div className="action__company">{a.company_name}</div>}
              <div className="action__title"><Icon size={15} strokeWidth={2} />{a.title}</div>
              <div className="action__msg">{a.message}</div>
              <div className="action__formula" title="Formula deterministica e versione">
                {a.formula} · {a.formula_version}
              </div>
            </div>
            <div className="action__side">
              {a.action_required
                ? <Badge tone="warning">Decisione richiesta</Badge>
                : <Badge tone="neutral">Informativo</Badge>}
              <span className="muted" style={{ fontSize: "0.7rem" }}>{CATEGORY_LABEL[a.category] ?? a.category} · priorità {a.priority}</span>
              {clickable && (
                <span className="action__open btn btn--ghost btn--sm" aria-hidden="true">
                  Apri cockpit <ArrowRight size={12} />
                </span>
              )}
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
  const c = data.counters;

  return (
    <>
      <PageHeader
        hero
        eyebrow={`Control hub · analisi al ${data.as_of}`}
        title="Cosa richiede attenzione oggi"
        question="Quale azienda guardare per prima, e perché. Solo segnali deterministici, con formula e fonti dichiarate."
        actions={
          <>
            <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Anno" style={{ width: 92 }}>
              {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
            </select>
            <select className="select" value={month} onChange={(e) => setMonth(Number(e.target.value))} aria-label="Periodo" style={{ width: 130 }}>
              {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>Gen–{m}</option>)}
            </select>
          </>
        }
      />

      <div className="stat-grid">
        <Stat
          hero
          icon={<Siren size={14} />}
          label="Segnali critici"
          value={c.critical}
          hint={`${c.warning} in attenzione · ${c.info} informativi`}
        />
        <Stat
          icon={<AlertTriangle size={14} />}
          label="Decisioni da prendere"
          value={c.action_required}
          hint="richiedono approvazione umana"
          tone={c.action_required > 0 ? "warn" : undefined}
          onClick={() => setOnlyActionable(true)}
        />
        <Stat
          icon={<Building2 size={14} />}
          label="Aziende gestite"
          value={c.companies}
          hint={`${c.companies_needing_attention} richiedono attenzione`}
          onClick={() => navigate("/companies")}
        />
        <Stat
          icon={<CalendarClock size={14} />}
          label="Orizzonte di cassa"
          value={<>{data.horizon_days}<span style={{ fontSize: "0.5em", marginLeft: 4, color: "var(--pys-ink-400)" }}>gg</span></>}
          hint="previsione tesoreria"
        />
      </div>

      <Card className="card__pad">
        <div className="card__title card__title--row">
          <span>Action center</span>
          <div className="segmented" role="tablist" aria-label="Filtro segnali">
            <button role="tab" aria-selected={!onlyActionable} className={`segmented__opt${!onlyActionable ? " segmented__opt--on" : ""}`} onClick={() => setOnlyActionable(false)}>
              Tutti ({data.actions.length})
            </button>
            <button role="tab" aria-selected={onlyActionable} className={`segmented__opt${onlyActionable ? " segmented__opt--on" : ""}`} onClick={() => setOnlyActionable(true)}>
              Solo decisioni ({c.action_required})
            </button>
          </div>
        </div>
        <ActionList actions={actions} onOpen={open} />
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 12 }}>
          Ordinamento: {data.priority.formula} · <span className="mono">{data.priority.version}</span>
        </div>
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Portafoglio aziende · chi guardare per prima</div>
        {data.companies.length === 0 ? (
          <EmptyState title="Nessuna azienda in questo workspace">
            Crea la prima anagrafica da <a onClick={() => navigate("/companies")} role="button" tabIndex={0}>Aziende</a>.
          </EmptyState>
        ) : (
          <table className="table table--flush">
            <thead>
              <tr>
                <th>Azienda</th>
                <th>Stato</th>
                <th style={{ textAlign: "right" }}>Cassa</th>
                <th style={{ textAlign: "right" }}>Cassa negativa</th>
                <th style={{ textAlign: "right" }}>Crediti scaduti</th>
                <th style={{ textAlign: "right" }}>Risultato</th>
                <th style={{ textAlign: "right" }}>Prossima scadenza</th>
                <th style={{ textAlign: "right" }}>Alert · riconc.</th>
                <th>Perché ora</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.companies.map((e) => (
                <tr key={e.company.id} className="portfolio__row" onClick={() => open(e.company.id)}>
                  <td>
                    <div className="table__primary">{e.company.legal_name}</div>
                    <div className="table__sub">
                      {e.company.vat_number ?? "P.IVA n.d."}{e.company.region ? ` · ${e.company.region}` : ""}
                    </div>
                  </td>
                  <td><Health health={e.health} /></td>
                  <td className="num" style={{ textAlign: "right" }}><Val v={e.cash.position} /></td>
                  <td className="num" style={{ textAlign: "right" }}>
                    {e.cash.first_negative_date ? (
                      <span className="tre-neg">{e.cash.first_negative_date}<div className="table__sub">tra {e.cash.days_to_negative} giorni</div></span>
                    ) : <span className="muted">—</span>}
                  </td>
                  <td className="num" style={{ textAlign: "right" }}><Val v={e.cash.overdue_receivables} /></td>
                  <td className="num" style={{ textAlign: "right" }}>
                    <Val v={e.economics.result} />
                    <div className="table__sub">{e.economics.covered_months}/{e.economics.expected_months} mesi</div>
                  </td>
                  <td className="num" style={{ textAlign: "right" }}>
                    {e.fiscal.next_obligation?.due_date ? (
                      <>
                        {e.fiscal.next_obligation.due_date}
                        <div className="table__sub"><Val v={e.fiscal.next_obligation.amount} /></div>
                      </>
                    ) : e.fiscal.pending_entries > 0 ? (
                      <span className="muted">{e.fiscal.pending_entries} voci da verificare</span>
                    ) : <span className="muted">—</span>}
                  </td>
                  <td className="num" style={{ textAlign: "right" }}>
                    {e.controlling.open_alerts > 0 ? (
                      <Badge tone={e.controlling.critical_alerts > 0 ? "danger" : "warning"}>
                        {e.controlling.open_alerts}{e.controlling.critical_alerts > 0 ? ` (${e.controlling.critical_alerts} crit.)` : ""}
                      </Badge>
                    ) : <span className="muted">0</span>}
                    <div className="table__sub">{e.cash.unreconciled_transactions || 0} da riconciliare</div>
                  </td>
                  <td className="portfolio__why">
                    {e.top_signal
                      ? <span title={e.top_signal}>{e.top_signal}</span>
                      : <span className="muted">{e.signal_count} segnali</span>}
                  </td>
                  <td style={{ textAlign: "right" }}><ArrowRight size={14} className="muted" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="portfolio__legend">
          <span>{data.aggregation_note}</span>
        </div>
      </Card>

      <details style={{ marginTop: 16 }}>
        <summary className="eyebrow eyebrow--muted" style={{ cursor: "pointer", padding: "6px 0" }}>
          Limitazioni dichiarate ({data.limitations.length})
        </summary>
        <Card className="card__pad card--section" style={{ marginTop: 8 }}>
          <ul className="mgmt-issues">
            {data.limitations.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </Card>
      </details>
    </>
  );
}
