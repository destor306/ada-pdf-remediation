"""
Auth routes: register, login, logout.
"""

import os
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models import User
from app.auth import (
    hash_password, verify_password, create_token,
    get_current_user, pages_remaining, reset_usage_if_new_month
)

router = APIRouter(prefix="/auth")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

IS_PROD = os.environ.get("ENV", "development").lower() == "production"

# ── Login brute-force protection ─────────────────────────────────────────────
# Max 10 failed attempts per IP per 15-minute window
_login_attempts: dict[str, list[float]] = defaultdict(list)
_login_lock = threading.Lock()
_MAX_ATTEMPTS = 10
_WINDOW_SEC   = 900  # 15 minutes


def _check_login_rate(ip: str) -> bool:
    """Returns True if the IP is allowed to attempt login."""
    now = time.time()
    cutoff = now - _WINDOW_SEC
    with _login_lock:
        attempts = [t for t in _login_attempts[ip] if t > cutoff]
        _login_attempts[ip] = attempts
        return len(attempts) < _MAX_ATTEMPTS


def _record_failed_login(ip: str):
    now = time.time()
    with _login_lock:
        _login_attempts[ip].append(now)


def _set_session(response, user_id: int):
    token = create_token(user_id)
    response.set_cookie(
        "session", token,
        httponly=True,
        samesite="lax",
        secure=IS_PROD,   # HTTPS-only in production
        max_age=60 * 60 * 24 * 30,
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, user=Depends(get_current_user)):
    if user:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "register.html", {"request": request, "error": None})


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if len(email) > 254:
        return templates.TemplateResponse(request, "register.html",
            {"request": request, "error": "Invalid email address."}, status_code=400)
    if len(password) < 8:
        return templates.TemplateResponse(request, "register.html",
            {"request": request, "error": "Password must be at least 8 characters."}, status_code=400)
    if len(password) > 1024:
        return templates.TemplateResponse(request, "register.html",
            {"request": request, "error": "Password too long."}, status_code=400)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse(request, "register.html",
            {"request": request, "error": "An account with that email already exists."}, status_code=400)

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse("/dashboard", status_code=302)
    _set_session(response, user.id)
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(get_current_user), next: str = "/"):
    if user:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None, "next": next})


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/dashboard"),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"

    if not _check_login_rate(ip):
        return templates.TemplateResponse(request, "login.html",
            {"request": request, "error": "Too many login attempts. Please wait 15 minutes.", "next": next},
            status_code=429)

    email = email.strip().lower()
    if len(email) > 254 or len(password) > 1024:
        return templates.TemplateResponse(request, "login.html",
            {"request": request, "error": "Invalid email or password.", "next": next}, status_code=401)

    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        _record_failed_login(ip)
        return templates.TemplateResponse(request, "login.html",
            {"request": request, "error": "Invalid email or password.", "next": next}, status_code=401)

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    response = RedirectResponse(next if next.startswith("/") else "/dashboard", status_code=302)
    _set_session(response, user.id)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/")
    response.delete_cookie("session")
    return response


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not user:
        return RedirectResponse("/auth/login?next=/auth/dashboard")

    reset_usage_if_new_month(user, db)
    remaining = pages_remaining(user, db)

    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "user": user,
        "pages_remaining": remaining,
        "pages_used": user.pages_used,
    })
