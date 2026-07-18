"""PDF report generation.

The LLM composes the content; this renders it deterministically. That split matters: an
officer attaches this to a case file, so the numbers in it must be the numbers the tools
returned, laid out by code, not a model's idea of a table.

xhtml2pdf rather than WeasyPrint, deliberately. WeasyPrint produces nicer output but
needs GTK/Pango system libraries -- trivial in Docker, an MSYS2 install on the Windows dev
box where this demo is actually driven. A report skill that only works in one of the two
places is a report skill that breaks on stage. xhtml2pdf is pure Python and behaves the
same in both.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).parent / "fonts"

# ONE bundled font covering Latin + Kannada + Devanagari. Every part of that sentence is
# load-bearing, and each was established by reading text back out of rendered PDFs rather
# than from documentation:
#
#  1. reportlab does NO per-glyph fallback and embeds one face per run. With the built-in
#     Helvetica, Kannada/Hindi is silently DROPPED: render succeeds, reports zero errors,
#     and the page is blank. The worst possible failure for a stated requirement.
#  2. Only the FIRST Indic face registered in a process ever draws. Registering separate
#     Kannada and Devanagari faces gave working Kannada and blank Hindi -- reproducibly,
#     regardless of order of use. So multiple script faces cannot coexist here at all.
#  3. Google's hinted per-script Noto faces carry digits but ZERO Latin letters, so a raw
#     Kannada face rendered "BNS 318 / IT Act 66D" as " 318 /  66 " -- statute names, the
#     one thing the prompt guarantees stays verbatim, vanishing from the report.
#
# Hence a single face merged offline with fontTools from NotoSans + NotoSansKannada +
# NotoSansDevanagari. fontTools is a build-time tool; nothing imports it at runtime.
# Bundled rather than taken from the host because neither place this runs has an Indic
# font: python:3.11-slim ships none, and the Windows dev box has only a .ttc.
FONT_NAME = "NotoSansKSP"
FONT_FILE = "NotoSansKSP-Regular.ttf"

# Kept as a map so callers can still ask per language; they all resolve to the one face.
_FONT_BY_LANGUAGE = {lang: (FONT_NAME, FONT_FILE) for lang in ("en", "hi", "kn")}

_registered: set[str] = set()
_fonts_initialised = False


def _register_all_fonts() -> None:
    """Register the font once, eagerly, before any rendering.

    Eager registration is a bug fix, not tidiness: xhtml2pdf/reportlab font state is
    effectively frozen after the first pisa render, and a font registered afterwards is
    still EMBEDDED in the PDF but never drawn. An English report followed by a Kannada one
    -- the normal order on a running server -- produced a blank Kannada page, while a
    Kannada report alone was fine. Pinned by test_kannada_survives_after_an_english_render.

    Registration goes through xhtml2pdf's DEFAULT_FONT map, not CSS @font-face:
    @font-face copies the file to a temp path reportlab cannot reopen on Windows, and a
    bare reportlab registerFont is ignored by xhtml2pdf entirely (font absent, text
    mangled). DEFAULT_FONT is what actually resolves a family name to a registered face.
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
        from xhtml2pdf.default import DEFAULT_FONT

        pdfmetrics.registerFont(TTFont(FONT_NAME, str(path)))
        DEFAULT_FONT[FONT_NAME.lower()] = FONT_NAME
        _registered.add(FONT_NAME)
    except Exception:
        logger.exception("report: could not register font %s", path)


def _resolve_font(language: str = "en") -> str | None:
    """CSS font-family name, or None to fall back to Helvetica (Latin only)."""
    _register_all_fonts()
    return FONT_NAME if FONT_NAME in _registered else None

