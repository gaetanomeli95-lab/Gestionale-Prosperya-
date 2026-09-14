# PROSPERYA CRM

Internal CRM and operations platform for **Prosperya S.r.l.** (P.IVA 07415020820), a business advisory firm based in Altavilla Milicia (Palermo). It replaces TeamSystem as the firm's operational backbone for client registry, pipeline, engagements, funding programmes (*bandi*), deadlines, and documents.

TeamSystem is the functional benchmark, **not** a blueprint: every feature is redesigned for Prosperya's actual workflows rather than cloned. See `docs/MASTER_SPEC.md` for the canonical specification and `docs/DECISIONS.md` for the architecture decision log.

## Architecture summary

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2.x (synchronous), Pydantic v2, Alembic. Modular monolith: one deployable, one schema, one domain per module under `backend/app/modules/<domain>` (each with `models.py`, `schemas.py`, `service.py`, `router.py`).
- **Database** — PostgreSQL 16 via `psycopg` (production target). SQLite is supported **only** as a local dev/test fallback because the dev machine has no Docker; `docker-compose.yml` is provided for the real setup.
- **Frontend** — Vite + React 18 + TypeScript, React Router, TanStack Query v5, react-hook-form + zod. No UI kit: a custom Prosperya component system driven by CSS custom-property tokens (`frontend/src/design-system/tokens.css`), documented in `docs/BRAND_SYSTEM.md`.
- **Auth** — Email + password → short-lived JWT access token (PyJWT); refresh token in an httpOnly cookie per design (hardening deferred to Phase 5, see ADR-004). Passwords hashed with argon2id via pwdlib. Roles: `admin`, `management`, `consultant`, `backoffice`, `readonly`.

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.12+ | backend |
| Node.js 20+ | frontend |
| Docker + Docker Compose | optional — only for the PostgreSQL-backed setup |

## Quickstart A — local, no Docker (SQLite fallback)

```powershell
# 1. Backend environment
python -m venv .venv
.venv\Scripts\Activate.ps1            # Unix: source .venv/bin/activate
pip install -r backend\requirements.txt

# 2. Configure
copy .env.example .env                # Unix: cp .env.example .env
# ensure .env contains: DATABASE_URL=sqlite:///./dev.db

# 3. Schema + seed
cd backend
alembic upgrade head                  # or: python -m app.db init
python -m app.seed                    # creates roles, admin user, ref data

# 4. Run API (http://localhost:8000, docs at /docs)
uvicorn app.main:app --reload

# 5. Frontend (new terminal, http://localhost:5173)
cd frontend
npm install
npm run dev                           # Vite proxies /api -> http://localhost:8000
```

### Seed credentials

| User | Password | Role |
|---|---|---|
| `admin@prosperya.it` | `prosperya-admin-dev` | admin |

The seed password is a development default; override it with `SEED_ADMIN_PASSWORD` in `.env` and never reuse it outside local dev.

## Quickstart B — Docker (PostgreSQL 16)

```powershell
docker compose up --build
```

Compose starts PostgreSQL 16, runs `alembic upgrade head`, seeds the database, and serves the API on `:8000` and the frontend on `:5173`. `DATABASE_URL` is injected by Compose; no `.env` edit is needed for the database.

## Tests

```powershell
# Backend (from backend/, venv active)
pytest                                # unit + domain + API tests
pytest -m integration                 # DB-integration tests (SQLite OK locally)

# Frontend (from frontend/)
npm run test                          # component tests (Vitest)
npm run test:e2e                      # Playwright E2E (requires running stack)
npm run lint && npm run typecheck
```

The acceptance gate for each phase is defined in `docs/TEST_PLAN.md`.

## Repository layout

```
Gestionale prosperya/
├── README.md                     ← you are here
├── CHANGELOG.md
├── docker-compose.yml            ← PostgreSQL 16 + backend + frontend
├── .env.example                  ← all env vars documented in docs/DEPLOYMENT.md
├── docs/                         ← full documentation set (start with MASTER_SPEC.md)
│   ├── MASTER_SPEC.md            canonical product spec + phase roadmap
│   ├── DISCOVERY.md              business analysis, workflows, entity map, risks
│   ├── ARCHITECTURE.md           modular monolith, layering, conventions
│   ├── DATA_MODEL.md             entity-by-entity schema reference
│   ├── BRAND_SYSTEM.md           design tokens + component specs
│   ├── UX_RULES.md               density, record anatomy, states, a11y
│   ├── TEAMSYSTEM_BENCHMARK.md   benchmark framework + analysis template
│   ├── SECURITY.md               auth, RBAC matrix, GDPR-aware notes
│   ├── IMPORT_STRATEGY.md        11-step CSV/XLSX/TeamSystem import pipeline
│   ├── AI_ARCHITECTURE.md        feature-flagged, human-in-the-loop AI design
│   ├── TEST_PLAN.md              test pyramid + acceptance gates
│   ├── DEPLOYMENT.md             environments, env vars, backups, rollback
│   └── DECISIONS.md              ADR log (ADR-001 … ADR-008)
├── backend/
│   ├── requirements.txt
│   ├── alembic/                  migrations
│   └── app/
│       ├── main.py               FastAPI app, middleware, router registration
│       ├── core/                 config, security, db session, errors, logging
│       ├── db/                   engine, base, init helpers
│       ├── seed.py               dev seed (roles, admin, ref data)
│       └── modules/<domain>/     models.py · schemas.py · service.py · router.py
└── frontend/
    ├── package.json · vite.config.ts
    └── src/
        ├── design-system/        tokens.css + Prosperya components
        ├── features/<domain>/    pages, forms, hooks per module
        ├── api/                  typed client, query keys
        └── routes/               React Router tree
```

## Documentation index

Start at `docs/MASTER_SPEC.md`, then `docs/ARCHITECTURE.md` and `docs/DATA_MODEL.md` before touching code. `docs/DECISIONS.md` records *why* things are the way they are — read it before proposing changes to any decision listed there.
