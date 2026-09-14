import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlarmClock, ArrowRight, Building2, Clock, TrendingUp, Zap } from "lucide-react";
import { api } from "../api/client";
import type { Dashboard } from "../api/types";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";
import { dateTimeIt, eur } from "../lib/format";

const FUNNEL_COLORS = ["#2f5f68", "#3f7a83", "#c9b991", "#a89056", "#55b57a", "#d42375"];

export default function DashboardPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/dashboard"),
  });

  if (isLoading) return <Spinner />;
  if (error || !data) return <ErrorBanner error={error} />;

  const maxStageValue = Math.max(1, ...data.pipeline_by_stage.map((s) => s.total_value));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Panoramica operativa</h1>
          <div className="page-head__meta">Cosa richiede attenzione oggi</div>
        </div>
      </div>

      <div className="kpi-grid">
        <Card className={`kpi kpi--edge-danger ${data.my_overdue_tasks > 0 ? "kpi--alert" : ""}`}>
          <div className="kpi__label"><AlarmClock size={13} /> Attività scadute</div>
          <div className="kpi__value">{data.my_overdue_tasks}</div>
          <div className="kpi__hint">su {data.my_open_tasks} aperte mie</div>
        </Card>
        <Card className="kpi kpi--edge-primary">
          <div className="kpi__label"><TrendingUp size={13} /> Opportunità aperte</div>
          <div className="kpi__value">{data.open_opportunities}</div>
          <div className="kpi__hint">{eur(data.pipeline_value_eur)} in pipeline</div>
        </Card>
        <Card className={`kpi kpi--edge-warn ${data.stale_opportunities > 0 ? "kpi--warn" : ""}`}>
          <div className="kpi__label"><Clock size={13} /> Opportunità ferme</div>
          <div className="kpi__value">{data.stale_opportunities}</div>
          <div className="kpi__hint">nessuna attività da 14+ giorni</div>
        </Card>
        <Card className="kpi kpi--edge-accent">
          <div className="kpi__label"><Zap size={13} /> Nuovi lead (30g)</div>
          <div className="kpi__value">{data.new_leads_30d}</div>
          <div className="kpi__hint"><Link to="/leads">Apri i lead →</Link></div>
        </Card>
        <Card className={`kpi kpi--edge-teal ${data.unassigned_companies > 0 ? "kpi--warn" : ""}`}>
          <div className="kpi__label"><Building2 size={13} /> Aziende senza owner</div>
          <div className="kpi__value">{data.unassigned_companies}</div>
          <div className="kpi__hint">{data.companies_total} aziende · {data.customers_total} clienti</div>
        </Card>
      </div>

      <div className="grid-2">
        <Card className="card__pad">
          <div className="card__title">Pipeline per fase</div>
          {data.pipeline_by_stage.length === 0 ? (
            <EmptyState>Nessuna fase configurata.</EmptyState>
          ) : (
            <div className="funnel">
              {data.pipeline_by_stage.map((s, i) => (
                <div className="funnel__row" key={s.stage_id}>
                  <span className="funnel__label">{s.stage_name}</span>
                  <div className="funnel__track">
                    <div
                      className="funnel__bar"
                      style={{
                        width: `${Math.max(4, (s.total_value / maxStageValue) * 100)}%`,
                        background: FUNNEL_COLORS[i % FUNNEL_COLORS.length],
                      }}
                    />
                  </div>
                  <span className="funnel__meta mono">
                    {s.count} · {eur(s.total_value)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="card__foot">
            <Link to="/pipeline" className="btn btn--ghost btn--sm">
              Apri pipeline <ArrowRight size={13} />
            </Link>
          </div>
        </Card>

        <Card className="card__pad">
          <div className="card__title">Scadenze e attività</div>
          {data.overdue_task_items.length === 0 && data.upcoming_tasks.length === 0 ? (
            <EmptyState>Nessuna attività in scadenza.</EmptyState>
          ) : (
            <ul className="timeline">
              {data.overdue_task_items.map((t) => (
                <li className="timeline__item" key={t.id}>
                  <span className="timeline__dot" style={{ background: "var(--pys-danger-600)" }} />
                  <div className="timeline__body">
                    {t.title} <StatusBadge status={t.priority} />
                    <div className="timeline__time">Scaduta il {dateTimeIt(t.due_date)}</div>
                  </div>
                </li>
              ))}
              {data.upcoming_tasks.map((t) => (
                <li className="timeline__item" key={t.id}>
                  <span className="timeline__dot" />
                  <div className="timeline__body">
                    {t.title} <StatusBadge status={t.priority} />
                    <div className="timeline__time">Scade {dateTimeIt(t.due_date)}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="card__foot">
            <Link to="/tasks" className="btn btn--ghost btn--sm">
              Vai alle attività <ArrowRight size={13} />
            </Link>
          </div>
        </Card>
      </div>
    </>
  );
}
