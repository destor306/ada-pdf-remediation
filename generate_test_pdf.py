"""
Generates a complex text-only PDF to stress-test the zero-AI text analysis path.
No tables, no images — but multiple heading levels, body paragraphs, bold labels,
ordered/unordered lists, footnote-sized text, and multi-page flow.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib import colors

OUTPUT = "test_complex_text.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    leftMargin=1.1 * inch,
    rightMargin=1.1 * inch,
    topMargin=1.0 * inch,
    bottomMargin=1.0 * inch,
)

styles = getSampleStyleSheet()

H1 = ParagraphStyle("H1", fontSize=22, leading=28, fontName="Helvetica-Bold",
                    spaceAfter=10, textColor=colors.HexColor("#1a1a2e"))
H2 = ParagraphStyle("H2", fontSize=16, leading=22, fontName="Helvetica-Bold",
                    spaceAfter=8, spaceBefore=16, textColor=colors.HexColor("#16213e"))
H3 = ParagraphStyle("H3", fontSize=13, leading=18, fontName="Helvetica-Bold",
                    spaceAfter=6, spaceBefore=10, textColor=colors.HexColor("#0f3460"))
H4 = ParagraphStyle("H4", fontSize=11, leading=16, fontName="Helvetica-Bold",
                    spaceAfter=4, spaceBefore=8)
BODY = ParagraphStyle("Body", fontSize=11, leading=16, fontName="Helvetica",
                      spaceAfter=8, alignment=TA_JUSTIFY)
BOLD_LABEL = ParagraphStyle("BoldLabel", fontSize=11, leading=16, fontName="Helvetica-Bold",
                             spaceAfter=4)
LIST_ITEM = ParagraphStyle("ListItem", fontSize=11, leading=16, fontName="Helvetica",
                            spaceAfter=4, leftIndent=20)
FOOTNOTE = ParagraphStyle("Footnote", fontSize=8, leading=12, fontName="Helvetica",
                           textColor=colors.grey, spaceAfter=4)
CENTERED = ParagraphStyle("Centered", fontSize=11, leading=16, fontName="Helvetica",
                           alignment=TA_CENTER, spaceAfter=6)

story = []

# ── PAGE 1 ──────────────────────────────────────────────────────────────────

story.append(Paragraph("UNITED STATES DEPARTMENT OF HEALTH SERVICES", H1))
story.append(Paragraph("Office of Civil Rights and Accessibility Compliance", H2))
story.append(Paragraph(
    "Policy Directive No. 2024-OCR-017: Implementation of Section 508 "
    "and Americans with Disabilities Act Requirements for Digital Communications",
    H2,
))
story.append(Spacer(1, 0.1 * inch))
story.append(Paragraph("Effective Date: October 1, 2024 &nbsp;&nbsp; Supersedes: Directive 2019-OCR-009", BODY))
story.append(Spacer(1, 0.15 * inch))

story.append(Paragraph("I. Purpose and Scope", H2))
story.append(Paragraph(
    "This directive establishes mandatory accessibility standards for all digital communications, "
    "electronic documents, and information technology systems procured, developed, or maintained by "
    "the Department. It applies to all bureau-level divisions, contracted vendors, and third-party "
    "service providers operating under a federal agreement with the Department.",
    BODY,
))
story.append(Paragraph(
    "Compliance with this directive is not optional. Failure to meet the requirements outlined herein "
    "may result in the suspension of procurement authority, mandatory remediation audits, and referral "
    "to the Office of Inspector General for review of contract performance obligations.",
    BODY,
))

story.append(Paragraph("II. Legal Authority", H2))
story.append(Paragraph(
    "This policy is issued pursuant to the following legal and regulatory authorities:",
    BODY,
))
for item in [
    "Americans with Disabilities Act of 1990 (ADA), 42 U.S.C. §§ 12101–12213",
    "Rehabilitation Act of 1973, Section 508, as amended by the Workforce Investment Act of 1998",
    "21st Century Integrated Digital Experience Act (21st Century IDEA), Pub. L. 115-336",
    "Office of Management and Budget Memorandum M-24-08: Strengthening Digital Accessibility",
    "Web Content Accessibility Guidelines (WCAG) 2.2, Level AA (W3C Recommendation, October 2023)",
    "PDF/UA-1 Standard (ISO 14289-1:2014) for accessible portable document format",
]:
    story.append(Paragraph(f"• {item}", LIST_ITEM))
story.append(Spacer(1, 0.1 * inch))

story.append(Paragraph("III. Definitions", H2))
story.append(Paragraph(
    "For the purposes of this directive, the following terms shall have the meanings ascribed below:",
    BODY,
))

story.append(Paragraph("Accessible Document", H4))
story.append(Paragraph(
    "Any electronic file, including but not limited to PDF, Word, Excel, or HTML, that conforms to "
    "recognized accessibility standards such that individuals with sensory, motor, or cognitive "
    "disabilities can perceive, understand, navigate, and interact with its content using assistive "
    "technologies, including screen readers, refreshable Braille displays, and voice recognition software.",
    BODY,
))

story.append(Paragraph("Assistive Technology (AT)", H4))
story.append(Paragraph(
    "Hardware or software that a person with a disability uses to increase, maintain, or improve their "
    "functional capabilities. Common examples include JAWS, NVDA, VoiceOver (macOS/iOS), TalkBack "
    "(Android), and ZoomText magnification software.",
    BODY,
))

story.append(Paragraph("Remediation", H4))
story.append(Paragraph(
    "The process of modifying an existing document or digital asset to bring it into conformance with "
    "applicable accessibility standards. Remediation may involve adding structural tags, alternative "
    "text descriptions, proper reading order, language metadata, and semantic markup.",
    BODY,
))

story.append(PageBreak())

# ── PAGE 2 ──────────────────────────────────────────────────────────────────

story.append(Paragraph("IV. Requirements for PDF Documents", H2))

story.append(Paragraph("A. Structural Tagging", H3))
story.append(Paragraph(
    "All PDF documents published or distributed by the Department must contain a complete and accurate "
    "logical structure tree. The structure tree must reflect the actual reading order of content as "
    "intended by the author, not the visual layout order produced by the authoring tool.",
    BODY,
))
story.append(Paragraph("Required structural tags include:", BOLD_LABEL))
for item in [
    "Document — root element encapsulating all page content",
    "H1 through H6 — hierarchical headings in sequential, non-skipping order",
    "P — standard paragraph elements for body text",
    "L and LI — list containers and list item elements",
    "Table, TR, TH, TD — table structure with proper scope attributes on header cells",
    "Figure with /Alt attribute — all non-decorative images and charts",
    "Artifact — decorative content, page numbers, and running headers/footers",
]:
    story.append(Paragraph(f"  {chr(9654)}  {item}", LIST_ITEM))
story.append(Spacer(1, 0.08 * inch))

story.append(Paragraph("B. Document Metadata Requirements", H3))
story.append(Paragraph(
    "Every accessible PDF must include the following document-level metadata properties, either "
    "embedded in the XMP metadata stream or set as document properties accessible via the PDF "
    "viewer's document properties dialog:",
    BODY,
))
for i, item in enumerate([
    "Title: A descriptive, meaningful document title (not the filename)",
    "Language: The primary language of the document content (e.g., en-US)",
    "PDF/UA identifier: Declared conformance to ISO 14289-1 via XMP property pdfuaid:part=1",
    "DisplayDocTitle: Set to True in ViewerPreferences so the title appears in the window title bar",
], 1):
    story.append(Paragraph(f"{i}. {item}", LIST_ITEM))
story.append(Spacer(1, 0.08 * inch))

story.append(Paragraph("C. Reading Order and Tab Order", H3))
story.append(Paragraph(
    "The logical reading order conveyed through the structure tree must match the intended "
    "reading sequence. Authors must not rely solely on visual placement to convey order. "
    "For multi-column documents, the structure tree must encode column-by-column flow, not "
    "left-to-right across columns.",
    BODY,
))
story.append(Paragraph(
    "Tab order for interactive elements (form fields, links, buttons) must be set to "
    "structure-based tab order (/S in the page's /Tabs entry) rather than row or unspecified order.",
    BODY,
))

story.append(Paragraph("D. Color and Contrast", H3))
story.append(Paragraph(
    "Text presented in PDF documents must meet the minimum contrast ratios defined in WCAG 2.2 "
    "Success Criterion 1.4.3 (Contrast, Minimum) at Level AA:",
    BODY,
))
story.append(Paragraph("• Normal text (below 18pt or 14pt bold): contrast ratio of at least 4.5:1", LIST_ITEM))
story.append(Paragraph("• Large text (18pt or larger, or 14pt bold or larger): contrast ratio of at least 3:1", LIST_ITEM))
story.append(Paragraph("• Logotypes and decorative text are exempt from contrast requirements", LIST_ITEM))
story.append(Spacer(1, 0.08 * inch))

story.append(Paragraph("V. Procurement and Vendor Obligations", H2))
story.append(Paragraph(
    "All contracts for the delivery of digital content, document production services, or information "
    "technology systems must include specific accessibility provisions. Contracting officers shall "
    "incorporate the following clauses into all relevant solicitations and awards:",
    BODY,
))

story.append(Paragraph("Accessibility Conformance Reporting", H4))
story.append(Paragraph(
    "Vendors must provide a current Accessibility Conformance Report (ACR) in Voluntary Product "
    "Accessibility Template (VPAT) 2.4 format for all deliverables. The ACR must be produced by a "
    "qualified accessibility evaluator and must not be older than 18 months at time of delivery.",
    BODY,
))

story.append(Paragraph("Remediation Timelines", H4))
story.append(Paragraph(
    "When accessibility defects are identified in delivered products, vendors must remediate critical "
    "failures within 15 business days and non-critical failures within 45 business days of written "
    "notification. Failure to remediate within these windows constitutes a material breach of contract.",
    BODY,
))

story.append(PageBreak())

# ── PAGE 3 ──────────────────────────────────────────────────────────────────

story.append(Paragraph("VI. Internal Review and Certification Process", H2))

story.append(Paragraph("A. Pre-Publication Review", H3))
story.append(Paragraph(
    "All documents classified as official communications, policy documents, public-facing reports, "
    "or legislative correspondence must pass an accessibility review before publication or distribution. "
    "The review process is as follows:",
    BODY,
))
for i, step in enumerate([
    "Author completes document and runs the built-in accessibility checker in the authoring tool (Microsoft Word, Adobe Acrobat, or equivalent).",
    "Author resolves all errors and warnings flagged by the built-in checker.",
    "Author submits the document to the designated Accessibility Coordinator for their bureau.",
    "Accessibility Coordinator performs a manual review using a screen reader and automated validator (PAC 2024 or AxesPDF).",
    "Documents passing review receive an Accessibility Certification stamp and are cleared for publication.",
    "Documents failing review are returned to the author with a remediation report detailing specific failures, affected pages, and required corrections.",
], 1):
    story.append(Paragraph(f"{i}.  {step}", LIST_ITEM))
story.append(Spacer(1, 0.08 * inch))

story.append(Paragraph("B. Automated Validation Tools", H3))
story.append(Paragraph(
    "The Department has standardized on the following automated accessibility validation tools. "
    "Manual review is always required in addition to automated testing; automated tools alone "
    "cannot detect all accessibility failures.",
    BODY,
))

story.append(Paragraph("PAC 2024 (PDF Accessibility Checker)", BOLD_LABEL))
story.append(Paragraph(
    "The primary tool for validating PDF/UA-1 conformance. PAC performs Matterhorn Protocol "
    "checks covering all 136 failure conditions defined in the PDF/UA standard. Free to download "
    "from the PDF Association. Required for all PDF documents prior to publication.",
    BODY,
))

story.append(Paragraph("Adobe Acrobat Pro Accessibility Checker", BOLD_LABEL))
story.append(Paragraph(
    "Available as part of the Department's Adobe Creative Cloud enterprise license. Provides "
    "real-time tagging feedback during document authoring and a full-document accessibility "
    "report. Useful for iterative remediation but does not replace PAC for final validation.",
    BODY,
))

story.append(Paragraph("Microsoft Word Accessibility Checker", BOLD_LABEL))
story.append(Paragraph(
    "Built into Microsoft Word 365 (Review tab → Check Accessibility). Should be run before "
    "exporting any Word document to PDF. Catches missing alt text, unlabeled tables, "
    "poor heading structure, and insufficient color contrast before the PDF conversion step.",
    BODY,
))

story.append(Paragraph("VII. Training and Awareness", H2))
story.append(Paragraph(
    "All Department employees who create, edit, or approve digital content are required to complete "
    "mandatory accessibility training. Training is available through the Department's Learning "
    "Management System (LMS) under course catalog number OCR-ACCESS-101.",
    BODY,
))
story.append(Paragraph("Required training modules:", BOLD_LABEL))
for item in [
    "Module 1: Introduction to Digital Accessibility and Legal Requirements (1.5 hours)",
    "Module 2: Creating Accessible Word Documents and Presentations (2 hours)",
    "Module 3: PDF Accessibility — Tagging, Reading Order, and Validation (2.5 hours)",
    "Module 4: Accessible Data Visualization and Infographic Design (1 hour)",
    "Module 5: Testing with Assistive Technology — Screen Readers and Keyboard Navigation (2 hours)",
]:
    story.append(Paragraph(f"• {item}", LIST_ITEM))

story.append(Spacer(1, 0.1 * inch))
story.append(Paragraph(
    "Training must be completed within 90 days of the effective date of this directive for existing "
    "employees, and within 30 days of onboarding for new employees. Completion records are maintained "
    "in the LMS and are subject to audit by the Office of Human Resources.",
    BODY,
))

story.append(PageBreak())

# ── PAGE 4 ──────────────────────────────────────────────────────────────────

story.append(Paragraph("VIII. Exceptions and Waivers", H2))
story.append(Paragraph(
    "Exemptions from the requirements of this directive are not granted lightly and must follow a "
    "formal waiver process. The following categories of content may be eligible for a time-limited "
    "technical exception:",
    BODY,
))

story.append(Paragraph("Archival Content", H3))
story.append(Paragraph(
    "Documents created prior to January 18, 2018 that have not been revised or redistributed since "
    "that date may qualify for archival status. Archived documents must be clearly labeled as such "
    "and must be accompanied by an accessible summary or equivalent accessible version upon request.",
    BODY,
))

story.append(Paragraph("Preprints and Draft Documents", H3))
story.append(Paragraph(
    "Working drafts, preliminary reports, and internal discussion documents that are not intended "
    "for public release or formal distribution are exempt from pre-publication review requirements. "
    "However, any such document that is later finalized or publicly released must be remediated "
    "before distribution.",
    BODY,
))

story.append(Paragraph("Technical Infeasibility", H3))
story.append(Paragraph(
    "In rare cases where full accessibility conformance is technically infeasible due to the nature "
    "of the content — for example, highly complex scientific notation, legacy scanned documents with "
    "no available source files, or specialized mathematical formula rendering — a formal waiver "
    "request may be submitted to the Chief Information Accessibility Officer (CIAO).",
    BODY,
))
story.append(Paragraph("A waiver request must include:", BOLD_LABEL))
for item in [
    "A detailed description of the content and the specific accessibility failure(s)",
    "Documentation of all remediation attempts and why full conformance cannot be achieved",
    "A proposed equivalent alternative that provides substantially the same information",
    "A remediation timeline with a target date for achieving full or partial conformance",
    "Signature of the bureau-level Director or designee",
]:
    story.append(Paragraph(f"  –  {item}", LIST_ITEM))
story.append(Spacer(1, 0.08 * inch))

story.append(Paragraph("IX. Roles and Responsibilities", H2))

story.append(Paragraph("Chief Information Accessibility Officer (CIAO)", H3))
story.append(Paragraph(
    "Provides Department-wide oversight of digital accessibility policy, issues guidance on emerging "
    "standards, reviews and approves waiver requests, and reports quarterly to the Deputy Secretary "
    "on the state of accessibility compliance across bureaus.",
    BODY,
))

story.append(Paragraph("Bureau Accessibility Coordinators", H3))
story.append(Paragraph(
    "Each bureau must designate a qualified Accessibility Coordinator responsible for conducting "
    "document reviews, maintaining a remediation log, delivering bureau-level training, and reporting "
    "compliance metrics to the CIAO on a monthly basis.",
    BODY,
))

story.append(Paragraph("Document Authors", H3))
story.append(Paragraph(
    "Individual document creators bear primary responsibility for ensuring their work meets "
    "accessibility standards prior to submission for review. Authors are expected to use accessible "
    "authoring practices from the beginning of document creation, not as a post-hoc remediation step.",
    BODY,
))

story.append(Paragraph("X. Enforcement and Non-Compliance", H2))
story.append(Paragraph(
    "Non-compliance with this directive will be addressed through the Department's standard "
    "performance management process. Depending on the severity and pattern of non-compliance, "
    "consequences may include:",
    BODY,
))
for item in [
    "Mandatory remediation training at employee expense of time",
    "Inclusion of accessibility compliance in annual performance evaluations",
    "Suspension of publishing rights pending successful completion of remediation",
    "Formal written reprimand entered into the employee's personnel file",
    "Escalation to the Office of Inspector General for patterns of willful non-compliance",
]:
    story.append(Paragraph(f"• {item}", LIST_ITEM))

story.append(Spacer(1, 0.15 * inch))
story.append(Paragraph(
    "Questions regarding this directive should be directed to the Office of Civil Rights and "
    "Accessibility Compliance at accessibility@hhs-example.gov or (202) 555-0147.",
    BODY,
))
story.append(Spacer(1, 0.08 * inch))
story.append(Paragraph(
    "This directive is effective immediately upon issuance and supersedes all previous guidance "
    "documents on digital accessibility issued by this office.",
    CENTERED,
))
story.append(Spacer(1, 0.15 * inch))
story.append(Paragraph(
    "1  WCAG 2.2 is a W3C Recommendation published October 5, 2023. Conformance to WCAG 2.1 Level AA "
    "satisfies the technical requirements of Section 508 under the Revised 508 Standards (2018). "
    "Agencies are encouraged but not required to conform to the additional criteria introduced in 2.2.",
    FOOTNOTE,
))
story.append(Paragraph(
    "2  The Matterhorn Protocol is published by the PDF Association and defines 136 checkpoints for "
    "PDF/UA-1 conformance testing. The full specification is available at pdfa.org.",
    FOOTNOTE,
))

doc.build(story)
print(f"Generated: {OUTPUT}")
