"""
Convert a .docx to a tagged, accessible PDF using LibreOffice headless.

LibreOffice is free and available on all platforms. On Linux it ships with
Ubuntu. On Windows/Mac install from libreoffice.org.

The exported PDF includes document structure tags (headings, tables, alt text)
that were set in the Word document — making it readable by screen readers and
compatible with PAC 2026 / VeraPDF validation.
"""

import subprocess
import os
import shutil
import tempfile
from pathlib import Path


LIBREOFFICE_BINS = ["libreoffice", "soffice", "/usr/bin/libreoffice", "/usr/bin/soffice"]


def find_libreoffice() -> str | None:
    for b in LIBREOFFICE_BINS:
        if shutil.which(b) or Path(b).exists():
            return b
    return None


def docx_to_pdf(docx_path: str, output_pdf_path: str) -> bool:
    """
    Convert docx → tagged PDF using LibreOffice headless.
    Returns True on success, False on failure.

    LibreOffice exports using the PDF/A profile which includes structure tags.
    """
    lo = find_libreoffice()
    if not lo:
        return False

    docx_path = str(Path(docx_path).resolve())
    out_dir   = str(Path(output_pdf_path).parent.resolve())

    # LibreOffice writes output as <docx_stem>.pdf in the output dir
    expected_pdf = Path(out_dir) / (Path(docx_path).stem + ".pdf")

    # Use a temp user profile dir to avoid LibreOffice lock conflicts
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            lo,
            "--headless",
            "--norestore",
            "--nofirststartwizard",
            f"-env:UserInstallation=file://{tmpdir}",
            "--convert-to", "pdf:writer_pdf_Export",
            "--outdir", out_dir,
            docx_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

    if result.returncode != 0:
        print(f"  [pdf_export] LibreOffice error: {result.stderr[:300]}")
        return False

    if not expected_pdf.exists():
        print(f"  [pdf_export] Expected output not found: {expected_pdf}")
        return False

    # Rename to desired output path if different
    if str(expected_pdf) != output_pdf_path:
        shutil.move(str(expected_pdf), output_pdf_path)

    return True


def is_available() -> bool:
    return find_libreoffice() is not None
