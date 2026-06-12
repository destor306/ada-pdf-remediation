"""
Generates a deliberately non-ADA-compliant PDF for testing.

Problems baked in:
  - No document language declaration
  - No tagged PDF structure
  - Images with no alt text
  - Tables with no header row markup
  - Inconsistent/skipped heading levels
  - Signature block as rasterized image (no text alternative)
  - Two-column layout that linearizes badly
  - Footnotes only identifiable by tiny font size
  - Pure decorative visual dividers treated as content
"""

import io
import math
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable
)
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.graphics.shapes import Drawing, Rect, Circle, Line, String
from reportlab.graphics import renderPDF
from reportlab.pdfgen import canvas as pdfgen_canvas
from PIL import Image as PILImage, ImageDraw, ImageFont
import random

OUTPUT = "test_bad_accessibility.pdf"


# ── Synthetic image generators ───────────────────────────────────────────────

def make_bar_chart_image(width=400, height=250):
    """Generate a bar chart as a PIL image (no alt text will be added)."""
    img = PILImage.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    bars = [("Q1", 82), ("Q2", 145), ("Q3", 97), ("Q4", 178)]
    bar_w = 60
    gap = 30
    baseline = height - 40
    max_val = 200
    colors_list = [(66, 133, 244), (52, 168, 83), (251, 188, 5), (234, 67, 53)]
    x = 40
    for i, (label, val) in enumerate(bars):
        bar_h = int((val / max_val) * (baseline - 20))
        fill = colors_list[i % len(colors_list)]
        draw.rectangle([x, baseline - bar_h, x + bar_w, baseline], fill=fill)
        draw.text((x + bar_w // 2 - 10, baseline + 5), label, fill=(0, 0, 0))
        draw.text((x + bar_w // 2 - 12, baseline - bar_h - 18), str(val), fill=(0, 0, 0))
        x += bar_w + gap
    draw.text((10, 5), "Revenue by Quarter ($K)", fill=(0, 0, 0))
    draw.line([(30, 20), (30, baseline), (x - gap, baseline)], fill=(0, 0, 0), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_org_chart_image(width=400, height=220):
    """Fake org chart as a rasterized image."""
    img = PILImage.new("RGB", (width, height), color=(245, 245, 250))
    draw = ImageDraw.Draw(img)
    boxes = [
        (150, 10, "CEO"),
        (50, 90, "VP Sales"),
        (250, 90, "VP Tech"),
        (10, 170, "Sales Mgr"),
        (110, 170, "Acct Mgr"),
        (210, 170, "Dev Lead"),
        (310, 170, "QA Lead"),
    ]
    for (x, y, label) in boxes:
        draw.rectangle([x, y, x + 90, y + 40], fill=(66, 133, 244), outline=(33, 66, 122), width=2)
        draw.text((x + 5, y + 12), label, fill=(255, 255, 255))
    lines = [(195, 50, 95, 90), (195, 50, 295, 90),
             (95, 130, 55, 170), (95, 130, 155, 170),
             (295, 130, 255, 170), (295, 130, 355, 170)]
    for (x1, y1, x2, y2) in lines:
        draw.line([(x1, y1), (x2, y2)], fill=(100, 100, 100), width=2)
    draw.text((120, 225), "Figure 3: Organizational Structure", fill=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_signature_image(width=280, height=90):
    """Fake cursive signature as a rasterized image."""
    img = PILImage.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Simulate a hand-drawn signature with connected curves
    pts = [
        (10, 60), (20, 30), (35, 20), (55, 35), (50, 60),
        (65, 25), (80, 60), (100, 40), (120, 60),
        (140, 30), (160, 55), (180, 20), (200, 50),
        (220, 35), (240, 55), (260, 45), (275, 50),
    ]
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=(0, 0, 128), width=3)
    draw.line([(10, 75), (275, 75)], fill=(0, 0, 0), width=1)
    draw.text((10, 78), "Authorized Signature", fill=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_pie_chart_image(width=300, height=300):
    """Simple pie chart."""
    img = PILImage.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    cx, cy, r = 150, 140, 100
    slices = [("Healthcare", 35, (66, 133, 244)),
              ("Education", 25, (52, 168, 83)),
              ("Transport", 20, (251, 188, 5)),
              ("Other", 20, (234, 67, 53))]
    start = 0
    for label, pct, fill in slices:
        end = start + pct * 3.6
        draw.pieslice([cx - r, cy - r, cx + r, cy + r],
                      start=start, end=end, fill=fill, outline=(255, 255, 255))
        mid = math.radians((start + end) / 2)
        lx = int(cx + (r + 20) * math.cos(mid))
        ly = int(cy + (r + 20) * math.sin(mid))
        draw.text((lx - 20, ly), f"{label}\n{pct}%", fill=(0, 0, 0))
        start = end
    draw.text((80, 270), "Budget Allocation 2025", fill=(80, 80, 80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Document build ────────────────────────────────────────────────────────────

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    leftMargin=0.9 * inch,
    rightMargin=0.9 * inch,
    topMargin=1.0 * inch,
    bottomMargin=1.0 * inch,
    title="",       # no title set
    author="",
    subject="",
)

styles = getSampleStyleSheet()

# Intentionally bad style hierarchy — jumps from H1 to H4, skips H2/H3
H1 = ParagraphStyle("BH1", fontSize=20, leading=26, fontName="Helvetica-Bold",
                    spaceAfter=10, textColor=colors.HexColor("#1a1a2e"))
H4 = ParagraphStyle("BH4", fontSize=13, leading=18, fontName="Helvetica-Bold",
                    spaceAfter=6, spaceBefore=12)  # skipped H2/H3
H6 = ParagraphStyle("BH6", fontSize=10, leading=14, fontName="Helvetica-BoldOblique",
                    spaceAfter=4, spaceBefore=8, textColor=colors.grey)
BODY = ParagraphStyle("BBody", fontSize=11, leading=16, fontName="Helvetica",
                      spaceAfter=8, alignment=TA_JUSTIFY)
CAPTION = ParagraphStyle("BCaption", fontSize=8, leading=11, fontName="Helvetica-Oblique",
                          alignment=TA_CENTER, textColor=colors.grey)
FOOTNOTE = ParagraphStyle("BFootnote", fontSize=7, leading=10, fontName="Helvetica",
                           textColor=colors.grey)
SMALL = ParagraphStyle("BSmall", fontSize=9, leading=13, fontName="Helvetica",
                       textColor=colors.darkgrey)

story = []

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Cover / Executive Summary
# ══════════════════════════════════════════════════════════════════════════════

story.append(Paragraph("FLORIDA DEPARTMENT OF EDUCATION", H1))
story.append(Paragraph("Annual Performance & Accessibility Report", H4))
story.append(Paragraph("Fiscal Year 2024–2025", H6))
story.append(Spacer(1, 0.15 * inch))

# Bar chart — no alt text in PDF metadata
bar_img = Image(make_bar_chart_image(), width=4.5 * inch, height=2.8 * inch)
story.append(bar_img)
# Caption placed as tiny text, not linked semantically
story.append(Paragraph("Figure 1. Quarterly revenue performance (2025)", CAPTION))
story.append(Spacer(1, 0.1 * inch))

story.append(Paragraph(
    "This report summarizes the Department's performance across four key areas: "
    "student achievement, program funding, staff development, and compliance. "
    "Data presented reflects outcomes from the 2024–2025 academic year across "
    "all 67 Florida school districts.",
    BODY,
))

# Table without header row markup — first row styled visually but not semantically
data = [
    ["District", "Enrollment", "Grad Rate %", "Budget ($M)", "Compliance"],
    ["Miami-Dade",   "356,000",  "84.2",  "4,820",  "✓"],
    ["Broward",      "271,000",  "87.1",  "3,650",  "✓"],
    ["Palm Beach",   "193,000",  "85.9",  "2,610",  "✗"],
    ["Hillsborough", "225,000",  "83.4",  "3,050",  "✓"],
    ["Orange",       "210,000",  "82.7",  "2,840",  "✗"],
    ["Pinellas",     "97,000",   "88.3",  "1,310",  "✓"],
    ["Duval",        "130,000",  "80.1",  "1,760",  "✗"],
    ["Lee",          "95,000",   "81.6",  "1,280",  "✓"],
]
tbl = Table(data, colWidths=[1.5*inch, 1.0*inch, 1.0*inch, 1.0*inch, 0.8*inch])
tbl.setStyle(TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
    ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
    ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",     (0, 0), (-1, -1), 9),
    ("ALIGN",        (1, 0), (-1, -1), "CENTER"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
    ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
    ("TOPPADDING",   (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
]))
story.append(tbl)
story.append(Paragraph("Table 1. District summary — top 8 by enrollment", CAPTION))
story.append(Spacer(1, 0.05 * inch))
story.append(Paragraph(
    "<super>1</super> Compliance column reflects Section 508 filing status only. "
    "Full ADA audit results available in Appendix C.",
    FOOTNOTE,
))

story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Budget & Org Structure
# ══════════════════════════════════════════════════════════════════════════════

story.append(Paragraph("Budget Allocation & Organizational Overview", H1))
story.append(Spacer(1, 0.1 * inch))

# Two images side by side — no alt text
pie_buf = make_pie_chart_image()
org_buf = make_org_chart_image()
pie_img = Image(pie_buf, width=2.9 * inch, height=2.9 * inch)
org_img = Image(org_buf, width=3.5 * inch, height=2.2 * inch)

side_by_side = Table([[pie_img, org_img]], colWidths=[3.1*inch, 3.6*inch])
side_by_side.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
]))
story.append(side_by_side)
story.append(Paragraph("Figure 2 (left): Budget allocation 2025.  Figure 3 (right): Org chart.", CAPTION))
story.append(Spacer(1, 0.15 * inch))

story.append(Paragraph("Funding Sources", H4))
story.append(Paragraph(
    "Federal Title I funding accounts for the largest single revenue stream at 38% of total "
    "operating budget. State allocations declined 4.2% year-over-year due to revised formula "
    "weighting. Local property tax contributions increased 6.1%, partially offsetting state "
    "reductions. The Department maintains a 3.5% reserve fund per statutory requirement.",
    BODY,
))

# Nested table — complex with merged-looking layout, no headers
fund_data = [
    ["Source", "FY2024 ($M)", "FY2025 ($M)", "Change"],
    ["Federal Title I",     "2,840", "2,910",  "+2.5%"],
    ["Federal IDEA",        "890",   "905",    "+1.7%"],
    ["State Base Funding",  "8,120", "7,780",  "-4.2%"],
    ["Local Property Tax",  "4,450", "4,722",  "+6.1%"],
    ["Grants & Other",      "560",   "598",    "+6.8%"],
    ["TOTAL",               "16,860","16,915", "+0.3%"],
]
fund_tbl = Table(fund_data, colWidths=[2.2*inch, 1.2*inch, 1.2*inch, 1.0*inch])
fund_tbl.setStyle(TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#34a853")),
    ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
    ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
    # Last row totals — bold but no scope attribute
    ("FONTNAME",     (0, -1), (-1, -1), "Helvetica-Bold"),
    ("BACKGROUND",   (0, -1), (-1, -1), colors.HexColor("#e8f5e9")),
    ("FONTSIZE",     (0, 0), (-1, -1), 9),
    ("ALIGN",        (1, 0), (-1, -1), "RIGHT"),
    ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#c8e6c9")),
    ("TOPPADDING",   (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
]))
story.append(fund_tbl)
story.append(Paragraph("Table 2. Funding by source", CAPTION))

story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — Program Performance (text-heavy, bad heading hierarchy)
# ══════════════════════════════════════════════════════════════════════════════

story.append(Paragraph("Program Performance Metrics", H1))
story.append(Spacer(1, 0.05 * inch))

# Skips to H6 — bad hierarchy
story.append(Paragraph("3.1  Early Childhood Education", H6))
story.append(Paragraph(
    "Voluntary Pre-K enrollment reached 178,432 children statewide, representing a 3.8% "
    "increase over FY2024. Kindergarten readiness scores improved across all five domains "
    "of the Florida Kindergarten Readiness Screener (FLKRS). Districts with dedicated "
    "coaching programs showed 12-point gains on average versus 4-point gains in control "
    "districts.",
    BODY,
))

story.append(Paragraph("3.2  K–12 Achievement", H6))
story.append(Paragraph(
    "Florida Assessment of Student Thinking (FAST) results indicate 61% of Grade 3 students "
    "achieved Level 3 or above in English Language Arts, up from 57% in FY2024. Mathematics "
    "proficiency at Grade 8 remained flat at 52%. Science scores declined 2 points at Grade 5, "
    "requiring targeted intervention.",
    BODY,
))

# A table with no header markup, mixed text/number columns
perf_data = [
    ["Metric",                     "Target", "FY2024", "FY2025", "Status"],
    ["Grade 3 ELA Proficiency",    "65%",    "57%",    "61%",    "↑ Progress"],
    ["Grade 8 Math Proficiency",   "58%",    "52%",    "52%",    "→ Flat"],
    ["Grade 5 Science",            "60%",    "54%",    "52%",    "↓ Declined"],
    ["HS Graduation Rate",         "90%",    "86.4%",  "87.2%",  "↑ Progress"],
    ["College Readiness (SAT≥1010)","45%",   "38%",    "40%",    "↑ Progress"],
    ["Teacher Retention Rate",     "88%",    "82%",    "84%",    "↑ Progress"],
    ["Chronic Absenteeism Rate",   "<12%",   "14.8%",  "13.2%",  "↑ Progress"],
]
perf_tbl = Table(perf_data, colWidths=[2.4*inch, 0.8*inch, 0.8*inch, 0.8*inch, 1.0*inch])
perf_tbl.setStyle(TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#ea4335")),
    ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
    ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",     (0, 0), (-1, -1), 8.5),
    ("ALIGN",        (1, 0), (-1, -1), "CENTER"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fce8e6")]),
    ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#f5c6c2")),
    ("TOPPADDING",   (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
]))
story.append(perf_tbl)
story.append(Paragraph("Table 3. Key performance indicators FY2025", CAPTION))
story.append(Spacer(1, 0.1 * inch))

story.append(Paragraph("3.3  Special Education", H6))
story.append(Paragraph(
    "Individualized Education Program (IEP) compliance rate stands at 94.7%, exceeding the "
    "federal threshold of 90%. Least Restrictive Environment placements in general education "
    "settings increased to 68.3%. However, 12 districts remain under corrective action plans "
    "for disproportionate representation of minority students in exceptional student education.",
    BODY,
))

story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — Compliance, Signature Block
# ══════════════════════════════════════════════════════════════════════════════

story.append(Paragraph("Compliance Certifications & Approval", H1))
story.append(Spacer(1, 0.08 * inch))

story.append(Paragraph(
    "This report has been reviewed and approved in accordance with Florida Statute §1001.10 "
    "and the federal Government Performance and Results Act (GPRA). The undersigned certify "
    "that all data presented herein is accurate to the best of their knowledge and has been "
    "validated through the Department's internal quality assurance process.",
    BODY,
))

# Compliance checklist table — no header
check_data = [
    ["Requirement",                                    "Status",  "Reference"],
    ["Section 508 Electronic Filing",                  "COMPLETE","29 U.S.C. § 794d"],
    ["Title II ADA Self-Evaluation",                   "PENDING", "28 CFR Part 35"],
    ["WCAG 2.1 AA Digital Documents",                  "PARTIAL", "DOJ Guidance 2024"],
    ["Florida Accessibility Standards (FAS)",          "COMPLETE","Rule 60-8.002"],
    ["Annual Progress Report Submission",              "COMPLETE","§1001.10(3)(c)"],
    ["Public Comment Period (30 days)",                "COMPLETE","§120.54"],
    ["Data Governance Certification",                  "COMPLETE","Fla. Exec. Order 21-02"],
]
check_tbl = Table(check_data, colWidths=[3.2*inch, 1.1*inch, 1.7*inch])
check_tbl.setStyle(TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#4a4a4a")),
    ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
    ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",     (0, 0), (-1, -1), 9),
    ("ALIGN",        (1, 0), (1, -1), "CENTER"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
    ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
    ("TOPPADDING",   (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
]))
story.append(check_tbl)
story.append(Paragraph("Table 4. Regulatory compliance checklist", CAPTION))
story.append(Spacer(1, 0.25 * inch))

story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
story.append(Spacer(1, 0.15 * inch))

# Signature block — rasterized image, no text alternative
story.append(Paragraph("Authorized By:", BODY))
sig_img = Image(make_signature_image(), width=3.0 * inch, height=0.95 * inch)
story.append(sig_img)
story.append(Paragraph("Dr. Sarah M. Johnson, Commissioner", SMALL))
story.append(Paragraph("Florida Department of Education", SMALL))
story.append(Paragraph("Date: June 12, 2025", SMALL))
story.append(Spacer(1, 0.1 * inch))

story.append(Paragraph("Co-signed:", BODY))
sig2_buf = make_signature_image()  # reuse
sig2_img = Image(sig2_buf, width=3.0 * inch, height=0.95 * inch)
story.append(sig2_img)
story.append(Paragraph("James R. Thornton, Chief Financial Officer", SMALL))
story.append(Paragraph("Florida Department of Education", SMALL))
story.append(Paragraph("Date: June 12, 2025", SMALL))
story.append(Spacer(1, 0.15 * inch))

story.append(Paragraph(
    "<super>*</super> This document has not been verified for PDF/UA or WCAG 2.1 conformance. "
    "Accessibility remediation required before public distribution.",
    FOOTNOTE,
))

story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — Appendix (data-heavy, complex table)
# ══════════════════════════════════════════════════════════════════════════════

story.append(Paragraph("Appendix A: District-Level Data", H1))
story.append(Spacer(1, 0.05 * inch))

# Large table — no row header, no scope
appendix_data = [
    ["District", "Region", "Schools", "Students", "Teachers", "Budget ($M)", "Grad%", "ELA3", "Math8"],
    ["Alachua",       "NF", "43",   "31,200",  "2,100",  "420",  "87.1","63","55"],
    ["Baker",         "NF", "8",    "4,100",   "310",    "55",   "82.0","58","49"],
    ["Bay",           "NW", "38",   "25,600",  "1,850",  "345",  "85.4","60","52"],
    ["Bradford",      "NF", "7",    "3,900",   "295",    "53",   "80.1","55","47"],
    ["Brevard",       "CE", "93",   "73,100",  "4,800",  "985",  "88.9","64","56"],
    ["Broward",       "SE", "241",  "271,000", "16,500", "3,650","87.1","62","54"],
    ["Calhoun",       "NW", "5",    "2,200",   "175",    "30",   "79.3","52","44"],
    ["Charlotte",     "SW", "22",   "19,500",  "1,350",  "263",  "86.2","61","53"],
    ["Citrus",        "CE", "24",   "17,200",  "1,200",  "232",  "84.7","59","51"],
    ["Clay",          "NE", "38",   "41,300",  "2,700",  "556",  "89.4","65","57"],
    ["Collier",       "SW", "60",   "50,200",  "3,400",  "676",  "86.8","62","54"],
    ["Columbia",      "NF", "17",   "11,400",  "820",    "154",  "83.1","57","49"],
    ["Desoto",        "SW", "10",   "7,600",   "570",    "102",  "80.5","54","46"],
    ["Dixie",         "NF", "5",    "2,400",   "195",    "32",   "78.2","51","43"],
    ["Duval",         "NE", "168",  "130,000", "8,600",  "1,760","80.1","58","50"],
]
appendix_tbl = Table(appendix_data, colWidths=[
    1.3*inch, 0.5*inch, 0.5*inch, 0.8*inch,
    0.7*inch, 0.7*inch, 0.5*inch, 0.5*inch, 0.5*inch
])
appendix_tbl.setStyle(TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
    ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
    ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",     (0, 0), (-1, -1), 8),
    ("ALIGN",        (1, 0), (-1, -1), "CENTER"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
    ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#bdc3c7")),
    ("TOPPADDING",   (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
]))
story.append(appendix_tbl)
story.append(Paragraph(
    "Table A-1. District data (partial — 15 of 67 districts shown). "
    "Full dataset available at fldoe.org/data. Regions: NF=North Florida, "
    "NW=Northwest, NE=Northeast, CE=Central, SE=Southeast, SW=Southwest.",
    CAPTION,
))

story.append(Spacer(1, 0.15 * inch))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
story.append(Spacer(1, 0.05 * inch))
story.append(Paragraph(
    "This document was generated for testing purposes. It intentionally lacks PDF/UA "
    "tagging, document language metadata, proper heading hierarchy, alt text for images, "
    "and semantic table header markup. Use accessifix.com to remediate.",
    FOOTNOTE,
))

# Build
doc.build(story)
print(f"Generated: {OUTPUT}")
print("ADA issues baked in:")
print("  - No PDF/UA tags (untagged PDF)")
print("  - No document language")
print("  - No title metadata")
print("  - 5 images with no alt text (bar chart, pie chart, org chart, 2x signature)")
print("  - 5 tables with no semantic header markup")
print("  - Heading hierarchy jumps H1->H4->H6 (skips H2, H3, H5)")
print("  - Footnotes only distinguished by font size")
print("  - Signatures as rasterized images (no text equivalent)")
