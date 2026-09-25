"""Document domain service — upload, immutable versioning, validation,
expiry and requirement lifecycle.

Every public function takes `tenant_id` explicitly and verifies ownership
before returning anything: a user must never reach a file by guessing an
id across tenants or companies.
"""
import io
import uuid
from datetime import date, datetime
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.activities.models import ActivityEvent
from app.modules.companies.models import Company
from app.modules.documents.models import (
    DOCUMENT_TYPE_SEED,
    Document,
    DocumentLink,
    DocumentRequirement,
    DocumentStatus,
    DocumentType,
    DocumentValidation,
    DocumentVersion,
    RequirementStatus,
    ValidationResult,
    VersionStatus,
)
from app.modules.documents.storage import (
    build_ref,
    get_storage,
    sanitize_filename,
    sha256_stream,
)
from app.shared.mixins import today as utc_today
from app.shared.mixins import utcnow


def _d(value) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _version_out(v: DocumentVersion) -> dict:
    return {
        "id": str(v.id), "document_id": str(v.document_id),
        "version_no": v.version_no,
        "original_filename": v.original_filename,
        "mime_type": v.mime_type, "file_size": v.file_size,
        "checksum_sha256": v.checksum_sha256,
        "storage_provider": v.storage_provider,
        "source": v.source, "status": v.status,
        "uploaded_by_id": str(v.uploaded_by_id) if v.uploaded_by_id else None,
        "uploaded_at": _d(v.uploaded_at),
        "expires_on": _d(v.expires_on), "notes": v.notes,
        "validations": [
            {"id": str(val.id),
             "validated_by_id": (str(val.validated_by_id)
                                 if val.validated_by_id else None),
             "validated_at": _d(val.validated_at),
             "result": val.result, "notes": val.notes}
            for val in v.validations
        ],
    }


def _document_out(doc: Document, *, detail: bool = False) -> dict:
    out = {
        "id": str(doc.id), "company_id": str(doc.company_id),
        "title": doc.title, "status": doc.status,
        "type_code": doc.doc_type.code if doc.doc_type else None,
        "type_label": doc.doc_type.label if doc.doc_type else None,
        "current_version_id": (str(doc.current_version_id)
                               if doc.current_version_id else None),
        "notes": doc.notes, "created_at": _d(doc.created_at),
    }
    if detail:
        out["versions"] = [_version_out(v) for v in doc.versions]
        out["links"] = [
            {"entity_type": link.entity_type,
             "entity_id": str(link.entity_id)}
            for link in doc.links
        ]
    return out


def _requirement_out(r: DocumentRequirement) -> dict:
    return {
        "id": str(r.id), "company_id": str(r.company_id),
        "practice_id": str(r.practice_id) if r.practice_id else None,
        "module": r.module, "doc_type_code": r.doc_type_code,
        "label": r.label, "mandatory": r.mandatory,
        "requires_validation": r.requires_validation,
        "due_at": _d(r.due_at), "status": r.status,
        "accepted_document_id": (str(r.accepted_document_id)
                                 if r.accepted_document_id else None),
        "accepted_version_id": (str(r.accepted_version_id)
                                if r.accepted_version_id else None),
        "source_ref": r.source_ref, "notes": r.notes,
        "created_at": _d(r.created_at),
    }


# ---------------------------------------------------------------------------
# Lookups — always tenant-scoped
# ---------------------------------------------------------------------------

def _company_or_404(db: Session, tenant_id, company_id) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id or company.deleted_at:
        raise NotFoundError("Azienda non trovata.")
    return company


def _document_or_404(db: Session, tenant_id, document_id) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id or doc.deleted_at:
        raise NotFoundError("Documento non trovato.")
    return doc


def _version_or_404(db: Session, doc: Document, version_id) -> DocumentVersion:
    v = db.get(DocumentVersion, version_id)
    if v is None or v.document_id != doc.id:
        raise NotFoundError("Versione del documento non trovata.")
    return v


def _requirement_or_404(db: Session, tenant_id, requirement_id) -> DocumentRequirement:
    r = db.get(DocumentRequirement, requirement_id)
    if r is None or r.tenant_id != tenant_id:
        raise NotFoundError("Requisito documentale non trovato.")
    return r


