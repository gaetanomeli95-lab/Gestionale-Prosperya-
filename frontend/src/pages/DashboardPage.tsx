import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Dashboard } from "../api/types";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";
import { dateTimeIt, eur } from "../lib/format";

export default function DashboardPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/dashboard"),
  });

  if (isLoading) return <Spinner />;
  if (error || !data) return <ErrorBanner error={error} />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Panoramica operativa</h1>
          <div className="page-head__meta">Cosa richiede attenzione oggi</div>
        </div>
      </div>

      <div className="kpi-grid">
        <Card className={`kpi ${data.my_overdue_tasks > 0 ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Attività scadute</div>
          <div className="kpi__value">{data.my_overdue_tasks}</div>
          <div className="kpi__hint">su {data.my_open_tasks} aperte mie</div>
        </Card>
        <Card className="kpi">
          <div className="kpi__label">Opportunità aperte</div>
          <div className="kpi__value">{data.open_opportunities}</div>
          <div className="kpi__hint">{eur(data.pipeline_value_eur)} in pipeline</div>
        </Card>
        <Card className={`kpi ${data.stale_opportunities > 0 ? "kpi--warn" : ""}`}>
          <div className="kpi__label">Opportunità ferme</div>
          <div className="kpi__value">{data.stale_opportunities}</div>
          <div className="kpi__hint">nessuna attività da 14+ giorni</div>
        </Card>
        <Card className="kpi">
          <div className="kpi__label">Nuovi lead (30g)</div>
          <div className="kpi__value">{data.new_leads_30d}</div>
        </Card>
        <Card className={`kpi ${data.unassigned_companies > 0 ? "kpi--warn" : ""}`}>
          <div className="kpi__label">Aziende senza owner</div>
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
            <table className="table">
              <thead>
                <tr><th>Fase</th><th>N°</th><th style={{ textAlign: "right" }}>Valore</th></tr>
              </thead>
              <tbody>
                {data.pipeline_by_stage.map((s) => (
                  <tr key={s.stage_id} style={{ cursor: "default" }}>
                    <td>{s.stage_name}</td>
                    <td className="mono">{s.count}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{eur(s.total_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ marginTop: 12 }}>
            <Link to="/pipeline" className="btn btn--ghost btn--sm">Apri pipeline →</Link>
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
          <div style={{ marginTop: 12 }}>
            <Link to="/tasks" className="btn btn--ghost btn--sm">Vai alle attività →</Link>
          </div>
        </Card>
      </div>
    </>
  );
}
