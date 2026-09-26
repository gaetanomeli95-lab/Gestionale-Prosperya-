import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight, CalendarClock, FileWarning, FolderKanban, Gauge, Mail, MessageSquareText, Phone, ShieldAlert, Users,
} from "lucide-react";
import { api } from "../api/client";
import type {
  ActivityEvent, Company, CompanyDossier, Contact, FundingOverview,
  Invoice, Note, Page, Task,
} from "../api/types";
import {
  Badge, Callout, EmptyState, ErrorBanner, KV, Progress, Row, Section, Skeleton, Stat, StatusBadge, Tabs, Tile, statusLabel, toast,
} from "../components/ui";
import { dateIt, dateTimeIt, eur } from "../lib/format";
import { ContactCreateModal } from "../components/ContactCreateModal";

type TabKey = "overview" | "contacts" | "tasks" | "notes" | "invoices" | "funding" | "dossier" | "timeline";

const SIZE_LABEL: Record<string, string> = { micro: "Micro", small: "Piccola", medium: "Media", large: "Grande" };
const MODULE_LABEL: Record<string, string> = {
  funding: "Finanza agevolata", practices: "Pratiche", documents: "Documenti", fiscal: "Fisco", billing: "Fatturazione",
  generic: "Generica", manual: "Manuale",
};
const PRACTICE_TYPE_LABEL: Record<string, string> = {
  generic: "Generica", funding: "Finanza agevolata", fiscal: "Fiscale", corporate: "Societaria", consulting: "Consulenza",
};

function useDossier(companyId: string) {
  return useQuery({
    queryKey: ["dossier", companyId],
    queryFn: () => api.get<CompanyDossier>(`/practices/companies/${companyId}/dossier`),
  });
}

/* ---------------- Quadro: "cosa sta succedendo con questo cliente" ---------------- */

