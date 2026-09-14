"""Tenant provisioning: everything a fresh tenant needs to be usable.

A tenant without pipeline stages cannot convert leads or use the kanban, so
defaults are created here — idempotently — whenever a tenant is created
(API, setup wizard, seed).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.service_lines.models import PipelineStage, ServiceLine
from app.modules.tenancy.models import Tenant

DEFAULT_STAGES = [
    # name, position, default probability, won, lost
    ("Qualifica", 0, 10, False, False),
    ("Proposta", 1, 30, False, False),
    ("Negoziazione", 2, 60, False, False),
    ("Contratto", 3, 80, False, False),
    ("Vinta", 90, 100, True, False),
    ("Persa", 99, 0, False, True),
]

DEFAULT_SERVICE_LINES = [
    ("consulenza", "Consulenza"),
    ("servizi", "Servizi"),
    ("prodotti", "Prodotti"),
]


def provision_defaults(db: Session, tenant: Tenant,
                       service_lines: list[tuple[str, str]] | None = None) -> None:
    """Create default pipeline stages and service lines if the tenant has none."""
    has_stages = db.scalar(
        select(PipelineStage.id).where(PipelineStage.tenant_id == tenant.id).limit(1))
    if has_stages is None:
        for name, pos, prob, won, lost in DEFAULT_STAGES:
            db.add(PipelineStage(tenant_id=tenant.id, name=name, position=pos,
                                 default_probability=prob, is_won=won, is_lost=lost))
    has_lines = db.scalar(
        select(ServiceLine.id).where(ServiceLine.tenant_id == tenant.id).limit(1))
    if has_lines is None:
        for i, (code, name) in enumerate(service_lines or DEFAULT_SERVICE_LINES):
            db.add(ServiceLine(tenant_id=tenant.id, code=code, name=name, sort_order=i))
    db.flush()
