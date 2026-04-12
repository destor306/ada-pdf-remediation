"""
In-memory job store with background thread execution.
For production, replace with Redis + RQ or Celery.
"""

import uuid
import threading
import traceback
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.config import UPLOAD_DIR, OUTPUT_DIR


JobStatus = Literal["queued", "running", "done", "failed"]


class Job:
    def __init__(self, job_id: str, pdf_path: str, output_path: str, use_claude: bool = False):
        self.id = job_id
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.use_claude = use_claude
        self.status: JobStatus = "queued"
        self.progress = 0          # 0–100
        self.current_page = 0
        self.total_pages = 0
        self.error: str | None = None
        self.check_report: dict | None = None
        self.created_at = datetime.utcnow().isoformat()
        self.completed_at: str | None = None


# Global job store (thread-safe via lock)
_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def create_job(pdf_path: str, output_path: str, use_claude: bool = False) -> Job:
    job_id = str(uuid.uuid4())
    job = Job(job_id, pdf_path, output_path, use_claude)
    with _lock:
        _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    with _lock:
        return list(_jobs.values())


def run_job(job: Job):
    """Execute the remediation pipeline in a background thread."""
    import sys
    import os
    sys.path.insert(0, str(Path(__file__).parent.parent))

    job.status = "running"
    try:
        import pdfplumber
        with pdfplumber.open(job.pdf_path) as pdf:
            job.total_pages = len(pdf.pages)

        # Import pipeline components
        from ada_remediate import (
            detect_backends, extract_text_layer, get_page_dimensions,
            analyze_page, build_docx, MAX_PAGES
        )

        backends = detect_backends()

        # Override: if use_claude and API key set, allow it; otherwise local only
        if not job.use_claude:
            backends["claude"] = False

        pages_to_process = min(job.total_pages, MAX_PAGES)
        text_layers = extract_text_layer(job.pdf_path)
        page_dims = get_page_dimensions(job.pdf_path)

        pages_data = []
        for page_num in range(1, pages_to_process + 1):
            job.current_page = page_num
            job.progress = int((page_num - 1) / pages_to_process * 90)
            page_data = analyze_page(
                job.pdf_path, page_num,
                text_layers.get(page_num, ""),
                backends
            )
            pages_data.append(page_data)

        job.progress = 90
        build_docx(pages_data, job.output_path, page_dims=page_dims)

        # Run local docx quality checks
        job.progress = 95
        try:
            from ada_check import CheckReport, run_docx_checks
            report = CheckReport(
                source_pdf=job.pdf_path,
                docx_path=job.output_path,
            )
            run_docx_checks(job.pdf_path, job.output_path, report)
            job.check_report = {
                "issues": [
                    {"severity": i.severity, "category": i.category, "message": i.message}
                    for i in report.issues
                ],
                "passed": report.passed,
                "failed": report.failed,
            }
        except Exception as check_err:
            job.check_report = {"error": str(check_err)}

        job.progress = 100
        job.status = "done"
        job.completed_at = datetime.utcnow().isoformat()

    except Exception as e:
        job.status = "failed"
        job.error = traceback.format_exc()
        job.completed_at = datetime.utcnow().isoformat()


def start_job(job: Job):
    """Launch job in a daemon thread."""
    t = threading.Thread(target=run_job, args=(job,), daemon=True)
    t.start()
