"""
Frank's PDF document generator (2026-09-04, P Corp OS systems audit) -- one
generic tool, not a template picker. The original brief asked for
proposals/quotes/reports/SOPs/briefs/contracts/financial reports; the
right architecture is ONE `generate_pdf_document` tool that renders
arbitrary structured content well, not a dozen bespoke generators. Frank
already has full context (every build_*_block() in main.py's system
prompt, plus every other domain tool to pull real numbers from) -- he
decides what a "financial report" or "quote" should actually say; this
module's only job is turning well-structured markdown into a
professionally formatted PDF.

Content model is a deliberately constrained markdown subset (headings,
paragraphs, bullet lists, simple pipe tables), not a nested JSON schema --
generating flowing markdown is something Claude is already good at, and
there's precedent for exactly this constraint already working:
PCorpKit/Sources/PCorpKit/SimpleMarkdownView.swift renders Frank's chat
replies the same way today, just without tables. This parser goes one step
further and supports simple tables too, since a real business document is
far more likely to need one than a chat bubble is.

Fails soft on content, fails loud on the file itself: any line the tiny
parser doesn't recognize as a heading/bullet/table row just falls through
to being treated as a plain paragraph (see _markdown_to_flowables below --
there is no "unparseable" case, every line matches something), so a
malformed table or stray syntax degrades to ugly-but-present text rather
than crashing the whole PDF. But if the PDF itself can't actually be
produced (disk full, permissions, a genuine reportlab error), that's
surfaced as a real error string back to Frank via execute_documents_tool_
call's try/except -- unlike trading_division.py's fail-soft-on-a-missing-
external-database (a completely separate project's file layout isn't this
app's business), a document Josh is relying on as a real deliverable is
this app's business, and a fake "success" would be actively worse than an
honest failure.

No dedicated _db.py -- there's no structured data to persist, just files
on disk, so this stays one file (same shape as legacy_vault.py/
decision_journal.py/focus.py, not joshx_tools.py's split, which only
exists where there's a real _db.py to separate from).
"""

import re
import xml.sax.saxutils as saxutils
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Same "backend/data/" convention as every DB_PATH in this codebase
# (joshx_db.py, finance_db.py, etc.) -- real generated output lives here,
# not somewhere temporary. Created on first use, not a manual setup step.
DOCS_DIR = Path(__file__).parent.parent / "data" / "generated_documents"

# Resolved relative to this file rather than hardcoded to a machine-
# specific location -- __file__ is backend/app/documents.py, so three
# .parent hops land at the repo root, then down into desktop/'s own real,
# git-tracked logo asset. Valid whether running via `uv run` in dev or
# from inside the bundled .app (backend_shim.c's PYTHONPATH points at this
# real repo checkout, not a bundled copy).
LOGO_PATH = (
    Path(__file__).parent.parent.parent
    / "desktop" / "Sources" / "PCorpOS" / "Resources" / "p_logo_black.png"
)

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_TABLE_DELIM_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _inline_markdown_to_xml(text: str) -> str:
    """**bold**/*italic* -> reportlab's mini-XML markup. Escape entities
    FIRST (Paragraph parses this as XML -- a raw "&" or "<" from Frank's
    own text would otherwise break parsing), then layer bold before italic
    so **bold** pairs are consumed before leftover single "*"s are read as
    italics."""
    escaped = saxutils.escape(text)
    bolded = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return re.sub(r"\*(.+?)\*", r"<i>\1</i>", bolded)


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "DocBody": ParagraphStyle(
            "DocBody", parent=base["BodyText"], fontSize=10.5, leading=15, spaceAfter=8,
        ),
        "DocH1": ParagraphStyle(
            "DocH1", parent=base["Heading1"], fontSize=18, leading=22,
            spaceBefore=4, spaceAfter=12, textColor=colors.HexColor("#1a1a1a"),
        ),
        "DocH2": ParagraphStyle(
            "DocH2", parent=base["Heading2"], fontSize=14, leading=18,
            spaceBefore=10, spaceAfter=8, textColor=colors.HexColor("#1a1a1a"),
        ),
        "DocH3": ParagraphStyle(
            "DocH3", parent=base["Heading3"], fontSize=12, leading=16,
            spaceBefore=8, spaceAfter=6, textColor=colors.HexColor("#333333"),
        ),
        "DocTableCell": ParagraphStyle("DocTableCell", parent=base["BodyText"], fontSize=9, leading=12),
        "DocTableHeader": ParagraphStyle(
            "DocTableHeader", parent=base["BodyText"], fontSize=9, leading=12, textColor=colors.white,
        ),
    }


