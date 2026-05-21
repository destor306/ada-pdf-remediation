"""
ADA PDF Remediation — FastAPI application entry point.
"""

import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.billing import init_stripe
from app.database import init_db
from app.storage import start_cleanup_thread
from app.routes.api import router as api_router
from app.routes.auth import router as auth_router
from app.routes.billing import router as billing_router
from app.routes.pages import router as pages_router
from app.routes.admin import router as admin_router

IS_PROD = os.environ.get("ENV", "development").lower() == "production"


def _check_secret_key():
    """Crash loudly if the default SECRET_KEY is used in production."""
    key = os.environ.get("SECRET_KEY", "")
    insecure_defaults = {
        "",
        "change-me-in-production-use-a-long-random-string",
        "change-me-to-a-long-random-string-before-deploying",
    }
    if IS_PROD and key in insecure_defaults:
        print("FATAL: SECRET_KEY is not set. Run: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
        sys.exit(1)
    if key in insecure_defaults:
        print("WARNING: SECRET_KEY is using an insecure default. Set a real value in .env before deploying.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_secret_key()
    init_db()
    init_stripe()
    start_cleanup_thread()
    print("AccessiFix API started.")
    yield


# Disable Swagger UI and ReDoc in production — exposes full API surface
docs_url   = None if IS_PROD else "/docs"
redoc_url  = None if IS_PROD else "/redoc"
openapi_url = None if IS_PROD else "/openapi.json"

app = FastAPI(
    title="AccessiFix — ADA PDF Remediation",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)


# ── Security headers middleware ──────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if IS_PROD:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Routers
app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(api_router)
app.include_router(billing_router)
app.include_router(admin_router)
