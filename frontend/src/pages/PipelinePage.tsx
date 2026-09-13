import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Opportunity, Page, PipelineStage } from "../api/types";
import { EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { dateIt, eur } from "../lib/format";

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["opportunities"] }),
  });

  if (loadingStages || loadingOpps) return <Spinner />;

  const openStages = (stages ?? []).filter((s) => !s.is_won && !s.is_lost);
  const terminalStages = (stages ?? []).filter((s) => s.is_won || s.is_lost);
  const byStage = (id: string) => (opps?.items ?? []).filter((o) => o.stage_id === id);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pipeline commerciale</h1>
          <div className="page-head__meta">
            {opps?.total ?? 0} opportunità aperte · {eur(
              (opps?.items ?? []).reduce((s, o) => s + (o.expected_value_eur ?? 0), 0),
            )}
          </div>
        </div>
      </div>
      {error && <ErrorBanner error={error} />}
      {move.error && <ErrorBanner error={move.error} />}

      <div className="kanban">
        {openStages.map((stage) => {
          const items = byStage(stage.id);
          const sum = items.reduce((s, o) => s + (o.expected_value_eur ?? 0), 0);
          return (
            <div className="kanban__col" key={stage.id}>
              <div className="kanban__head">
                <span className="kanban__title">{stage.name}</span>
                <span className="kanban__sum">{items.length} · {eur(sum)}</span>
              </div>
              {items.length === 0 && <div className="empty" style={{ padding: 12 }}>—</div>}
              {items.map((o) => (
                <div className="kanban__card" key={o.id}>
                  <div className="kanban__card-title">{o.title}</div>
                  <div className="kanban__card-meta">
                    {eur(o.expected_value_eur)}
                    {o.probability != null && ` · ${o.probability}%`}
                    {o.expected_close_date && ` · chiusura ${dateIt(o.expected_close_date)}`}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <select
                      className="select"
                      style={{ fontSize: "0.75rem", padding: "4px 8px" }}
                      value=""
                      aria-label="Sposta in fase"
                      onChange={(e) => {
                        if (e.target.value) move.mutate({ id: o.id, stage_id: e.target.value });
                      }}
                    >
                      <option value="">Sposta…</option>
                      {[...openStages.filter((s) => s.id !== stage.id), ...terminalStages].map((s) => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {(!opps || opps.items.length === 0) && (
        <EmptyState>Nessuna opportunità aperta. Converti un lead per iniziare.</EmptyState>
      )}
    </>
  );
}
