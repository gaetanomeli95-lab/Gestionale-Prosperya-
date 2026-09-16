import type { CSSProperties, ReactNode } from "react";

export function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

const STATUS_TONES: Record<string, string> = {
  // companies
  prospect: "info", customer: "success", former: "neutral",
  lead: "info", qualified: "primary", active: "success", dormant: "neutral",
  // leads
  new: "info", contacted: "primary", unqualified: "neutral", converted: "success",
  // opportunities
  open: "primary", won: "success", lost: "danger",
  // tasks
  todo: "neutral", in_progress: "primary", done: "success", cancelled: "neutral",
  // priorities
  low: "neutral", medium: "info", high: "warning", urgent: "danger",
  // invoices
  draft: "neutral", ready_to_send: "info", queued: "info", transmitting: "info",
  sent_to_provider: "primary", submitted_to_sdi: "primary", delivered: "success",
  accepted: "success", rejected: "danger", delivery_failed: "danger",
  transmission_unknown: "warning", requires_reconciliation: "warning",
  credited: "accent", imported: "neutral",
  // health
  healthy: "success", degraded: "warning", unavailable: "danger",
  authentication_error: "danger", configuration_error: "warning", unknown: "neutral",
  // fiscal
  calculated: "primary", review_required: "warning", validated: "success",
  superseded: "neutral", pending: "warning", paid: "success",
  validation_required: "warning", approved: "primary", exported: "accent",
  generated: "neutral", settled: "success", locked: "neutral",
  resolved: "info", supported: "success", unsupported: "danger",
  insufficient_data: "warning",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  return <Badge tone={STATUS_TONES[s] ?? "neutral"}>{s.replaceAll("_", " ")}</Badge>;
}

export function Card({ children, className = "", style }: {
  children: ReactNode; className?: string; style?: CSSProperties;
}) {
  return <section className={`card ${className}`} style={style}>{children}</section>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spinner() {
  return <div className="empty" role="status">Caricamento…</div>;
}

export function ErrorBanner({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : "Si è verificato un errore imprevisto.";
  return <div className="alert alert--danger" role="alert">{message}</div>;
}

export function Modal({
  title, onClose, children, footer,
}: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="modal__backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={title}>
        <div className="modal__head"><h3>{title}</h3></div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Pagination({
  page, pageSize, total, onPage,
}: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="pagination">
      <button className="btn btn--ghost btn--sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ← Precedente
      </button>
      <span>Pagina {page} di {pages} · {total} risultati</span>
      <button className="btn btn--ghost btn--sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Successiva →
      </button>
    </div>
  );
}
