"""
API routes for the ADA remediation pipeline.
"""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse

from app.config import (
    UPLOAD_DIR, OUTPUT_DIR, MAX_UPLOAD_MB, MAX_PAGES_HARD,
    FREE_PAGES_PER_MONTH, PRICE_PER_PAGE, LARGE_DOC_THRESHOLD
)
from app.jobs import create_job, get_job, start_job
from app.billing import calculate_charge, create_checkout_session

router = APIRouter(prefix="/api")


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
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

    # Save upload
    upload_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{upload_id}.pdf"
    pdf_path.write_bytes(content)

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
    requires_confirmation = page_count > LARGE_DOC_THRESHOLD

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
    }


@router.post("/process")
async def process_pdf(body: dict):
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

    use_claude = body.get("use_claude", False)

    # Count pages for billing
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)

    # Create job record
    output_path = str(OUTPUT_DIR / f"{upload_id}_accessible.docx")
    job = create_job(str(pdf_path), output_path, use_claude=use_claude)

    billing = calculate_charge(page_count)

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
async def job_status(job_id: str):
    """Poll job status and progress."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "current_page": job.current_page,
        "total_pages": job.total_pages,
        "error": job.error,
        "check_report": job.check_report if job.status == "done" else None,
        "completed_at": job.completed_at,
    }


@router.get("/download/{job_id}")
async def download_result(job_id: str):
    """Download the completed .docx file."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "done":
        raise HTTPException(400, f"Job not complete (status: {job.status})")
    if not Path(job.output_path).exists():
        raise HTTPException(500, "Output file missing")

    filename = Path(job.output_path).name
    return FileResponse(
        path=job.output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.post("/check")
async def check_compliance(body: dict):
    """
    Run ada_check.py compliance check on a completed job.
    Body: { "job_id": "..." }
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
        from ada_check import CheckReport, run_docx_checks
        report = CheckReport(source_pdf=job.pdf_path, docx_path=job.output_path)
        run_docx_checks(job.pdf_path, job.output_path, report)
        result = {
            "issues": [
                {"severity": i.severity, "category": i.category, "message": i.message}
                for i in report.issues
            ],
            "passed": report.passed,
            "failed": report.failed,
        }
        job.check_report = result
        return result
    except Exception as e:
        raise HTTPException(500, f"Check failed: {e}")
