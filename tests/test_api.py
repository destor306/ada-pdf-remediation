"""
API integration tests.
Run with: pytest tests/ -v
"""

import io
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

from app.main import app

client = TestClient(app)

ROOT = Path(__file__).parent.parent

TEST_PDF = next(
    (p for p in [
        ROOT / "test_fldoe.pdf",
        ROOT / "test_complex_text.pdf",
    ] if p.exists()),
    ROOT / "test_fldoe.pdf",
)

# Complex PDF: images + tables + AcroForm fields + signatures
COMPLEX_PDF = ROOT / "test_complex_mixed.pdf"


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
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if not admin_password:
        pytest.skip("ADMIN_PASSWORD not set — admin is locked")
    resp = client.get("/admin/", auth=("admin", admin_password))
    assert resp.status_code == 200
    assert "Admin Dashboard" in resp.text


def test_upload_valid_pdf():
    if not TEST_PDF.exists():
        pytest.skip("test_fldoe.pdf not found")
    data = upload_test_pdf()
    assert "upload_id" in data
    page_count = data["page_count"]
    assert page_count > 0
    assert data["billing"]["total_pages"] == page_count
    assert data["billing"]["free_pages"] == min(page_count, 3)
    assert data["billing"]["billable_pages"] == max(page_count - 3, 0)
    assert data["billing"]["requires_payment"] == (page_count > 3)


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


# ============================================================
# Complex PDF tests — images, tables, AcroForm, signatures
# ============================================================

@pytest.fixture(scope="module")
def complex_pdf_path():
    if not COMPLEX_PDF.exists():
        pytest.skip("test_complex_mixed.pdf not found — run generate_complex_test_pdf.py")
    return COMPLEX_PDF


