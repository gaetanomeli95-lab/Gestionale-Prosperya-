"""tasks.sync_key: database-enforced exactly-once

Revision ID: b3d2f0a1c5e7
Revises: a7c1e3f9b2d4
Create Date: 2026-09-24

The deadline->task synchronisation (practices.service.sync_deadline_task)
relied on read-then-insert over a NON-unique index on tasks.sync_key. That is
idempotent for sequential calls but not under concurrent identical requests
or transaction retries. This adds a partial UNIQUE index on
(tenant_id, sync_key) for live rows so the database guarantees one task per
sync key; the service handles the conflict by re-reading.

Refuses to run if duplicates already exist (data must be reviewed by a
human, never silently merged).
"""
from alembic import op
from sqlalchemy import text

revision = 'b3d2f0a1c5e7'
down_revision = 'a7c1e3f9b2d4'
branch_labels = None
depends_on = None

INDEX = "uq_tasks_tenant_sync_key"
WHERE = "sync_key IS NOT NULL AND deleted_at IS NULL"


def upgrade() -> None:
    bind = op.get_bind()
    dupes = bind.execute(text(
        "SELECT tenant_id, sync_key, COUNT(*) FROM tasks "  # noqa: S608 — constant SQL, no user input
        f"WHERE {WHERE} GROUP BY tenant_id, sync_key HAVING COUNT(*) > 1")).fetchall()
    if dupes:
        raise RuntimeError(
            f"{len(dupes)} duplicated live (tenant_id, sync_key) pairs in tasks; "
            "resolve them before applying b3d2f0a1c5e7: " + ", ".join(str(d[:2]) for d in dupes[:5]))
    op.create_index(INDEX, "tasks", ["tenant_id", "sync_key"], unique=True,
                    postgresql_where=text(WHERE), sqlite_where=text(WHERE))


def downgrade() -> None:
    op.drop_index(INDEX, table_name="tasks")
