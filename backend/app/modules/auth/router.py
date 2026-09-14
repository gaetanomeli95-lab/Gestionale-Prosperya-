import hashlib
import secrets
import time
from collections import OrderedDict
from datetime import UTC, datetime
from threading import Lock

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError, UnauthorizedError
from app.core.rbac import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db import get_db
from app.modules.users.models import User
from app.modules.users.schemas import LoginRequest, TokenResponse, UserOut
from app.shared.events import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Login brute-force throttle: per-IP and per-email sliding window (5 min).
# In-process only — a shared store (Redis) is needed for multi-worker prod.
LOGIN_WINDOW_SECONDS = 300
_login_attempts: OrderedDict[str, list[float]] = OrderedDict()
_login_lock = Lock()
# Constant-time behaviour for unknown emails: always verify against a real hash.
_dummy_hash = hash_password(secrets.token_urlsafe(32))


class TooManyAttemptsError(AppError):
    status_code = 429
    code = "too_many_attempts"


def _key(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()


def check_login_rate(request: Request, email: str) -> None:
    max_attempts = get_settings().login_max_attempts
    if max_attempts <= 0:
        return
    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _login_lock:
        for key in (_key("ip", host), _key("email", email)):
            attempts = [t for t in _login_attempts.pop(key, []) if t > now - LOGIN_WINDOW_SECONDS]
            _login_attempts[key] = attempts
            if len(attempts) >= max_attempts:
                raise TooManyAttemptsError("Troppi tentativi; riprovare più tardi.")
            attempts.append(now)
        while len(_login_attempts) > 10_000:
            _login_attempts.popitem(last=False)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    check_login_rate(request, email)
    user = db.scalar(select(User).where(User.email == email))
    valid = verify_password(payload.password, user.hashed_password if user else _dummy_hash)
    if user is None or not valid:
        raise UnauthorizedError("Invalid email or password.", code="invalid_credentials")
    if not user.is_active:
        raise UnauthorizedError("This account is disabled.", code="account_disabled")
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise UnauthorizedError("La password attuale non è corretta.", code="invalid_credentials")
    user.hashed_password = hash_password(payload.new_password)
    record_audit(db, actor_id=user.id, action="user.change_password", entity_type="user",
                 entity_id=user.id, tenant_id=user.tenant_id)
    db.commit()
