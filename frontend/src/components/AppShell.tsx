import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Building2,
  CheckSquare,
  ChevronsUpDown,
  Euro,
  FileText,
  FolderKanban,
  Gauge,
  GitBranch,
  HandCoins,
  Landmark,
  Layers,
  PanelLeftClose,
  PanelLeftOpen,
  Radar,
  Receipt,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  User,
  Users,
  Zap,
} from "lucide-react";
import { api, getTenantId, setTenantId } from "../api/client";
import type { SearchHit, Tenant } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const STAFF_ROLES = ["admin", "management", "consultant", "backoffice", "readonly"];

// Preview builds mark the UI; set VITE_PROSPERYA_PREVIEW=0 to hide.
const IS_PREVIEW = import.meta.env.VITE_PROSPERYA_PREVIEW !== "0";
const COLLAPSE_KEY = "pys.sidebar.collapsed";

export function ProsperyaMark({ size = 36 }: { size?: number }) {
  // Simplified "10 leve" mark: node ring around a P.
  const nodes = ["#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A",
                 "#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A"];
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true">
      <defs>
        <linearGradient id="mk-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1d3f45" />
          <stop offset="1" stopColor="#0b1416" />
        </linearGradient>
      </defs>
      <rect width="512" height="512" rx="112" fill="url(#mk-bg)" />
      <g opacity="0.95">
        {nodes.map((c, i) => {
          const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
          return <circle key={i} cx={256 + Math.cos(a) * 165} cy={256 + Math.sin(a) * 165} r="52" fill={c} />;
        })}
      </g>
      <circle cx="256" cy="256" r="92" fill="#0b1416" stroke="#ffffff" strokeOpacity="0.18" strokeWidth="3" />
      <text x="256" y="290" fill="#e9d8a6" fontFamily="Georgia, serif" fontSize="104" fontWeight="700" textAnchor="middle">P</text>
    </svg>
  );
}

type NavItem = { to: string; icon: typeof Gauge; label: string; hint?: string };

/** Navigation is organised by the question the user is asking, not by module. */
const NAV: { label?: string; items: NavItem[] }[] = [
  {
    items: [
      { to: "/hub", icon: Radar, label: "Control hub", hint: "Cosa richiede attenzione oggi" },
      { to: "/", icon: Gauge, label: "Panoramica", hint: "Sintesi commerciale e operativa" },
    ],
  },
  {
    label: "Clienti",
    items: [
      { to: "/companies", icon: Building2, label: "Aziende", hint: "Dossier cliente" },
      { to: "/contacts", icon: Users, label: "Contatti" },
      { to: "/leads", icon: Zap, label: "Lead" },
      { to: "/pipeline", icon: GitBranch, label: "Pipeline" },
    ],
  },
  {
    label: "Lavoro",
    items: [
      { to: "/tasks", icon: CheckSquare, label: "Attività" },
      { to: "/practices", icon: FolderKanban, label: "Pratiche", hint: "Lavoro bloccato o in scadenza" },
      { to: "/documents", icon: FileText, label: "Documenti", hint: "Mancanti, in scadenza, da validare" },
    ],
  },
  {
    label: "Finanza e fisco",
    items: [
      { to: "/billing", icon: Euro, label: "Fatturazione" },
      { to: "/treasury", icon: Landmark, label: "Tesoreria" },
      { to: "/management", icon: BarChart3, label: "Controllo di gestione" },
      { to: "/controlling", icon: ShieldAlert, label: "Controlling", hint: "Cosa cambia e perché" },
      { to: "/fiscal", icon: Receipt, label: "Fisco", hint: "Cosa verificare o pagare" },
      { to: "/funding", icon: HandCoins, label: "Finanza agevolata", hint: "Opportunità e requisiti" },
    ],
  },
  {
    label: "Strumenti",
    items: [
      { to: "/assistant", icon: Sparkles, label: "AI CFO" },
      { to: "/settings", icon: Settings, label: "Impostazioni" },
    ],
  },
];
const ALL_NAV = NAV.flatMap((s) => s.items);

function usePageTitle(pathname: string) {
  return useMemo(() => {
    if (pathname.startsWith("/companies/")) return { section: "Aziende", title: "Dossier azienda" };
    if (pathname.startsWith("/cockpit/")) return { section: "Control hub", title: "Cockpit CFO" };
    const exact = ALL_NAV.find((n) => n.to === pathname);
    if (exact) {
      const section = NAV.find((s) => s.items.includes(exact))?.label;
      return { section, title: exact.label };
    }
    return { section: undefined, title: "Prosperya" };
  }, [pathname]);
}

