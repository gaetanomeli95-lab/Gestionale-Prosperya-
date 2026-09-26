import {
  AlertTriangle, CheckCircle2, Eye, Info, Landmark, Plus, RefreshCw, ShieldAlert, XCircle,
} from "lucide-react";
import type {
  AlertsResponse, ControllingAlert, ControllingSnapshot, DebtFacility,
  DebtLine, DscrResult, EwRulesResponse, FacilitiesResponse,
} from "../../api/types";
import {
  Badge, Callout, Dot, EmptyState, KV, NA, Row, Section, Skeleton, StatusBadge, Tile,
} from "../../components/ui";
import { dateIt } from "../../lib/format";
import {
  KIND_LABEL, MetricBadge, Reasons, SEVERITY_LABEL, SEVERITY_TONE, Val,
} from "./shared";

const EVAL_LABEL: Record<string, string> = {
  fired: "segnale rilevato", not_fired: "non rilevato",
  insufficient_data: "dati insufficienti", unsupported: "non supportato",
};
const EVAL_TONE: Record<string, string> = {
  fired: "danger", not_fired: "success",
  insufficient_data: "warning", unsupported: "neutral",
};
const FACILITY_TYPE_LABEL: Record<string, string> = {
  mortgage: "mutuo", leasing: "leasing", credit_line: "affidamento",
  loan: "finanziamento", other: "altro",
};
const PARAM_KIND_LABEL: Record<string, string> = {
  statutory: "di legge", operational: "operativa",
};
const CATEGORY_LABEL: Record<string, string> = {
  ccii_legal: "CCII", organizational: "organizzativa",
};

const SEVERITY_ICON = { critical: ShieldAlert, warning: AlertTriangle, info: Info };

// ---------------------------------------------------------------------------
// Debito & DSCR
// ---------------------------------------------------------------------------

export function DscrCard({ dscr }: { dscr: DscrResult }) {
  const low = dscr.value != null && Number(dscr.value) < 1;
  return (
    <Section
      title={<>DSCR prospettico · orizzonte {dscr.horizon_days} giorni</>}
      actions={<MetricBadge status={dscr.status} />}
      footer={
        <>
          Formula <span className="mono">{dscr.formula_version}</span> · motore{" "}
          <span className="mono">{dscr.engine_version}</span> · il DSCR è un proxy gestionale,
          non una determinazione legale.
        </>
      }
    >
      <div className="grid-auto grid-auto--sm">
        <Tile label="Valore" tone={low ? "danger" : dscr.value == null ? "muted" : "success"}
              value={dscr.value != null ? <span className="num">{dscr.value}</span> : <NA />}
              hint={low ? "sotto la soglia di copertura 1,0" : dscr.value != null ? "copre il servizio del debito" : undefined} />
        <Tile label="Flusso disponibile (numeratore)" value={<Val v={dscr.numerator} />} hint="proxy CFADS" />
        <Tile label="Servizio del debito (denominatore)" value={<Val v={dscr.denominator} />} />
        <Tile label="Copertura orizzonte"
              value={dscr.coverage_percent ? <span className="num">{dscr.coverage_percent}%</span> : <NA />}
              hint={dscr.covered_until ? `dati fino al ${dateIt(dscr.covered_until)}` : undefined} />
      </div>

      {dscr.components && (
        <div className="mt-4">
          <KV columns={3} items={[
            { k: "Incassi attesi", v: <Val v={dscr.components.expected_inflows} /> },
            { k: "Pagamenti attesi (escl. debito)", v: <Val v={dscr.components.expected_outflows_ex_debt} /> },
            { k: "Rate in scadenza", v: <span className="num">{dscr.components.instalments_due}</span> },
          ]} />
        </div>
      )}

      {dscr.reasons.length > 0 && <div className="mt-3"><Reasons items={dscr.reasons} /></div>}

      <details className="mt-3">
        <summary className="eyebrow eyebrow--muted">
          Formula, ipotesi e fonti ({dscr.source_ids.length} partite, {dscr.debt_line_ids.length} rate)
        </summary>
        <div className="mt-3">
          <KV columns={1} items={Object.entries(dscr.formulas).map(([k, v]) => ({
            k: <span className="mono">{k}</span>, v,
          }))} />
        </div>
        <div className="mt-3"><Reasons items={dscr.assumptions} /></div>
      </details>
    </Section>
  );
}

