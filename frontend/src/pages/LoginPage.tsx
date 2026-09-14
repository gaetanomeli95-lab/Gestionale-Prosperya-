import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner } from "../components/ui";

function LoginMark() {
  const nodes = ["#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A",
                 "#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A"];
  return (
    <svg width="72" height="72" viewBox="0 0 512 512" aria-hidden="true">
      <rect width="512" height="512" rx="112" fill="#0b1416" fillOpacity="0.55" />
      <g opacity="0.95">
        {nodes.map((c, i) => {
          const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
          return <circle key={i} cx={256 + Math.cos(a) * 165} cy={256 + Math.sin(a) * 165} r="52" fill={c} />;
        })}
      </g>
      <circle cx="256" cy="256" r="92" fill="#0b1416" stroke="#ffffff" strokeOpacity="0.18" strokeWidth="3" />
      <text x="256" y="290" fill="#e9d8a6" fontFamily="Georgia, serif" fontSize="104" fontWeight="700" textAnchor="middle">P</text>
    </svg>
  );
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err : new Error("Accesso non riuscito."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login__hero">
        <div className="login__hero-inner">
          <LoginMark />
          <h1 className="login__hero-title">PROSPERYA</h1>
          <p className="login__hero-sub">Il sistema operativo dell'impresa</p>
          <ul className="login__hero-list">
            <li>CRM e pipeline commerciale</li>
            <li>Fatturazione elettronica e SDI</li>
            <li>Controllo di gestione e finanza agevolata</li>
          </ul>
        </div>
      </div>
      <div className="login__panel">
        <form className="login__card" onSubmit={submit}>
          <div className="login__brand">
            <h2>Benvenuto</h2>
            <p>Accedi al tuo workspace</p>
          </div>
          {error ? <ErrorBanner error={error} /> : null}
          <div className="field">
            <label className="field__label" htmlFor="email">Email</label>
            <input id="email" className="input" type="email" required autoComplete="username"
                   value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="password">Password</label>
            <input id="password" className="input" type="password" required autoComplete="current-password"
                   value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <button className="btn btn--primary" style={{ width: "100%", justifyContent: "center", padding: "10px 14px" }} disabled={busy}>
            {busy ? "Accesso…" : "Accedi"}
          </button>
        </form>
      </div>
    </div>
  );
}
