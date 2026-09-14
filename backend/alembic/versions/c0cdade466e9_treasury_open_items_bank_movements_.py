"""treasury: open items, bank movements, reconciliation

Adds the canonical treasury chain (ADR-016):
`bank_accounts` -> `bank_transactions` -> `reconciliation_allocations` <-
`open_items`, plus `bank_sync_batches` (idempotent provider refreshes) and
`invoices.due_date` (the bridge from a fiscal document to the scadenzario).

Reversible: `downgrade()` drops only what this revision created.

Revision ID: c0cdade466e9
Revises: 6250868682c8
Create Date: 2026-09-14 17:48:38.435426
"""
import sqlalchemy as sa

import app.shared.mixins  # noqa: F401 — provides app.shared.mixins.GUID below
from alembic import op


revision = 'c0cdade466e9'
down_revision = '6250868682c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('bank_accounts',
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('bank_name', sa.String(length=160), nullable=True),
    sa.Column('iban_last4', sa.String(length=4), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('provider_key', sa.String(length=60), nullable=False),
    sa.Column('provider_api_version', sa.String(length=20), nullable=True),
    sa.Column('provider_account_id', sa.String(length=160), nullable=False),
    sa.Column('credentials_ref', sa.String(length=120), nullable=True),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('connection_status', sa.String(length=24), nullable=False),
    sa.Column('connection_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sync_error', sa.Text(), nullable=True),
    sa.Column('balance_amount', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('balance_date', sa.Date(), nullable=True),
    sa.Column('balance_source', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('company_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('tenant_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', app.shared.mixins.GUID(), nullable=False),
    sa.CheckConstraint("balance_source IN ('provider', 'manual')", name='ck_balance_source_9fdaa83dcc0f'),
    sa.CheckConstraint("currency = 'EUR'", name='ck_currency_1bb44636ba6f'),
    sa.CheckConstraint('balance_amount IS NULL OR (balance_amount > -1000000000000000000 AND balance_amount < 1000000000000000000)', name='ck_balance_amount_2f0745114372'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'company_id', 'provider_key', 'provider_account_id', name='uq_bank_account_provider_ref')
    )
    op.create_index(op.f('ix_bank_accounts_company_id'), 'bank_accounts', ['company_id'], unique=False)
    op.create_index(op.f('ix_bank_accounts_tenant_id'), 'bank_accounts', ['tenant_id'], unique=False)
    op.create_table('bank_sync_batches',
    sa.Column('bank_account_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('provider_key', sa.String(length=60), nullable=False),
    sa.Column('provider_api_version', sa.String(length=20), nullable=True),
    sa.Column('environment', sa.String(length=20), nullable=False),
    sa.Column('window_start', sa.Date(), nullable=True),
    sa.Column('window_end', sa.Date(), nullable=True),
    sa.Column('fetched_count', sa.Integer(), nullable=False),
    sa.Column('inserted_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('actor_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('company_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('tenant_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', app.shared.mixins.GUID(), nullable=False),
    sa.CheckConstraint('fetched_count >= 0 AND inserted_count >= 0 AND duplicate_count >= 0', name='ck_fetched_count_c5bb1d5b2875'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['bank_account_id'], ['bank_accounts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'company_id', 'idempotency_key', name='uq_bank_sync_idempotency')
    )
    op.create_index(op.f('ix_bank_sync_batches_bank_account_id'), 'bank_sync_batches', ['bank_account_id'], unique=False)
    op.create_index(op.f('ix_bank_sync_batches_company_id'), 'bank_sync_batches', ['company_id'], unique=False)
    op.create_index(op.f('ix_bank_sync_batches_tenant_id'), 'bank_sync_batches', ['tenant_id'], unique=False)
    op.create_table('bank_transactions',
    sa.Column('bank_account_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('provider_tx_id', sa.String(length=160), nullable=False),
    sa.Column('booking_date', sa.Date(), nullable=False),
    sa.Column('value_date', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('counterparty_name', sa.String(length=300), nullable=True),
    sa.Column('counterparty_iban_last4', sa.String(length=4), nullable=True),
    sa.Column('description', sa.String(length=600), nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('sync_batch_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('company_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('tenant_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', app.shared.mixins.GUID(), nullable=False),
    sa.CheckConstraint("currency = 'EUR'", name='ck_currency_1bb44636ba6f'),
    sa.CheckConstraint('amount <> 0 AND amount > -1000000000000000000 AND amount < 1000000000000000000', name='ck_amount_207644f569ad'),
    sa.ForeignKeyConstraint(['bank_account_id'], ['bank_accounts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'bank_account_id', 'provider_tx_id', name='uq_bank_tx_provider_ref')
    )
    op.create_index(op.f('ix_bank_transactions_bank_account_id'), 'bank_transactions', ['bank_account_id'], unique=False)
    op.create_index(op.f('ix_bank_transactions_booking_date'), 'bank_transactions', ['booking_date'], unique=False)
    op.create_index(op.f('ix_bank_transactions_company_id'), 'bank_transactions', ['company_id'], unique=False)
    op.create_index(op.f('ix_bank_transactions_sync_batch_id'), 'bank_transactions', ['sync_batch_id'], unique=False)
    op.create_index(op.f('ix_bank_transactions_tenant_id'), 'bank_transactions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_bank_transactions_value_date'), 'bank_transactions', ['value_date'], unique=False)
    op.create_table('open_items',
    sa.Column('direction', sa.String(length=12), nullable=False),
    sa.Column('counterparty_name', sa.String(length=300), nullable=False),
    sa.Column('counterparty_vat', sa.String(length=32), nullable=True),
    sa.Column('document_number', sa.String(length=80), nullable=True),
    sa.Column('document_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('category', sa.String(length=120), nullable=True),
    sa.Column('cost_center_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=160), nullable=False),
    sa.Column('invoice_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('company_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('tenant_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', app.shared.mixins.GUID(), nullable=False),
    sa.CheckConstraint("currency = 'EUR'", name='ck_currency_1bb44636ba6f'),
    sa.CheckConstraint("direction IN ('receivable', 'payable')", name='ck_direction_073850a64fb5'),
    sa.CheckConstraint("source IN ('invoice', 'manual', 'import')", name='ck_source_57014e44fdf0'),
    sa.CheckConstraint('amount > 0 AND amount < 1000000000000000000', name='ck_amount_3fc0297920af'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'company_id', 'source', 'source_ref', name='uq_open_item_source_ref')
    )
    op.create_index(op.f('ix_open_items_company_id'), 'open_items', ['company_id'], unique=False)
    op.create_index(op.f('ix_open_items_direction'), 'open_items', ['direction'], unique=False)
    op.create_index(op.f('ix_open_items_due_date'), 'open_items', ['due_date'], unique=False)
    op.create_index(op.f('ix_open_items_invoice_id'), 'open_items', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_open_items_tenant_id'), 'open_items', ['tenant_id'], unique=False)
    op.create_table('reconciliation_allocations',
    sa.Column('open_item_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('bank_transaction_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=3, scale=2), nullable=True),
    sa.Column('engine_version', sa.String(length=40), nullable=True),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('reason', sa.String(length=300), nullable=True),
    sa.Column('actor_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('approved_by_id', app.shared.mixins.GUID(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('company_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('tenant_id', app.shared.mixins.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', app.shared.mixins.GUID(), nullable=False),
    sa.CheckConstraint("(bank_transaction_id IS NOT NULL) OR method IN ('write_off', 'cancellation')", name='ck_bank_transaction_id_f8fd222f4b81'),
    sa.CheckConstraint("method IN ('exact', 'fuzzy', 'manual', 'write_off', 'cancellation')", name='ck_method_0ec89a75ba09'),
    sa.CheckConstraint('amount > 0 AND amount < 1000000000000000000', name='ck_amount_3fc0297920af'),
    sa.CheckConstraint('confidence IS NULL OR (confidence >= 0 AND confidence <= 1)', name='ck_confidence_506af7cc409c'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['bank_transaction_id'], ['bank_transactions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['open_item_id'], ['open_items.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reconciliation_allocations_bank_transaction_id'), 'reconciliation_allocations', ['bank_transaction_id'], unique=False)
    op.create_index(op.f('ix_reconciliation_allocations_company_id'), 'reconciliation_allocations', ['company_id'], unique=False)
    op.create_index(op.f('ix_reconciliation_allocations_open_item_id'), 'reconciliation_allocations', ['open_item_id'], unique=False)
    op.create_index(op.f('ix_reconciliation_allocations_tenant_id'), 'reconciliation_allocations', ['tenant_id'], unique=False)
    # Existing invoices keep due_date NULL: the treasury refuses to invent a
    # due date and reports those documents as "skipped" instead.
    op.add_column('invoices', sa.Column('due_date', sa.Date(), nullable=True))
    op.create_index(op.f('ix_invoices_due_date'), 'invoices', ['due_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_invoices_due_date'), table_name='invoices')
    op.drop_column('invoices', 'due_date')
    op.drop_index(op.f('ix_reconciliation_allocations_tenant_id'), table_name='reconciliation_allocations')
    op.drop_index(op.f('ix_reconciliation_allocations_open_item_id'), table_name='reconciliation_allocations')
    op.drop_index(op.f('ix_reconciliation_allocations_company_id'), table_name='reconciliation_allocations')
    op.drop_index(op.f('ix_reconciliation_allocations_bank_transaction_id'), table_name='reconciliation_allocations')
    op.drop_table('reconciliation_allocations')
    op.drop_index(op.f('ix_open_items_tenant_id'), table_name='open_items')
    op.drop_index(op.f('ix_open_items_invoice_id'), table_name='open_items')
    op.drop_index(op.f('ix_open_items_due_date'), table_name='open_items')
    op.drop_index(op.f('ix_open_items_direction'), table_name='open_items')
    op.drop_index(op.f('ix_open_items_company_id'), table_name='open_items')
    op.drop_table('open_items')
    op.drop_index(op.f('ix_bank_transactions_value_date'), table_name='bank_transactions')
    op.drop_index(op.f('ix_bank_transactions_tenant_id'), table_name='bank_transactions')
    op.drop_index(op.f('ix_bank_transactions_sync_batch_id'), table_name='bank_transactions')
    op.drop_index(op.f('ix_bank_transactions_company_id'), table_name='bank_transactions')
    op.drop_index(op.f('ix_bank_transactions_booking_date'), table_name='bank_transactions')
    op.drop_index(op.f('ix_bank_transactions_bank_account_id'), table_name='bank_transactions')
    op.drop_table('bank_transactions')
    op.drop_index(op.f('ix_bank_sync_batches_tenant_id'), table_name='bank_sync_batches')
    op.drop_index(op.f('ix_bank_sync_batches_company_id'), table_name='bank_sync_batches')
    op.drop_index(op.f('ix_bank_sync_batches_bank_account_id'), table_name='bank_sync_batches')
    op.drop_table('bank_sync_batches')
    op.drop_index(op.f('ix_bank_accounts_tenant_id'), table_name='bank_accounts')
    op.drop_index(op.f('ix_bank_accounts_company_id'), table_name='bank_accounts')
    op.drop_table('bank_accounts')