def _activity(db: Session, *, tenant_id, actor_id, event_type: str,
              entity_type: str, entity_id, summary: str,
              payload: dict | None = None) -> None:
    db.add(ActivityEvent(
        tenant_id=tenant_id, actor_id=actor_id, event_type=event_type,
        entity_type=entity_type, entity_id=entity_id, summary=summary,
        payload=payload or {}))


# ---------------------------------------------------------------------------
# Document types registry
# ---------------------------------------------------------------------------

def sync_document_types(db: Session, *, tenant_id) -> None:
    """Materialise the seed registry for a tenant (idempotent)."""
    existing = {t.code for t in db.scalars(
        select(DocumentType).where(DocumentType.tenant_id == tenant_id))}
    for row in DOCUMENT_TYPE_SEED:
        if row["code"] not in existing:
            db.add(DocumentType(tenant_id=tenant_id, **row))
    db.flush()


def list_document_types(db: Session, *, tenant_id) -> dict:
    sync_document_types(db, tenant_id=tenant_id)
    rows = db.scalars(
        select(DocumentType)
        .where(DocumentType.tenant_id == tenant_id,
               DocumentType.is_active.is_(True))
        .order_by(DocumentType.label)).all()
    return {"types": [
        {"id": str(t.id), "code": t.code, "label": t.label,
         "domain": t.domain, "tracks_expiry": t.tracks_expiry}
        for t in rows
    ]}


# ---------------------------------------------------------------------------
# Upload & versioning
# ---------------------------------------------------------------------------

def _store_version(db: Session, *, tenant_id, doc: Document, stream: BinaryIO,
                   filename: str, mime_type: str | None, actor_id,
                   source: str, expires_on: date | None,
                   notes: str | None) -> tuple[DocumentVersion, bool]:
    """Persist bytes + immutable version row. Returns (version, duplicate).

    Duplicate = same checksum already stored on this document — the caller
    gets the existing version back instead of a silent overwrite."""
    raw = stream.read()
    checksum, size = sha256_stream(io.BytesIO(raw))

    existing = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc.id,
               DocumentVersion.checksum_sha256 == checksum)).first()
    if existing is not None:
        return existing, True

    version_no = (db.scalar(
        select(func.max(DocumentVersion.version_no))
        .where(DocumentVersion.document_id == doc.id)) or 0) + 1
    version_id = uuid.uuid4()
    storage = get_storage()
    ref = build_ref(tenant_id=tenant_id, document_id=doc.id,
                    version_id=version_id, checksum=checksum,
                    filename=filename)
    storage.store(ref=ref, stream=io.BytesIO(raw))

    version = DocumentVersion(
        id=version_id, tenant_id=tenant_id, document_id=doc.id,
        version_no=version_no,
        original_filename=filename, mime_type=mime_type,
        file_size=size, checksum_sha256=checksum,
        storage_provider=storage.key, storage_ref=ref,
        source=source, uploaded_by_id=actor_id,
        expires_on=expires_on, notes=notes)
    db.add(version)

    # Supersede the previous current version.
    if doc.current_version_id and doc.current_version_id != version_id:
        prev = db.get(DocumentVersion, doc.current_version_id)
        if prev is not None:
            prev.status = VersionStatus.SUPERSEDED
    # Assign via the relationship (post_update=True): the version INSERT is
    # emitted before the document UPDATE, keeping the circular FK valid.
    doc.current_version = version
    db.flush()
    return version, False


