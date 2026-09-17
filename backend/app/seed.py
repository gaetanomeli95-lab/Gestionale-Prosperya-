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
        # Own idempotency keys: these run on existing databases too.
        _seed_fixed_costs(db, tenant_id=tid, company=demo_company, actor=consultant)
        _seed_classification(db, tenant_id=tid, company=demo_company, actor=consultant)
        _seed_treasury(db, tenant_id=tid, company=demo_company, actor=consultant)
        _seed_fiscal(db, tenant_id=tid, company=demo_company, actor=consultant)
        _seed_controlling(db, tenant_id=tid, company=demo_company, actor=consultant)
        _seed_funding(db, tenant_id=tid, company=demo_company, actor=consultant)

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


def _seed_fixed_costs(db, *, tenant_id, company, actor) -> None:
    """A structurally fixed cost, so contribution margin and break-even have
    both natures to work with. Idempotent through its own import key."""
    import csv
    import io

    from app.modules.management import service as mgmt

    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(mgmt.CSV_HEADERS)
    for month in range(1, 7):
        writer.writerow([f"DEMO-FITTIZIO-2026-{month:02}-F", f"2026-{month:02}-01",
                         "cost", "Struttura e affitti demo", "8000", "EUR"])
    mgmt.import_actuals(
        db, tenant_id=tenant_id, company=company, actor_id=actor.id,
        filename="demo-costi-fissi-2026.csv", csv_content=stream.getvalue(),
        idempotency_key="demo-finance-fixed-v1", origin="fictional_demo")


def _seed_classification(db, *, tenant_id, company, actor) -> None:
    """Classify the demo categories so contribution margin and break-even are
    calculable, and attribute them to two cost centres.

    Idempotent: only categories still unclassified are touched.
    """
    import uuid as _uuid

    from app.modules.management import service as mgmt
    from app.modules.management.models import CostCenter

    centers = {row.code: row for row in db.scalars(
        select(CostCenter).where(CostCenter.tenant_id == tenant_id,
                                 CostCenter.company_id == company.id)).all()}
    for code, name in (("CDC-PROD", "Produzione e delivery (demo)"),
                       ("CDC-ADM", "Struttura e amministrazione (demo)")):
        if code not in centers:
            created = mgmt.create_cost_center(db, tenant_id=tenant_id, company=company,
                                              actor_id=actor.id, code=code, name=name)
            centers[code] = db.get(CostCenter, _uuid.UUID(created["id"]))

    # Fictional but coherent: operating costs vary with volumes, rent does not.
    plan = {
        "Costi demo": ("variable", "CDC-PROD"),
        "Struttura e affitti demo": ("fixed", "CDC-ADM"),
        "Vendite demo": (None, "CDC-PROD"),
    }
    listing = mgmt.list_categories(db, tenant_id=tenant_id, company_id=company.id)
    for category in listing["categories"]:
        target = plan.get(category["name"])
        if target is None or category["cost_nature"] is not None:
            continue
        nature, center_code = target
        if nature is None and category["cost_center_id"] is not None:
            continue
        mgmt.classify_category(
            db, tenant_id=tenant_id, company=company, actor_id=actor.id,
            category_id=_uuid.UUID(category["id"]), cost_nature=nature,
            cost_center_id=centers[center_code].id)


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


