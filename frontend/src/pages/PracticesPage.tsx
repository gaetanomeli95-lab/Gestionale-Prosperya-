import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AlertOctagon, CalendarClock, FolderKanban, Hourglass } from "lucide-react";
import { api } from "../api/client";
import type { CompanyListItem, Page, Practice } from "../api/types";
import {
  Badge, EmptyState, ErrorBanner, Field, Modal, PageHeader, Section, Segmented, Skeleton, Stat, statusLabel, toast,
} from "../components/ui";
import { dateIt } from "../lib/format";

/** Deadline → operational Task (exactly-once via sync_key on the backend). */
function DeadlineModal({ practice, onClose }: { practice: Practice; onClose: () => void }) {
  const qc = useQueryClient();
  const uid = useId();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/practices/${practice.id}/deadlines`, {
      title, due_at: new Date(`${due}T12:00:00`).toISOString(), kind: "deadline",
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["practices"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      toast("Scadenza creata: attività aggiunta alla coda operativa");
      onClose();
    },
  });
  const formId = `${uid}-form`;
  return (
    <Modal title={`Scadenza — ${practice.title}`} subtitle="Crea un'attività nella coda operativa. Ripetere la stessa scadenza aggiorna l'attività esistente, non la duplica."
           size="sm" onClose={onClose}
           footer={<>
             <button type="button" className="btn btn--ghost" onClick={onClose}>Annulla</button>
             <button type="submit" form={formId} className="btn btn--primary" disabled={add.isPending || !title.trim() || !due}>Crea scadenza</button>
           </>}>
      <form id={formId} aria-label="Nuova scadenza"
            onSubmit={(e: FormEvent) => { e.preventDefault(); if (title.trim() && due) add.mutate(); }}>
        {add.error && <ErrorBanner error={add.error} />}
        <div className="form-grid">
          <Field label="Titolo *" htmlFor={`${uid}-t`} span2>
            <input id={`${uid}-t`} className="input" required autoFocus value={title}
                   onChange={(e) => setTitle(e.target.value)} placeholder="es. Consegna bilancio firmato" />
          </Field>
          <Field label="Data *" htmlFor={`${uid}-d`}>
            <input id={`${uid}-d`} className="input" type="date" required value={due}
                   onChange={(e) => setDue(e.target.value)} />
          </Field>
        </div>
      </form>
    </Modal>
  );
}

const TRANSITIONS: Record<string, string[]> = {
  draft: ["open", "cancelled"],
  open: ["in_progress", "waiting_client", "waiting_external", "cancelled"],
  in_progress: ["waiting_client", "waiting_external", "ready", "completed", "cancelled"],
  waiting_client: ["in_progress", "cancelled"],
  waiting_external: ["in_progress", "cancelled"],
  ready: ["completed", "in_progress", "cancelled"],
};
const ACTION_LABEL: Record<string, string> = {
  open: "Apri", in_progress: "Avvia", waiting_client: "Attendi cliente", waiting_external: "Attendi esterno",
  ready: "Pronta", completed: "Completa", cancelled: "Annulla",
};
const PRACTICE_STATUS_LABEL: Record<string, string> = {
  draft: "Bozza", open: "Aperta", in_progress: "In corso", waiting_client: "In attesa del cliente",
  waiting_external: "In attesa esterna", ready: "Pronta", completed: "Completata", cancelled: "Annullata",
};
const TYPE_LABEL: Record<string, string> = {
  generic: "Generica", fiscal: "Fiscale", startup: "Startup", consulting: "Consulenza", funding: "Finanza agevolata", corporate: "Societaria",
};
const MODULE_LABEL: Record<string, string> = { funding: "Finanza agevolata", documents: "Documenti", fiscal: "Fisco", manual: "Manuale" };
const OPEN_STATES = ["draft", "open", "in_progress", "waiting_client", "waiting_external", "ready"];

type View = "all" | "blocked" | "due";

export default function PracticesPage() {
  const [companyId, setCompanyId] = useState("");
  const [status, setStatus] = useState("");
  const [view, setView] = useState<View>("all");
  const [title, setTitle] = useState("");
  const [type, setType] = useState("generic");
  const [deadlineFor, setDeadlineFor] = useState<Practice | null>(null);
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
    mutationFn: () => api.post(`/practices/companies/${companyId}`, { title, practice_type: type }),
    onSuccess: () => { setTitle(""); qc.invalidateQueries({ queryKey: ["practices"] }); toast("Pratica creata"); },
  });

  const transition = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) => api.post(`/practices/${id}/transition`, { action }),
    onSuccess: (_r, v) => { qc.invalidateQueries({ queryKey: ["practices"] }); toast(`Pratica: ${PRACTICE_STATUS_LABEL[v.action] ?? statusLabel(v.action)}`); },
  });

  const all = practices.data?.practices ?? [];
  const now = Date.now();
  const soon = now + 14 * 86_400_000;
  const isOpen = (p: Practice) => OPEN_STATES.includes(p.status);
  const isDue = (p: Practice) => isOpen(p) && !!p.target_date && new Date(p.target_date).getTime() <= soon;
  const isOverdue = (p: Practice) => isOpen(p) && !!p.target_date && new Date(p.target_date).getTime() < now;
  const blocked = all.filter((p) => isOpen(p) && p.open_blockers > 0);
  const due = all.filter(isDue);
  const shown = view === "blocked" ? blocked : view === "due" ? due : all;
  const waitingClient = all.filter((p) => p.status === "waiting_client").length;

  return (
    <>
      <PageHeader
        hero
        eyebrow="Lavoro"
        title="Pratiche"
        question="Quale lavoro è bloccato o vicino a una scadenza? Casi operativi trasversali: funding, fiscale, consulenza."
      />

      {practices.isLoading ? <Skeleton kind="stats" rows={4} /> : (
        <div className="stat-grid">
          <Stat hero icon={<AlertOctagon size={14} />} label="Bloccate" value={blocked.length}
                hint={`${blocked.reduce((s, p) => s + p.open_blockers, 0)} blocchi aperti in totale`} onClick={() => setView("blocked")} />
          <Stat icon={<CalendarClock size={14} />} label="In scadenza (14 giorni)" value={due.length}
                hint={`${all.filter(isOverdue).length} già oltre la data obiettivo`} tone={all.some(isOverdue) ? "danger" : due.length ? "warn" : undefined} onClick={() => setView("due")} />
          <Stat icon={<Hourglass size={14} />} label="In attesa del cliente" value={waitingClient} hint="documenti o risposte da ricevere" />
          <Stat icon={<FolderKanban size={14} />} label="Aperte" value={all.filter(isOpen).length} hint={`${all.length} in questa vista`} onClick={() => setView("all")} />
        </div>
      )}

      <Section title="Nuova pratica">
        <form className="toolbar" onSubmit={(e: FormEvent) => { e.preventDefault(); if (title.trim() && companyId) create.mutate(); }}>
          <select className="select" aria-label="Azienda" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            <option value="">Azienda…</option>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <input className="input" aria-label="Titolo pratica" placeholder="Nuova pratica…" value={title} onChange={(e) => setTitle(e.target.value)} />
          <select className="select" aria-label="Tipo pratica" value={type} onChange={(e) => setType(e.target.value)}>
            {["generic", "fiscal", "startup", "consulting"].map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select>
          <button className="btn btn--primary" type="submit" disabled={!title.trim() || !companyId || create.isPending}>Crea</button>
        </form>
        {create.error && <ErrorBanner error={create.error} />}
      </Section>

      <Section className="mt-4" flush
        title={<>Pratiche <span className="tab__count">{shown.length}</span></>}
        actions={<>
          <Segmented ariaLabel="Vista" value={view} onChange={setView} options={[
            { value: "all", label: "Tutte" }, { value: "blocked", label: `Bloccate (${blocked.length})` }, { value: "due", label: `In scadenza (${due.length})` },
          ]} />
          <select className="select select--sm" aria-label="Filtra per stato" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Tutti gli stati</option>
            {Object.keys(PRACTICE_STATUS_LABEL).map((s) => <option key={s} value={s}>{PRACTICE_STATUS_LABEL[s]}</option>)}
          </select>
        </>}
      >
        {practices.error && <ErrorBanner error={practices.error} />}
        {practices.isLoading ? <Skeleton kind="table" rows={5} /> :
         shown.length === 0 ? (
          <EmptyState title={view === "blocked" ? "Nessuna pratica bloccata" : view === "due" ? "Nessuna scadenza nei prossimi 14 giorni" : "Nessuna pratica in questa vista"}>
            {view === "all" ? "Crea la prima pratica scegliendo l'azienda qui sopra." : "Ottimo: il lavoro scorre."}
          </EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead>
              <tr>
                <th>Pratica</th><th>Azienda</th><th>Stato</th><th>Blocchi</th><th>Data obiettivo</th><th className="right">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => {
                const company = companies.data?.items.find((c) => c.id === p.company_id);
                const overdue = isOverdue(p);
                return (
                  <tr key={p.id}>
                    <td>
                      <div className="table__primary">{p.title}</div>
                      <div className="table__sub">{TYPE_LABEL[p.practice_type] ?? p.practice_type}{p.source_module ? ` · da ${MODULE_LABEL[p.source_module] ?? p.source_module}` : ""}</div>
                    </td>
                    <td>{company ? <Link to={`/companies/${company.id}`}>{company.legal_name}</Link> : <span className="muted">—</span>}</td>
                    <td><Badge tone={p.status === "completed" ? "success" : p.status === "cancelled" ? "neutral" : p.status.startsWith("waiting") ? "warning" : p.status === "ready" ? "accent" : "primary"} title={p.status}>{PRACTICE_STATUS_LABEL[p.status] ?? statusLabel(p.status)}</Badge></td>
                    <td>{p.open_blockers > 0 ? <Badge tone="danger">{p.open_blockers} {p.open_blockers === 1 ? "aperto" : "aperti"}</Badge> : <span className="muted">—</span>}</td>
                    <td className="num">
                      {p.target_date ? <span className={overdue ? "neg strong" : isDue(p) ? "strong" : undefined}>{dateIt(p.target_date)}{overdue ? " · scaduta" : ""}</span> : <span className="muted">—</span>}
                    </td>
                    <td className="right nowrap">
                      <button className="btn btn--ghost btn--sm" aria-label={`Aggiungi scadenza a ${p.title}`} onClick={() => setDeadlineFor(p)}>+ Scadenza</button>
                      {(TRANSITIONS[p.status] ?? []).slice(0, 2).map((a) => (
                        <button key={a} className={`btn btn--sm ${a === "cancelled" ? "btn--danger" : "btn--ghost"}`} disabled={transition.isPending}
                                onClick={() => transition.mutate({ id: p.id, action: a })}>
                          {ACTION_LABEL[a] ?? a}
                        </button>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Section>
      {deadlineFor && <DeadlineModal practice={deadlineFor} onClose={() => setDeadlineFor(null)} />}
    </>
  );
}
