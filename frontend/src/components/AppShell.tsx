import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Building2,
  CheckSquare,
  ChevronsUpDown,
  Euro,
  Gauge,
  GitBranch,
  HandCoins,
  Landmark,
  Layers,
  Radar,
  Receipt,
  Settings,
  ShieldAlert,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
import { api, getTenantId, setTenantId } from "../api/client";
import type { SearchHit, Tenant } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const STAFF_ROLES = ["admin", "management", "consultant", "backoffice", "readonly"];

function ProsperyaMark() {
  // Simplified "10 leve" mark: node ring around a P.
  const nodes = ["#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A",
                 "#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A"];
  return (
    <svg width="36" height="36" viewBox="0 0 512 512" aria-hidden="true">
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

const NAV: { label?: string; items: { to: string; icon: typeof Gauge; label: string }[] }[] = [
  {
    items: [
      { to: "/hub", icon: Radar, label: "Control hub" },
      { to: "/", icon: Gauge, label: "Panoramica" },
    ],
  },
  {
    label: "Commerciale",
    items: [
      { to: "/leads", icon: Zap, label: "Lead" },
      { to: "/pipeline", icon: GitBranch, label: "Pipeline" },
    ],
  },
  {
    label: "Anagrafiche",
    items: [
      { to: "/companies", icon: Building2, label: "Aziende" },
      { to: "/contacts", icon: Users, label: "Contatti" },
    ],
  },
  {
    label: "Operativo",
    items: [{ to: "/tasks", icon: CheckSquare, label: "Attività" }],
  },
  {
    label: "Amministrazione",
    items: [
      { to: "/billing", icon: Euro, label: "Fatturazione" },
      { to: "/management", icon: BarChart3, label: "Controllo di gestione" },
      { to: "/treasury", icon: Landmark, label: "Tesoreria" },
      { to: "/fiscal", icon: Receipt, label: "Fisco" },
      { to: "/controlling", icon: ShieldAlert, label: "Controlling" },
      { to: "/funding", icon: HandCoins, label: "Finanza agevolata" },
    ],
  },
  {
    label: "Intelligenza",
    items: [{ to: "/assistant", icon: Sparkles, label: "AI CFO" }],
  },
  {
    label: "Sistema",
    items: [{ to: "/settings", icon: Settings, label: "Impostazioni" }],
  },
];

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    clearTimeout(timer.current);
    if (q.trim().length < 2) {
      setHits([]);
      return;
    }
    timer.current = setTimeout(() => {
      api.get<{ results: SearchHit[] }>(`/search?q=${encodeURIComponent(q)}`)
        .then((r) => { setHits(r.results); setOpen(true); })
        .catch(() => setHits([]));
    }, 250);
    return () => clearTimeout(timer.current);
  }, [q]);

  const go = (h: SearchHit) => {
    setOpen(false);
    setQ("");
    const path = { company: `/companies/${h.id}`, contact: `/contacts`, lead: `/leads`, opportunity: `/pipeline`, practice: `/practices`, document: `/documents` }[h.type];
    navigate(path);
  };

  return (
    <div className="search">
      <input
        className="input search__input"
        placeholder="Cerca aziende, contatti, P.IVA…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        aria-label="Ricerca globale"
      />
      {open && hits.length > 0 && (
        <div className="search__results">
          {hits.map((h) => (
            <a key={`${h.type}-${h.id}`} className="search__hit" onMouseDown={() => go(h)}>
              <span className="search__hit-type">{h.type}</span>
              <span>
                <div>{h.title}</div>
                {h.subtitle && <div className="muted" style={{ fontSize: "0.75rem" }}>{h.subtitle}</div>}
              </span>
            </a>
          ))}
        </div>
      )}
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
    <label className="tenant-switcher" title="Contesto tenant attivo">
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
  const current = useQuery({
    queryKey: ["tenant-current"],
    queryFn: () => api.get<Tenant & { branding?: { app_name?: string } }>("/tenants/current"),
    staleTime: 5 * 60_000,
  });
  const appName = current.data?.branding?.app_name || current.data?.display_name || "Prosperya";

  const initials = (user?.full_name ?? "")
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="shell">
      <aside className="shell__sidebar">
        <div className="shell__brand">
          <ProsperyaMark />
          <div>
            <div className="shell__brand-name" title={appName}>{appName.toUpperCase()}</div>
            <div className="shell__brand-sub">Operating platform</div>
          </div>
        </div>
        <div className="shell__tenant">
          <TenantSwitcher />
        </div>
        <nav className="shell__nav">
          {NAV.map((section, i) => (
            <div className="nav__section" key={i}>
              {section.label && <div className="nav__label">{section.label}</div>}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) => `nav__item${isActive ? " nav__item--active" : ""}`}
                >
                  <item.icon size={15} className="nav__icon" strokeWidth={1.8} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="shell__user">
          <div className="shell__avatar">{initials}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
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
          <GlobalSearch />
        </header>
        <main className="shell__content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
