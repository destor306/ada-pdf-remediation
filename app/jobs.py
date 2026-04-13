"""
Job queue — auto-selects Redis/RQ when REDIS_URL is set, falls back to in-memory threads.
"""

import uuid
import threading
import traceback
from datetime import datetime, timezone

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
from pathlib import Path
from typing import Literal

from app.config import UPLOAD_DIR, OUTPUT_DIR, REDIS_URL

JobStatus = Literal["queued", "running", "done", "failed"]


class Job:
    def __init__(self, job_id: str, pdf_path: str, output_path: str, use_claude: bool = False):
        self.id           = job_id
        self.pdf_path     = pdf_path
        self.output_path  = output_path
        self.use_claude   = use_claude
        self.status: JobStatus = "queued"
        self.progress     = 0
        self.current_page = 0
        self.total_pages  = 0
        self.error: str | None = None
        self.check_report: dict | None = None
        self.created_at   = _now()
        self.completed_at: str | None = None


# ---------- in-memory store (always present as fallback) ----------
_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _store(job: Job):
    with _lock:
        _jobs[job.id] = job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    with _lock:
        return list(_jobs.values())


# ---------- job execution ----------
def _execute(job: Job):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    job.status = "running"
    try:
        import pdfplumber
        with pdfplumber.open(job.pdf_path) as pdf:
            job.total_pages = len(pdf.pages)

        from ada_remediate import (
            detect_backends, extract_text_layer, get_page_dimensions,
            analyze_page, build_docx, MAX_PAGES,
        )

        backends = detect_backends()
        if not job.use_claude:
            backends["claude"] = False

        pages_to_process = min(job.total_pages, MAX_PAGES)
        text_layers = extract_text_layer(job.pdf_path)
        page_dims   = get_page_dimensions(job.pdf_path)

        pages_data = []
        for page_num in range(1, pages_to_process + 1):
            job.current_page = page_num
            job.progress = int((page_num - 1) / pages_to_process * 88)
            pages_data.append(
                analyze_page(job.pdf_path, page_num, text_layers.get(page_num, ""), backends)
            )

        job.progress = 90
        build_docx(pages_data, job.output_path, page_dims=page_dims)

        job.progress = 95
        try:
            from ada_check import CheckReport, run_docx_checks
            rpt = CheckReport(source_pdf=job.pdf_path, docx_path=job.output_path)
            run_docx_checks(job.pdf_path, job.output_path, rpt)
            job.check_report = {
                "issues": [{"severity": i.severity, "category": i.category, "message": i.message} for i in rpt.issues],
                "passed": rpt.passed,
                "failed": rpt.failed,
            }
        except Exception as ce:
            job.check_report = {"error": str(ce)}

        job.progress    = 100
        job.status      = "done"
        job.completed_at = _now()

    except Exception:
        job.status       = "failed"
        job.error        = traceback.format_exc()
        job.completed_at = _now()


def create_job(pdf_path: str, output_path: str, use_claude: bool = False) -> Job:
    job = Job(str(uuid.uuid4()), pdf_path, output_path, use_claude)
    _store(job)
    return job


def start_job(job: Job):
    """Start job — uses Redis/RQ if available, otherwise a daemon thread."""
    if REDIS_URL:
        try:
            import redis
            from rq import Queue
            conn = redis.from_url(REDIS_URL)
            q    = Queue("ada", connection=conn)
            q.enqueue(_execute, job, job_timeout=3600)
            return
        except Exception:
            pass  # fall through to thread
    t = threading.Thread(target=_execute, args=(job,), daemon=True)
    t.start()
