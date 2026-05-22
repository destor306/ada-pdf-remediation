"""
Job queue — auto-selects Redis/RQ when REDIS_URL is set, falls back to in-memory threads.

When REDIS_URL is configured:
  - Job state is stored in Redis so web-process and worker-process stay in sync.
  - Jobs are executed by RQ workers (run: rq worker ada).
When REDIS_URL is absent:
  - Jobs run in daemon threads within the web process (dev/single-server mode).
"""

import uuid
import json
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import UPLOAD_DIR, OUTPUT_DIR, REDIS_URL

JobStatus = Literal["queued", "running", "done", "failed"]

_REDIS_TTL = 86400 * 7  # keep job state 7 days


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job:
    def __init__(
        self,
        job_id: str,
        pdf_path: str,
        output_path: str,
        use_claude: bool = False,
        notify_email: str = "",
        user_id: int | None = None,
        original_stem: str = "",
    ):
        self.id            = job_id
        self.pdf_path      = pdf_path
        self.output_path   = output_path
        self.output_pdf    = output_path.replace(".docx", "_ada.pdf")
        self.use_claude    = use_claude
        self.notify_email  = notify_email
        self.user_id       = user_id
        self.original_stem = original_stem or Path(pdf_path).stem
        self.status: JobStatus = "queued"
        self.progress      = 0
        self.current_page  = 0
        self.total_pages   = 0
        self.error: str | None = None
        self.check_report: dict | None = None
        self.backend       = "unknown"
        self.created_at    = _now()
        self.completed_at: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        obj = cls.__new__(cls)
        obj.__dict__.update(d)
        return obj


# ---------- in-memory fallback ----------
_jobs: dict[str, Job] = {}
_lock = threading.Lock()


# ---------- Redis helpers ----------

def _redis():
    if not REDIS_URL:
        return None
    try:
        import redis
        return redis.from_url(REDIS_URL)
    except Exception:
        return None


def _r_key(job_id: str) -> str:
    return f"accessifix:job:{job_id}"


def _r_index_key() -> str:
    return "accessifix:jobs"


def _store(job: Job):
    with _lock:
        _jobs[job.id] = job
    r = _redis()
    if r:
        r.setex(_r_key(job.id), _REDIS_TTL, json.dumps(job.to_dict()))
        r.sadd(_r_index_key(), job.id)
        r.expire(_r_index_key(), _REDIS_TTL)


def get_job(job_id: str) -> Job | None:
    r = _redis()
    if r:
        raw = r.get(_r_key(job_id))
        if raw:
            return Job.from_dict(json.loads(raw))
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    r = _redis()
    if r:
        ids = r.smembers(_r_index_key())
        jobs = []
        for jid in ids:
            raw = r.get(_r_key(jid.decode() if isinstance(jid, bytes) else jid))
            if raw:
                jobs.append(Job.from_dict(json.loads(raw)))
        return jobs
    with _lock:
        return list(_jobs.values())


# ---------- execution ----------

def _execute(job_id: str):
    """Worker entry point — loads job from store, runs pipeline, persists progress."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    job = get_job(job_id)
    if job is None:
        return

    def _save():
        _store(job)

    job.status = "running"
    _save()
    try:
        import pdfplumber
        with pdfplumber.open(job.pdf_path) as pdf:
            job.total_pages = len(pdf.pages)
        _save()

        from ada_remediate import (
            detect_backends, extract_text_layer, get_page_dimensions,
            analyze_page, build_docx, tag_pdf_with_accessibility, MAX_PAGES,
        )

        backends = detect_backends()
        if not job.use_claude:
            backends["claude"] = False

        job.backend = "ollama" if backends["ollama"] else ("claude" if backends["claude"] else "mock")
        _save()

        pages_to_process = min(job.total_pages, MAX_PAGES)
        text_layers = extract_text_layer(job.pdf_path)
        page_dims   = get_page_dimensions(job.pdf_path)

        pages_data = []
        for page_num in range(1, pages_to_process + 1):
            job.current_page = page_num
            job.progress     = int((page_num - 1) / pages_to_process * 88)
            _save()
            pages_data.append(
                analyze_page(job.pdf_path, page_num, text_layers.get(page_num, ""), backends)
            )

        job.progress = 90
        _save()
        doc_title = Path(job.pdf_path).stem.replace("_", " ").title()
        tag_pdf_with_accessibility(job.pdf_path, pages_data, job.output_pdf, title=doc_title)

        job.progress = 93
        _save()
        try:
            from pdf2docx import Converter
            cv = Converter(job.pdf_path)
            cv.convert(job.output_path, start=0, end=None)
            cv.close()
        except Exception:
            build_docx(pages_data, job.output_path, page_dims=page_dims)

        job.progress = 97
        _save()
        try:
            from ada_check import CheckReport, run_docx_checks, run_verapdf, check_visual_similarity
            rpt = CheckReport(source_pdf=job.pdf_path, docx_path=job.output_path, pdf_path=job.output_pdf)
            run_docx_checks(job.pdf_path, job.output_path, rpt)
            if job.output_pdf:
                run_verapdf(job.output_pdf, rpt)
                check_visual_similarity(job.pdf_path, job.output_pdf, rpt)
            job.check_report = {
                "issues": [{"severity": i.severity, "category": i.category, "message": i.message} for i in rpt.issues],
                "passed": rpt.passed,
                "failed": rpt.failed,
            }
        except Exception as ce:
            job.check_report = {"error": str(ce)}

        job.progress     = 100
        job.status       = "done"
        job.completed_at = _now()
        _save()

        if job.user_id:
            try:
                from app.database import SessionLocal
                from app.models import User
                from app.auth import current_month
                db = SessionLocal()
                user = db.get(User, job.user_id)
                if user:
                    month = current_month()
                    if user.usage_month != month:
                        user.pages_used = 0
                        user.usage_month = month
                    user.pages_used = (user.pages_used or 0) + job.total_pages
                    db.commit()
            except Exception:
                pass
            finally:
                db.close()

        if job.notify_email:
            from app.email_notify import notify_done
            from app.config import APP_URL
            notify_done(job.notify_email, job.id, job.total_pages, APP_URL)

    except Exception:
        job.status       = "failed"
        job.error        = traceback.format_exc()
        job.completed_at = _now()
        _save()

        if job.notify_email:
            from app.email_notify import notify_failed
            notify_failed(job.notify_email, job.id)


def create_job(
    pdf_path: str,
    output_path: str,
    use_claude: bool = False,
    notify_email: str = "",
    user_id: int | None = None,
    original_stem: str = "",
) -> Job:
    job = Job(str(uuid.uuid4()), pdf_path, output_path, use_claude, notify_email, user_id, original_stem)
    _store(job)
    return job


def start_job(job: Job):
    """Enqueue job — uses Redis/RQ if available, otherwise a daemon thread."""
    if REDIS_URL:
        try:
            import redis
            from rq import Queue
            conn = redis.from_url(REDIS_URL)
            q    = Queue("ada", connection=conn)
            q.enqueue(_execute, job.id, job_timeout=3600)
            return
        except Exception:
            pass
    t = threading.Thread(target=_execute, args=(job.id,), daemon=True)
    t.start()
