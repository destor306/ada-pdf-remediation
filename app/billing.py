"""
Stripe per-page billing.

Flow:
  1. User uploads PDF → /upload returns page_count + price estimate
  2. If page_count > FREE_PAGES_PER_MONTH → create Stripe Checkout session
  3. Stripe redirects to /billing/success?session_id=... + job_id
  4. Webhook confirms payment → job is released to process
  5. On /billing/cancel → job is deleted

For MVP: we gate processing behind payment for paid pages.
Free tier (≤3 pages/month) processes immediately.
"""

import stripe
from app.config import (
    STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY,
    PRICE_PER_PAGE, FREE_PAGES_PER_MONTH, APP_URL
)


def init_stripe():
    if STRIPE_SECRET_KEY:
        stripe.api_key = STRIPE_SECRET_KEY


def calculate_charge(page_count: int) -> dict:
    """Return billing info for a given page count."""
    billable_pages = max(0, page_count - FREE_PAGES_PER_MONTH)
    amount_usd = round(billable_pages * PRICE_PER_PAGE, 2)
    return {
        "total_pages": page_count,
        "free_pages": min(page_count, FREE_PAGES_PER_MONTH),
        "billable_pages": billable_pages,
        "amount_usd": amount_usd,
        "requires_payment": amount_usd > 0,
    }


def create_checkout_session(page_count: int, job_id: str) -> str | None:
    """
    Create a Stripe Checkout session for billable pages.
    Returns the session URL, or None if Stripe is not configured.
    """
    if not STRIPE_SECRET_KEY:
        return None

    billing = calculate_charge(page_count)
    if not billing["requires_payment"]:
        return None

    amount_cents = int(billing["amount_usd"] * 100)

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": "ADA PDF Remediation",
                    "description": (
                        f"{billing['billable_pages']} pages × ${PRICE_PER_PAGE:.2f}/page"
                        f" ({billing['free_pages']} free page(s) applied)"
                    ),
                },
                "unit_amount": amount_cents,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{APP_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}&job_id={job_id}",
        cancel_url=f"{APP_URL}/billing/cancel?job_id={job_id}",
        metadata={"job_id": job_id, "page_count": page_count},
    )
    return session.url


def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event | None:
    """Verify and parse an incoming Stripe webhook."""
    from app.config import STRIPE_WEBHOOK_SECRET
    if not STRIPE_WEBHOOK_SECRET:
        return None
    try:
        return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        return None
