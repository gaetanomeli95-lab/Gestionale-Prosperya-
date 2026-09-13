import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Lead, Page, ServiceLine } from "../api/types";
import { EmptyState, ErrorBanner, Modal, Pagination, Spinner, StatusBadge } from "../components/ui";
import { dateIt, eur } from "../lib/format";

export default function LeadsPage() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const { data, isLoading, error } = useQuery({
    queryKey: ["leads", status, page],
    queryFn: () =>
      api.get<Page<Lead>>(`/leads?page=${page}&page_size=25${status ? `&status=${status}` : ""}`),
  });
  const { data: serviceLines } = useQuery({
    queryKey: ["service-lines"],
    queryFn: () => api.get<ServiceLine[]>("/service-lines"),
  });

  const create = useMutation({
    mutationFn: (d: Record<string, unknown>) => api.post("/leads", d),
    onSuccess: () => { setCreating(false); qc.invalidateQueries({ queryKey: ["leads"] }); },
  });
  const convert = useMutation({
    mutationFn: (id: string) =>
      api.post<{ company_id: string }>(`/leads/${id}/convert`, { create_opportunity: true }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["companies"] });
      navigate(`/companies/${r.company_id}`);
    },
  });

  return (
    <>
      <div className="page-head">
        <div><h1>Lead</h1><div className="page-head__meta">Contatti in ingresso da qualificare</div></div>
        <button className="btn btn--primary" onClick={() => setCreating(true)}>+ Nuovo lead</button>
      </div>
      <div className="toolbar">
        <select className="select" style={{ maxWidth: 200 }} value={status}
                onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">Tutti gli stati</option>
          <option value="new">Nuovi</option>
          <option value="contacted">Contattati</option>
          <option value="qualified">Qualificati</option>
          <option value="unqualified">Non qualificati</option>
          <option value="converted">Convertiti</option>
        </select>
      </div>
      {error && <ErrorBanner error={error} />}
      {convert.error && <ErrorBanner error={convert.error} />}
      {isLoading ? <Spinner /> : !data || data.items.length === 0 ? (
        <EmptyState>Nessun lead.</EmptyState>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr><th>Azienda</th><th>Contatto</th><th>Fonte</th><th>Interesse</th><th>Valore</th><th>Stato</th><th></th></tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.id} style={{ cursor: "default" }}>
                  <td><strong>{l.company_name}</strong><div className="muted" style={{ fontSize: "0.75rem" }}>{dateIt(l.created_at)}</div></td>
                  <td>{l.contact_name ?? "—"}<div className="muted" style={{ fontSize: "0.75rem" }}>{l.email ?? ""}</div></td>
                  <td className="muted">{l.source}</td>
                  <td>{l.interest ?? "—"}</td>
                  <td className="mono">{eur(l.estimated_value_eur)}</td>
                  <td><StatusBadge status={l.status} /></td>
                  <td>
                    {l.status !== "converted" && (
                      <button className="btn btn--accent btn--sm"
                              disabled={convert.isPending}
                              onClick={() => convert.mutate(l.id)}>
                        Converti
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}

      {creating && (
        <Modal title="Nuovo lead" onClose={() => setCreating(false)} footer={null}>
          <form onSubmit={(e: FormEvent<HTMLFormElement>) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            create.mutate({
              company_name: String(f.get("company_name") ?? ""),
              contact_name: String(f.get("contact_name") ?? "") || undefined,
              email: String(f.get("email") ?? "") || undefined,
              phone: String(f.get("phone") ?? "") || undefined,
              source: String(f.get("source") ?? "other"),
              interest: String(f.get("interest") ?? "") || undefined,
              service_line_id: String(f.get("service_line_id") ?? "") || undefined,
            });
          }}>
            {create.error && <ErrorBanner error={create.error} />}
            <div className="form-grid">
              <div className="field span-2"><label className="field__label">Azienda *</label>
                <input className="input" name="company_name" required /></div>
              <div className="field"><label className="field__label">Persona di riferimento</label>
                <input className="input" name="contact_name" /></div>
              <div className="field"><label className="field__label">Email</label>
                <input className="input" name="email" type="email" /></div>
              <div className="field"><label className="field__label">Telefono</label>
                <input className="input" name="phone" /></div>
              <div className="field"><label className="field__label">Fonte</label>
                <select className="select" name="source">
                  <option value="website">Sito web</option>
                  <option value="referral">Passaparola</option>
                  <option value="social">Social</option>
                  <option value="event">Evento</option>
                  <option value="partner">Partner</option>
                  <option value="outreach">Attività commerciale</option>
                  <option value="other">Altro</option>
                </select></div>
              <div className="field span-2"><label className="field__label">Interesse / servizio</label>
                <input className="input" name="interest" placeholder="Es. finanza agevolata, startup…" /></div>
              <div className="field span-2"><label className="field__label">Linea di servizio</label>
                <select className="select" name="service_line_id">
                  <option value="">—</option>
                  {serviceLines?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select></div>
            </div>
            <div className="modal__foot" style={{ margin: "16px -20px -16px", padding: "12px 0 0" }}>
              <button type="button" className="btn btn--ghost" onClick={() => setCreating(false)}>Annulla</button>
              <button type="submit" className="btn btn--primary" disabled={create.isPending}>Crea lead</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
