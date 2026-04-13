"""
File lifecycle management.
- Uploads auto-expire after 1 hour
- Outputs auto-expire after 24 hours
Run cleanup() periodically or call from a cron/scheduled task.
"""

import time
import threading
from pathlib import Path
from app.config import UPLOAD_DIR, OUTPUT_DIR

UPLOAD_TTL  = 3600        # 1 hour
OUTPUT_TTL  = 86400       # 24 hours


def cleanup():
    now = time.time()
    removed = 0
    for path in UPLOAD_DIR.glob("*.pdf"):
        if now - path.stat().st_mtime > UPLOAD_TTL:
            path.unlink(missing_ok=True)
            removed += 1
    for path in OUTPUT_DIR.glob("*.docx"):
        if now - path.stat().st_mtime > OUTPUT_TTL:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def start_cleanup_thread():
    """Run cleanup every 15 minutes in the background."""
    def _loop():
        while True:
            time.sleep(900)
            try:
                cleanup()
            except Exception:
                pass
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