function OverviewTab({ company, onGo }: { company: Company; onGo: (t: TabKey) => void }) {
  const dossier = useDossier(company.id);
  const funding = useQuery({
    queryKey: ["funding-overview", company.id],
    queryFn: () => api.get<FundingOverview>(`/funding/companies/${company.id}/overview`),
  });
  const tasks = useQuery({
    queryKey: ["tasks", "company", company.id],
    queryFn: () => api.get<Page<Task>>(`/tasks?entity_type=company&entity_id=${company.id}`),
  });
  const { data: completeness } = useQuery({
    queryKey: ["completeness", company.id],
    queryFn: () => api.get<{ score: number; missing_fields: string[] }>(`/companies/${company.id}/completeness`),
  });

  if (dossier.isLoading) return <><Skeleton kind="stats" rows={4} /><Skeleton rows={6} /></>;
  if (dossier.error) return <ErrorBanner error={dossier.error} />;
  const d = dossier.data!;
  const openTasks = (tasks.data?.items ?? []).filter((t) => t.status !== "done" && t.status !== "cancelled");
  const blocked = d.practices.filter((p) => p.open_blockers > 0);
  const mandatoryMissing = d.missing_documents.filter((r) => r.mandatory);
  const now = Date.now();
  const soonDeadlines = [...d.deadlines]
    .filter((x) => x.status !== "done" && x.status !== "cancelled")
    .sort((a, b) => (a.due_at ?? "").localeCompare(b.due_at ?? ""));

  const todo: { key: string; tone: "critical" | "warning" | "info"; icon: typeof Gauge; title: string; sub: string; go: TabKey; trailing?: string }[] = [];
  soonDeadlines.slice(0, 4).forEach((x) => {
    const overdue = x.due_at ? new Date(x.due_at).getTime() < now : false;
    todo.push({ key: `dl-${x.id}`, tone: overdue ? "critical" : "warning", icon: CalendarClock, title: x.title,
      sub: overdue ? `Scaduta il ${dateIt(x.due_at)}` : `Scade il ${dateIt(x.due_at)}`, go: "dossier", trailing: statusLabel(x.status) });
  });
  mandatoryMissing.slice(0, 4).forEach((r) => {
    todo.push({ key: `doc-${r.id}`, tone: "critical", icon: FileWarning, title: r.label,
      sub: `Documento obbligatorio mancante · ${MODULE_LABEL[r.module] ?? r.module}`, go: "dossier" });
  });
  blocked.slice(0, 3).forEach((p) => {
    todo.push({ key: `pr-${p.id}`, tone: "warning", icon: FolderKanban, title: p.title,
      sub: `${p.open_blockers} ${p.open_blockers === 1 ? "blocco aperto" : "blocchi aperti"} · ${PRACTICE_TYPE_LABEL[p.practice_type] ?? p.practice_type}`, go: "dossier", trailing: statusLabel(p.status) });
  });
  openTasks.slice(0, 3).forEach((t) => {
    todo.push({ key: `t-${t.id}`, tone: "info", icon: Users, title: t.title,
      sub: t.due_date ? `Attività · scade ${dateIt(t.due_date)}` : "Attività aperta", go: "tasks", trailing: statusLabel(t.priority) });
  });

  const dm = funding.data?.de_minimis;

  return (
    <>
      <div className="stat-grid">
        <Stat hero icon={<ShieldAlert size={14} />} label="Da fare ora" value={todo.length}
              hint={`${soonDeadlines.length} scadenze · ${mandatoryMissing.length} documenti obbligatori mancanti · ${blocked.length} pratiche bloccate`} />
        <Stat icon={<FolderKanban size={14} />} label="Pratiche aperte" value={d.practices.filter((p) => !["closed", "completed", "cancelled"].includes(p.status)).length}
              hint={`${blocked.length} con blocchi`} tone={blocked.length ? "warn" : undefined} onClick={() => onGo("dossier")} />
        <Stat icon={<FileWarning size={14} />} label="Documenti mancanti" value={d.missing_documents.length}
              hint={`${mandatoryMissing.length} obbligatori`} tone={mandatoryMissing.length ? "danger" : undefined} onClick={() => onGo("dossier")} />
        <Stat icon={<Users size={14} />} label="Attività aperte" value={openTasks.length}
              hint={`${d.client_requests.filter((r) => r.status !== "fulfilled").length} richieste al cliente`} onClick={() => onGo("tasks")} />
      </div>

      <div className="grid-2-1">
        <Section title="Da fare ora" actions={<button className="btn btn--ghost btn--sm" onClick={() => onGo("dossier")}>Dossier completo <ArrowRight size={12} /></button>}>
          {todo.length === 0 ? (
            <EmptyState title="Niente di urgente" icon={<Gauge size={20} strokeWidth={1.8} />}>
              Nessuna scadenza aperta, nessun documento obbligatorio mancante, nessuna pratica bloccata.
            </EmptyState>
          ) : (
            <div className="rows">
              {todo.map((it) => (
                <Row key={it.key} tone={it.tone} leading={<it.icon size={16} />} title={it.title} sub={it.sub}
                     trailing={it.trailing ? <Badge tone={it.tone === "critical" ? "danger" : it.tone === "warning" ? "warning" : "neutral"}>{it.trailing}</Badge> : <ArrowRight size={14} className="muted" />}
                     onClick={() => onGo(it.go)} />
              ))}
            </div>
          )}
        </Section>

        <div className="stack">
          <Section title="Scheda">
            {completeness && (
              <div className="mb-3">
                <Progress value={completeness.score} tone={completeness.score < 60 ? "warn" : completeness.score < 90 ? "accent" : "success"}
                          label={`${completeness.score}% completa`} />
                {completeness.missing_fields.length > 0 && (
                  <div className="text-xs muted mt-1">Mancano: {completeness.missing_fields.join(", ")}</div>
                )}
              </div>
            )}
            <KV columns={2} items={[
              { k: "P.IVA", v: company.vat_number && <span className="num">{company.vat_number}</span> },
              { k: "Codice fiscale", v: company.tax_code && <span className="num">{company.tax_code}</span> },
              { k: "Forma giuridica", v: company.legal_form },
              { k: "ATECO", v: company.ateco_code },
              { k: "Settore", v: company.industry },
              { k: "Dimensione", v: company.size_band !== "unknown" ? `${SIZE_LABEL[company.size_band] ?? company.size_band}${company.employee_count != null ? ` · ${company.employee_count} dip.` : ""}` : null },
              { k: "Fatturato", v: company.revenue_eur != null ? eur(company.revenue_eur) : null },
              { k: "Sede", v: [company.address, company.city, company.region].filter(Boolean).join(", ") || null },
              { k: "Email", v: company.email && <a href={`mailto:${company.email}`}>{company.email}</a> },
              { k: "PEC", v: company.pec && <a href={`mailto:${company.pec}`}>{company.pec}</a> },
              { k: "Telefono", v: company.phone && <a href={`tel:${company.phone}`}>{company.phone}</a> },
              { k: "Sito", v: company.website && <a href={company.website} target="_blank" rel="noreferrer">{company.website}</a> },
            ]} />
            {company.tags.length > 0 && (
              <div className="cluster mt-3">{company.tags.map((t) => <Badge key={t} tone="accent" dot={false}>{t}</Badge>)}</div>
            )}
          </Section>

          <Section title="Finanza agevolata" actions={<Link to={`/funding?company=${company.id}`} className="btn btn--ghost btn--sm">Apri <ArrowRight size={12} /></Link>}>
            {funding.isLoading ? <Skeleton rows={3} /> : funding.error ? <ErrorBanner error={funding.error} /> : (
              <div className="grid-auto grid-auto--sm">
                <Tile label="De minimis" value={<StatusBadge status={dm?.status} />}
                      hint={dm?.regime ? `Soglia ${eur(Number(dm.regime.threshold))} su ${dm.regime.period_months} mesi` : undefined} />
                <Tile label="Residuo" value={dm?.headroom != null ? eur(Number(dm.headroom)) : <span className="na">n.d.</span>}
                      hint={dm?.aid_total != null ? `Aiuti ricevuti ${eur(Number(dm.aid_total))}` : "Storico aiuti non dichiarato"} />
                <Tile label="Pratiche" value={funding.data?.practices.length ?? 0} hint={`${funding.data?.assessments.length ?? 0} valutazioni`} />
              </div>
            )}
          </Section>
        </div>
      </div>
    </>
  );
}

