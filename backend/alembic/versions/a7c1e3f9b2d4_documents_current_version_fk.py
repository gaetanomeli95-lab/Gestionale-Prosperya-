"""documents.current_version_id foreign key (PostgreSQL integrity fix)

Revision ID: a7c1e3f9b2d4
Revises: fddef49e1556
Create Date: 2026-09-24

Found while validating the schema on PostgreSQL. The ORM declares
`documents.current_version_id -> document_versions.id` with `use_alter=True`
(circular FK). Alembic's `create_table` correctly omits such constraints from
CREATE TABLE and expects a separate `create_foreign_key`, which the generated
migration fddef49e1556 never emitted. SQLite inlines the FK anyway, so the two
dialects diverged: PostgreSQL databases had NO referential integrity on this
column. This migration adds the constraint where it is missing and is
idempotent on both dialects.
"""
from alembic import op
from sqlalchemy import inspect

revision = 'a7c1e3f9b2d4'
down_revision = 'fddef49e1556'
branch_labels = None
depends_on = None

FK_NAME = "documents_current_version_id_fkey"


def _has_fk(bind) -> bool:
    for fk in inspect(bind).get_foreign_keys("documents"):
        if fk["constrained_columns"] == ["current_version_id"]:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    if _has_fk(bind):
        return  # SQLite (inlined) or already repaired
    if bind.dialect.name == "sqlite":
        # Unreachable in practice (SQLite inlines the FK); batch mode would be
        # required to add one, and nothing to fix.
        return
    op.create_foreign_key(FK_NAME, "documents", "document_versions",
                          ["current_version_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # inlined by the original CREATE TABLE; nothing added here
    if _has_fk(bind):
        op.drop_constraint(FK_NAME, "documents", type_="foreignkey")
