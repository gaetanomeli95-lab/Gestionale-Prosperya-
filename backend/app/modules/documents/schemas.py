"""Request schemas for the documents API."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class RequirementCreate(BaseModel):
    doc_type_code: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=300)
    module: str = Field(default="generic", max_length=40)
    practice_id: uuid.UUID | None = None
    mandatory: bool = True
    requires_validation: bool = False
    due_at: datetime | None = None
    source_ref: str | None = Field(default=None, max_length=80)
    notes: str | None = None


class RequirementStatusUpdate(BaseModel):
    status: str
    document_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    notes: str | None = None


class RequirementFulfill(BaseModel):
    document_id: uuid.UUID


class ValidationPayload(BaseModel):
    result: str  # validated | rejected
    notes: str | None = None


class DocumentStatusUpdate(BaseModel):
    status: str  # to_review | archived | received


class DocumentLinkCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=40)
    entity_id: uuid.UUID


class VersionMeta(BaseModel):
    """Optional metadata accepted alongside a multipart upload."""
    expires_on: date | None = None
    notes: str | None = None