def _seed_fiscal(db, *, tenant_id, company, actor) -> None:
    """Fictional fiscal scenario for the demo company (monthly VAT payer).

    Deterministic and idempotent: the whole block is guarded by the presence
    of the `DEMO-IVA-` source refs, and every write inside goes through the
    same idempotent service functions the API uses. The scenario exercises
    the full chain — entries → settlement → human validation → deadline →
    treasury cash obligation — plus the review path:

    * July 2026: validated settlement, payable 3300.00 → due 20/08/2026
      (August deferral), already overdue at demo time → critical signal;
    * August 2026: validated settlement, payable 1540.00 → due 16/09/2026,
      upcoming → info signal;
    * September 2026: validated settlement, payable 990.00 → due 16/10/2026,
      a day the demo cash forecast projects as negative → liquidity-risk
      cross signal;
    * October 2026: open entries, one purchase awaiting deductibility
      review → data-quality signal.
    """
    from datetime import date

    from app.modules.fiscal import rules_seed
    from app.modules.fiscal import service as fiscal
    from app.modules.fiscal.models import VatEntry

    # Rule sets are jurisdiction-level reference data: materialise them first.
    rules_seed.ensure_rule_sets(db)

    if db.scalar(select(VatEntry).where(
            VatEntry.tenant_id == tenant_id, VatEntry.company_id == company.id,
            VatEntry.source_ref.like("DEMO-IVA-%"))):
        return

    def entry(direction, competence, taxable, vat, ref, **kw):
        fiscal.record_vat_entry(
            db, tenant_id=tenant_id, company=company, actor_id=actor.id,
            direction=direction, competence_date=date.fromisoformat(competence),
            taxable_amount=taxable, vat_amount=vat, source_ref=ref, **kw)

    # --- July 2026: payable 3300.00, validated ---------------------------
    entry("sale", "2026-07-08", "20000.00", "4400.00", "DEMO-IVA-07-S1",
          vat_rate="22", document_number="FT 71/2026",
          counterparty_name="Cliente Rossi S.p.A.")
    entry("sale", "2026-07-21", "5000.00", "1100.00", "DEMO-IVA-07-S2",
          vat_rate="22", document_number="FT 74/2026",
          counterparty_name="Beta Servizi S.r.l.")
    entry("purchase", "2026-07-10", "10000.00", "2200.00", "DEMO-IVA-07-P1",
          vat_rate="22", deductible=True, document_number="ACQ 310/2026",
          counterparty_name="Fornitore Sandbox S.p.A.")
    july = fiscal.calculate_settlement(db, tenant_id=tenant_id, company=company,
                                       actor_id=actor.id, year=2026, period_no=7,
                                       frequency="monthly")
    fiscal.validate_settlement(db, tenant_id=tenant_id, company=company,
                               actor_id=actor.id,
                               settlement_id=uuid.UUID(july["id"]),
                               note="Liquidazione demo validata (scenario sandbox).")

    # --- August 2026: payable 1540.00, validated -------------------------
    entry("sale", "2026-08-04", "7000.00", "1540.00", "DEMO-IVA-08-S1",
          vat_rate="22", document_number="FT 80/2026",
          counterparty_name="Mariani Costruzioni S.r.l.")
    entry("purchase", "2026-08-06", "0.00", "0.00", "DEMO-IVA-08-P1",
          vat_rate="22", deductible=True, document_number="ACQ 322/2026",
          counterparty_name="Fornitore Sandbox S.p.A.")
    august = fiscal.calculate_settlement(db, tenant_id=tenant_id, company=company,
                                         actor_id=actor.id, year=2026, period_no=8,
                                         frequency="monthly")
    fiscal.validate_settlement(db, tenant_id=tenant_id, company=company,
                               actor_id=actor.id,
                               settlement_id=uuid.UUID(august["id"]),
                               note="Liquidazione demo validata (scenario sandbox).")

    # --- September 2026: payable 990.00, validated -----------------------
    # Due 16/10/2026 — inside the horizon where the demo forecast is already
    # negative, so the cockpit raises the liquidity-vs-obligation signal.
    entry("sale", "2026-09-03", "6000.00", "1320.00", "DEMO-IVA-09-S1",
          vat_rate="22", document_number="FT 88/2026",
          counterparty_name="Cliente Rossi S.p.A.")
    entry("purchase", "2026-09-09", "1500.00", "330.00", "DEMO-IVA-09-P1",
          vat_rate="22", deductible=True, document_number="ACQ 340/2026",
          counterparty_name="Fornitore Sandbox S.p.A.")
    september = fiscal.calculate_settlement(db, tenant_id=tenant_id, company=company,
                                            actor_id=actor.id, year=2026, period_no=9,
                                            frequency="monthly")
    fiscal.validate_settlement(db, tenant_id=tenant_id, company=company,
                               actor_id=actor.id,
                               settlement_id=uuid.UUID(september["id"]),
                               note="Liquidazione demo validata (scenario sandbox).")

    # --- October 2026: open period, one entry awaiting review ------------
    entry("sale", "2026-10-02", "4500.00", "990.00", "DEMO-IVA-10-S1",
          vat_rate="22", document_number="FT 95/2026",
          counterparty_name="Beta Servizi S.r.l.")
    entry("purchase", "2026-10-05", "1500.00", "330.00", "DEMO-IVA-10-P1",
          vat_rate="22", document_number="ACQ 355/2026",
          counterparty_name="Fornitore Sandbox S.p.A.",
          notes="Detraibilità da confermare: veicolo aziendale ad uso promiscuo (demo).")


