"""Documents API — upload/download through authorised endpoints only.

Files are served exclusively via `GET /documents/{id}/download`: the
backend resolves tenant → document → version, then asks the storage
provider for bytes. No filesystem path is ever exposed to clients.
"""
import uuid
from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.documents import service
from app.modules.documents.schemas import (
    DocumentLinkCreate,
    DocumentStatusUpdate,
    RequirementCreate,
    RequirementFulfill,
    RequirementStatusUpdate,
    ValidationPayload,
)
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User

router = APIRouter(prefix="/documents", tags=["documents"])

READ = require_permissions("documents:read")
WRITE = require_permissions("documents:write")


# ---------------------------------------------------------------------------
# Registry & listing
# ---------------------------------------------------------------------------

@router.get("/types")
def document_types(db: Session = Depends(get_db),
                   ctx: TenantContext = Depends(get_tenant_ctx),
                   _: User = Depends(READ)):
    out = service.list_document_types(db, tenant_id=ctx.tenant_id)
    db.commit()
    return out


@router.get("")
def list_documents(company_id: uuid.UUID | None = None,
                   status: str | None = None,
                   expiring_within: int | None = Query(default=None, ge=0),
                   db: Session = Depends(get_db),
                   ctx: TenantContext = Depends(get_tenant_ctx),
                   _: User = Depends(READ)):
    return service.list_documents(db, tenant_id=ctx.tenant_id,
                                  company_id=company_id, status=status,
                                  expiring_within=expiring_within)


@router.get("/requirements/list")
def list_requirements(company_id: uuid.UUID | None = None,
                      practice_id: uuid.UUID | None = None,
                      status: str | None = None, module: str | None = None,
                      db: Session = Depends(get_db),
                      ctx: TenantContext = Depends(get_tenant_ctx),
                      _: User = Depends(READ)):
    return service.list_requirements(
        db, tenant_id=ctx.tenant_id, company_id=company_id,
        practice_id=practice_id, status=status, module=module)


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db),
                 ctx: TenantContext = Depends(get_tenant_ctx),
                 _: User = Depends(READ)):
    return service.get_document(db, tenant_id=ctx.tenant_id,
                                document_id=document_id)


# ---------------------------------------------------------------------------
# Upload & versions
# ---------------------------------------------------------------------------

@router.post("/companies/{company_id}/upload", status_code=201)
def upload_document(company_id: uuid.UUID,
                    file: UploadFile = File(...),
                    title: str | None = Form(default=None),
                    type_code: str | None = Form(default=None),
                    expires_on: date | None = Form(default=None),
                    notes: str | None = Form(default=None),
                    db: Session = Depends(get_db),
                    ctx: TenantContext = Depends(get_tenant_ctx),
                    user: User = Depends(WRITE)):
    out = service.upload_document(
        db, tenant_id=ctx.tenant_id, company_id=company_id,
        actor_id=user.id, stream=file.file,
        filename=file.filename or "file", title=title, type_code=type_code,
        mime_type=file.content_type, expires_on=expires_on, notes=notes)
    db.commit()
    return out


@router.post("/{document_id}/versions", status_code=201)
def add_version(document_id: uuid.UUID,
                file: UploadFile = File(...),
                expires_on: date | None = Form(default=None),
                notes: str | None = Form(default=None),
                db: Session = Depends(get_db),
                ctx: TenantContext = Depends(get_tenant_ctx),
                user: User = Depends(WRITE)):
    out = service.add_version(
        db, tenant_id=ctx.tenant_id, document_id=document_id,
        actor_id=user.id, stream=file.file,
        filename=file.filename or "file", mime_type=file.content_type,
        expires_on=expires_on, notes=notes)
    db.commit()
    return out


