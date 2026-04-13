"""
Simple in-memory rate limiter keyed by IP.
Tracks free-tier page usage per IP per calendar month.
For production, back this with Redis.
"""

import time
import threading
from collections import defaultdict
from datetime import datetime, timezone

_lock    = threading.Lock()
_usage: dict[str, dict] = defaultdict(lambda: {"month": "", "pages": 0})

FREE_PAGES = 3


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def check_free_tier(ip: str, page_count: int) -> tuple[bool, int]:
    """
    Returns (allowed, remaining_free_pages).
    allowed = True if this request fits within the free tier.
    """
    month = _month_key()
    with _lock:
        record = _usage[ip]
        if record["month"] != month:
            record["month"] = month
            record["pages"] = 0
        used = record["pages"]
        remaining = max(0, FREE_PAGES - used)
    return remaining >= page_count, remaining


def consume_free_pages(ip: str, pages: int):
    """Record page consumption for an IP."""
    month = _month_key()
    with _lock:
        record = _usage[ip]
        if record["month"] != month:
            record["month"] = month
            record["pages"] = 0
        record["pages"] = min(record["pages"] + pages, FREE_PAGES)


def get_usage(ip: str) -> dict:
    month = _month_key()
    with _lock:
        record = _usage[ip]
        if record["month"] != month:
            return {"month": month, "pages_used": 0, "pages_remaining": FREE_PAGES}
        return {
            "month": month,
            "pages_used": record["pages"],
            "pages_remaining": max(0, FREE_PAGES - record["pages"]),
        }
