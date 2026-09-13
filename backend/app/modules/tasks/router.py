from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskOut, TaskUpdate
from app.modules.users.models import User
from app.shared.events import record_activity, record_audit
from app.shared.mixins import utcnow
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_or_404(db: Session, task_id: UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise NotFoundError("Task not found.")
    return task


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: TaskStatus | None = None,
    owner_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    overdue: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("tasks:read")),
):
    stmt = select(Task).where(Task.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Task.status == status)
    else:
        stmt = stmt.where(Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]))
    if owner_id:
        stmt = stmt.where(Task.owner_id == owner_id)
    if entity_type:
        stmt = stmt.where(Task.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(Task.entity_id == entity_id)
    if overdue:
        stmt = stmt.where(Task.due_date < utcnow())
    return paginate(
        db, stmt.order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc()),
        PageParams(page, page_size), TaskOut,
    )


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("tasks:write")),
):
    task = Task(**payload.model_dump(), created_by_id=actor.id)
    db.add(task)
    db.flush()
    if task.entity_type and task.entity_id:
        record_activity(
            db, actor_id=actor.id, event_type="task.created",
            entity_type=task.entity_type, entity_id=task.entity_id,
            summary=f"Task created: {task.title}",
        )
    record_audit(db, actor_id=actor.id, action="task.create", entity_type="task", entity_id=task.id)
    db.commit()
    return TaskOut.model_validate(task)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("tasks:write")),
):
    task = _get_or_404(db, task_id)
    data = payload.model_dump(exclude_unset=True)
    was_open = task.status != TaskStatus.DONE
    for k, v in data.items():
        setattr(task, k, v)
    if task.status == TaskStatus.DONE and was_open:
        task.completed_at = utcnow()
        if task.entity_type and task.entity_id:
            record_activity(
                db, actor_id=actor.id, event_type="task.completed",
                entity_type=task.entity_type, entity_id=task.entity_id,
                summary=f"Task completed: {task.title}",
            )
    elif task.status != TaskStatus.DONE:
        task.completed_at = None
    record_audit(
        db, actor_id=actor.id, action="task.update", entity_type="task",
        entity_id=task.id, changes={"fields": sorted(data)},
    )
    db.commit()
    return TaskOut.model_validate(task)


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("tasks:write")),
):
    task = _get_or_404(db, task_id)
    task.deleted_at = utcnow()
    record_audit(db, actor_id=actor.id, action="task.delete", entity_type="task", entity_id=task.id)
    db.commit()
