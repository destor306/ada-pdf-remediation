"""
API routes for the ADA remediation pipeline.
"""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config import (
    UPLOAD_DIR, OUTPUT_DIR, MAX_UPLOAD_MB, MAX_PAGES_HARD,
    FREE_PAGES_PER_MONTH, PRICE_PER_PAGE, LARGE_DOC_THRESHOLD,
    STRIPE_SECRET_KEY, APP_URL,
)
from app.jobs import create_job, get_job, start_job
from app.billing import calculate_charge, create_checkout_session
from app.ratelimit import check_free_tier, consume_free_pages, get_usage
from app.database import get_db
from app.auth import get_current_user, pages_remaining, can_process_free
from app.models import User

router = APIRouter(prefix="/api")


@router.get("/usage")
async def usage_route(request: Request):
    """Return free-tier usage for the current IP."""
    ip = request.client.host if request.client else "unknown"
    return get_usage(ip)


@router.post("/upload")
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Accept a PDF upload, return page count and cost estimate.
    Does NOT start processing yet.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    # Size check
    content = await file.read()
    mb = len(content) / 1_048_576
    if mb > MAX_UPLOAD_MB:
        raise HTTPException(413, f"File too large ({mb:.1f} MB). Max {MAX_UPLOAD_MB} MB.")

    # Magic byte check — real PDFs start with %PDF
    if not content[:5].startswith(b"%PDF-"):
        raise HTTPException(400, "File does not appear to be a valid PDF.")

    # Save upload
    upload_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{upload_id}.pdf"
    pdf_path.write_bytes(content)
    # Persist original filename so download can use it
    (UPLOAD_DIR / f"{upload_id}.name").write_text(file.filename, encoding="utf-8")

    # Count pages
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            page_count = len(pdf.pages)
    except Exception as e:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not read PDF: {e}")

    if page_count > MAX_PAGES_HARD:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(400, f"Document has {page_count} pages. Max allowed: {MAX_PAGES_HARD}.")

    billing = calculate_charge(page_count)

    # Plan-aware billing for logged-in users
    if user:
        plan = user.plan.value
        if plan in ("free", "pro", "business"):
            remaining = pages_remaining(user, db)
            if remaining is not None and remaining >= page_count:
                billing = dict(billing, requires_payment=False, amount_usd=0)
        # payg always uses calculate_charge (charges for all pages)

    requires_confirmation = page_count > LARGE_DOC_THRESHOLD
    ip = request.client.host if request.client else "unknown"
    usage = get_usage(ip)

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "page_count": page_count,
        "billing": billing,
        "requires_confirmation": requires_confirmation,
        "large_doc_warning": (
            f"This document has {page_count} pages."
            if requires_confirmation else None
        ),
        "free_tier_usage": usage,
    }


@router.post("/process")
async def process_pdf(
    request: Request,
    body: dict,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start processing a previously uploaded PDF.
    Body: { "upload_id": "...", "use_claude": false, "confirmed": true }

    If billing is required and Stripe is configured, returns a checkout_url.
    Otherwise starts the job immediately.
    """
    upload_id = body.get("upload_id")
    if not upload_id:
        raise HTTPException(400, "upload_id required")

    pdf_path = UPLOAD_DIR / f"{upload_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, "Upload not found or expired")

    use_claude   = body.get("use_claude", False)
    notify_email = body.get("email", "").strip()

    # Recover original filename
    name_file = UPLOAD_DIR / f"{upload_id}.name"
    original_filename = name_file.read_text(encoding="utf-8").strip() if name_file.exists() else f"{upload_id}.pdf"
    original_stem = Path(original_filename).stem

    # Count pages for billing
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)

    # Create job record, attaching user_id when logged in
    output_path = str(OUTPUT_DIR / f"{upload_id}_accessible.docx")
    job = create_job(str(pdf_path), output_path, use_claude=use_claude, notify_email=notify_email, user_id=user.id if user else None, original_stem=original_stem)

    billing = calculate_charge(page_count)

    # Plan-aware billing: skip payment for users with included pages
    if user:
        plan = user.plan.value
        if plan in ("free", "pro", "business"):
            remaining = pages_remaining(user, db)
            if remaining is not None and remaining >= page_count:
                # Covered by subscription/free plan — start immediately
                start_job(job)
                return {
                    "job_id": job.id,
                    "status": "queued",
                    "billing": dict(billing, requires_payment=False, amount_usd=0),
                }
        # payg or insufficient remaining pages — fall through to Stripe

    # If payment required, create Stripe session
    if billing["requires_payment"]:
        checkout_url = create_checkout_session(page_count, job.id)
        if checkout_url:
            return {
                "job_id": job.id,
                "status": "awaiting_payment",
                "checkout_url": checkout_url,
                "billing": billing,
            }

    # Free or Stripe not configured → start immediately
    start_job(job)
    return {
        "job_id": job.id,
        "status": "queued",
        "billing": billing,
    }


@router.get("/status/{job_id}")
async def job_status(job_id: str, user: User | None = Depends(get_current_user)):
    """Poll job status and progress."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Ownership check: logged-in users can only access their own jobs (or anonymous jobs)
    if user and job.user_id is not None and job.user_id != user.id:
        raise HTTPException(403, "Access denied")

    backend_labels = {
        "ollama": "Local AI (Ollama)",
        "claude": "Claude API",
        "mock": "Text extraction (no AI — install Ollama for better results)",
        "unknown": "Detecting…",
    }
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "current_page": job.current_page,
        "total_pages": job.total_pages,
        "error": job.error,
        "check_report": job.check_report if job.status == "done" else None,
        "completed_at": job.completed_at,
        "backend": job.backend,
        "backend_label": backend_labels.get(job.backend, job.backend),
        "has_pdf": bool(getattr(job, "output_pdf", None) and Path(job.output_pdf).exists()) if job.status == "done" else False,
        "has_docx": Path(job.output_path).exists() if job.status == "done" else False,
    }


