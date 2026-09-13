import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Contact, Page } from "../api/types";
import { EmptyState, ErrorBanner, Modal, Pagination, Spinner } from "../components/ui";

export default function ContactsPage() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["contacts", q, page],
    queryFn: () =>
      api.get<Page<Contact>>(`/contacts?page=${page}&page_size=25${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  });

  const create = useMutation({
    mutationFn: (d: { first_name: string; last_name: string; email?: string; phone?: string; role_title?: string }) =>
      api.post("/contacts", d),
    onSuccess: () => { setCreating(false); qc.invalidateQueries({ queryKey: ["contacts"] }); },
  });

  return (
    <>
      <div className="page-head">
        <div><h1>Contatti</h1><div className="page-head__meta">{data ? `${data.total} persone` : "…"}</div></div>
        <button className="btn btn--primary" onClick={() => setCreating(true)}>+ Nuovo contatto</button>
      </div>
      <div className="toolbar">
        <input className="input" placeholder="Cerca per nome, email, telefono…" value={q}
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

      {creating && (
        <Modal title="Nuovo contatto" onClose={() => setCreating(false)} footer={null}>
          <form
            onSubmit={(e: FormEvent<HTMLFormElement>) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              create.mutate({
                first_name: String(f.get("first_name") ?? ""),
                last_name: String(f.get("last_name") ?? ""),
                email: String(f.get("email") ?? "") || undefined,
                phone: String(f.get("phone") ?? "") || undefined,
                role_title: String(f.get("role_title") ?? "") || undefined,
              });
            }}
          >
            {create.error && <ErrorBanner error={create.error} />}
            <div className="form-grid">
              <div className="field"><label className="field__label">Nome *</label>
                <input className="input" name="first_name" required /></div>
              <div className="field"><label className="field__label">Cognome *</label>
                <input className="input" name="last_name" required /></div>
              <div className="field"><label className="field__label">Email</label>
                <input className="input" name="email" type="email" /></div>
              <div className="field"><label className="field__label">Telefono</label>
                <input className="input" name="phone" /></div>
              <div className="field span-2"><label className="field__label">Ruolo</label>
                <input className="input" name="role_title" /></div>
            </div>
            <div className="modal__foot" style={{ margin: "16px -20px -16px", padding: "12px 0 0" }}>
              <button type="button" className="btn btn--ghost" onClick={() => setCreating(false)}>Annulla</button>
              <button type="submit" className="btn btn--primary" disabled={create.isPending}>Crea</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
