"""Preview demo dataset — multi-company story for client-validation builds.

Five companies in the platform workspace, each with a clearly different
situation so the Control Hub explains itself at a glance:

* **Litoranea Alimentari** — healthy: profitable, cash positive, no alerts.
* **Officine Meccaniche Etna** — liquidity pressure: forecast goes negative.
* **Edil Costruzioni Madonie** — fiscal obligation: validated VAT overdue.
* **Ceramiche Artistiche** — early warning: overdue debt instalment (CCII).
* **Techne Consulting** — commercial: open pipeline opportunities.

The historical "Azienda Demo Siciliana" (seed.py) remains the full-spectrum
company. Everything is deterministic, idempotent (guarded by VAT / source_ref
prefixes / facility names) and uses the same service functions as the API.
Dates are relative to today so signals stay meaningful. Never run against
production data.
"""
import io
import uuid
from csv import writer as csv_writer
from datetime import date, timedelta

from sqlalchemy import select

from app.modules.companies.models import (
    Company,
    CompanySizeBand,
    CompanyStatus,
    LifecycleStage,
)
from app.modules.contacts.models import CompanyContact, Contact
from app.modules.opportunities.models import Opportunity
from app.modules.tasks.models import Task, TaskPriority
from app.shared.mixins import today as utc_today


def _day(offset: int) -> str:
    return (utc_today() + timedelta(days=offset)).isoformat()


def _mk_company(db, *, tid, actor, vat, name, industry, city, revenue,
                employees, contact_name, contact_role) -> Company:
    co = db.scalar(select(Company).where(Company.tenant_id == tid,
                                         Company.vat_number == vat))
    if co is not None:
        return co
    co = Company(
        legal_name=name, vat_number=vat, tax_code=vat, legal_form="S.r.l.",
        industry=industry, size_band=CompanySizeBand.SMALL,
        revenue_eur=revenue, employee_count=employees, country="Italia",
        region="Sicilia", city=city, source="seed",
        status=CompanyStatus.CUSTOMER, lifecycle_stage=LifecycleStage.ACTIVE,
        tags=["preview"], owner_id=actor.id, tenant_id=tid)
    db.add(co)
    db.flush()
    first, _, last = contact_name.partition(" ")
    person = Contact(first_name=first, last_name=last or first,
                     email=f"{first.lower()}.{last.lower().replace(' ', '') or 'demo'}@example.it",
                     role_title=contact_role, owner_id=actor.id, tenant_id=tid)
    db.add(person)
    db.flush()
    db.add(CompanyContact(company_id=co.id, contact_id=person.id,
                          is_primary=True, relationship_role=contact_role))
    return co


def _actuals(db, *, tid, company, actor, key, months, fixed_monthly,
             plan) -> None:
    """Six months of consuntivi + classification so contribution margin,
    break-even and trends are computable. `months`: [(rev, var_cost), …]."""
    from app.modules.management import service as mgmt
    from app.modules.management.models import CostCenter, ImportBatch

    if db.scalar(select(ImportBatch).where(ImportBatch.company_id == company.id)):
        return
    stream = io.StringIO(newline="")
    w = csv_writer(stream, lineterminator="\n")
    w.writerow(mgmt.CSV_HEADERS)
    for m, (rev, cost) in enumerate(months, start=1):
        w.writerow([f"{key}-2026-{m:02}-R", f"2026-{m:02}-15", "revenue",
                    "Vendite", rev, "EUR"])
        w.writerow([f"{key}-2026-{m:02}-C", f"2026-{m:02}-20", "cost",
                    "Costi operativi", cost, "EUR"])
        w.writerow([f"{key}-2026-{m:02}-F", f"2026-{m:02}-01", "cost",
                    "Struttura e affitti", fixed_monthly, "EUR"])
    mgmt.import_actuals(db, tenant_id=tid, company=company, actor_id=actor.id,
                        filename=f"{key.lower()}-consuntivi-2026.csv",
                        csv_content=stream.getvalue(),
                        idempotency_key=f"{key.lower()}-v1",
                        origin="fictional_demo")
    centers = {r.code: r for r in db.scalars(
        select(CostCenter).where(CostCenter.tenant_id == tid,
                                 CostCenter.company_id == company.id)).all()}
    for code, name in (("CDC-OPS", "Operatività"), ("CDC-STR", "Struttura")):
        if code not in centers:
            c = mgmt.create_cost_center(db, tenant_id=tid, company=company,
                                        actor_id=actor.id, code=code, name=name)
            centers[code] = db.get(CostCenter, uuid.UUID(c["id"]))
    listing = mgmt.list_categories(db, tenant_id=tid, company_id=company.id)
    for cat in listing["categories"]:
        target = plan.get(cat["name"])
        if target is None or cat["cost_nature"] is not None:
            continue
        nature, cc = target
        if nature is None and cat["cost_center_id"] is not None:
            continue
        mgmt.classify_category(db, tenant_id=tid, company=company,
                               actor_id=actor.id,
                               category_id=uuid.UUID(cat["id"]),
                               cost_nature=nature,
                               cost_center_id=centers[cc].id)


