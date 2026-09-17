"""Request schemas for the practices API."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PracticeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    practice_type: str = "generic"
    description: str | None = None
    owner_id: uuid.UUID | None = None
    priority: str = "medium"
    target_date: datetime | None = None
    source_module: str | None = Field(default=None, max_length=40)
    external_ref: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class PracticeTransition(BaseModel):
    action: str
    note: str | None = None


class BlockerCreate(BaseModel):
    kind: str
    detail: str | None = Field(default=None, max_length=500)
    ref_type: str | None = Field(default=None, max_length=40)
    ref_id: uuid.UUID | None = None


class ClientRequestCreate(BaseModel):
    item: str = Field(min_length=1, max_length=300)
    practice_id: uuid.UUID | None = None
    description: str | None = None
    due_at: datetime | None = None
    notes: str | None = None
    send: bool = True


class ClientRequestTransition(BaseModel):
    action: str
    notes: str | None = None


class DeadlineSync(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime
    kind: str = Field(default="deadline", max_length=40)
    priority: str = "high"
