"""
ADA PDF Remediation — FastAPI application entry point.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.billing import init_stripe
from app.storage import start_cleanup_thread
from app.routes.api import router as api_router
from app.routes.billing import router as billing_router
from app.routes.pages import router as pages_router
from app.routes.admin import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_stripe()
    start_cleanup_thread()
    print("ADA Remediation API started.")
    print("  Docs: http://localhost:8000/docs")
    yield


app = FastAPI(
    title="ADA PDF Remediation",
    description="Convert non-compliant PDFs to ADA/PDF-UA compliant documents",
    version="0.1.0",
    lifespan=lifespan,
)

# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Routers
app.include_router(pages_router)
app.include_router(api_router)
app.include_router(billing_router)
app.include_router(admin_router)