def _treasury(db, *, tid, company, actor, key, balance, script, items) -> None:
    from app.modules.treasury import service as treasury
    from app.modules.treasury.models import BankAccount

    if db.scalar(select(BankAccount).where(BankAccount.tenant_id == tid,
                                           BankAccount.company_id == company.id)):
        return
    account = treasury.create_account(
        db, tenant_id=tid, company=company, actor_id=actor.id,
        label="Conto operativo (dimostrativo)",
        provider_key="sandbox-openbanking", provider_api_version="v1",
        provider_account_id=f"{key}-0001",
        bank_name="Banca dimostrativa", iban_last4="0001",
        config={"script": script, "opening_balance": balance,
                "balance_date": _day(-1),
                "label": "Conto operativo (dimostrativo)"})
    treasury.sync_account(db, tenant_id=tid, company=company, actor_id=actor.id,
                          account_id=uuid.UUID(account["id"]),
                          date_from=utc_today() - timedelta(days=90),
                          date_to=utc_today(),
                          idempotency_key=f"{key.lower()}-sync-v1")
    treasury.import_open_items(db, tenant_id=tid, company=company,
                               actor_id=actor.id, rows=items)


def _fiscal(db, *, tid, company, actor, key, period, entries,
            validate: bool) -> None:
    """VAT entries for one monthly period; optionally calculate+validate."""
    from app.modules.fiscal import rules_seed
    from app.modules.fiscal import service as fiscal
    from app.modules.fiscal.models import VatEntry

    rules_seed.ensure_rule_sets(db)
    if db.scalar(select(VatEntry).where(
            VatEntry.tenant_id == tid, VatEntry.company_id == company.id,
            VatEntry.source_ref.like(f"{key}-%"))):
        return
    for direction, comp, taxable, vat, ref, kw in entries:
        fiscal.record_vat_entry(
            db, tenant_id=tid, company=company, actor_id=actor.id,
            direction=direction, competence_date=date.fromisoformat(comp),
            taxable_amount=taxable, vat_amount=vat, source_ref=f"{key}-{ref}",
            **kw)
    if validate:
        st = fiscal.calculate_settlement(db, tenant_id=tid, company=company,
                                         actor_id=actor.id, year=2026,
                                         period_no=period, frequency="monthly")
        fiscal.validate_settlement(db, tenant_id=tid, company=company,
                                   actor_id=actor.id,
                                   settlement_id=uuid.UUID(st["id"]),
                                   note="Liquidazione validata (dati dimostrativi).")


def _debt(db, *, tid, company, actor, name, ftype, lender, outstanding,
          instalments, detect: bool) -> None:
    """`instalments`: [(due_offset, principal, interest, "paid"|None), …]."""
    from app.modules.controlling import rules_seed
    from app.modules.controlling import service as controlling
    from app.modules.controlling.models import DebtFacility

    rules_seed.ensure_rules(db, tenant_id=tid)
    if db.scalar(select(DebtFacility).where(
            DebtFacility.tenant_id == tid, DebtFacility.company_id == company.id,
            DebtFacility.name == name)):
        return
    fac = controlling.create_facility(
        db, tenant_id=tid, company=company, actor_id=actor.id, name=name,
        facility_type=ftype, lender_name=lender,
        outstanding_principal=outstanding,
        notes="Piano inserito manualmente (dati dimostrativi).")
    fid = uuid.UUID(fac["id"])
    for no, (offset, principal, interest, state) in enumerate(instalments, 1):
        line = controlling.add_instalment(
            db, tenant_id=tid, company=company, actor_id=actor.id,
            facility_id=fid, instalment_no=no,
            due_date=utc_today() + timedelta(days=offset),
            principal=principal, interest=interest)
        if state == "paid":
            controlling.settle_instalment(
                db, tenant_id=tid, company=company, actor_id=actor.id,
                line_id=uuid.UUID(line["id"]), action="paid",
                settled_on=utc_today() + timedelta(days=offset),
                note="Rata regolarmente versata.")
    if detect:
        controlling.run_detection(db, tenant_id=tid, company=company,
                                  actor_id=actor.id)


