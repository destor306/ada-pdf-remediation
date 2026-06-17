"""
Generates a complex PDF with images, tables, AcroForm fields, and signatures.
This is the hardest class of document for ADA remediation.

Accessibility problems baked in (intentional):
  - AcroForm fields with no /TU (tooltip/label) on most fields
  - Images (chart, logo, signature) with no alt text
  - Tables with no semantic header markup
  - Signature rendered as a rasterized image
  - Tab order not set to structure-based
  - No document language or title metadata
"""

import io
import math
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, PageBreak, HRFlowable, KeepTogether,
)
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdfgen_canvas
from reportlab.pdfbase import pdfmetrics
from PIL import Image as PILImage, ImageDraw
import random

OUTPUT = "test_complex_mixed.pdf"


# ── Image generators ──────────────────────────────────────────────────────────

def make_bar_chart(width=380, height=220):
    img = PILImage.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    bars = [("Jan", 42), ("Feb", 67), ("Mar", 55), ("Apr", 91), ("May", 78), ("Jun", 103)]
    bar_w = 44
    gap = 16
    baseline = height - 35
    max_val = 120
    palette = [(66, 133, 244), (52, 168, 83), (251, 188, 5),
               (234, 67, 53), (103, 58, 183), (0, 172, 193)]
    x = 18
    for i, (label, val) in enumerate(bars):
        bh = int((val / max_val) * (baseline - 20))
        draw.rectangle([x, baseline - bh, x + bar_w, baseline], fill=palette[i])
        draw.text((x + bar_w // 2 - 10, baseline + 4), label, fill=(60, 60, 60))
        draw.text((x + bar_w // 2 - 10, baseline - bh - 14), str(val), fill=(40, 40, 40))
        x += bar_w + gap
    draw.text((8, 4), "Applications Received (H1 2025)", fill=(30, 30, 30))
    draw.line([(14, 18), (14, baseline), (x - gap + 2, baseline)], fill=(120, 120, 120), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_pie_chart(width=260, height=260):
    img = PILImage.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    cx, cy, r = 130, 120, 90
    slices = [
        ("Online", 48, (66, 133, 244)),
        ("In-Person", 31, (52, 168, 83)),
        ("Mail", 13, (251, 188, 5)),
        ("Fax", 8, (234, 67, 53)),
    ]
    start = 0
    for label, pct, fill in slices:
        end = start + pct * 3.6
        draw.pieslice([cx - r, cy - r, cx + r, cy + r], start=start, end=end,
                      fill=fill, outline=(255, 255, 255))
        mid = math.radians((start + end) / 2)
        lx = int(cx + (r + 16) * math.cos(mid)) - 12
        ly = int(cy + (r + 16) * math.sin(mid)) - 6
        draw.text((lx, ly), f"{pct}%", fill=(40, 40, 40))
        start = end
    draw.text((40, 228), "Submission Channel Distribution", fill=(80, 80, 80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_signature(width=260, height=80, name="Dr. J. Williams"):
    img = PILImage.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    pts = [(10,55),(22,28),(38,18),(55,32),(50,55),(68,22),(85,55),
           (105,38),(125,55),(145,28),(165,52),(185,18),(205,48),
           (222,33),(242,52),(255,44)]
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i+1]], fill=(0, 0, 128), width=3)
    draw.line([(8, 70), (255, 70)], fill=(0, 0, 0), width=1)
    draw.text((8, 72), name, fill=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_agency_logo(width=180, height=60):
    img = PILImage.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 59, 59], fill=(0, 84, 166))
    draw.text((12, 18), "ADA", fill=(255, 255, 255))
    draw.text((68, 8), "Office of", fill=(40, 40, 40))
    draw.text((68, 24), "Civil Rights", fill=(0, 84, 166))
    draw.text((68, 40), "& Compliance", fill=(80, 80, 80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Form page builder (uses pdfgen canvas directly) ───────────────────────────

def build_form_page(c: pdfgen_canvas.Canvas, y_top: float, page_h: float):
    """Draw form fields on the current canvas page using AcroForm."""
    W = 8.5 * inch
    form = c.acroForm

    y = y_top

    # Section: Applicant Information
    c.setFont("Helvetica-Bold", 13)
    c.drawString(0.85 * inch, y, "SECTION A — APPLICANT INFORMATION")
    y -= 0.25 * inch

    c.setFont("Helvetica", 10)
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.line(0.85 * inch, y, W - 0.85 * inch, y)
    y -= 0.3 * inch

    def field_row(label, field_name, x, field_y, w, tooltip=None):
        c.setFont("Helvetica", 9)
        c.drawString(x, field_y + 14, label)
        form.textfield(
            name=field_name,
            tooltip=tooltip or "",   # intentionally blank on some — accessibility failure
            x=x, y=field_y, width=w, height=20,
            fontSize=9, borderWidth=0.5,
            borderColor=colors.HexColor("#888888"),
            fillColor=colors.HexColor("#f9f9f9"),
            textColor=colors.black,
            forceBorder=True,
        )

    left_x = 0.85 * inch
    mid_x  = 4.35 * inch
    fw_full = W - 1.7 * inch
    fw_half = (fw_full - 0.15 * inch) / 2

    # Full name — no tooltip (intentional a11y failure)
    field_row("Full Legal Name *", "full_name", left_x, y, fw_full, tooltip="")
    y -= 0.55 * inch

    # Two-column: First / Last
    field_row("First Name", "first_name", left_x, y, fw_half, tooltip="First name")
    field_row("Last Name", "last_name", mid_x, y, fw_half, tooltip="Last name")
    y -= 0.55 * inch

    # Date of birth / Case number — no tooltips (intentional)
    field_row("Date of Birth (MM/DD/YYYY)", "dob", left_x, y, fw_half, tooltip="")
    field_row("Case / File Number", "case_num", mid_x, y, fw_half, tooltip="")
    y -= 0.55 * inch

    field_row("Email Address", "email", left_x, y, fw_full, tooltip="Email address")
    y -= 0.55 * inch

    field_row("Mailing Address", "address", left_x, y, fw_full, tooltip="")
    y -= 0.55 * inch

    city_w = fw_full * 0.45
    state_w = fw_full * 0.2
    zip_w = fw_full * 0.28
    state_x = left_x + city_w + 0.1 * inch
    zip_x   = state_x + state_w + 0.1 * inch

    field_row("City", "city", left_x, y, city_w, tooltip="City")
    field_row("State", "state", state_x, y, state_w, tooltip="")
    field_row("ZIP Code", "zip", zip_x, y, zip_w, tooltip="")
    y -= 0.6 * inch

    # Checkboxes — no group label / legend in the PDF (a11y failure)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x, y, "Complaint Type (check all that apply):")
    y -= 0.28 * inch

    checkbox_items = [
        ("cb_employment",  "Employment Discrimination"),
        ("cb_housing",     "Housing Discrimination"),
        ("cb_public",      "Public Accommodation"),
        ("cb_education",   "Education"),
        ("cb_gov",         "Government Services"),
    ]
    cx = left_x
    for fname, label in checkbox_items:
        form.checkbox(
            name=fname,
            tooltip=label,   # tooltip present but no visible legend linking to group
            x=cx, y=y - 2, size=12,
            borderWidth=0.5,
            borderColor=colors.HexColor("#555555"),
            fillColor=colors.white,
            forceBorder=True,
        )
        c.setFont("Helvetica", 9)
        c.drawString(cx + 16, y + 1, label)
        cx += 1.35 * inch

    y -= 0.45 * inch

    # Radio buttons — preferred contact method
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x, y, "Preferred Contact Method:")
    y -= 0.28 * inch

    radio_opts = [("Email", "email_opt"), ("Phone", "phone_opt"), ("Mail", "mail_opt")]
    rx = left_x
    for label, val in radio_opts:
        form.radio(
            name="contact_pref",
            tooltip="",       # intentionally empty
            value=val,
            selected=(val == "email_opt"),
            x=rx, y=y - 2, size=12,
            borderWidth=0.5,
            borderColor=colors.HexColor("#555555"),
            fillColor=colors.white,
            forceBorder=True,
        )
        c.setFont("Helvetica", 9)
        c.drawString(rx + 16, y + 1, label)
        rx += 1.1 * inch

    y -= 0.55 * inch

    # Dropdown/select — use listbox (choice widget has version-specific bugs)
    c.setFont("Helvetica", 9)
    c.drawString(left_x, y + 14, "Disability Category:")
    form.listbox(
        name="disability_cat",
        tooltip="",   # intentionally blank — a11y failure
        value="-- Select --",
        options=[
            "-- Select --",
            "Mobility / Physical",
            "Vision",
            "Hearing",
            "Cognitive / Learning",
            "Psychiatric / Mental Health",
            "Other / Multiple",
        ],
        x=left_x, y=y - 30, width=fw_half, height=50,
        fontSize=9, borderWidth=0.5,
        borderColor=colors.HexColor("#888888"),
        fillColor=colors.HexColor("#f9f9f9"),
        forceBorder=True,
    )
    y -= 0.95 * inch

    # Multi-line text area
    c.setFont("Helvetica", 9)
    c.drawString(left_x, y + 14, "Description of Complaint *")
    form.textfield(
        name="description",
        tooltip="",    # intentionally blank — a11y failure
        x=left_x, y=y - 55, width=fw_full, height=70,
        fontSize=9, borderWidth=0.5,
        borderColor=colors.HexColor("#888888"),
        fillColor=colors.HexColor("#f9f9f9"),
        textColor=colors.black,
        forceBorder=True,
        fieldFlags="multiline",
    )
    y -= 1.35 * inch

    return y


# ── Platypus story (pages 2-4 only) ──────────────────────────────────────────

def build_data_pages():
    """Build the platypus-based pages 2, 3, 4."""
    styles = getSampleStyleSheet()

    H1 = ParagraphStyle("CH1", fontSize=16, leading=21, fontName="Helvetica-Bold",
                        spaceAfter=8, textColor=colors.HexColor("#1a1a2e"))
    H2 = ParagraphStyle("CH2", fontSize=12, leading=17, fontName="Helvetica-Bold",
                        spaceAfter=6, spaceBefore=12)
    BODY = ParagraphStyle("CBody", fontSize=10, leading=15, fontName="Helvetica",
                          spaceAfter=7)
    CAPTION = ParagraphStyle("CCap", fontSize=8, leading=11,
                              fontName="Helvetica-Oblique",
                              alignment=TA_CENTER, textColor=colors.grey)
    SMALL = ParagraphStyle("CSmall", fontSize=9, leading=13, fontName="Helvetica",
                           textColor=colors.HexColor("#444444"))
    FN = ParagraphStyle("CFN", fontSize=7, leading=10, fontName="Helvetica",
                        textColor=colors.grey)

    story = []

    # ── PAGE 2: Tables + Charts ──────────────────────────────────────────────
    story.append(Paragraph("SECTION B — CASE VOLUME & STATISTICS", H1))

    # Two charts side by side — no alt text
    bar_buf = make_bar_chart()
    pie_buf = make_pie_chart()
    bar_img = RLImage(bar_buf, width=3.8 * inch, height=2.2 * inch)
    pie_img = RLImage(pie_buf, width=2.6 * inch, height=2.6 * inch)

    chart_row = Table([[bar_img, pie_img]], colWidths=[4.0 * inch, 2.8 * inch])
    chart_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(chart_row)
    story.append(Paragraph(
        "Figure 1 (left): Monthly application volume, H1 2025.  "
        "Figure 2 (right): Submission channel breakdown.",
        CAPTION,
    ))
    story.append(Spacer(1, 0.15 * inch))

    # Main data table — header row styled but not semantically marked
    case_data = [
        ["Category", "Filed", "Resolved", "Pending", "Avg Days", "Compliant"],
        ["Employment",     "1,284", "1,041", "243",  "38",  "✓"],
        ["Housing",        "892",   "720",   "172",  "45",  "✓"],
        ["Public Accom.",  "674",   "519",   "155",  "29",  "✗"],
        ["Education",      "438",   "371",   "67",   "52",  "✓"],
        ["Gov. Services",  "319",   "261",   "58",   "33",  "✗"],
        ["Transportation", "203",   "180",   "23",   "41",  "✓"],
        ["TOTAL",          "3,810", "3,092", "718",  "40",  "—"],
    ]
    tbl = Table(case_data, colWidths=[1.6*inch, 0.7*inch, 0.8*inch,
                                       0.7*inch, 0.75*inch, 0.75*inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1a3a6b")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#e8edf5")),
        ("FONTSIZE",      (0, 0), (-1, -1),  9),
        ("ALIGN",         (1, 0), (-1, -1),  "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -2), [colors.white, colors.HexColor("#f4f6fb")]),
        ("GRID",          (0, 0), (-1, -1),  0.4, colors.HexColor("#c0c8d8")),
        ("TOPPADDING",    (0, 0), (-1, -1),  4),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
    ]))
    story.append(tbl)
    story.append(Paragraph("Table 1. Case summary by category, FY2025 YTD.", CAPTION))
    story.append(Spacer(1, 0.1 * inch))

    # Nested breakdown table — span-like layout, no headers
    breakdown_data = [
        ["Region", "Q1 Cases", "Q2 Cases", "YTD Total", "Resolution Rate"],
        ["Northeast",    "412",  "387",  "799",  "83.1%"],
        ["Southeast",    "388",  "401",  "789",  "81.4%"],
        ["Midwest",      "291",  "305",  "596",  "79.8%"],
        ["Southwest",    "263",  "278",  "541",  "80.2%"],
        ["West",         "540",  "545",  "1,085","82.7%"],
    ]
    tbl2 = Table(breakdown_data, colWidths=[1.4*inch, 0.9*inch, 0.9*inch, 0.9*inch, 1.2*inch])
    tbl2.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#2d6a4f")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1),  9),
        ("ALIGN",         (1, 0), (-1, -1),  "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#d8f3dc")]),
        ("GRID",          (0, 0), (-1, -1),  0.4, colors.HexColor("#95d5b2")),
        ("TOPPADDING",    (0, 0), (-1, -1),  4),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
    ]))
    story.append(tbl2)
    story.append(Paragraph("Table 2. Regional case breakdown, FY2025.", CAPTION))
    story.append(Spacer(1, 0.05 * inch))
    story.append(Paragraph(
        "¹ Resolution rate includes cases closed within 90 days of filing.",
        FN,
    ))

    story.append(PageBreak())

    # ── PAGE 3: Compliance Checklist + Signature Block ────────────────────────
    story.append(Paragraph("SECTION C — COMPLIANCE CERTIFICATION", H1))
    story.append(Paragraph(
        "The following compliance requirements have been reviewed and verified by the "
        "Office of Civil Rights and Accessibility Compliance for the reporting period "
        "ending June 30, 2025.",
        BODY,
    ))

    check_data = [
        ["Requirement",                              "Standard",         "Status",   "Due Date"],
        ["ADA Title II Self-Evaluation",             "28 CFR § 35.105",  "COMPLETE", "03/31/25"],
        ["Transition Plan Update",                   "28 CFR § 35.150",  "COMPLETE", "03/31/25"],
        ["Grievance Procedure Published",            "28 CFR § 35.107",  "COMPLETE", "01/15/25"],
        ["ADA Coordinator Designated",               "28 CFR § 35.107",  "COMPLETE", "01/01/25"],
        ["Website Accessibility (WCAG 2.1 AA)",      "DOJ Rule 2024",    "PARTIAL",  "09/30/25"],
        ["Digital Document Remediation",             "Section 508",      "IN PROG.", "12/31/25"],
        ["Employee Training – ADA Basics",           "Internal Policy",  "COMPLETE", "06/01/25"],
        ["Employee Training – Digital Access",       "Internal Policy",  "PENDING",  "09/01/25"],
        ["Reasonable Accommodation Log Updated",     "42 U.S.C. §12112", "COMPLETE", "06/30/25"],
        ["Annual Report Filed with HHS",             "§1557 ACA",        "COMPLETE", "05/01/25"],
    ]
    chk_tbl = Table(check_data, colWidths=[2.6*inch, 1.3*inch, 0.85*inch, 0.85*inch])
    chk_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#3a3a3a")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1),  8.5),
        ("ALIGN",         (2, 0), (3, -1),  "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ("GRID",          (0, 0), (-1, -1),  0.4, colors.HexColor("#bbbbbb")),
        ("TOPPADDING",    (0, 0), (-1, -1),  4),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
        ("WORDWRAP",      (0, 0), (0, -1),  "LTR"),
    ]))
    story.append(chk_tbl)
    story.append(Paragraph("Table 3. Compliance checklist — June 2025.", CAPTION))
    story.append(Spacer(1, 0.3 * inch))

    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#aaaaaa")))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Authorized Signatures", H2))
    story.append(Paragraph(
        "The undersigned certify that all information in this report is accurate, "
        "complete, and has been verified through the Department's internal review process.",
        BODY,
    ))

    # Signature 1 — rasterized image, no alt text
    sig1 = make_signature(name="Dr. J. Williams")
    sig1_img = RLImage(sig1, width=2.8 * inch, height=0.85 * inch)

    # Signature 2
    sig2 = make_signature(name="M. R. Chen")
    sig2_img = RLImage(sig2, width=2.8 * inch, height=0.85 * inch)

    sig_table = Table(
        [[sig1_img, sig2_img],
         [Paragraph("Dr. J. Williams, ADA Coordinator", SMALL),
          Paragraph("M. R. Chen, Chief Compliance Officer", SMALL)],
         [Paragraph("Date: June 12, 2025", SMALL),
          Paragraph("Date: June 12, 2025", SMALL)]],
        colWidths=[3.4 * inch, 3.4 * inch],
    )
    sig_table.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(sig_table)
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph(
        "* This document has not been verified for PDF/UA or WCAG 2.1 conformance. "
        "ADA remediation required before public distribution. "
        "Known issues: untagged form fields, no alt text on images, "
        "no semantic table header markup, no document language.",
        FN,
    ))

    story.append(PageBreak())

    # ── PAGE 4: Agency logo + mixed image/table/text ──────────────────────────
    story.append(Paragraph("APPENDIX — AGENCY CONTACT DIRECTORY", H1))

    logo_buf = make_agency_logo()
    logo_img = RLImage(logo_buf, width=1.8 * inch, height=0.6 * inch)

    hdr_table = Table(
        [[logo_img,
          Paragraph(
              "Office of Civil Rights &amp; Accessibility Compliance<br/>"
              "123 Federal Plaza, Suite 800, Washington DC 20001<br/>"
              "Tel: (202) 555-0190  |  TTY: (202) 555-0191",
              SMALL,
          )]],
        colWidths=[2.0 * inch, 4.8 * inch],
    )
    hdr_table.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ("LINEBELOW",    (0, 0), (-1, 0), 1, colors.HexColor("#1a3a6b")),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 0.15 * inch))

    contacts = [
        ["Name",                   "Title",                          "Phone",          "Email"],
        ["Dr. Janet Williams",     "ADA Coordinator",                "(202) 555-0192", "j.williams@ocrc.gov"],
        ["Marcus Chen",            "Chief Compliance Officer",       "(202) 555-0193", "m.chen@ocrc.gov"],
        ["Priya Nair",             "Section 508 Program Manager",    "(202) 555-0194", "p.nair@ocrc.gov"],
        ["Carlos Rivera",          "Complaint Intake Specialist",    "(202) 555-0195", "c.rivera@ocrc.gov"],
        ["Susan Park",             "Legal Counsel",                  "(202) 555-0196", "s.park@ocrc.gov"],
        ["Thomas Okafor",          "Accessibility Testing Lead",     "(202) 555-0197", "t.okafor@ocrc.gov"],
        ["Angela Reyes",           "Community Outreach Coordinator", "(202) 555-0198", "a.reyes@ocrc.gov"],
    ]
    ctbl = Table(contacts, colWidths=[1.5*inch, 2.0*inch, 1.2*inch, 2.0*inch])
    ctbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1a3a6b")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1),  9),
        ("ALIGN",         (2, 0), (2, -1),  "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#eef1f8")]),
        ("GRID",          (0, 0), (-1, -1),  0.4, colors.HexColor("#c0c8d8")),
        ("TOPPADDING",    (0, 0), (-1, -1),  5),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  5),
    ]))
    story.append(ctbl)
    story.append(Paragraph("Table 4. Key contact directory.", CAPTION))

    return story


