"""Idempotent loading of the verified rule sets into the database.

The engine reads rules from the database, never from Python constants, so the
seeded content in `rules.py` has to be materialised once per installation.
Re-running this is safe: an existing (family, version) row is left untouched —
a law change must arrive as a **new version**, not as an edit of the old one.
"""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fiscal import rules
from app.modules.fiscal.models import FiscalRuleSet, FiscalTaxCode, RuleStatus


def _fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_rule_sets(db: Session) -> dict:
    """Create the verified rule sets and tax codes if missing.

    Returns a small report so callers (seed, first-run setup, admin sync
    endpoint) can tell what happened.
    """
    created_rules, created_codes = [], []

    for spec in rules.SEEDED_RULE_SETS:
        existing = db.scalar(
            select(FiscalRuleSet).where(
                FiscalRuleSet.jurisdiction == rules.JURISDICTION,
                FiscalRuleSet.rule_family == spec["rule_family"],
                FiscalRuleSet.version == spec["version"],
            )
        )
        if existing is None:
            existing = FiscalRuleSet(
                code=spec["code"],
                jurisdiction=rules.JURISDICTION,
                rule_family=spec["rule_family"],
                version=spec["version"],
                status=RuleStatus.ACTIVE,
                effective_from=spec["effective_from"],
                effective_to=spec["effective_to"],
                payload=spec["payload"],
                source_authority=spec["source_authority"],
                source_title=spec["source_title"],
                source_url=spec["source_url"],
                source_published_at=spec["source_published_at"],
                retrieved_at=rules.RETRIEVED_AT,
                source_fingerprint=_fingerprint(spec["payload"]),
                legal_reference=spec["legal_reference"],
                notes=spec["notes"],
                engine_version=rules.ENGINE_VERSION,
            )
            db.add(existing)
            db.flush()
            created_rules.append(f"{spec['rule_family']}/{spec['version']}")

    # Tax codes hang off the F24 format rule set: it is the row that carries
    # the official F24 instructions provenance.
    format_rule = db.scalar(
        select(FiscalRuleSet).where(
            FiscalRuleSet.jurisdiction == rules.JURISDICTION,
            FiscalRuleSet.rule_family == "f24_format",
            FiscalRuleSet.status == RuleStatus.ACTIVE,
        ).order_by(FiscalRuleSet.effective_from.desc())
    )
    if format_rule is not None:
        for spec in rules.SEEDED_TAX_CODES:
            present = db.scalar(
                select(FiscalTaxCode).where(
                    FiscalTaxCode.jurisdiction == rules.JURISDICTION,
                    FiscalTaxCode.code == spec["code"],
                    FiscalTaxCode.valid_from == rules.SUPPORTED_FROM,
                )
            )
            if present is not None:
                continue
            db.add(FiscalTaxCode(
                code=spec["code"],
                jurisdiction=rules.JURISDICTION,
                description=spec["description"],
                section=spec["section"],
                usage=spec["usage"],
                reference_number=spec["reference_number"],
                valid_from=rules.SUPPORTED_FROM,
                valid_to=None,
                requires_reference_period=spec["requires_reference_period"],
                rule_set_id=format_rule.id,
                source_url=rules.TAX_CODE_SOURCE["url"],
                notes=spec["notes"],
            ))
            created_codes.append(spec["code"])
        db.flush()

    return {
        "rule_sets_created": created_rules,
        "tax_codes_created": created_codes,
        "engine_version": rules.ENGINE_VERSION,
        "retrieved_at": rules.RETRIEVED_AT.isoformat(),
        "note": ("Le regole sono dati di riferimento versionati ed effective-dated: "
                 "un cambio normativo arriva come nuova versione, mai come modifica."),
    }
