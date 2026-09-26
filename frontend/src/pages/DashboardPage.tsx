import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  AlarmClock, ArrowRight, Building2, CalendarClock, CheckCircle2, Clock, Layers, TrendingUp, Zap,
} from "lucide-react";
import { api } from "../api/client";
import type { Dashboard } from "../api/types";
import {
  EmptyState, ErrorBanner, KV, PageHeader, Progress, Row, Section, Skeleton, Stat, StatusBadge,
} from "../components/ui";
import { dateTimeIt, eur } from "../lib/format";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/dashboard"),
  });

  const header = (
    <PageHeader
      hero
      eyebrow="Panoramica"
      title="Panoramica operativa"
      question="Come va il lavoro commerciale e operativo questa settimana?"
      actions={
        <>
          <Link to="/pipeline" className="btn btn--ghost">Pipeline <ArrowRight size={14} /></Link>
          <Link to="/tasks" className="btn btn--primary">Attività <ArrowRight size={14} /></Link>
        </>
      }
    />
  );

  if (isLoading) {
    return (
      <>
        {header}
        <Skeleton kind="stats" rows={5} />
        <div className="grid-2-1">
          <Section title="Da fare ora"><Skeleton rows={5} /></Section>
          <Section title="Pipeline per fase"><Skeleton rows={4} /></Section>
        </div>
      </>
    );
  }
  if (error || !data) return <>{header}<ErrorBanner error={error} /></>;

  const maxStageValue = Math.max(1, ...data.pipeline_by_stage.map((s) => s.total_value));
  const overdue = data.overdue_task_items;
  const upcoming = data.upcoming_tasks;
  const nothingToDo = overdue.length === 0 && upcoming.length === 0;
  const customerShare = data.companies_total > 0
    ? Math.round((data.customers_total / data.companies_total) * 100) : null;

  return (
    <>
      {header}

      <div className="stat-grid">
        <Stat
          hero
          icon={<TrendingUp size={14} />}
          label="Valore in pipeline"
          value={<span className="num money">{eur(data.pipeline_value_eur)}</span>}
          hint={`${data.open_opportunities} ${data.open_opportunities === 1 ? "opportunità aperta" : "opportunità aperte"}`}
          onClick={() => navigate("/pipeline")}
        />
        <Stat
          icon={<AlarmClock size={14} />}
          label="Attività scadute"
          value={<span className="num">{data.my_overdue_tasks}</span>}
          hint={`su ${data.my_open_tasks} aperte assegnate a te`}
          tone={data.my_overdue_tasks > 0 ? "danger" : undefined}
          onClick={() => navigate("/tasks")}
        />
        <Stat
          icon={<Clock size={14} />}
          label="Opportunità ferme"
          value={<span className="num">{data.stale_opportunities}</span>}
          hint="senza attività da 14 o più giorni"
          tone={data.stale_opportunities > 0 ? "warn" : undefined}
          onClick={() => navigate("/pipeline")}
        />
        <Stat
          icon={<Zap size={14} />}
          label="Nuovi lead"
          value={<span className="num">{data.new_leads_30d}</span>}
          hint="entrati negli ultimi 30 giorni"
          onClick={() => navigate("/leads")}
        />
        <Stat
          icon={<Building2 size={14} />}
          label="Aziende senza responsabile"
          value={<span className="num">{data.unassigned_companies}</span>}
          hint={`su ${data.companies_total} aziende gestite`}
          tone={data.unassigned_companies > 0 ? "warn" : undefined}
          onClick={() => navigate("/companies")}
        />
      </div>

      <div className="grid-2-1">
        <Section
          title="Da fare ora"
          actions={<Link to="/tasks" className="btn btn--ghost btn--sm">Tutte le attività <ArrowRight size={13} /></Link>}
          footer={nothingToDo ? undefined : `${overdue.length} ${overdue.length === 1 ? "scaduta" : "scadute"} · ${upcoming.length} in arrivo`}
        >
          {nothingToDo ? (
            <EmptyState
              title="Nessuna attività in scadenza"
              icon={<CheckCircle2 size={20} strokeWidth={1.8} />}
              action={<Link to="/tasks" className="btn btn--ghost btn--sm">Pianifica un'attività</Link>}
            >
              La coda è pulita: niente di scaduto e niente in arrivo nei prossimi giorni.
            </EmptyState>
          ) : (
            <div className="rows">
              {overdue.map((t) => (
                <Row
                  key={t.id}
                  tone="critical"
                  leading={<AlarmClock size={16} />}
                  title={t.title}
                  sub={<>Scaduta il {dateTimeIt(t.due_date)} · va chiusa o riprogrammata</>}
                  trailing={<StatusBadge status={t.priority} />}
                  onClick={() => navigate("/tasks")}
                />
              ))}
              {upcoming.map((t) => (
                <Row
                  key={t.id}
                  tone="info"
                  leading={<CalendarClock size={16} />}
                  title={t.title}
                  sub={<>Scade {dateTimeIt(t.due_date)}</>}
                  trailing={<StatusBadge status={t.priority} />}
                  onClick={() => navigate("/tasks")}
                />
              ))}
            </div>
          )}
        </Section>

        <div className="stack">
          <Section
            title="Pipeline per fase"
            actions={<Link to="/pipeline" className="btn btn--ghost btn--sm">Apri <ArrowRight size={13} /></Link>}
          >
            {data.pipeline_by_stage.length === 0 ? (
              <EmptyState
                title="Nessuna fase configurata"
                icon={<Layers size={20} strokeWidth={1.8} />}
                action={<Link to="/settings" className="btn btn--ghost btn--sm">Configura le fasi</Link>}
              >
                Le fasi della pipeline si definiscono nelle impostazioni delle linee di servizio.
              </EmptyState>
            ) : (
              <div className="rows">
                {data.pipeline_by_stage.map((s) => (
                  <Row
                    key={s.stage_id}
                    title={s.stage_name}
                    sub={
                      <Progress
                        value={s.total_value}
                        max={maxStageValue}
                        tone="accent"
                        label={<span className="money">{eur(s.total_value)}</span>}
                      />
                    }
                    trailing={<span className="num strong">{s.count}</span>}
                  />
                ))}
              </div>
            )}
          </Section>

          <Section title="Portafoglio">
            <KV
              columns={1}
              items={[
                { k: "Aziende gestite", v: <span className="num">{data.companies_total}</span> },
                {
                  k: "Clienti attivi",
                  v: <span className="num">{data.customers_total}{customerShare != null && <span className="muted"> · {customerShare}%</span>}</span>,
                },
                {
                  k: "Senza responsabile",
                  v: <span className={`num${data.unassigned_companies > 0 ? " neg" : ""}`}>{data.unassigned_companies}</span>,
                },
              ]}
            />
          </Section>
        </div>
      </div>
    </>
  );
}
