"""
HTML page routes (served via Jinja2 templates).
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import STRIPE_PUBLISHABLE_KEY
from app.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    job_id: str = "",
    paid: str = "",
    cancelled: str = "",
    user=Depends(get_current_user),
):
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "stripe_pk": STRIPE_PUBLISHABLE_KEY,
        "job_id": job_id,
        "paid": paid,
        "cancelled": bool(cancelled),
        "user": user,
    })


@router.get("/compliance-guide", response_class=HTMLResponse)
async def compliance_guide(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse(request, "compliance_guide.html", {
        "request": request,
        "user": user,
    })


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/auth/dashboard")