def upload_document(db: Session, *, tenant_id, company_id, actor_id,
                    stream: BinaryIO, filename: str,
                    title: str | None = None,
                    type_code: str | None = None,
                    mime_type: str | None = None,
                    source: str = "upload",
                    expires_on: date | None = None,
                    notes: str | None = None,
                    links: list[dict] | None = None) -> dict:
    """Create a Document + its first immutable version."""
    company = _company_or_404(db, tenant_id, company_id)
    sync_document_types(db, tenant_id=tenant_id)

    type_id = None
    if type_code:
        dt = db.scalars(select(DocumentType).where(
            DocumentType.tenant_id == tenant_id,
            DocumentType.code == type_code)).first()
        if dt is None:
            raise ValidationError(f"Tipo documento sconosciuto: {type_code}.",
                                  code="document_type_unknown")
        type_id = dt.id
        if dt.tracks_expiry is False:
            expires_on = None

    doc = Document(tenant_id=tenant_id, company_id=company.id,
                   type_id=type_id,
                   title=title or sanitize_filename(filename),
                   status=DocumentStatus.RECEIVED, notes=notes)
    db.add(doc)
    db.flush()

    version, duplicate = _store_version(
        db, tenant_id=tenant_id, doc=doc, stream=stream, filename=filename,
        mime_type=mime_type, actor_id=actor_id, source=source,
        expires_on=expires_on, notes=notes)

    for link in links or []:
        db.add(DocumentLink(tenant_id=tenant_id, document_id=doc.id,
                            entity_type=link["entity_type"],
                            entity_id=link["entity_id"],
                            created_by_id=actor_id))

    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="document_uploaded", entity_type="document",
              entity_id=doc.id,
              summary=f"Documento caricato: {doc.title}",
              payload={"version_no": version.version_no,
                       "checksum": version.checksum_sha256})
    db.flush()
    out = _document_out(doc, detail=True)
    out["duplicate_content"] = duplicate
    return out


def add_version(db: Session, *, tenant_id, document_id, actor_id,
                stream: BinaryIO, filename: str,
                mime_type: str | None = None,
                source: str = "upload",
                expires_on: date | None = None,
                notes: str | None = None) -> dict:
    """Append an immutable version. The document status resets to RECEIVED —
    a new file always re-enters the review flow."""
    doc = _document_or_404(db, tenant_id, document_id)
    version, duplicate = _store_version(
        db, tenant_id=tenant_id, doc=doc, stream=stream, filename=filename,
        mime_type=mime_type, actor_id=actor_id, source=source,
        expires_on=expires_on, notes=notes)
    if not duplicate:
        doc.status = DocumentStatus.RECEIVED
        _activity(db, tenant_id=tenant_id, actor_id=actor_id,
                  event_type="document_version_added", entity_type="document",
                  entity_id=doc.id,
                  summary=f"Nuova versione v{version.version_no}: {doc.title}",
                  payload={"version_no": version.version_no})
    db.flush()
    out = _version_out(version)
    out["duplicate_content"] = duplicate
    return out


def get_document(db: Session, *, tenant_id, document_id) -> dict:
    return _document_out(_document_or_404(db, tenant_id, document_id),
                         detail=True)


def list_documents(db: Session, *, tenant_id, company_id=None,
                   status: str | None = None,
                   expiring_within: int | None = None) -> dict:
    stmt = (select(Document)
            .where(Document.tenant_id == tenant_id,
                   Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc()))
    if company_id:
        stmt = stmt.where(Document.company_id == company_id)
    if status:
        stmt = stmt.where(Document.status == status)
    rows = db.scalars(stmt).all()
    if expiring_within is not None:
        horizon = utc_today().toordinal() + expiring_within
        rows = [d for d in rows
                if d.current_version and d.current_version.expires_on
                and d.current_version.expires_on.toordinal() <= horizon]
    return {"documents": [_document_out(d) for d in rows]}


def open_version_stream(db: Session, *, tenant_id, document_id,
                        version_id=None) -> tuple[BinaryIO, DocumentVersion, Document]:
    """Authorised read: resolves tenant → document → version, then asks the
    provider for the bytes. Never exposes a filesystem path."""
    doc = _document_or_404(db, tenant_id, document_id)
    if version_id is None:
        if doc.current_version_id is None:
            raise NotFoundError("Il documento non ha contenuti.")
        version = db.get(DocumentVersion, doc.current_version_id)
    else:
        version = _version_or_404(db, doc, version_id)
    storage = get_storage(version.storage_provider)
    return storage.open(ref=version.storage_ref), version, doc


# ---------------------------------------------------------------------------
# Validation lifecycle — human decision only
# ---------------------------------------------------------------------------

