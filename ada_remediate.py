#!/usr/bin/env python3
"""
ADA PDF Remediation Tool (MVP)

Hybrid pipeline: Ollama (local, free) → Claude API fallback (paid)

Workflow:
  Input PDF → Cost estimate + confirmation → Vision analysis (per page) → .docx → Tagged PDF

Usage:
  python3 ada_remediate.py input.pdf [output.docx]

Environment:
  ANTHROPIC_API_KEY  — required only if Claude fallback is used
  OLLAMA_HOST        — optional, defaults to http://localhost:11434
  LOCAL_MODEL        — optional, defaults to qwen2-vl
  NO_FALLBACK        — set to 1 to disable Claude fallback
"""

import sys
import os
import base64
import json
import re
import io
from pathlib import Path

import sys
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

import pikepdf
import pdfplumber
from pdf2image import convert_from_path
from docx import Document
from docx.shared import Pt, Inches, Emu
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DPI = 150                        # page render resolution
LARGE_DOC_THRESHOLD = 50         # pages — prompt user confirmation above this
MAX_PAGES = 500                  # hard cap

# Cost constants (USD)
CLAUDE_COST_PER_PAGE = 0.025     # ~$0.02–0.03 estimate
LOCAL_COST_PER_PAGE = 0.0        # free

LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2-vl")
CLAUDE_MODEL = "claude-sonnet-4-5"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Poppler path (Windows — set via env or auto-detected)
_WINGET_POPPLER = os.path.expandvars(
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
)
_poppler_candidates = [
    os.environ.get("POPPLER_PATH", ""),
    next((str(p) for p in Path(_WINGET_POPPLER).glob("poppler-*/Library/bin") if p.is_dir()), "") if os.path.isdir(_WINGET_POPPLER) else "",
]
POPPLER_PATH = next((p for p in _poppler_candidates if p and os.path.isdir(p)), None)


# ---------------------------------------------------------------------------
# Vision backend detection
# ---------------------------------------------------------------------------

def detect_backends() -> dict:
    """Check which backends are available."""
    backends = {"ollama": False, "claude": False, "mock": False}

    # Check Ollama
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_HOST)
        models = client.list()
        model_names = [m.model for m in models.models]
        backends["ollama"] = any(LOCAL_MODEL in m for m in model_names)
        if not backends["ollama"]:
            print(f"  [info] Ollama running but '{LOCAL_MODEL}' not found.")
            print(f"         Run: ollama pull {LOCAL_MODEL}")
    except Exception:
        pass

    # Check Claude
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and os.environ.get("NO_FALLBACK") != "1":
        backends["claude"] = True

    # Mock mode — always available as last resort (text extraction, no AI)
    # Enabled automatically when no real backend found, or via MOCK_MODE=1
    if os.environ.get("MOCK_MODE") == "1" or (not backends["ollama"] and not backends["claude"]):
        backends["mock"] = True

    return backends


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def estimate_cost(page_count: int, backends: dict) -> tuple[float, str]:
    """Return (estimated_cost_usd, breakdown_string)."""
    if backends["ollama"]:
        cost = 0.0
        note = f"Local model ({LOCAL_MODEL}) — $0.00"
        if backends["claude"]:
            note += f" + Claude fallback at ${CLAUDE_COST_PER_PAGE:.3f}/page if needed"
    elif backends["claude"]:
        cost = page_count * CLAUDE_COST_PER_PAGE
        note = f"Claude API only — ~${cost:.2f} ({page_count} pages × ${CLAUDE_COST_PER_PAGE:.3f})"
    else:
        cost = 0.0
        note = "No AI backend available — will fail"
    return cost, note


def confirm_large_doc(page_count: int, cost_note: str) -> bool:
    """Ask user to confirm processing a large document."""
    print(f"\n  Document has {page_count} pages (over {LARGE_DOC_THRESHOLD}-page threshold).")
    print(f"  Estimated cost: {cost_note}")
    answer = input("  Continue? [y/N] ").strip().lower()
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------

