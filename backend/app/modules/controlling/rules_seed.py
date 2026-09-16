"""Materialise the versioned early-warning rules.

Idempotent like `fiscal.rules_seed`: an existing (code, version) is never
edited — a regulatory change must arrive as a new version.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.controlling import ew
from app.modules.controlling.models import EarlyWarningRule, RuleStatus
from app.shared.mixins import today


def ensure_rules(db: Session, *, tenant_id) -> dict:
    created = []
    for spec in ew.seed_definitions():
        existing = db.scalar(
            select(EarlyWarningRule).where(
                EarlyWarningRule.tenant_id == tenant_id,
                EarlyWarningRule.code == spec["code"],
                EarlyWarningRule.version == spec["version"]))
        if existing is not None:
            continue
        row = EarlyWarningRule(
            tenant_id=tenant_id, code=spec["code"], version=spec["version"],
            status=RuleStatus.ACTIVE, category=spec["category"],
            title=spec["title"], description=spec["description"],
            legal_reference=spec["legal_reference"],
            source_authority=spec["source_authority"],
            source_url=spec["source_url"],
            source_retrieved_at=today(),
            effective_from=date(2026, 1, 1), effective_to=None,
            params=spec["params"], data_requirements=spec["data_requirements"],
            formula=spec["formula"], formula_version=ew.EW_FORMULA_VERSION)
        db.add(row)
        created.append(spec["code"])
    return {"rules_created": created, "formula_version": ew.EW_FORMULA_VERSION}


def active_rules(db: Session, *, tenant_id, on_date: date) -> list[EarlyWarningRule]:
    """Rules in force at `on_date`: active, effective-dated, latest version
    per code."""
    rows = db.scalars(
        select(EarlyWarningRule)
        .where(EarlyWarningRule.tenant_id == tenant_id,
               EarlyWarningRule.status == RuleStatus.ACTIVE,
               EarlyWarningRule.effective_from <= on_date)
        .order_by(EarlyWarningRule.code, EarlyWarningRule.version.desc())
    ).all()
    latest: dict[str, EarlyWarningRule] = {}
    for row in rows:
        if row.code in latest:
            continue
        if row.effective_to is not None and row.effective_to < on_date:
            continue
        latest[row.code] = row
    return [latest[code] for code in sorted(latest)]


def rule_dict(row: EarlyWarningRule) -> dict:
    return {
        "id": str(row.id), "code": row.code, "version": row.version,
        "status": row.status, "category": row.category, "title": row.title,
        "description": row.description, "legal_reference": row.legal_reference,
        "source_authority": row.source_authority, "source_url": row.source_url,
        "source_retrieved_at": (row.source_retrieved_at.isoformat()
                                if row.source_retrieved_at else None),
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "params": row.params, "data_requirements": row.data_requirements,
        "formula": row.formula, "formula_version": row.formula_version,
    }