def validate_version(db: Session, *, tenant_id, document_id, version_id,
                     actor_id, result: str,
                     notes: str | None = None) -> dict:
    doc = _document_or_404(db, tenant_id, document_id)
    version = _version_or_404(db, doc, version_id)
    if result not in {r.value for r in ValidationResult}:
        raise ValidationError("Esito validazione non valido.",
                              code="document_validation_result")
    db.add(DocumentValidation(
        tenant_id=tenant_id, version_id=version.id,
        validated_by_id=actor_id, result=result, notes=notes))
    doc.status = (DocumentStatus.VALIDATED
                  if result == ValidationResult.VALIDATED
                  else DocumentStatus.REJECTED)
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type=f"document_{result}", entity_type="document",
              entity_id=doc.id,
              summary=f"Documento {result}: {doc.title} "
                      f"(v{version.version_no})",
              payload={"version_no": version.version_no, "notes": notes})
    db.flush()
    return _document_out(doc, detail=True)


def set_document_status(db: Session, *, tenant_id, document_id, actor_id,
                        status: str) -> dict:
    """Explicit status moves that aren't validation outcomes (to_review,
    archived). Expired/superseded are system-managed."""
    doc = _document_or_404(db, tenant_id, document_id)
    allowed = {DocumentStatus.TO_REVIEW, DocumentStatus.ARCHIVED,
               DocumentStatus.RECEIVED}
    if status not in allowed:
        raise ValidationError(
            f"Stato non impostabile manualmente: {status}.",
            code="document_status")
    doc.status = status
    db.flush()
    return _document_out(doc, detail=True)


def refresh_expired(db: Session, *, tenant_id,
                    as_of: date | None = None) -> int:
    """Mark documents whose current version is past expiry. Deterministic —
    unknown expiry stays null and never expires."""
    as_of = as_of or utc_today()
    docs = db.scalars(
        select(Document)
        .join(DocumentVersion,
              Document.current_version_id == DocumentVersion.id)
        .where(Document.tenant_id == tenant_id,
               Document.deleted_at.is_(None),
               Document.status.notin_([DocumentStatus.EXPIRED,
                                       DocumentStatus.ARCHIVED,
                                       DocumentStatus.SUPERSEDED]),
               DocumentVersion.expires_on.is_not(None),
               DocumentVersion.expires_on < as_of)).all()
    for doc in docs:
        doc.status = DocumentStatus.EXPIRED
    db.flush()
    return len(docs)


# ---------------------------------------------------------------------------
# Requirements — the shared checklist
# ---------------------------------------------------------------------------

def _sync_practice_blockers(db: Session, *, tenant_id, req: DocumentRequirement, actor_id) -> None:
    """A requirement attached to a practice drives that practice's
    missing-document blockers. Keep them in step on every status change so
    the generic module behaves exactly like the funding path does.
    Lazy import: practices.service imports this module."""
    if req.practice_id is None:
        return
    from app.modules.practices import service as practice_service
    practice_service.sync_document_blockers(
        db, tenant_id=tenant_id, practice_id=req.practice_id, actor_id=actor_id)


def create_requirement(db: Session, *, tenant_id, company_id, actor_id,
                       doc_type_code: str, label: str,
                       module: str = "generic",
                       practice_id=None, mandatory: bool = True,
                       requires_validation: bool = False,
                       due_at: datetime | None = None,
                       source_ref: str | None = None,
                       notes: str | None = None) -> dict:
    _company_or_404(db, tenant_id, company_id)
    req = DocumentRequirement(
        tenant_id=tenant_id, company_id=company_id,
        practice_id=practice_id, module=module,
        doc_type_code=doc_type_code, label=label, mandatory=mandatory,
        requires_validation=requires_validation, due_at=due_at,
        status=RequirementStatus.MISSING, source_ref=source_ref,
        notes=notes)
    db.add(req)
    db.flush()
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="document_required", entity_type="document_requirement",
              entity_id=req.id, summary=f"Documento richiesto: {label}",
              payload={"module": module, "mandatory": mandatory})
    _sync_practice_blockers(db, tenant_id=tenant_id, req=req, actor_id=actor_id)
    return _requirement_out(req)


