import type { CSSProperties, ReactNode } from "react";
import { Inbox } from "lucide-react";

export function Badge({ tone = "neutral", children, title }: { tone?: string; children: ReactNode; title?: string }) {
  return <span className={`badge badge--${tone}`} title={title}>{children}</span>;
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
  // practices
  blocked: "danger", completed: "success", closed: "neutral", submitted: "primary",
};

/** Italian, human labels for machine statuses. Codes stay English in the API. */
const STATUS_LABELS: Record<string, string> = {
  prospect: "Prospect", customer: "Cliente", former: "Ex cliente",
  lead: "Lead", qualified: "Qualificato", active: "Attivo", dormant: "Inattivo",
  new: "Nuovo", contacted: "Contattato", unqualified: "Non qualificato", converted: "Convertito",
  open: "Aperta", won: "Vinta", lost: "Persa",
  todo: "Da fare", in_progress: "In corso", done: "Fatto", cancelled: "Annullato",
  low: "Bassa", medium: "Media", high: "Alta", urgent: "Urgente",
  draft: "Bozza", ready_to_send: "Pronta all'invio", queued: "In coda", transmitting: "In trasmissione",
  sent_to_provider: "Inviata al provider", submitted_to_sdi: "Inviata a SdI", delivered: "Consegnata",
  accepted: "Accettata", rejected: "Scartata", delivery_failed: "Mancata consegna",
  transmission_unknown: "Trasmissione incerta", requires_reconciliation: "Da riconciliare",
  credited: "Stornata", imported: "Importata",
  healthy: "Operativo", degraded: "Degradato", unavailable: "Non disponibile",
  authentication_error: "Errore autenticazione", configuration_error: "Errore configurazione", unknown: "Sconosciuto",
  calculated: "Calcolato", review_required: "Da verificare", validated: "Validato",
  superseded: "Superato", pending: "In attesa", paid: "Pagato",
  validation_required: "Da validare", approved: "Approvato", exported: "Esportato",
  generated: "Generato", settled: "Regolato", locked: "Bloccato",
  resolved: "Risolto", supported: "Supportato", unsupported: "Non supportato",
  insufficient_data: "Dati insufficienti",
  blocked: "Bloccata", completed: "Completata", closed: "Chiusa", submitted: "Presentata",
  small: "Piccola", micro: "Micro", medium_size: "Media", large: "Grande",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return STATUS_LABELS[status] ?? status.replaceAll("_", " ");
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  return <Badge tone={STATUS_TONES[s] ?? "neutral"} title={s}>{statusLabel(s)}</Badge>;
}

export function Card({ children, className = "", style, onClick }: {
  children: ReactNode; className?: string; style?: CSSProperties; onClick?: () => void;
}) {
  return <section className={`card ${className}`} style={style} onClick={onClick}>{children}</section>;
}

export function EmptyState({ children, title, icon }: { children: ReactNode; title?: string; icon?: ReactNode }) {
  if (!title) return <div className="empty">{children}</div>;
  return (
    <div className="empty empty--rich">
      <div className="empty__icon">{icon ?? <Inbox size={20} strokeWidth={1.8} />}</div>
      <div className="empty__title">{title}</div>
      <div>{children}</div>
    </div>
  );
}

export function Spinner() {
  return <div className="empty" role="status">Caricamento…</div>;
}

export function ErrorBanner({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : "Si è verificato un errore imprevisto.";
  return <div className="alert alert--danger" role="alert">{message}</div>;
}

/** Page header: eyebrow + title + the question this screen answers + actions. */
export function PageHeader({ eyebrow, title, question, actions, hero = false }: {
  eyebrow?: string; title: string; question?: ReactNode; actions?: ReactNode; hero?: boolean;
}) {
  return (
    <div className={hero ? "hero" : "page-head"}>
      <div>
        {eyebrow && <div className="eyebrow" style={{ marginBottom: 8 }}>{eyebrow}</div>}
        <h1>{title}</h1>
        {question && <div className={hero ? "hero__q" : "page-head__meta"}>{question}</div>}
      </div>
      {actions && <div className={hero ? "hero__ctrl" : "page-head__actions"}>{actions}</div>}
    </div>
  );
}

/** Number tile. `hero` renders the one number that matters on a dark petrol tile. */
export function Stat({ label, value, hint, icon, tone, hero = false, onClick }: {
  label: ReactNode; value: ReactNode; hint?: ReactNode; icon?: ReactNode;
  tone?: "danger" | "warn"; hero?: boolean; onClick?: () => void;
}) {
  const cls = ["card", "stat", hero ? "card--dark stat--hero" : "", tone ? `stat--${tone}` : "", onClick ? "card--interactive" : ""]
    .filter(Boolean).join(" ");
  return (
    <section className={cls} onClick={onClick} role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined}
             onKeyDown={onClick ? (e) => e.key === "Enter" && onClick() : undefined}>
      <div className="stat__label">{icon}{label}</div>
      <div className="stat__value">{value}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </section>
  );
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
