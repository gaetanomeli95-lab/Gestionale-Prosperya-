import type { MetricResult } from "../../api/types";
import { Badge } from "../../components/ui";
import { money } from "../../lib/format";

export const METRIC_STATUS_LABEL: Record<string, string> = {
  available: "disponibile",
  partial: "copertura parziale",
  insufficient_data: "dati insufficienti",
  not_applicable: "non applicabile",
  not_calculable: "non calcolabile",
  unsupported: "non supportato",
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

/** Decimal string or the explicit "no evidence" marker — never a fake 0. */
export function Val({ v, suffix }: { v: string | null | undefined; suffix?: string }) {
  if (v == null) {
    return <span className="tre-null" title="Nessuna evidenza disponibile: non è zero">n.d.</span>;
  }
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

export function MetricBadge({ status }: { status: string }) {
  const tone = {
    available: "success", partial: "warning", insufficient_data: "warning",
    not_applicable: "neutral", not_calculable: "neutral", unsupported: "neutral",
  }[status] ?? "neutral";
  return <Badge tone={tone}>{METRIC_STATUS_LABEL[status] ?? status}</Badge>;
}

export function Metric({ label, m, suffix }: { label: string; m: MetricResult; suffix?: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className="mono">
        {m.value != null ? <Val v={m.value} suffix={suffix} /> : <MetricBadge status={m.status} />}
        {m.reasons.length > 0 && (
          <div className="muted" style={{ fontSize: "0.72rem" }}>{m.reasons.join(" ")}</div>
        )}
      </dd>
    </>
  );
}
