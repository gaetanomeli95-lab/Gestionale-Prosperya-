import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { Contact, Page } from "../api/types";
import { ContactCreateModal } from "../components/ContactCreateModal";
import { EmptyState, ErrorBanner, Pagination, Spinner } from "../components/ui";

export default function ContactsPage() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["contacts", q, page],
    queryFn: () =>
      api.get<Page<Contact>>(`/contacts?page=${page}&page_size=25${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  });

  return (
    <>
      <div className="page-head">
        <div><h1>Contatti</h1><div className="page-head__meta">{data ? `${data.total} persone` : "…"}</div></div>
        <button className="btn btn--primary" onClick={() => setCreating(true)}>+ Nuovo contatto</button>
      </div>
      <div className="toolbar">
        <input className="input" aria-label="Cerca per nome, email, telefono" placeholder="Cerca per nome, email, telefono…" value={q}
               onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>
      {error && <ErrorBanner error={error} />}
      {isLoading ? <Spinner /> : !data || data.items.length === 0 ? (
        <EmptyState>Nessun contatto trovato.</EmptyState>
      ) : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Nome</th><th>Ruolo</th><th>Email</th><th>Telefono</th></tr></thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} style={{ cursor: "default" }}>
                  <td><strong>{c.first_name} {c.last_name}</strong></td>
                  <td>{c.role_title ?? "—"}</td>
                  <td>{c.email ?? "—"}</td>
                  <td className="mono">{c.phone ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}

      {creating && <ContactCreateModal onClose={() => setCreating(false)} />}
    </>
  );
}
