import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SearchHit } from "../api/types";
import { useAuth } from "../auth/AuthContext";

function ProsperyaMark() {
  // Simplified "10 leve" mark: node ring around a P.
  const nodes = ["#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A",
                 "#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A"];
  return (
    <svg width="34" height="34" viewBox="0 0 512 512" aria-hidden="true">
      <rect width="512" height="512" rx="112" fill="#111a1c" />
      <g opacity="0.95">
        {nodes.map((c, i) => {
          const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
          return <circle key={i} cx={256 + Math.cos(a) * 165} cy={256 + Math.sin(a) * 165} r="52" fill={c} />;
        })}
      </g>
      <circle cx="256" cy="256" r="92" fill="#111a1c" stroke="#ffffff" strokeOpacity="0.18" strokeWidth="3" />
      <text x="256" y="290" fill="#fff" fontFamily="Arial, sans-serif" fontSize="104" fontWeight="700" textAnchor="middle">P</text>
    </svg>
  );
}

const NAV: { label?: string; items: { to: string; icon: string; label: string }[] }[] = [
  { items: [{ to: "/", icon: "◈", label: "Panoramica" }] },
  {
    label: "Commerciale",
    items: [
      { to: "/leads", icon: "◇", label: "Lead" },
      { to: "/pipeline", icon: "▤", label: "Pipeline" },
    ],
  },
  {
    label: "Anagrafiche",
    items: [
      { to: "/companies", icon: "▦", label: "Aziende" },
      { to: "/contacts", icon: "◉", label: "Contatti" },
    ],
  },
  {
    label: "Operativo",
    items: [{ to: "/tasks", icon: "☑", label: "Attività" }],
  },
  {
    label: "Amministrazione",
    items: [{ to: "/billing", icon: "€", label: "Fatturazione" }],
  },
];

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const timer = useRef<ReturnType<typeof setTimeout>>();

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
    const path = { company: `/companies/${h.id}`, contact: `/contacts`, lead: `/leads`, opportunity: `/pipeline` }[h.type];
    navigate(path);
  };

  return (
    <div className="search">
      <input
        className="input"
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

export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="shell">
      <aside className="shell__sidebar">
        <div className="shell__brand">
          <ProsperyaMark />
          <div>
            <div className="shell__brand-name">PROSPERYA</div>
            <div className="shell__brand-sub">CRM · Regia operativa</div>
          </div>
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
                  <span className="nav__icon">{item.icon}</span>
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="shell__user">
          <div>
            <div className="shell__user-name">{user?.full_name}</div>
            <div className="shell__user-role">{user?.role}</div>
          </div>
          <button
            className="btn btn--ghost btn--sm"
            style={{ color: "#cfd6cd", borderColor: "#3a4d52" }}
            onClick={() => { logout(); navigate("/login"); }}
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