def _build_table(table_lines: list[str], styles: dict) -> Table | None:
    """Turns a run of consecutive '| a | b |' lines into a Table. Degrades
    gracefully against a real malformed-input case: an inconsistent column
    count (e.g. an "unclosed" row missing a trailing cell) would make
    reportlab's own Table raise ValueError ("elements are not all the same
    length") -- normalized away here by padding every row to the widest
    row's column count, rather than either crashing or silently dropping
    the ragged row."""
    rows = []
    for raw in table_lines:
        if _TABLE_DELIM_RE.match(raw):
            continue  # "|---|---|" header-separator row -- not data
        inner = raw[1:-1] if raw.startswith("|") and raw.endswith("|") else raw
        rows.append([cell.strip() for cell in inner.split("|")])
    if not rows:
        return None
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]

    data = []
    for row_index, row in enumerate(normalized):
        style = styles["DocTableHeader"] if row_index == 0 else styles["DocTableCell"]
        data.append([Paragraph(_inline_markdown_to_xml(cell), style) for cell in row])

    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    return table


def _markdown_to_flowables(markdown_text: str, styles: dict) -> list:
    """Deliberately minimal, not a CommonMark parser -- every line is
    classified by one of four cheap regexes, and anything that matches
    none of them just becomes plain paragraph text. That total fallback is
    what makes this fail-soft by construction: there is no line shape this
    function can't do something reasonable with."""
    flowables: list = []
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    paragraph_buffer: list[str] = []

    def flush_paragraph():
        if paragraph_buffer:
            text = " ".join(paragraph_buffer).strip()
            if text:
                flowables.append(Paragraph(_inline_markdown_to_xml(text), styles["DocBody"]))
            paragraph_buffer.clear()

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            style_name = {1: "DocH1", 2: "DocH2"}.get(level, "DocH3")
            flowables.append(Paragraph(_inline_markdown_to_xml(heading.group(2).strip()), styles[style_name]))
            i += 1
            continue

        if _BULLET_RE.match(stripped):
            flush_paragraph()
            items = []
            while i < len(lines) and _BULLET_RE.match(lines[i].strip()):
                item_text = _BULLET_RE.match(lines[i].strip()).group(1).strip()
                items.append(ListItem(Paragraph(_inline_markdown_to_xml(item_text), styles["DocBody"])))
                i += 1
            flowables.append(ListFlowable(items, bulletType="bullet", leftIndent=18))
            continue

        if _TABLE_ROW_RE.match(stripped):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1
            table = _build_table(table_lines, styles)
            if table is not None:
                flowables.append(table)
            continue

        paragraph_buffer.append(stripped)
        i += 1

    flush_paragraph()
    return flowables


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "document"