@router.get("/download/{job_id}")
async def download_result(job_id: str, fmt: str = "pdf", user: User | None = Depends(get_current_user)):
    """
    Download completed output.
    fmt=pdf  → ADA-compliant PDF (default)
    fmt=docx → Word document (intermediate)
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Ownership check: logged-in users can only access their own jobs (or anonymous jobs)
    if user and job.user_id is not None and job.user_id != user.id:
        raise HTTPException(403, "Access denied")

    if job.status != "done":
        raise HTTPException(400, f"Job not complete (status: {job.status})")

    stem = getattr(job, "original_stem", None) or Path(job.pdf_path).stem

    # Prefer PDF output
    if fmt != "docx" and getattr(job, "output_pdf", None) and Path(job.output_pdf).exists():
        return FileResponse(
            path=job.output_pdf,
            media_type="application/pdf",
            filename=f"{stem}_accessible.pdf",
        )

    # Fall back to docx
    if not Path(job.output_path).exists():
        raise HTTPException(500, "Output file missing")
    return FileResponse(
        path=job.output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{stem}_accessible.docx",
    )


@router.post("/audit")
async def audit_pdf_route(body: dict):
    """
    Run a free accessibility audit on an uploaded (not yet remediated) PDF.
    Body: { "upload_id": "..." }
    Returns a visual report with highlighted page images and plain-English findings.
    """
    upload_id = body.get("upload_id")
    if not upload_id:
        raise HTTPException(400, "upload_id required")

    pdf_path = UPLOAD_DIR / f"{upload_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, "Upload not found — it may have expired (files are deleted after 1 hour)")

    try:
        from app.audit import audit_pdf
        result = audit_pdf(str(pdf_path))
        return result
    except Exception as e:
        raise HTTPException(500, f"Audit failed: {e}")


@router.post("/check")
async def check_compliance(body: dict):
    """
    Run ada_check.py compliance check on a completed (remediated) job.
    Body: { "job_id": "..." }
    Checks both DOCX structure and the PDF struct tree (same checks Acrobat runs).
    """
    job_id = body.get("job_id")
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "done":
        raise HTTPException(400, "Job not complete yet")

    # Return cached report if available
    if job.check_report:
        return job.check_report

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from ada_check import CheckReport, run_docx_checks, check_pdf_tags
        rpt = CheckReport(
            source_pdf=job.pdf_path,
            docx_path=job.output_path,
            pdf_path=job.output_pdf,
        )
        run_docx_checks(job.pdf_path, job.output_path, rpt)
        if job.output_pdf and Path(job.output_pdf).exists():
            check_pdf_tags(job.output_pdf, rpt)
        result = {
            "issues": [
                {"severity": i.severity, "category": i.category, "message": i.message}
                for i in rpt.issues
            ],
            "passed": rpt.passed,
            "failed": rpt.failed,
        }
        job.check_report = result
        return result
    except Exception as e:
        raise HTTPException(500, f"Check failed: {e}")


# Stripe price IDs — set these in .env after creating products in Stripe dashboard
STRIPE_PRICE_IDS = {
    "pro":      os.environ.get("STRIPE_PRICE_PRO", ""),
    "business": os.environ.get("STRIPE_PRICE_BUSINESS", ""),
}


@router.post("/subscribe")
async def create_subscription(
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Start a Stripe Checkout session for a monthly subscription plan,
    or switch user to payg/free (no payment needed).
    Body: { "plan": "free" | "payg" | "pro" | "business" }
    """
    if not user:
        raise HTTPException(401, "Login required")

    plan = body.get("plan", "")
    if plan not in ("free", "payg", "pro", "business"):
        raise HTTPException(400, "Invalid plan")

    # free / payg — no Stripe session needed, just update the record
    if plan in ("free", "payg"):
        from app.models import PlanTier
        user.plan = PlanTier(plan)
        db.commit()
        return {"message": f"Switched to {plan} plan."}

    # pro / business — create Stripe Checkout subscription session
    price_id = STRIPE_PRICE_IDS.get(plan)
    if not price_id or not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe not configured for subscriptions. Contact support.")

    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    # Reuse existing Stripe customer if available
    customer_id = user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(email=user.email, metadata={"user_id": user.id})
        customer_id = customer.id
        user.stripe_customer_id = customer_id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{APP_URL}/billing/sub-success?plan={plan}",
        cancel_url=f"{APP_URL}/auth/dashboard",
        metadata={"user_id": user.id, "plan": plan},
    )
    return {"checkout_url": session.url}
