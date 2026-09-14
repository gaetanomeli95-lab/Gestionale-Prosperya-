import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, UserPlus } from "lucide-react";
import { api } from "../api/client";
import type { Page, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, ErrorBanner, Modal, Spinner } from "../components/ui";

const STAFF = ["admin", "management", "consultant", "backoffice", "readonly"];
const ROLE_LABEL: Record<string, string> = {
  admin: "Amministratore", management: "Direzione", consultant: "Consulente",
  backoffice: "Back office", readonly: "Sola lettura",
  client_admin: "Amministratore", client_operator: "Operatore", client_readonly: "Sola lettura",
};

export default function SettingsPage() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "client_admin";
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Impostazioni</h1>
          <div className="page-head__meta">Utenti, accessi e sicurezza del tuo account</div>
        </div>
      </div>
      <div className="grid-2">
        <PasswordCard />
        {canManage && <UsersCard me={user!} />}
      </div>
    </>
  );
}

function PasswordCard() {
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const [done, setDone] = useState(false);
  const m = useMutation({
    mutationFn: () => api.post("/auth/change-password", { current_password: f.current, new_password: f.next }),
    onSuccess: () => { setDone(true); setF({ current: "", next: "", confirm: "" }); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setDone(false);
    if (f.next !== f.confirm) return;
    m.mutate();
  };
  return (
    <Card className="card__pad">
      <div className="card__title"><KeyRound size={13} style={{ verticalAlign: -2, marginRight: 6 }} />Cambia password</div>
      {m.error ? <ErrorBanner error={m.error} /> : null}
      {done && <div className="alert alert--info">Password aggiornata.</div>}
      {f.confirm && f.next !== f.confirm && <div className="alert alert--warning">Le password non coincidono.</div>}
      <form onSubmit={submit}>
        <div className="field"><label className="field__label">Password attuale</label>
          <input className="input" type="password" required autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></div>
        <div className="field"><label className="field__label">Nuova password (min. 10)</label>
          <input className="input" type="password" required minLength={10} autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} /></div>
        <div className="field"><label className="field__label">Conferma</label>
          <input className="input" type="password" required minLength={10} autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} /></div>
        <button className="btn btn--primary" disabled={m.isPending}>Aggiorna</button>
      </form>
    </Card>
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
    onSuccess: () => { setOpen(false); setF({ ...f, full_name: "", email: "", password: "" }); qc.invalidateQueries({ queryKey: ["users"] }); },
  });
  const toggle = useMutation({
    mutationFn: (u: User) => api.patch(`/users/${u.id}`, { is_active: !u.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <Card className="card__pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div className="card__title" style={{ margin: 0 }}>Utenti</div>
        <button className="btn btn--primary btn--sm" onClick={() => setOpen(true)}><UserPlus size={13} /> Nuovo utente</button>
      </div>
      {users.isLoading ? <Spinner /> : users.error ? <ErrorBanner error={users.error} /> : (
        <table className="table">
          <thead><tr><th>Nome</th><th>Email</th><th>Ruolo</th><th>Stato</th><th></th></tr></thead>
          <tbody>
            {users.data?.items.map((u) => (
              <tr key={u.id} style={{ cursor: "default" }}>
                <td>{u.full_name}{u.id === me.id && <span className="muted"> (tu)</span>}</td>
                <td className="muted">{u.email}</td>
                <td>{ROLE_LABEL[u.role] ?? u.role}</td>
                <td><Badge tone={u.is_active ? "success" : "neutral"}>{u.is_active ? "attivo" : "disattivato"}</Badge></td>
                <td style={{ textAlign: "right" }}>
                  {u.id !== me.id && (
                    <button className="btn btn--ghost btn--sm" disabled={toggle.isPending} onClick={() => toggle.mutate(u)}>
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
        <Modal title="Nuovo utente" onClose={() => setOpen(false)}
          footer={<>
            <button className="btn btn--ghost" onClick={() => setOpen(false)}>Annulla</button>
            <button className="btn btn--primary" disabled={create.isPending || !f.full_name || !f.email || f.password.length < 10} onClick={() => create.mutate()}>Crea</button>
          </>}>
          {create.error ? <ErrorBanner error={create.error} /> : null}
          <div className="field"><label className="field__label">Nome completo</label>
            <input className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
          <div className="field"><label className="field__label">Email</label>
            <input className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div className="field"><label className="field__label">Password iniziale (min. 10)</label>
            <input className="input" type="text" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
          <div className="field"><label className="field__label">Ruolo</label>
            <select className="select" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select></div>
          <div className="muted" style={{ fontSize: "0.75rem" }}>Comunica la password iniziale all'utente: potrà cambiarla da Impostazioni.</div>
        </Modal>
      )}
    </Card>
  );
}
