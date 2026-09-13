import uuid

from pydantic import BaseModel, ConfigDict, Field


class ServiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    sort_order: int


class ServiceLineCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    sort_order: int = 0


class PipelineStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_line_id: uuid.UUID | None
    name: str
    position: int
    default_probability: int | None
    is_won: bool
    is_lost: bool
    is_active: bool


class PipelineStageCreate(BaseModel):
    service_line_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    position: int = 0
    default_probability: int | None = Field(default=None, ge=0, le=100)
    is_won: bool = False
    is_lost: bool = False