# ---------------------------------------------------------------------------
# Company stories
# ---------------------------------------------------------------------------

def _healthy(db, *, tid, actor) -> None:
    co = _mk_company(db, tid=tid, actor=actor, vat="02111111111",
                     name="Litoranea Alimentari S.r.l.",
                     industry="Produzione alimentare", city="Trapani",
                     revenue=950_000, employees=14,
                     contact_name="Salvo Ferraro", contact_role="Titolare")
    _actuals(db, tid=tid, company=co, actor=actor, key="PV-LIT",
             months=[("62000", "31000"), ("64000", "32000"), ("66000", "33000"),
                     ("68000", "33500"), ("70000", "34000"), ("72000", "35000")],
             fixed_monthly="14000",
             plan={"Costi operativi": ("variable", "CDC-OPS"),
                   "Struttura e affitti": ("fixed", "CDC-STR"),
                   "Vendite": (None, "CDC-OPS")})
    _treasury(db, tid=tid, company=co, actor=actor, key="PV-LIT",
              balance="48000.00",
              script=[{"id": "PV-LIT-001", "date": _day(-6), "amount": "18500.00",
                       "counterparty": "GDO SICILIA SPA",
                       "description": "BONIFICO INCASSO FATTURA FT 12/2026"}],
              items=[
                  {"source_ref": "PV-LIT-FT12", "direction": "receivable",
                   "counterparty_name": "GDO Sicilia S.p.A.",
                   "document_number": "FT 12/2026", "document_date": _day(-36),
                   "due_date": _day(-6), "amount": "18500.00"},
                  {"source_ref": "PV-LIT-FT15", "direction": "receivable",
                   "counterparty_name": "Ho.Re.Co. Distribuzione S.r.l.",
                   "document_number": "FT 15/2026", "document_date": _day(-10),
                   "due_date": _day(20), "amount": "9200.00"},
                  {"source_ref": "PV-LIT-ACQ31", "direction": "payable",
                   "counterparty_name": "Materie Prime Sud S.r.l.",
                   "document_number": "31/2026", "document_date": _day(-8),
                   "due_date": _day(22), "amount": "6400.00"}])
    _fiscal(db, tid=tid, company=co, actor=actor, key="PV-LIT", period=8,
            entries=[("sale", "2026-08-10", "30000.00", "6600.00", "S1",
                      {"vat_rate": "22", "document_number": "FT 14/2026",
                       "counterparty_name": "GDO Sicilia S.p.A."}),
                     ("purchase", "2026-08-12", "12000.00", "2640.00", "P1",
                      {"vat_rate": "22", "deductible": True,
                       "document_number": "ACQ 88/2026",
                       "counterparty_name": "Materie Prime Sud S.r.l."})],
            validate=True)


