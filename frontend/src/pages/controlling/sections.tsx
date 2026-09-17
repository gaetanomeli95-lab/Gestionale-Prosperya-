import {
  CheckCircle2, Eye, Plus, RefreshCw, ShieldAlert, XCircle,
} from "lucide-react";
import type {
  AlertsResponse, ControllingAlert, ControllingSnapshot, DebtFacility,
  DebtLine, DscrResult, EwRulesResponse, FacilitiesResponse,
} from "../../api/types";
import { Badge, Card, EmptyState, Spinner, StatusBadge } from "../../components/ui";
import { dateIt } from "../../lib/format";
import { MetricBadge, Val } from "./shared";

const SEVERITY_LABEL: Record<string, string> = {
  critical: "critico", warning: "attenzione", info: "informativo",
};
const KIND_LABEL: Record<string, string> = {
  early_warning: "CCII / early warning", management: "gestionale",
};
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

// ---------------------------------------------------------------------------
// Debito & DSCR
// ---------------------------------------------------------------------------

export function DscrCard({ dscr }: { dscr: DscrResult }) {
  return (
    <Card className="card__pad">
      <div className="card__title">
        DSCR prospettico · orizzonte {dscr.horizon_days} giorni{" "}
        <MetricBadge status={dscr.status} />
      </div>
      <div className="kpi-grid" style={{ marginBottom: 12 }}>
        <div>
          <div className="kpi__label">Valore</div>
          <div className="kpi__value mono" style={{ fontSize: "1.6rem" }}>{dscr.value ?? "n.d."}</div>
        </div>
        <div>
          <div className="kpi__label">Numeratore (CFADS proxy)</div>
          <div className="kpi__value mono" style={{ fontSize: "1.1rem" }}><Val v={dscr.numerator} /></div>
        </div>
        <div>
          <div className="kpi__label">Denominatore (servizio del debito)</div>
          <div className="kpi__value mono" style={{ fontSize: "1.1rem" }}><Val v={dscr.denominator} /></div>
        </div>
        <div>
          <div className="kpi__label">Copertura orizzonte</div>
          <div className="kpi__value mono" style={{ fontSize: "1.1rem" }}>
            {dscr.coverage_percent ? `${dscr.coverage_percent}%` : "n.d."}
          </div>
        </div>
      </div>
      {dscr.components && (
        <div className="dl">
          <dt>Incassi attesi</dt><dd className="mono"><Val v={dscr.components.expected_inflows} /></dd>
          <dt>Pagamenti attesi (escl. debito)</dt><dd className="mono"><Val v={dscr.components.expected_outflows_ex_debt} /></dd>
          <dt>Rate in scadenza</dt><dd className="mono">{dscr.components.instalments_due}</dd>
          <dt>Finestra coperta fino al</dt><dd className="mono">{dscr.covered_until ?? "—"}</dd>
        </div>
      )}
      {dscr.reasons.length > 0 && (
        <ul className="mgmt-issues" style={{ marginTop: 10 }}>
          {dscr.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <details style={{ marginTop: 10 }}>
        <summary className="muted" style={{ cursor: "pointer", fontSize: "0.78rem" }}>
          Formula, ipotesi e fonti ({dscr.source_ids.length} partite, {dscr.debt_line_ids.length} rate)
        </summary>
        <div className="dl" style={{ marginTop: 8 }}>
          {Object.entries(dscr.formulas).map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt className="mono" style={{ fontSize: "0.75rem" }}>{k}</dt>
              <dd style={{ fontSize: "0.78rem" }}>{v}</dd>
            </div>
          ))}
        </div>
        <ul className="mgmt-issues" style={{ marginTop: 8 }}>
          {dscr.assumptions.map((a) => <li key={a}>{a}</li>)}
        </ul>
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          Formula <span className="mono">{dscr.formula_version}</span> · motore{" "}
          <span className="mono">{dscr.engine_version}</span> · il DSCR è un proxy
          gestionale, non una determinazione legale.
        </div>
      </details>
    </Card>
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
    <>
      <DscrCard dscr={snap.dscr} />
      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Linee di debito e rate</span>
          {canWrite && (
            <button className="btn btn--ghost btn--sm" onClick={onNewFacility}>
              <Plus size={13} /> Nuova linea
            </button>
          )}
        </div>
        {!facilities ? <Spinner /> : facilities.facilities.length === 0 ? (
          <EmptyState>Nessuna linea di debito registrata. Le rate non sono duplicate come partite di tesoreria.</EmptyState>
        ) : (
          facilities.facilities.map((f) => (
            <div key={f.id} style={{ marginBottom: 18 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <strong>
                  {f.name}{" "}
                  <Badge tone="info">{FACILITY_TYPE_LABEL[f.facility_type] ?? f.facility_type}</Badge>{" "}
                  {!f.is_active && <Badge tone="neutral">non attiva</Badge>}
                </strong>
                <span className="muted" style={{ fontSize: "0.75rem" }}>
                  {f.lender_name ?? "finanziatore n.d."} · residuo <Val v={f.outstanding_principal} /> ·{" "}
                  {f.scheduled_count} rate pianificate (<Val v={f.scheduled_service} />)
                </span>
              </div>
              <table className="table" style={{ marginTop: 6 }}>
                <thead>
                  <tr>
                    <th>Rata</th><th>Scadenza</th>
                    <th style={{ textAlign: "right" }}>Capitale</th>
                    <th style={{ textAlign: "right" }}>Interessi</th>
                    <th style={{ textAlign: "right" }}>Rata totale</th>
                    <th>Stato</th>
                    {canWrite && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {(f.lines ?? []).map((l) => (
                    <tr key={l.id} style={{ cursor: "default" }}>
                      <td className="mono">{l.instalment_no}</td>
                      <td className="mono">
                        <span className={l.status === "scheduled" && l.due_date < snap.as_of ? "tre-neg" : ""}>
                          {l.due_date}
                        </span>
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={l.principal} /></td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={l.interest} /></td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={l.service} /></td>
                      <td>
                        <StatusBadge status={l.status} />
                        {l.status_note && <div className="muted" style={{ fontSize: "0.7rem" }}>{l.status_note}</div>}
                      </td>
                      {canWrite && (
                        <td style={{ textAlign: "right" }}>
                          {l.status === "scheduled" && (
                            <button className="btn btn--ghost btn--sm" onClick={() => onSettle(l)}>
                              Regola
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
              {canWrite && (
                <button className="btn btn--ghost btn--sm" style={{ marginTop: 4 }}
                        onClick={() => onAddInstalment(f)}>
                  <Plus size={12} /> Aggiungi rata
                </button>
              )}
            </div>
          ))
        )}
        {facilities && (
          <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
            {facilities.counters.instalments} rate totali: {facilities.counters.scheduled} pianificate,{" "}
            {facilities.counters.paid} pagate, {facilities.counters.waived} sospese.
          </div>
        )}
      </Card>
    </>
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
  return (
    <>
      <div className="ai-banner" style={{ marginBottom: 16 }}>
        <ShieldAlert size={18} />
        <div>
          <strong>Segnali da verificare, non verdetti</strong>
          <div>
            Le regole early-warning sono ancorate al D.Lgs. 14/2019 (CCII). Un segnale rilevato
            indica una condizione da verificare: il sistema non determina mai uno stato di crisi.
            Le soglie marcate "operational" sono parametri di lavoro, non valori di legge.
          </div>
        </div>
        {canWrite && (
          <button className="btn btn--primary" disabled={evaluating} onClick={onEvaluate}>
            <RefreshCw size={14} /> {evaluating ? "Valutazione…" : "Rivaluta segnali"}
          </button>
        )}
      </div>

      <Card className="card__pad">
        <div className="card__title">Alert durevoli</div>
        {rows.length === 0 ? (
          <EmptyState>
            Nessun alert registrato. La detection non avviene al caricamento della pagina:
            usa "Rivaluta segnali" per valutare le regole attive.
          </EmptyState>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Regola</th><th>Segnale</th><th>Severità</th><th>Tipo</th>
                <th>Rilevato</th><th>Stato</th>
                {canWrite && <th></th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} style={{ cursor: "default" }}>
                  <td className="mono" style={{ fontSize: "0.75rem" }}>{a.rule_code} v{a.rule_version}</td>
                  <td>
                    <div>{a.title}</div>
                    <div className="muted" style={{ fontSize: "0.75rem" }}>{a.message}</div>
                    {a.resolution_note && (
                      <div className="muted" style={{ fontSize: "0.7rem" }}>Nota: {a.resolution_note}</div>
                    )}
                  </td>
                  <td>
                    <Badge tone={a.severity === "critical" ? "danger" : a.severity === "warning" ? "warning" : "info"}>
                      {SEVERITY_LABEL[a.severity]}
                    </Badge>
                  </td>
                  <td><Badge tone={a.kind === "early_warning" ? "accent" : "neutral"}>{KIND_LABEL[a.kind]}</Badge></td>
                  <td className="mono" style={{ fontSize: "0.75rem" }}>
                    {a.detected_at}
                    <div className="muted" style={{ fontSize: "0.68rem" }}>prima: {a.first_detected_at}</div>
                  </td>
                  <td>
                    <StatusBadge status={a.status} />
                    {a.resolution_kind && (
                      <div className="muted" style={{ fontSize: "0.68rem" }}>
                        {a.resolution_kind === "auto" ? "auto" : "umana"} · {a.resolved_at ? dateIt(a.resolved_at) : ""}
                      </div>
                    )}
                  </td>
                  {canWrite && (
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {a.status === "open" && (
                        <button className="btn btn--ghost btn--sm" title="Prendi in carico"
                                onClick={() => onTransition(a, "acknowledge")}>
                          <Eye size={12} />
                        </button>
                      )}
                      {(a.status === "open" || a.status === "acknowledged") && (
                        <>
                          <button className="btn btn--ghost btn--sm" title="Risolvi"
                                  onClick={() => onTransition(a, "resolve")}>
                            <CheckCircle2 size={12} />
                          </button>
                          <button className="btn btn--ghost btn--sm" title="Ignora (motivazione obbligatoria)"
                                  onClick={() => onTransition(a, "dismiss")}>
                            <XCircle size={12} />
                          </button>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {alerts && (
          <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
            {alerts.counters.total} alert: {alerts.counters.open} aperti,{" "}
            {alerts.counters.acknowledged} presi in carico, {alerts.counters.resolved} risolti,{" "}
            {alerts.counters.dismissed} ignorati.
          </div>
        )}
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Valutazione corrente delle regole (live, non persistita)</div>
        <table className="table">
          <thead>
            <tr><th>Regola</th><th>Categoria</th><th>Stato</th><th>Dettaglio</th></tr>
          </thead>
          <tbody>
            {snap.evaluations.map((e) => (
              <tr key={e.rule_code} style={{ cursor: "default" }}>
                <td className="mono" style={{ fontSize: "0.75rem" }}>{e.rule_code} v{e.rule_version}</td>
                <td><Badge tone={e.category === "ccii_legal" ? "accent" : "neutral"}>
                  {e.category === "ccii_legal" ? "CCII" : "organizzativa"}</Badge></td>
                <td><Badge tone={EVAL_TONE[e.state]}>{EVAL_LABEL[e.state]}</Badge></td>
                <td style={{ fontSize: "0.78rem" }}>{e.message ?? e.reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {rules && (
        <Card className="card__pad" style={{ marginTop: 16 }}>
          <div className="card__title">Regole attive e riferimenti normativi</div>
          {rules.rules.map((r) => (
            <div key={r.id} style={{ marginBottom: 14 }}>
              <div>
                <strong className="mono" style={{ fontSize: "0.8rem" }}>{r.code} v{r.version}</strong>{" "}
                <Badge tone={r.category === "ccii_legal" ? "accent" : "neutral"}>
                  {r.category === "ccii_legal" ? "CCII" : "organizzativa"}
                </Badge>{" "}
                <span className="muted" style={{ fontSize: "0.72rem" }}>efficace dal {r.effective_from}</span>
              </div>
              <div style={{ fontSize: "0.82rem" }}>{r.title}</div>
              <div className="muted" style={{ fontSize: "0.75rem" }}>{r.description}</div>
              <div className="muted" style={{ fontSize: "0.72rem", marginTop: 2 }}>{r.legal_reference}</div>
              <div style={{ fontSize: "0.72rem", marginTop: 2 }}>
                {Object.entries(r.params).map(([k, p]) => (
                  <span key={k} className="mono" style={{ marginRight: 10 }}>
                    {k}={String(p.value)}{" "}
                    <Badge tone={p.kind === "statutory" ? "primary" : "warning"}>{p.kind}</Badge>
                  </span>
                ))}
              </div>
              <div className="muted mono" style={{ fontSize: "0.68rem" }}>
                {r.formula} · {r.formula_version} · fonte: {r.source_authority}
              </div>
            </div>
          ))}
          <div className="muted" style={{ fontSize: "0.72rem" }}>{rules.disclaimer}</div>
        </Card>
      )}
    </>
  );
}