@router.get("/{document_id}/download")
def download_document(document_id: uuid.UUID,
                      version_id: uuid.UUID | None = None,
                      db: Session = Depends(get_db),
                      ctx: TenantContext = Depends(get_tenant_ctx),
                      _: User = Depends(READ)):
    stream, version, doc = service.open_version_stream(
        db, tenant_id=ctx.tenant_id, document_id=document_id,
        version_id=version_id)
    return StreamingResponse(
        stream, media_type=version.mime_type or "application/octet-stream",
        headers={"Content-Disposition":
                 f'attachment; filename="{version.original_filename}"',
                 "X-Checksum-SHA256": version.checksum_sha256})


# ---------------------------------------------------------------------------
# Validation & status
# ---------------------------------------------------------------------------

@router.post("/{document_id}/versions/{version_id}/validate")
def validate_version(document_id: uuid.UUID, version_id: uuid.UUID,
                     payload: ValidationPayload,
                     db: Session = Depends(get_db),
                     ctx: TenantContext = Depends(get_tenant_ctx),
                     user: User = Depends(WRITE)):
    out = service.validate_version(
        db, tenant_id=ctx.tenant_id, document_id=document_id,
        version_id=version_id, actor_id=user.id,
        result=payload.result, notes=payload.notes)
    db.commit()
    return out


@router.post("/{document_id}/status")
def set_status(document_id: uuid.UUID, payload: DocumentStatusUpdate,
               db: Session = Depends(get_db),
               ctx: TenantContext = Depends(get_tenant_ctx),
               user: User = Depends(WRITE)):
    out = service.set_document_status(
        db, tenant_id=ctx.tenant_id, document_id=document_id,
        actor_id=user.id, status=payload.status)
    db.commit()
    return out


@router.post("/{document_id}/links", status_code=201)
def link_document(document_id: uuid.UUID, payload: DocumentLinkCreate,
                  db: Session = Depends(get_db),
                  ctx: TenantContext = Depends(get_tenant_ctx),
                  user: User = Depends(WRITE)):
    out = service.link_document(
        db, tenant_id=ctx.tenant_id, document_id=document_id,
        actor_id=user.id, entity_type=payload.entity_type,
        entity_id=payload.entity_id)
    db.commit()
    return out


@router.post("/{document_id}/archive")
def archive_document(document_id: uuid.UUID, db: Session = Depends(get_db),
                     ctx: TenantContext = Depends(get_tenant_ctx),
                     user: User = Depends(WRITE)):
    out = service.archive_document(db, tenant_id=ctx.tenant_id,
                                   document_id=document_id,
                                   actor_id=user.id)
    db.commit()
    return out


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

@router.post("/companies/{company_id}/requirements", status_code=201)
def create_requirement(company_id: uuid.UUID, payload: RequirementCreate,
                       db: Session = Depends(get_db),
                       ctx: TenantContext = Depends(get_tenant_ctx),
                       user: User = Depends(WRITE)):
    out = service.create_requirement(
        db, tenant_id=ctx.tenant_id, company_id=company_id,
        actor_id=user.id, **payload.model_dump())
    db.commit()
    return out


@router.post("/requirements/{requirement_id}/status")
def update_requirement(requirement_id: uuid.UUID,
                       payload: RequirementStatusUpdate,
                       db: Session = Depends(get_db),
                       ctx: TenantContext = Depends(get_tenant_ctx),
                       user: User = Depends(WRITE)):
    out = service.update_requirement_status(
        db, tenant_id=ctx.tenant_id, requirement_id=requirement_id,
        actor_id=user.id, status=payload.status,
        document_id=payload.document_id, version_id=payload.version_id,
        notes=payload.notes)
    db.commit()
    return out


@router.post("/requirements/{requirement_id}/fulfill")
def fulfill_requirement(requirement_id: uuid.UUID,
                        payload: RequirementFulfill,
                        db: Session = Depends(get_db),
                        ctx: TenantContext = Depends(get_tenant_ctx),
                        user: User = Depends(WRITE)):
    out = service.fulfill_requirement(
        db, tenant_id=ctx.tenant_id, requirement_id=requirement_id,
        actor_id=user.id, document_id=payload.document_id)
    db.commit()
    return out