const HIT_LABEL: Record<SearchHit["type"], string> = {
  company: "Azienda", contact: "Contatto", lead: "Lead", opportunity: "Opportunità", practice: "Pratica", document: "Documento",
};
const HIT_ICON: Record<SearchHit["type"], typeof Gauge> = {
  company: Building2, contact: User, lead: Zap, opportunity: GitBranch, practice: FolderKanban, document: FileText,
};

type Cmd = { id: string; title: string; sub?: string; icon: typeof Gauge; hint?: string; run: () => void };

/** Command palette: one place to search anything and go anywhere. Ctrl/⌘+K. */
function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    if (!open) return;
    setQ(""); setHits([]); setActive(0);
    const t = setTimeout(() => inputRef.current?.focus(), 10);
    return () => clearTimeout(t);
  }, [open]);

  useEffect(() => {
    clearTimeout(timer.current);
    if (q.trim().length < 2) { setHits([]); return; }
    timer.current = setTimeout(() => {
      api.get<{ results: SearchHit[] }>(`/search?q=${encodeURIComponent(q)}`)
        .then((r) => setHits(r.results))
        .catch(() => setHits([]));
    }, 180);
    return () => clearTimeout(timer.current);
  }, [q]);

  const go = useCallback((path: string) => { onClose(); navigate(path); }, [navigate, onClose]);

  const cmds: Cmd[] = useMemo(() => {
    const hitCmds: Cmd[] = hits.map((h) => ({
      id: `${h.type}-${h.id}`,
      title: h.title,
      sub: h.subtitle ?? undefined,
      icon: HIT_ICON[h.type],
      hint: HIT_LABEL[h.type],
      run: () => go({ company: `/companies/${h.id}`, contact: "/contacts", lead: "/leads", opportunity: "/pipeline", practice: "/practices", document: "/documents" }[h.type]),
    }));
    const needle = q.trim().toLowerCase();
    const navCmds: Cmd[] = ALL_NAV
      .filter((n) => !needle || n.label.toLowerCase().includes(needle) || (n.hint ?? "").toLowerCase().includes(needle))
      .map((n) => ({ id: `nav-${n.to}`, title: n.label, sub: n.hint, icon: n.icon, hint: "Vai a", run: () => go(n.to) }));
    return [...hitCmds, ...navCmds];
  }, [hits, q, go]);

  useEffect(() => { setActive(0); }, [cmds.length, q]);

  if (!open) return null;

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, cmds.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); cmds[active]?.run(); }
    else if (e.key === "Escape") { onClose(); }
  };

  const firstNav = cmds.findIndex((c) => c.id.startsWith("nav-"));

  return (
    <div className="cmdk__backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cmdk" role="dialog" aria-label="Cerca e vai">
        <input
          ref={inputRef}
          className="cmdk__input"
          placeholder="Cerca aziende, contatti, P.IVA… oppure scrivi dove vuoi andare"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          aria-label="Ricerca globale"
        />
        <div className="cmdk__list">
          {cmds.length === 0 && <div className="cmdk__empty">Nessun risultato per “{q}”.</div>}
          {cmds.map((c, i) => (
            <div key={c.id}>
              {i === 0 && firstNav !== 0 && <div className="cmdk__group eyebrow eyebrow--muted">Risultati</div>}
              {i === firstNav && <div className="cmdk__group eyebrow eyebrow--muted">Vai a</div>}
              <a
                className={`cmdk__item${i === active ? " cmdk__item--active" : ""}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => { e.preventDefault(); c.run(); }}
              >
                <span className="cmdk__icon"><c.icon size={15} strokeWidth={1.9} /></span>
                <span>
                  <div className="cmdk__title">{c.title}</div>
                  {c.sub && <div className="cmdk__sub">{c.sub}</div>}
                </span>
                <span className="cmdk__hint">{c.hint}</span>
              </a>
            </div>
          ))}
        </div>
        <div className="cmdk__foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> naviga</span>
          <span><kbd>↵</kbd> apri</span>
          <span><kbd>esc</kbd> chiudi</span>
        </div>
      </div>
    </div>
  );
}

/** Tenant workspace selector. Staff can switch tenant context; client-role
 *  users see their tenant name read-only (server enforces the lock). */
function TenantSwitcher() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isStaff = user ? STAFF_ROLES.includes(user.role) : false;
  const [selected, setSelected] = useState<string | null>(getTenantId());

  const { data } = useQuery({
    queryKey: ["tenants"],
    queryFn: () => api.get<Tenant[]>("/tenants"),
    enabled: isStaff,
    retry: false,
  });

  if (!user) return null;
  const tenants = data ?? [];
  const current =
    tenants.find((t) => t.id === selected) ??
    tenants.find((t) => t.id === user.tenant_id) ??
    tenants[0];

  if (!isStaff || tenants.length === 0) {
    return (
      <div className="tenant-chip" title="Contesto tenant">
        <Layers size={14} />
        <span className="tenant-chip__name">Workspace cliente</span>
      </div>
    );
  }

  return (
    <label className="tenant-switcher" title="Workspace attivo">
      <Layers size={14} className="tenant-switcher__icon" />
      <select
        className="tenant-switcher__select"
        value={current?.id ?? ""}
        onChange={(e) => {
          const id = e.target.value;
          setSelected(id);
          setTenantId(id === user.tenant_id ? null : id);
          queryClient.clear();
        }}
        aria-label="Tenant attivo"
      >
        {tenants.map((t) => (
          <option key={t.id} value={t.id}>
            {t.is_platform_org ? "★ " : ""}{t.display_name}
          </option>
        ))}
      </select>
      <ChevronsUpDown size={13} className="tenant-switcher__chevron" />
    </label>
  );
}

export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const [cmdOpen, setCmdOpen] = useState(false);
  const page = usePageTitle(pathname);

  const current = useQuery({
    queryKey: ["tenant-current"],
    queryFn: () => api.get<Tenant & { branding?: { app_name?: string } }>("/tenants/current"),
    staleTime: 5 * 60_000,
  });
  const appName = current.data?.branding?.app_name || current.data?.display_name || "Prosperya";

  useEffect(() => { localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0"); }, [collapsed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmdOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => { document.title = `${page.title} · ${appName}`; }, [page.title, appName]);

  const initials = (user?.full_name ?? "")
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className={`shell${collapsed ? " shell--collapsed" : ""}`}>
      <aside className="shell__sidebar">
        <div className="shell__brand">
          <ProsperyaMark />
          <div style={{ minWidth: 0 }}>
            <div className="shell__brand-name" title={appName}>{appName.toUpperCase()}</div>
            <div className="shell__brand-sub">Operating platform</div>
          </div>
          <button
            className="shell__collapse"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Espandi menu" : "Comprimi menu"}
            title={collapsed ? "Espandi menu" : "Comprimi menu"}
          >
            {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
          </button>
        </div>
        {IS_PREVIEW && <div className="shell__preview">Preview · dati dimostrativi</div>}
        <nav className="shell__nav" aria-label="Navigazione principale">
          {NAV.map((section, i) => (
            <div className="nav__section" key={i}>
              {section.label && <div className="nav__label">{section.label}</div>}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  title={collapsed ? item.label : item.hint}
                  className={({ isActive }) => `nav__item${isActive ? " nav__item--active" : ""}`}
                >
                  <item.icon size={16} className="nav__icon" strokeWidth={1.8} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="shell__user">
          <div className="shell__avatar" title={user?.full_name}>{initials}</div>
          <div className="shell__user-meta">
            <div className="shell__user-name">{user?.full_name}</div>
            <div className="shell__user-role">{user?.role}</div>
          </div>
          <button
            className="btn btn--ghost btn--sm shell__logout"
            onClick={() => { setTenantId(null); logout(); navigate("/login"); }}
          >
            Esci
          </button>
        </div>
      </aside>
      <div className="shell__main">
        <header className="shell__topbar">
          <div className="topbar__ctx">
            {page.section && <><span className="eyebrow eyebrow--muted">{page.section}</span><span className="topbar__sep">/</span></>}
            <span className="topbar__title">{page.title}</span>
          </div>
          <div className="topbar__right">
            <button className="topbar__kbd" onClick={() => setCmdOpen(true)} aria-label="Ricerca globale">
              <Search size={15} />
              <span>Cerca o vai a…</span>
              <kbd>Ctrl K</kbd>
            </button>
            <TenantSwitcher />
            {IS_PREVIEW && <span className="topbar__preview">Preview</span>}
          </div>
        </header>
        <main className="shell__content">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
    </div>
  );
}
