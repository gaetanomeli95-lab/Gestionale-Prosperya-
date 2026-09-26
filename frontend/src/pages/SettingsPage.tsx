import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plug, ShieldCheck, UserPlus, Users } from "lucide-react";
import { api } from "../api/client";
import type { Page, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Callout, Dot, EmptyState, ErrorBanner, Field, Modal, PageHeader, Row, Section, Skeleton, Tabs, toast } from "../components/ui";

const STAFF = ["admin", "management", "consultant", "backoffice", "readonly"];
const ROLE_LABEL: Record<string, string> = {
  admin: "Amministratore", management: "Direzione", consultant: "Consulente",
  backoffice: "Back office", readonly: "Sola lettura",
  client_admin: "Amministratore", client_operator: "Operatore", client_readonly: "Sola lettura",
};

type Tab = "account" | "users" | "integrations";

export default function SettingsPage() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "client_admin";
  const [tab, setTab] = useState<Tab>("account");
  const tabs: { key: Tab; label: string }[] = [
    { key: "account", label: "Account e sicurezza" },
    ...(canManage ? [{ key: "users" as Tab, label: "Utenti" }] : []),
    { key: "integrations", label: "Integrazioni" },
  ];
  return (
    <>
      <PageHeader eyebrow="Strumenti" title="Impostazioni" question="Account, accessi del team e stato delle integrazioni esterne." />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "account" && (
        <div className="grid-1-2">
          <PasswordCard />
          <Section title={<><ShieldCheck size={13} /> Il tuo profilo</>}>
            <Row leading={<Users size={16} />} title={user?.full_name} sub={user?.email} trailing={<Badge tone="primary" dot={false}>{ROLE_LABEL[user?.role ?? ""] ?? user?.role}</Badge>} />
            <Callout tone="neutral" title="Sessione">Le sessioni scadono automaticamente; usa «Esci» dal menu laterale per chiudere l'accesso su questo dispositivo.</Callout>
          </Section>
        </div>
      )}
      {tab === "users" && canManage && <UsersCard me={user!} />}
      {tab === "integrations" && <IntegrationsCard />}
    </>
  );
}

function PasswordCard() {
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const m = useMutation({
    mutationFn: () => api.post("/auth/change-password", { current_password: f.current, new_password: f.next }),
    onSuccess: () => { setF({ current: "", next: "", confirm: "" }); toast("Password aggiornata"); },
  });
  const mismatch = !!f.confirm && f.next !== f.confirm;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mismatch) return;
    m.mutate();
  };
  return (
    <Section title={<><KeyRound size={13} /> Cambia password</>}>
      {m.error ? <ErrorBanner error={m.error} /> : null}
      <form onSubmit={submit} className="stack stack--sm">
        <Field label="Password attuale" htmlFor="password-attuale">
          <input id="password-attuale" className="input" type="password" required autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} />
        </Field>
        <Field label="Nuova password (min. 10)" htmlFor="nuova-password-min-10" hint="Almeno 10 caratteri. Evita password già usate altrove.">
          <input id="nuova-password-min-10" className="input" type="password" required minLength={10} autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} />
        </Field>
        <Field label="Conferma" htmlFor="conferma" error={mismatch ? "Le password non coincidono." : undefined}>
          <input id="conferma" className="input" type="password" required minLength={10} autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} />
        </Field>
        <div><button className="btn btn--primary" disabled={m.isPending || mismatch}>Aggiorna password</button></div>
      </form>
    </Section>
  );
}

