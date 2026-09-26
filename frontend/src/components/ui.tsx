import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Inbox, Info, X } from "lucide-react";

/* =========================================================================
   Prosperya UI kit — the only place where visual primitives are defined.
   Pages compose these; they do not invent classes or inline styles.
   ========================================================================= */

/* ---------- badges & statuses ---------- */

export function Badge({ tone = "neutral", children, title, dot = true }: {
  tone?: string; children: ReactNode; title?: string; dot?: boolean;
}) {
  return <span className={`badge badge--${tone}${dot ? "" : " badge--nodot"}`} title={title}>{children}</span>;
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
  // practices / funding / documents
  blocked: "danger", completed: "success", closed: "neutral", submitted: "primary",
  in_review: "primary", eligible: "success", not_eligible: "danger", partial: "warning",
  missing: "danger", uploaded: "info", expired: "danger", valid: "success", invalid: "danger",
  // severities
  critical: "danger", warning: "warning", info: "info", ok: "success", attention: "warning",
  // alerts
  dismissed: "neutral",
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
  in_review: "In revisione", eligible: "Ammissibile", not_eligible: "Non ammissibile", partial: "Parziale",
  missing: "Mancante", uploaded: "Caricato", expired: "Scaduto", valid: "Valido", invalid: "Non valido",
  critical: "Critico", warning: "Attenzione", info: "Informativo", ok: "Ok", attention: "Attenzione",
  dismissed: "Archiviato",
  small: "Piccola", micro: "Micro", medium_size: "Media", large: "Grande",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return STATUS_LABELS[status] ?? status.replaceAll("_", " ");
}
export function statusTone(status: string | null | undefined): string {
  return STATUS_TONES[status ?? "unknown"] ?? "neutral";
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  return <Badge tone={statusTone(s)} title={s}>{statusLabel(s)}</Badge>;
}

/** Small colored dot + label, for health/severity inline. */
export function Dot({ tone = "neutral", children, title }: { tone?: string; children?: ReactNode; title?: string }) {
  return <span className={`dot dot--${tone}`} title={title}><i />{children}</span>;
}

/* ---------- surfaces ---------- */

export function Card({ children, className = "", style, onClick, tone }: {
  children: ReactNode; className?: string; style?: CSSProperties; onClick?: () => void;
  tone?: "dark" | "section" | "critical" | "warning";
}) {
  const cls = ["card", tone ? `card--${tone}` : "", onClick ? "card--interactive" : "", className].filter(Boolean).join(" ");
  return <section className={cls} style={style} onClick={onClick}>{children}</section>;
}

/** Card with a header row (eyebrow title + optional actions) and padded body. */
export function Section({ title, actions, children, footer, tone, className = "", flush = false }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; footer?: ReactNode;
  tone?: "dark" | "section" | "critical" | "warning"; className?: string; flush?: boolean;
}) {
  return (
    <Card tone={tone} className={`section ${className}`}>
      {(title || actions) && (
        <div className="section__head">
          {title && <div className="card__title section__title">{title}</div>}
          {actions && <div className="section__actions">{actions}</div>}
        </div>
      )}
      <div className={`section__body${flush ? " section__body--flush" : ""}`}>{children}</div>
      {footer && <div className="section__foot">{footer}</div>}
    </Card>
  );
}

/** Compact info tile (label above, value below). For dense facts grids. */
export function Tile({ label, value, hint, tone, icon }: {
  label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: "danger" | "warn" | "success" | "muted"; icon?: ReactNode;
}) {
  return (
    <div className={`tile${tone ? ` tile--${tone}` : ""}`}>
      <div className="tile__label">{icon}{label}</div>
      <div className="tile__value">{value}</div>
      {hint && <div className="tile__hint">{hint}</div>}
    </div>
  );
}

