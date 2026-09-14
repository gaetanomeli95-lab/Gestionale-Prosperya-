import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "../api/client";
import type { CompanyCockpit } from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { money } from "../lib/format";
import { ActionList } from "./HubPage";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];

function Val({ v, suffix }: { v: string | null; suffix?: string }) {
  if (v == null) return <span className="tre-null" title="Nessuna evidenza disponibile: non è zero">n.d.</span>;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

export default function CockpitPage() {
  const { companyId = "" } = useParams();
  const [year, setYear] = useState(2026);
  const [month, setMonth] = useState(6);

  const cockpit = useQuery({
    queryKey: ["cockpit", companyId, year, month],
    queryFn: () => api.get<CompanyCockpit>(
      `/cockpit/companies/${companyId}?year=${year}&through_month=${month}`),
    enabled: !!companyId,
  });

  if (cockpit.isLoading) return <Spinner />;
  if (cockpit.error) return <ErrorBanner error={cockpit.error} />;
  const data = cockpit.data!;
  const { company, management: mgmt, treasury: cash, commercial } = data;

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/hub" className="muted" style={{ fontSize: "0.78rem" }}>
            <ArrowLeft size={12} style={{ verticalAlign: -2 }} /> Control hub
          </Link>
          <h1>{company.legal_name}</h1>
          <div className="page-head__meta">
            {company.vat_number ? `P.IVA ${company.vat_number}` : "P.IVA n.d."}
            {company.ateco_code ? ` · ATECO ${company.ateco_code}` : ""}
            {company.region ? ` · ${company.region}` : ""}
            {company.employee_count != null ? ` · ${company.employee_count} dipendenti` : ""}
            {" · "}<Badge tone="info">{company.status}</Badge>
          </div>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90 }}>
            {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
          </select>
          <select className="select" value={month} onChange={(e) => setMonth(Number(e.target.value))} style={{ width: 120 }}>
            {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>Gen–{m}</option>)}
          </select>
          <Link className="btn btn--ghost" to="/treasury">Tesoreria</Link>
          <Link className="btn btn--ghost" to="/management">Controllo di gestione</Link>
        </div>
      </div>

      <Card className="card__pad">
        <div className="card__title">Cosa richiede attenzione</div>
        <ActionList actions={data.actions} />
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
          {data.priority.formula} · <span className="mono">{data.priority.version}</span>
        </div>
      </Card>

      <div className="kpi-grid" style={{ marginTop: 16 }}>
        <Card className="kpi kpi--edge-primary">
          <div className="kpi__label">Ricavi disponibili</div>
          <div className="kpi__value mono"><Val v={mgmt.revenue} /></div>
          <div className="kpi__hint">{mgmt.period.label}</div>
        </Card>
        <Card className={`kpi kpi--edge-teal ${mgmt.result && Number(mgmt.result) < 0 ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Risultato gestionale</div>
          <div className="kpi__value mono"><Val v={mgmt.result} /></div>
          <div className="kpi__hint">margine <Val v={mgmt.margin_percent} suffix="%" /> · non è EBITDA</div>
        </Card>
        <Card className={`kpi kpi--edge-warn ${cash.position.status === "not_calculable" ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Cassa</div>
          <div className="kpi__value mono"><Val v={cash.position.amount} /></div>
          <div className="kpi__hint">
            {cash.forecast.first_negative_date
              ? <span className="tre-neg">negativa dal {cash.forecast.first_negative_date}</span>
              : `previsione ${cash.forecast.horizon_days} giorni`}
          </div>
        </Card>
        <Card className="kpi kpi--edge-accent">
          <div className="kpi__label">Crediti scaduti</div>
          <div className="kpi__value mono"><Val v={cash.aging.receivables.overdue.amount} /></div>
          <div className="kpi__hint">
            {cash.aging.receivables.overdue.count} partite · max {cash.aging.receivables.overdue.max_days} giorni
          </div>
        </Card>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <Card className="card__pad">
          <div className="card__title">Economia gestionale · budget vs consuntivo</div>
          <table className="table">
            <thead>
              <tr>
                <th></th>
                <th style={{ textAlign: "right" }}>Budget</th>
                <th style={{ textAlign: "right" }}>Consuntivo</th>
                <th style={{ textAlign: "right" }}>Scostamento</th>
              </tr>
            </thead>
            <tbody>
              {(["revenue", "costs", "result"] as const).map((k) => {
                const variance = mgmt.budget[`${k === "costs" ? "cost" : k}_variance` as keyof typeof mgmt.budget] as string | null;
                return (
                  <tr key={k} style={{ cursor: "default" }}>
                    <td>{{ revenue: "Ricavi", costs: "Costi", result: "Risultato" }[k]}</td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={mgmt.budget[k]} /></td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={mgmt[k]} /></td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={variance} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
            Copertura {mgmt.quality.covered_months}/{mgmt.quality.expected_months} mesi ·
            formula <span className="mono">{mgmt.trace.formula_version}</span> ·
            {mgmt.trace.source_count} fonti tracciate
          </div>
        </Card>

        <Card className="card__pad">
          <div className="card__title">Tesoreria</div>
          <div className="dl">
            <dt>Crediti aperti</dt><dd className="mono"><Val v={cash.counters.receivable_residual} /></dd>
            <dt>Debiti aperti</dt><dd className="mono"><Val v={cash.counters.payable_residual} /></dd>
            <dt>Movimenti da riconciliare</dt>
            <dd className="mono">{cash.counters.unreconciled_transactions} (<Val v={cash.counters.unreconciled_amount} />)</dd>
            {cash.forecast.horizons.map((h) => (
              <>
                <dt key={`t-${h.horizon_days}`}>Flusso netto {h.horizon_days}g</dt>
                <dd key={`v-${h.horizon_days}`} className="mono"><Val v={h.net_flow} /></dd>
              </>
            ))}
          </div>
          <div className="card__title" style={{ marginTop: 18 }}>Pipeline commerciale</div>
          {commercial.open_opportunities === 0 ? (
            <EmptyState>Nessuna opportunità aperta.</EmptyState>
          ) : (
            <table className="table">
              <thead><tr><th>Opportunità</th><th style={{ textAlign: "right" }}>Valore atteso</th><th style={{ textAlign: "right" }}>Inattiva</th></tr></thead>
              <tbody>
                {commercial.items.map((o) => (
                  <tr key={o.id} style={{ cursor: "default" }}>
                    <td>{o.title}</td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={o.expected_value_eur} /></td>
                    <td className="mono" style={{ textAlign: "right" }}>
                      {o.days_inactive != null
                        ? <span className={o.days_inactive >= commercial.stale_days_threshold ? "tre-neg" : ""}>{o.days_inactive}g</span>
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
            {commercial.expected_value_note}
          </div>
        </Card>
      </div>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Qualità dei dati e limitazioni</div>
        <ul className="mgmt-issues">
          {mgmt.quality.issues.map((i) => <li key={i}>{i}</li>)}
          {data.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </Card>
    </>
  );
}
