"""Exactly-once for deadline -> task synchronisation (mission §24).

Before b3d2f0a1c5e7 the guarantee was a read-then-insert over a non-unique
index: fine sequentially, wrong under concurrent identical requests. Now the
database enforces one live task per (tenant_id, sync_key) and the service
survives the conflict by adopting the winner.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.modules.practices import service as practice_service
from app.modules.practices.models import Practice
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tenancy.models import Tenant
from app.modules.users.models import User

API = "/api/v1"


@pytest.fixture()
def ctx(client, admin_headers):
    cid = client.post(f"{API}/companies", headers=admin_headers,
                      json={"legal_name": f"Exactly Once {uuid.uuid4().hex[:6]} Srl",
                            "country": "IT"}).json()["id"]
    pid = client.post(f"{API}/practices/companies/{cid}", headers=admin_headers,
                      json={"title": "Scadenza", "practice_type": "generic"}).json()["id"]
    with SessionLocal() as db:
        p = db.get(Practice, uuid.UUID(pid))
        admin = db.scalar(select(User).where(User.email == "admin@prosperya.it"))
        return {"tenant_id": p.tenant_id, "practice_id": p.id, "actor_id": admin.id}


def _sync(db, ctx, due, title="Consegna", kind="deadline"):
    return practice_service.sync_deadline_task(
        db, tenant_id=ctx["tenant_id"], practice_id=ctx["practice_id"],
        actor_id=ctx["actor_id"], title=title, due_at=due, kind=kind)


def _live_tasks(db, ctx):
    return db.scalars(select(Task).where(Task.entity_id == ctx["practice_id"],
                                         Task.deleted_at.is_(None))).all()


def test_repeated_sync_reuses_one_task(ctx):
    due = datetime.now(UTC) + timedelta(days=3)
    with SessionLocal() as db:
        t1 = _sync(db, ctx, due)
        t2 = _sync(db, ctx, due, title="Consegna (aggiornata)")
        db.commit()
        assert t1.id == t2.id
        tasks = _live_tasks(db, ctx)
        assert len(tasks) == 1 and tasks[0].title == "Consegna (aggiornata)"


def test_database_rejects_duplicate_live_sync_key(ctx):
    """The constraint, independent of the service."""
    with SessionLocal() as db:
        due = datetime.now(UTC) + timedelta(days=1)
        _sync(db, ctx, due)
        db.commit()
        key = db.scalars(select(Task.sync_key).where(Task.entity_id == ctx["practice_id"])).first()
        db.add(Task(tenant_id=ctx["tenant_id"], title="dup", status=TaskStatus.TODO,
                    entity_type="practice", entity_id=ctx["practice_id"], sync_key=key))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_soft_deleted_task_does_not_block_resync(ctx):
    with SessionLocal() as db:
        due = datetime.now(UTC) + timedelta(days=2)
        t = _sync(db, ctx, due)
        t.deleted_at = datetime.now(UTC)
        db.commit()
        t2 = _sync(db, ctx, due)
        db.commit()
        assert t2.id != t.id
        assert len(_live_tasks(db, ctx)) == 1


def test_lost_race_adopts_winner(ctx, monkeypatch):
    """Simulate two requests racing on the same key: the second one's read
    sees nothing (stale), its insert hits the unique index, and it must return
    the row the first request created — not raise, not duplicate."""
    due = datetime.now(UTC) + timedelta(days=5)
    with SessionLocal() as winner:
        w = _sync(winner, ctx, due)
        winner.commit()
        winner_id = w.id

    with SessionLocal() as loser:
        real_scalars = loser.scalars
        calls = {"n": 0}

        class _Empty:
            def first(self): return None
            def all(self): return []

        def stale_first_read(stmt, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1 and "tasks" in str(stmt):
                return _Empty()          # pretend the winner's row is not visible yet
            return real_scalars(stmt, *a, **kw)

        monkeypatch.setattr(loser, "scalars", stale_first_read)
        adopted = _sync(loser, ctx, due, title="dal perdente")
        loser.commit()
        assert adopted.id == winner_id

    with SessionLocal() as db:
        tasks = _live_tasks(db, ctx)
        assert len(tasks) == 1 and tasks[0].title == "dal perdente"


def test_other_tenant_may_use_same_sync_key(ctx):
    """Uniqueness is per tenant."""
    with SessionLocal() as db:
        other = db.scalar(select(Tenant).where(Tenant.id != ctx["tenant_id"]))
        assert other is not None
        due = datetime.now(UTC) + timedelta(days=4)
        _sync(db, ctx, due)
        db.commit()
        key = db.scalars(select(Task.sync_key).where(Task.entity_id == ctx["practice_id"])).first()
        db.add(Task(tenant_id=other.id, title="stesso key, altro tenant",
                    status=TaskStatus.TODO, sync_key=key))
        db.flush()
        db.rollback()
