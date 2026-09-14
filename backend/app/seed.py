"""Development seed data. Clearly labelled demo data — never run against a
production database. Usage: python -m app.seed
"""
import sys
import uuid

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
from app.modules.management.models import ImportBatch
from app.modules.opportunities.models import Opportunity
from app.modules.service_lines.models import PipelineStage, ServiceLine
from app.modules.tasks.models import Task, TaskPriority
from app.modules.tenancy.models import Tenant
from app.modules.tenancy.provisioning import provision_defaults
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

    # --- tenants ---------------------------------------------------------
    # The platform org tenant holds the operator's own CRM workspace.
    platform = db.scalar(select(Tenant).where(Tenant.is_platform_org.is_(True)))
    if platform is None:
        platform = Tenant(
            slug="platform", display_name="Piattaforma (operatore)",
            legal_name="Prosperya S.r.l.", is_platform_org=True,
            branding={"app_name": "Prosperya"},
        )
        db.add(platform)
        db.flush()

    demo_tenant = db.scalar(select(Tenant).where(Tenant.slug == "cliente-demo"))
    if demo_tenant is None:
        demo_tenant = Tenant(
            slug="cliente-demo", display_name="Azienda Cliente Demo S.r.l.",
            legal_name="Azienda Cliente Demo S.r.l.", vat_number="09999999999",
        )
        db.add(demo_tenant)
        db.flush()
    provision_defaults(db, demo_tenant)

    tid = platform.id

    if not db.scalar(select(User).where(User.email == settings.seed_admin_email)):
        db.add(User(
            email=settings.seed_admin_email,
            full_name="Amministratore Piattaforma",
            hashed_password=hash_password(settings.seed_admin_password),
            role=Role.ADMIN,
            tenant_id=tid,
        ))

    consultant = db.scalar(select(User).where(User.email == "consulente@prosperya.it"))
    if consultant is None:
        consultant = User(
            email="consulente@prosperya.it",
            full_name="Maria Consulente (demo)",
            hashed_password=hash_password("prosperya-demo-dev"),
            role=Role.CONSULTANT,
            tenant_id=tid,
        )
        db.add(consultant)
        db.flush()

    # A client-tenant demo user (locked to the demo client tenant).
    if not db.scalar(select(User).where(User.email == "cliente@demo.example")):
        db.add(User(
            email="cliente@demo.example",
            full_name="Paolo Cliente (demo)",
            hashed_password=hash_password("prosperya-client-dev"),
            role=Role.CLIENT_ADMIN,
            tenant_id=demo_tenant.id,
        ))

    lines = {}
    for i, (code, name) in enumerate(SERVICE_LINES):
        sl = db.scalar(
            select(ServiceLine).where(
                ServiceLine.tenant_id == tid, ServiceLine.code == code
            )
        )
        if sl is None:
            sl = ServiceLine(code=code, name=name, sort_order=i, tenant_id=tid)
            db.add(sl)
            db.flush()
        lines[code] = sl

    stages = []
    for name, pos, prob in STAGES:
        st = db.scalar(
            select(PipelineStage).where(
                PipelineStage.tenant_id == tid, PipelineStage.name == name
            )
        )
        if st is None:
            st = PipelineStage(name=name, position=pos, default_probability=prob,
                               tenant_id=tid)
            db.add(st)
            db.flush()
        stages.append(st)
    if not db.scalar(select(PipelineStage).where(
        PipelineStage.tenant_id == tid, PipelineStage.is_won.is_(True)
    )):
        db.add(PipelineStage(name="Vinta", position=90, default_probability=100,
                             is_won=True, tenant_id=tid))
        db.add(PipelineStage(name="Persa", position=99, default_probability=0,
                             is_lost=True, tenant_id=tid))

    if not db.scalar(select(Company).where(
        Company.tenant_id == tid, Company.vat_number == "01234567890"
    )):
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
            tenant_id=tid,
        )
        db.add(demo)
        db.flush()

        person = Contact(
            first_name="Giuseppe", last_name="Rossi (demo)",
            email="giuseppe.rossi@demo.example", phone="+39 333 0000000",
            role_title="Amministratore", owner_id=consultant.id, tenant_id=tid,
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
            tenant_id=tid,
        ))
        db.add(Task(
            title="Preparare proposta Growth Factors (demo)",
            owner_id=consultant.id, priority=TaskPriority.HIGH,
            entity_type="company", entity_id=demo.id, tenant_id=tid,
        ))

    # --- demo management data (append-only consuntivi + budget) -------------
    demo_company = db.scalar(select(Company).where(
        Company.tenant_id == tid, Company.vat_number == "01234567890"
    ))
    if demo_company is not None and not db.scalar(
        select(ImportBatch).where(ImportBatch.company_id == demo_company.id)
    ):
        import csv
        import io

        from app.modules.management import service as mgmt

        revenues = ["100000", "104000", "109000", "115000", "120000", "128000"]
        costs = ["62000", "64000", "65000", "67000", "69000", "72000"]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(mgmt.CSV_HEADERS)
        for month, (revenue, cost) in enumerate(zip(revenues, costs, strict=True), start=1):
            prefix = f"DEMO-FITTIZIO-2026-{month:02}"
            writer.writerow([f"{prefix}-R", f"2026-{month:02}-15", "revenue",
                             "Vendite demo", revenue, "EUR"])
            writer.writerow([f"{prefix}-C", f"2026-{month:02}-20", "cost",
                             "Costi demo", cost, "EUR"])
        mgmt.import_actuals(
            db, tenant_id=tid, company=demo_company, actor_id=consultant.id,
            filename="demo-consuntivi-2026.csv", csv_content=stream.getvalue(),
            idempotency_key="demo-finance-v1", origin="fictional_demo")
        for month in range(1, 7):
            mgmt.save_budget(db, tenant_id=tid, company=demo_company,
                             actor_id=consultant.id, year=2026, month=month,
                             revenue="105000.00", costs="75000.00")

    if demo_company is not None:
        _seed_treasury(db, tenant_id=tid, company=demo_company, actor=consultant)

    if not db.scalar(select(Lead).where(
        Lead.tenant_id == tid, Lead.company_name == "Startup Esempio"
    )):
        db.add(Lead(
            company_name="Startup Esempio",
            contact_name="Anna Bianchi", email="anna@startup-esempio.example",
            source=LeadSource.WEBSITE, priority=LeadPriority.HIGH,
            interest="Finanza agevolata — contributi a fondo perduto",
            service_line_id=lines["finanza-agevolata"].id,
            owner_id=consultant.id,
            tenant_id=tid,
        ))

    db.commit()