def list_requirements(db: Session, *, tenant_id, company_id=None,
                      practice_id=None, status: str | None = None,
                      module: str | None = None) -> dict:
    stmt = (select(DocumentRequirement)
            .where(DocumentRequirement.tenant_id == tenant_id)
            .order_by(DocumentRequirement.created_at.desc()))
    if company_id:
        stmt = stmt.where(DocumentRequirement.company_id == company_id)
    if practice_id:
        stmt = stmt.where(DocumentRequirement.practice_id == practice_id)
    if status:
        stmt = stmt.where(DocumentRequirement.status == status)
    if module:
        stmt = stmt.where(DocumentRequirement.module == module)
    rows = db.scalars(stmt).all()
    return {"requirements": [_requirement_out(r) for r in rows]}


def update_requirement_status(db: Session, *, tenant_id, requirement_id,
                              actor_id, status: str,
                              document_id=None, version_id=None,
                              notes: str | None = None) -> dict:
    """Move a requirement through its lifecycle. RECEIVED/VALIDATED may
    carry the accepted document/version pointers."""
    req = _requirement_or_404(db, tenant_id, requirement_id)
    if status not in {s.value for s in RequirementStatus}:
        raise ValidationError("Stato requisito non valido.",
                              code="requirement_status")
    if document_id is not None:
        doc = _document_or_404(db, tenant_id, document_id)
        req.accepted_document_id = doc.id
        if version_id is not None:
            req.accepted_version_id = _version_or_404(db, doc, version_id).id
        elif doc.current_version_id:
            req.accepted_version_id = doc.current_version_id
    req.status = status
    if notes:
        req.notes = notes
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="document_requirement_updated",
              entity_type="document_requirement", entity_id=req.id,
              summary=f"Requisito \"{req.label}\": {status}",
              payload={"status": status})
    db.flush()
    _sync_practice_blockers(db, tenant_id=tenant_id, req=req, actor_id=actor_id)
    return _requirement_out(req)


def fulfill_requirement(db: Session, *, tenant_id, requirement_id, actor_id,
                        document_id) -> dict:
    """Attach an uploaded document to a requirement. Status becomes
    VALIDATED when the document is already validated and validation is
    required, otherwise RECEIVED."""
    req = _requirement_or_404(db, tenant_id, requirement_id)
    doc = _document_or_404(db, tenant_id, document_id)
    if doc.company_id != req.company_id:
        raise ValidationError(
            "Il documento appartiene a un'altra azienda.",
            code="requirement_company_mismatch")
    req.accepted_document_id = doc.id
    req.accepted_version_id = doc.current_version_id
    if req.requires_validation and doc.status != DocumentStatus.VALIDATED:
        req.status = RequirementStatus.RECEIVED
    elif doc.status == DocumentStatus.VALIDATED:
        req.status = RequirementStatus.VALIDATED
    else:
        req.status = RequirementStatus.RECEIVED
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="document_requirement_fulfilled",
              entity_type="document_requirement", entity_id=req.id,
              summary=f"Requisito \"{req.label}\" soddisfatto da \"{doc.title}\": {req.status}",
              payload={"document_id": str(doc.id), "status": req.status})
    db.flush()
    _sync_practice_blockers(db, tenant_id=tenant_id, req=req, actor_id=actor_id)
    return _requirement_out(req)


def link_document(db: Session, *, tenant_id, document_id, actor_id,
                  entity_type: str, entity_id) -> dict:
    doc = _document_or_404(db, tenant_id, document_id)
    link = DocumentLink(tenant_id=tenant_id, document_id=doc.id,
                        entity_type=entity_type, entity_id=entity_id,
                        created_by_id=actor_id)
    db.add(link)
    db.flush()
    return {"id": str(link.id), "entity_type": entity_type,
            "entity_id": str(entity_id)}


def archive_document(db: Session, *, tenant_id, document_id, actor_id) -> dict:
    """Soft-delete policy: archive, never hard-delete operational evidence."""
    doc = _document_or_404(db, tenant_id, document_id)
    doc.status = DocumentStatus.ARCHIVED
    doc.deleted_at = utcnow()
    _activity(db, tenant_id=tenant_id, actor_id=actor_id,
              event_type="document_archived", entity_type="document",
              entity_id=doc.id, summary=f"Documento archiviato: {doc.title}")
    db.flush()
    return _document_out(doc, detail=True)
