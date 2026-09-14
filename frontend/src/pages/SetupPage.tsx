import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner } from "../components/ui";

/** First-run wizard shown when the database has no users yet. */
export default function SetupPage() {
  const { adopt } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    company_name: "", vat_number: "", admin_name: "", admin_email: "", admin_password: "", confirm: "",
  });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.admin_password !== form.confirm) {
      setError(new Error("Le due password non coincidono."));
      return;
    }
    setBusy(true);
    try {
      const res = await api.post<{ access_token: string; user: User }>("/setup", {
        company_name: form.company_name.trim(),
        vat_number: form.vat_number.trim() || null,
        admin_name: form.admin_name.trim(),
        admin_email: form.admin_email.trim(),
        admin_password: form.admin_password,
      });
      adopt(res.access_token, res.user);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err : new Error("Configurazione non riuscita."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login__hero">
        <div className="login__hero-inner">
          <h1 className="login__hero-title">Benvenuto</h1>
          <p className="login__hero-sub">Configuriamo la tua azienda in un minuto</p>
          <ul className="login__hero-list">
            <li>I dati restano sul tuo computer</li>
            <li>Potrai aggiungere colleghi da Impostazioni</li>
            <li>Pipeline e linee di servizio già pronte, personalizzabili</li>
          </ul>
        </div>
      </div>
      <div className="login__panel">
        <form className="login__card" style={{ width: 440 }} onSubmit={submit}>
          <div className="login__brand">
            <h2>Primo avvio</h2>
            <p>Crea la tua azienda e l'utente amministratore</p>
          </div>
          {error ? <ErrorBanner error={error} /> : null}
          <div className="field">
            <label className="field__label">Nome azienda *</label>
            <input className="input" required value={form.company_name} onChange={set("company_name")} placeholder="Es. Rossi S.r.l." />
          </div>
          <div className="field">
            <label className="field__label">Partita IVA</label>
            <input className="input" value={form.vat_number} onChange={set("vat_number")} placeholder="Facoltativa" />
          </div>
          <hr style={{ border: 0, borderTop: "1px solid var(--pys-border)", margin: "16px 0" }} />
          <div className="field">
            <label className="field__label">Il tuo nome *</label>
            <input className="input" required value={form.admin_name} onChange={set("admin_name")} />
          </div>
          <div className="field">
            <label className="field__label">Email (sarà il tuo login) *</label>
            <input className="input" type="email" required autoComplete="username" value={form.admin_email} onChange={set("admin_email")} />
          </div>
          <div className="form-grid">
            <div className="field">
              <label className="field__label">Password * (min. 10 caratteri)</label>
              <input className="input" type="password" required minLength={10} autoComplete="new-password" value={form.admin_password} onChange={set("admin_password")} />
            </div>
            <div className="field">
              <label className="field__label">Conferma password *</label>
              <input className="input" type="password" required minLength={10} autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
            </div>
          </div>
          <button className="btn btn--primary" style={{ width: "100%", justifyContent: "center", padding: "10px 14px" }} disabled={busy}>
            {busy ? "Configurazione…" : "Crea e accedi"}
          </button>
        </form>
      </div>
    </div>
  );
}
