import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.tasks.models import TaskPriority, TaskStatus


class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    owner_id: uuid.UUID | None = None
    due_date: datetime | None = None
    reminder_at: datetime | None = None
    entity_type: str | None = Field(default=None, max_length=40)
    entity_id: uuid.UUID | None = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    owner_id: uuid.UUID | None = None
    due_date: datetime | None = None
    reminder_at: datetime | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None


class TaskOut(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
