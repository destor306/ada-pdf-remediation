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


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html", {"request": request, "sent": False, "error": None})


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    import secrets as _secrets
    from datetime import timedelta
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        token = _secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_exp = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()
        # Send email
        from app.config import APP_URL
        from app.email_notify import _send
        reset_url = f"{APP_URL}/auth/reset-password?token={token}"
        _send(email, "Reset your AccessiFix password",
            f'<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:2rem">'
            f'<h2 style="color:#2563EB">Reset your password</h2>'
            f'<p>Click the link below to set a new password. This link expires in 1 hour.</p>'
            f'<p style="margin:1.5rem 0"><a href="{reset_url}" style="background:#2563EB;color:white;'
            f'padding:.7rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:600">Reset Password</a></p>'
            f'<p style="color:#64748B;font-size:.85rem">If you didn\'t request this, you can safely ignore it.</p></div>')
    # Always show "sent" to prevent email enumeration
    return templates.TemplateResponse(request, "forgot_password.html", {"request": request, "sent": True, "error": None})


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == token).first()
    if not user or not user.reset_token_exp or user.reset_token_exp < datetime.now(timezone.utc):
        return templates.TemplateResponse(request, "forgot_password.html",
            {"request": request, "sent": False, "error": "This reset link has expired or is invalid. Please request a new one."})
    return templates.TemplateResponse(request, "reset_password.html", {"request": request, "token": token, "error": None})


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password(request: Request, token: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == token).first()
    if not user or not user.reset_token_exp or user.reset_token_exp < datetime.now(timezone.utc):
        return templates.TemplateResponse(request, "forgot_password.html",
            {"request": request, "sent": False, "error": "This reset link has expired. Please request a new one."})
    if len(password) < 8:
        return templates.TemplateResponse(request, "reset_password.html",
            {"request": request, "token": token, "error": "Password must be at least 8 characters."})
    user.password_hash = hash_password(password)
    user.reset_token = None
    user.reset_token_exp = None
    db.commit()
    response = RedirectResponse("/auth/login?reset=1", status_code=302)
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
