import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ProsperyaMark } from "../components/AppShell";
import { ErrorBanner, Field } from "../components/ui";

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
  const mismatch = !!form.confirm && form.admin_password !== form.confirm;

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
          <ProsperyaMark size={72} />
          <div className="eyebrow login__eyebrow">Primo avvio</div>
          <h1 className="login__hero-title">Benvenuto</h1>
          <p className="login__hero-sub">Configuriamo il tuo workspace in un minuto</p>
          <ul className="login__hero-list">
            <li>I dati restano nel tuo ambiente</li>
            <li>Potrai aggiungere colleghi da Impostazioni</li>
            <li>Pipeline e linee di servizio già pronte, personalizzabili</li>
          </ul>
        </div>
      </div>
      <div className="login__panel">
        <form className="login__card login__card--wide" onSubmit={submit}>
          <div className="login__brand">
            <div className="eyebrow mb-3">Configurazione</div>
            <h2>Crea il tuo workspace</h2>
            <p>La tua organizzazione e l'utente amministratore.</p>
          </div>
          {error ? <ErrorBanner error={error} /> : null}
          <div className="form-section">
            <div className="form-section__title">Organizzazione</div>
            <Field label="Nome azienda *" htmlFor="nome-azienda">
              <input id="nome-azienda" className="input" required value={form.company_name} onChange={set("company_name")} placeholder="Es. Rossi S.r.l." />
            </Field>
            <Field label="Partita IVA" htmlFor="partita-iva" hint="Facoltativa, puoi aggiungerla dopo.">
              <input id="partita-iva" className="input" value={form.vat_number} onChange={set("vat_number")} />
            </Field>
          </div>
          <div className="form-section">
            <div className="form-section__title">Amministratore</div>
            <Field label="Il tuo nome *" htmlFor="il-tuo-nome">
              <input id="il-tuo-nome" className="input" required value={form.admin_name} onChange={set("admin_name")} />
            </Field>
            <Field label="Email (sarà il tuo login) *" htmlFor="email-sara-il-tuo-login">
              <input id="email-sara-il-tuo-login" className="input" type="email" required autoComplete="username" value={form.admin_email} onChange={set("admin_email")} />
            </Field>
            <div className="form-grid">
              <Field label="Password * (min. 10 caratteri)" htmlFor="password-min-10-caratteri">
                <input id="password-min-10-caratteri" className="input" type="password" required minLength={10} autoComplete="new-password" value={form.admin_password} onChange={set("admin_password")} />
              </Field>
              <Field label="Conferma password *" htmlFor="conferma-password" error={mismatch ? "Le password non coincidono." : undefined}>
                <input id="conferma-password" className="input" type="password" required minLength={10} autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
              </Field>
            </div>
          </div>
          <button className="btn btn--primary btn--lg w-full mt-3" disabled={busy || mismatch}>
            {busy ? "Configurazione…" : "Crea e accedi"}
          </button>
        </form>
      </div>
    </div>
  );
}
