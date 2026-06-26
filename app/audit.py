"""
PDF Accessibility Audit Engine

Scans an uploaded PDF for ADA/PDF-UA violations, maps each finding to a
bounding box on the relevant page, renders highlighted page images, and
returns a structured JSON report the frontend can display directly.

Designed to run on the ORIGINAL uploaded PDF (before remediation) so users
can see exactly what is broken and why it needs to be fixed.
"""

import base64
import io
import re
import uuid
from typing import Optional

import fitz                        # PyMuPDF
import pikepdf
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Finding severity → color (RGBA)
# ---------------------------------------------------------------------------

_COLORS = {
    "error":   (220, 53,  53,  90),   # red, semi-transparent fill
    "warning": (234, 139, 0,   90),   # amber
    "info":    (37,  99,  235, 70),   # blue
}
_OUTLINE = {
    "error":   (220, 53,  53,  220),
    "warning": (234, 139, 0,   220),
    "info":    (37,  99,  235, 180),
}

# How much to expand a tight bbox so the highlight is clearly visible
_PAD = 4


# ---------------------------------------------------------------------------
# Plain-English issue catalogue
# A finding is produced for each rule that fires. Each entry defines:
#   title        — short label shown in the issue list
#   description  — why it matters and what needs to be fixed (or auto-fixed)
#   severity     — "error" | "warning" | "info"
#   category     — grouping label
# ---------------------------------------------------------------------------

def _finding(rule_id: str, title: str, description: str,
             severity: str, category: str,
             page: Optional[int] = None,
             bbox: Optional[list] = None,
             element: Optional[str] = None) -> dict:
    return {
        "id": f"{rule_id}_{uuid.uuid4().hex[:6]}",
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "page": page,
        "bbox": bbox,
        "element": element,
    }


# ---------------------------------------------------------------------------
# Core audit function
# ---------------------------------------------------------------------------

