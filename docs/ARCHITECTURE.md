# ARCHITECTURE — PROSPERYA CRM

## 1. Modular monolith (ADR-001)

One FastAPI application, one PostgreSQL schema, one deployable. Domains are isolated as **modules** under `backend/app/modules/<domain>/`. This is the right size for a single-tenant internal tool with a small team: we get deployment simplicity and transactions across the domain, while module boundaries keep the codebase from congealing.

**Module contract** — each module contains exactly:

```
backend/app/modules/<domain>/
├── __init__.py
├── models.py      # SQLAlchemy 2.x mapped models (module-owned tables only)
├── schemas.py     # Pydantic v2 request/response schemas
├── service.py     # all business logic; the only place that queries module tables
└── router.py      # FastAPI APIRouter: HTTP parsing → service → response
```

**Boundaries:**
- A module's tables are created/queried **only** inside its `service.py`.
- Other modules may `from app.modules.<domain>.service import ...` and call public functions; they may not import `models.py` for querying.
- Shared infra (db session, security, errors, logging) lives in `app/core/` and is dependency-injected.
- FKs may point at another module's table (e.g. `opportunities.company_id → companies.id`) — ownership refers to *writes and queries*, not schema references.

## 2. Backend layering

```
HTTP request
  → router.py     parse/validate input (Pydantic), auth dep, RBAC dep, map errors
  → service.py    business rules, transactions, optimistic-concurrency checks,
                  writes activity_events + audit_log where required
  → models.py     ORM persistence (SQLAlchemy 2.x sync sessions)
```

Rules:
- Routers contain no business logic; services contain no HTTP concepts.
- Every mutation endpoint runs in one transaction; service functions commit, routers never do.
- Soft-deleted rows (`deleted_at IS NOT NULL`) are excluded by a default query helper — filtering by it is the service layer's job, applied via a shared `not_deleted()` clause.
- Optimistic concurrency: update endpoints on `companies`, `contacts`, `leads`, `opportunities` require the client's `version`; mismatch → `409 VERSION_CONFLICT`.

**Module registry** (Phase 0/1): `users`, `audit`, `activity`, `companies`, `contacts`, `leads`, `opportunities` (owns `pipeline_stages`), `tasks`, `notes`, `service_lines`, `documents`, `funding` (owns `funding_programmes` + `funding_applications`), `deadlines`, `search`. Phase 2+: `practices`, `calendar`, `dashboards`, `eligibility`, `assessments`, `warnings`, `imports`, `ai`.

## 3. Frontend structure

```
frontend/src/
├── design-system/
│   ├── tokens.css          # all --pys-* custom properties (BRAND_SYSTEM.md)
│   └── components/         # Button, Input, Table, Card, Alert, Badge, …
├── api/
│   ├── client.ts           # fetch wrapper: auth header, error envelope handling
│   └── <domain>.ts         # typed endpoints + TanStack Query hooks per module
├── features/<domain>/      # pages, forms, columns, domain hooks
├── routes/                 # React Router tree, lazy-loaded per feature
├── auth/                   # token store, guards, role checks
└── lib/                    # formatting, dates, zod schemas shared with forms
```

- Data fetching only through TanStack Query; no ad-hoc `fetch` in components.
- Forms: react-hook-form + zod; zod schemas mirror backend `schemas.py` field names (snake_case on the wire).
- No UI kit. All styling via `--pys-*` tokens; component variants defined in `BRAND_SYSTEM.md`.

## 4. Auth & RBAC flow

```
POST /api/auth/login {email, password}
  → verify argon2id hash (pwdlib)
  → issue JWT access token (HS256, 15 min) — sub=user_id, role claim
  → (Phase 5) refresh token in httpOnly Secure SameSite=Lax cookie

Request: Authorization: Bearer <jwt>
  → auth dependency decodes, loads user, attaches to request context
  → RBAC dependency: require_role("management", "admin") or capability check
  → router → service
```

- Roles: `admin` ⊃ `management` ⊃ `consultant`; `backoffice` is a parallel track (documents/deadlines/imports focus); `readonly` can `GET` only.
- RBAC enforced **server-side** on every endpoint; the frontend hides UI it can't use but never trusts that as security.
- Audit: login success/failure, permission denials on sensitive endpoints, and all mutations are written to `audit_log` with actor, IP, user-agent (ADR-007).

## 5. Error handling convention

Single error envelope for every non-2xx response:

```json
{
  "error": {
    "code": "COMPANY_NOT_FOUND",
    "message": "The requested company does not exist or was deleted.",
    "details": { "company_id": "…" }
  }
}
```

- `code`: `SCREAMING_SNAKE` — stable, machine-readable, namespaced by domain (`AUTH_INVALID_CREDENTIALS`, `VERSION_CONFLICT`, `IMPORT_INVALID_FILE`).
- `message`: user-safe, presentable as-is; never contains stack traces, SQL, or internals.
- HTTP status mapping: 400 validation-shape, 401 unauthenticated, 403 unauthorized, 404 missing, 409 conflict (`VERSION_CONFLICT`, `DUPLICATE_VAT_NUMBER`), 422 field validation (Pydantic, `details.fields`), 500 `INTERNAL_ERROR`.
- Backend raises domain exceptions (`NotFoundError`, `ConflictError`, `ForbiddenError`); a single exception handler in `app/core/errors.py` maps them to the envelope.
- Frontend `api/client.ts` parses the envelope; forms map `details.fields` onto inputs; everything else goes to the standard error state (`UX_RULES.md`).

## 6. Logging & health checks

- Structured JSON logs (`app/core/logging.py`): `ts`, `level`, `request_id`, `user_id`, `route`, `duration_ms`, `error.code`. No PII in log messages (IDs only).
- `X-Request-ID` propagated inbound or generated; echoed in response headers.
- Endpoints: `GET /health` (liveness — process up) and `GET /health/ready` (readiness — DB `SELECT 1`). Used by Compose healthchecks and deploy probes (`DEPLOYMENT.md`).

## 7. Versioning policy

- API paths are prefixed `/api/` and currently unversioned (v1 implied). Breaking changes require a `/api/v2/` mount while v1 stays live for one release — internal users only, so deprecation windows are short but nonzero.
- Schema versioning: Alembic linear history, one migration per change, `downgrade()` mandatory.
- `CHANGELOG.md` follows Keep a Changelog; every merged feature lands under `[Unreleased]`.

## 8. Extracting a module later

If a domain ever outgrows the monolith (most likely candidates: `documents` for storage scale, `imports` for heavy batch work, `ai` for provider isolation):

1. Its `service.py` is already the only public API — put it behind an internal HTTP/queue interface.
2. Move its tables to a dedicated schema/DB; replace cross-module FKs with ID references.
3. The module becomes a separate FastAPI app reusing `app/core/` as a shared package.

Design rule that keeps this cheap: **no cross-module joins in queries, no cross-module writes.** We enforce this in review, not with tooling.
