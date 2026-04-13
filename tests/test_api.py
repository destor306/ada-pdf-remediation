"""
API integration tests.
Run with: pytest tests/ -v
"""

import io
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

from app.main import app

client = TestClient(app)

TEST_PDF = Path(__file__).parent.parent / "test_fldoe.pdf"


# ---------- helpers ----------

def upload_test_pdf() -> dict:
    with open(TEST_PDF, "rb") as f:
        resp = client.post("/api/upload", files={"file": ("test.pdf", f, "application/pdf")})
    assert resp.status_code == 200
    return resp.json()


# ---------- tests ----------

def test_home_page():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ADA PDF Remediation" in resp.text


def test_admin_page():
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Job Dashboard" in resp.text


def test_upload_valid_pdf():
    if not TEST_PDF.exists():
        pytest.skip("test_fldoe.pdf not found")
    data = upload_test_pdf()
    assert "upload_id" in data
    assert data["page_count"] == 7
    assert data["billing"]["total_pages"] == 7
    assert data["billing"]["free_pages"] == 3
    assert data["billing"]["billable_pages"] == 4
    assert data["billing"]["requires_payment"] is True


def test_upload_non_pdf():
    resp = client.post(
        "/api/upload",
        files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_large_file():
    big = io.BytesIO(b"0" * (51 * 1024 * 1024))  # 51 MB fake file
    resp = client.post(
        "/api/upload",
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert resp.status_code == 413


def test_process_unknown_upload():
    resp = client.post("/api/process", json={"upload_id": "nonexistent-id"})
    assert resp.status_code == 404


def test_status_unknown_job():
    resp = client.get("/api/status/nonexistent-job-id")
    assert resp.status_code == 404


def test_download_unknown_job():
    resp = client.get("/api/download/nonexistent-job-id")
    assert resp.status_code == 404


def test_billing_calculation():
    from app.billing import calculate_charge
    assert calculate_charge(3) == {
        "total_pages": 3, "free_pages": 3, "billable_pages": 0,
        "amount_usd": 0.0, "requires_payment": False,
    }
    c = calculate_charge(10)
    assert c["billable_pages"] == 7
    assert c["amount_usd"] == pytest.approx(0.35)
    assert c["requires_payment"] is True


def test_process_and_status_flow():
    """Upload → process (no AI, no Stripe) → poll status."""
    if not TEST_PDF.exists():
        pytest.skip("test_fldoe.pdf not found")

    upload = upload_test_pdf()
    upload_id = upload["upload_id"]

    # Start job (Stripe not configured → starts immediately)
    resp = client.post("/api/process", json={"upload_id": upload_id, "use_claude": False})
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    job_id = data["job_id"]

    # Poll status — job exists
    resp = client.get(f"/api/status/{job_id}")
    assert resp.status_code == 200
    status = resp.json()
    assert status["status"] in ("queued", "running", "done", "failed")
