import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { CompanyListItem, Page, Practice } from "../api/types";
import {
  Card, EmptyState, ErrorBanner, Spinner, StatusBadge,
} from "../components/ui";
import { dateTimeIt } from "../lib/format";

const TRANSITIONS: Record<string, string[]> = {
  draft: ["open", "cancelled"],
  open: ["in_progress", "waiting_client", "waiting_external", "cancelled"],
  in_progress: ["waiting_client", "waiting_external", "ready", "completed", "cancelled"],
  waiting_client: ["in_progress", "cancelled"],
  waiting_external: ["in_progress", "cancelled"],
  ready: ["completed", "in_progress", "cancelled"],
};

export default function PracticesPage() {
  const [companyId, setCompanyId] = useState("");
  const [status, setStatus] = useState("");
  const [title, setTitle] = useState("");
  const [type, setType] = useState("generic");
  const qc = useQueryClient();

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });

  const params = new URLSearchParams();
  if (companyId) params.set("company_id", companyId);
  if (status) params.set("status", status);
  const practices = useQuery({
    queryKey: ["practices", companyId, status],
    queryFn: () => api.get<{ practices: Practice[] }>(`/practices?${params}`),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post(`/practices/companies/${companyId}`, {
        title, practice_type: type,
      }),
    onSuccess: () => {
      setTitle("");
      qc.invalidateQueries({ queryKey: ["practices"] });
    },
  });

  const transition = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post(`/practices/${id}/transition`, { action }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["practices"] }),
  });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pratiche</h1>
          <div className="page-head__meta">
            Casi operativi trasversali — funding, fiscale, consulenza
          </div>
        </div>
      </div>

      <form
        className="toolbar"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (title.trim() && companyId) create.mutate();
        }}
      >
        <select className="select" style={{ maxWidth: 260 }} value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}>
          <option value="">Azienda…</option>
          {companies.data?.items.map((c) => (
            <option key={c.id} value={c.id}>{c.legal_name}</option>
          ))}
        </select>
        <input className="input" placeholder="Nuova pratica…" value={title}
               onChange={(e) => setTitle(e.target.value)} />
        <select className="select" style={{ maxWidth: 160 }} value={type}
                onChange={(e) => setType(e.target.value)}>
          <option value="generic">Generica</option>
          <option value="fiscal">Fiscale</option>
          <option value="startup">Startup</option>
          <option value="consulting">Consulenza</option>
        </select>
        <button className="btn btn--primary" type="submit"
                disabled={!title.trim() || !companyId}>
          Crea
        </button>
        <select className="select" style={{ maxWidth: 160, marginLeft: "auto" }}
                value={status}
                onChange={(e) => setStatus(e.target.value)}>
          <option value="">Tutti gli stati</option>
          {["draft", "open", "in_progress", "waiting_client",
            "waiting_external", "ready", "completed", "cancelled"]
            .map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </form>

      {practices.error && <ErrorBanner error={practices.error} />}
      {practices.isLoading ? <Spinner /> :
       !practices.data || practices.data.practices.length === 0 ? (
        <EmptyState>Nessuna pratica in questa vista.</EmptyState>
      ) : (
        <Card>
          <table className="table">
            <thead>
              <tr>
                <th>Pratica</th><th>Azienda</th><th>Tipo</th>
                <th>Stato</th><th>Blocchi</th><th>Scadenza</th><th></th>
              </tr>
            </thead>
            <tbody>
              {practices.data.practices.map((p) => {
                const company = companies.data?.items.find(
                  (c) => c.id === p.company_id);
                return (
                  <tr key={p.id}>
                    <td>
                      {p.title}
                      {p.source_module && (
                        <div className="muted" style={{ fontSize: "0.75rem" }}>
                          origine: {p.source_module}
                        </div>
                      )}
                    </td>
                    <td>
                      {company ? (
                        <Link to={`/companies/${company.id}`}>
                          {company.legal_name}
                        </Link>
                      ) : "—"}
                    </td>
                    <td className="muted">{p.practice_type}</td>
                    <td><StatusBadge status={p.status} /></td>
                    <td>
                      {p.open_blockers > 0 ? (
                        <span className="badge badge--danger">
                          {p.open_blockers} aperti
                        </span>
                      ) : "—"}
                    </td>
                    <td className="mono">{dateTimeIt(p.target_date)}</td>
                    <td>
                      {(TRANSITIONS[p.status] ?? []).slice(0, 2).map((a) => (
                        <button key={a}
                                className="btn btn--ghost btn--sm"
                                onClick={() => transition.mutate(
                                  { id: p.id, action: a })}>
                          → {a}
                        </button>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