def render_page_to_base64(pdf_path: str, page_number: int) -> str:
    """Render a single PDF page to a base64 PNG."""
    images = convert_from_path(
        pdf_path, dpi=DPI,
        first_page=page_number, last_page=page_number,
        fmt="png",
        poppler_path=POPPLER_PATH,
    )
    if not images:
        raise ValueError(f"Could not render page {page_number}")
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def extract_text_layer(pdf_path: str) -> dict[int, str]:
    """Extract raw text per page as a hint for vision models."""
    pages = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            pages[i] = page.extract_text() or ""
    return pages


# ---------------------------------------------------------------------------
# Shared prompt
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Page dimension extraction
# ---------------------------------------------------------------------------

def get_page_dimensions(pdf_path: str) -> list[tuple[float, float]]:
    """
    Return (width_inches, height_inches) for each page.
    PDF mediabox units are points (1 pt = 1/72 inch).
    """
    dims = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            w_pts = float(page.width)
            h_pts = float(page.height)
            dims.append((w_pts / 72.0, h_pts / 72.0))
    return dims


# ---------------------------------------------------------------------------
# Shared prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert document accessibility specialist.

Given an image of a single PDF page, reconstruct its content as a structured JSON object
suitable for building an accessible Word document.

Return ONLY valid JSON — no markdown fences, no explanation.

JSON schema:
{
  "page": <int>,
  "elements": [
    {
      "type": "heading" | "paragraph" | "table" | "list" | "caption" | "image_alt",
      "level": <int 1-6>,          // headings only
      "text": "<string>",          // all types except table
      "rows": [                    // table only
        { "is_header": <bool>, "cells": ["<string>", ...] }
      ],
      "col_widths": [0.15, 0.25, 0.60],  // table only: relative column widths (must sum to 1.0)
      "items": ["<string>", ...],  // list only
      "ordered": <bool>            // list only
    }
  ]
}

Rules:
- Preserve reading order: top-to-bottom, left-to-right for English.
- Tables: every row must have the same cell count. Identify header rows. Never merge or skip columns.
- Multi-column layouts: linearize in logical reading order.
- Headings: infer level from visual prominence (font size, bold, position). Level 1 = page/section title.
- Figures/charts: use type "image_alt" with a descriptive text.
- Footnotes: include as paragraph elements at the end.
- Omit decorative page numbers, running headers/footers, and horizontal rules.
- Blank page: return { "page": <n>, "elements": [] }.
- For tables: estimate col_widths as relative proportions matching the visual column widths.
"""


def user_message_text(page_num: int, text_hint: str) -> str:
    hint = f"\nRaw text layer hint (may be garbled):\n{text_hint[:2000]}" if text_hint.strip() else ""
    return f"This is page {page_num}.{hint}\n\nReconstruct this page as JSON per the schema."


def parse_json_response(raw: str, page_num: int) -> dict:
    """Strip markdown fences and parse JSON."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [warn] JSON parse error on page {page_num}: {e}")
        return {"page": page_num, "elements": []}


# ---------------------------------------------------------------------------
# Local model (Ollama)
# ---------------------------------------------------------------------------

def analyze_with_ollama(pdf_path: str, page_num: int, text_hint: str = "") -> dict | None:
    """Try local vision model. Returns None on failure.

    llava-family models do not support the 'system' role — they silently return
    empty when a system message is present.  Workaround: fold the system prompt
    into the user message so the full instruction arrives in one turn.
    """
    try:
        import ollama
        image_b64 = render_page_to_base64(pdf_path, page_num)
        client = ollama.Client(host=OLLAMA_HOST)

        # Combine system instructions + user request into a single user message
        combined = (
            f"{SYSTEM_PROMPT}\n\n"
            f"---\n"
            f"{user_message_text(page_num, text_hint)}"
        )

        response = client.chat(
            model=LOCAL_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": combined,
                    "images": [image_b64],
                },
            ],
            format="json",
            options={"temperature": 0},
        )
        raw = response.message.content or ""
        if not raw.strip():
            print(f"  [warn] Local model returned empty response for page {page_num}, trying fallback.")
            return None
        result = parse_json_response(raw, page_num)
        # Basic quality check: did we get any elements?
        if result.get("elements"):
            return result
        print(f"  [warn] Local model returned empty elements for page {page_num}, trying fallback.")
        return None
    except Exception as e:
        print(f"  [warn] Ollama error on page {page_num}: {e}")
        return None


