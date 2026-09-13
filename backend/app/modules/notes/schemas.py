import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteCreate(BaseModel):
    body: str = Field(min_length=1)
    entity_type: str = Field(min_length=1, max_length=40)
    entity_id: uuid.UUID
    pinned: bool = False


class NoteUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1)
    pinned: bool | None = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    body: str
    author_id: uuid.UUID | None
    pinned: bool
    entity_type: str
    entity_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