# Deliberately plain: xhtml2pdf supports a subset of CSS2 (no flexbox, no grid), so this
# sticks to what it actually renders rather than what looks good in a browser.
_TEMPLATE = """
<html>
<head><meta charset="utf-8"/><style>
  {font_face}
  @page {{ size: a4 portrait; margin: 1.6cm 1.5cm 2cm 1.5cm;
           @frame footer {{ -pdf-frame-content: footer; bottom: 1cm; height: 1cm; }} }}
  body {{ font-family: {font_family}; font-size: 10pt; color: #1a2233; line-height: 1.45; }}
  .rule {{ background-color: #c8901f; height: 3px; margin: 0 0 14px 0; }}
  .eyebrow {{ font-size: 7.5pt; letter-spacing: 1.5px; color: #6b7280; text-transform: uppercase; }}
  h1 {{ font-size: 19pt; margin: 2px 0 6px 0; color: #16233d; font-family: {font_family}; }}
  h2 {{ font-size: 12pt; margin: 18px 0 6px 0; color: #16233d; font-family: {font_family};
        border-bottom: 1px solid #dde2ea; padding-bottom: 3px; }}
  .meta {{ font-size: 8.5pt; color: #4b5563; margin-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0 12px 0; font-size: 8.5pt; }}
  th {{ background-color: #16233d; color: #ffffff; text-align: left; padding: 5px 6px; }}
  td {{ border-bottom: 1px solid #e5e7eb; padding: 4px 6px; vertical-align: top; }}
  .caption {{ font-size: 7.5pt; color: #6b7280; font-style: italic; margin: -6px 0 12px 0; }}
  .disclaimer {{ background-color: #fdf6e7; border-left: 3px solid #c8901f;
                 padding: 8px 10px; font-size: 8pt; color: #4b5563; margin-top: 18px; }}
  .footer {{ font-size: 7.5pt; color: #9099a8; }}
</style></head>
<body>
  <div class="eyebrow">Karnataka State Police &middot; Crime Intelligence Platform</div>
  <div class="rule"></div>
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
  <div class="meta">Generated {generated} by {officer}</div>
  {sections}
  <div class="disclaimer">
    <b>Decision support, not automated accusation.</b> Every finding here is drawn from records
    in the case databases and is for the investigating officer to verify. Case data in this
    platform is synthetic. Statutes and cited judgments are real and attributed; verify section
    mappings against current law with counsel before filing.
  </div>
  <div id="footer" class="footer">{title} &middot; page <pdf:pagenumber> of <pdf:pagecount></div>
</body>
</html>
"""


def _escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _markdown_to_html(body: str) -> str:
    """Render the model's markdown to HTML.

    The body is escaped BEFORE markdown runs. python-markdown passes raw HTML straight
    through by default, and this text is LLM-authored from officer (or judge) input --
    the same rendered HTML is also served as a document artifact into the frontend's
    iframe, so a stray <script> would be markup rather than text. Escaping first means
    markdown still produces its own tags from markdown syntax (**bold**, tables), while
    any literal HTML in the content shows up as the characters the author typed.
    """
    escaped = _escape(body or "")
    try:
        import markdown as md

        return md.markdown(escaped, extensions=["tables", "fenced_code"])
    except Exception:
        logger.debug("markdown unavailable; falling back to plain paragraphs", exc_info=True)
        return "".join(f"<p>{p}</p>" for p in escaped.split("\n\n") if p.strip())


def _table_html(artifact: dict[str, Any]) -> str:
    columns = artifact.get("columns") or []
    rows = artifact.get("rows") or []
    head = "".join(f"<th>{_escape(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows[:200]
    )
    caption = f'<div class="caption">{_escape(artifact.get("caption"))}</div>' if artifact.get("caption") else ""
    return f"<h2>{_escape(artifact.get('title'))}</h2><table><tr>{head}</tr>{body}</table>{caption}"


