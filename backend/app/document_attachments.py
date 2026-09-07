"""
Inbound chat attachments (2026-09-05) -- deliberately a separate file from
documents.py, which is the OUTBOUND side (Frank generating a PDF). Same
domain name, opposite direction; conflating them would make both files
harder to read for no real benefit.

Tiered handling, not one-size-fits-all extraction: a PDF is passed straight
through as a native Claude "document" content block -- Claude reads the
real PDF (text, layout, embedded images) natively, so there is zero local
parsing for the single highest-value case. DOCX/XLSX have no Claude-native
equivalent and get extracted to plain text locally (python-docx/openpyxl,
both confirmed pure-Python-or-prebuilt-wheel, no native toolchain needed --
same check already applied to reportlab/Pillow). CSV needs no dependency at
all -- stdlib csv, formatted the same way as everything else here.

Docx tables and CSV/XLSX sheets are all rendered as the same `| a | b |`
markdown pipe-table syntax SimpleMarkdownView.swift was just taught to
render tonight -- one mental model for "a table" across the codebase, even
though this specific use is about what's sent TO Claude, not what's shown
on screen.

`build_content_block` never raises. A corrupted or password-protected
DOCX/XLSX, an unsupported type, or an oversized file all degrade to an
honest text block Frank can relay -- the same "fail soft on content, fail
loud only on the file itself" split documents.py already established for
outbound generation.
"""

import base64
import csv
import io
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

# Uploaded chat attachments land here -- relocated from main.py (2026-09-06)
# so data_analysis.py can read a stored attachment's bytes back off disk
# without importing from main.py (a leaf module nothing else imports from).
# Filenames only in messages.attachments, not the bytes themselves -- see
# main.py's own comment on that column for why.
ATTACHMENTS_DIR = Path(__file__).parent.parent / "data" / "attachments"

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 6
MAX_TOTAL_ATTACHMENT_BYTES = 40 * 1024 * 1024

# Real bug found live (2026-09-05): with no mention of this anywhere in
# Frank's system prompt, he had no way to know attachments land directly
# in his own turn's context -- the only attachment-related text he ever
# saw was consult_design_agent's tool description ("the actual attachment
# is automatically forwarded to this agent"), which reads, from his side,
# like attachments *only* ever reach him through that one tool. Confirmed
# live: asked to read a real PDF, he answered correctly the first time
# (the content genuinely was in his context), then on the very next turn
# insisted his own correct answer must have been "fabricated," since he
# reasoned he has no direct attachment-reading capability at all. This
# static note, appended to every turn's system prompt in main.py, closes
# that gap -- not a per-turn data block (nothing here varies), so a plain
# string constant rather than an async build_*_block() function.
ATTACHMENT_CAPABILITY_NOTE = """

When Josh attaches a file, you see it directly in this same turn -- no tool call needed to read it. An image or PDF appears as real visual/document content; a DOCX/XLSX/CSV arrives as its extracted text (tables rendered as markdown). consult_design_agent additionally forwards the same attachment to the Design Agent for dedicated critique work -- that's an addition, not the only way you ever see one. If an attachment is in your context, it's real: describe, quote, or act on it directly. Never claim you can't read something that's actually right there.

For real statistics on an attached CSV/XLSX -- averages, correlation between columns, outliers -- use the analyze_data tool instead of computing them yourself off the extracted text table. Your own arithmetic over many rows of text is unreliable; analyze_data runs actual computation and hands back real numbers."""

# Caps how much extracted text a single XLSX/CSV can contribute -- a
# 100k-row spreadsheet must not silently blow the context window.
MAX_TABLE_ROWS = 500
MAX_TABLE_CHARS = 40_000


def classify_attachment(media_type: str, filename: str) -> str:
    """Derived here, server-side, only -- the wire payload never sends a
    kind field, so this is the one place the mapping can drift."""
    if media_type.startswith("image/"):
        return "image"
    if media_type == "application/pdf":
        return "pdf"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "docx":
        return "docx"
    if extension == "xlsx":
        return "xlsx"
    if extension == "csv":
        return "csv"
    return "unsupported"


def rows_to_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return "(empty)"
    truncated = len(rows) > MAX_TABLE_ROWS
    shown = rows[:MAX_TABLE_ROWS]
    header = shown[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in shown[1:]:
        lines.append("| " + " | ".join(row) + " |")
    text = "\n".join(lines)
    if len(text) > MAX_TABLE_CHARS:
        text = text[:MAX_TABLE_CHARS] + "\n... (truncated, too long)"
    elif truncated:
        text += f"\n... ({len(rows) - MAX_TABLE_ROWS} more rows not shown)"
    return text


def _extract_docx(raw_bytes: bytes) -> str:
    doc = Document(io.BytesIO(raw_bytes))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        parts.append(rows_to_markdown_table(rows))
    return "\n\n".join(parts) if parts else "(no readable text found)"


def _extract_xlsx(raw_bytes: bytes) -> str:
    # data_only=True returns each formula cell's last-calculated value,
    # not the formula text -- what Frank actually wants to reason about.
    workbook = load_workbook(io.BytesIO(raw_bytes), data_only=True, read_only=True)
    sheets = []
    for sheet in workbook.worksheets:
        rows = [
            [("" if cell is None else str(cell)) for cell in row]
            for row in sheet.iter_rows(values_only=True)
        ]
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            continue
        sheets.append(f"### {sheet.title}\n\n" + rows_to_markdown_table(rows))
    return "\n\n".join(sheets) if sheets else "(no readable data found)"


def _extract_csv(raw_bytes: bytes) -> str:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1")
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]
    rows = [row for row in rows if any(cell for cell in row)]
    return rows_to_markdown_table(rows)


def build_content_block(media_type: str, filename: str, raw_bytes: bytes) -> dict:
    kind = classify_attachment(media_type, filename)
    if kind == "image":
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": _b64(raw_bytes)},
        }
    if kind == "pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": _b64(raw_bytes)},
        }
    if kind in ("docx", "xlsx", "csv"):
        try:
            extractor = {"docx": _extract_docx, "xlsx": _extract_xlsx, "csv": _extract_csv}[kind]
            extracted = extractor(raw_bytes)
            return {"type": "text", "text": f"[Attached file '{filename}']\n\n{extracted}"}
        except Exception as error:
            return {
                "type": "text",
                "text": f"[Could not read attached file '{filename}': {error}. It may be corrupted or password-protected.]",
            }
    return {
        "type": "text",
        "text": f"[Attached file '{filename}' has an unsupported type ({media_type}) and was not included.]",
    }


def _b64(raw_bytes: bytes) -> str:
    return base64.b64encode(raw_bytes).decode("ascii")
