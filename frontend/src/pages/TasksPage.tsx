import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { AlarmClock, CheckCircle2, Flame, ListChecks, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Page, Task } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  Badge, EmptyState, ErrorBanner, NA, PageHeader, Pagination, Section, Segmented, Skeleton, Stat,
  StatusBadge, toast,
} from "../components/ui";
import { dateTimeIt } from "../lib/format";

type Filter = "open" | "mine" | "overdue" | "all";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "open", label: "Aperte" },
  { value: "mine", label: "Assegnate a me" },
  { value: "overdue", label: "Scadute" },
  { value: "all", label: "Tutte" },
];

const ENTITY_LABEL: Record<string, string> = {
  company: "Azienda", contact: "Contatto", lead: "Lead", opportunity: "Opportunità",
  practice: "Pratica", document: "Documento", invoice: "Fattura", deadline: "Scadenza",
};

export default function TasksPage() {
  const [filter, setFilter] = useState<Filter>("open");
  const [page, setPage] = useState(1);
  const [title, setTitle] = useState("");
  const { user } = useAuth();
  const qc = useQueryClient();

  const query = (() => {
    const params = new URLSearchParams({ page: String(page), page_size: "50" });
    if (filter === "mine" && user) params.set("owner_id", user.id);
    if (filter === "overdue") params.set("overdue", "true");
    if (filter === "all") params.set("status", "");
    return `/tasks?${params.toString()}`;
  })();

  const { data, isLoading, error } = useQuery({
    queryKey: ["tasks", filter, page, user?.id],
    queryFn: () => api.get<Page<Task>>(query),
  });

  const add = useMutation({
    mutationFn: (t: string) => api.post("/tasks", { title: t, owner_id: user?.id }),
    onSuccess: () => { setTitle(""); qc.invalidateQueries({ queryKey: ["tasks"] }); toast("Attività aggiunta"); },
  });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.patch(`/tasks/${id}`, { status }),
    onSuccess: (_r, v) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      toast(v.status === "done" ? "Attività completata" : v.status === "cancelled" ? "Attività annullata" : "Attività riaperta");
    },
  });

  const items = data?.items ?? [];
  const isOverdue = (t: Task) => Boolean(t.due_date && t.status !== "done" && t.status !== "cancelled" && new Date(t.due_date) < new Date());
  const overdueCount = items.filter(isOverdue).length;
  const hotCount = items.filter((t) => (t.priority === "high" || t.priority === "urgent") && t.status !== "done" && t.status !== "cancelled").length;
  const currentLabel = FILTERS.find((f) => f.value === filter)?.label ?? "";

  return (
    <>
      <PageHeader
        eyebrow="Operatività"
        title="Attività"
        question="Cosa devo chiudere oggi, e cosa è già in ritardo?"
      />

      {isLoading && !data ? <Skeleton kind="stats" rows={3} /> : data && (
        <div className="stat-grid">
          <Stat hero icon={<ListChecks size={14} />} label={currentLabel}
                value={<span className="num">{data.total}</span>}
                hint="attività in questa vista" />
          <Stat icon={<AlarmClock size={14} />} label="Scadute"
                value={<span className="num">{overdueCount}</span>}
                hint="in questa pagina · da chiudere o riprogrammare"
                tone={overdueCount > 0 ? "danger" : undefined}
                onClick={() => { setFilter("overdue"); setPage(1); }} />
          <Stat icon={<Flame size={14} />} label="Priorità alta o urgente"
                value={<span className="num">{hotCount}</span>}
                hint="in questa pagina · ancora aperte"
                tone={hotCount > 0 ? "warn" : undefined} />
        </div>
      )}

      <form className="toolbar" onSubmit={(e: FormEvent) => { e.preventDefault(); if (title.trim()) add.mutate(title.trim()); }}>
        <input className="input" aria-label="Nuova attività" placeholder="Nuova attività assegnata a te…"
               value={title} onChange={(e) => setTitle(e.target.value)} />
        <button className="btn btn--primary" type="submit" disabled={!title.trim() || add.isPending}>
          <Plus size={14} /> Aggiungi
        </button>
        <div className="toolbar__end">
          <Segmented
            ariaLabel="Filtra attività"
            options={FILTERS}
            value={filter}
            onChange={(v) => { setFilter(v); setPage(1); }}
          />
        </div>
      </form>

      <Section
        title="Coda operativa"
        flush
        footer={data && data.total > 0
          ? "Spunta per completare; «Annulla» chiude un'attività che non serve più."
          : undefined}
      >
        {error && <div className="card__pad"><ErrorBanner error={error} /></div>}
        {isLoading ? (
          <div className="card__pad"><Skeleton kind="table" rows={6} /></div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title={filter === "overdue" ? "Niente in ritardo" : "Nessuna attività in questa vista"}
            icon={<CheckCircle2 size={20} strokeWidth={1.8} />}
            action={filter !== "all"
              ? <button className="btn btn--ghost btn--sm" onClick={() => { setFilter("all"); setPage(1); }}>Mostra tutte</button>
              : undefined}
          >
            {filter === "overdue"
              ? "Tutte le scadenze sono rispettate. Aggiungi la prossima attività dal campo qui sopra."
              : "Scrivi la prossima cosa da fare nel campo qui sopra: sarà assegnata a te."}
          </EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead>
              <tr>
                <th><span className="muted" aria-hidden="true">✓</span></th>
                <th>Attività</th>
                <th>Priorità</th>
                <th className="th--num">Scadenza</th>
                <th>Collegata a</th>
                <th className="right">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((t) => {
                const overdue = isOverdue(t);
                const closed = t.status === "done" || t.status === "cancelled";
                return (
                  <tr key={t.id}>
                    <td>
                      <label className="check">
                        <input type="checkbox" checked={t.status === "done"} aria-label="Completa"
                               onChange={() => setStatus.mutate({ id: t.id, status: t.status === "done" ? "todo" : "done" })} />
                      </label>
                    </td>
                    <td>
                      <div className="cluster">
                        <span className={closed ? "muted" : "table__primary"}>
                          {t.status === "done" ? <s>{t.title}</s> : t.title}
                        </span>
                        {overdue && <Badge tone="danger">Scaduta</Badge>}
                        {closed && <StatusBadge status={t.status} />}
                      </div>
                      {t.description && <div className="table__sub truncate">{t.description}</div>}
                    </td>
                    <td><StatusBadge status={t.priority} /></td>
                    <td className={`td--num${overdue ? " neg" : ""}`}>
                      {t.due_date ? dateTimeIt(t.due_date) : <NA title="Nessuna scadenza impostata" />}
                    </td>
                    <td className="muted">
                      {t.entity_type ? (ENTITY_LABEL[t.entity_type] ?? t.entity_type) : <NA title="Attività libera, non collegata" />}
                    </td>
                    <td className="right">
                      {!closed && (
                        <button className="btn btn--ghost btn--sm"
                                disabled={setStatus.isPending}
                                onClick={() => setStatus.mutate({ id: t.id, status: "cancelled" })}>
                          Annulla
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Section>
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
    </>
  );
}