def _graph_html(artifact: dict[str, Any]) -> str:
    """Graphs become an edge list.

    A force-directed layout is interactive by nature; rendering one to static PDF needs a
    layout engine (networkx + matplotlib) for a picture that is usually unreadable at A4.
    The edges carry the actual evidence -- who paid whom, how much, when -- so the table
    is what an officer would cite anyway.
    """
    nodes = {n["id"]: n for n in artifact.get("nodes") or []}
    links = artifact.get("links") or []
    rows = []
    for link in links[:200]:
        src = nodes.get(link.get("source"), {}).get("label", link.get("source"))
        dst = nodes.get(link.get("target"), {}).get("label", link.get("target"))
        props = link.get("properties") or {}
        detail = ", ".join(f"{k}: {v}" for k, v in props.items() if k != "amount")
        rows.append(
            f"<tr><td>{_escape(src)}</td><td>{_escape(link.get('relationship'))}</td>"
            f"<td>{_escape(dst)}</td><td>{_escape(detail)}</td></tr>"
        )
    legend = ", ".join(sorted({str(n.get("type")) for n in nodes.values()}))
    caption = _escape(artifact.get("caption") or "")
    return (
        f"<h2>{_escape(artifact.get('title'))}</h2>"
        f"<table><tr><th>From</th><th>Link</th><th>To</th><th>Evidence</th></tr>"
        f"{''.join(rows)}</table>"
        f'<div class="caption">{caption} Entities: {_escape(legend)}.</div>'
    )


def render_report_html(
    title: str,
    sections: list[dict[str, str]],
    artifacts: list[dict[str, Any]] | None = None,
    meta: str = "",
    officer: str = "",
    language: str = "en",
) -> str:
    parts: list[str] = []
    for section in sections or []:
        heading = section.get("heading")
        if heading:
            parts.append(f"<h2>{_escape(heading)}</h2>")
        parts.append(_markdown_to_html(section.get("body_markdown") or section.get("body") or ""))

    for artifact in artifacts or []:
        kind = artifact.get("kind")
        if kind == "table":
            parts.append(_table_html(artifact))
        elif kind == "graph":
            parts.append(_graph_html(artifact))
        elif kind == "document" and artifact.get("text"):
            parts.append(f"<h2>{_escape(artifact.get('title'))}</h2>")
            parts.append(_markdown_to_html(artifact["text"]))

    family = _resolve_font(language)
    font_family = family if family else "Helvetica"

    return _TEMPLATE.format(
        font_face="",  # see _resolve_font: registration is via DEFAULT_FONT, not @font-face
        font_family=font_family,
        title=_escape(title),
        meta=_escape(meta),
        generated=datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
        officer=_escape(officer or "Crime Intelligence Platform"),
        sections="".join(parts),
    )


def html_to_pdf(html: str) -> bytes:
    """Render to PDF bytes. Raises if xhtml2pdf reports errors."""
    from xhtml2pdf import pisa

    buffer = io.BytesIO()
    result = pisa.CreatePDF(src=html, dest=buffer, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF rendering failed with {result.err} error(s)")
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

    def _build(handle, title: str, sections: list[dict], artifacts: list[dict]) -> str:
        html = render_report_html(
            title=title, sections=sections, artifacts=artifacts,
            meta=case_ref, officer=officer, language=language,
        )
        pdf = html_to_pdf(html)
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
        return (f"Report '{title}' generated as a downloadable PDF ({len(pdf) // 1024} KB) "
                f"with {len(artifacts)} attached finding(s). It is available to the officer "
                f"as a document artifact - do not repeat its contents in your answer.")

    def _generate_report(title: str, sections: list[dict], include_artifacts: bool = True) -> str:
        emitter = CURRENT_EMITTER.get()
        if not (sections or []):
            return "Provide at least one section with a heading and body_markdown."

        # Artifacts already emitted this run -- the tables and trails the analysis tools
        # produced. Reusing them keeps the report's numbers identical to what the officer
        # saw on screen, instead of asking the model to retype them.
        artifacts = bus.artifacts_of(run_id) if include_artifacts else []

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
            "sections: a list of {heading, body_markdown} you compose from what the other "
            "tools returned. include_artifacts=True attaches the tables and money trails "
            "already produced in this conversation, so do not retype their numbers."
        ),
    )
