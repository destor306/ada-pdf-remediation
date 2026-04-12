"""
Stripe billing routes: success, cancel, webhook.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse

from app.billing import verify_webhook
from app.jobs import get_job, start_job

router = APIRouter(prefix="/billing")


@router.get("/success")
async def billing_success(session_id: str, job_id: str):
    """
    Stripe redirects here after successful payment.
    Release the job for processing.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status == "queued":
        start_job(job)

    return RedirectResponse(url=f"/?job_id={job_id}&paid=1")


@router.get("/cancel")
async def billing_cancel(job_id: str):
    """User cancelled payment — redirect home."""
    return RedirectResponse(url=f"/?cancelled=1")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint.
    Listens for checkout.session.completed to release jobs.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    event = verify_webhook(payload, sig_header)
    if event is None:
        raise HTTPException(400, "Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        job_id = session.get("metadata", {}).get("job_id")
        if job_id:
            job = get_job(job_id)
            if job and job.status == "queued":
                start_job(job)

    return {"status": "ok"}