# ---------------------------------------------------------------------------
# Claude API fallback
# ---------------------------------------------------------------------------

def analyze_with_claude(pdf_path: str, page_num: int, text_hint: str = "") -> dict:
    """Analyze page with Claude vision API."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    image_b64 = render_page_to_base64(pdf_path, page_num)

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
                },
                {"type": "text", "text": user_message_text(page_num, text_hint)},
            ],
        }],
    )
    raw = response.content[0].text.strip()
    return parse_json_response(raw, page_num)


# ---------------------------------------------------------------------------
# Mock backend (no AI — uses pdfplumber text extraction)
# ---------------------------------------------------------------------------

def analyze_with_mock(pdf_path: str, page_num: int, text_hint: str = "") -> dict:
    """
    No-AI fallback: converts raw pdfplumber text into structured elements.
    Good enough to test the full pipeline and UI without any API keys or Ollama.
    Output quality: readable text, basic heading detection, no table structure.
    """
    import pdfplumber

    elements = []
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num - 1]

        # Try to extract table data
        tables = page.extract_tables()
        text_outside_tables = page.extract_text() or ""

        # Detect title/heading lines (short lines at top, or ALL CAPS lines)
        lines = [l.strip() for l in text_outside_tables.splitlines() if l.strip()]
        used_as_heading = set()

        for i, line in enumerate(lines[:5]):  # first 5 lines — likely headings
            if len(line) < 80 and (line.isupper() or i == 0):
                level = 1 if i == 0 else 2
                elements.append({"type": "heading", "level": level, "text": line})
                used_as_heading.add(line)

        # Add tables
        for table in tables:
            if not table:
                continue
            rows = []
            for r_idx, row in enumerate(table):
                cells = [str(c or "").strip() for c in row]
                if any(cells):
                    rows.append({"is_header": r_idx == 0, "cells": cells})
            if rows:
                elements.append({"type": "table", "rows": rows})

        # Remaining lines as paragraphs
        for line in lines:
            if line not in used_as_heading and len(line) > 2:
                # Skip lines that are likely already captured in tables
                elements.append({"type": "paragraph", "text": line})

    return {"page": page_num, "elements": elements}


# ---------------------------------------------------------------------------
# Page analysis dispatcher
# ---------------------------------------------------------------------------

def analyze_page(
    pdf_path: str,
    page_num: int,
    text_hint: str,
    backends: dict,
) -> dict:
    """Try local first, fall back to Claude, then mock (text-only) as last resort."""
    if backends["ollama"]:
        result = analyze_with_ollama(pdf_path, page_num, text_hint)
        if result is not None:
            return result

    if backends["claude"]:
        print(f"    → Using Claude API fallback for page {page_num}")
        return analyze_with_claude(pdf_path, page_num, text_hint)

    if backends.get("mock"):
        return analyze_with_mock(pdf_path, page_num, text_hint)

    print(f"  [error] No backend available for page {page_num}. Returning empty.")
    return {"page": page_num, "elements": []}


# ---------------------------------------------------------------------------
# Word document builder
# ---------------------------------------------------------------------------

def set_cell_shading(cell, fill: str = "D9E1F2"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def add_accessible_table(doc: Document, rows_data: list[dict], col_widths: list[float] | None, page_width_in: float):
    if not rows_data:
        return
    col_count = max(len(r.get("cells", [])) for r in rows_data)
    if col_count == 0:
        return

    table = doc.add_table(rows=0, cols=col_count)
    table.style = "Table Grid"

    # Apply column widths if provided
    if col_widths and len(col_widths) == col_count:
        total = sum(col_widths) or 1.0
        usable_width = page_width_in - 1.5  # subtract margins
        for i, col in enumerate(table.columns):
            col.width = Inches(usable_width * col_widths[i] / total)

    for row_data in rows_data:
        cells_text = row_data.get("cells", [])
        is_header = row_data.get("is_header", False)

        cells_text = list(cells_text) + [""] * col_count
        cells_text = cells_text[:col_count]

        row = table.add_row()

        if is_header:
            trPr = row._tr.get_or_add_trPr()
            trPr.append(OxmlElement("w:tblHeader"))

        for i, text in enumerate(cells_text):
            cell = row.cells[i]
            para = cell.paragraphs[0]
            run = para.add_run(str(text))
            if is_header:
                run.bold = True
                set_cell_shading(cell)


def set_page_size(section, width_in: float, height_in: float):
    """Set Word section page size to match the source PDF page."""
    section.page_width = Inches(width_in)
    section.page_height = Inches(height_in)
    # Set narrow margins to maximize content area
    margin = Inches(0.75)
    section.top_margin = margin
    section.bottom_margin = margin
    section.left_margin = margin
    section.right_margin = margin
    # Orientation
    if width_in > height_in:
        section.orientation = WD_ORIENT.LANDSCAPE
    else:
        section.orientation = WD_ORIENT.PORTRAIT


def build_docx(pages_data: list[dict], output_path: str, page_dims: list[tuple[float, float]] | None = None, title: str = ""):
    doc = Document()
    doc.core_properties.title = title or Path(output_path).stem.replace("_", " ").title()
    doc.core_properties.language = "en-US"

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    # Set first section dimensions from page 1
    if page_dims:
        set_page_size(doc.sections[0], page_dims[0][0], page_dims[0][1])

    for idx, page_data in enumerate(pages_data):
        elements = page_data.get("elements", [])
        if not elements:
            continue

        # Use this page's dimensions for column width calculations
        if page_dims and idx < len(page_dims):
            page_w = page_dims[idx][0]
        else:
            page_w = 8.5  # default letter width

        for elem in elements:
            etype = elem.get("type", "paragraph")
            text = elem.get("text", "").strip()

            if etype == "heading":
                level = max(1, min(6, elem.get("level", 2)))
                p = doc.add_paragraph(style=f"Heading {level}")
                p.add_run(text)

            elif etype == "paragraph":
                if text:
                    doc.add_paragraph(text)

            elif etype == "table":
                add_accessible_table(doc, elem.get("rows", []), elem.get("col_widths"), page_w)
                doc.add_paragraph()

            elif etype == "list":
                style_name = "List Number" if elem.get("ordered") else "List Bullet"
                for item in elem.get("items", []):
                    doc.add_paragraph(item, style=style_name)

            elif etype == "caption":
                if text:
                    doc.add_paragraph(text, style="Caption")

            elif etype == "image_alt":
                p = doc.add_paragraph(f"[Figure: {text}]")
                if p.runs:
                    p.runs[0].italic = True

        if idx < len(pages_data) - 1:
            # Add page break and new section if page size changes
            doc.add_page_break()
            if page_dims and idx + 1 < len(page_dims):
                next_w, next_h = page_dims[idx + 1]
                curr_w, curr_h = page_dims[idx]
                if abs(next_w - curr_w) > 0.1 or abs(next_h - curr_h) > 0.1:
                    new_section = doc.add_section()
                    set_page_size(new_section, next_w, next_h)

    doc.save(output_path)


# ---------------------------------------------------------------------------
# PDF Accessibility Tagger (pikepdf-based, in-place)
# ---------------------------------------------------------------------------

def _decode_pdf_string(s) -> str:
    """Decode a pikepdf String to a Python str."""
    if isinstance(s, pikepdf.String):
        raw = bytes(s)
        if len(raw) >= 2 and raw[:2] == b'\xfe\xff':
            return raw[2:].decode('utf-16-be', errors='replace')
        if len(raw) >= 2 and raw[:2] == b'\xff\xfe':
            return raw[2:].decode('utf-16-le', errors='replace')
        return raw.decode('cp1252', errors='replace')
    return str(s)


def _get_block_text(instructions, start: int, end: int) -> str:
    """Extract concatenated text from a BT..ET block."""
    parts = []
    for i in range(start, end + 1):
        op = str(instructions[i].operator)
        ops = instructions[i].operands
        if op == 'Tj' and ops:
            parts.append(_decode_pdf_string(ops[0]))
        elif op == 'TJ' and ops:
            for item in ops[0]:
                if isinstance(item, (pikepdf.String, bytes)):
                    parts.append(_decode_pdf_string(item))
        elif op == "'" and ops:
            parts.append(_decode_pdf_string(ops[0]))
        elif op == '"' and len(ops) >= 3:
            parts.append(_decode_pdf_string(ops[2]))
    return ''.join(parts).strip()


def _find_content_blocks(instructions) -> list[dict]:
    """
    Find all BT..ET text blocks and standalone Do (image) operators.
    Returns list of dicts: {type, start, end, text or xobj}.
    """
    blocks = []
    in_bt = False
    bt_start = 0
    for i, instr in enumerate(instructions):
        op = str(instr.operator)
        if op == 'BT':
            in_bt = True
            bt_start = i
        elif op == 'ET' and in_bt:
            text = _get_block_text(instructions, bt_start, i)
            blocks.append({'type': 'text', 'start': bt_start, 'end': i, 'text': text})
            in_bt = False
        elif op == 'Do' and not in_bt:
            xobj = str(instructions[i].operands[0]) if instructions[i].operands else '/Im'
            blocks.append({'type': 'image', 'start': i, 'end': i, 'xobj': xobj})
    return blocks


def _match_blocks_to_elements(blocks: list[dict], elements: list[dict]) -> dict[int, tuple[str, int]]:
    """
    Match content-stream blocks to Claude-extracted elements by text overlap.
    Returns {block_index: (tag_name, local_mcid)}.
    """
    TYPE_MAP = {
        'paragraph': 'P', 'table': 'Table',
        'list': 'L', 'caption': 'Caption', 'image_alt': 'Figure',
    }

    elem_info = []
    for elem in elements:
        etype = elem.get('type', 'paragraph')
        text = elem.get('text', '').strip()
        level = elem.get('level', 1)
        tag = f'H{max(1, min(6, level))}' if etype == 'heading' else TYPE_MAP.get(etype, 'P')
        if etype == 'table':
            rows = elem.get('rows', [])
            text = ' '.join(str(c) for c in rows[0].get('cells', [])) if rows else ''
        elif etype == 'list':
            text = ' '.join(elem.get('items', [])[:3])
        elem_info.append({'tag': tag, 'text': text.lower().strip()})

    assignments = {}
    used_elements = set()
    mcid = 0

    for block_idx, block in enumerate(blocks):
        if block['type'] == 'image':
            assignments[block_idx] = ('Figure', mcid)
            mcid += 1
            continue

        block_text = block.get('text', '').lower().strip()
        if not block_text:
            continue

        best_elem, best_score = None, 0
        for ei, elem in enumerate(elem_info):
            if ei in used_elements or not elem['text']:
                continue
            bwords = set(block_text.split())
            ewords = set(elem['text'].split())
            overlap = len(bwords & ewords)
            score = overlap / max(len(bwords), len(ewords))
            if score > best_score and score > 0.2:
                best_score = score
                best_elem = ei

        if best_elem is not None:
            assignments[block_idx] = (elem_info[best_elem]['tag'], mcid)
            used_elements.add(best_elem)
            mcid += 1

    return assignments


def _inject_mcids(instructions, blocks: list[dict], assignments: dict[int, tuple[str, int]]) -> list:
    """Return a new instruction list with BDC/EMC markers injected around assigned blocks."""
    from pikepdf import ContentStreamInstruction, Operator, Name, Dictionary, Integer as PikInt

    block_starts = {b['start']: (i, b) for i, b in enumerate(blocks) if i in assignments}
    block_ends   = {b['end']:   i       for i, b in enumerate(blocks) if i in assignments}

    new_instrs = []
    for idx, instr in enumerate(instructions):
        if idx in block_starts:
            block_idx, _ = block_starts[idx]
            tag_name, mcid_val = assignments[block_idx]
            new_instrs.append(ContentStreamInstruction(
                [Name(f'/{tag_name}'), Dictionary(MCID=PikInt(mcid_val))],
                Operator('BDC'),
            ))
        new_instrs.append(instr)
        if idx in block_ends:
            new_instrs.append(ContentStreamInstruction([], Operator('EMC')))
    return new_instrs


def tag_pdf_with_accessibility(
    source_pdf: str,
    pages_data: list[dict],
    output_path: str,
    title: str = "",
) -> None:
    """
    Create an accessible PDF by tagging the ORIGINAL document in-place.
    Visual appearance (fonts, images, tables, layout) is preserved exactly.
    Adds: MarkInfo, Lang, document title, and a full StructTreeRoot with MCIDs.
    """
    from pikepdf import Dictionary, Array, Name, String, Integer as PikInt

    doc_title = title or Path(source_pdf).stem.replace("_", " ").title()

    with pikepdf.open(source_pdf) as pdf:
        # Document-level metadata
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            if not meta.get('dc:title'):
                meta['dc:title'] = doc_title
            meta['dc:language'] = 'en-US'
        pdf.Root['/Lang'] = String('en-US')
        pdf.Root['/MarkInfo'] = Dictionary(Marked=True)
        if '/StructTreeRoot' in pdf.Root:
            del pdf.Root['/StructTreeRoot']

        all_struct_elems = []
        parent_tree_nums = []
        global_mcid = 0

        for page_idx, page_data in enumerate(pages_data):
            if page_idx >= len(pdf.pages):
                break
            page_obj = pdf.pages[page_idx]
            elements = page_data.get('elements', [])
            if not elements:
                continue

            # Parse content stream
            try:
                raw_stream = pikepdf.parse_content_stream(page_obj)
                blocks = _find_content_blocks(raw_stream)
                assignments = _match_blocks_to_elements(blocks, elements)
            except Exception as e:
                print(f"  [warn] Stream parse failed p{page_idx + 1}: {e}")
                blocks, assignments = [], {}

            # Build struct elements for matched blocks
            local_mcid_to_struct = {}
            for block_idx, (tag_name, local_mcid) in assignments.items():
                page_mcid = global_mcid + local_mcid
                mcr = pdf.make_indirect(Dictionary(
                    Type=Name('/MCR'),
                    Pg=page_obj.obj,
                    MCID=PikInt(page_mcid),
                ))
                struct_d = Dictionary(
                    Type=Name('/StructElem'),
                    S=Name(f'/{tag_name}'),
                    Pg=page_obj.obj,
                    K=Array([mcr]),
                )
                # Add Alt text for figures
                if tag_name == 'Figure':
                    for elem in elements:
                        if elem.get('type') == 'image_alt':
                            alt = elem.get('text', '')[:500]
                            if alt:
                                struct_d['/Alt'] = String(alt)
                            break
                struct_ref = pdf.make_indirect(struct_d)
                local_mcid_to_struct[page_mcid] = struct_ref
                all_struct_elems.append(struct_ref)

            # Add unmatched table/figure elements (important for accessibility)
            for elem in elements:
                etype = elem.get('type')
                if etype == 'table':
                    rows = elem.get('rows', [])
                    alt = ''
                    if rows:
                        cells = rows[0].get('cells', [])
                        alt = 'Table: ' + ', '.join(str(c) for c in cells[:6])
                    struct_d = Dictionary(
                        Type=Name('/StructElem'), S=Name('/Table'), Pg=page_obj.obj,
                    )
                    if alt:
                        struct_d['/Alt'] = String(alt[:500])
                    all_struct_elems.append(pdf.make_indirect(struct_d))
                elif etype == 'image_alt':
                    text = elem.get('text', '')[:500]
                    struct_d = Dictionary(
                        Type=Name('/StructElem'), S=Name('/Figure'), Pg=page_obj.obj,
                    )
                    if text:
                        struct_d['/Alt'] = String(text)
                    all_struct_elems.append(pdf.make_indirect(struct_d))

            # Inject MCIDs into content stream
            if assignments and blocks:
                try:
                    global_assignments = {
                        bi: (tag, global_mcid + lm)
                        for bi, (tag, lm) in assignments.items()
                    }
                    new_stream = _inject_mcids(raw_stream, blocks, global_assignments)
                    page_obj['/Contents'] = pdf.make_stream(
                        pikepdf.unparse_content_stream(new_stream)
                    )
                    for page_mcid, struct_ref in local_mcid_to_struct.items():
                        parent_tree_nums += [PikInt(page_mcid), struct_ref]
                except Exception as e:
                    print(f"  [warn] MCID injection failed p{page_idx + 1}: {e}")

            if assignments:
                global_mcid += max(lm for _, lm in assignments.values()) + 1

        if not all_struct_elems:
            pdf.save(output_path)
            return

        doc_elem = pdf.make_indirect(Dictionary(
            Type=Name('/StructElem'),
            S=Name('/Document'),
            K=Array(all_struct_elems),
        ))
        for ref in all_struct_elems:
            ref['/P'] = doc_elem

        parent_tree = pdf.make_indirect(Dictionary(Nums=Array(parent_tree_nums)))
        struct_root = pdf.make_indirect(Dictionary(
            Type=Name('/StructTreeRoot'),
            K=Array([doc_elem]),
            ParentTree=parent_tree,
            ParentTreeNextKey=PikInt(global_mcid),
        ))
        doc_elem['/P'] = struct_root
        pdf.Root['/StructTreeRoot'] = struct_root

        pdf.save(output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"Error: file not found: {pdf_path}")
        sys.exit(1)

    docx_output_path = sys.argv[2] if len(sys.argv) > 2 else Path(pdf_path).stem + "_accessible.docx"
    pdf_output_path  = str(Path(pdf_path).stem + "_accessible.pdf")

    # --- Step 1: Page count ---
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
    pages_to_process = min(total_pages, MAX_PAGES)
    print(f"\nPDF: {pdf_path}")
    print(f"Pages: {total_pages}" + (f" (capped at {MAX_PAGES})" if total_pages > MAX_PAGES else ""))

    # --- Step 2: Detect backends and show cost estimate ---
    print("\nDetecting AI backends...")
    backends = detect_backends()
    print(f"  Ollama ({LOCAL_MODEL}): {'available' if backends['ollama'] else 'not available'}")
    print(f"  Claude API:             {'available' if backends['claude'] else 'not available'}")

    if not backends["ollama"] and not backends["claude"]:
        print(f"\n  [info] No AI backend found — running in mock mode (text extraction only).")
        print(f"         Output will be readable but table structure won't be reconstructed.")
        print(f"         To enable AI: install Ollama + pull {LOCAL_MODEL}, or set ANTHROPIC_API_KEY")

    cost, cost_note = estimate_cost(pages_to_process, backends)
    print(f"\nCost estimate: {cost_note}")

    # --- Step 3: Confirm large documents ---
    if pages_to_process > LARGE_DOC_THRESHOLD:
        if not confirm_large_doc(pages_to_process, cost_note):
            print("Aborted.")
            sys.exit(0)

    # --- Step 4: Extract text layer hints + page dimensions ---
    print("\nExtracting text layer and page dimensions...")
    text_layers = extract_text_layer(pdf_path)
    page_dims = get_page_dimensions(pdf_path)
    print(f"  Page sizes: {', '.join(f'{w:.1f}\"×{h:.1f}\"' for w, h in page_dims[:pages_to_process])}")

    # --- Step 5: Analyze pages ---
    pages_data = []
    claude_pages = 0
    local_pages = 0

    for page_num in range(1, pages_to_process + 1):
        backend_hint = f"(ollama)" if backends["ollama"] else "(claude)"
        print(f"  Page {page_num}/{pages_to_process} {backend_hint}...", end=" ", flush=True)
        page_data = analyze_page(pdf_path, page_num, text_layers.get(page_num, ""), backends)
        pages_data.append(page_data)
        elem_count = len(page_data.get("elements", []))
        print(f"{elem_count} elements")

    # --- Step 6: Tag original PDF with accessibility structure ---
    # (preserves all fonts, images, tables, and layout from the source PDF)
    print(f"\nTagging original PDF with accessibility structure → {pdf_output_path}")
    doc_title = Path(pdf_path).stem.replace("_", " ").title()
    tag_pdf_with_accessibility(pdf_path, pages_data, pdf_output_path, title=doc_title)
    print(f"  ✅ Accessible PDF created (visual appearance preserved).")

    # --- Step 7: Also build DOCX for editing ---
    print(f"\nBuilding editable .docx → {docx_output_path}")
    build_docx(pages_data, docx_output_path, page_dims=page_dims)

    print(f"\nDone!")
    print(f"  PDF file (primary):  {pdf_output_path}  ← visually identical to source")
    print(f"  Word file (editable): {docx_output_path}")
    print(f"\nValidate with PAC 2026: https://pac.pdf-accessibility.org")


if __name__ == "__main__":
    main()