/* ---------------- Contatti ---------------- */

function ContactsTab({ companyId }: { companyId: string }) {
  const [creating, setCreating] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["contacts", "company", companyId],
    queryFn: () => api.get<Page<Contact>>(`/contacts?page_size=200&company_id=${companyId}`),
  });

  return (
    <Section
      title={<>{data ? `${data.total} ${data.total === 1 ? "contatto collegato" : "contatti collegati"}` : "Contatti"}</>}
      actions={<><Link to="/contacts" className="btn btn--ghost btn--sm">Tutti i contatti</Link><button className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>+ Nuovo contatto</button></>}
      flush={!!data && data.items.length > 0}
    >
      {error && <ErrorBanner error={error} />}
      {isLoading ? <Skeleton kind="table" rows={3} /> : !data || data.items.length === 0 ? (
        <EmptyState title="Nessun contatto collegato" icon={<Users size={20} strokeWidth={1.8} />}
                    action={<button className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>Aggiungi il referente principale</button>}>
          Serve almeno un referente per inviare richieste documentali e comunicazioni.
        </EmptyState>
      ) : (
        <table className="table table--flush table--static">
          <thead><tr><th>Nome</th><th>Ruolo</th><th>Email</th><th>Telefono</th></tr></thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.id}>
                <td><span className="table__primary">{c.first_name} {c.last_name}</span></td>
                <td>{c.role_title ?? <span className="muted">—</span>}</td>
                <td>{c.email ? <a href={`mailto:${c.email}`} className="cluster"><Mail size={13} />{c.email}</a> : <span className="muted">—</span>}</td>
                <td className="num">{c.phone ? <a href={`tel:${c.phone}`} className="cluster"><Phone size={13} />{c.phone}</a> : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {creating && <ContactCreateModal companyId={companyId} onClose={() => setCreating(false)} />}
    </Section>
  );
}

/* ---------------- Attività ---------------- */

function TasksTab({ companyId }: { companyId: string }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["tasks", "company", companyId],
    queryFn: () => api.get<Page<Task>>(`/tasks?entity_type=company&entity_id=${companyId}`),
  });
  const add = useMutation({
    mutationFn: () => api.post("/tasks", { title, entity_type: "company", entity_id: companyId }),
    onSuccess: () => { setTitle(""); qc.invalidateQueries({ queryKey: ["tasks"] }); toast("Attività aggiunta"); },
  });
  const complete = useMutation({
    mutationFn: (id: string) => api.patch(`/tasks/${id}`, { status: "done" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tasks"] }); toast("Attività completata"); },
  });
  const open = (data?.items ?? []).filter((t) => t.status !== "done" && t.status !== "cancelled");
  const done = (data?.items ?? []).filter((t) => t.status === "done");

  return (
    <Section title={`Attività · ${open.length} aperte`}>
      <form className="toolbar" onSubmit={(e: FormEvent) => { e.preventDefault(); if (title.trim()) add.mutate(); }}>
        <input className="input" placeholder="Nuova attività per questa azienda…" aria-label="Nuova attività" value={title}
               onChange={(e) => setTitle(e.target.value)} />
        <button className="btn btn--primary" type="submit" disabled={!title.trim() || add.isPending}>Aggiungi</button>
      </form>
      {isLoading ? <Skeleton rows={4} /> : open.length === 0 ? (
        <EmptyState title="Nessuna attività aperta">Aggiungi la prossima cosa da fare per questo cliente.</EmptyState>
      ) : (
        <div className="rows">
          {open.map((t) => (
            <Row key={t.id} title={t.title}
                 sub={t.due_date ? `Scade ${dateIt(t.due_date)}` : "Senza scadenza"}
                 trailing={<><StatusBadge status={t.priority} /><button className="btn btn--ghost btn--sm" onClick={() => complete.mutate(t.id)}>Completa</button></>} />
          ))}
        </div>
      )}
      {done.length > 0 && (
        <details className="mt-3">
          <summary className="eyebrow eyebrow--muted">Completate ({done.length})</summary>
          <div className="rows mt-2">
            {done.map((t) => <Row key={t.id} title={<span className="muted">{t.title}</span>} sub={t.completed_at ? `Completata ${dateIt(t.completed_at)}` : undefined} />)}
          </div>
        </details>
      )}
    </Section>
  );
}

/* ---------------- Note ---------------- */

function NotesTab({ companyId }: { companyId: string }) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["notes", "company", companyId],
    queryFn: () => api.get<Page<Note>>(`/notes?entity_type=company&entity_id=${companyId}`),
  });
  const add = useMutation({
    mutationFn: () => api.post("/notes", { body, entity_type: "company", entity_id: companyId }),
    onSuccess: () => { setBody(""); qc.invalidateQueries({ queryKey: ["notes"] }); toast("Nota salvata"); },
  });

  return (
    <div className="grid-1-2">
      <Section title="Nuova nota">
        <div className="field">
          <textarea className="textarea" rows={5} placeholder="Cosa è emerso, cosa è stato deciso…" aria-label="Testo della nota" value={body}
                    onChange={(e) => setBody(e.target.value)} />
        </div>
        <button className="btn btn--primary w-full" disabled={!body.trim() || add.isPending} onClick={() => add.mutate()}>Salva nota</button>
      </Section>
      <Section title={`Note · ${data?.total ?? 0}`}>
        {isLoading ? <Skeleton rows={4} /> : !data || data.items.length === 0 ? (
          <EmptyState title="Nessuna nota" icon={<MessageSquareText size={20} strokeWidth={1.8} />}>Le note restano nel dossier e sono visibili al team.</EmptyState>
        ) : (
          <ul className="timeline">
            {data.items.map((n) => (
              <li className="timeline__item" key={n.id}>
                <span className="timeline__dot" />
                <div className="timeline__body">
                  {n.body}
                  <div className="timeline__time">{dateTimeIt(n.created_at)}{n.pinned ? " · in evidenza" : ""}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

/* ---------------- Cronologia ---------------- */

const EVENT_LABEL: Record<string, string> = {
  created: "creazione", updated: "aggiornamento", note_added: "nota", task_created: "attività", task_completed: "attività completata",
  contact_linked: "contatto collegato", invoice_issued: "fattura emessa", practice_created: "pratica", document_uploaded: "documento",
};

function TimelineTab({ companyId }: { companyId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["timeline", "company", companyId],
    queryFn: () => api.get<Page<ActivityEvent>>(`/timeline/company/${companyId}`),
  });
  return (
    <Section title="Cronologia">
      {isLoading ? <Skeleton rows={5} /> : !data || data.items.length === 0 ? (
        <EmptyState title="Nessun evento registrato">Gli eventi compaiono qui man mano che il team lavora sul cliente.</EmptyState>
      ) : (
        <ul className="timeline">
          {data.items.map((e) => (
            <li className="timeline__item" key={e.id}>
              <span className="timeline__dot" />
              <div className="timeline__body">
                {e.summary}
                <div className="timeline__time">{dateTimeIt(e.created_at)} · {EVENT_LABEL[e.event_type] ?? e.event_type.replaceAll("_", " ")}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

/* ---------------- Fatture ---------------- */

function InvoicesTab({ companyId }: { companyId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["invoices", "company", companyId],
    queryFn: () => api.get<Page<Invoice>>(`/billing/invoices?company_id=${companyId}`),
  });
  const total = (data?.items ?? []).reduce((s, i) => s + (i.total_amount ?? 0), 0);
  return (
    <Section title={`Fatture · ${data?.total ?? 0}`} flush={!!data && data.items.length > 0}
             actions={<Link to="/billing" className="btn btn--ghost btn--sm">Fatturazione <ArrowRight size={12} /></Link>}
             footer={data && data.items.length > 0 ? <>Totale emesso: <span className="strong num">{eur(total)}</span></> : undefined}>
      {isLoading ? <Skeleton kind="table" rows={3} /> : !data || data.items.length === 0 ? (
        <EmptyState title="Nessuna fattura per questa azienda">Le fatture emesse dal modulo Fatturazione compaiono qui.</EmptyState>
      ) : (
        <table className="table table--flush table--static">
          <thead><tr><th>Numero</th><th>Data</th><th className="th--num">Totale</th><th>Stato</th><th>Canale</th></tr></thead>
          <tbody>
            {data.items.map((i) => (
              <tr key={i.id}>
                <td className="num table__primary">{i.number ? `${i.series}${i.number}/${i.fiscal_year}` : "Bozza"}</td>
                <td>{dateIt(i.issue_date)}</td>
                <td className="td--num">{eur(i.total_amount)}</td>
                <td><StatusBadge status={i.status} /></td>
                <td className="muted">{i.provider_key ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

/* ---------------- Agevolazioni ---------------- */

function FundingTab({ companyId }: { companyId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["funding-overview", companyId],
    queryFn: () => api.get<FundingOverview>(`/funding/companies/${companyId}/overview`),
  });
  if (isLoading) return <Skeleton rows={6} />;
  if (error) return <ErrorBanner error={error} />;
  if (!data) return <EmptyState title="Nessun dato agevolativo" />;
  const dm = data.de_minimis;
  const yesNo = (v: boolean | null) => v === null ? null : v ? "Sì" : "No";
  return (
    <div className="stack">
      <div className="grid-2">
        <Section title="Profilo agevolativo">
          {!data.profile ? (
            <Callout tone="neutral" title="Profilo non dichiarato">I dati mancanti restano espliciti, mai assunti. Compila il profilo dal workspace Finanza agevolata.</Callout>
          ) : (
            <KV columns={2} items={[
              { k: "Regione progetto", v: data.profile.project_region },
              { k: "Startup", v: yesNo(data.profile.is_startup) },
              { k: "Quota femminile", v: data.profile.female_ownership_pct != null ? `${data.profile.female_ownership_pct}%` : null },
              { k: "Storico aiuti completo", v: yesNo(data.profile.aid_history_complete) },
            ]} />
          )}
        </Section>
        <Section title="De minimis">
          <div className="grid-auto grid-auto--sm">
            <Tile label="Posizione" value={<StatusBadge status={dm.status} />} hint={dm.regime ? `${dm.regime.code} · soglia ${eur(Number(dm.regime.threshold))} su ${dm.regime.period_months} mesi` : undefined} />
            <Tile label="Aiuti ricevuti" value={dm.aid_total != null ? eur(Number(dm.aid_total)) : <span className="na">n.d.</span>} />
            <Tile label="Residuo" value={dm.headroom != null ? eur(Number(dm.headroom)) : <span className="na">n.d.</span>} tone={dm.headroom != null && Number(dm.headroom) <= 0 ? "danger" : undefined} />
          </div>
        </Section>
      </div>
      <Section title="Valutazioni e pratiche" actions={<Link to={`/funding?company=${companyId}`} className="btn btn--primary btn--sm">Apri workspace <ArrowRight size={12} /></Link>}
               footer={data.deadlines.length > 0 ? <>{data.deadlines.length} scadenze aperte · prossima {dateTimeIt(data.deadlines[0].due_at)}</> : undefined}>
        {!data.assessments.length && !data.practices.length ? (
          <EmptyState title="Nessuna valutazione né pratica" action={<Link to={`/funding?company=${companyId}`} className="btn btn--ghost btn--sm">Cerca programmi compatibili</Link>}>
            Esegui un match per scoprire le opportunità disponibili per questa azienda.
          </EmptyState>
        ) : (
          <div className="rows">
            {data.practices.map((p) => (
              <Row key={p.id} leading={<FolderKanban size={16} />} title={p.programme_title ?? "Pratica agevolativa"}
                   sub={[p.programme_code, p.version_no != null ? `v${p.version_no}` : null, p.created_at ? `aperta ${dateIt(p.created_at)}` : null].filter(Boolean).join(" · ")}
                   trailing={<StatusBadge status={p.status} />} />
            ))}
            {data.assessments.map((a) => (
              <Row key={a.id} leading={<Gauge size={16} />} title="Valutazione di ammissibilità" sub={`${dateTimeIt(a.assessed_at)} · motore ${a.engine_version}`}
                   trailing={<StatusBadge status={a.result} />} />
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

/* ---------------- Dossier operativo ---------------- */

function DossierTab({ companyId }: { companyId: string }) {
  const { data, isLoading, error } = useDossier(companyId);
  if (isLoading) return <Skeleton rows={8} />;
  if (error) return <ErrorBanner error={error} />;
  if (!data) return <EmptyState title="Nessun dato operativo" />;
  return (
    <div className="stack">
      <div className="grid-2">
        <Section title={`Pratiche (${data.practices.length})`} actions={<Link to="/practices" className="btn btn--ghost btn--sm">Pratiche <ArrowRight size={12} /></Link>}>
          {data.practices.length === 0 ? <EmptyState title="Nessuna pratica">Apri una pratica dal modulo Pratiche o da Finanza agevolata.</EmptyState> : (
            <div className="rows">
              {data.practices.map((p) => (
                <Row key={p.id} tone={p.open_blockers > 0 ? "warning" : undefined} leading={<FolderKanban size={16} />} title={p.title}
                     sub={[PRACTICE_TYPE_LABEL[p.practice_type] ?? p.practice_type, p.source_module ? MODULE_LABEL[p.source_module] ?? p.source_module : null, p.target_date ? `obiettivo ${dateIt(p.target_date)}` : null].filter(Boolean).join(" · ")}
                     trailing={<>{p.open_blockers > 0 && <Badge tone="danger">{p.open_blockers} {p.open_blockers === 1 ? "blocco" : "blocchi"}</Badge>}<StatusBadge status={p.status} /></>} />
              ))}
            </div>
          )}
        </Section>
        <Section title={`Documenti mancanti (${data.missing_documents.length})`} actions={<Link to="/documents" className="btn btn--ghost btn--sm">Documenti <ArrowRight size={12} /></Link>}>
          {data.missing_documents.length === 0 ? <EmptyState title="Nessun requisito scoperto">Tutti i documenti richiesti sono presenti.</EmptyState> : (
            <div className="rows">
              {data.missing_documents.map((r) => (
                <Row key={r.id} tone={r.mandatory ? "critical" : "info"} leading={<FileWarning size={16} />} title={r.label}
                     sub={`${MODULE_LABEL[r.module] ?? r.module} · ${r.doc_type_code.replaceAll("_", " ")}`}
                     trailing={<>{r.mandatory && <Badge tone="danger">Obbligatorio</Badge>}<StatusBadge status={r.status} /></>} />
              ))}
            </div>
          )}
        </Section>
        <Section title={`Richieste al cliente (${data.client_requests.length})`}>
          {data.client_requests.length === 0 ? <EmptyState title="Nessuna richiesta" /> : (
            <div className="rows">
              {data.client_requests.map((r) => (
                <Row key={r.id} title={r.item} sub={r.due_at ? `Entro ${dateTimeIt(r.due_at)}` : "Senza termine"} trailing={<StatusBadge status={r.status} />} />
              ))}
            </div>
          )}
        </Section>
        <Section title={`Scadenze operative (${data.deadlines.length})`}>
          {data.deadlines.length === 0 ? <EmptyState title="Nessuna scadenza aperta" /> : (
            <div className="rows">
              {data.deadlines.map((d) => {
                const overdue = d.due_at ? new Date(d.due_at).getTime() < Date.now() && d.status !== "done" : false;
                return <Row key={d.id} tone={overdue ? "critical" : "warning"} leading={<CalendarClock size={16} />} title={d.title}
                            sub={d.due_at ? `${overdue ? "Scaduta" : "Scade"} ${dateTimeIt(d.due_at)}` : "Senza data"} trailing={<StatusBadge status={d.status} />} />;
              })}
            </div>
          )}
        </Section>
      </div>
      <Section title="Attività recenti">
        {data.activities.length === 0 ? <EmptyState title="Nessuna attività registrata" /> : (
          <ul className="timeline">
            {data.activities.slice(0, 15).map((a) => (
              <li className="timeline__item" key={a.id}>
                <span className="timeline__dot" />
                <div className="timeline__body cluster cluster--between w-full">
                  <span>{a.summary}</span>
                  <span className="timeline__time">{dateTimeIt(a.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

/* ---------------- Page ---------------- */

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabKey>("overview");

  const { data: company, isLoading, error } = useQuery({
    queryKey: ["company", id],
    queryFn: () => api.get<Company>(`/companies/${id}`),
  });
  const dossier = useDossier(id!);

  if (isLoading) return <><Skeleton rows={2} /><Skeleton kind="stats" rows={4} /></>;
  if (error || !company) return <ErrorBanner error={error} />;

  const initials = company.legal_name.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const d = dossier.data;
  const missing = d?.missing_documents.length ?? 0;
  const blocked = d?.practices.filter((p) => p.open_blockers > 0).length ?? 0;

  const tabs: { key: TabKey; label: string; count?: number; tone?: string }[] = [
    { key: "overview", label: "Quadro" },
    { key: "contacts", label: "Contatti" },
    { key: "tasks", label: "Attività" },
    { key: "notes", label: "Note" },
    { key: "invoices", label: "Fatture" },
    { key: "funding", label: "Agevolazioni" },
    { key: "dossier", label: "Dossier", count: d ? missing + blocked : undefined, tone: missing + blocked > 0 ? "danger" : undefined },
    { key: "timeline", label: "Cronologia" },
  ];

  return (
    <>
      <section className="card dossier">
        <div className="dossier__mark" aria-hidden="true">{initials || "•"}</div>
        <div className="truncate">
          <div className="eyebrow">Dossier cliente</div>
          <h1 className="dossier__name">{company.legal_name}</h1>
          <div className="dossier__meta">
            <StatusBadge status={company.status} />
            <StatusBadge status={company.lifecycle_stage} />
            {company.vat_number && <span className="num">P.IVA {company.vat_number}</span>}
            {(company.city || company.region) && <span>{[company.city, company.region].filter(Boolean).join(", ")}</span>}
            {company.ateco_code && <span>ATECO {company.ateco_code}</span>}
            {company.size_band !== "unknown" && <span>{SIZE_LABEL[company.size_band] ?? company.size_band}</span>}
          </div>
        </div>
        <div className="dossier__actions">
          <Link to="/companies" className="btn btn--ghost btn--sm">← Elenco</Link>
          <Link to={`/controlling?company=${company.id}`} className="btn btn--ghost">Controlling</Link>
          <button className="btn btn--primary" onClick={() => navigate(`/cockpit/${company.id}`)}><Gauge size={15} /> Cockpit CFO</button>
        </div>
      </section>

      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {tab === "overview" && <OverviewTab company={company} onGo={setTab} />}
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
