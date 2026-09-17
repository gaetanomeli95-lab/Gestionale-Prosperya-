import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  ActivityEvent, Company, Contact, FundingOverview, Invoice, Note, Page, Task,
} from "../api/types";
import {
  Card, EmptyState, ErrorBanner, Spinner, StatusBadge,
} from "../components/ui";
import { dateIt, dateTimeIt, eur } from "../lib/format";

const TABS = [
  ["overview", "Quadro"],
  ["contacts", "Contatti"],
  ["tasks", "Attività"],
  ["notes", "Note"],
  ["invoices", "Fatture"],
  ["funding", "Agevolazioni"],
  ["timeline", "Cronologia"],
] as const;

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

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("overview");

  const { data: company, isLoading, error } = useQuery({
    queryKey: ["company", id],
    queryFn: () => api.get<Company>(`/companies/${id}`),
  });
  const { data: contacts } = useQuery({
    queryKey: ["contacts", "company", id],
    queryFn: () => api.get<Page<Contact>>("/contacts?page_size=200"),
    enabled: tab === "contacts",
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

      {tab === "contacts" && (
        <Card className="card__pad">
          <EmptyState>
            I contatti collegati all'azienda sono gestiti dalla sezione{" "}
            <Link to="/contacts">Contatti</Link>.{contacts ? ` (${contacts.total} contatti totali in CRM)` : ""}
          </EmptyState>
        </Card>
      )}
      {tab === "tasks" && <TasksTab companyId={company.id} />}
      {tab === "notes" && <NotesTab companyId={company.id} />}
      {tab === "invoices" && <InvoicesTab companyId={company.id} />}
      {tab === "funding" && <FundingTab companyId={company.id} />}
      {tab === "timeline" && <TimelineTab companyId={company.id} />}
    </>
  );
}
