"""PDF report generation.

The LLM composes the content; this renders it deterministically. That split matters: an
officer attaches this to a case file, so the numbers in it must be the numbers the tools
returned, laid out by code, not a model's idea of a table.

RENDER ENGINE: reportlab platypus, directly -- NOT xhtml2pdf and NOT WeasyPrint.

  * WeasyPrint needs GTK/Pango system libs, absent on the native-Windows dev box this demo
    is driven from (`cannot load library 'libgobject-2.0-0'`), so it never rendered here.
  * xhtml2pdf's HTML->reportlab table converter crashes in reportlab's own table geometry
    (`_listCellGeom`, tables.py) on non-trivial tables, and it silently drops embedded chart
    images. Both are exactly what a case dossier needs.

Building the story with platypus flowables (Paragraph / Table / Image) skips the fragile
HTML layer entirely: it is pure Python (identical on Windows and in Docker), lays out
word-wrapped tables reliably, and embeds the run's generated chart PNGs as real images.

FONTS: reportlab does NO per-glyph fallback and embeds one face per run. With the built-in
Helvetica, Kannada/Hindi is silently DROPPED -- the render succeeds, reports zero errors,
and the page is blank, the worst failure for a stated requirement. Google's per-script Noto
faces also carry digits but ZERO Latin letters, so "BNS 318 / IT Act 66D" renders as
" 318 /  66 ". Hence ONE face merged offline (fontTools) from NotoSans + NotoSansKannada +
NotoSansDevanagari, bundled beside this file, registered once as a family so <b>/<i> markup
in Paragraphs resolves instead of raising. Verified by reading text back out of the PDF
(test_assistant_report.py), never from documentation.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).parent / "fonts"
FONT_NAME = "NotoSansKSP"
FONT_FILE = "NotoSansKSP-Regular.ttf"
MONO_FONT = "Courier"  # built-in, Latin/ASCII only -- code blocks and SQL are ASCII

# --- theme: reuse the frontend's dark crime-intel palette (index.css tokens) -------------
# The product is dark-themed and screen-first (demo/judges), so the dossier matches it: a
# deep-navy page, light ink, blue accent, and the same green/amber/red status hues.
PAGE_BG = colors.HexColor("#0e1114")     # --bg-1
PANEL_BG = colors.HexColor("#14171b")    # --surface
PANEL_ALT = colors.HexColor("#1a1e23")   # --surface-raised
INK = colors.HexColor("#f5f7fa")         # --text
DIM = colors.HexColor("#b6c0cc")         # --text-dim
MUTE = colors.HexColor("#84909f")        # --text-mute
ACCENT = colors.HexColor("#60a5fa")      # --accent-strong
RULE = colors.HexColor("#2b3038")        # border-strong-ish
OK = colors.HexColor("#5ea479")
WARN = colors.HexColor("#c99457")
DANGER = colors.HexColor("#c15a54")

_MARGINS = {"left": 1.5 * cm, "right": 1.5 * cm, "top": 1.7 * cm, "bottom": 1.8 * cm}
CONTENT_WIDTH = A4[0] - _MARGINS["left"] - _MARGINS["right"]

_STATUS_FILL = {"GREEN": OK, "AMBER": WARN, "RED": DANGER}

# A4 portrait can't render more columns legibly; extras are dropped with a caption note.
_MAX_TABLE_COLS = 12
# Bound each cell's height: one long cell (e.g. a brief-facts narrative in a raw SQL dump)
# in a narrow column otherwise wraps into a row taller than the page, and reportlab -- which
# cannot split a single row across pages -- aborts the ENTIRE PDF with a LayoutError.
_MAX_CELL_LINES = 12

_registered: set[str] = set()
_fonts_initialised = False


def _register_all_fonts() -> None:
    """Register the bundled face once, eagerly, as a family so <b>/<i> markup resolves.

    Kept eager and idempotent: reportlab caches font state, and registering a family maps
    normal/bold/italic to the same real face so a Paragraph carrying <b> (statute names,
    amounts) renders instead of raising KeyError on a missing bold variant.
    """
    global _fonts_initialised
    if _fonts_initialised:
        return
    _fonts_initialised = True

    path = FONT_DIR / FONT_FILE
    if not path.exists():
        logger.warning(
            "report: bundled font %s missing; falling back to Helvetica. "
            "Kannada and Hindi text WILL be silently dropped from PDFs.", path,
        )
        return
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont(FONT_NAME, str(path)))
        # One real face for every weight/slant: no bold/italic TTF is bundled, so map them
        # all to the regular face. <b>/<i> then resolve (same glyphs) rather than erroring.
        pdfmetrics.registerFontFamily(
            FONT_NAME, normal=FONT_NAME, bold=FONT_NAME, italic=FONT_NAME, boldItalic=FONT_NAME,
        )
        _registered.add(FONT_NAME)
    except Exception:
        logger.exception("report: could not register font %s", path)


def _resolve_font() -> str:
    """The registered Indic-capable face, or Helvetica (Latin only) if it's missing."""
    _register_all_fonts()
    return FONT_NAME if FONT_NAME in _registered else "Helvetica"


