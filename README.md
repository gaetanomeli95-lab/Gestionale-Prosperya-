# PROSPERYA CRM

Internal CRM and operations platform for **Prosperya S.r.l.** (P.IVA 07415020820), a business advisory firm based in Altavilla Milicia (Palermo). It replaces TeamSystem as the firm's operational backbone for client registry, pipeline, engagements, funding programmes (*bandi*), deadlines, and documents.

TeamSystem is the functional benchmark, **not** a blueprint: every feature is redesigned for Prosperya's actual workflows rather than cloned. See `docs/MASTER_SPEC.md` for the canonical specification and `docs/DECISIONS.md` for the architecture decision log.

## Architecture summary

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2.x (synchronous), Pydantic v2, Alembic. Modular monolith: one deployable, one schema, one domain per module under `backend/app/modules/<domain>` (each with `models.py`, `schemas.py`, `service.py`, `router.py`).
- **Database** — PostgreSQL 16 via `psycopg` (production target). SQLite is supported **only** as a local dev/test fallback because the dev machine has no Docker; `docker-compose.yml` is provided for the real setup.
- **Frontend** — Vite + React 18 + TypeScript, React Router, TanStack Query v5, react-hook-form + zod. No UI kit: a custom Prosperya component system driven by CSS custom-property tokens (`frontend/src/design-system/tokens.css`), documented in `docs/BRAND_SYSTEM.md`.
- **Auth** — Email + password → short-lived JWT access token (PyJWT); refresh token in an httpOnly cookie per design (hardening deferred to Phase 5, see ADR-004). Passwords hashed with argon2id via pwdlib. Roles: `admin`, `management`, `consultant`, `backoffice`, `readonly` (staff) and `client_admin`, `client_operator`, `client_readonly` (locked to their tenant).

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.12+ | backend |
| Node.js 20+ | frontend |
| Docker + Docker Compose | PostgreSQL — the production target; **recommended** |

PostgreSQL is the database the product runs on. SQLite still works as a quick
local fallback, but it hides real defects (two were found in Phase B–F only
by running PostgreSQL) — use it for a fast test loop, not to validate schema
changes. See `docs/TEST_PLAN.md`.

## Quickstart — reproducible development environment

```powershell
# 0. Clone and configure
git clone https://github.com/gaetanomeli95-lab/Gestionale-Prosperya-.git
cd Gestionale-Prosperya-
copy .env.example .env                 # Unix: cp .env.example .env
#    .env already points DATABASE_URL at the compose database below.
#    Generate a real JWT_SECRET for anything non-local:
#    python -c "import secrets; print(secrets.token_urlsafe(48))"

# 1. Start PostgreSQL 16.15 (named volume prosperya-pgdata, healthcheck)
docker compose up -d db

# 2. Backend environment
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1             # Unix: source .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock.txt   # hash-pinned lock (see docs/DEPLOYMENT.md)

# 3. Migrate + seed demo data (idempotent)
alembic upgrade head
python -m app.seed                     # admin user, reference data, demo sandbox
#    optional richer multi-company demo:
#    $env:PROSPERYA_PREVIEW="1"; python -m scripts.seed_check

# 4. Run the API (http://localhost:8000, docs at /docs)
uvicorn app.main:app --reload

# 5. Frontend (new terminal, http://localhost:5173 — Vite proxies /api to :8000)
cd frontend
npm ci
npm run dev
```

No Docker? Set `DATABASE_URL=sqlite:///./dev.db` in `.env` and skip step 1.

### Seed credentials (development only)

| User | Password | Role | Tenant |
|---|---|---|---|
| `admin@prosperya.it` | `prosperya-admin-dev` | admin | platform |
| `consulente@prosperya.it` | `prosperya-demo-dev` | consultant | platform |
| `cliente@demo.example` | `prosperya-client-dev` | client_admin | demo client (locked) |

Override with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`. The application
**refuses to start** in `ENVIRONMENT=production` with a short or placeholder
`JWT_SECRET` or a non-standard password-hash profile.

## Tests

```powershell
# Backend — fast loop on in-memory SQLite (~2 min), from backend/ with venv active
pytest
ruff check app tests alembic scripts

# Backend — the same suite on PostgreSQL (what CI runs)
$env:TEST_DATABASE_URL = "postgresql+psycopg://prosperya:prosperya-dev-only@localhost:5432/prosperya"
pytest

# Migrations round-trip + seed idempotency (any DATABASE_URL)
alembic upgrade head; alembic downgrade base; alembic upgrade head
python -m scripts.seed_check

# Frontend, from frontend/
npm run lint                           # tsc -b --noEmit
npm test                               # Vitest component tests
npm run build                          # production build
$env:E2E_PYTHON = "..\backend\.venv\Scripts\python.exe"   # Unix: ../backend/.venv/bin/python
npm run test:e2e                       # 5 Playwright smoke flows vs a disposable seeded backend
```

First E2E run: `npx playwright install chromium`.

### Reset the development environment

```powershell
docker compose down -v                 # drops the prosperya-pgdata volume
docker compose up -d db
cd backend; alembic upgrade head; python -m app.seed
```

CI (`.github/workflows/ci.yml`) runs: ruff + SQLite tests, tsc + Vitest +
build, PostgreSQL migrations empty→head→base→head + double seed + full suite,
and the Playwright flows. See `docs/TEST_PLAN.md` for the gate definition.
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
│   ├── TREASURY_ARCHITECTURE.md  scadenzario, banca (AIS), riconciliazione L1/L2, cassa
│   ├── BILLING_ARCHITECTURE.md   provider-independent billing
│   ├── AI_ARCHITECTURE.md        feature-flagged, human-in-the-loop AI design
│   ├── TEST_PLAN.md              test pyramid, dialect strategy, acceptance gates
│   ├── PROJECT_STATE_AUDIT.md    repository forensics (Phase A) + B–F outcomes
│   ├── DEPLOYMENT.md             environments, env vars, backups, rollback
│   └── DECISIONS.md              ADR log (ADR-001 … ADR-024)
├── backend/
│   ├── requirements.txt
│   ├── alembic/                  migrations
│   └── app/
│       ├── main.py               FastAPI app, middleware, router registration
│       ├── core/                 config, security, db session, errors, logging
│       ├── db/                   engine, base, init helpers
│       ├── seed.py               dev seed (roles, admin, ref data, demo sandbox)
│       ├── models_all.py         single import surface for Base.metadata
│       └── modules/<domain>/     models.py · schemas.py · service.py · router.py
│           ├── management/       controllo di gestione (consuntivi, budget)
│           ├── treasury/         scadenzario, banca, riconciliazione, cassa
│           └── cockpit/          control hub multi-azienda + CFO cockpit
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
