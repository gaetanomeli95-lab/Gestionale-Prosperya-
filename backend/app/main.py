import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.errors import register_error_handlers
from app.modules.activities.router import router as timeline_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.modules.companies.router import router as companies_router
from app.modules.contacts.router import router as contacts_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.leads.router import router as leads_router
from app.modules.notes.router import router as notes_router
from app.modules.opportunities.router import router as opportunities_router
from app.modules.search.router import router as search_router
from app.modules.service_lines.router import router as service_lines_router
from app.modules.tasks.router import router as tasks_router
from app.modules.users.router import router as users_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

settings = get_settings()

app = FastAPI(
    title="Prosperya CRM API",
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
    allow_headers=["Authorization", "Content-Type"],
)

API = "/api/v1"
for r in (
    auth_router, users_router, companies_router, contacts_router, leads_router,
    opportunities_router, service_lines_router, tasks_router, notes_router,
    timeline_router, search_router, dashboard_router, audit_router,
    billing_router,
):
    app.include_router(r, prefix=API)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": settings.app_name}
