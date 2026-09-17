import { useState } from "react";
import { FlaskConical } from "lucide-react";
import type {
  ControllingAlert, DebtFacility, DebtLine,
  ScenarioPresets, ScenarioResult,
} from "../../api/types";
import { Badge, Card, Modal, Spinner } from "../../components/ui";
import { money } from "../../lib/format";
import { MetricBadge, Val } from "./shared";

// ---------------------------------------------------------------------------
// Scenari — deterministic recompute on transformed copies, BASE vs others
// ---------------------------------------------------------------------------

const SCENARIO_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: "revenue_change_pct", label: "Variazione ricavi %", hint: "es. -20" },
  { key: "collection_delay_days", label: "Ritardo incassi (giorni)", hint: "es. 30" },
  { key: "supplier_delay_days", label: "Slittamento fornitori (giorni)", hint: "es. -15" },
  { key: "fixed_cost_monthly_delta", label: "Delta costi fissi €/mese", hint: "es. 500" },
  { key: "variable_cost_change_pct", label: "Variazione costi variabili %", hint: "es. 10" },
  { key: "debt_service_change_pct", label: "Variazione servizio debito %", hint: "es. 0" },
];

function Delta({ base, value, invert }: { base: string | null; value: string | null; invert?: boolean }) {
  if (base == null || value == null) return <span className="muted">—</span>;
  const d = Number(value) - Number(base);
  if (Math.abs(d) < 0.005) return <span className="muted">=</span>;
  const worse = invert ? d > 0 : d < 0;
  return (
    <span className={worse ? "tre-neg" : "tre-pos"}>
      {d > 0 ? "+" : ""}{money(d.toFixed(2))}
    </span>
  );
}

