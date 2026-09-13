import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page, Task } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorBanner, Pagination, Spinner, StatusBadge } from "../components/ui";
import { dateTimeIt } from "../lib/format";

export default function TasksPage() {
  const [filter, setFilter] = useState<"open" | "mine" | "overdue" | "all">("open");
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
    onSuccess: () => { setTitle(""); qc.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.patch(`/tasks/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  return (
    <>
      <div className="page-head">
        <div><h1>Attività</h1><div className="page-head__meta">Coda operativa globale</div></div>
      </div>

      <form className="toolbar" onSubmit={(e: FormEvent) => { e.preventDefault(); if (title.trim()) add.mutate(title.trim()); }}>
        <input className="input" placeholder="Nuova attività…" value={title} onChange={(e) => setTitle(e.target.value)} />
        <button className="btn btn--primary" type="submit" disabled={!title.trim()}>Aggiungi</button>
        <select className="select" style={{ maxWidth: 180, marginLeft: "auto" }} value={filter}
                onChange={(e) => { setFilter(e.target.value as typeof filter); setPage(1); }}>
          <option value="open">Aperte</option>
          <option value="mine">Assegnate a me</option>
          <option value="overdue">Scadute</option>
          <option value="all">Tutte</option>
        </select>
      </form>

      {error && <ErrorBanner error={error} />}
      {isLoading ? <Spinner /> : !data || data.items.length === 0 ? (
        <EmptyState>Nessuna attività in questa vista.</EmptyState>
      ) : (
        <div className="card">
          <table className="table">
            <thead><tr><th></th><th>Attività</th><th>Priorità</th><th>Scadenza</th><th>Collegata a</th><th></th></tr></thead>
            <tbody>
              {data.items.map((t) => {
                const overdue = t.due_date && t.status !== "done" && new Date(t.due_date) < new Date();
                return (
                  <tr key={t.id} style={{ cursor: "default" }}>
                    <td style={{ width: 28 }}>
                      <input type="checkbox" checked={t.status === "done"} aria-label="Completa"
                             onChange={() => setStatus.mutate({ id: t.id, status: t.status === "done" ? "todo" : "done" })} />
                    </td>
                    <td>
                      <span style={t.status === "done" ? { textDecoration: "line-through", opacity: 0.6 } : {}}>
                        {t.title}
                      </span>
                      {overdue && <span className="badge badge--danger" style={{ marginLeft: 8 }}>scaduta</span>}
                    </td>
                    <td><StatusBadge status={t.priority} /></td>
                    <td className="mono">{dateTimeIt(t.due_date)}</td>
                    <td className="muted">{t.entity_type ?? "—"}</td>
                    <td>
                      {t.status !== "done" && t.status !== "cancelled" && (
                        <button className="btn btn--ghost btn--sm"
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
        </div>
      )}
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
    </>
  );
}