export function DebtTab({ snap, facilities, canWrite, onNewFacility, onAddInstalment, onSettle }: {
  snap: ControllingSnapshot;
  facilities: FacilitiesResponse | undefined;
  canWrite: boolean;
  onNewFacility: () => void;
  onAddInstalment: (f: DebtFacility) => void;
  onSettle: (l: DebtLine) => void;
}) {
  return (
    <div className="stack">
      <DscrCard dscr={snap.dscr} />
      <Section
        title="Linee di debito e rate"
        actions={canWrite && (
          <button className="btn btn--primary btn--sm" onClick={onNewFacility}>
            <Plus size={13} /> Nuova linea
          </button>
        )}
        footer={facilities && (
          <>
            {facilities.counters.instalments} rate totali: {facilities.counters.scheduled} pianificate,{" "}
            {facilities.counters.paid} pagate, {facilities.counters.waived} sospese. Le rate non sono
            duplicate come partite di tesoreria.
          </>
        )}
      >
        {!facilities ? <Skeleton kind="table" rows={4} /> : facilities.facilities.length === 0 ? (
          <EmptyState
            title="Nessuna linea di debito registrata"
            icon={<Landmark size={20} strokeWidth={1.8} />}
            action={canWrite && (
              <button className="btn btn--primary btn--sm" onClick={onNewFacility}>
                <Plus size={13} /> Registra la prima linea
              </button>
            )}
          >
            Senza mutui, leasing o affidamenti il DSCR non è calcolabile: registra le linee e le
            rate per ottenere la copertura del servizio del debito.
          </EmptyState>
        ) : (
          <div className="stack stack--lg">
            {facilities.facilities.map((f) => <FacilityBlock key={f.id} f={f} asOf={snap.as_of}
                                                             canWrite={canWrite}
                                                             onAddInstalment={onAddInstalment}
                                                             onSettle={onSettle} />)}
          </div>
        )}
      </Section>
    </div>
  );
}