def _seed_treasury(db, *, tenant_id, company, actor) -> None:
    """Fictional treasury scenario for the demo company.

    Everything here is *simulated*: the bank account uses the
    `sandbox-openbanking` adapter (`is_real_institution=False`) and the
    movements are scripted, so the reconciliation engine, the aging report and
    the cash forecast can be exercised end-to-end without touching a real
    institution. Dates are relative to today so the demo stays meaningful.
    """
    from datetime import timedelta

    from app.modules.treasury import service as treasury
    from app.modules.treasury.models import BankAccount
    from app.shared.mixins import today as utc_today

    if db.scalar(select(BankAccount).where(BankAccount.tenant_id == tenant_id,
                                           BankAccount.company_id == company.id)):
        return

    today = utc_today()

    def day(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    # Scripted movements: two exact matches (one by document reference, one
    # cumulative), one fuzzy candidate, and two unmatched outflows.
    script = [
        {"id": "SBX-DEMO-001", "date": day(-12), "amount": "12200.00",
         "counterparty": "CLIENTE ROSSI SPA",
         "description": "BONIFICO INCASSO FATTURA FT 45/2026 CLIENTE ROSSI SPA"},
        {"id": "SBX-DEMO-002", "date": day(-4), "amount": "1500.00",
         "counterparty": "BETA SERVIZI SRL",
         "description": "BONIFICO BETA SERVIZI SRL SALDO PARTITE APERTE"},
        {"id": "SBX-DEMO-003", "date": day(-1), "amount": "8000.00",
         "counterparty": "MARIANI S.",
         "description": "BONIFICO DA MARIANI S. ACCONTO LAVORI"},
        {"id": "SBX-DEMO-004", "date": day(-3), "amount": "-3660.00",
         "counterparty": "FORNITORE SANDBOX SPA",
         "description": "BONIFICO FORNITORE SANDBOX SPA FATT 220/2026"},
        {"id": "SBX-DEMO-005", "date": day(-2), "amount": "-4.50",
         "description": "COMMISSIONI TENUTA CONTO"},
    ]
    account = treasury.create_account(
        db, tenant_id=tenant_id, company=company, actor_id=actor.id,
        label="Conto operativo (DEMO SANDBOX)",
        provider_key="sandbox-openbanking", provider_api_version="v1",
        provider_account_id="DEMO-SANDBOX-0001",
        bank_name="Banca Sandbox (simulata)", iban_last4="0001",
        config={"script": script, "opening_balance": "9000.00",
                "balance_date": day(-1), "label": "Conto operativo (DEMO SANDBOX)"},
    )
    treasury.sync_account(
        db, tenant_id=tenant_id, company=company, actor_id=actor.id,
        account_id=uuid.UUID(account["id"]), date_from=today - timedelta(days=90),
        date_to=today, idempotency_key="demo-bank-sync-v1")

    # Scadenzario: matched, overdue and future items — the forecast turns
    # negative because of the concentrated F24 + payroll obligations.
    treasury.import_open_items(
        db, tenant_id=tenant_id, company=company, actor_id=actor.id,
        rows=[
            {"source_ref": "DEMO-FT-45", "direction": "receivable",
             "counterparty_name": "Cliente Rossi S.p.A.", "counterparty_vat": "01111111119",
             "document_number": "FT 45/2026", "document_date": day(-40),
             "due_date": day(12), "amount": "12200.00", "category": "Vendite demo"},
            {"source_ref": "DEMO-FT-46", "direction": "receivable",
             "counterparty_name": "Beta Servizi S.r.l.", "document_number": "FT 46/2026",
             "document_date": day(-30), "due_date": day(5), "amount": "1000.00"},
            {"source_ref": "DEMO-FT-47", "direction": "receivable",
             "counterparty_name": "Beta Servizi S.r.l.", "document_number": "FT 47/2026",
             "document_date": day(-25), "due_date": day(20), "amount": "500.00"},
            {"source_ref": "DEMO-FT-40", "direction": "receivable",
             "counterparty_name": "Gamma Industrie S.p.A.", "document_number": "FT 40/2026",
             "document_date": day(-75), "due_date": day(-45), "amount": "15000.00"},
            {"source_ref": "DEMO-FT-48", "direction": "receivable",
             "counterparty_name": "Mariani Costruzioni S.r.l.", "document_number": "FT 48/2026",
             "document_date": day(-20), "due_date": day(3), "amount": "8000.00"},
            {"source_ref": "DEMO-ACQ-220", "direction": "payable",
             "counterparty_name": "Fornitore Sandbox S.p.A.", "document_number": "220/2026",
             "document_date": day(-10), "due_date": day(8), "amount": "3660.00",
             "category": "Acquisti demo"},
            {"source_ref": "DEMO-F24-09", "direction": "payable",
             "counterparty_name": "Erario (demo)", "document_number": "F24 09/2026",
             "due_date": day(16), "amount": "9500.00",
             "notes": "Importo inserito manualmente: nessun calcolo fiscale è eseguito dalla piattaforma."},
            {"source_ref": "DEMO-PAY-09", "direction": "payable",
             "counterparty_name": "Stipendi (demo)", "due_date": day(18),
             "amount": "21000.00",
             "notes": "Costo inserito manualmente: il modulo HR non è implementato."},
        ])


def main() -> None:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to seed in production.", file=sys.stderr)
        sys.exit(1)
    import app.models_all  # noqa: F401 — registers every table before create_all

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    print(f"Seed complete. Login: {settings.seed_admin_email} / {settings.seed_admin_password}")


if __name__ == "__main__":
    main()
