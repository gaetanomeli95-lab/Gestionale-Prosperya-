import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Mail, Phone, UserPlus, Users } from "lucide-react";
import { api } from "../api/client";
import type { Contact, Page } from "../api/types";
import { ContactCreateModal } from "../components/ContactCreateModal";
import {
  EmptyState, ErrorBanner, NA, PageHeader, Pagination, Section, Skeleton, Stat,
} from "../components/ui";

function initials(c: Contact) {
  return `${c.first_name?.[0] ?? ""}${c.last_name?.[0] ?? ""}`.toUpperCase() || "?";
}

export default function ContactsPage() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["contacts", q, page],
    queryFn: () =>
      api.get<Page<Contact>>(`/contacts?page=${page}&page_size=25${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  });

  const items = data?.items ?? [];
  const withEmail = items.filter((c) => c.email).length;
  const withPhone = items.filter((c) => c.phone).length;
  const searching = q.trim().length > 0;

  return (
    <>
      <PageHeader
        eyebrow="CRM"
        title="Contatti"
        question="Chi sono le persone con cui parliamo, e come le raggiungo subito?"
        actions={
          <button className="btn btn--primary" onClick={() => setCreating(true)}>
            <UserPlus size={15} /> Nuovo contatto
          </button>
        }
      />

      {isLoading && !data ? <Skeleton kind="stats" rows={3} /> : data && (
        <div className="stat-grid">
          <Stat hero icon={<Users size={14} />} label="Persone in rubrica"
                value={<span className="num">{data.total}</span>}
                hint={searching ? `risultati per "${q}"` : "in tutto il workspace"} />
          <Stat icon={<Mail size={14} />} label="Con email"
                value={<span className="num">{withEmail}</span>}
                hint={`su ${items.length} in questa pagina`}
                tone={items.length > 0 && withEmail < items.length ? "warn" : undefined} />
          <Stat icon={<Phone size={14} />} label="Con telefono"
                value={<span className="num">{withPhone}</span>}
                hint={`su ${items.length} in questa pagina`} />
        </div>
      )}

      <Section
        title="Rubrica"
        flush
        actions={
          <input className="input input--sm" aria-label="Cerca per nome, email, telefono"
                 placeholder="Cerca per nome, email, telefono…" value={q}
                 onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        }
        footer={data && data.total > 0
          ? `${data.total} ${data.total === 1 ? "persona" : "persone"} · pagina ${page}`
          : undefined}
      >
        {error && <div className="card__pad"><ErrorBanner error={error} /></div>}
        {isLoading ? (
          <div className="card__pad"><Skeleton kind="table" rows={6} /></div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title={searching ? "Nessun contatto corrisponde alla ricerca" : "Nessun contatto in rubrica"}
            action={
              <button className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>
                <UserPlus size={14} /> Nuovo contatto
              </button>
            }
          >
            {searching
              ? "Prova con un cognome o un dominio email diverso, oppure crea la persona adesso."
              : "Aggiungi le persone che rappresentano i clienti: senza un referente non puoi inviare richieste documentali."}
          </EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead>
              <tr>
                <th>Persona</th>
                <th>Ruolo</th>
                <th>Email</th>
                <th>Telefono</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="cluster">
                      <span className="row__lead text-xs strong" aria-hidden="true">{initials(c)}</span>
                      <div>
                        <div className="table__primary">{c.first_name} {c.last_name}</div>
                        <div className="table__sub">
                          {c.email && c.phone ? "Raggiungibile per email e telefono"
                            : c.email ? "Solo email" : c.phone ? "Solo telefono" : "Nessun recapito"}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>{c.role_title ?? <NA title="Ruolo non indicato" />}</td>
                  <td>{c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : <NA title="Email non indicata" />}</td>
                  <td className="num">{c.phone ? <a href={`tel:${c.phone}`}>{c.phone}</a> : <NA title="Telefono non indicato" />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}

      {creating && <ContactCreateModal onClose={() => setCreating(false)} />}
    </>
  );
}
