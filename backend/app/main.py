import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.bootstrap import frontend_dist
from app.config import get_settings
from app.core.errors import register_error_handlers
from app.modules.activities.router import router as timeline_router
from app.modules.assistant.router import router as assistant_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.modules.companies.router import router as companies_router
from app.modules.contacts.router import router as contacts_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.leads.router import router as leads_router
from app.modules.management.router import router as management_router
from app.modules.notes.router import router as notes_router
from app.modules.opportunities.router import router as opportunities_router
from app.modules.search.router import router as search_router
from app.modules.service_lines.router import router as service_lines_router
from app.modules.setup.router import router as setup_router
from app.modules.tasks.router import router as tasks_router
from app.modules.tenancy.router import router as tenancy_router
from app.modules.users.router import router as users_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

settings = get_settings()

app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
)

register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-Id"],
)

API = "/api/v1"
for r in (
    setup_router, auth_router, tenancy_router, users_router, companies_router, contacts_router,
    leads_router, opportunities_router, service_lines_router, tasks_router,
    notes_router, timeline_router, search_router, dashboard_router, audit_router,
    billing_router, management_router, assistant_router,
):
    app.include_router(r, prefix=API)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": settings.app_name}


# Serve the built frontend (SPA) when it exists — single-process deployment.
# API routes above take precedence; every other GET falls back to index.html.
_frontend_dist = frontend_dist()
if _frontend_dist.is_dir():
    _assets = _frontend_dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):  # noqa: ANN001
        if full_path.startswith(("api/", "docs", "openapi.json", "health")):
            raise HTTPException(status_code=404, detail="Not Found")
        target = _frontend_dist / full_path
        if full_path and target.is_file() and target.is_relative_to(_frontend_dist):
            return FileResponse(target)
        return FileResponse(_frontend_dist / "index.html")