function ScenarioKpiTable({ base, others }: { base: ScenarioResult; others: ScenarioResult[] }) {
  const rows: { label: string; get: (s: ScenarioResult) => string | null; invert?: boolean; suffix?: string }[] = [
    { label: "DSCR", get: (s) => s.dscr.value },
    { label: "Cassa minima proiettata", get: (s) => s.continuity.minimum_projected_balance },
    { label: "Margine di contribuzione", get: (s) => s.profitability.contribution_margin },
    { label: "Break-even ricavi", get: (s) => s.profitability.break_even_revenue, invert: true },
    { label: "Margine di sicurezza %", get: (s) => s.profitability.margin_of_safety_percent, suffix: "%" },
  ];
  return (
    <table className="table">
      <thead>
        <tr>
          <th>KPI</th>
          <th style={{ textAlign: "right" }}>{base.label}</th>
          {others.map((s) => (
            <th key={s.label} style={{ textAlign: "right" }}>
              {s.label}
              <div className="muted" style={{ fontWeight: 400, fontSize: "0.65rem" }}>Δ vs {base.label}</div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} style={{ cursor: "default" }}>
            <td>{r.label}</td>
            <td className="mono" style={{ textAlign: "right" }}>
              <Val v={r.get(base)} suffix={r.suffix} />
            </td>
            {others.map((s) => (
              <td key={s.label} className="mono" style={{ textAlign: "right" }}>
                <Val v={r.get(s)} suffix={r.suffix} />
                <div style={{ fontSize: "0.7rem" }}>
                  <Delta base={r.get(base)} value={r.get(s)} invert={r.invert} />
                </div>
              </td>
            ))}
          </tr>
        ))}
        <tr style={{ cursor: "default" }}>
          <td>Prima data negativa</td>
          <td className="mono" style={{ textAlign: "right" }}>{base.continuity.first_negative_date ?? "mai"}</td>
          {others.map((s) => (
            <td key={s.label} className="mono" style={{ textAlign: "right" }}>
              {s.continuity.first_negative_date ?? "mai"}
            </td>
          ))}
        </tr>
        <tr style={{ cursor: "default" }}>
          <td>Runway</td>
          <td className="mono" style={{ textAlign: "right" }}>{base.continuity.runway_status}</td>
          {others.map((s) => (
            <td key={s.label} className="mono" style={{ textAlign: "right" }}>{s.continuity.runway_status}</td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

export function ScenariosTab({ presets, canWrite, form, setForm, result, results, running, onRun }: {
  presets: ScenarioPresets | undefined;
  canWrite: boolean;
  form: Record<string, string>;
  setForm: (f: Record<string, string>) => void;
  result: ScenarioResult | null;
  results: Record<string, ScenarioResult>;
  running: boolean;
  onRun: (payload: Record<string, unknown>) => void;
}) {
  const presetList = presets ? Object.entries(presets.presets) : [];

  const base = results["BASE"] ?? null;
  const others = ["STRESS", "UPSIDE"]
    .map((k) => results[k])
    .filter(Boolean) as ScenarioResult[];
  const custom = Object.values(results).find(
    (r) => !["BASE", "STRESS", "UPSIDE"].includes(r.label)) ?? null;

  return (
    <>
      <div className="ai-banner" style={{ marginBottom: 16 }}>
        <FlaskConical size={18} />
        <div>
          <strong>Ricalcolo deterministico su copie dei dati</strong>
          <div>
            Ogni scenario trasforma le fonti datate con ipotesi esplicite e riesegue gli stessi
            motori. I consuntivi storici non vengono mai modificati. Formula{" "}
            <span className="mono">{presets?.formula_version ?? "scenario-v1.0"}</span>.
          </div>
        </div>
      </div>

      <Card className="card__pad">
        <div className="card__title">Preset</div>
        {!presets ? <Spinner /> : (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {presetList.map(([key, p]) => (
              <button key={key} className="btn btn--ghost" disabled={!canWrite || running}
                      onClick={() => onRun({ label: p.label, ...p.assumptions })}>
                {p.label}
                <span className="muted" style={{ fontSize: "0.68rem", marginLeft: 6 }}>
                  ricavi {p.assumptions.revenue_change_pct}% · incassi {p.assumptions.collection_delay_days}g
                </span>
              </button>
            ))}
          </div>
        )}
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
          Esegui tutti e tre i preset per vedere la tabella comparativa con i delta rispetto al BASE.
        </div>
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Scenario personalizzato</div>
        <div className="form-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
          {SCENARIO_FIELDS.map((f) => (
            <label key={f.key} className="field">
              <span className="field__label">{f.label}</span>
              <input className="input" value={form[f.key]} placeholder={f.hint}
                     onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
              {presets?.bounds[f.key] && (
                <span className="muted" style={{ fontSize: "0.65rem" }}>
                  intervallo {presets.bounds[f.key][0]}..{presets.bounds[f.key][1]}
                </span>
              )}
            </label>
          ))}
        </div>
        <div style={{ marginTop: 10 }}>
          <button className="btn btn--primary" disabled={!canWrite || running}
                  onClick={() => onRun({ ...form, label: form.label || "CUSTOM" })}>
            {running ? "Ricalcolo…" : "Esegui scenario"}
          </button>
        </div>
      </Card>

      {result && (
        <Card className="card__pad" style={{ marginTop: 16 }}>
          <div className="card__title">
            Risultato {result.label} <Badge tone="info">{result.formula_version}</Badge>
          </div>
          <div className="kpi-grid">
            <div>
              <div className="kpi__label">DSCR</div>
              <div className="kpi__value mono">{result.dscr.value ?? result.dscr.status}</div>
            </div>
            <div>
              <div className="kpi__label">Cassa minima</div>
              <div className="kpi__value mono"><Val v={result.continuity.minimum_projected_balance} /></div>
            </div>
            <div>
              <div className="kpi__label">Margine contribuzione</div>
              <div className="kpi__value mono"><Val v={result.profitability.contribution_margin} /></div>
            </div>
            <div>
              <div className="kpi__label">Break-even</div>
              <div className="kpi__value mono"><Val v={result.profitability.break_even_revenue} /></div>
            </div>
          </div>
          <div className="muted" style={{ fontSize: "0.75rem", marginTop: 8 }}>{result.note}</div>
          <details style={{ marginTop: 8 }}>
            <summary className="muted" style={{ cursor: "pointer", fontSize: "0.75rem" }}>Ipotesi applicate</summary>
            <div className="dl" style={{ marginTop: 6 }}>
              {Object.entries(result.assumptions).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt className="mono" style={{ fontSize: "0.72rem" }}>{k}</dt>
                  <dd className="mono" style={{ fontSize: "0.78rem" }}>{String(v)}</dd>
                </div>
              ))}
            </div>
          </details>
        </Card>
      )}

      {base && others.length > 0 && (
        <Card className="card__pad" style={{ marginTop: 16 }}>
          <div className="card__title">Confronto scenari (Δ vs BASE)</div>
          <ScenarioKpiTable base={base} others={custom ? [...others, custom] : others} />
        </Card>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Data quality
// ---------------------------------------------------------------------------

export function QualityTab({ snap }: { snap: import("../../api/types").ControllingSnapshot }) {
  const cont = snap.continuity;
  return (
    <>
      <Card className="card__pad">
        <div className="card__title">Stato dei dati di input</div>
        <div className="dl">
          <dt>Saldo iniziale (cassa)</dt>
          <dd><MetricBadge status={snap.opening_balance_status} /> <span className="mono"><Val v={snap.opening_balance} /></span></dd>
          <dt>DSCR</dt>
          <dd><MetricBadge status={snap.dscr.status} /></dd>
          <dt>Runway</dt>
          <dd><MetricBadge status={cont.runway_status} /></dd>
          <dt>Copertura continuità</dt>
          <dd className="mono">{cont.coverage.months_with_data}/{cont.coverage.months_total} mesi</dd>
          <dt>Partite aperte</dt><dd className="mono">{snap.counters.open_items}</dd>
          <dt>Rate pianificate</dt><dd className="mono">{snap.counters.debt_lines_scheduled}</dd>
        </div>
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Stato delle regole early-warning</div>
        <table className="table">
          <thead><tr><th>Regola</th><th>Stato</th><th>Motivo</th></tr></thead>
          <tbody>
            {snap.evaluations.map((e) => (
              <tr key={e.rule_code} style={{ cursor: "default" }}>
                <td className="mono" style={{ fontSize: "0.75rem" }}>{e.rule_code}</td>
                <td><MetricBadge status={e.state === "fired" ? "available" : e.state} /></td>
                <td style={{ fontSize: "0.78rem" }}>{e.reason ?? e.message ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {cont.issues.length > 0 && (
        <Card className="card__pad" style={{ marginTop: 16 }}>
          <div className="card__title">Problemi rilevati</div>
          <ul className="mgmt-issues">{cont.issues.map((i) => <li key={i}>{i}</li>)}</ul>
        </Card>
      )}

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Limitazioni dichiarate</div>
        <ul className="mgmt-issues">{snap.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

export function TransitionModal({ alert, action, pending, onClose, onSubmit }: {
  alert: ControllingAlert;
  action: "resolve" | "dismiss";
  pending: boolean;
  onClose: () => void;
  onSubmit: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  const required = action === "dismiss";
  return (
    <Modal title={action === "resolve" ? "Risolvi segnale" : "Ignora segnale"} onClose={onClose}>
      <p style={{ fontSize: "0.82rem" }}>
        <strong>{alert.rule_code}</strong> — {alert.title}
      </p>
      <label className="field">
        <span className="field__label">
          Motivazione {required ? "(obbligatoria, min 5 caratteri)" : "(facoltativa)"}
        </span>
        <textarea className="input" rows={3} value={note}
                  onChange={(e) => setNote(e.target.value)} />
      </label>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
        <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
        <button className="btn btn--primary" disabled={pending || (required && note.trim().length < 5)}
                onClick={() => onSubmit(note)}>
          {pending ? "Salvataggio…" : action === "resolve" ? "Risolvi" : "Ignora"}
        </button>
      </div>
    </Modal>
  );
}

export function FacilityModal({ pending, onClose, onSubmit }: {
  pending: boolean;
  onClose: () => void;
  onSubmit: (p: Record<string, unknown>) => void;
}) {
  const [f, setF] = useState({ name: "", facility_type: "mortgage", lender_name: "", outstanding_principal: "", notes: "" });
  return (
    <Modal title="Nuova linea di debito" onClose={onClose}>
      <div className="form-grid">
        <label className="field"><span className="field__label">Nome</span>
          <input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="field"><span className="field__label">Tipo</span>
          <select className="select" value={f.facility_type} onChange={(e) => setF({ ...f, facility_type: e.target.value })}>
            <option value="mortgage">Mutuo</option><option value="leasing">Leasing</option>
            <option value="credit_line">Affidamento</option><option value="loan">Finanziamento</option>
            <option value="other">Altro</option>
          </select></label>
        <label className="field"><span className="field__label">Finanziatore</span>
          <input className="input" value={f.lender_name} onChange={(e) => setF({ ...f, lender_name: e.target.value })} /></label>
        <label className="field"><span className="field__label">Residuo capitale €</span>
          <input className="input" value={f.outstanding_principal} onChange={(e) => setF({ ...f, outstanding_principal: e.target.value })} /></label>
      </div>
      <label className="field"><span className="field__label">Note</span>
        <textarea className="input" rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
        <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
        <button className="btn btn--primary" disabled={pending || !f.name.trim()}
                onClick={() => onSubmit({ ...f, lender_name: f.lender_name || null,
                                          outstanding_principal: f.outstanding_principal || null,
                                          notes: f.notes || null })}>
          {pending ? "Salvataggio…" : "Crea linea"}
        </button>
      </div>
    </Modal>
  );
}

export function InstalmentModal({ facility, pending, onClose, onSubmit }: {
  facility: DebtFacility;
  pending: boolean;
  onClose: () => void;
  onSubmit: (p: Record<string, unknown>) => void;
}) {
  const [f, setF] = useState({ instalment_no: "", due_date: "", principal: "", interest: "0" });
  return (
    <Modal title={`Aggiungi rata — ${facility.name}`} onClose={onClose}>
      <div className="form-grid">
        <label className="field"><span className="field__label">N. rata</span>
          <input className="input" value={f.instalment_no} onChange={(e) => setF({ ...f, instalment_no: e.target.value })} /></label>
        <label className="field"><span className="field__label">Scadenza</span>
          <input className="input" type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></label>
        <label className="field"><span className="field__label">Capitale €</span>
          <input className="input" value={f.principal} onChange={(e) => setF({ ...f, principal: e.target.value })} /></label>
        <label className="field"><span className="field__label">Interessi €</span>
          <input className="input" value={f.interest} onChange={(e) => setF({ ...f, interest: e.target.value })} /></label>
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
        <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
        <button className="btn btn--primary" disabled={pending || !f.instalment_no || !f.due_date}
                onClick={() => onSubmit({ instalment_no: Number(f.instalment_no), due_date: f.due_date,
                                          principal: f.principal, interest: f.interest })}>
          {pending ? "Salvataggio…" : "Aggiungi rata"}
        </button>
      </div>
    </Modal>
  );
}

export function SettleModal({ line, pending, onClose, onSubmit }: {
  line: DebtLine;
  pending: boolean;
  onClose: () => void;
  onSubmit: (p: { action: string; settled_on?: string; note?: string }) => void;
}) {
  const [action, setAction] = useState<"paid" | "waived">("paid");
  const [settledOn, setSettledOn] = useState("");
  const [note, setNote] = useState("");
  return (
    <Modal title={`Regola rata ${line.instalment_no} del ${line.due_date}`} onClose={onClose}>
      <div className="form-grid">
        <label className="field"><span className="field__label">Esito</span>
          <select className="select" value={action} onChange={(e) => setAction(e.target.value as "paid" | "waived")}>
            <option value="paid">Pagata</option><option value="waived">Sospesa / rinunciata</option>
          </select></label>
        {action === "paid" && (
          <label className="field"><span className="field__label">Data regolazione</span>
            <input className="input" type="date" value={settledOn} onChange={(e) => setSettledOn(e.target.value)} /></label>
        )}
      </div>
      <label className="field"><span className="field__label">
        Nota {action === "waived" ? "(obbligatoria, min 5 caratteri)" : "(facoltativa)"}
      </span>
        <textarea className="input" rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
        <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
        <button className="btn btn--primary"
                disabled={pending || (action === "waived" && note.trim().length < 5)}
                onClick={() => onSubmit({ action, settled_on: settledOn || undefined, note: note || undefined })}>
          {pending ? "Salvataggio…" : "Conferma"}
        </button>
      </div>
    </Modal>
  );
}