function FacilityBlock({ f, asOf, canWrite, onAddInstalment, onSettle }: {
  f: DebtFacility; asOf: string; canWrite: boolean;
  onAddInstalment: (f: DebtFacility) => void; onSettle: (l: DebtLine) => void;
}) {
  const lines = f.lines ?? [];
  return (
    <div>
      <div className="cluster cluster--between">
        <div className="cluster">
          <span className="strong">{f.name}</span>
          <Badge tone="info" dot={false}>{FACILITY_TYPE_LABEL[f.facility_type] ?? f.facility_type}</Badge>
          {!f.is_active && <Badge tone="neutral">non attiva</Badge>}
        </div>
        <span className="muted text-xs">
          {f.lender_name ?? "finanziatore n.d."} · residuo <Val v={f.outstanding_principal} /> ·{" "}
          {f.scheduled_count ?? 0} rate pianificate (<Val v={f.scheduled_service} />)
        </span>
      </div>
      {lines.length === 0 ? (
        <EmptyState>Nessuna rata pianificata per questa linea.</EmptyState>
      ) : (
        <table className="table table--static table--dense mt-2">
          <thead>
            <tr>
              <th>Rata</th><th>Scadenza</th>
              <th className="th--num">Capitale</th>
              <th className="th--num">Interessi</th>
              <th className="th--num">Rata totale</th>
              <th>Stato</th>
              {canWrite && <th></th>}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const overdue = l.status === "scheduled" && l.due_date < asOf;
              return (
                <tr key={l.id}>
                  <td className="num">{l.instalment_no}</td>
                  <td className={overdue ? "num neg" : "num"} title={overdue ? "Rata scaduta e non regolata" : undefined}>
                    {dateIt(l.due_date)}
                  </td>
                  <td className="td--num"><Val v={l.principal} /></td>
                  <td className="td--num"><Val v={l.interest} /></td>
                  <td className="td--num"><Val v={l.service} /></td>
                  <td>
                    <StatusBadge status={l.status} />
                    {l.status_note && <div className="table__sub">{l.status_note}</div>}
                  </td>
                  {canWrite && (
                    <td className="right">
                      {l.status === "scheduled" && (
                        <button className="btn btn--ghost btn--sm" onClick={() => onSettle(l)}>Regola</button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {canWrite && (
        <div className="mt-2">
          <button className="btn btn--ghost btn--sm" onClick={() => onAddInstalment(f)}>
            <Plus size={12} /> Aggiungi rata
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Early warning
// ---------------------------------------------------------------------------

export function EarlyWarningTab({ snap, alerts, rules, canWrite, evaluating, onEvaluate, onTransition }: {
  snap: ControllingSnapshot;
  alerts: AlertsResponse | undefined;
  rules: EwRulesResponse | undefined;
  canWrite: boolean;
  evaluating: boolean;
  onEvaluate: () => void;
  onTransition: (a: ControllingAlert, action: "acknowledge" | "resolve" | "dismiss") => void;
}) {
  const rows = alerts?.alerts ?? snap.alerts;
  const evaluateBtn = canWrite && (
    <button className="btn btn--primary btn--sm" disabled={evaluating} onClick={onEvaluate}>
      <RefreshCw size={13} /> {evaluating ? "Valutazione…" : "Rivaluta segnali"}
    </button>
  );
  return (
    <div className="stack">
      <Callout tone="warning" title="Segnali da verificare, non verdetti" action={evaluateBtn}>
        Le regole early-warning sono ancorate al D.Lgs. 14/2019 (CCII). Un segnale rilevato indica
        una condizione da verificare: il sistema non determina mai uno stato di crisi. Le soglie
        operative sono parametri di lavoro, non valori di legge.
      </Callout>

      <Section
        title="Alert durevoli"
        footer={alerts && (
          <>
            {alerts.counters.total} alert: {alerts.counters.open} aperti,{" "}
            {alerts.counters.acknowledged} presi in carico, {alerts.counters.resolved} risolti,{" "}
            {alerts.counters.dismissed} archiviati.
          </>
        )}
      >
        {rows.length === 0 ? (
          <EmptyState title="Nessun alert registrato" icon={<ShieldAlert size={20} strokeWidth={1.8} />} action={evaluateBtn}>
            La detection non avviene al caricamento della pagina: rivaluta i segnali per applicare
            le regole attive ai dati di oggi.
          </EmptyState>
        ) : (
          <div className="rows">
            {rows.map((a) => <AlertRow key={a.id} a={a} canWrite={canWrite} onTransition={onTransition} />)}
          </div>
        )}
      </Section>

      <Section title="Valutazione corrente delle regole" actions={<Badge tone="neutral" dot={false}>live, non persistita</Badge>} flush>
        <table className="table table--flush table--static table--dense">
          <thead>
            <tr><th>Regola</th><th>Categoria</th><th>Esito</th><th>Dettaglio</th></tr>
          </thead>
          <tbody>
            {snap.evaluations.map((e) => (
              <tr key={e.rule_code}>
                <td>
                  <div className="table__primary">{e.title ?? e.rule_code}</div>
                  <div className="table__sub mono">{e.rule_code} v{e.rule_version}</div>
                </td>
                <td><Badge tone={e.category === "ccii_legal" ? "accent" : "neutral"} dot={false}>{CATEGORY_LABEL[e.category]}</Badge></td>
                <td><Dot tone={EVAL_TONE[e.state]}>{EVAL_LABEL[e.state]}</Dot></td>
                <td className="text-xs">{e.message ?? e.reason ?? <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {rules && (
        <details>
          <summary className="eyebrow eyebrow--muted">
            Regole attive e riferimenti normativi ({rules.rules.length})
          </summary>
          <div className="mt-3">
            <Section footer={rules.disclaimer}>
              <div className="rows">
                {rules.rules.map((r) => (
                  <Row
                    key={r.id}
                    leading={<Landmark size={16} />}
                    title={
                      <span className="cluster">
                        {r.title}
                        <Badge tone={r.category === "ccii_legal" ? "accent" : "neutral"} dot={false}>{CATEGORY_LABEL[r.category]}</Badge>
                      </span>
                    }
                    sub={
                      <>
                        <div>{r.description}</div>
                        <div className="mt-1">{r.legal_reference} · efficace dal {dateIt(r.effective_from)}</div>
                        <div className="cluster mt-1">
                          {Object.entries(r.params).map(([k, p]) => (
                            <span key={k} className="cluster">
                              <span className="mono">{k} = {String(p.value)}</span>
                              <Badge tone={p.kind === "statutory" ? "primary" : "warning"} dot={false}>{PARAM_KIND_LABEL[p.kind]}</Badge>
                            </span>
                          ))}
                        </div>
                        <div className="mono text-2xs mt-1">{r.code} v{r.version} · {r.formula} · {r.formula_version} · fonte: {r.source_authority}</div>
                      </>
                    }
                  />
                ))}
              </div>
            </Section>
          </div>
        </details>
      )}
    </div>
  );
}

function AlertRow({ a, canWrite, onTransition }: {
  a: ControllingAlert; canWrite: boolean;
  onTransition: (a: ControllingAlert, action: "acknowledge" | "resolve" | "dismiss") => void;
}) {
  const Icon = SEVERITY_ICON[a.severity];
  const active = a.status === "open" || a.status === "acknowledged";
  return (
    <Row
      tone={a.severity === "critical" ? "critical" : a.severity === "warning" ? "warning" : "info"}
      leading={<Icon size={16} />}
      title={
        <span className="cluster">
          {a.title}
          <Badge tone={SEVERITY_TONE[a.severity]} dot={false}>{SEVERITY_LABEL[a.severity]}</Badge>
          <Badge tone={a.kind === "early_warning" ? "accent" : "neutral"} dot={false}>{KIND_LABEL[a.kind]}</Badge>
        </span>
      }
      sub={
        <>
          <div>{a.message}</div>
          <div className="mt-1">
            Rilevato il {dateIt(a.detected_at)}
            {a.first_detected_at !== a.detected_at && <> · prima volta il {dateIt(a.first_detected_at)}</>}
            {a.resolution_kind && (
              <> · chiuso {a.resolution_kind === "auto" ? "automaticamente" : "da un operatore"}
                {a.resolved_at ? ` il ${dateIt(a.resolved_at)}` : ""}</>
            )}
          </div>
          {a.resolution_note && <div className="mt-1">Nota: {a.resolution_note}</div>}
          <div className="mono text-2xs mt-1">{a.rule_code} v{a.rule_version} · {a.formula_version}</div>
        </>
      }
      trailing={
        <div className="stack stack--sm">
          <div className="right"><StatusBadge status={a.status} /></div>
          {canWrite && active && (
            <div className="cluster cluster--end">
              {a.status === "open" && (
                <button className="btn btn--ghost btn--sm" title="Prendi in carico" onClick={() => onTransition(a, "acknowledge")}>
                  <Eye size={12} /> Prendi in carico
                </button>
              )}
              <button className="btn btn--ghost btn--sm" title="Risolvi" onClick={() => onTransition(a, "resolve")}>
                <CheckCircle2 size={12} /> Risolvi
              </button>
              <button className="btn btn--danger btn--sm" title="Archivia (motivazione obbligatoria)" onClick={() => onTransition(a, "dismiss")}>
                <XCircle size={12} /> Archivia
              </button>
            </div>
          )}
        </div>
      }
    />
  );
}