def _liquidity_pressure(db, *, tid, actor) -> None:
    co = _mk_company(db, tid=tid, actor=actor, vat="02222222222",
                     name="Officine Meccaniche Etna S.p.A.",
                     industry="Meccanica di precisione", city="Catania",
                     revenue=2_400_000, employees=32,
                     contact_name="Laura Puglisi", contact_role="CFO")
    _actuals(db, tid=tid, company=co, actor=actor, key="PV-OME",
             months=[("150000", "118000"), ("148000", "120000"),
                     ("152000", "121000"), ("149000", "122000"),
                     ("151000", "123000"), ("150000", "124000")],
             fixed_monthly="26000",
             plan={"Costi operativi": ("variable", "CDC-OPS"),
                   "Struttura e affitti": ("fixed", "CDC-STR"),
                   "Vendite": (None, "CDC-OPS")})
    _treasury(db, tid=tid, company=co, actor=actor, key="PV-OME",
              balance="11500.00",
              script=[{"id": "PV-OME-001", "date": _day(-5), "amount": "-22000.00",
                       "counterparty": "ACCIAIERIE SUD SPA",
                       "description": "BONIFICO ACCIAIERIE SUD SPA FATT 140/2026"},
                      {"id": "PV-OME-002", "date": _day(-2), "amount": "9600.00",
                       "counterparty": "AEROSPACE COMPONENTS SRL",
                       "description": "BONIFICO INCASSO FT 201/2026"}],
              items=[
                  {"source_ref": "PV-OME-FT198", "direction": "receivable",
                   "counterparty_name": "Aerospace Components S.r.l.",
                   "document_number": "FT 198/2026", "document_date": _day(-70),
                   "due_date": _day(-40), "amount": "34000.00"},
                  {"source_ref": "PV-OME-FT205", "direction": "receivable",
                   "counterparty_name": "Navale Tirrena S.p.A.",
                   "document_number": "FT 205/2026", "document_date": _day(-15),
                   "due_date": _day(45), "amount": "41000.00"},
                  {"source_ref": "PV-OME-F24", "direction": "payable",
                   "counterparty_name": "Erario", "document_number": "F24 09/2026",
                   "due_date": _day(9), "amount": "18500.00",
                   "notes": "Importo inserito manualmente."},
                  {"source_ref": "PV-OME-PAY", "direction": "payable",
                   "counterparty_name": "Stipendi", "due_date": _day(13),
                   "amount": "38000.00",
                   "notes": "Costo inserito manualmente."},
                  {"source_ref": "PV-OME-ACQ140", "direction": "payable",
                   "counterparty_name": "Acciaierie Sud S.p.A.",
                   "document_number": "141/2026", "document_date": _day(-6),
                   "due_date": _day(24), "amount": "22000.00"}])


def _fiscal_obligation(db, *, tid, actor) -> None:
    co = _mk_company(db, tid=tid, actor=actor, vat="02333333333",
                     name="Edil Costruzioni Madonie S.r.l.",
                     industry="Costruzioni", city="Petralia Sottana",
                     revenue=1_100_000, employees=19,
                     contact_name="Giuseppe Mirto", contact_role="Amministratore")
    _treasury(db, tid=tid, company=co, actor=actor, key="PV-EDIL",
              balance="26000.00",
              script=[{"id": "PV-EDIL-001", "date": _day(-7), "amount": "14000.00",
                       "counterparty": "COMUNE DI PETRALIA",
                       "description": "BONIFICO SAL LAVORI PUBBLICI"}],
              items=[
                  {"source_ref": "PV-EDIL-SAL3", "direction": "receivable",
                   "counterparty_name": "Comune di Petralia Sottana",
                   "document_number": "SAL 3/2026", "document_date": _day(-20),
                   "due_date": _day(40), "amount": "52000.00"},
                  {"source_ref": "PV-EDIL-ACQ9", "direction": "payable",
                   "counterparty_name": "Calcestruzzi Madonie S.r.l.",
                   "document_number": "9/2026", "document_date": _day(-12),
                   "due_date": _day(18), "amount": "11800.00"}])
    # Validated July settlement → payable due 20/08 → already overdue.
    _fiscal(db, tid=tid, company=co, actor=actor, key="PV-EDIL", period=7,
            entries=[("sale", "2026-07-15", "40000.00", "8800.00", "S1",
                      {"vat_rate": "22", "document_number": "FT 33/2026",
                       "counterparty_name": "Comune di Petralia Sottana"}),
                     ("purchase", "2026-07-18", "15000.00", "3300.00", "P1",
                      {"vat_rate": "22", "deductible": True,
                       "document_number": "ACQ 51/2026",
                       "counterparty_name": "Calcestruzzi Madonie S.r.l."})],
            validate=True)


