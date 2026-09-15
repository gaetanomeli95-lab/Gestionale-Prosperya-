"""fiscal core v1 — regole versionate, registro IVA, liquidazioni, scadenze, F24

Revision ID: f1a2b3c4d5e6
Revises: 241a5cddffba
Create Date: 2026-09-14

Creates the fiscal domain tables and widens the open_items source CHECK to
admit 'fiscal' (validated IVA liabilities become treasury cash obligations).
Batch mode is used for the CHECK replacement so SQLite stays supported.
"""
import sqlalchemy as sa

import app.shared.mixins  # noqa: F401 — provides app.shared.mixins.GUID below
from alembic import op


revision = "f1a2b3c4d5e6"
down_revision = "241a5cddffba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- jurisdiction-level reference data ---------------------------------
    op.create_table(
        "fiscal_rule_sets",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("jurisdiction", sa.String(length=8), nullable=False),
        sa.Column("rule_family", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_authority", sa.String(length=120), nullable=False),
        sa.Column("source_title", sa.String(length=300), nullable=False),
        sa.Column("source_url", sa.String(length=600), nullable=False),
        sa.Column("source_published_at", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.Date(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("legal_reference", sa.String(length=300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'superseded', 'draft')",
                           name="ck_status_ruleset"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                           name="ck_effective_range"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jurisdiction", "rule_family", "version",
                            name="uq_rule_set_family_version"),
    )
    op.create_index("ix_fiscal_rule_sets_rule_family", "fiscal_rule_sets", ["rule_family"])
    op.create_index("ix_fiscal_rule_sets_effective_from", "fiscal_rule_sets", ["effective_from"])

    op.create_table(
        "fiscal_tax_codes",
        sa.Column("code", sa.String(length=12), nullable=False),
        sa.Column("jurisdiction", sa.String(length=8), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("usage", sa.String(length=40), nullable=False),
        sa.Column("reference_number", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("requires_reference_period", sa.Boolean(), nullable=False),
        sa.Column("rule_set_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("source_url", sa.String(length=600), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("section IN ('erario', 'inps', 'regioni', 'imu', 'altri')",
                           name="ck_section_taxcode"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from",
                           name="ck_validity_range"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["fiscal_rule_sets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jurisdiction", "code", "valid_from", name="uq_tax_code_validity"),
    )
    op.create_index("ix_fiscal_tax_codes_code", "fiscal_tax_codes", ["code"])
    op.create_index("ix_fiscal_tax_codes_rule_set_id", "fiscal_tax_codes", ["rule_set_id"])

    # --- tenant-scoped fiscal data ------------------------------------------
    op.create_table(
        "vat_entries",
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_ref", sa.String(length=160), nullable=False),
        sa.Column("invoice_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("document_number", sa.String(length=80), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("competence_date", sa.Date(), nullable=False),
        sa.Column("counterparty_name", sa.String(length=300), nullable=True),
        sa.Column("counterparty_vat", sa.String(length=32), nullable=True),
        sa.Column("taxable_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("vat_nature", sa.String(length=8), nullable=True),
        sa.Column("deductible", sa.Boolean(), nullable=True),
        sa.Column("treatment", sa.String(length=24), nullable=False),
        sa.Column("treatment_reason", sa.String(length=300), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reverses_entry_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("created_by_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("tenant_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("company_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("direction IN ('sale', 'purchase')", name="ck_direction_vat"),
        sa.CheckConstraint(
            "treatment IN ('supported', 'unsupported', 'requires_review', 'insufficient_data')",
            name="ck_treatment_vat"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_currency_vat"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "company_id", "source", "source_ref",
                            name="uq_vat_entry_source_ref"),
    )
    op.create_index(op.f("ix_vat_entries_tenant_id"), "vat_entries", ["tenant_id"], unique=False)
    op.create_index("ix_vat_entries_direction", "vat_entries", ["direction"])
    op.create_index("ix_vat_entries_competence_date", "vat_entries", ["competence_date"])
    op.create_index("ix_vat_entries_treatment", "vat_entries", ["treatment"])
    op.create_index("ix_vat_entries_company_id", "vat_entries", ["company_id"])
    op.create_index("ix_vat_entries_invoice_id", "vat_entries", ["invoice_id"])
    op.create_index("ix_vat_entries_reverses_entry_id", "vat_entries", ["reverses_entry_id"])

    op.create_table(
        "fiscal_periods",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(length=12), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("tenant_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("company_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("frequency IN ('monthly', 'quarterly')", name="ck_frequency_period"),
        sa.CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_year_period"),
        sa.CheckConstraint("period_no BETWEEN 1 AND 12", name="ck_period_no"),
        sa.CheckConstraint("end_date >= start_date", name="ck_period_range"),
        sa.CheckConstraint(
            "status IN ('open', 'calculated', 'review_required', 'validated', 'locked')",
            name="ck_status_period"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "company_id", "year", "frequency", "period_no",
                            name="uq_fiscal_period_scope"),
    )
    op.create_index(op.f("ix_fiscal_periods_tenant_id"), "fiscal_periods", ["tenant_id"], unique=False)
    op.create_index("ix_fiscal_periods_year", "fiscal_periods", ["year"])
    op.create_index("ix_fiscal_periods_company_id", "fiscal_periods", ["company_id"])

    op.create_table(
        "vat_settlements",
        sa.Column("period_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_set_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("formula_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("debit_total", sa.Numeric(20, 2), nullable=True),
        sa.Column("credit_total", sa.Numeric(20, 2), nullable=True),
        sa.Column("prior_credit", sa.Numeric(20, 2), nullable=True),
        sa.Column("prior_small_debit", sa.Numeric(20, 2), nullable=True),
        sa.Column("interest_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("net_position", sa.Numeric(20, 2), nullable=True),
        sa.Column("payable_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("carry_forward_credit", sa.Numeric(20, 2), nullable=True),
        sa.Column("carry_forward_debit", sa.Numeric(20, 2), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("unsupported_count", sa.Integer(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_by_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("validated_by_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_note", sa.String(length=600), nullable=True),
        sa.Column("superseded_by_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("tenant_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("company_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_version_settlement"),
        sa.CheckConstraint(
            "status IN ('calculated', 'review_required', 'validated', 'superseded')",
            name="ck_status_settlement"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_currency_settlement"),
        sa.ForeignKeyConstraint(["period_id"], ["fiscal_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["fiscal_rule_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["calculated_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["validated_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "period_id", "version", name="uq_settlement_version"),
    )
    op.create_index(op.f("ix_vat_settlements_tenant_id"), "vat_settlements", ["tenant_id"], unique=False)
    op.create_index("ix_vat_settlements_period_id", "vat_settlements", ["period_id"])
    op.create_index("ix_vat_settlements_status", "vat_settlements", ["status"])
    op.create_index("ix_vat_settlements_company_id", "vat_settlements", ["company_id"])
    op.create_index("ix_vat_settlements_rule_set_id", "vat_settlements", ["rule_set_id"])

    op.create_table(
        "fiscal_deadlines",
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("period_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("settlement_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("statutory_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_date_status", sa.String(length=20), nullable=False),
        sa.Column("deferral_reason", sa.String(length=300), nullable=True),
        sa.Column("amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rule_set_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("open_item_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tenant_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("company_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'validated', 'settled', 'cancelled')",
                           name="ck_status_deadline"),
        sa.CheckConstraint("due_date_status IN ('resolved', 'review_required')",
                           name="ck_due_status"),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_amount_deadline"),
        sa.ForeignKeyConstraint(["period_id"], ["fiscal_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["settlement_id"], ["vat_settlements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["fiscal_rule_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "company_id", "kind", "period_id",
                            name="uq_fiscal_deadline_period"),
    )
    op.create_index(op.f("ix_fiscal_deadlines_tenant_id"), "fiscal_deadlines", ["tenant_id"], unique=False)
    op.create_index("ix_fiscal_deadlines_kind", "fiscal_deadlines", ["kind"])
    op.create_index("ix_fiscal_deadlines_due_date", "fiscal_deadlines", ["due_date"])
    op.create_index("ix_fiscal_deadlines_company_id", "fiscal_deadlines", ["company_id"])
    op.create_index("ix_fiscal_deadlines_period_id", "fiscal_deadlines", ["period_id"])
    op.create_index("ix_fiscal_deadlines_settlement_id", "fiscal_deadlines", ["settlement_id"])
    op.create_index("ix_fiscal_deadlines_open_item_id", "fiscal_deadlines", ["open_item_id"])

    op.create_table(
        "f24_drafts",
        sa.Column("settlement_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("deadline_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("rule_set_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_debit", sa.Numeric(20, 2), nullable=False),
        sa.Column("total_credit", sa.Numeric(20, 2), nullable=False),
        sa.Column("balance", sa.Numeric(20, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("taxpayer_snapshot", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("validated_by_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("export_format", sa.String(length=40), nullable=True),
        sa.Column("export_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("tenant_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("company_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('generated', 'validation_required', 'validated', 'approved', 'exported')",
            name="ck_status_f24"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_currency_f24"),
        sa.ForeignKeyConstraint(["settlement_id"], ["vat_settlements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deadline_id"], ["fiscal_deadlines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["fiscal_rule_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["validated_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "settlement_id", name="uq_f24_draft_settlement"),
    )
    op.create_index(op.f("ix_f24_drafts_tenant_id"), "f24_drafts", ["tenant_id"], unique=False)
    op.create_index("ix_f24_drafts_settlement_id", "f24_drafts", ["settlement_id"])
    op.create_index("ix_f24_drafts_deadline_id", "f24_drafts", ["deadline_id"])
    op.create_index("ix_f24_drafts_company_id", "f24_drafts", ["company_id"])

    op.create_table(
        "f24_lines",
        sa.Column("draft_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("tax_code", sa.String(length=12), nullable=False),
        sa.Column("tax_code_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("tax_code_description", sa.String(length=300), nullable=True),
        sa.Column("reference_year", sa.Integer(), nullable=False),
        sa.Column("reference_period", sa.String(length=12), nullable=True),
        sa.Column("debit_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("credit_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("origin_kind", sa.String(length=40), nullable=False),
        sa.Column("origin_settlement_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("origin_deadline_id", app.shared.mixins.GUID(), nullable=True),
        sa.Column("rule_reference", sa.String(length=300), nullable=True),
        sa.Column("explanation", sa.String(length=600), nullable=False),
        sa.Column("tenant_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("company_id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("id", app.shared.mixins.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("section IN ('erario', 'inps', 'regioni', 'imu', 'altri')",
                           name="ck_section_f24line"),
        sa.CheckConstraint("debit_amount >= 0 AND credit_amount >= 0", name="ck_amounts_f24line"),
        sa.CheckConstraint("reference_year BETWEEN 2000 AND 2100", name="ck_year_f24line"),
        sa.ForeignKeyConstraint(["draft_id"], ["f24_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tax_code_id"], ["fiscal_tax_codes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_f24_lines_tenant_id"), "f24_lines", ["tenant_id"], unique=False)
    op.create_index("ix_f24_lines_draft_id", "f24_lines", ["draft_id"])
    op.create_index("ix_f24_lines_company_id", "f24_lines", ["company_id"])

    # --- widen open_items source CHECK to admit 'fiscal' ---------------------
    with op.batch_alter_table("open_items") as batch:
        batch.drop_constraint("ck_source_57014e44fdf0", type_="check")
        batch.create_check_constraint(
            "ck_source_446eef24d856",
            "source IN ('invoice', 'manual', 'import', 'fiscal')")


def downgrade() -> None:
    with op.batch_alter_table("open_items") as batch:
        batch.drop_constraint("ck_source_446eef24d856", type_="check")
        batch.create_check_constraint(
            "ck_source_57014e44fdf0",
            "source IN ('invoice', 'manual', 'import')")

    op.drop_table("f24_lines")
    op.drop_table("f24_drafts")
    op.drop_table("fiscal_deadlines")
    op.drop_table("vat_settlements")
    op.drop_table("fiscal_periods")
    op.drop_table("vat_entries")
    op.drop_table("fiscal_tax_codes")
    op.drop_table("fiscal_rule_sets")
