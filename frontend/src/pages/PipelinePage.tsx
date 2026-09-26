import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CalendarClock, Layers, Target, TrendingUp, Zap } from "lucide-react";
import { api } from "../api/client";
import type { Opportunity, Page, PipelineStage } from "../api/types";
import {
  Badge, EmptyState, ErrorBanner, PageHeader, Skeleton, Stat, toast,
} from "../components/ui";
import { dateIt, eur } from "../lib/format";

function isOverdue(iso: string | null) {
  return Boolean(iso && new Date(iso) < new Date());
}

export default function PipelinePage() {
  const qc = useQueryClient();
  const { data: stages, isLoading: loadingStages } = useQuery({
    queryKey: ["pipeline-stages"],
    queryFn: () => api.get<PipelineStage[]>("/service-lines/pipeline-stages"),
  });
  const { data: opps, isLoading: loadingOpps, error } = useQuery({
    queryKey: ["opportunities"],
    queryFn: () => api.get<Page<Opportunity>>("/opportunities?page_size=200&status=open"),
  });

  const move = useMutation({
    mutationFn: ({ id, stage_id }: { id: string; stage_id: string }) =>
      api.post(`/opportunities/${id}/move`, { stage_id }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["opportunities"] }); toast("Opportunità spostata"); },
  });

  const items = opps?.items ?? [];
  const totalValue = items.reduce((s, o) => s + (o.expected_value_eur ?? 0), 0);
  const weighted = items.reduce((s, o) => s + ((o.expected_value_eur ?? 0) * ((o.probability ?? 0) / 100)), 0);
  const now = new Date();
  const closingThisMonth = items.filter((o) => {
    if (!o.expected_close_date) return false;
    const d = new Date(o.expected_close_date);
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
  }).length;
  const stalledActions = items.filter((o) => isOverdue(o.next_action_date)).length;

  const header = (
    <PageHeader
      eyebrow="CRM"
      title="Pipeline commerciale"
      question="Quanto vale il lavoro in trattativa e quali opportunità vanno spinte adesso?"
      actions={<Link to="/leads" className="btn btn--ghost"><Zap size={14} /> Lead da convertire</Link>}
    />
  );

  if (loadingStages || loadingOpps) {
    return (
      <>
        {header}
        <Skeleton kind="stats" rows={4} />
        <Skeleton kind="table" rows={5} />
      </>
    );
  }

  const openStages = (stages ?? []).filter((s) => !s.is_won && !s.is_lost);
  const terminalStages = (stages ?? []).filter((s) => s.is_won || s.is_lost);
  const byStage = (id: string) => items.filter((o) => o.stage_id === id);

  return (
    <>
      {header}

      <div className="stat-grid">
        <Stat hero icon={<TrendingUp size={14} />} label="Valore in trattativa"
              value={<span className="num money">{eur(totalValue)}</span>}
              hint={`${opps?.total ?? 0} ${(opps?.total ?? 0) === 1 ? "opportunità aperta" : "opportunità aperte"}`} />
        <Stat icon={<Target size={14} />} label="Valore ponderato"
              value={<span className="num money">{eur(Math.round(weighted))}</span>}
              hint="valore × probabilità di chiusura" />
        <Stat icon={<CalendarClock size={14} />} label="In chiusura questo mese"
              value={<span className="num">{closingThisMonth}</span>}
              hint="con data di chiusura prevista nel mese" />
        <Stat icon={<Layers size={14} />} label="Prossimo passo in ritardo"
              value={<span className="num">{stalledActions}</span>}
              hint="azione pianificata già scaduta"
              tone={stalledActions > 0 ? "warn" : undefined} />
      </div>

      {error && <ErrorBanner error={error} />}
      {move.error && <ErrorBanner error={move.error} />}

      {items.length === 0 ? (
        <EmptyState
          title="Nessuna opportunità aperta"
          icon={<TrendingUp size={20} strokeWidth={1.8} />}
          action={<Link to="/leads" className="btn btn--primary btn--sm"><Zap size={14} /> Converti un lead</Link>}
        >
          La pipeline si popola convertendo i lead qualificati: ogni conversione crea l'azienda e la prima opportunità.
        </EmptyState>
      ) : (
        <div className="kanban">
          {openStages.map((stage) => {
            const colItems = byStage(stage.id);
            const sum = colItems.reduce((s, o) => s + (o.expected_value_eur ?? 0), 0);
            return (
              <div className="kanban__col" key={stage.id}>
                <div className="kanban__head">
                  <span className="kanban__title">{stage.name}</span>
                  <span className="kanban__sum num">
                    {colItems.length} · <span className="money">{eur(sum)}</span>
                  </span>
                </div>
                {colItems.length === 0 && (
                  <div className="empty text-xs">Nessuna opportunità in questa fase</div>
                )}
                {colItems.map((o) => {
                  const lateAction = isOverdue(o.next_action_date);
                  return (
                    <div className="kanban__card" key={o.id}>
                      <div className="cluster cluster--between">
                        <div className="kanban__card-title truncate" title={o.title}>{o.title}</div>
                        {o.probability != null && <Badge tone="neutral" dot={false}>{o.probability}%</Badge>}
                      </div>
                      <div className="money money--lg mt-1">
                        {o.expected_value_eur == null ? <span className="na" title="Valore non stimato">n.d.</span> : eur(o.expected_value_eur)}
                      </div>
                      <div className="kanban__card-meta">
                        {o.expected_close_date
                          ? <>Chiusura prevista {dateIt(o.expected_close_date)}</>
                          : <span className="muted">Nessuna data di chiusura</span>}
                      </div>
                      {o.next_action && (
                        <div className={`kanban__card-meta${lateAction ? " neg" : ""}`}>
                          {lateAction ? "In ritardo: " : "Prossimo passo: "}{o.next_action}
                          {o.next_action_date && <> · {dateIt(o.next_action_date)}</>}
                        </div>
                      )}
                      <div className="mt-2">
                        <select
                          className="select select--sm"
                          value=""
                          aria-label="Sposta in fase"
                          onChange={(e) => {
                            if (e.target.value) move.mutate({ id: o.id, stage_id: e.target.value });
                          }}
                        >
                          <option value="">Sposta in…</option>
                          {[...openStages.filter((s) => s.id !== stage.id), ...terminalStages].map((s) => (
                            <option key={s.id} value={s.id}>
                              {s.is_won ? `${s.name} (vinta)` : s.is_lost ? `${s.name} (persa)` : s.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