# ── Main build ────────────────────────────────────────────────────────────────

def build():
    tmp_path = OUTPUT + ".tmp.pdf"
    final_path = OUTPUT

    # ── Phase 1: Platypus builds pages 2-4 into a temp file ──────────────────
    buf2 = io.BytesIO()
    doc = SimpleDocTemplate(
        buf2,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title="",
        author="",
        subject="",
    )
    doc.build(build_data_pages())
    platypus_pdf_bytes = buf2.getvalue()

    # ── Phase 2: Page 1 built with pdfgen (for AcroForm fields) ──────────────
    # Final PDF: page 1 (form) written by pdfgen canvas, then pages 2-4 merged

    from pikepdf import Pdf as PikePdf

    # Build page-1 canvas
    buf1 = io.BytesIO()
    c = pdfgen_canvas.Canvas(buf1, pagesize=letter)
    W, H = letter

    # No title, no lang metadata (intentional failures)
    c.setTitle("")
    c.setAuthor("")

    # Header
    c.setFillColor(colors.HexColor("#1a3a6b"))
    c.rect(0, H - 0.6 * inch, W, 0.6 * inch, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.white)
    c.drawString(0.85 * inch, H - 0.38 * inch, "ADA COMPLAINT / ACCOMMODATION REQUEST FORM")

    c.setFillColor(colors.black)
    y_cursor = H - 0.85 * inch
    build_form_page(c, y_cursor, H)

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.grey)
    c.drawString(0.85 * inch, 0.35 * inch,
                 "Form OCA-2025-01 | Office of Civil Rights & Accessibility Compliance | "
                 "This form is NOT screen-reader accessible — remediation required.")
    c.showPage()
    c.save()
    buf1.seek(0)

    # ── Phase 3: Merge page-1 + pages 2-4 via pikepdf ────────────────────────
    import pikepdf

    p1_pdf   = pikepdf.open(buf1)
    rest_pdf = pikepdf.open(io.BytesIO(platypus_pdf_bytes))

    merged = pikepdf.Pdf.new()
    merged.pages.append(p1_pdf.pages[0])
    for pg in rest_pdf.pages:
        merged.pages.append(pg)

    # Copy AcroForm from page-1 PDF (form fields won't survive without it)
    if "/AcroForm" in p1_pdf.Root:
        merged.Root["/AcroForm"] = merged.copy_foreign(p1_pdf.Root["/AcroForm"])

    merged.save(final_path)

    print(f"Generated: {final_path}")
    print("Intentional ADA failures:")
    print("  - AcroForm fields: most have no /TU (tooltip/label) — screen readers blind")
    print("  - Checkboxes/radios: no visible group legend (no <fieldset>/<legend> equivalent)")
    print("  - Dropdown: no tooltip")
    print("  - 2 signature images: no alt text")
    print("  - 2 chart images: no alt text")
    print("  - 1 agency logo: no alt text")
    print("  - 4 tables: no semantic header row markup")
    print("  - No document title or language metadata")
    print("  - No PDF tags (untagged)")


if __name__ == "__main__":
    build()
