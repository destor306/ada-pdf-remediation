"""
Auth helpers: password hashing, JWT tokens, session cookie.
"""

import os
import bcrypt
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-use-a-long-random-string")
ALGORITHM  = "HS256"
TOKEN_TTL_DAYS = 30

PLAN_PAGE_LIMITS = {
    "free":     3,
    "payg":     None,   # unlimited, pay per page
    "pro":      200,
    "business": 1000,
}


# ---------- password ----------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------- JWT ----------

def create_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(data["sub"])
    except (JWTError, KeyError, ValueError):
        return None


# ---------- FastAPI deps ----------

def get_current_user(
    session: str = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not session:
        return None
    user_id = decode_token(session)
    if not user_id:
        return None
    return db.get(User, user_id)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


# ---------- usage / plan helpers ----------

def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def reset_usage_if_new_month(user: User, db: Session):
    """Reset page counter when calendar month rolls over."""
    month = current_month()
    if user.usage_month != month:
        user.pages_used   = 0
        user.usage_month  = month
        db.commit()


def pages_remaining(user: User, db: Session) -> int | None:
    """Returns pages left this month, or None for unlimited (payg)."""
    reset_usage_if_new_month(user, db)
    limit = PLAN_PAGE_LIMITS.get(user.plan.value)
    if limit is None:
        return None  # payg — unlimited
    return max(0, limit - user.pages_used)


def can_process_free(user: User, page_count: int, db: Session) -> bool:
    remaining = pages_remaining(user, db)
    if remaining is None:
        return False  # payg always pays
    return remaining >= page_count
