"""
HTML page routes (served via Jinja2 templates).
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import STRIPE_PUBLISHABLE_KEY

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, job_id: str = "", paid: str = "", cancelled: str = ""):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "stripe_pk": STRIPE_PUBLISHABLE_KEY,
        "job_id": job_id,
        "paid": paid,
        "cancelled": cancelled,
    })