def _seed_controlling(db, *, tenant_id, company, actor) -> None:
    """Fictional controlling scenario for the demo company.

    Deterministic and idempotent: guarded by the facility name, every write
    goes through the same service functions the API uses, and dates are
    relative to today so the early-warning signals stay meaningful:

    * "Mutuo ipotecario (demo)": two instalments already paid, one scheduled
      and overdue → fires EW-FIN-OVERDUE (critical), six future monthly
      instalments → feed the prospective DSCR and the 12-month continuity;
    * "Leasing attrezzature (demo)": small quarterly schedule → second
      facility for the debt-service view;
    * detection runs once so the alert lifecycle is visible in the UI.
    """
    from datetime import timedelta

    from app.modules.controlling import rules_seed
    from app.modules.controlling import service as controlling
    from app.modules.controlling.models import DebtFacility
    from app.shared.mixins import today as utc_today

    # Early-warning rules are jurisdiction-level reference data: load first.
    rules_seed.ensure_rules(db, tenant_id=tenant_id)

    if db.scalar(select(DebtFacility).where(
            DebtFacility.tenant_id == tenant_id,
            DebtFacility.company_id == company.id,
            DebtFacility.name == "Mutuo ipotecario (demo)")):
        return

    today = utc_today()

    def day(offset: int):
        return today + timedelta(days=offset)

    mortgage = controlling.create_facility(
        db, tenant_id=tenant_id, company=company, actor_id=actor.id,
        name="Mutuo ipotecario (demo)", facility_type="mortgage",
        lender_name="Banca Sandbox (simulata)", outstanding_principal="180000.00",
        notes="Scenario fittizio: piano di ammortamento inserito manualmente.")
    fid = uuid.UUID(mortgage["id"])

    # Two paid instalments, one overdue scheduled, six upcoming.
    schedule = [(-60, "paid"), (-30, "paid"), (-10, None),
                (20, None), (50, None), (80, None),
                (110, None), (140, None), (170, None)]
    for no, (offset, state) in enumerate(schedule, start=1):
        line = controlling.add_instalment(
            db, tenant_id=tenant_id, company=company, actor_id=actor.id,
            facility_id=fid, instalment_no=no, due_date=day(offset),
            principal="2400.00", interest="350.00")
        if state == "paid":
            controlling.settle_instalment(
                db, tenant_id=tenant_id, company=company, actor_id=actor.id,
                line_id=uuid.UUID(line["id"]), action="paid",
                settled_on=day(offset), note="Rata demo regolarmente versata.")

    leasing = controlling.create_facility(
        db, tenant_id=tenant_id, company=company, actor_id=actor.id,
        name="Leasing attrezzature (demo)", facility_type="leasing",
        lender_name="Leasing Sandbox S.p.A.", outstanding_principal="24000.00",
        notes="Scenario fittizio: canoni trimestrali.")
    lid = uuid.UUID(leasing["id"])
    for no, offset in enumerate((30, 120, 210), start=1):
        controlling.add_instalment(
            db, tenant_id=tenant_id, company=company, actor_id=actor.id,
            facility_id=lid, instalment_no=no, due_date=day(offset),
            principal="1900.00", interest="180.00")

    # One detection pass so the alert lifecycle is visible immediately.
    controlling.run_detection(db, tenant_id=tenant_id, company=company,
                              actor_id=actor.id)


def _seed_funding(db, *, tenant_id, company, actor) -> None:
    """Funding core seed: verified reference data + a declared profile.

    Reference data (authorities, de minimis regime, four real-world-shaped
    programmes) is idempotent by (code, version). The demo company gets a
    declared funding profile and one de minimis aid so the deterministic
    engine has facts to evaluate — nothing is fabricated.
    """
    from datetime import timedelta
    from decimal import Decimal

    from app.modules.funding import service as funding
    from app.modules.funding.models import FundingCompanyProfile
    from app.modules.funding.seed_data import sync_reference_data
    from app.shared.mixins import today as utc_today

    sync_reference_data(db, tenant_id=tenant_id)

    if db.scalar(select(FundingCompanyProfile).where(
            FundingCompanyProfile.tenant_id == tenant_id,
            FundingCompanyProfile.company_id == company.id)):
        return

    today = utc_today()
    funding.upsert_profile(
        db, tenant_id=tenant_id, company=company,
        payload={
            "incorporated_on": today - timedelta(days=365 * 4),
            "is_startup": False,
            "is_innovative_startup": False,
            "female_ownership_pct": Decimal("60.00"),
            "youth_ownership_pct": None,
            "project_region": "Sicilia",
            "project_location": "Catania",
            "single_undertaking_known": True,
            "aid_history_complete": True,
            "notes": "Profilo dichiarato a fini dimostrativi.",
        })
    funding.add_company_aid(
        db, tenant_id=tenant_id, company=company,
        payload={
            "programme_label": "Voucher digitalizzazione (demo)",
            "authority": "Camera di Commercio (demo)",
            "regime_code": "DE_MINIMIS",
            "granted_on": today - timedelta(days=400),
            "amount": Decimal("10000.00"),
            "reference": "DEMO-AID-001",
            "source": "seed",
            "status": "declared",
        })


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
