import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ContactBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    role_title: str | None = Field(default=None, max_length=160)
    preferred_channel: str | None = Field(default=None, max_length=32)
    privacy_consent: bool = False
    owner_id: uuid.UUID | None = None


class ContactCreate(ContactBase):
    company_id: uuid.UUID | None = None
    relationship_role: str | None = None
    is_primary: bool = False


class ContactUpdate(BaseModel):
    version: int
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = None
    role_title: str | None = None
    preferred_channel: str | None = None
    privacy_consent: bool | None = None
    owner_id: uuid.UUID | None = None


class ContactOut(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CompanyContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    relationship_role: str | None
    is_primary: bool


class ContactDetail(ContactOut):
    companies: list[CompanyContactOut] = []


class LinkContactRequest(BaseModel):
    company_id: uuid.UUID
    relationship_role: str | None = None
    is_primary: bool = False
