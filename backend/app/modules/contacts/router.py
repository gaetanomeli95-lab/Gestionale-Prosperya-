from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.companies.models import Company
from app.modules.contacts.models import CompanyContact, Contact
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactDetail,
    ContactOut,
    ContactUpdate,
    LinkContactRequest,
)
from app.modules.tenancy.context import TenantContext, get_tenant_ctx
from app.modules.users.models import User
from app.shared.events import record_activity, record_audit
from app.shared.mixins import utcnow
from app.shared.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _get_contact_or_404(db: Session, contact_id: UUID, ctx: TenantContext) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None or contact.tenant_id != ctx.tenant_id or contact.deleted_at is not None:
        raise NotFoundError("Contact not found.")
    return contact


def _check_email_duplicate(
    db: Session, ctx: TenantContext, email: str | None, exclude_id=None
) -> None:
    if not email:
        return
    stmt = select(Contact).where(
        Contact.tenant_id == ctx.tenant_id,
        func.lower(Contact.email) == email.lower(),
        Contact.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Contact.id != exclude_id)
    existing = db.scalars(stmt).first()
    if existing:
        raise ConflictError(
            f"A contact with this email already exists: {existing.first_name} {existing.last_name}.",
            code="duplicate_contact",
            details={"contact_id": str(existing.id)},
        )


@router.get("", response_model=Page[ContactOut])
def list_contacts(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: str | None = None,
    company_id: UUID | None = Query(default=None, description="Only contacts linked to this company"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("contacts:read")),
):
    stmt = select(Contact).where(
        Contact.tenant_id == ctx.tenant_id, Contact.deleted_at.is_(None)
    )
    if company_id is not None:
        # Tenant-scoped through the company: a foreign company id yields an empty page, never a leak.
        stmt = stmt.join(CompanyContact, CompanyContact.contact_id == Contact.id).join(
            Company, Company.id == CompanyContact.company_id
        ).where(Company.id == company_id, Company.tenant_id == ctx.tenant_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Contact.first_name.ilike(like),
                Contact.last_name.ilike(like),
                Contact.email.ilike(like),
                Contact.phone.ilike(like),
            )
        )
    return paginate(
        db, stmt.order_by(Contact.last_name, Contact.first_name),
        PageParams(page, page_size), ContactOut,
    )


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(
    payload: ContactCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("contacts:write")),
):
    _check_email_duplicate(db, ctx, payload.email)
    data = payload.model_dump(exclude={"company_id", "relationship_role", "is_primary"})
    contact = Contact(**data, tenant_id=ctx.tenant_id)
    db.add(contact)
    db.flush()
    if payload.company_id:
        _link(db, ctx, contact.id, payload, actor.id)
    record_activity(
        db, tenant_id=ctx.tenant_id, actor_id=actor.id, event_type="contact.created",
        entity_type="contact",
        entity_id=contact.id, summary=f"Contact {contact.first_name} {contact.last_name} created",
    )
    record_audit(db, actor_id=actor.id, action="contact.create", entity_type="contact",
                 entity_id=contact.id, tenant_id=ctx.tenant_id)
    db.commit()
    return ContactOut.model_validate(contact)


def _link(
    db: Session, ctx: TenantContext, contact_id: UUID,
    payload: LinkContactRequest | ContactCreate, actor_id,
) -> None:
    company = db.get(Company, payload.company_id)
    if (
        company is None
        or company.tenant_id != ctx.tenant_id
        or company.deleted_at is not None
    ):
        raise ValidationError("The specified company does not exist.", code="invalid_company")
    exists = db.scalar(
        select(CompanyContact).where(
            CompanyContact.company_id == payload.company_id,
            CompanyContact.contact_id == contact_id,
        )
    )
    if exists:
        raise ConflictError("This contact is already linked to the company.", code="already_linked")
    db.add(
        CompanyContact(
            company_id=payload.company_id,
            contact_id=contact_id,
            relationship_role=payload.relationship_role,
            is_primary=payload.is_primary,
        )
    )
    db.flush()


@router.get("/{contact_id}", response_model=ContactDetail)
def get_contact(
    contact_id: UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: User = Depends(require_permissions("contacts:read")),
):
    contact = _get_contact_or_404(db, contact_id, ctx)
    out = ContactDetail.model_validate(contact)
    out.companies = [
        {"company_id": link.company_id, "relationship_role": link.relationship_role,
         "is_primary": link.is_primary}
        for link in contact.companies
    ]
    return out


@router.post("/{contact_id}/links", status_code=201)
def link_contact(
    contact_id: UUID,
    payload: LinkContactRequest,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("contacts:write")),
):
    contact = _get_contact_or_404(db, contact_id, ctx)
    _link(db, ctx, contact.id, payload, actor.id)
    record_activity(
        db, tenant_id=ctx.tenant_id, actor_id=actor.id, event_type="contact.linked",
        entity_type="contact",
        entity_id=contact.id, summary=f"Contact linked to company {payload.company_id}",
    )
    db.commit()
    return {"ok": True}


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: UUID,
    payload: ContactUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("contacts:write")),
):
    contact = _get_contact_or_404(db, contact_id, ctx)
    if payload.version != contact.version:
        raise ConflictError(
            "This record was modified by someone else. Reload and try again.",
            code="stale_version",
        )
    if payload.email:
        _check_email_duplicate(db, ctx, payload.email, exclude_id=contact.id)
    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    for k, v in data.items():
        setattr(contact, k, v)
    contact.version += 1
    record_audit(
        db, actor_id=actor.id, action="contact.update", entity_type="contact",
        entity_id=contact.id, tenant_id=ctx.tenant_id, changes={"fields": sorted(data)},
    )
    db.commit()
    return ContactOut.model_validate(contact)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(
    contact_id: UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_ctx),
    actor: User = Depends(require_permissions("contacts:write")),
):
    contact = _get_contact_or_404(db, contact_id, ctx)
    contact.deleted_at = utcnow()
    contact.version += 1
    record_audit(db, actor_id=actor.id, action="contact.delete", entity_type="contact",
                 entity_id=contact.id, tenant_id=ctx.tenant_id)
    db.commit()
