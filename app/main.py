"""
ADA PDF Remediation — FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.billing import init_stripe
from app.routes.api import router as api_router
from app.routes.billing import router as billing_router
from app.routes.pages import router as pages_router

app = FastAPI(
    title="ADA PDF Remediation",
    description="Convert non-compliant PDFs to ADA/PDF-UA compliant documents",
    version="0.1.0",
)

# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Routers
app.include_router(pages_router)
app.include_router(api_router)
app.include_router(billing_router)

# Init Stripe
init_stripe()


@app.on_event("startup")
async def startup():
    print("ADA Remediation API started.")
    print("  Docs: http://localhost:8000/docs")
