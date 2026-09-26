import { useState } from "react";
import { FlaskConical, Play } from "lucide-react";
import type {
  ControllingAlert, ControllingSnapshot, DebtFacility, DebtLine,
  ScenarioPresets, ScenarioResult,
} from "../../api/types";
import {
  Badge, Callout, EmptyState, Field, KV, Modal, Section, Skeleton, Tile,
} from "../../components/ui";
import { money } from "../../lib/format";
import { MetricBadge, Reasons, RUNWAY_LABEL, Val } from "./shared";

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
const ASSUMPTION_LABEL: Record<string, string> = Object.fromEntries(SCENARIO_FIELDS.map((f) => [f.key, f.label]));

const SCENARIO_LABEL: Record<string, string> = { BASE: "Base", STRESS: "Stress", UPSIDE: "Ottimistico" };
const scenarioName = (label: string) => SCENARIO_LABEL[label] ?? label;

function Delta({ base, value, invert }: { base: string | null; value: string | null; invert?: boolean }) {
  if (base == null || value == null) return <span className="muted">—</span>;
  const d = Number(value) - Number(base);
  if (Math.abs(d) < 0.005) return <span className="muted">=</span>;
  const worse = invert ? d > 0 : d < 0;
  return (
    <span className={`num ${worse ? "neg" : "pos"}`}>
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
    <table className="table table--flush table--static">
      <thead>
        <tr>
          <th>Indicatore</th>
          <th className="th--num">{scenarioName(base.label)}</th>
          {others.map((s) => (
            <th key={s.label} className="th--num">
              {scenarioName(s.label)}
              <div className="table__sub">Δ vs {scenarioName(base.label)}</div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <td className="table__primary">{r.label}</td>
            <td className="td--num"><Val v={r.get(base)} suffix={r.suffix} /></td>
            {others.map((s) => (
              <td key={s.label} className="td--num">
                <Val v={r.get(s)} suffix={r.suffix} />
                <div className="table__sub"><Delta base={r.get(base)} value={r.get(s)} invert={r.invert} /></div>
              </td>
            ))}
          </tr>
        ))}
        <tr>
          <td className="table__primary">Prima data negativa</td>
          <td className="td--num">{base.continuity.first_negative_date ?? <span className="muted">mai</span>}</td>
          {others.map((s) => (
            <td key={s.label} className="td--num">
              {s.continuity.first_negative_date
                ? <span className="neg">{s.continuity.first_negative_date}</span>
                : <span className="muted">mai</span>}
            </td>
          ))}
        </tr>
        <tr>
          <td className="table__primary">Autonomia di cassa</td>
          <td className="td--num">{RUNWAY_LABEL[base.continuity.runway_status] ?? base.continuity.runway_status}</td>
          {others.map((s) => (
            <td key={s.label} className="td--num">{RUNWAY_LABEL[s.continuity.runway_status] ?? s.continuity.runway_status}</td>
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
  const ranCount = Object.keys(results).length;

  return (
    <div className="stack">
      <Callout tone="info" title="Ricalcolo deterministico su copie dei dati">
        Ogni scenario trasforma le fonti datate con ipotesi esplicite e riesegue gli stessi motori.
        I consuntivi storici non vengono mai modificati.
      </Callout>

      <div className="grid-1-2">
        <Section
          title="Preset"
          footer={<>Esegui i tre preset per ottenere il confronto con i delta rispetto allo scenario Base. Formula <span className="mono">{presets?.formula_version ?? "scenario-v1.0"}</span>.</>}
        >
          {!presets ? <Skeleton rows={3} /> : (
            <div className="stack stack--sm">
              {presetList.map(([key, p]) => {
                const done = !!results[p.label];
                return (
                  <button key={key} className={`btn ${done ? "btn--ghost" : "btn--primary"} w-full`}
                          disabled={!canWrite || running}
                          onClick={() => onRun({ label: p.label, ...p.assumptions })}>
                    <Play size={12} /> {scenarioName(p.label)}
                    <span className="muted text-2xs">
                      ricavi {p.assumptions.revenue_change_pct}% · incassi +{p.assumptions.collection_delay_days}g
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Section>

        <Section title="Scenario personalizzato">
          <div className="form-grid">
            {SCENARIO_FIELDS.map((f) => (
              <Field key={f.key} htmlFor={`sc-${f.key}`} label={f.label}
                     hint={presets?.bounds[f.key] ? `Intervallo ammesso ${presets.bounds[f.key][0]} … ${presets.bounds[f.key][1]}` : undefined}>
                <input id={`sc-${f.key}`} className="input input--num" value={form[f.key]} placeholder={f.hint}
                       onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
              </Field>
            ))}
          </div>
          <div className="cluster cluster--end mt-2">
            <button className="btn btn--ghost" disabled={!canWrite || running}
                    onClick={() => onRun({ ...form, label: form.label || "CUSTOM" })}>
              <FlaskConical size={14} /> {running ? "Ricalcolo…" : "Esegui scenario"}
            </button>
          </div>
        </Section>
      </div>

      {!result && ranCount === 0 && (
        <Section>
          <EmptyState title="Nessuno scenario eseguito" icon={<FlaskConical size={20} strokeWidth={1.8} />}>
            Scegli un preset o imposta ipotesi personalizzate: il risultato compare qui con DSCR,
            cassa minima, margine e break-even ricalcolati.
          </EmptyState>
        </Section>
      )}

      {result && (
        <Section
          title={<>Risultato · {scenarioName(result.label)}</>}
          actions={<Badge tone="info" dot={false}>{result.formula_version}</Badge>}
          footer={result.note}
        >
          <div className="grid-auto grid-auto--sm">
            <Tile label="DSCR"
                  tone={result.dscr.value != null && Number(result.dscr.value) < 1 ? "danger" : undefined}
                  value={result.dscr.value != null ? <span className="num">{result.dscr.value}</span> : <MetricBadge status={result.dscr.status} />} />
            <Tile label="Cassa minima"
                  tone={result.continuity.minimum_projected_balance != null && Number(result.continuity.minimum_projected_balance) < 0 ? "danger" : undefined}
                  value={<Val v={result.continuity.minimum_projected_balance} />}
                  hint={result.continuity.first_negative_date ? `negativa dal ${result.continuity.first_negative_date}` : RUNWAY_LABEL[result.continuity.runway_status]} />
            <Tile label="Margine di contribuzione" value={<Val v={result.profitability.contribution_margin} />}
                  hint={result.profitability.contribution_margin_percent ? `${result.profitability.contribution_margin_percent}% dei ricavi` : undefined} />
            <Tile label="Break-even" value={<Val v={result.profitability.break_even_revenue} />}
                  hint={result.profitability.margin_of_safety_percent ? `margine di sicurezza ${result.profitability.margin_of_safety_percent}%` : undefined} />
          </div>
          <details className="mt-3">
            <summary className="eyebrow eyebrow--muted">Ipotesi applicate</summary>
            <div className="mt-3">
              <KV columns={3} items={Object.entries(result.assumptions).map(([k, v]) => ({
                k: ASSUMPTION_LABEL[k] ?? k, v: <span className="num">{String(v)}</span>,
              }))} />
            </div>
          </details>
        </Section>
      )}

      {base && others.length > 0 && (
        <Section title="Confronto scenari" actions={<span className="muted text-xs">Δ rispetto allo scenario Base</span>} flush>
          <ScenarioKpiTable base={base} others={custom ? [...others, custom] : others} />
        </Section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data quality
// ---------------------------------------------------------------------------

export function QualityTab({ snap }: { snap: ControllingSnapshot }) {
  const cont = snap.continuity;
  return (
    <div className="stack">
      <div className="grid-1-2">
        <Section title="Stato dei dati di input">
          <KV columns={1} items={[
            { k: "Saldo iniziale (cassa)", v: <span className="cluster"><Val v={snap.opening_balance} /><MetricBadge status={snap.opening_balance_status} /></span> },
            { k: "DSCR", v: <MetricBadge status={snap.dscr.status} /> },
            { k: "Autonomia di cassa", v: <MetricBadge status={cont.runway_status} /> },
            { k: "Copertura continuità", v: <span className="num">{cont.coverage.months_with_data}/{cont.coverage.months_total} mesi</span> },
            { k: "Partite aperte", v: <span className="num">{snap.counters.open_items}</span> },
            { k: "Rate pianificate", v: <span className="num">{snap.counters.debt_lines_scheduled}</span> },
          ]} />
        </Section>

        <Section title="Stato delle regole early-warning" flush>
          <table className="table table--flush table--static table--dense">
            <thead><tr><th>Regola</th><th>Stato</th><th>Motivo</th></tr></thead>
            <tbody>
              {snap.evaluations.map((e) => (
                <tr key={e.rule_code}>
                  <td>
                    <div className="table__primary">{e.title ?? e.rule_code}</div>
                    <div className="table__sub mono">{e.rule_code}</div>
                  </td>
                  <td><MetricBadge status={e.state === "fired" ? "available" : e.state} /></td>
                  <td className="text-xs">{e.reason ?? e.message ?? <span className="muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>

      {cont.issues.length > 0 && (
        <Callout tone="warning" title={`Problemi rilevati (${cont.issues.length})`}>
          <Reasons items={cont.issues} />
        </Callout>
      )}

      <details>
        <summary className="eyebrow eyebrow--muted">Limitazioni dichiarate ({snap.limitations.length})</summary>
        <div className="mt-3"><Section tone="section"><Reasons items={snap.limitations} /></Section></div>
      </details>
    </div>
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
    <Modal
      size="sm"
      title={action === "resolve" ? "Risolvi segnale" : "Archivia segnale"}
      subtitle={alert.title}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
          <button className={`btn ${action === "dismiss" ? "btn--danger" : "btn--primary"}`}
                  disabled={pending || (required && note.trim().length < 5)}
                  onClick={() => onSubmit(note)}>
            {pending ? "Salvataggio…" : action === "resolve" ? "Risolvi" : "Archivia"}
          </button>
        </>
      }
    >
      {action === "dismiss" && (
        <Callout tone="warning">
          Archiviare un segnale non lo elimina: resta tracciato con la tua motivazione e può
          riaprirsi alla prossima rivalutazione se la condizione persiste.
        </Callout>
      )}
      <div className="mt-3">
        <Field htmlFor="tr-note" label="Motivazione"
               hint={required ? "Obbligatoria, almeno 5 caratteri." : "Facoltativa."}>
          <textarea id="tr-note" className="textarea" rows={3} value={note}
                    onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
      <div className="muted mono text-2xs">{alert.rule_code} v{alert.rule_version}</div>
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
    <Modal
      title="Nuova linea di debito"
      subtitle="Mutui, leasing e affidamenti alimentano il DSCR e la continuità 12 mesi."
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
          <button className="btn btn--primary" disabled={pending || !f.name.trim()}
                  onClick={() => onSubmit({ ...f, lender_name: f.lender_name || null,
                                            outstanding_principal: f.outstanding_principal || null,
                                            notes: f.notes || null })}>
            {pending ? "Salvataggio…" : "Crea linea"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field htmlFor="fac-name" label="Nome">
          <input id="fac-name" className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field htmlFor="fac-type" label="Tipo">
          <select id="fac-type" className="select" value={f.facility_type} onChange={(e) => setF({ ...f, facility_type: e.target.value })}>
            <option value="mortgage">Mutuo</option><option value="leasing">Leasing</option>
            <option value="credit_line">Affidamento</option><option value="loan">Finanziamento</option>
            <option value="other">Altro</option>
          </select>
        </Field>
        <Field htmlFor="fac-lender" label="Finanziatore">
          <input id="fac-lender" className="input" value={f.lender_name} onChange={(e) => setF({ ...f, lender_name: e.target.value })} />
        </Field>
        <Field htmlFor="fac-principal" label="Residuo capitale €">
          <input id="fac-principal" className="input input--num" value={f.outstanding_principal} onChange={(e) => setF({ ...f, outstanding_principal: e.target.value })} />
        </Field>
        <Field htmlFor="fac-notes" label="Note" span2>
          <textarea id="fac-notes" className="textarea" rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        </Field>
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
    <Modal
      size="sm"
      title="Aggiungi rata"
      subtitle={facility.name}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
          <button className="btn btn--primary" disabled={pending || !f.instalment_no || !f.due_date}
                  onClick={() => onSubmit({ instalment_no: Number(f.instalment_no), due_date: f.due_date,
                                            principal: f.principal, interest: f.interest })}>
            {pending ? "Salvataggio…" : "Aggiungi rata"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field htmlFor="inst-no" label="N. rata">
          <input id="inst-no" className="input input--num" value={f.instalment_no} onChange={(e) => setF({ ...f, instalment_no: e.target.value })} />
        </Field>
        <Field htmlFor="inst-due" label="Scadenza">
          <input id="inst-due" className="input" type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} />
        </Field>
        <Field htmlFor="inst-principal" label="Capitale €">
          <input id="inst-principal" className="input input--num" value={f.principal} onChange={(e) => setF({ ...f, principal: e.target.value })} />
        </Field>
        <Field htmlFor="inst-interest" label="Interessi €">
          <input id="inst-interest" className="input input--num" value={f.interest} onChange={(e) => setF({ ...f, interest: e.target.value })} />
        </Field>
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
    <Modal
      size="sm"
      title={`Regola rata ${line.instalment_no}`}
      subtitle={<>Scadenza {line.due_date} · importo <Val v={line.service} /></>}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
          <button className="btn btn--primary"
                  disabled={pending || (action === "waived" && note.trim().length < 5)}
                  onClick={() => onSubmit({ action, settled_on: settledOn || undefined, note: note || undefined })}>
            {pending ? "Salvataggio…" : "Conferma"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field htmlFor="settle-action" label="Esito">
          <select id="settle-action" className="select" value={action} onChange={(e) => setAction(e.target.value as "paid" | "waived")}>
            <option value="paid">Pagata</option><option value="waived">Sospesa / rinunciata</option>
          </select>
        </Field>
        {action === "paid" && (
          <Field htmlFor="settle-date" label="Data regolazione">
            <input id="settle-date" className="input" type="date" value={settledOn} onChange={(e) => setSettledOn(e.target.value)} />
          </Field>
        )}
        <Field htmlFor="settle-note" label="Nota" span2
               hint={action === "waived" ? "Obbligatoria, almeno 5 caratteri." : "Facoltativa."}>
          <textarea id="settle-note" className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
