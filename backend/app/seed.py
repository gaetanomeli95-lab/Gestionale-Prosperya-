"""Development seed data. Clearly labelled demo data — never run against a
production database. Usage: python -m app.seed
"""
import sys

from sqlalchemy import select

from app.config import get_settings
from app.core.rbac import Role
from app.core.security import hash_password
from app.db import Base, SessionLocal, engine
from app.modules.companies.models import (
    Company,
    CompanySizeBand,
    CompanyStatus,
    LifecycleStage,
)
from app.modules.contacts.models import CompanyContact, Contact
from app.modules.leads.models import Lead, LeadPriority, LeadSource
from app.modules.opportunities.models import Opportunity
from app.modules.service_lines.models import PipelineStage, ServiceLine
from app.modules.tasks.models import Task, TaskPriority
from app.modules.users.models import User

SERVICE_LINES = [
    ("startup", "Start Up"),
    ("finanza-agevolata", "Finanza Agevolata"),
    ("advisory", "Advisory"),
    ("governance", "Governance e controllo"),
    ("growth-factors", "Growth Factors"),
    ("business-planning", "Business Planning"),
    ("internazionalizzazione", "Internazionalizzazione"),
]

STAGES = [
    ("Qualifica", 0, 10),
    ("Proposta", 1, 30),
    ("Negoziazione", 2, 60),
    ("Contratto", 3, 80),
]


def seed(db) -> None:
    settings = get_settings()

    if not db.scalar(select(User).where(User.email == settings.seed_admin_email)):
        db.add(User(
            email=settings.seed_admin_email,
            full_name="Amministratore Prosperya",
            hashed_password=hash_password(settings.seed_admin_password),
            role=Role.ADMIN,
        ))

    consultant = db.scalar(select(User).where(User.email == "consulente@prosperya.it"))
    if consultant is None:
        consultant = User(
            email="consulente@prosperya.it",
            full_name="Maria Consulente (demo)",
            hashed_password=hash_password("prosperya-demo-dev"),
            role=Role.CONSULTANT,
        )
        db.add(consultant)
        db.flush()

    lines = {}
    for i, (code, name) in enumerate(SERVICE_LINES):
        sl = db.scalar(select(ServiceLine).where(ServiceLine.code == code))
        if sl is None:
            sl = ServiceLine(code=code, name=name, sort_order=i)
            db.add(sl)
            db.flush()
        lines[code] = sl

    stages = []
    for name, pos, prob in STAGES:
        st = db.scalar(select(PipelineStage).where(PipelineStage.name == name))
        if st is None:
            st = PipelineStage(name=name, position=pos, default_probability=prob)
            db.add(st)
            db.flush()
        stages.append(st)
    if not db.scalar(select(PipelineStage).where(PipelineStage.is_won.is_(True))):
        db.add(PipelineStage(name="Vinta", position=90, default_probability=100, is_won=True))
        db.add(PipelineStage(name="Persa", position=99, default_probability=0, is_lost=True))

    if not db.scalar(select(Company).where(Company.vat_number == "01234567890")):
        demo = Company(
            legal_name="Azienda Demo Siciliana S.r.l.",
            vat_number="01234567890",
            tax_code="01234567890",
            legal_form="S.r.l.",
            ateco_code="62.02.00",
            industry="Consulenza informatica",
            size_band=CompanySizeBand.SMALL,
            revenue_eur=1_800_000,
            employee_count=18,
            country="Italia",
            region="Sicilia",
            city="Palermo",
            email="info@demo.example",
            phone="+39 091 000000",
            source="seed",
            status=CompanyStatus.CUSTOMER,
            lifecycle_stage=LifecycleStage.ACTIVE,
            tags=["demo"],
            owner_id=consultant.id,
        )
        db.add(demo)
        db.flush()

        person = Contact(
            first_name="Giuseppe", last_name="Rossi (demo)",
            email="giuseppe.rossi@demo.example", phone="+39 333 0000000",
            role_title="Amministratore", owner_id=consultant.id,
        )
        db.add(person)
        db.flush()
        db.add(CompanyContact(company_id=demo.id, contact_id=person.id, is_primary=True,
                              relationship_role="Decision maker"))

        db.add(Opportunity(
            title="Azienda Demo — Growth Factors assessment",
            company_id=demo.id, contact_id=person.id,
            service_line_id=lines["growth-factors"].id,
            stage_id=stages[1].id, owner_id=consultant.id,
            expected_value_eur=12000, probability=30,
            source="referral",
        ))
        db.add(Task(
            title="Preparare proposta Growth Factors (demo)",
            owner_id=consultant.id, priority=TaskPriority.HIGH,
            entity_type="company", entity_id=demo.id,
        ))

    if not db.scalar(select(Lead).where(Lead.company_name == "Startup Esempio")):
        db.add(Lead(
            company_name="Startup Esempio",
            contact_name="Anna Bianchi", email="anna@startup-esempio.example",
            source=LeadSource.WEBSITE, priority=LeadPriority.HIGH,
            interest="Finanza agevolata — contributi a fondo perduto",
            service_line_id=lines["finanza-agevolata"].id,
            owner_id=consultant.id,
        ))

    db.commit()


def main() -> None:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to seed in production.", file=sys.stderr)
        sys.exit(1)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    print(f"Seed complete. Login: {settings.seed_admin_email} / {settings.seed_admin_password}")


if __name__ == "__main__":
    main()
