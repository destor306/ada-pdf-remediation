"""
Windows GPU Worker — runs on your RTX 3070 desktop.

Uses:
  - Ollama (qwen2-vl:7b) for vision AI
  - Microsoft Word (via docx2pdf) for proper tagged PDF export
  - Redis queue to receive jobs from the web server

Setup on Windows:
  1. Install Python: python.org
  2. Install Ollama: ollama.com/download/windows
  3. Run: ollama pull qwen2-vl:7b
  4. Install Word (Microsoft 365 or standalone)
  5. pip install docx2pdf ollama pdfplumber pdf2image python-docx anthropic pillow rq redis python-dotenv
  6. Set environment variables (or create .env in this folder):
       REDIS_URL=redis://your-web-server-ip:6379
       OLLAMA_HOST=http://localhost:11434
  7. Run: python worker_windows.py

The worker pulls jobs from the 'ada' queue, processes with Ollama + Word,
and marks jobs complete. The web server serves the result to the user.
"""

import os
import sys
import traceback
import uuid
import threading
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Queue connection ──────────────────────────────────────────────────────────
REDIS_URL   = os.environ.get("REDIS_URL", "redis://localhost:6379")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2-vl:7b")

# ── PDF export backend ────────────────────────────────────────────────────────

def export_pdf_word(docx_path: str, pdf_path: str) -> bool:
    """
    Export .docx → tagged PDF using Microsoft Word's COM interface.
    This produces the highest-quality PDF/UA output.
    Requires: Word installed on Windows, pip install docx2pdf
    """
    try:
        from docx2pdf import convert
        convert(docx_path, pdf_path)
        return Path(pdf_path).exists()
    except ImportError:
        print("  [worker] docx2pdf not installed: pip install docx2pdf")
        return False
    except Exception as e:
        print(f"  [worker] Word export failed: {e}")
        return False


def export_pdf_libreoffice(docx_path: str, pdf_path: str) -> bool:
    """Fallback: LibreOffice headless (lower tag quality than Word)."""
    import subprocess, shutil, tempfile
    lo = shutil.which("soffice") or shutil.which("libreoffice")
    if not lo:
        return False
    out_dir      = str(Path(pdf_path).parent)
    expected_pdf = Path(out_dir) / (Path(docx_path).stem + ".pdf")
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            [lo, "--headless", "--norestore",
             f"-env:UserInstallation=file://{tmp}",
             "--convert-to", "pdf:writer_pdf_Export",
             "--outdir", out_dir, docx_path],
            capture_output=True, timeout=120,
        )
    if r.returncode != 0 or not expected_pdf.exists():
        return False
    if str(expected_pdf) != pdf_path:
        shutil.move(str(expected_pdf), pdf_path)
    return True


def export_pdf(docx_path: str, pdf_path: str) -> bool:
    """Try Word first (best tags), fall back to LibreOffice."""
    if export_pdf_word(docx_path, pdf_path):
        print("  [worker] PDF exported via Microsoft Word (PDF/UA quality)")
        return True
    if export_pdf_libreoffice(docx_path, pdf_path):
        print("  [worker] PDF exported via LibreOffice (fallback)")
        return True
    print("  [worker] No PDF export backend available")
    return False


# ── Job processing ────────────────────────────────────────────────────────────