def _draw_header_footer(canvas, doc):
    """Runs on every page (SimpleDocTemplate's onFirstPage/onLaterPages --
    the idiomatic reportlab mechanism for a fixed decoration repeated
    across a flowing document, vs. BaseDocTemplate/PageTemplate, which is
    the right tool only when different pages need genuinely different
    layouts, not the case here). The document TITLE itself is a Paragraph
    flowable at the top of the story instead of canvas-drawn text -- that
    lets reportlab handle wrapping/pagination for a long title for free,
    rather than hand-computing text width on the canvas. The logo is a
    small running corner mark on every page (real letterhead behavior);
    the footer carries the page number and generation timestamp regardless
    of content. No "Page X of Y" -- the total page count needs a two-pass
    build (a buffering canvas subclass), a deliberate scope cut for v1,
    not an oversight.
    """
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    canvas.drawString(0.75 * inch, 0.5 * inch, f"Generated by Frank — P Corp OS — {timestamp}")
    canvas.drawRightString(doc.pagesize[0] - 0.75 * inch, 0.5 * inch, f"Page {canvas.getPageNumber()}")
    if LOGO_PATH.exists():
        try:
            canvas.drawImage(
                str(LOGO_PATH),
                doc.pagesize[0] - 1.15 * inch, doc.pagesize[1] - 0.85 * inch,
                width=0.4 * inch, height=0.4 * inch,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass  # decorative only -- never let a bad image file sink the whole document
    canvas.restoreState()


def generate_pdf_document(title: str, content: str, document_type: str = "document") -> str:
    """Renders `content` (constrained markdown) into a PDF under `title`
    and returns the absolute path it was saved to. `document_type` is a
    filename/metadata label only -- no branching on it."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    styles = _build_styles()
    story = [Paragraph(_inline_markdown_to_xml(title), styles["DocH1"]), Spacer(1, 12)]
    story.extend(_markdown_to_flowables(content, styles))

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    type_slug = _slugify(document_type)
    title_slug = _slugify(title)
    # Real bug found live (2026-09-09): a natural title restates the
    # document type ("Invoice INV-001 - Herbish" for document_type=
    # "invoice"), so prepending type_slug unconditionally produced doubled
    # prefixes like "invoice-invoice-inv-001-herbish...". Skip the prefix
    # when the title's own slug already starts with it -- applies equally
    # to "quote"/"proposal"/etc., not just this one case.
    if title_slug == type_slug or title_slug.startswith(f"{type_slug}-"):
        filename = f"{title_slug}-{timestamp}.pdf"
    else:
        filename = f"{type_slug}-{title_slug}-{timestamp}.pdf"
    output_path = DOCS_DIR / filename

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        topMargin=1.0 * inch,
        bottomMargin=0.85 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=title,
    )
    doc.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)
    return str(output_path)


GENERATE_PDF_DOCUMENT_TOOL = {
    "name": "generate_pdf_document",
    "description": (
        "Generate a professionally formatted PDF and save it to disk, returning its file path. "
        "Use for any document Josh asks for that should exist as a real file -- a proposal, quote, "
        "report, SOP, brief, contract draft, financial summary, executive summary / \"how's the business "
        "doing\" report, etc. This is one generic renderer, not a template picker: decide what the document "
        "should say yourself (pull real data first from whatever tool holds it -- Joshx, Finance, Trading "
        "Division, Alpha Mode, People, check_connected_apps_status, etc. -- rather than inventing numbers), "
        "then author the body as markdown. For an executive summary specifically, check_connected_apps_status "
        "has no other path into your context -- call it, don't skip it. Never compute or state a combined "
        "total (total business-wide revenue, a blended portfolio value across accounts/currencies) that no "
        "existing tool already gives you -- Joshx and Finance both deliberately report only real per-project "
        "and per-holding figures for exactly this reason; report the real breakdown, not a number you added "
        "up yourself. Supported markdown: '# Heading' / '## Subheading', plain paragraphs, '- bullet' lists, "
        "**bold** / *italic*, and simple pipe tables ('| Col A | Col B |' rows; an optional '|---|---|' "
        "separator row is fine but not required). No images, code blocks, or nested lists -- keep formatting simple."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Document title, shown at the top of the PDF and used in its filename.",
            },
            "content": {
                "type": "string",
                "description": "The full document body, written in the constrained markdown subset described above.",
            },
            "document_type": {
                "type": "string",
                "description": (
                    "Short free-text label for what kind of document this is, e.g. \"proposal\", "
                    "\"quote\", \"financial-report\". Used only for the filename, never for branching logic."
                ),
            },
        },
        "required": ["title", "content"],
    },
}

DOCUMENTS_TOOLS = [GENERATE_PDF_DOCUMENT_TOOL]
DOCUMENTS_TOOL_NAMES = {tool["name"] for tool in DOCUMENTS_TOOLS}


async def execute_documents_tool_call(name: str, tool_input: dict) -> str:
    if name == "generate_pdf_document":
        try:
            path = generate_pdf_document(
                tool_input["title"],
                tool_input["content"],
                tool_input.get("document_type", "document"),
            )
        except Exception as exc:
            # Real failure (disk full, permissions, a genuine reportlab
            # error) -- surfaced honestly so Frank can tell Josh the truth,
            # not swallowed into a fake success. Malformed *content* never
            # reaches here -- _markdown_to_flowables has no failure case.
            return f"Could not generate the PDF: {exc}"
        return f"PDF saved to {path}"
    return f"Unknown tool: {name}"