# --- styles ------------------------------------------------------------------------------


def _styles() -> dict[str, ParagraphStyle]:
    font = _resolve_font()
    return {
        "eyebrow": ParagraphStyle("eyebrow", fontName=font, fontSize=7.5, leading=10,
                                  textColor=MUTE, spaceAfter=2),
        "h1": ParagraphStyle("h1", fontName=font, fontSize=19, leading=23, textColor=INK,
                              spaceBefore=2, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=font, fontSize=12.5, leading=16, textColor=ACCENT,
                             spaceBefore=14, spaceAfter=5),
        "h3": ParagraphStyle("h3", fontName=font, fontSize=10.5, leading=14, textColor=INK,
                             spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("body", fontName=font, fontSize=9.5, leading=14, textColor=INK,
                               spaceAfter=6),
        "meta": ParagraphStyle("meta", fontName=font, fontSize=8.5, leading=12, textColor=DIM,
                               spaceAfter=2),
        "caption": ParagraphStyle("caption", fontName=font, fontSize=7.5, leading=10,
                                  textColor=MUTE, spaceBefore=-2, spaceAfter=12, italic=1),
        "th": ParagraphStyle("th", fontName=font, fontSize=8.5, leading=11, textColor=INK),
        "td": ParagraphStyle("td", fontName=font, fontSize=8.5, leading=11, textColor=DIM),
        # Wide tables (many columns): smaller font + break-anywhere wrap so long identifiers
        # (account numbers, UPIs, hashes) don't overflow the narrow columns.
        "th_sm": ParagraphStyle("th_sm", fontName=font, fontSize=7, leading=9, textColor=INK,
                                wordWrap="CJK"),
        "td_sm": ParagraphStyle("td_sm", fontName=font, fontSize=7, leading=9, textColor=DIM,
                                wordWrap="CJK"),
        "disclaimer": ParagraphStyle("disclaimer", fontName=font, fontSize=8, leading=11.5,
                                     textColor=DIM),
    }


def _escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    """Escape, then apply the inline markdown reportlab's Paragraph mini-language supports."""
    s = _escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+)`", rf'<font face="{MONO_FONT}">\1</font>', s)
    return s


# --- markdown -> flowables ---------------------------------------------------------------


def _is_separator_row(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells)


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _truncate_cell(value: Any, usable_w: float, font_size: float) -> str:
    """Cap a cell's text so it can't wrap into a row taller than the page frame.

    reportlab cannot split one table row across pages, so a single oversized cell aborts
    the whole PDF. Bounding chars ~= (chars that fit one line) * _MAX_CELL_LINES keeps every
    row well within a page regardless of how wide the source data is.
    """
    s = "" if value is None else str(value)
    chars_per_line = max(4, int(usable_w / (font_size * 0.5)))
    max_chars = chars_per_line * _MAX_CELL_LINES
    return s if len(s) <= max_chars else s[: max_chars - 1].rstrip() + "\u2026"


def _grid_table(header: list[str], rows: list[list[str]], S: dict[str, ParagraphStyle],
                caption: str = "") -> list:
    if not header:
        return []
    note = ""
    ncols = len(header)
    if ncols > _MAX_TABLE_COLS:
        note = f" Showing first {_MAX_TABLE_COLS} of {ncols} columns."
        header = header[:_MAX_TABLE_COLS]
        rows = [list(row)[:_MAX_TABLE_COLS] for row in rows]
        ncols = _MAX_TABLE_COLS
    col_w = CONTENT_WIDTH / ncols
    usable_w = max(8.0, col_w - 12)  # column width minus LEFT+RIGHT cell padding
    th, td = (S["th_sm"], S["td_sm"]) if ncols >= 7 else (S["th"], S["td"])

    def _cell(value: Any, style: ParagraphStyle) -> Paragraph:
        return Paragraph(_inline(_truncate_cell(value, usable_w, style.fontSize)), style)

    data = [[_cell(c, th) for c in header]]
    for row in rows:
        cells = list(row) + [""] * (ncols - len(row))
        data.append([_cell(c, td) for c in cells[:ncols]])

    # splitByRow so a long multi-row table flows onto the next page instead of overflowing.
    table = Table(data, colWidths=[col_w] * ncols, repeatRows=1, splitByRow=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL_ALT),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("FONTNAME", (0, 0), (-1, 0), _resolve_font()),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PANEL_BG, PAGE_BG]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # Colour the leading STATUS cell of a legal checklist (GREEN/AMBER/RED) for scannability.
    for r, row in enumerate(rows, start=1):
        token = str(row[0]).strip().upper() if row else ""
        if token in _STATUS_FILL:
            style.append(("TEXTCOLOR", (0, r), (0, r), _STATUS_FILL[token]))
    table.setStyle(TableStyle(style))
    out: list = [table]
    caption = (caption + note).strip()
    if caption:
        out.append(Paragraph(_escape(caption), S["caption"]))
    return out


def _bullets(items: list[str], S: dict[str, ParagraphStyle], ordered: bool = False) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(_inline(it), S["body"]), leftIndent=12) for it in items],
        bulletType="1" if ordered else "bullet",
        bulletColor=ACCENT, start="1" if ordered else None,
        leftIndent=14, bulletFontName=_resolve_font(), bulletFontSize=8,
    )


def _code_block(code: str, S: dict[str, ParagraphStyle]) -> Table:
    para = Preformatted(code, ParagraphStyle("code", fontName=MONO_FONT, fontSize=7.5,
                                             leading=10, textColor=DIM))
    box = Table([[para]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 2, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return box


def _markdown_flowables(md: str, S: dict[str, ParagraphStyle]) -> list:
    """A small, dependency-free markdown subset -> flowables (headings, GFM tables, bullets,
    ordered lists, fenced code, paragraphs with inline bold/italic/code)."""
    flow: list = []
    lines = (md or "").replace("\r\n", "\n").split("\n")
    para: list[str] = []

    def flush() -> None:
        if para:
            text = " ".join(p.strip() for p in para).strip()
            if text:
                flow.append(Paragraph(_inline(text), S["body"]))
            para.clear()

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush()
            i += 1
            code: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            flow.append(_code_block("\n".join(code), S))
            continue

        if "|" in stripped and i + 1 < n and _is_separator_row(lines[i + 1]):
            flush()
            header = _split_row(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            flow.extend(_grid_table(header, rows, S))
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush()
            flow.append(Paragraph(_inline(heading.group(2)),
                                  S["h2"] if len(heading.group(1)) <= 2 else S["h3"]))
            i += 1
            continue

        if re.match(r"^[-*]\s+\S", stripped):
            flush()
            items: list[str] = []
            while i < n and re.match(r"^[-*]\s+\S", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            flow.append(_bullets(items, S))
            continue

        if re.match(r"^\d+\.\s+\S", stripped):
            flush()
            items = []
            while i < n and re.match(r"^\d+\.\s+\S", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            flow.append(_bullets(items, S, ordered=True))
            continue

        if not stripped:
            flush()
            i += 1
            continue

        para.append(line)
        i += 1

    flush()
    return flow


# --- artifacts (tables, graphs, chart PNGs) ----------------------------------------------


def _table_artifact(artifact: dict[str, Any], S: dict[str, ParagraphStyle]) -> list:
    out: list = [Paragraph(_escape(artifact.get("title") or "Table"), S["h2"])]
    out.extend(_grid_table(
        [str(c) for c in (artifact.get("columns") or [])],
        [[("" if c is None else str(c)) for c in row] for row in (artifact.get("rows") or [])[:200]],
        S, caption=artifact.get("caption") or "",
    ))
    return out


def _graph_artifact(artifact: dict[str, Any], S: dict[str, ParagraphStyle]) -> list:
    """A force graph can't be laid out statically at A4; its edges ARE the evidence (who
    paid whom, how much, when), so render them as an edge-list table."""
    nodes = {n["id"]: n for n in artifact.get("nodes") or []}
    header = ["From", "Link", "To", "Detail"]
    rows: list[list[str]] = []
    for link in (artifact.get("links") or [])[:200]:
        src = nodes.get(link.get("source"), {}).get("label", link.get("source"))
        dst = nodes.get(link.get("target"), {}).get("label", link.get("target"))
        props = link.get("properties") or {}
        detail = ", ".join(f"{k}: {v}" for k, v in props.items() if k != "amount")
        rows.append([str(src), str(link.get("relationship") or ""), str(dst), detail])
    legend = ", ".join(sorted({str(n.get("type")) for n in nodes.values()}))
    caption = f"{artifact.get('caption') or ''} Entities: {legend}.".strip()
    out: list = [Paragraph(_escape(artifact.get("title") or "Graph"), S["h2"])]
    out.extend(_grid_table(header, rows, S, caption=caption))
    return out


def _image_flowable(png: bytes, title: str, S: dict[str, ParagraphStyle]) -> list:
    """Embed a generated chart PNG, scaled to fit the content width and one frame's height."""
    try:
        from reportlab.lib.utils import ImageReader

        reader = ImageReader(io.BytesIO(png))
        iw, ih = reader.getSize()
        if not iw or not ih:
            return []
        max_h = A4[1] - _MARGINS["top"] - _MARGINS["bottom"] - 60
        scale = min(CONTENT_WIDTH / iw, max_h / ih)
        image = Image(io.BytesIO(png), width=iw * scale, height=ih * scale)
        image.hAlign = "LEFT"
    except Exception:
        logger.debug("report: could not embed image %s", title, exc_info=True)
        return []
    return [Paragraph(_escape(title), S["h2"]), image, Spacer(1, 6)]


def _artifact_flowables(artifacts: list[dict[str, Any]], images: dict[str, bytes],
                        S: dict[str, ParagraphStyle]) -> list:
    flow: list = []
    for artifact in artifacts or []:
        kind = artifact.get("kind")
        if kind == "table":
            flow.extend(_table_artifact(artifact, S))
        elif kind == "graph":
            flow.extend(_graph_artifact(artifact, S))
        elif kind == "document":
            fmt = (artifact.get("format") or "").lower()
            blob = images.get(artifact.get("id"))
            if fmt == "png" and blob:
                flow.extend(_image_flowable(blob, artifact.get("title") or "Chart", S))
            elif fmt in ("text", "html") and artifact.get("text"):
                flow.append(Paragraph(_escape(artifact.get("title") or "Document"), S["h2"]))
                flow.extend(_markdown_flowables(artifact["text"], S))
            # pdf/svg/other document artifacts are not embedded.
    return flow


# --- page decoration (dark background + footer on every page) ----------------------------


def _page_decorator(title: str):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(PAGE_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setFillColor(MUTE)
        canvas.setFont(_resolve_font(), 7)
        canvas.drawString(_MARGINS["left"], 1.0 * cm,
                          f"{title[:70]} \u00b7 Karnataka State Police")
        canvas.drawRightString(A4[0] - _MARGINS["right"], 1.0 * cm,
                               f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return draw


_DISCLAIMER = (
    "<b>Decision support, not automated accusation.</b> Every finding here is drawn from records "
    "in the case databases and is for the investigating officer to verify. Case data in this "
    "platform is synthetic. Statutes and cited judgments are real and attributed; verify section "
    "mappings against current law with counsel before filing."
)


def build_report_pdf(
    title: str,
    sections: list[dict[str, str]],
    artifacts: list[dict[str, Any]] | None = None,
    images: dict[str, bytes] | None = None,
    meta: str = "",
    officer: str = "",
    language: str = "en",
) -> bytes:
    """Render the report to PDF bytes with reportlab platypus.

    `images` maps a png document-artifact id to its raw bytes (fetched by the caller), so
    this function stays pure -- no DB, no Stratus -- and is unit-testable in isolation.
    """
    S = _styles()
    story: list = [
        Paragraph("KARNATAKA STATE POLICE \u00b7 CRIME INTELLIGENCE PLATFORM", S["eyebrow"]),
        HRFlowable(width="100%", thickness=2, color=ACCENT, spaceBefore=2, spaceAfter=8),
        Paragraph(_escape(title), S["h1"]),
    ]
    if meta:
        story.append(Paragraph(_escape(meta), S["meta"]))
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    story.append(Paragraph(f"Generated {generated} by {_escape(officer or 'Crime Intelligence Platform')}",
                           S["meta"]))
    story.append(Spacer(1, 8))

    for section in sections or []:
        heading = section.get("heading")
        if heading:
            story.append(Paragraph(_escape(heading), S["h2"]))
        story.extend(_markdown_flowables(section.get("body_markdown") or section.get("body") or "", S))

    story.extend(_artifact_flowables(artifacts or [], images or {}, S))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=6))
    disclaimer = Table([[Paragraph(_DISCLAIMER, S["disclaimer"])]], colWidths=[CONTENT_WIDTH])
    disclaimer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(disclaimer)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=title,
        leftMargin=_MARGINS["left"], rightMargin=_MARGINS["right"],
        topMargin=_MARGINS["top"], bottomMargin=_MARGINS["bottom"],
    )
    decorate = _page_decorator(title)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


# --- the tool ----------------------------------------------------------------


def build_report_tool(session_id: str, run_id: str, language: str, officer: str,
                      case_ref: str = ""):
    """A supervisor-only tool that turns this run's findings into a downloadable PDF.

    session/run/language are bound at construction rather than passed as arguments: the
    model should be deciding what the report *says*, not which session it belongs to or
    which language it is in (the officer already chose that).
    """
    import uuid as _uuid

    from langchain_core.tools import StructuredTool

    from .. import bus
    from ..events import DocumentArtifact
    from ..tools import CURRENT_EMITTER, _in_thread

    def _collect_images(artifacts: list[dict]) -> dict[str, bytes]:
        """Load the raw bytes of any generated chart PNG so it can be embedded in the PDF."""
        from .. import persistence

        images: dict[str, bytes] = {}
        for artifact in artifacts:
            if artifact.get("kind") != "document" or (artifact.get("format") or "").lower() != "png":
                continue
            row = persistence.load_artifact(artifact.get("id")) or {}
            blob = row.get("blob")
            if blob:
                images[artifact["id"]] = bytes(blob)
        return images

    def _build(handle, title: str, sections: list[dict], artifacts: list[dict]) -> str:
        # P4: emit progress so the socket stays busy through render + upload and the officer
        # sees movement instead of a silent gap that trips the WS idle timeout.
        if handle:
            handle.progress("Laying out the report and embedding charts\u2026")
        images = _collect_images(artifacts)
        pdf = build_report_pdf(
            title=title, sections=sections, artifacts=artifacts, images=images,
            meta=case_ref, officer=officer, language=language,
        )
        if handle:
            handle.progress(f"Rendered {len(pdf) // 1024} KB PDF; saving\u2026")
        artifact_id = f"doc-{_uuid.uuid4().hex[:8]}"

        key = f"assistant/{session_id}/{run_id}/artifacts/{artifact_id}.pdf"
        stored = False
        try:
            from ...services.catalyst_queue import upload_file_to_stratus

            upload_file_to_stratus(key, pdf)
            stored = True
        except Exception:
            # A Stratus outage must not lose the report: the artifact endpoint falls back
            # to the Postgres row, so the officer's download still works.
            logger.exception("report: Stratus upload failed for %s", key)

        from .. import persistence

        document = DocumentArtifact(
            id=artifact_id, title=title, format="pdf",
            url=f"/api/v1/assistant/artifacts/{artifact_id}",
            caption=f"{len(sections)} section(s), {len(artifacts)} attached finding(s).",
        )
        persistence.save_artifact(document, session_id, run_id, stratus_key=key if stored else None)
        persistence.save_pdf_bytes(artifact_id, pdf)

        if handle:
            handle.emit_artifact(document)
            handle.output = f"{len(pdf) // 1024} KB PDF"
            # Show WHAT went into the PDF in the reasoning trail (rendered as markdown):
            # the composed section headings + how many findings were attached, so the
            # officer can see the report captured the chat, not a silent "done".
            heads = "\n".join(f"- {(s.get('heading') or 'Section')}" for s in sections)
            handle.detail = (
                f"**Report contents** ({len(sections)} section(s), "
                f"{len(artifacts)} attached finding(s)):\n{heads}"
            )
        return (f"Report '{title}' generated as a downloadable PDF ({len(pdf) // 1024} KB) "
                f"with {len(artifacts)} attached finding(s). It is available to the officer "
                f"as a document artifact - do not repeat its contents in your answer.")

    def _session_artifacts() -> list[dict]:
        """Every finding artifact in this chat, oldest first, deduped by id.

        The current run's bus history only holds THIS turn -- but a 'report of all the
        findings in the chat' turn usually produces none of its own. So merge the whole
        session's persisted artifacts (prior turns' tables/graphs/charts, from Postgres)
        with anything this run just emitted. Prior report PDFs are dropped -- they aren't
        findings and can't be embedded anyway.
        """
        from .. import persistence

        merged: list[dict] = []
        seen: set[str] = set()
        for art in [*persistence.load_session_artifacts(session_id), *bus.artifacts_of(run_id)]:
            aid = art.get("id")
            if aid in seen:
                continue
            if art.get("kind") == "document" and (art.get("format") or "").lower() == "pdf":
                continue
            seen.add(aid)
            merged.append(art)
        return merged

    def _sections_from_run() -> list[dict]:
        """Inner fallback: findings this run already produced (used when the chat has no
        prior assistant answers yet, e.g. a report requested on the very first turn)."""
        sections: list[dict] = []
        seen: set[str] = set()
        for event in bus.history(run_id):
            if event.get("type") != "step":
                continue
            step = event.get("step") or {}
            if step.get("status") != "done":
                continue
            output = (step.get("output") or "").strip()
            step_title = (step.get("title") or "").strip()
            if len(output) < 60 or not step_title or step_title.startswith(("Delegating", "Generating")):
                continue
            key = output[:80]
            if key in seen:
                continue
            seen.add(key)
            sections.append({"heading": step_title, "body_markdown": output})
        return sections[:8]

    def _sections_from_chat() -> list[dict]:
        """Compose sections from the findings already in this chat.

        The model sometimes calls generate_report with only a title (a common GLM slip),
        and the specialist that composes it only sees a bounded slice of history -- so on a
        'put all the findings in the chat into a PDF' request it can miss earlier turns.
        Rebuild from the durable record: each prior assistant answer becomes a section,
        headed by the question that produced it. The attached artifacts carry the numbers.
        """
        from .. import persistence

        sections: list[dict] = []
        pending_q: str | None = None
        for msg in persistence.load_history(session_id, limit=40):
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role == "user":
                pending_q = content
            elif role == "assistant" and len(content) >= 40:
                heading = (pending_q or "Finding").strip()[:90]
                sections.append({"heading": heading, "body_markdown": content})
                pending_q = None
        return sections[-12:] or _sections_from_run() or [
            {"heading": "Summary", "body_markdown": "See the attached findings below."}
        ]

    def _generate_report(title: str, sections: list[dict] | None = None,
                         include_artifacts: bool = True) -> str:
        emitter = CURRENT_EMITTER.get()

        # Artifacts across the WHOLE chat -- the tables/trails/charts every turn produced.
        # Reusing them keeps the report's numbers identical to what the officer saw on
        # screen, instead of asking the model to retype them, and ensures a "report of all
        # the findings" captures earlier turns, not just the current one.
        artifacts = _session_artifacts() if include_artifacts else []

        # sections is optional: if the model omitted it, synthesise from the chat's findings
        # so the tool still runs (and emits a visible step) instead of raising a pydantic
        # "sections field required" error before the body -- which showed the officer an
        # error and no report step at all.
        sections = list(sections or []) or _sections_from_chat()

        if emitter is None:
            return _build(None, title, sections, artifacts)
        # `with` rather than manual __enter__/__exit__: the context manager closes the step
        # as 'error' on a raise. Calling __exit__(None, None, None) after a failure would
        # report a green, finished step for a report that never rendered.
        with emitter.step("supervisor", "tool_call", "Generating PDF report") as handle:
            return _build(handle, title, sections, artifacts)

    return StructuredTool.from_function(
        func=_generate_report,
        coroutine=_in_thread(_generate_report),
        name="generate_report",
        description=(
            "Produce a downloadable PDF report of your findings for the case file. "
            "Call this ONLY when the officer asks for a report, dossier, summary document, "
            "or PDF -- not on every answer. "
            "sections: a list of {heading, body_markdown} objects you compose from the "
            "findings -- ALWAYS pass this (it is the report body). When the officer asks for a "
            "report of ALL the findings in the chat, cover EVERY earlier finding in the "
            "conversation, one section each, not just the latest. If you omit sections the "
            "report falls back to the chat's prior answers, which is lower quality. "
            "include_artifacts=True attaches the tables, money trails and chart PNGs produced "
            "across the WHOLE chat (every turn), so do not retype their numbers."
        ),
    )
