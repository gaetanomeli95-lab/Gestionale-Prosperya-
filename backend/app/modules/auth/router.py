from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import UnauthorizedError
from app.core.rbac import get_current_user
from app.core.security import create_access_token, verify_password
from app.db import get_db
from app.modules.users.models import User
from app.modules.users.schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password.", code="invalid_credentials")
    if not user.is_active:
        raise UnauthorizedError("This account is disabled.", code="account_disabled")
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)
