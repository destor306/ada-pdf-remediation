"""
Stripe billing routes: success, cancel, webhook.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.billing import verify_webhook
from app.jobs import get_job, start_job
from app.database import get_db
from app.auth import get_current_user
from app.models import PlanTier

router = APIRouter(prefix="/billing")


@router.get("/success")
async def billing_success(session_id: str, job_id: str):
    """Stripe redirects here after successful one-time payment. Release the job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status == "queued":
        start_job(job)
    return RedirectResponse(url=f"/?job_id={job_id}&paid=1")


@router.get("/sub-success")
async def subscription_success(
    plan: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Stripe redirects here after a successful subscription checkout."""
    if user and plan in PlanTier.__members__:
        user.plan = PlanTier(plan)
        db.commit()
    return RedirectResponse(url="/auth/dashboard")


@router.get("/cancel")
async def billing_cancel(job_id: str = ""):
    return RedirectResponse(url=f"/?cancelled=1" if not job_id else f"/?cancelled=1&job_id={job_id}")


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Stripe webhook endpoint.
    Handles:
      - checkout.session.completed  → release pay-as-you-go job OR activate subscription
      - customer.subscription.deleted → downgrade user to free
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    event = verify_webhook(payload, sig_header)
    if event is None:
        raise HTTPException(400, "Invalid webhook signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        meta = data.get("metadata", {})
        job_id = meta.get("job_id")
        if job_id:
            job = get_job(job_id)
            if job and job.status == "queued":
                start_job(job)

        # Subscription checkout — activate plan
        plan = meta.get("plan")
        user_id = meta.get("user_id")
        if plan and user_id:
            from app.models import User
            user = db.get(User, int(user_id))
            if user and plan in PlanTier.__members__:
                user.plan = PlanTier(plan)
                user.stripe_sub_id = data.get("subscription")
                db.commit()

    elif event_type == "customer.subscription.deleted":
        # Subscription cancelled — downgrade to free
        customer_id = data.get("customer")
        if customer_id:
            from app.models import User
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user.plan = PlanTier.free
                user.stripe_sub_id = None
                db.commit()

    return {"status": "ok"}