/** Number tile. `hero` renders the one number that matters on a dark petrol tile. */
export function Stat({ label, value, hint, icon, tone, hero = false, onClick }: {
  label: ReactNode; value: ReactNode; hint?: ReactNode; icon?: ReactNode;
  tone?: "danger" | "warn" | "success"; hero?: boolean; onClick?: () => void;
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

/** A list row: leading icon/avatar, title + subtitle, trailing content. Clickable when onClick. */
export function Row({ leading, title, sub, trailing, onClick, tone }: {
  leading?: ReactNode; title: ReactNode; sub?: ReactNode; trailing?: ReactNode; onClick?: () => void;
  tone?: "critical" | "warning" | "info" | "success";
}) {
  const cls = ["row", onClick ? "row--link" : "", tone ? `row--${tone}` : ""].filter(Boolean).join(" ");
  return (
    <div className={cls} onClick={onClick} role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined}
         onKeyDown={onClick ? (e) => e.key === "Enter" && onClick() : undefined}>
      {leading && <div className="row__lead">{leading}</div>}
      <div className="row__main">
        <div className="row__title">{title}</div>
        {sub && <div className="row__sub">{sub}</div>}
      </div>
      {trailing && <div className="row__trail">{trailing}</div>}
    </div>
  );
}

/** Key/value pairs, two columns. */
export function KV({ items, columns = 1 }: { items: { k: ReactNode; v: ReactNode }[]; columns?: 1 | 2 | 3 }) {
  return (
    <dl className={`kv kv--${columns}`}>
      {items.map((it, i) => (
        <div className="kv__item" key={i}>
          <dt>{it.k}</dt>
          <dd>{it.v ?? <span className="muted">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Progress({ value, max = 100, tone, label }: { value: number; max?: number; tone?: "danger" | "warn" | "success" | "accent"; label?: ReactNode }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className={`progress${tone ? ` progress--${tone}` : ""}`} role="progressbar" aria-valuenow={value} aria-valuemax={max}>
      <div className="progress__track"><div className="progress__bar" style={{ width: `${pct}%` }} /></div>
      {label && <div className="progress__label">{label}</div>}
    </div>
  );
}

/* ---------- feedback ---------- */

export function EmptyState({ children, title, icon, action }: { children?: ReactNode; title?: string; icon?: ReactNode; action?: ReactNode }) {
  if (!title) return <div className="empty">{children}</div>;
  return (
    <div className="empty empty--rich">
      <div className="empty__icon">{icon ?? <Inbox size={20} strokeWidth={1.8} />}</div>
      <div className="empty__title">{title}</div>
      {children && <div className="empty__body">{children}</div>}
      {action && <div className="empty__action">{action}</div>}
    </div>
  );
}

/** Loading placeholder. Prefer `<Skeleton rows={n} />` inside a card over a bare Spinner. */
export function Skeleton({ rows = 3, kind = "lines" }: { rows?: number; kind?: "lines" | "stats" | "table" }) {
  if (kind === "stats") {
    return (
      <div className="stat-grid" role="status" aria-label="Caricamento">
        {Array.from({ length: rows }).map((_, i) => <div key={i} className="card stat skeleton skeleton--stat" />)}
      </div>
    );
  }
  if (kind === "table") {
    return (
      <div className="skeleton-table" role="status" aria-label="Caricamento">
        {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton skeleton--row" />)}
      </div>
    );
  }
  return (
    <div className="skeleton-lines" role="status" aria-label="Caricamento">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton skeleton--line" style={{ width: `${92 - (i % 3) * 14}%` }} />)}
    </div>
  );
}

export function Spinner() {
  return <Skeleton rows={4} />;
}

export function ErrorBanner({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : "Si è verificato un errore imprevisto.";
  return <Callout tone="danger" role="alert">{message}</Callout>;
}

/** Inline message with icon. Replaces the old .alert. */
export function Callout({ tone = "info", title, children, role, action }: {
  tone?: "info" | "warning" | "danger" | "success" | "neutral"; title?: ReactNode; children?: ReactNode; role?: string; action?: ReactNode;
}) {
  const Icon = tone === "danger" || tone === "warning" ? AlertTriangle : tone === "success" ? CheckCircle2 : Info;
  return (
    <div className={`callout callout--${tone}`} role={role}>
      <Icon size={16} className="callout__icon" />
      <div className="callout__body">
        {title && <div className="callout__title">{title}</div>}
        {children && <div>{children}</div>}
      </div>
      {action && <div className="callout__action">{action}</div>}
    </div>
  );
}

/* ---------- toasts (global, no provider needed) ---------- */

type Toast = { id: number; tone: "success" | "danger" | "info"; text: string };
const toastListeners = new Set<(t: Toast) => void>();
let toastSeq = 0;
export function toast(text: string, tone: Toast["tone"] = "success") {
  const t = { id: ++toastSeq, tone, text };
  toastListeners.forEach((l) => l(t));
}
export function ToastHost() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const on = (t: Toast) => {
      setItems((xs) => [...xs, t]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), 4200);
    };
    toastListeners.add(on);
    return () => { toastListeners.delete(on); };
  }, []);
  if (!items.length) return null;
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`}>
          {t.tone === "success" ? <CheckCircle2 size={16} /> : t.tone === "danger" ? <AlertTriangle size={16} /> : <Info size={16} />}
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  );
}

/* ---------- navigation inside a page ---------- */

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { key: T; label: ReactNode; count?: number; tone?: string }[]; value: T; onChange: (k: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={value === t.key}
                className={`tab${value === t.key ? " tab--active" : ""}`} onClick={() => onChange(t.key)}>
          {t.label}
          {t.count != null && <span className={`tab__count${t.tone ? ` tab__count--${t.tone}` : ""}`}>{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, ariaLabel }: {
  options: { value: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; ariaLabel?: string;
}) {
  return (
    <div className="segmented" role="tablist" aria-label={ariaLabel}>
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value}
                className={`segmented__opt${value === o.value ? " segmented__opt--on" : ""}`} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Page header: eyebrow + title + the question this screen answers + actions. */
export function PageHeader({ eyebrow, title, question, actions, hero = false }: {
  eyebrow?: ReactNode; title: ReactNode; question?: ReactNode; actions?: ReactNode; hero?: boolean;
}) {
  return (
    <div className={hero ? "hero" : "page-head"}>
      <div>
        {eyebrow && <div className="eyebrow page-head__eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {question && <div className={hero ? "hero__q" : "page-head__meta"}>{question}</div>}
      </div>
      {actions && <div className={hero ? "hero__ctrl" : "page-head__actions"}>{actions}</div>}
    </div>
  );
}

/** Filter/search bar above lists. */
export function Toolbar({ children, end }: { children?: ReactNode; end?: ReactNode }) {
  return (
    <div className="toolbar">
      {children}
      {end && <div className="toolbar__end">{end}</div>}
    </div>
  );
}

/* ---------- overlays ---------- */

export function Modal({
  title, subtitle, onClose, children, footer, size,
}: { title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; size?: "sm" | "lg" }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal__backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${size ? ` modal--${size}` : ""}`} role="dialog" aria-label={title} aria-modal="true">
        <div className="modal__head">
          <div>
            <h3>{title}</h3>
            {subtitle && <div className="modal__sub">{subtitle}</div>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Chiudi"><X size={16} /></button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__foot">{footer}</div>}
      </div>
    </div>
  );
}

/** Right-side panel for quick details without leaving the page. */
export function Drawer({ title, subtitle, onClose, children, footer, width }: {
  title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="drawer__backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" style={width ? { width } : undefined}>
        <div className="drawer__head">
          <div>
            <h3>{title}</h3>
            {subtitle && <div className="drawer__sub">{subtitle}</div>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Chiudi"><X size={16} /></button>
        </div>
        <div className="drawer__body">{children}</div>
        {footer && <div className="drawer__foot">{footer}</div>}
      </aside>
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

/* ---------- form helpers ---------- */

export function Field({ label, htmlFor, hint, error, children, span2 = false }: {
  label: ReactNode; htmlFor: string; hint?: ReactNode; error?: ReactNode; children: ReactNode; span2?: boolean;
}) {
  return (
    <div className={`field${span2 ? " span-2" : ""}`}>
      <label className="field__label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <div className="field__hint">{hint}</div>}
      {error && <div className="field__error" role="alert">{error}</div>}
    </div>
  );
}

/** Explicit "no evidence" marker — never a fake zero. */
export function NA({ title = "Nessuna evidenza disponibile: non è zero" }: { title?: string }) {
  return <span className="na" title={title}>n.d.</span>;
}