def audit_pdf(pdf_path: str, max_pages: int = 20) -> dict:
    """
    Run accessibility audit on `pdf_path` (the original, untagged PDF).
    Returns a dict with:
      score          0–100 (100 = no errors/warnings found)
      status         "pass" | "warning" | "fail"
      total_errors   int
      total_warnings int
      total_passed   int
      findings       list of finding dicts
      pages          list of {page_num, image_b64, finding_ids} dicts
    """
    findings = []

    # ------------------------------------------------------------------
    # 1. Document-level checks via pikepdf
    # ------------------------------------------------------------------
    try:
        pdf = pikepdf.open(pdf_path)

        # Tagged / StructTreeRoot
        has_struct = "/StructTreeRoot" in pdf.Root
        mark_info  = pdf.Root.get("/MarkInfo")
        is_marked  = bool(mark_info and mark_info.get("/Marked"))

        if not has_struct or not is_marked:
            findings.append(_finding(
                "no_tags",
                "Document has no accessibility tags",
                "Screen readers cannot read this document at all. Every element — "
                "headings, paragraphs, tables, images — must be tagged with its role. "
                "AccessiFix adds the full tag structure automatically.",
                "error", "Structure"
            ))

        # Language
        if not pdf.Root.get("/Lang"):
            findings.append(_finding(
                "no_lang",
                "No document language declared",
                "Screen readers need the language tag to pronounce words correctly. "
                "Without it, a Spanish document read by an English voice profile sounds "
                "incomprehensible. AccessiFix sets this automatically.",
                "error", "Metadata"
            ))

        # Title
        title_ok = False
        try:
            title_ok = bool(pdf.docinfo.get("/Title", "").strip())
        except Exception:
            pass
        if not title_ok:
            findings.append(_finding(
                "no_title",
                "No document title set",
                "Screen readers announce the document title when users open the file. "
                "Without a title the file name is read aloud — unhelpful for government "
                "reports and forms. AccessiFix sets a meaningful title automatically.",
                "warning", "Metadata"
            ))

        # ViewerPreferences / DisplayDocTitle
        vp = pdf.Root.get("/ViewerPreferences")
        if not (vp and vp.get("/DisplayDocTitle")):
            findings.append(_finding(
                "no_display_title",
                "Title bar shows file name, not document title",
                "Even when a title is set, Acrobat must be told to display it. "
                "This is a minor but required PDF/UA setting — AccessiFix adds it.",
                "info", "Metadata"
            ))

        pdf.close()
    except Exception as e:
        findings.append(_finding(
            "open_error",
            "Could not inspect PDF structure",
            f"The file may be password-protected or corrupted: {e}",
            "error", "Structure"
        ))

    # ------------------------------------------------------------------
    # 2. Per-page checks via PyMuPDF (images, headings, tables, links)
    # ------------------------------------------------------------------
    pages_out = []
    try:
        doc   = fitz.open(pdf_path)
        n     = min(len(doc), max_pages)
        sizes = []           # collect font sizes for heading heuristic
        page_findings: dict[int, list] = {}   # page_num (1-based) -> [finding_id]

        # First pass: collect font sizes for median body size
        for pi in range(n):
            pg = doc[pi]
            for block in pg.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sz = span.get("size", 0)
                        if sz and 6 < sz < 60:
                            sizes.append(sz)

        body_size = sorted(sizes)[len(sizes) // 2] if sizes else 12.0
        heading_threshold = body_size * 1.18   # 18% larger = likely a heading

        # Track heading levels across pages for gap detection
        prev_heading_level = 0

        for pi in range(n):
            pg        = doc[pi]
            page_num  = pi + 1
            pf        = []   # finding ids on this page

            # --- Images missing alt text ---
            images = pg.get_images(full=True)
            for img_index, img_info in enumerate(images):
                # xref is img_info[0]; check for /Alt on the associated image
                # We cannot easily check /Alt on original untagged PDFs, so we
                # flag ALL images that are not tiny decorative elements.
                try:
                    rect = pg.get_image_bbox(img_info)
                    w    = abs(rect.x1 - rect.x0)
                    h    = abs(rect.y1 - rect.y0)
                    if w < 20 and h < 20:
                        continue   # likely decorative rule/bullet
                    f = _finding(
                        "img_no_alt",
                        "Image has no alt text",
                        "Blind users hear nothing when a screen reader reaches this image. "
                        "For charts and photos, the alt text must describe what the image "
                        "conveys — not just what it looks like. "
                        "AccessiFix generates descriptive alt text automatically using AI.",
                        "error", "Images",
                        page=page_num,
                        bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
                        element=f"Image {img_index + 1} on page {page_num}"
                    )
                    findings.append(f)
                    pf.append(f["id"])
                except Exception:
                    pass

            # --- Heading hierarchy (font-size heuristic) ---
            page_headings = []
            for block in pg.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sz   = span.get("size", 0)
                        text = span.get("text", "").strip()
                        if not text or sz <= heading_threshold:
                            continue
                        # Estimate heading level by size ratio
                        ratio = sz / body_size
                        if ratio >= 2.0:
                            level = 1
                        elif ratio >= 1.6:
                            level = 2
                        elif ratio >= 1.35:
                            level = 3
                        else:
                            level = 4
                        page_headings.append((level, text, span.get("bbox"), sz))

            # Check for skipped heading levels
            for level, text, bbox, _ in page_headings:
                if prev_heading_level > 0 and level > prev_heading_level + 1:
                    f = _finding(
                        "heading_skip",
                        f"Heading skips a level (H{prev_heading_level} → H{level})",
                        f'The heading "{text[:60]}" jumps from H{prev_heading_level} to '
                        f"H{level} — skipping level(s) in between. Screen reader users "
                        "navigate by heading level; a gap breaks that navigation. "
                        "AccessiFix normalises all heading levels automatically.",
                        "error", "Headings",
                        page=page_num,
                        bbox=list(bbox) if bbox else None,
                        element=text[:80]
                    )
                    findings.append(f)
                    pf.append(f["id"])
                prev_heading_level = level

            # --- Tables without semantic headers ---
            try:
                tables = pg.find_tables()
                for ti, table in enumerate(tables):
                    if not table.rows:
                        continue
                    # Heuristic: if first row cells are not obviously bolder/larger
                    # than remaining rows, flag as potentially missing headers.
                    # PyMuPDF table extraction doesn't expose cell font directly,
                    # so we check whether the row bbox is distinctly styled by
                    # re-querying the span data in that area.
                    first_row = table.rows[0]
                    row_bbox  = fitz.Rect(first_row.rect)
                    spans_in_row = []
                    for block in pg.get_text("dict")["blocks"]:
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                sb = fitz.Rect(span.get("bbox", [0]*4))
                                if row_bbox.intersects(sb):
                                    spans_in_row.append(span)

                    # If no spans in first row are bold, treat as missing header
                    first_row_bold = any(
                        span.get("flags", 0) & 2**4  # bold flag in PyMuPDF
                        for span in spans_in_row
                    )
                    if not first_row_bold and len(table.rows) > 1:
                        rect = table.bbox
                        f = _finding(
                            "table_no_header",
                            "Table is missing a header row",
                            "Screen readers announce column names when entering a table. "
                            "Without a marked header row, a person using a screen reader "
                            "hears raw data with no context about what each column means. "
                            "AccessiFix marks header rows automatically.",
                            "warning", "Tables",
                            page=page_num,
                            bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
                            element=f"Table {ti + 1} on page {page_num}"
                        )
                        findings.append(f)
                        pf.append(f["id"])
            except Exception:
                pass

            # --- Raw URL links (not descriptive) ---
            for link in pg.get_links():
                if link.get("kind") != fitz.LINK_URI:
                    continue
                # Check the visible text at the link rect
                link_rect = fitz.Rect(link["from"])
                link_text = pg.get_text("text", clip=link_rect).strip()
                url       = link.get("uri", "")
                if re.match(r"https?://", link_text, re.I):
                    f = _finding(
                        "link_raw_url",
                        "Link displays raw URL instead of descriptive text",
                        f'"{link_text[:60]}" is not a useful link label for screen reader '
                        "users, who hear every character read aloud. Descriptive text like "
                        '"Visit the ADA compliance guide" is required by WCAG 2.4.4.',
                        "warning", "Links",
                        page=page_num,
                        bbox=list(link_rect),
                        element=link_text[:80]
                    )
                    findings.append(f)
                    pf.append(f["id"])

            page_findings[page_num] = pf

        # ------------------------------------------------------------------
        # 3. Render pages with highlight overlays
        # ------------------------------------------------------------------
        for pi in range(n):
            page_num = pi + 1
            pg       = doc[pi]
            mat      = fitz.Matrix(1.5, 1.5)   # 108 DPI
            clip     = pg.rect
            pix      = pg.get_pixmap(matrix=mat, colorspace=fitz.csRGB, clip=clip)
            img      = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw     = ImageDraw.Draw(img, "RGBA")

            # Scale factor between PDF points and rendered pixels
            sx = pix.width  / (clip.x1 - clip.x0)
            sy = pix.height / (clip.y1 - clip.y0)

            for fid in page_findings.get(page_num, []):
                fnd = next((f for f in findings if f["id"] == fid), None)
                if not fnd or not fnd.get("bbox"):
                    continue
                x0, y0, x1, y1 = fnd["bbox"]
                px0 = max(0, (x0 - clip.x0) * sx - _PAD)
                py0 = max(0, (y0 - clip.y0) * sy - _PAD)
                px1 = min(pix.width,  (x1 - clip.x0) * sx + _PAD)
                py1 = min(pix.height, (y1 - clip.y0) * sy + _PAD)
                sev  = fnd["severity"]
                fill = _COLORS.get(sev, _COLORS["info"])
                outl = _OUTLINE.get(sev, _OUTLINE["info"])
                draw.rectangle([px0, py0, px1, py1], fill=fill, outline=outl[:3] + (255,), width=2)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=72)
            b64 = base64.b64encode(buf.getvalue()).decode()

            pages_out.append({
                "page_num":    page_num,
                "image_b64":   b64,
                "finding_ids": page_findings.get(page_num, []),
            })

        doc.close()
    except Exception as e:
        findings.append(_finding(
            "render_error",
            "Could not render page images",
            f"Page rendering failed: {e}",
            "info", "Structure"
        ))

    # ------------------------------------------------------------------
    # 4. Score
    # ------------------------------------------------------------------
    errors   = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos    = [f for f in findings if f["severity"] == "info"]

    # Deduct points: errors cost 15 pts each (min 0), warnings cost 5 pts
    score = max(0, 100 - len(errors) * 15 - len(warnings) * 5)
    if errors:
        status = "fail"
    elif warnings:
        status = "warning"
    else:
        status = "pass"

    return {
        "score":          score,
        "status":         status,
        "total_errors":   len(errors),
        "total_warnings": len(warnings),
        "total_info":     len(infos),
        "findings":       findings,
        "pages":          pages_out,
    }
