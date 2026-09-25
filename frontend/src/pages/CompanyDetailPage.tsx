import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  ActivityEvent, Company, CompanyDossier, Contact, FundingOverview,
  Invoice, Note, Page, Task,
} from "../api/types";
import {
  Card, EmptyState, ErrorBanner, Spinner, StatusBadge,
} from "../components/ui";
import { dateIt, dateTimeIt, eur } from "../lib/format";
import { ContactCreateModal } from "../components/ContactCreateModal";

const TABS = [
  ["overview", "Quadro"],
  ["contacts", "Contatti"],
  ["tasks", "Attività"],
  ["notes", "Note"],
  ["invoices", "Fatture"],
  ["funding", "Agevolazioni"],
  ["dossier", "Dossier"],
  ["timeline", "Cronologia"],
] as const;

function ContactsTab({ companyId }: { companyId: string }) {
  const [creating, setCreating] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["contacts", "company", companyId],
    queryFn: () => api.get<Page<Contact>>(`/contacts?page_size=200&company_id=${companyId}`),
  });

  return (
    <Card className="card__pad">
      <div className="page-head" style={{ marginBottom: 12 }}>
        <div className="page-head__meta">
          {data ? `${data.total} ${data.total === 1 ? "contatto collegato" : "contatti collegati"}` : "…"}
          {" · "}<Link to="/contacts">tutti i contatti</Link>
        </div>
        <button className="btn btn--primary" onClick={() => setCreating(true)}>+ Nuovo contatto</button>
      </div>
      {error && <ErrorBanner error={error} />}
      {isLoading ? <Spinner /> : !data || data.items.length === 0 ? (
        <EmptyState>
          Nessun contatto collegato a questa azienda. Aggiungi il referente principale
          per poter inviare richieste documentali e comunicazioni.
        </EmptyState>
      ) : (
        <table className="table">
          <thead><tr><th>Nome</th><th>Ruolo</th><th>Email</th><th>Telefono</th></tr></thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.id}>
                <td><strong>{c.first_name} {c.last_name}</strong></td>
                <td>{c.role_title ?? "—"}</td>
                <td>{c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : "—"}</td>
                <td className="mono">{c.phone ? <a href={`tel:${c.phone}`}>{c.phone}</a> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {creating && <ContactCreateModal companyId={companyId} onClose={() => setCreating(false)} />}
    </Card>
  );
}

function TasksTab({ companyId }: { companyId: string }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const { data } = useQuery({
    queryKey: ["tasks", "company", companyId],
    queryFn: () => api.get<Page<Task>>(`/tasks?entity_type=company&entity_id=${companyId}`),
  });
  const add = useMutation({
    mutationFn: () =>
      api.post("/tasks", { title, entity_type: "company", entity_id: companyId }),
    onSuccess: () => { setTitle(""); qc.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  const complete = useMutation({
    mutationFn: (id: string) => api.patch(`/tasks/${id}`, { status: "done" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  return (
    <Card className="card__pad">
      <form className="toolbar" onSubmit={(e: FormEvent) => { e.preventDefault(); if (title.trim()) add.mutate(); }}>
        <input className="input" placeholder="Nuova attività per questa azienda…" value={title}
               onChange={(e) => setTitle(e.target.value)} />
        <button className="btn btn--primary" type="submit" disabled={!title.trim()}>Aggiungi</button>
      </form>
      {!data || data.items.length === 0 ? <EmptyState>Nessuna attività aperta.</EmptyState> : (
        <ul className="timeline">
          {data.items.map((t) => (
            <li className="timeline__item" key={t.id}>
              <span className="timeline__dot" />
              <div className="timeline__body" style={{ flex: 1, display: "flex", justifyContent: "space-between" }}>
                <span>{t.title} <StatusBadge status={t.priority} /></span>
                <span className="timeline__time">{t.due_date ? `Scade ${dateTimeIt(t.due_date)}` : ""}
                  {" "}<button className="btn btn--ghost btn--sm" onClick={() => complete.mutate(t.id)}>Completa</button>
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function NotesTab({ companyId }: { companyId: string }) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const { data } = useQuery({
    queryKey: ["notes", "company", companyId],
    queryFn: () => api.get<Page<Note>>(`/notes?entity_type=company&entity_id=${companyId}`),
  });
  const add = useMutation({
    mutationFn: () => api.post("/notes", { body, entity_type: "company", entity_id: companyId }),
    onSuccess: () => { setBody(""); qc.invalidateQueries({ queryKey: ["notes"] }); },
  });

  return (
    <Card className="card__pad">
      <div className="field">
        <textarea className="textarea" rows={3} placeholder="Aggiungi una nota…" value={body}
                  onChange={(e) => setBody(e.target.value)} />
      </div>
      <button className="btn btn--primary btn--sm" disabled={!body.trim()} onClick={() => add.mutate()}>
        Salva nota
      </button>
      {!data || data.items.length === 0 ? <EmptyState>Nessuna nota.</EmptyState> : (
        <ul className="timeline" style={{ marginTop: 16 }}>
          {data.items.map((n) => (
            <li className="timeline__item" key={n.id}>
              <span className="timeline__dot" />
              <div className="timeline__body">
                {n.body}
                <div className="timeline__time">{dateTimeIt(n.created_at)}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function TimelineTab({ companyId }: { companyId: string }) {
  const { data } = useQuery({
    queryKey: ["timeline", "company", companyId],
    queryFn: () => api.get<Page<ActivityEvent>>(`/timeline/company/${companyId}`),
  });
  if (!data || data.items.length === 0) return <EmptyState>Nessun evento registrato.</EmptyState>;
  return (
    <Card className="card__pad">
      <ul className="timeline">
        {data.items.map((e) => (
          <li className="timeline__item" key={e.id}>
            <span className="timeline__dot" />
            <div className="timeline__body">
              {e.summary}
              <div className="timeline__time">{dateTimeIt(e.created_at)} · {e.event_type}</div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function InvoicesTab({ companyId }: { companyId: string }) {
  const { data } = useQuery({
    queryKey: ["invoices", "company", companyId],
    queryFn: () => api.get<Page<Invoice>>(`/billing/invoices?company_id=${companyId}`),
  });
  if (!data || data.items.length === 0) return <EmptyState>Nessuna fattura per questa azienda.</EmptyState>;
  return (
    <Card>
      <table className="table">
        <thead><tr><th>N°</th><th>Data</th><th>Totale</th><th>Stato</th><th>Provider</th></tr></thead>
        <tbody>
          {data.items.map((i) => (
            <tr key={i.id} style={{ cursor: "default" }}>
              <td className="mono">{i.number ? `${i.series}${i.number}/${i.fiscal_year}` : "bozza"}</td>
              <td>{dateIt(i.issue_date)}</td>
              <td className="mono">{eur(i.total_amount)}</td>
              <td><StatusBadge status={i.status} /></td>
              <td className="muted">{i.provider_key ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function FundingTab({ companyId }: { companyId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["funding-overview", companyId],
    queryFn: () => api.get<FundingOverview>(`/funding/companies/${companyId}/overview`),
  });
  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner error={error} />;
  if (!data) return <EmptyState>Nessun dato agevolativo.</EmptyState>;
  const dm = data.de_minimis;
  return (
    <>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card className="card__pad">
          <h4>Profilo agevolativo</h4>
          {!data.profile ? (
            <EmptyState>Profilo non dichiarato — i dati mancanti restano
              espliciti, mai assunti.</EmptyState>
          ) : (
            <dl className="dl">
              <dt>Regione progetto</dt><dd>{data.profile.project_region ?? "n/d"}</dd>
              <dt>Startup</dt><dd>{data.profile.is_startup === null ? "n/d" : data.profile.is_startup ? "sì" : "no"}</dd>
              <dt>Quota femminile</dt><dd>{data.profile.female_ownership_pct ?? "n/d"}%</dd>
              <dt>Storico aiuti completo</dt><dd>{data.profile.aid_history_complete === null ? "n/d" : data.profile.aid_history_complete ? "sì" : "no"}</dd>
            </dl>
          )}
        </Card>
        <Card className="card__pad">
          <h4>De minimis</h4>
          <p><StatusBadge status={dm.status} /></p>
          {dm.regime && (
            <p className="muted" style={{ fontSize: 12 }}>
              {dm.regime.code} — soglia {eur(Number(dm.regime.threshold))} su{" "}
              {dm.regime.period_months} mesi
            </p>
          )}
          {dm.aid_total != null && (
            <p style={{ fontSize: 13 }}>
              Aiuti: {eur(Number(dm.aid_total))} — residuo {eur(Number(dm.headroom))}
            </p>
          )}
        </Card>
      </div>
      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="toolbar" style={{ justifyContent: "space-between" }}>
          <h4 style={{ margin: 0 }}>Valutazioni e pratiche</h4>
          <Link to={`/funding?company=${companyId}`} className="btn btn--ghost btn--sm">
            Apri workspace →
          </Link>
        </div>
        {!data.assessments.length && !data.practices.length ? (
          <EmptyState>Nessuna valutazione né pratica.</EmptyState>
        ) : (
          <table className="table">
            <tbody>
              {data.assessments.map((a) => (
                <tr key={a.id}>
                  <td>Valutazione <span className="muted">{a.engine_version}</span></td>
                  <td><StatusBadge status={a.result} /></td>
                  <td className="muted">{dateTimeIt(a.assessed_at)}</td>
                </tr>
              ))}
              {data.practices.map((p) => (
                <tr key={p.id}>
                  <td>Pratica <span className="muted">{p.programme_title ?? ""}</span></td>
                  <td><StatusBadge status={p.status} /></td>
                  <td className="muted">{p.id.slice(0, 8)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data.deadlines.length > 0 && (
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            Scadenze aperte: {data.deadlines.length} — prossima{" "}
            {dateTimeIt(data.deadlines[0].due_at)}
          </p>
        )}
      </Card>
    </>
  );
}

function DossierTab({ companyId }: { companyId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dossier", companyId],
    queryFn: () =>
      api.get<CompanyDossier>(`/practices/companies/${companyId}/dossier`),
  });
  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner error={error} />;
  if (!data) return <EmptyState>Nessun dato operativo.</EmptyState>;
  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <Card className="card__pad">
        <h4>Pratiche ({data.practices.length})</h4>
        {data.practices.length === 0 ? (
          <EmptyState>Nessuna pratica.</EmptyState>
        ) : (
          <table className="table">
            <tbody>
              {data.practices.map((p) => (
                <tr key={p.id}>
                  <td>{p.title}
                    <div className="muted" style={{ fontSize: "0.75rem" }}>
                      {p.practice_type}
                      {p.source_module ? ` · ${p.source_module}` : ""}
                    </div>
                  </td>
                  <td><StatusBadge status={p.status} /></td>
                  <td>
                    {p.open_blockers > 0 && (
                      <span className="badge badge--danger">
                        {p.open_blockers} blocchi
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card className="card__pad">
        <h4>Documenti mancanti ({data.missing_documents.length})</h4>
        {data.missing_documents.length === 0 ? (
          <EmptyState>Nessun requisito scoperto.</EmptyState>
        ) : (
          <table className="table">
            <tbody>
              {data.missing_documents.map((r) => (
                <tr key={r.id}>
                  <td>{r.label}
                    <div className="muted" style={{ fontSize: "0.75rem" }}>
                      {r.module} · {r.doc_type_code}
                    </div>
                  </td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{r.mandatory && (
                    <span className="badge badge--danger">obbligatorio</span>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card className="card__pad">
        <h4>Richieste al cliente ({data.client_requests.length})</h4>
        {data.client_requests.length === 0 ? (
          <EmptyState>Nessuna richiesta.</EmptyState>
        ) : (
          <table className="table">
            <tbody>
              {data.client_requests.map((r) => (
                <tr key={r.id}>
                  <td>{r.item}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="mono">{r.due_at ? dateTimeIt(r.due_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card className="card__pad">
        <h4>Scadenze operative ({data.deadlines.length})</h4>
        {data.deadlines.length === 0 ? (
          <EmptyState>Nessuna scadenza aperta.</EmptyState>
        ) : (
          <table className="table">
            <tbody>
              {data.deadlines.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td>
                  <td><StatusBadge status={d.status} /></td>
                  <td className="mono">{d.due_at ? dateTimeIt(d.due_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card className="card__pad" style={{ gridColumn: "1 / -1" }}>
        <h4>Attività recenti</h4>
        {data.activities.length === 0 ? (
          <EmptyState>Nessuna attività registrata.</EmptyState>
        ) : (
          <ul className="timeline">
            {data.activities.slice(0, 15).map((a) => (
              <li className="timeline__item" key={a.id}>
                <span className="timeline__dot" />
                <div className="timeline__body">
                  <span>{a.summary}</span>
                  <span className="timeline__time">{dateTimeIt(a.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("overview");

  const { data: company, isLoading, error } = useQuery({
    queryKey: ["company", id],
    queryFn: () => api.get<Company>(`/companies/${id}`),
  });
  const { data: completeness } = useQuery({
    queryKey: ["completeness", id],
    queryFn: () => api.get<{ score: number; missing_fields: string[] }>(`/companies/${id}/completeness`),
  });

  if (isLoading) return <Spinner />;
  if (error || !company) return <ErrorBanner error={error} />;

  return (
    <>
      <div className="record-head">
        <div>
          <div className="record-head__id">
            <h1>{company.legal_name}</h1>
            <StatusBadge status={company.status} />
            <StatusBadge status={company.lifecycle_stage} />
          </div>
          <div className="page-head__meta">
            {company.vat_number && <>P.IVA {company.vat_number} · </>}
            {[company.city, company.region].filter(Boolean).join(", ")}
            {company.ateco_code && <> · ATECO {company.ateco_code}</>}
          </div>
        </div>
        <Link to="/companies" className="btn btn--ghost btn--sm">← Elenco</Link>
      </div>

      {completeness && completeness.missing_fields.length > 0 && (
        <div className="alert alert--info">
          Scheda completata al {completeness.score}%. Campi mancanti: {completeness.missing_fields.join(", ")}.
        </div>
      )}

      <div className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key}
                  className={`tab${tab === key ? " tab--active" : ""}`}
                  onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <Card className="card__pad">
          <dl className="dl">
            <dt>Ragione sociale</dt><dd>{company.legal_name}</dd>
            <dt>Nome commerciale</dt><dd>{company.trading_name ?? "—"}</dd>
            <dt>P.IVA</dt><dd className="mono">{company.vat_number ?? "—"}</dd>
            <dt>Codice fiscale</dt><dd className="mono">{company.tax_code ?? "—"}</dd>
            <dt>Forma giuridica</dt><dd>{company.legal_form ?? "—"}</dd>
            <dt>ATECO</dt><dd>{company.ateco_code ?? "—"}</dd>
            <dt>Settore</dt><dd>{company.industry ?? "—"}</dd>
            <dt>Dimensione</dt><dd>{company.size_band} · {company.employee_count ?? "?"} dipendenti · {eur(company.revenue_eur)}</dd>
            <dt>Sede</dt><dd>{[company.address, company.city, company.region, company.country].filter(Boolean).join(", ") || "—"}</dd>
            <dt>Email</dt><dd>{company.email ?? "—"}</dd>
            <dt>PEC</dt><dd>{company.pec ?? "—"}</dd>
            <dt>Telefono</dt><dd>{company.phone ?? "—"}</dd>
            <dt>Sito</dt><dd>{company.website ? <a href={company.website} target="_blank" rel="noreferrer">{company.website}</a> : "—"}</dd>
            <dt>Fonte</dt><dd>{company.source ?? "—"}</dd>
            <dt>Tag</dt><dd>{company.tags.length ? company.tags.join(", ") : "—"}</dd>
          </dl>
        </Card>
      )}

      {tab === "contacts" && <ContactsTab companyId={company.id} />}
      {tab === "tasks" && <TasksTab companyId={company.id} />}
      {tab === "notes" && <NotesTab companyId={company.id} />}
      {tab === "invoices" && <InvoicesTab companyId={company.id} />}
      {tab === "funding" && <FundingTab companyId={company.id} />}
      {tab === "dossier" && <DossierTab companyId={company.id} />}
      {tab === "timeline" && <TimelineTab companyId={company.id} />}
    </>
  );
}
