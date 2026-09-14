"""Role-based access control.

Backend authorization is authoritative. Scopes use the form
`<domain>:<action>`; `*` wildcards are supported. Frontend may hide UI
elements for ergonomics, but every mutating endpoint re-checks here.
"""
from collections.abc import Iterable
from enum import StrEnum
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db import get_db


class Role(StrEnum):
    # Platform-operator staff (can switch tenant context via X-Tenant-Id)
    ADMIN = "admin"
    MANAGEMENT = "management"
    CONSULTANT = "consultant"
    BACKOFFICE = "backoffice"
    READONLY = "readonly"
    # Client-tenant users (locked to their own tenant_id)
    CLIENT_ADMIN = "client_admin"
    CLIENT_OPERATOR = "client_operator"
    CLIENT_READONLY = "client_readonly"


STAFF_ROLES = frozenset({
    Role.ADMIN, Role.MANAGEMENT, Role.CONSULTANT, Role.BACKOFFICE, Role.READONLY,
})
CLIENT_ROLES = frozenset({Role.CLIENT_ADMIN, Role.CLIENT_OPERATOR, Role.CLIENT_READONLY})

_ALL = {"*"}

_BUSINESS_WRITE = {
    "companies:read", "companies:write",
    "contacts:read", "contacts:write",
    "leads:read", "leads:write",
    "opportunities:read", "opportunities:write",
    "tasks:read", "tasks:write",
    "notes:read", "notes:write",
    "search:read", "dashboard:read",
    "service_lines:read",
    "audit:read",
    "billing:read", "billing:write",
    "management:read", "management:write",
    "assistant:use",
}

_BUSINESS_READ = {s for s in _BUSINESS_WRITE if s.endswith(":read")}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: _ALL,
    Role.MANAGEMENT: _BUSINESS_WRITE | {
        "users:read", "reports:read", "billing:submit", "tenants:read",
    },
    Role.CONSULTANT: _BUSINESS_WRITE | {"tenants:read"},
    Role.BACKOFFICE: (_BUSINESS_READ | {
        "tasks:write", "notes:write", "contacts:write",
        "documents:write", "billing:write", "tenants:read",
    }),
    Role.READONLY: _BUSINESS_READ,
    # Client-tenant roles: same domain surface, tenant-locked by context
    Role.CLIENT_ADMIN: _BUSINESS_WRITE | {"users:read", "users:write", "billing:submit", "billing:admin"},
    Role.CLIENT_OPERATOR: _BUSINESS_WRITE,
    Role.CLIENT_READONLY: _BUSINESS_READ,
}


def permissions_for(role: Role) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def role_allows(role: Role, scope: str) -> bool:
    perms = permissions_for(role)
    if "*" in perms:
        return True
    if scope in perms:
        return True
    domain = scope.split(":", 1)[0]
    return f"{domain}:*" in perms


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """Resolve the authenticated user or raise 401."""
    from app.modules.users.models import User

    if credentials is None:
        raise UnauthorizedError("Authentication required.")
    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Account not available.")
    return user


def require_permissions(*scopes: str):
    """Dependency factory: user must hold ALL listed scopes."""

    def checker(user=Depends(get_current_user)):
        missing = [s for s in scopes if not role_allows(user.role, s)]
        if missing:
            raise ForbiddenError(
                "You do not have permission to perform this action.",
                details={"missing": missing},
            )
        return user

    return checker


def can_write(user) -> bool:
    return user.role != Role.READONLY


CurrentUserId = UUID


def scope_list_for(role: Role) -> Iterable[str]:
    return sorted(permissions_for(role))
