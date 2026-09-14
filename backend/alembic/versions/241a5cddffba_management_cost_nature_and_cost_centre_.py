"""management: cost nature and cost centre on categories

Classification is reference data on `management_categories`, never on the
append-only `actuals`: contribution margin and break-even are re-derived at
read time, so a reclassification never rewrites history (ADR-019).

`cost_nature` stays nullable because *unclassified* is a real state that
blocks the break-even calculation instead of being guessed.

Reversible. Uses batch mode so FK and CHECK exist on both dialects: plain
ALTERs on PostgreSQL, table copy on SQLite (which cannot ALTER ADD
CONSTRAINT).
"""
import sqlalchemy as sa

import app.shared.mixins  # noqa: F401 — provides app.shared.mixins.GUID below
from alembic import op

COST_NATURE_CHECK = "cost_nature IS NULL OR cost_nature IN ('fixed', 'variable')"
COST_NATURE_CHECK_NAME = "ck_cost_nature_managed_values"
FK_NAME = "fk_management_categories_cost_center"


revision = '241a5cddffba'
down_revision = 'c0cdade466e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing cost centres are active: server_default keeps the NOT NULL
    # column addable on a populated table.
    op.add_column('cost_centers',
                  sa.Column('is_active', sa.Boolean(), nullable=False,
                            server_default=sa.true()))
    with op.batch_alter_table('management_categories') as batch:
        batch.add_column(sa.Column('cost_nature', sa.String(length=10), nullable=True))
        batch.add_column(sa.Column('cost_center_id', app.shared.mixins.GUID(), nullable=True))
        batch.create_index(op.f('ix_management_categories_cost_center_id'),
                           ['cost_center_id'], unique=False)
        batch.create_foreign_key(FK_NAME, 'cost_centers',
                                 ['cost_center_id'], ['id'], ondelete='SET NULL')
        batch.create_check_constraint(COST_NATURE_CHECK_NAME, COST_NATURE_CHECK)


def downgrade() -> None:
    with op.batch_alter_table('management_categories') as batch:
        batch.drop_constraint(COST_NATURE_CHECK_NAME, type_='check')
        batch.drop_constraint(FK_NAME, type_='foreignkey')
        batch.drop_index(op.f('ix_management_categories_cost_center_id'))
        batch.drop_column('cost_center_id')
        batch.drop_column('cost_nature')
    op.drop_column('cost_centers', 'is_active')
