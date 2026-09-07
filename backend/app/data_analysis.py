"""
Real numeric computation over an attached CSV/XLSX (2026-09-06, systems
audit gap: "no pandas, no numpy, anywhere in the backend"). Deliberately
separate from document_attachments.py's CSV/XLSX handling -- that module
formats bytes as human-readable markdown text for Claude to read (every
cell str()'d, no type coercion); this module parses the same bytes into
an actual typed pandas.DataFrame so real statistics/correlation/outlier
detection can be computed server-side instead of guessed at by an LLM
reading a text table.

One generic tool (analyze_data), not three. Forecasting/trend
extrapolation is a deliberate v1 scope cut. Read-only, no approval flow.
Only sheet 0 of an XLSX is read -- multi-sheet analysis is also a
deliberate v1 scope cut, not a silent limitation.
"""

import io

import pandas as pd

from app.db import find_recent_attachment
from app.document_attachments import ATTACHMENTS_DIR, classify_attachment, rows_to_markdown_table

MAX_CORRELATE_COLUMNS = 25
NUMERIC_COERCION_MIN_RATIO = 0.8
# Real bug found live (2026-09-06): a column at, say, 60% numeric (mixed
# with "N/A"/"TBD"/blank) fails NUMERIC_COERCION_MIN_RATIO and is dropped
# from every operation's numeric selection -- but describe/outliers only
# ever disclosed a dropped column when the caller explicitly passed
# `columns`. Left to the unfiltered case, the column just silently
# vanished from the result with no note at all; it only came across
# honestly in live testing because Frank still had the raw extracted
# table in his own context to cross-reference against. This floor exists
# so a column that's clearly *trying* to be numeric (not just a stray
# numeric-looking string in an otherwise-text column) gets named in the
# result unconditionally, regardless of whether `columns` was passed.
PARTIAL_NUMERIC_DISCLOSURE_RATIO = 0.3


class _AnalysisError(Exception):
    """Internal control flow only -- caught in execute_data_analysis_tool_call
    and turned into an honest message Frank can relay, never raised past it."""


async def _resolve_dataframe(conversation_id: int, source: str) -> tuple[pd.DataFrame, str, str | None]:
    attachment = await find_recent_attachment(conversation_id, source)
    if attachment is None:
        raise _AnalysisError(
            f"Couldn't find an attached file matching \"{source}\" in this conversation. "
            "Check the name, or attach it first."
        )
    kind = classify_attachment(attachment["media_type"], attachment["original_name"])
    if kind not in ("csv", "xlsx"):
        raise _AnalysisError(
            f"\"{attachment['original_name']}\" isn't a CSV or spreadsheet (it's {kind}) "
            "-- analyze_data only works on CSV/XLSX attachments."
        )
    path = ATTACHMENTS_DIR / attachment["filename"]
    try:
        raw_bytes = path.read_bytes()
    except FileNotFoundError:
        raise _AnalysisError(f"\"{attachment['original_name']}\" is no longer available on disk.")
    try:
        if kind == "csv":
            try:
                df = pd.read_csv(io.BytesIO(raw_bytes))
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(raw_bytes), encoding="latin-1")
        else:
            df = pd.read_excel(io.BytesIO(raw_bytes), engine="openpyxl", sheet_name=0)
    except Exception as error:
        raise _AnalysisError(
            f"Couldn't read \"{attachment['original_name']}\" as a spreadsheet: {error}. "
            "It may be corrupted or not actually a CSV/XLSX."
        )
    df, dropped = _coerce_numeric_like_columns(df)
    dropped_note = None
    if dropped:
        described = ", ".join(f"\"{col}\" ({ratio:.0%} numeric)" for col, ratio in dropped)
        dropped_note = (
            f"Note: {described} looked partly numeric but had too many non-numeric cells "
            f"(need ≥{NUMERIC_COERCION_MIN_RATIO:.0%}) to include in this analysis -- "
            "clean up the source data if you need it computed on."
        )
    return df, attachment["original_name"], dropped_note


def _coerce_numeric_like_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, float]]]:
    # A column that's mostly numeric with a few stray cells ("N/A", blank,
    # "TBD") comes back from pandas as dtype=object -- naively selecting
    # only already-numeric columns would silently drop it. Keep it if at
    # least 80% of its non-null cells actually parse as numeric. A column
    # between PARTIAL_NUMERIC_DISCLOSURE_RATIO and NUMERIC_COERCION_MIN_RATIO
    # still gets dropped (not coerced -- too unreliable to compute on) but
    # is reported back so the caller can disclose it rather than silently
    # dropping it (see the real bug this closes, above).
    dropped: list[tuple[str, float]] = []
    for col in df.columns:
        if df[col].dtype != object:
            continue
        coerced = pd.to_numeric(df[col], errors="coerce")
        non_null = df[col].notna().sum()
        if non_null == 0:
            continue
        ratio = coerced.notna().sum() / non_null
        if ratio >= NUMERIC_COERCION_MIN_RATIO:
            df[col] = coerced
        elif ratio >= PARTIAL_NUMERIC_DISCLOSURE_RATIO:
            dropped.append((col, ratio))
    return df, dropped