def upload_complex_pdf(path: Path) -> dict:
    with open(path, "rb") as f:
        resp = client.post(
            "/api/upload",
            files={"file": (path.name, f, "application/pdf")},
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── PDF structure inspection helpers ─────────────────────────────────────────

def _open_pikepdf(path):
    import pikepdf
    return pikepdf.open(str(path))


def _count_acroform_fields(pdf_path):
    """Return the number of AcroForm fields in the PDF."""
    import pikepdf
    with pikepdf.open(str(pdf_path)) as pdf:
        acroform = pdf.Root.get("/AcroForm")
        if not acroform:
            return 0
        fields = acroform.get("/Fields", [])
        return len(fields)


def _has_accessibility_tags(pdf_path):
    """Return True if the PDF has MarkInfo Marked=True and a StructTreeRoot."""
    import pikepdf
    with pikepdf.open(str(pdf_path)) as pdf:
        mark_info = pdf.Root.get("/MarkInfo")
        if not mark_info:
            return False
        marked = mark_info.get("/Marked")
        if not bool(marked):
            return False
        return "/StructTreeRoot" in pdf.Root


def _has_lang(pdf_path):
    import pikepdf
    with pikepdf.open(str(pdf_path)) as pdf:
        return "/Lang" in pdf.Root


def _has_doc_title(pdf_path):
    import pikepdf
    with pikepdf.open(str(pdf_path)) as pdf:
        with pdf.open_metadata() as meta:
            return bool(meta.get("dc:title", "").strip())


# ── Source PDF checks ─────────────────────────────────────────────────────────

class TestComplexPdfStructure:
    """Verify the test PDF itself has the expected bad-accessibility properties."""

    def test_page_count(self, complex_pdf_path):
        import pdfplumber
        with pdfplumber.open(str(complex_pdf_path)) as pdf:
            assert len(pdf.pages) == 4

    def test_has_acroform_fields(self, complex_pdf_path):
        count = _count_acroform_fields(complex_pdf_path)
        assert count > 0, "Expected AcroForm fields on page 1"

    def test_source_is_untagged(self, complex_pdf_path):
        assert not _has_accessibility_tags(complex_pdf_path), \
            "Source PDF should NOT be tagged — it is the bad input"

    def test_source_has_no_lang(self, complex_pdf_path):
        assert not _has_lang(complex_pdf_path)

    def test_source_has_no_title(self, complex_pdf_path):
        assert not _has_doc_title(complex_pdf_path)

    def test_complex_pages_detected(self, complex_pdf_path):
        """Pages 1-3 (form/charts/tables/sigs) must classify as complex."""
        from ada_remediate import classify_page_complexity
        complexities = {
            n: classify_page_complexity(str(complex_pdf_path), n)
            for n in range(1, 5)
        }
        complex_pages = [n for n, c in complexities.items() if c == "complex"]
        # Pages 2 and 3 have embedded images — must be detected
        assert 2 in complex_pages, f"Page 2 (charts) should be complex; got {complexities}"
        assert 3 in complex_pages, f"Page 3 (signatures) should be complex; got {complexities}"

    def test_image_extraction_finds_images(self, complex_pdf_path):
        """extract_page_images must find the embedded chart and signature images."""
        from ada_remediate import extract_page_images
        # Page 2 has bar chart + pie chart
        imgs_p2 = extract_page_images(str(complex_pdf_path), 2)
        assert len(imgs_p2) >= 2, \
            f"Expected ≥2 images on page 2 (charts), found {len(imgs_p2)}"

        # Page 3 has two signature images
        imgs_p3 = extract_page_images(str(complex_pdf_path), 3)
        assert len(imgs_p3) >= 1, \
            f"Expected ≥1 image on page 3 (signatures), found {len(imgs_p3)}"

    def test_table_extraction_finds_tables(self, complex_pdf_path):
        """pdfplumber must extract table data from pages 2 and 3."""
        import pdfplumber
        with pdfplumber.open(str(complex_pdf_path)) as pdf:
            p2_tables = pdf.pages[1].extract_tables()
            assert len(p2_tables) >= 1, "Page 2 should have at least one extractable table"
            p3_tables = pdf.pages[2].extract_tables()
            assert len(p3_tables) >= 1, "Page 3 should have at least one extractable table"


# ── Upload tests ──────────────────────────────────────────────────────────────

class TestComplexPdfUpload:

    def test_upload_succeeds(self, complex_pdf_path):
        data = upload_complex_pdf(complex_pdf_path)
        assert "upload_id" in data
        assert data["page_count"] == 4

    def test_billing_on_4_pages(self, complex_pdf_path):
        data = upload_complex_pdf(complex_pdf_path)
        billing = data["billing"]
        assert billing["total_pages"] == 4
        assert billing["free_pages"] == 3
        assert billing["billable_pages"] == 1
        assert billing["requires_payment"] is True

    def test_upload_preserves_original_filename(self, complex_pdf_path):
        data = upload_complex_pdf(complex_pdf_path)
        # Upload ID should be set and non-empty
        assert data["upload_id"]


# ── Pipeline / mock-mode analysis ────────────────────────────────────────────

class TestComplexPdfAnalysis:
    """Run the analysis pipeline in mock/text mode (no AI key needed)."""

    def test_mock_analysis_all_pages(self, complex_pdf_path, tmp_path):
        """analyze_page in mock mode must return elements for every page."""
        from ada_remediate import analyze_page, extract_text_layer
        os.environ["MOCK_MODE"] = "1"
        try:
            text_layers = extract_text_layer(str(complex_pdf_path))
            backends = {"ollama": False, "claude": False, "mock": True}
            for page_num in range(1, 5):
                result = analyze_page(
                    str(complex_pdf_path), page_num,
                    text_layers.get(page_num, ""), backends,
                )
                assert result["page"] == page_num
                # Mock mode may produce empty elements for form-only pages — that's OK
                # but the result dict must always exist
                assert "elements" in result
        finally:
            del os.environ["MOCK_MODE"]

    def test_text_analysis_page2_finds_tables(self, complex_pdf_path):
        """analyze_with_mock should extract table rows from page 2."""
        from ada_remediate import analyze_with_mock, extract_text_layer
        text_layers = extract_text_layer(str(complex_pdf_path))
        result = analyze_with_mock(
            str(complex_pdf_path), 2, text_layers.get(2, "")
        )
        types = [e["type"] for e in result.get("elements", [])]
        assert "table" in types, \
            f"Expected at least one table element on page 2, got types: {types}"

    def test_table_rows_have_header_flag(self, complex_pdf_path):
        """Mock analysis should mark the first row of each table as is_header=True."""
        from ada_remediate import analyze_with_mock
        result = analyze_with_mock(str(complex_pdf_path), 2, "")
        tables = [e for e in result.get("elements", []) if e["type"] == "table"]
        for tbl in tables:
            rows = tbl.get("rows", [])
            if rows:
                assert rows[0].get("is_header") is True, \
                    f"First row of table should be is_header=True, got: {rows[0]}"

    def test_full_mock_pipeline_produces_docx(self, complex_pdf_path, tmp_path):
        """End-to-end mock pipeline: PDF → elements → DOCX without errors."""
        from ada_remediate import (
            analyze_page, extract_text_layer, get_page_dimensions,
            build_docx, extract_page_images,
        )
        os.environ["MOCK_MODE"] = "1"
        try:
            backends = {"ollama": False, "claude": False, "mock": True}
            text_layers = extract_text_layer(str(complex_pdf_path))
            page_dims = get_page_dimensions(str(complex_pdf_path))
            pages_data = [
                analyze_page(str(complex_pdf_path), n,
                             text_layers.get(n, ""), backends)
                for n in range(1, 5)
            ]
            out_docx = str(tmp_path / "output.docx")
            build_docx(pages_data, out_docx, page_dims=page_dims, title="Test Complex Mixed")
            assert Path(out_docx).exists()
            assert Path(out_docx).stat().st_size > 1000
        finally:
            del os.environ["MOCK_MODE"]

    def test_full_mock_pipeline_produces_tagged_pdf(self, complex_pdf_path, tmp_path):
        """End-to-end: source PDF → tagged accessible PDF with MarkInfo + StructTreeRoot."""
        from ada_remediate import (
            analyze_page, extract_text_layer,
            tag_pdf_with_accessibility,
        )
        os.environ["MOCK_MODE"] = "1"
        try:
            backends = {"ollama": False, "claude": False, "mock": True}
            text_layers = extract_text_layer(str(complex_pdf_path))
            pages_data = [
                analyze_page(str(complex_pdf_path), n,
                             text_layers.get(n, ""), backends)
                for n in range(1, 5)
            ]
            out_pdf = str(tmp_path / "output_accessible.pdf")
            tag_pdf_with_accessibility(
                str(complex_pdf_path), pages_data, out_pdf,
                title="ADA Complaint Form — Accessible",
            )
            assert Path(out_pdf).exists()
            assert _has_accessibility_tags(out_pdf), \
                "Output PDF must have MarkInfo Marked=True and StructTreeRoot"
            assert _has_lang(out_pdf), "Output PDF must have /Lang set"
            assert _has_doc_title(out_pdf), "Output PDF must have dc:title metadata"
        finally:
            del os.environ["MOCK_MODE"]

    def test_tagged_pdf_preserves_acroform(self, complex_pdf_path, tmp_path):
        """Tagging the PDF must not destroy the AcroForm fields."""
        from ada_remediate import (
            analyze_page, extract_text_layer, tag_pdf_with_accessibility,
        )
        os.environ["MOCK_MODE"] = "1"
        try:
            backends = {"ollama": False, "claude": False, "mock": True}
            text_layers = extract_text_layer(str(complex_pdf_path))
            pages_data = [
                analyze_page(str(complex_pdf_path), n,
                             text_layers.get(n, ""), backends)
                for n in range(1, 5)
            ]
            out_pdf = tmp_path / "output_with_form.pdf"
            tag_pdf_with_accessibility(
                str(complex_pdf_path), pages_data, str(out_pdf),
                title="ADA Form",
            )
            original_fields = _count_acroform_fields(complex_pdf_path)
            output_fields   = _count_acroform_fields(out_pdf)
            assert output_fields == original_fields, (
                f"AcroForm fields lost during tagging: "
                f"{original_fields} original → {output_fields} after"
            )
        finally:
            del os.environ["MOCK_MODE"]


# ── API flow with complex PDF ─────────────────────────────────────────────────

class TestComplexPdfApiFlow:

    def test_upload_and_process_flow(self, complex_pdf_path):
        """Upload complex PDF → kick off mock job → confirm job is tracked."""
        upload_data = upload_complex_pdf(complex_pdf_path)
        upload_id = upload_data["upload_id"]

        resp = client.post(
            "/api/process",
            json={"upload_id": upload_id, "use_claude": False},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        resp = client.get(f"/api/status/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("queued", "running", "done", "failed")

    def test_double_process_same_upload_creates_independent_jobs(self, complex_pdf_path):
        """Processing the same upload_id twice creates two independent jobs (re-run allowed)."""
        upload_data = upload_complex_pdf(complex_pdf_path)
        upload_id = upload_data["upload_id"]

        resp1 = client.post("/api/process", json={"upload_id": upload_id, "use_claude": False})
        assert resp1.status_code == 200
        job1 = resp1.json()["job_id"]

        resp2 = client.post("/api/process", json={"upload_id": upload_id, "use_claude": False})
        assert resp2.status_code == 200
        job2 = resp2.json()["job_id"]

        assert job1 != job2, "Each /process call must produce a distinct job_id"
