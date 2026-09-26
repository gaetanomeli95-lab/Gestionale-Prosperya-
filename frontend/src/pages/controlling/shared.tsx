import type { ReactNode } from "react";
import type { MetricResult } from "../../api/types";
import { Dot, NA, Tile } from "../../components/ui";
import { money } from "../../lib/format";

/* Labels (Italian on screen, codes stay English in the API) */

export const METRIC_STATUS_LABEL: Record<string, string> = {
  available: "disponibile",
  partial: "copertura parziale",
  insufficient_data: "dati insufficienti",
  not_applicable: "non applicabile",
  not_calculable: "non calcolabile",
  unsupported: "non supportato",
  limited: "limitata",
  beyond_horizon: "oltre l'orizzonte",
};

export const METRIC_STATUS_TONE: Record<string, string> = {
  available: "success", partial: "warning", insufficient_data: "warning",
  not_applicable: "neutral", not_calculable: "neutral", unsupported: "neutral",
  limited: "warning", beyond_horizon: "success",
};

export const NATURE_LABEL: Record<string, string> = {
  trade_receivable: "crediti commerciali",
  trade_payable: "debiti commerciali",
  fiscal: "obbligazioni fiscali",
  financial: "esposizioni finanziarie",
  debt_service: "servizio del debito",
  fixed_cost: "costi fissi (ipotesi)",
};

export const RUNWAY_LABEL: Record<string, string> = {
  limited: "limitata",
  beyond_horizon: "oltre l'orizzonte dei dati",
  not_calculable: "non calcolabile",
};

export const SEVERITY_LABEL: Record<string, string> = {
  critical: "critico", warning: "attenzione", info: "informativo",
};
export const SEVERITY_TONE: Record<string, string> = {
  critical: "danger", warning: "warning", info: "info",
};

export const KIND_LABEL: Record<string, string> = {
  early_warning: "CCII / early warning", management: "gestionale",
};

export const CERTAINTY_LABEL: Record<string, string> = {
  actual: "consuntivo", contracted: "contrattuale", forecast: "previsione", assumption: "ipotesi",
};
export const CERTAINTY_TONE: Record<string, string> = {
  actual: "success", contracted: "primary", forecast: "info", assumption: "warning",
};

export const TREND_METRIC_LABEL: Record<string, string> = {
  revenue: "Ricavi",
  costs: "Costi",
  result: "Risultato gestionale",
  margin_percent: "Margine %",
  contribution_margin: "Margine di contribuzione",
  overdue_receivables: "Crediti scaduti",
  overdue_payables: "Debiti scaduti",
  cash_position: "Posizione di cassa",
  dscr: "DSCR",
  minimum_projected_balance: "Cassa minima proiettata",
  open_items: "Partite aperte",
};

export function trendLabel(metric: string): string {
  return TREND_METRIC_LABEL[metric] ?? metric.replaceAll("_", " ");
}

/** Decimal string or the explicit "no evidence" marker — never a fake 0. */
export function Val({ v, suffix }: { v: string | null | undefined; suffix?: string }) {
  if (v == null) return <NA />;
  const n = Number(v);
  const cls = Number.isFinite(n) && n < 0 ? "num neg" : "num";
  return <span className={cls}>{suffix ? `${v}${suffix}` : money(v)}</span>;
}

/** Inline metric status: colored dot + Italian label. */
export function MetricBadge({ status }: { status: string }) {
  return (
    <Dot tone={METRIC_STATUS_TONE[status] ?? "neutral"} title={status}>
      {METRIC_STATUS_LABEL[status] ?? status.replaceAll("_", " ")}
    </Dot>
  );
}

/** Dense fact tile for a MetricResult: value or status, reasons as hint. */
export function Metric({ label, m, suffix, icon }: {
  label: ReactNode; m: MetricResult; suffix?: string; icon?: ReactNode;
}) {
  const tone = m.value == null
    ? "muted"
    : suffix === "%" && Number(m.value) < 0 ? "danger" : undefined;
  return (
    <Tile
      icon={icon}
      label={label}
      tone={tone}
      value={m.value != null ? <Val v={m.value} suffix={suffix} /> : <MetricBadge status={m.status} />}
      hint={m.reasons.length > 0 ? m.reasons.join(" ") : undefined}
    />
  );
}

/** Bullet list of declared reasons / issues / limitations. */
export function Reasons({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mgmt-issues">
      {items.map((r) => <li key={r}>{r}</li>)}
    </ul>
  );
}

/** Small muted footnote: formula/engine versions, never in the primary view. */
export function Footnote({ children }: { children: ReactNode }) {
  return <div className="muted text-xs mt-2">{children}</div>;
}