def _select_numeric(df: pd.DataFrame, columns: list[str] | None) -> tuple[pd.DataFrame, list[str]]:
    numeric = df.select_dtypes(include="number")
    notes: list[str] = []
    if columns:
        missing = [c for c in columns if c not in df.columns]
        non_numeric = [c for c in columns if c in df.columns and c not in numeric.columns]
        if missing:
            notes.append(f"Column(s) not found: {', '.join(missing)}.")
        if non_numeric:
            notes.append(f"Column(s) not numeric, skipped: {', '.join(non_numeric)}.")
        keep = [c for c in columns if c in numeric.columns]
        numeric = numeric[keep] if keep else numeric.iloc[:, 0:0]
    return numeric, notes


def describe_dataframe(df: pd.DataFrame, columns: list[str] | None = None) -> str:
    numeric, notes = _select_numeric(df, columns)
    if numeric.shape[1] == 0:
        return "No numeric columns found to describe." + ("" if not notes else " " + " ".join(notes))
    stats = numeric.agg(["count", "mean", "median", "std", "min", "max"]).round(4)
    rows = [[""] + list(stats.index)] + [[col] + [str(v) for v in stats[col]] for col in stats.columns]
    result = rows_to_markdown_table(rows)
    return result if not notes else result + "\n\n" + " ".join(notes)


def correlate_dataframe(df: pd.DataFrame, columns: list[str] | None = None) -> str:
    numeric, notes = _select_numeric(df, columns)
    if numeric.shape[1] < 2:
        return "Need at least 2 numeric columns to correlate." + ("" if not notes else " " + " ".join(notes))
    if numeric.shape[1] > MAX_CORRELATE_COLUMNS:
        numeric = numeric.iloc[:, :MAX_CORRELATE_COLUMNS]
        notes.append(
            f"More than {MAX_CORRELATE_COLUMNS} numeric columns -- showing the first "
            f"{MAX_CORRELATE_COLUMNS}. Pass `columns` to pick specific ones."
        )
    corr = numeric.corr(numeric_only=True).round(3)
    rows = [[""] + list(corr.columns)] + [[col] + [str(v) for v in corr[col]] for col in corr.columns]
    result = rows_to_markdown_table(rows)
    return result if not notes else result + "\n\n" + " ".join(notes)


def find_outliers(df: pd.DataFrame, columns: list[str] | None = None, threshold: float = 3.0) -> str:
    numeric, notes = _select_numeric(df, columns)
    if numeric.shape[1] == 0:
        return "No numeric columns found to check for outliers." + ("" if not notes else " " + " ".join(notes))
    outlier_rows = []
    for col in numeric.columns:
        series = numeric[col].dropna()
        if series.std(ddof=0) == 0 or len(series) < 2:
            continue
        z = (series - series.mean()) / series.std(ddof=0)
        for idx in z[z.abs() > threshold].index:
            outlier_rows.append([str(idx), col, str(df.loc[idx, col]), f"{z[idx]:.2f}"])
    if not outlier_rows:
        base = f"No outliers found past {threshold} standard deviations."
        return base if not notes else base + " " + " ".join(notes)
    rows = [["row", "column", "value", "z-score"]] + outlier_rows
    result = rows_to_markdown_table(rows)
    return result if not notes else result + "\n\n" + " ".join(notes)


ANALYZE_DATA_TOOL = {
    "name": "analyze_data",
    "description": (
        "Runs real, computed numeric analysis on an attached CSV or XLSX file -- actual pandas statistics, "
        "not an estimate read off the extracted text table. Use this whenever Josh asks for real numbers "
        "(averages, correlation between columns, outliers) from a spreadsheet/CSV he's attached, instead of "
        "computing them yourself by reading the table. `source` is the filename as Josh referred to it "
        "(e.g. \"budget.csv\") -- resolves to the most recent matching attachment in this conversation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "The attached CSV/XLSX file's name, as Josh referred to it."},
            "operation": {
                "type": "string",
                "enum": ["describe", "correlate", "outliers"],
                "description": (
                    "\"describe\": count/mean/median/std/min/max per numeric column. "
                    "\"correlate\": pairwise correlation matrix across numeric columns. "
                    "\"outliers\": rows whose value in a numeric column is more than `outlier_threshold` "
                    "standard deviations from that column's mean."
                ),
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional -- restrict analysis to these column names.",
            },
            "outlier_threshold": {
                "type": "number",
                "description": "Only used for operation=\"outliers\". Defaults to 3.",
            },
        },
        "required": ["source", "operation"],
    },
}

DATA_ANALYSIS_TOOLS = [ANALYZE_DATA_TOOL]
DATA_ANALYSIS_TOOL_NAMES = {tool["name"] for tool in DATA_ANALYSIS_TOOLS}


async def execute_data_analysis_tool_call(name: str, tool_input: dict, conversation_id: int) -> str:
    if name != "analyze_data":
        return f"Unknown tool: {name}"
    try:
        df, original_name, dropped_note = await _resolve_dataframe(conversation_id, tool_input["source"])
    except _AnalysisError as error:
        return str(error)
    operation = tool_input.get("operation")
    columns = tool_input.get("columns")
    header = f"Analysis of \"{original_name}\" ({operation}):\n\n"
    if operation == "describe":
        body = describe_dataframe(df, columns)
    elif operation == "correlate":
        body = correlate_dataframe(df, columns)
    elif operation == "outliers":
        threshold = float(tool_input.get("outlier_threshold", 3.0))
        body = find_outliers(df, columns, threshold)
    else:
        return f"Unknown operation: {operation}"
    return header + body + ("" if not dropped_note else "\n\n" + dropped_note)
