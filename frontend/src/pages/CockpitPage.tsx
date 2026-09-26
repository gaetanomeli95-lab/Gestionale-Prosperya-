import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Building2, Landmark, Receipt, ShieldAlert, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { api } from "../api/client";
import type { CompanyCockpit } from "../api/types";
import { Badge, Callout, EmptyState, ErrorBanner, KV, NA, Section, Skeleton, Stat, StatusBadge, Tile, statusLabel } from "../components/ui";
import { money } from "../lib/format";
import { ActionList } from "./HubPage";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];

function Val({ v, suffix }: { v: string | null; suffix?: string }) {
  if (v == null) return <NA />;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

function Signed({ v }: { v: string | null }) {
  if (v == null) return <NA />;
  const n = Number(v);
  return <span className={n < 0 ? "neg" : n > 0 ? "pos" : undefined}>{money(v)}</span>;
}

export default function CockpitPage() {
  const { companyId = "" } = useParams();
  const navigate = useNavigate();
  const [year, setYear] = useState(2026);
  const [month, setMonth] = useState(6);

  const cockpit = useQuery({
    queryKey: ["cockpit", companyId, year, month],
    queryFn: () => api.get<CompanyCockpit>(
      `/cockpit/companies/${companyId}?year=${year}&through_month=${month}`),
    enabled: !!companyId,
  });

  if (cockpit.isLoading) return <><Skeleton rows={2} /><Skeleton kind="stats" rows={4} /><Skeleton rows={6} /></>;
  if (cockpit.error) return <ErrorBanner error={cockpit.error} />;
  const data = cockpit.data!;
  const { company, management: mgmt, treasury: cash, commercial } = data;
  const initials = company.legal_name.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const critical = data.actions.filter((a) => a.severity === "critical").length;
  const resultNeg = mgmt.result != null && Number(mgmt.result) < 0;

  return (
    <>
      <section className="card dossier">
        <div className="dossier__mark" aria-hidden="true">{initials || "•"}</div>
        <div className="truncate">
          <div className="eyebrow">Cockpit CFO · <Link to="/hub">Control hub</Link></div>
          <h1 className="dossier__name">{company.legal_name}</h1>
          <div className="dossier__meta">
            <StatusBadge status={company.status} />
            <span className="num">{company.vat_number ? `P.IVA ${company.vat_number}` : "P.IVA n.d."}</span>
            {company.ateco_code && <span>ATECO {company.ateco_code}</span>}
            {company.region && <span>{company.region}</span>}
            {company.employee_count != null && <span>{company.employee_count} dipendenti</span>}
          </div>
        </div>
        <div className="dossier__actions">
          <select className="select select--sm" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Anno">
            {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
          </select>
          <select className="select select--sm" value={month} onChange={(e) => setMonth(Number(e.target.value))} aria-label="Periodo">
            {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>Gen–{m}</option>)}
          </select>
          <button className="btn btn--primary" onClick={() => navigate(`/companies/${companyId}`)}><Building2 size={15} /> Dossier azienda</button>
        </div>
      </section>

      <div className="stat-grid">
        <Stat hero icon={<Wallet size={14} />} label="Cassa" value={<Val v={cash.position.amount} />}
              hint={cash.forecast.first_negative_date
                ? <span className="neg">Negativa dal {cash.forecast.first_negative_date}</span>
                : `Previsione a ${cash.forecast.horizon_days} giorni · ${statusLabel(cash.position.status)}`} />
        <Stat icon={resultNeg ? <TrendingDown size={14} /> : <TrendingUp size={14} />} label="Risultato gestionale" value={<Signed v={mgmt.result} />}
              hint={<>Margine <Val v={mgmt.margin_percent} suffix="%" /> · {mgmt.period.label}</>} tone={resultNeg ? "danger" : undefined} />
        <Stat icon={<Landmark size={14} />} label="Crediti scaduti" value={<Val v={cash.aging.receivables.overdue.amount} />}
              hint={`${cash.aging.receivables.overdue.count} partite · max ${cash.aging.receivables.overdue.max_days} giorni`}
              tone={cash.aging.receivables.overdue.count > 0 ? "warn" : undefined} onClick={() => navigate("/treasury")} />
        <Stat icon={<ShieldAlert size={14} />} label="Segnali aperti" value={data.actions.length}
              hint={`${critical} critici · ${data.controlling.open_alerts} alert controlling`} tone={critical > 0 ? "danger" : undefined} />
      </div>

      <Section title="Cosa richiede attenzione" tone={critical > 0 ? "critical" : data.actions.some((a) => a.severity === "warning") ? "warning" : undefined}
               footer={<>Ordinamento: {data.priority.formula} · <span className="mono">{data.priority.version}</span></>}>
        <ActionList actions={data.actions} />
      </Section>

      <div className="grid-2 mt-4">
        <Section title="Economia gestionale · budget vs consuntivo" flush
                 footer={<>Copertura {mgmt.quality.covered_months}/{mgmt.quality.expected_months} mesi · {mgmt.trace.source_count} fonti tracciate · formule <span className="mono">{mgmt.trace.formula_version}</span> / <span className="mono">{data.contribution.trace.formula_version}</span></>}>
          <table className="table table--flush table--static">
            <thead>
              <tr><th></th><th className="th--num">Budget</th><th className="th--num">Consuntivo</th><th className="th--num">Scostamento</th></tr>
            </thead>
            <tbody>
              {(["revenue", "costs", "result"] as const).map((k) => {
                const variance = mgmt.budget[`${k === "costs" ? "cost" : k}_variance` as keyof typeof mgmt.budget] as string | null;
                return (
                  <tr key={k}>
                    <td className="table__primary">{{ revenue: "Ricavi", costs: "Costi", result: "Risultato" }[k]}</td>
                    <td className="td--num"><Val v={mgmt.budget[k]} /></td>
                    <td className="td--num"><Val v={mgmt[k]} /></td>
                    <td className="td--num"><Signed v={variance} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="section__body">
            <div className="card__title">Margine di contribuzione e break-even</div>
            <div className="grid-auto grid-auto--sm">
              <Tile label="Costi variabili" value={<Val v={data.contribution.variable_costs} />} />
              <Tile label="Costi fissi" value={<Val v={data.contribution.fixed_costs} />} />
              <Tile label="Margine di contribuzione" value={<Val v={data.contribution.contribution_margin} />}
                    hint={data.contribution.contribution_margin_percent ? `${data.contribution.contribution_margin_percent}% dei ricavi` : undefined} />
              <Tile label="Break-even" value={<Val v={data.contribution.break_even_revenue} />} hint="ricavi di pareggio" />
            </div>
            {data.contribution.reasons.length > 0 && (
              <details className="mt-3">
                <summary className="eyebrow eyebrow--muted">Perché alcuni valori mancano ({data.contribution.reasons.length})</summary>
                <ul className="mgmt-issues mt-2">{data.contribution.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              </details>
            )}
          </div>
        </Section>

        <div className="stack">
          <Section title="Tesoreria" actions={<Link to="/treasury" className="btn btn--ghost btn--sm">Apri <ArrowRight size={12} /></Link>}>
            <div className="grid-auto grid-auto--sm">
              <Tile label="Crediti aperti" value={<Val v={cash.counters.receivable_residual} />} />
              <Tile label="Debiti aperti" value={<Val v={cash.counters.payable_residual} />} />
              <Tile label="Da riconciliare" value={cash.counters.unreconciled_transactions} hint={<Val v={cash.counters.unreconciled_amount} />}
                    tone={cash.counters.unreconciled_transactions > 0 ? "warn" : undefined} />
              {cash.forecast.horizons.map((h) => (
                <Tile key={h.horizon_days} label={`Flusso netto ${h.horizon_days}g`} value={<Signed v={h.net_flow} />} />
              ))}
            </div>
          </Section>

          <Section title="Fisco · IVA e F24" actions={<Link to={`/fiscal?company=${companyId}`} className="btn btn--ghost btn--sm">Apri <ArrowRight size={12} /></Link>}
                   footer={<>Motore <span className="mono">{data.fiscal.engine_version}</span> · importi solo da liquidazioni calcolate e validate da un operatore.</>}>
            <KV columns={2} items={[
              { k: "Posizione IVA", v: data.fiscal.latest_settlement ? (
                  <span className="cluster"><span className="num"><Val v={data.fiscal.latest_settlement.net_position} /></span><StatusBadge status={data.fiscal.latest_settlement.status} /></span>
                ) : <span className="na">nessuna liquidazione</span> },
              { k: "Periodo", v: data.fiscal.latest_settlement ? `${data.fiscal.latest_settlement.period?.label ?? ""} · v${data.fiscal.latest_settlement.version}` : null },
              { k: "Prossima scadenza", v: data.fiscal.next_obligation ? <span className="num">{data.fiscal.next_obligation.due_date} · <Val v={data.fiscal.next_obligation.amount} /></span> : <span className="na">nessuna obbligazione validata</span> },
              { k: "Voci IVA da verificare", v: <span className="num">{data.fiscal.counters.pending_entries}</span> },
              { k: "Bozze F24", v: <span className="num">{data.fiscal.counters.f24_drafts}</span> },
              { k: "Scadenze aperte", v: <span className="num">{data.fiscal.counters.open_deadlines}</span> },
            ]} />
          </Section>
        </div>
      </div>

      <div className="grid-2 mt-4">
        <Section title={<>Controlling & early warning {data.controlling.open_alerts > 0 ? <Badge tone="danger">{data.controlling.open_alerts} aperti</Badge> : <Badge tone="success">nessun segnale</Badge>}</>}
                 actions={<Link to={`/controlling?company=${companyId}`} className="btn btn--ghost btn--sm">Apri <ArrowRight size={12} /></Link>}
                 footer="I segnali early-warning non sono una determinazione legale di crisi.">
          {data.controlling.alerts.length === 0 ? (
            <Callout tone="neutral">{data.controlling.note}</Callout>
          ) : (
            <div className="hub__actions">
              {data.controlling.alerts.slice(0, 5).map((a) => (
                <div className={`action action--${a.severity}`} key={a.id}>
                  <i className="action__edge" />
                  <div>
                    <div className="action__title"><ShieldAlert size={15} strokeWidth={2} />{a.title}</div>
                    <div className="action__msg">{a.message}</div>
                    <div className="action__formula">{a.rule_code} v{a.rule_version} · {a.formula_version} · {a.detected_at}</div>
                  </div>
                  <div className="action__side">
                    <Badge tone={a.severity === "critical" ? "danger" : "warning"}>{statusLabel(a.severity)}</Badge>
                    <span className="muted text-2xs">{a.kind === "early_warning" ? "CCII" : "Gestionale"}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="Pipeline commerciale" flush={commercial.open_opportunities > 0} footer={commercial.expected_value_note}
                 actions={<Link to="/pipeline" className="btn btn--ghost btn--sm">Apri <ArrowRight size={12} /></Link>}>
          {commercial.open_opportunities === 0 ? (
            <EmptyState title="Nessuna opportunità aperta" icon={<Receipt size={20} strokeWidth={1.8} />}>Le opportunità del CRM legate a questa azienda compaiono qui.</EmptyState>
          ) : (
            <table className="table table--flush table--static">
              <thead><tr><th>Opportunità</th><th className="th--num">Valore atteso</th><th className="th--num">Inattiva da</th></tr></thead>
              <tbody>
                {commercial.items.map((o) => (
                  <tr key={o.id}>
                    <td className="table__primary">{o.title}</td>
                    <td className="td--num"><Val v={o.expected_value_eur} /></td>
                    <td className="td--num">
                      {o.days_inactive != null
                        ? <span className={o.days_inactive >= commercial.stale_days_threshold ? "neg" : undefined}>{o.days_inactive} g</span>
                        : <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      </div>

      <details className="mt-4">
        <summary className="eyebrow eyebrow--muted">Qualità dei dati e limitazioni ({mgmt.quality.issues.length + data.limitations.length})</summary>
        <Section tone="section" className="mt-2">
          <ul className="mgmt-issues">
            {mgmt.quality.issues.map((i) => <li key={i}>{i}</li>)}
            {data.limitations.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </Section>
      </details>
    </>
  );
}