def _early_warning(db, *, tid, actor) -> None:
    co = _mk_company(db, tid=tid, actor=actor, vat="02555555555",
                     name="Ceramiche Artistiche S.r.l.",
                     industry="Artigianato ceramico", city="Caltagirone",
                     revenue=620_000, employees=9,
                     contact_name="Rosa Vecchio", contact_role="Titolare")
    _treasury(db, tid=tid, company=co, actor=actor, key="PV-CER",
              balance="19800.00",
              script=[{"id": "PV-CER-001", "date": _day(-4), "amount": "7200.00",
                       "counterparty": "HOTEL COLLECTION SRL",
                       "description": "BONIFICO FORNITURA CERAMICHE"}],
              items=[
                  {"source_ref": "PV-CER-FT8", "direction": "receivable",
                   "counterparty_name": "Hotel Collection S.r.l.",
                   "document_number": "FT 8/2026", "document_date": _day(-34),
                   "due_date": _day(-4), "amount": "7200.00"},
                  {"source_ref": "PV-CER-ACQ5", "direction": "payable",
                   "counterparty_name": "Fornaci del Sud S.r.l.",
                   "document_number": "5/2026", "document_date": _day(-9),
                   "due_date": _day(21), "amount": "4300.00"}])
    _debt(db, tid=tid, company=co, actor=actor,
          name="Finanziamento forno (demo)", ftype="loan",
          lender="Banca dimostrativa", outstanding="85000.00",
          instalments=[(-90, "1800.00", "220.00", "paid"),
                       (-60, "1800.00", "220.00", "paid"),
                       (-30, "1800.00", "220.00", "paid"),
                       (-12, "1800.00", "220.00", None),
                       (18, "1800.00", "220.00", None),
                       (48, "1800.00", "220.00", None),
                       (78, "1800.00", "220.00", None)],
          detect=True)


def _commercial(db, *, tid, actor, lines, stages) -> None:
    co = _mk_company(db, tid=tid, actor=actor, vat="02444444444",
                     name="Techne Consulting S.r.l.",
                     industry="Consulenza digitale", city="Palermo",
                     revenue=480_000, employees=7,
                     contact_name="Marco Albanese", contact_role="CEO")
    if db.scalar(select(Opportunity).where(Opportunity.company_id == co.id)):
        return
    db.add(Opportunity(
        title="Techne — assessment Growth Factors",
        company_id=co.id, service_line_id=lines["growth-factors"].id,
        stage_id=stages[2].id, owner_id=actor.id,
        expected_value_eur=28000, probability=60, source="referral",
        tenant_id=tid))
    db.add(Opportunity(
        title="Techne — pianificazione triennale",
        company_id=co.id, service_line_id=lines["business-planning"].id,
        stage_id=stages[1].id, owner_id=actor.id,
        expected_value_eur=15000, probability=30, source="website",
        tenant_id=tid))
    db.add(Task(title="Call di follow-up con Marco Albanese",
                owner_id=actor.id, priority=TaskPriority.MEDIUM,
                entity_type="company", entity_id=co.id, tenant_id=tid))
    _treasury(db, tid=tid, company=co, actor=actor, key="PV-TEC",
              balance="33000.00",
              script=[{"id": "PV-TEC-001", "date": _day(-3), "amount": "11000.00",
                       "counterparty": "RETAIL GROUP SPA",
                       "description": "BONIFICO CONSULENZA Q3"}],
              items=[
                  {"source_ref": "PV-TEC-FT21", "direction": "receivable",
                   "counterparty_name": "Retail Group S.p.A.",
                   "document_number": "FT 21/2026", "document_date": _day(-33),
                   "due_date": _day(-3), "amount": "11000.00"}])


def seed_preview(db) -> None:
    """Idempotent: safe on every boot; each block self-guards."""
    from app.modules.companies.models import Company as _C
    from app.modules.service_lines.models import PipelineStage, ServiceLine
    from app.modules.tenancy.models import Tenant
    from app.modules.users.models import User

    platform = db.scalar(select(Tenant).where(Tenant.is_platform_org.is_(True)))
    if platform is None:
        return
    tid = platform.id
    actor = db.scalar(select(User).where(User.tenant_id == tid).limit(1))
    if actor is None:
        return
    lines = {r.code: r for r in db.scalars(
        select(ServiceLine).where(ServiceLine.tenant_id == tid)).all()}
    stages = db.scalars(select(PipelineStage).where(
        PipelineStage.tenant_id == tid).order_by(PipelineStage.position)).all()
    if not lines or not stages:
        return
    # Only seed the extra companies once the base demo company exists.
    if not db.scalar(select(_C).where(_C.tenant_id == tid,
                                     _C.vat_number == "01234567890")):
        return
    _healthy(db, tid=tid, actor=actor)
    _liquidity_pressure(db, tid=tid, actor=actor)
    _fiscal_obligation(db, tid=tid, actor=actor)
    _early_warning(db, tid=tid, actor=actor)
    _commercial(db, tid=tid, actor=actor, lines=lines, stages=stages)
    db.commit()