function UsersCard({ me }: { me: User }) {
  const qc = useQueryClient();
  const isStaff = STAFF.includes(me.role);
  const roles = isStaff
    ? ["admin", "management", "consultant", "backoffice", "readonly"]
    : ["client_admin", "client_operator", "client_readonly"];
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ full_name: "", email: "", password: "", role: roles[roles.length === 5 ? 2 : 1] });

  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<Page<User>>("/users?page_size=200") });
  const create = useMutation({
    mutationFn: () => api.post("/users", { ...f, tenant_id: me.tenant_id }),
    onSuccess: () => { setOpen(false); setF({ ...f, full_name: "", email: "", password: "" }); qc.invalidateQueries({ queryKey: ["users"] }); toast("Utente creato"); },
  });
  const toggle = useMutation({
    mutationFn: (u: User) => api.patch(`/users/${u.id}`, { is_active: !u.is_active }),
    onSuccess: (_r, u) => { qc.invalidateQueries({ queryKey: ["users"] }); toast(u.is_active ? "Utente disattivato" : "Utente riattivato"); },
  });
  const items = users.data?.items ?? [];

  return (
    <Section title={<>Utenti <span className="tab__count">{items.length}</span></>} flush={items.length > 0}
             actions={<button className="btn btn--primary btn--sm" onClick={() => setOpen(true)}><UserPlus size={13} /> Nuovo utente</button>}>
      {users.isLoading ? <Skeleton kind="table" rows={4} /> : users.error ? <ErrorBanner error={users.error} /> : items.length === 0 ? (
        <EmptyState title="Nessun utente" action={<button className="btn btn--primary btn--sm" onClick={() => setOpen(true)}>Invita il primo collega</button>} />
      ) : (
        <table className="table table--flush table--static">
          <thead><tr><th>Nome</th><th>Ruolo</th><th>Stato</th><th className="right"></th></tr></thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.id}>
                <td><div className="table__primary">{u.full_name}{u.id === me.id && <span className="muted"> (tu)</span>}</div><div className="table__sub">{u.email}</div></td>
                <td>{ROLE_LABEL[u.role] ?? u.role}</td>
                <td><Badge tone={u.is_active ? "success" : "neutral"}>{u.is_active ? "Attivo" : "Disattivato"}</Badge></td>
                <td className="right">
                  {u.id !== me.id && (
                    <button className={`btn btn--sm ${u.is_active ? "btn--danger" : "btn--ghost"}`} disabled={toggle.isPending} onClick={() => toggle.mutate(u)}>
                      {u.is_active ? "Disattiva" : "Riattiva"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && (
        <Modal title="Nuovo utente" subtitle="L'utente riceve una password iniziale e potrà cambiarla da Impostazioni." size="sm" onClose={() => setOpen(false)}
          footer={<>
            <button className="btn btn--ghost" onClick={() => setOpen(false)}>Annulla</button>
            <button className="btn btn--primary" disabled={create.isPending || !f.full_name || !f.email || f.password.length < 10} onClick={() => create.mutate()}>Crea</button>
          </>}>
          {create.error ? <ErrorBanner error={create.error} /> : null}
          <Field label="Nome completo" htmlFor="nome-completo"><input id="nome-completo" className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Email" htmlFor="email"><input id="email" className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Password iniziale (min. 10)" htmlFor="password-iniziale-min-10" hint="Comunicala all'utente in modo sicuro.">
            <input id="password-iniziale-min-10" className="input" type="text" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          </Field>
          <Field label="Ruolo" htmlFor="ruolo">
            <select id="ruolo" className="select" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </Field>
        </Modal>
      )}
    </Section>
  );
}

/* ---------- Integration Center: "il provider esiste" ≠ "Prosperya ha un connettore" ---------- */

type CatalogEntry = {
  key: string; name: string; vendor: string; integration_kind: string; auth_model: string; protocol: string;
  api_version: string | null; research_status: string; status: string; adapter_registered: boolean;
  capabilities: Record<string, boolean | null>; commercial_prerequisites: string; known_limitations: string;
  documentation_url: string; documentation_quality: string; last_verified: string; notes: string; tags: string[];
};
const SUPPORT_LABEL: Record<string, { label: string; tone: string }> = {
  supported_in_prosperya: { label: "Connettore attivo", tone: "success" },
  in_development: { label: "In sviluppo", tone: "primary" },
  implementable: { label: "Implementabile", tone: "info" },
  supported_by_provider_api: { label: "API disponibile", tone: "info" },
  requires_credentials: { label: "Servono credenziali", tone: "warning" },
  requires_partner_agreement: { label: "Serve accordo partner", tone: "warning" },
  researched: { label: "Analizzato", tone: "neutral" },
  unavailable: { label: "Non integrabile", tone: "danger" },
  unknown: { label: "Da verificare", tone: "neutral" },
};
const KIND_LABEL: Record<string, string> = {
  public_rest: "API REST pubblica", partner_api: "API partner", on_request: "Documentazione su richiesta", direct_channel: "Canale diretto SdI", none: "Nessuna API", internal: "Interno",
};
const CAP_LABEL: Record<string, string> = {
  outgoing_invoices: "Fatture attive", incoming_invoices: "Fatture passive", credit_notes: "Note di credito", sdi_status: "Stato SdI",
  receipt_download: "Ricevute", xml_download: "XML", webhooks: "Webhook", status_polling: "Polling", sandbox: "Ambiente di test",
  multi_company: "Multi-azienda", provider_side_archive: "Conservazione",
};

function IntegrationsCard() {
  const q = useQuery({ queryKey: ["provider-catalog"], queryFn: () => api.get<{ providers: CatalogEntry[] }>("/billing/providers/catalog"), retry: false });
  const health = useQuery({ queryKey: ["billing-provider"], queryFn: () => api.get<{ provider_key?: string; status?: string; api_version?: string }>("/billing/provider"), retry: false });
  if (q.isLoading) return <Skeleton rows={6} />;
  if (q.error) return <Callout tone="neutral" title="Integrazioni non visibili">Il catalogo integrazioni richiede il permesso di lettura sulla fatturazione.</Callout>;
  const providers = q.data?.providers ?? [];
  const active = providers.filter((p) => p.status === "supported_in_prosperya");
  return (
    <div className="stack">
      <Callout tone="info" title="Due cose diverse: «il provider esiste» e «Prosperya ha un connettore»">
        Ogni fornitore esterno resta sostituibile: la fatturazione elettronica parla con un'interfaccia neutra e gli adapter si aggiungono senza toccare il dominio.
        {health.data?.provider_key && <> Connettore attivo: <strong>{health.data.provider_key}</strong> · <Dot tone={health.data.status === "healthy" ? "success" : "warning"}>{health.data.status === "healthy" ? "operativo" : health.data.status}</Dot></>}
      </Callout>
      <Section title={<><Plug size={13} /> Fatturazione elettronica <span className="tab__count">{providers.length}</span></>}
               footer={<>{active.length} connettori attivi · {providers.length - active.length} provider analizzati. Date di verifica dichiarate su ogni scheda.</>}>
        <div className="rows">
          {providers.map((p) => {
            const s = SUPPORT_LABEL[p.status] ?? SUPPORT_LABEL.unknown;
            const caps = Object.entries(p.capabilities).filter(([, v]) => v === true).map(([k]) => CAP_LABEL[k] ?? k);
            return (
              <Row key={p.key} leading={<Plug size={16} />} tone={p.status === "supported_in_prosperya" ? "success" : undefined}
                   title={<>{p.name} <span className="muted text-xs">· {p.vendor}</span></>}
                   sub={<>
                     <span>{KIND_LABEL[p.integration_kind] ?? p.integration_kind}{p.api_version ? ` · ${p.api_version}` : ""} · verificato {p.last_verified}</span>
                     {caps.length > 0 && <div className="cluster mt-1">{caps.map((c) => <Badge key={c} tone="neutral" dot={false}>{c}</Badge>)}</div>}
                     <details className="mt-1"><summary className="text-2xs">Prerequisiti e limiti</summary>
                       <div className="text-xs mt-1"><strong>Prerequisiti:</strong> {p.commercial_prerequisites}</div>
                       <div className="text-xs"><strong>Limiti noti:</strong> {p.known_limitations}</div>
                       {p.documentation_url && <a className="text-xs" href={p.documentation_url} target="_blank" rel="noreferrer">Documentazione ufficiale ↗</a>}
                     </details>
                   </>}
                   trailing={<Badge tone={s.tone} title={p.status}>{s.label}</Badge>} />
            );
          })}
        </div>
      </Section>
      <Section title="Altre integrazioni">
        <div className="rows">
          <Row leading={<Plug size={16} />} title="Calendario" sub="Scadenze e appuntamenti verso calendari esterni" trailing={<Badge tone="neutral">Pianificato</Badge>} />
          <Row leading={<Plug size={16} />} title="Email" sub="Invio comunicazioni e richieste documentali" trailing={<Badge tone="neutral">Pianificato</Badge>} />
          <Row leading={<Plug size={16} />} title="AI CFO" sub="Assistente su fonti interne, con limiti dichiarati" trailing={<Badge tone="success">Attivo</Badge>} />
        </div>
      </Section>
    </div>
  );
}
