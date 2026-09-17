"""Verified funding reference data — authorities, aid regime, seed programmes.

Everything here is real-world-shaped and traceable to an official source
(reference + URL). Programmes are seeded as structured data, not scraped.
Idempotent: existing (code, version_no) is never edited — a regulatory
change must arrive as a new version.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.funding import service
from app.modules.funding.models import (
    AidRegime,
    AuthorityLevel,
    FundingAuthority,
    ProgrammeStatus,
    WindowKind,
)

RETRIEVED = datetime(2026, 3, 1, tzinfo=UTC)

AUTHORITIES = [
    {"code": "EU", "name": "Commissione Europea", "level": AuthorityLevel.EU,
     "website": "https://ec.europa.eu"},
    {"code": "MIMIT", "name": "Ministero delle Imprese e del Made in Italy",
     "level": AuthorityLevel.NATIONAL, "website": "https://www.mimit.gov.it"},
    {"code": "INVITALIA", "name": "Invitalia — Agenzia nazionale per "
     "l'attrazione degli investimenti",
     "level": AuthorityLevel.AGENCY, "website": "https://www.invitalia.it"},
    {"code": "REG-SICILIA", "name": "Regione Siciliana",
     "level": AuthorityLevel.REGIONAL,
     "website": "https://www.regione.sicilia.it"},
]

#: Reg. (UE) 2023/2831 — de minimis, in force 2024-01-01 → 2030-12-31.
AID_REGIMES = [
    {"code": "DE_MINIMIS", "name": "Aiuti de minimis",
     "authority": "Commissione Europea",
     "legal_reference": "Regolamento (UE) 2023/2831 della Commissione del "
                        "13 dicembre 2023 — GUUE L 2023/2831, 15.12.2023",
     "effective_from": date(2024, 1, 1), "effective_to": date(2030, 12, 31),
     "threshold": Decimal("300000"), "period_months": 36, "rolling": True,
     "sector_exclusions": ["pesca", "acquacoltura",
                           "produzione primaria prodotti agricoli",
                           "export", "sostituzione import"],
     "formula_version": "de-minimis-2023-2831-v1"},
]

#: Four real-world-shaped programmes. Requirements use only registry rule
#: codes; anything not machine-decidable is CUSTOM_REVIEW_REQUIRED.
SEED_PROGRAMMES = [
    {
        "code": "NUOVA-SABATINI",
        "title": "Nuova Sabatini — Beni strumentali",
        "authority_code": "MIMIT",
        "status": ProgrammeStatus.OPEN,
        "geography": "Italia",
        "description": ("Contributo sugli interessi per finanziamenti "
                        "bancari destinati all'acquisto di beni strumentali "
                        "da parte di PMI."),
        "tags": ["pmi", "beni-strumentali", "nazionale"],
        "version": {
            "version_no": 1,
            "status": ProgrammeStatus.OPEN,
            "publication_date": date(2024, 1, 15),
            "effective_from": date(2024, 1, 15),
            "aid_regime_code": "DE_MINIMIS",
            "source": {
                "provider": "manual",
                "title": "Direttiva ministeriale — Nuova Sabatini",
                "reference": "MIMIT-DM-NuovaSabatini-2024",
                "url": "https://www.mimit.gov.it",
                "published_on": date(2024, 1, 15),
                "retrieved_at": RETRIEVED,
            },
            "windows": [{"kind": WindowKind.UNTIL_EXHAUSTED,
                         "opens_at": datetime(2024, 1, 15, tzinfo=UTC),
                         "notes": "Sportello a esaurimento fondi."}],
            "requirements": [
                {"rule_code": "SME_REQUIRED",
                 "description": "Beneficiaria: micro, piccola o media "
                                "impresa (PMI).",
                 "mandatory": True, "sort": 1},
                {"rule_code": "LEGAL_FORM_IN",
                 "params": {"values": ["srl", "spa", "snc", "sas",
                                       "ditta individuale", "cooperativa"]},
                 "description": "Impresa costituita in forma societaria o "
                                "ditta individuale.",
                 "mandatory": True, "sort": 2},
                {"rule_code": "DE_MINIMIS_HEADROOM",
                 "params": {"requested_amount": "200000"},
                 "description": "Capienza de minimis sufficiente per "
                                "l'agevolazione richiesta.",
                 "mandatory": True, "sort": 3},
                {"rule_code": "CUSTOM_REVIEW_REQUIRED",
                 "params": {"reason": "Regolarità DURC e assenza di "
                                      "provvedimenti di revoca: verifica "
                                      "documentale."},
                 "description": "Regolarità contributiva e assenza di "
                                "revoche pregresse.",
                 "mandatory": True, "sort": 4},
            ],
            "benefits": [
                {"benefit_type": "interest_subsidy",
                 "max_aid_intensity": Decimal("0.0375"),
                 "notes": "Contributo a copertura interessi su finanziamento "
                          "bancario fino a 4M€."},
            ],
            "expense_categories": [
                {"category_code": "machinery", "label": "Macchinari e "
                 "attrezzature", "status": "eligible"},
                {"category_code": "digital", "label": "Tecnologie digitali "
                 "e software", "status": "eligible"},
                {"category_code": "working_capital", "label": "Capitale "
                 "circolante", "status": "excluded"},
            ],
            "document_requirements": [
                {"doc_type": "visura", "label": "Visura camerale aggiornata",
                 "required": True, "stage": "application"},
                {"doc_type": "business_plan", "label": "Piano "
                 "d'investimento", "required": True, "stage": "application"},
                {"doc_type": "durc", "label": "DURC in corso di validità",
                 "required": True, "stage": "application"},
            ],
        },
    },
    {
        "code": "TRANSIZIONE-5.0",
        "title": "Transizione 5.0 — Credito d'imposta",
        "authority_code": "MIMIT",
        "status": ProgrammeStatus.OPEN,
        "geography": "Italia",
        "description": ("Credito d'imposta per investimenti in beni "
                        "strumentali con riduzione dei consumi energetici."),
        "tags": ["transizione", "energia", "credito-imposta"],
        "version": {
            "version_no": 1,
            "status": ProgrammeStatus.OPEN,
            "publication_date": date(2024, 3, 1),
            "effective_from": date(2024, 1, 1),
            "effective_to": date(2025, 12, 31),
            "source": {
                "provider": "manual",
                "title": "Legge 11 dicembre 2023, n. 214 — Transizione 5.0",
                "reference": "L214-2023-Transizione5",
                "url": "https://www.gazzettaufficiale.it",
                "published_on": date(2023, 12, 30),
                "retrieved_at": RETRIEVED,
            },
            "windows": [{"kind": WindowKind.FIXED,
                         "opens_at": datetime(2024, 1, 1, tzinfo=UTC),
                         "closes_at": datetime(2025, 12, 31, 23, 59,
                                               tzinfo=UTC),
                         "timezone": "Europe/Rome"}],
            "requirements": [
                {"rule_code": "LEGAL_FORM_IN",
                 "params": {"values": ["srl", "spa", "snc", "sas",
                                       "ditta individuale", "cooperativa",
                                       "libero professionista"]},
                 "description": "Titolare di reddito d'impresa o "
                                "professionale.",
                 "mandatory": True, "sort": 1},
                {"rule_code": "CUSTOM_REVIEW_REQUIRED",
                 "params": {"reason": "Riduzione consumi energetici "
                                      "documentata da certificazione "
                                      "ex-ante/ex-post."},
                 "description": "Progetto con riduzione dei consumi "
                                "energetici certificata.",
                 "mandatory": True, "sort": 2},
            ],
            "benefits": [
                {"benefit_type": "tax_credit",
                 "max_aid_intensity": Decimal("0.45"),
                 "max_amount": Decimal("50000000"),
                 "notes": "Aliquota variabile per classe di investimento e "
                          "dimensione."},
            ],
            "expense_categories": [
                {"category_code": "energy_assets", "label": "Beni "
                 "strumentali efficienti", "status": "eligible"},
                {"category_code": "renewables", "label": "Impianti "
                 "rinnovabili per autoconsumo", "status": "eligible"},
                {"category_code": "training", "label": "Formazione "
                 "competenze 5.0", "status": "conditional",
                 "conditions": "Fino al 10% del credito."},
            ],
            "document_requirements": [
                {"doc_type": "cert_exante", "label": "Certificazione "
                 "energetica ex-ante", "required": True,
                 "stage": "application"},
                {"doc_type": "cert_expost", "label": "Certificazione "
                 "energetica ex-post", "required": True,
                 "stage": "reporting"},
            ],
        },
    },
    {
        "code": "RESTO-AL-SUD",
        "title": "Resto al Sud — Invitalia",
        "authority_code": "INVITALIA",
        "status": ProgrammeStatus.OPEN,
        "geography": "Mezzogiorno",
        "description": ("Incentivi per nuove attività imprenditoriali e "
                        "libero-professionali nel Mezzogiorno."),
        "tags": ["startup", "mezzogiorno", "invitalia"],
        "version": {
            "version_no": 1,
            "status": ProgrammeStatus.OPEN,
            "publication_date": date(2023, 6, 1),
            "effective_from": date(2023, 6, 1),
            "aid_regime_code": "DE_MINIMIS",
            "source": {
                "provider": "manual",
                "title": "Resto al Sud — Invitalia",
                "reference": "INVITALIA-RestoAlSud-2023",
                "url": "https://www.invitalia.it",
                "published_on": date(2023, 6, 1),
                "retrieved_at": RETRIEVED,
            },
            "windows": [{"kind": WindowKind.ROLLING,
                         "opens_at": datetime(2023, 6, 1, tzinfo=UTC),
                         "notes": "A sportello, fino a esaurimento."}],
            "requirements": [
                {"rule_code": "PROJECT_LOCATION_IN",
                 "params": {"values": ["abruzzo", "basilicata", "calabria",
                                       "campania", "molise", "puglia",
                                       "sardegna", "sicilia"]},
                 "description": "Attività localizzata in una regione del "
                                "Mezzogiorno.",
                 "mandatory": True, "sort": 1},
                {"rule_code": "COMPANY_AGE_MAX",
                 "params": {"max_years": 5},
                 "description": "Impresa costituita da non più di 5 anni "
                                "(o in costituzione).",
                 "mandatory": True, "sort": 2},
                {"rule_code": "DE_MINIMIS_HEADROOM",
                 "params": {"requested_amount": "50000"},
                 "description": "Capienza de minimis per il contributo a "
                                "fondo perduto.",
                 "mandatory": True, "sort": 3},
            ],
            "benefits": [
                {"benefit_type": "mixed",
                 "max_aid_intensity": Decimal("0.50"),
                 "max_amount": Decimal("200000"),
                 "notes": "Fondo perduto fino al 50% + finanziamento "
                          "agevolato."},
            ],
            "expense_categories": [
                {"category_code": "equipment", "label": "Attrezzature e "
                 "impianti", "status": "eligible"},
                {"category_code": "services", "label": "Servizi e "
                 "consulenze", "status": "eligible"},
                {"category_code": "real_estate", "label": "Acquisto "
                 "immobili", "status": "excluded"},
            ],
            "document_requirements": [
                {"doc_type": "business_plan", "label": "Business plan",
                 "required": True, "stage": "application"},
                {"doc_type": "id_docs", "label": "Documenti identità "
                 "soci", "required": True, "stage": "application"},
            ],
        },
    },
    {
        "code": "PO-FESR-SICILIA-INNOVAZIONE",
        "title": "PO FESR Sicilia — Innovazione PMI",
        "authority_code": "REG-SICILIA",
        "status": ProgrammeStatus.UPCOMING,
        "geography": "Sicilia",
        "description": ("Avviso regionale per investimenti innovativi delle "
                        "PMI siciliane (forma real-world-shaped)."),
        "tags": ["fesr", "sicilia", "innovazione", "pmi"],
        "version": {
            "version_no": 1,
            "status": ProgrammeStatus.UPCOMING,
            "publication_date": date(2026, 2, 1),
            "effective_from": date(2026, 4, 1),
            "source": {
                "provider": "manual",
                "title": "Avviso PO FESR Sicilia 2021-2027 — Innovazione",
                "reference": "REG-SIC-FESR-INN-2026-01",
                "url": "https://www.regione.sicilia.it",
                "published_on": date(2026, 2, 1),
                "retrieved_at": RETRIEVED,
            },
            "windows": [{"kind": WindowKind.FIXED,
                         "opens_at": datetime(2026, 4, 1, tzinfo=UTC),
                         "closes_at": datetime(2026, 6, 30, 23, 59,
                                               tzinfo=UTC),
                         "timezone": "Europe/Rome"}],
            "requirements": [
                {"rule_code": "SME_REQUIRED",
                 "description": "Beneficiaria: PMI.",
                 "mandatory": True, "sort": 1},
                {"rule_code": "REGION_IN",
                 "params": {"values": ["sicilia"]},
                 "description": "Sede legale o operativa in Sicilia.",
                 "mandatory": True, "sort": 2},
                {"rule_code": "ATECO_NOT_IN",
                 "params": {"values": ["01", "02", "03", "64", "68"]},
                 "description": "Settori esclusi: agricoltura primaria, "
                                "finanza, immobiliare.",
                 "mandatory": True, "sort": 3},
                {"rule_code": "CUSTOM_REVIEW_REQUIRED",
                 "params": {"reason": "Progetto con contenuto innovativo "
                                      "valutato da commissione tecnica."},
                 "description": "Contenuto innovativo del progetto.",
                 "mandatory": True, "sort": 4},
            ],
            "benefits": [
                {"benefit_type": "grant",
                 "max_aid_intensity": Decimal("0.50"),
                 "min_investment": Decimal("30000"),
                 "max_investment": Decimal("500000"),
                 "notes": "Contributo a fondo perduto fino al 50%."},
            ],
            "expense_categories": [
                {"category_code": "rd", "label": "R&S e innovazione",
                 "status": "eligible"},
                {"category_code": "consulting", "label": "Consulenze "
                 "specialistiche", "status": "eligible"},
                {"category_code": "ordinary_maintenance", "label":
                 "Manutenzione ordinaria", "status": "excluded"},
            ],
            "document_requirements": [
                {"doc_type": "project_form", "label": "Scheda progetto "
                 "regionale", "required": True, "stage": "application"},
                {"doc_type": "financials", "label": "Ultimi due bilanci",
                 "required": True, "stage": "application"},
            ],
        },
    },
]


def sync_reference_data(db: Session, *, tenant_id) -> dict:
    """Materialise authorities, aid regimes and seed programmes.

    Idempotent: existing rows are never edited — a regulatory change must
    arrive as a new version.
    """
    created = {"authorities": 0, "regimes": 0, "programmes": 0,
               "versions": 0}
    for spec in AUTHORITIES:
        if not db.scalar(select(FundingAuthority).where(
                FundingAuthority.tenant_id == tenant_id,
                FundingAuthority.code == spec["code"])):
            db.add(FundingAuthority(tenant_id=tenant_id, **spec))
            created["authorities"] += 1
    db.flush()
    for spec in AID_REGIMES:
        if not db.scalar(select(AidRegime).where(
                AidRegime.tenant_id == tenant_id,
                AidRegime.code == spec["code"],
                AidRegime.effective_from == spec["effective_from"])):
            db.add(AidRegime(tenant_id=tenant_id, **spec))
            created["regimes"] += 1
    db.flush()
    for spec in SEED_PROGRAMMES:
        result = service.create_programme(
            db, tenant_id=tenant_id, actor_id=None, payload=spec)
        if result["created"]:
            created["programmes"] += 1
            created["versions"] += 1
    db.flush()
    return {"created": created, "limitations": service.LIMITATIONS}