def process_job(job_data: dict):
    """
    Full pipeline for one job:
      PDF → vision AI → .docx → Word PDF export → quality check
    """
    job_id      = job_data["id"]
    pdf_path    = job_data["pdf_path"]
    output_docx = job_data["output_path"]
    output_pdf  = output_docx.replace(".docx", "_ada.pdf")
    use_claude  = job_data.get("use_claude", False)

    print(f"\n{'='*60}")
    print(f"Job {job_id[:8]} | {Path(pdf_path).name}")
    print(f"{'='*60}")

    # Add project root to path so we can import ada_remediate
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        import pdfplumber
        from ada_remediate import (
            detect_backends, extract_text_layer,
            get_page_dimensions, analyze_page, build_docx, MAX_PAGES,
        )

        # Page count
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
        pages_to_process = min(total_pages, MAX_PAGES)
        print(f"Pages: {pages_to_process}")

        # Backends
        backends = detect_backends()
        if not use_claude:
            backends["claude"] = False
        print(f"Backend: {'Ollama (' + LOCAL_MODEL + ')' if backends['ollama'] else 'mock (no AI)'}")

        # Extract text hints + page dims
        text_layers = extract_text_layer(pdf_path)
        page_dims   = get_page_dimensions(pdf_path)

        # Process pages
        pages_data = []
        for page_num in range(1, pages_to_process + 1):
            print(f"  Page {page_num}/{pages_to_process}...", end=" ", flush=True)
            data = analyze_page(pdf_path, page_num, text_layers.get(page_num, ""), backends)
            pages_data.append(data)
            print(f"{len(data.get('elements', []))} elements")

        # Build Word doc
        print("Building .docx...")
        build_docx(pages_data, output_docx, page_dims=page_dims)

        # Export to tagged PDF via Word
        print("Exporting PDF...")
        pdf_ok = export_pdf(output_docx, output_pdf)

        # Quality check
        print("Running quality checks...")
        check_result = {}
        try:
            from ada_check import CheckReport, run_docx_checks, run_verapdf, check_visual_similarity
            rpt = CheckReport(source_pdf=pdf_path, docx_path=output_docx,
                              pdf_path=output_pdf if pdf_ok else None)
            run_docx_checks(pdf_path, output_docx, rpt)
            if pdf_ok:
                run_verapdf(output_pdf, rpt)
                check_visual_similarity(pdf_path, output_pdf, rpt)
            rpt.print_report()
            check_result = {
                "issues": [{"severity": i.severity, "category": i.category,
                            "message": i.message} for i in rpt.issues],
                "passed": rpt.passed,
                "failed": rpt.failed,
            }
        except Exception as ce:
            print(f"  [check] {ce}")
            check_result = {"error": str(ce)}

        print(f"\nJob {job_id[:8]} DONE")
        print(f"  docx: {output_docx}")
        print(f"  pdf:  {output_pdf if pdf_ok else 'N/A'}")
        return {"status": "done", "check_report": check_result, "has_pdf": pdf_ok}

    except Exception:
        tb = traceback.format_exc()
        print(f"\nJob {job_id[:8]} FAILED:\n{tb}")
        return {"status": "failed", "error": tb}


# ── Standalone file-based mode (no Redis) ────────────────────────────────────

def run_single(pdf_path: str, output_dir: str = "."):
    """
    Process a single PDF without Redis — useful for local testing on Windows
    before connecting to the web server.

    Usage:
      python worker_windows.py path/to/file.pdf
    """
    job_id  = str(uuid.uuid4())
    stem    = Path(pdf_path).stem
    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True)

    job_data = {
        "id":          job_id,
        "pdf_path":    str(Path(pdf_path).resolve()),
        "output_path": str(out_dir / f"{stem}_accessible.docx"),
        "use_claude":  bool(os.environ.get("ANTHROPIC_API_KEY")),
    }
    result = process_job(job_data)
    return result


# ── Redis/RQ worker mode ──────────────────────────────────────────────────────

def run_worker():
    """Connect to Redis and process jobs from the queue continuously."""
    try:
        import redis
        from rq import Worker, Queue
        conn = redis.from_url(REDIS_URL)
        conn.ping()
        print(f"Connected to Redis: {REDIS_URL}")
    except Exception as e:
        print(f"Cannot connect to Redis ({REDIS_URL}): {e}")
        print("Run in standalone mode instead: python worker_windows.py file.pdf")
        sys.exit(1)

    from rq import Worker, Queue
    q = Queue("ada", connection=conn)
    print(f"Worker ready. Listening on queue 'ada'.")
    print(f"Ollama: {OLLAMA_HOST}  Model: {LOCAL_MODEL}")
    w = Worker([q], connection=conn)
    w.work()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        # Standalone: python worker_windows.py file.pdf
        pdf   = sys.argv[1]
        outdir = sys.argv[2] if len(sys.argv) >= 3 else "."
        if not Path(pdf).exists():
            print(f"File not found: {pdf}")
            sys.exit(1)
        run_single(pdf, outdir)
    else:
        # Queue worker mode
        run_worker()
