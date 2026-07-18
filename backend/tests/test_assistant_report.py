"""Checks for PDF report rendering.

Kannada export is a stated requirement, and its failure mode is invisible: reportlab does
no glyph fallback, so a missing font produces a valid, error-free, EMPTY page. Nothing
raises. The only way to know it works is to read the text back out of the PDF, which is
what these tests do.

They also pin the second trap: Google's per-script Noto faces carry digits but no Latin
letters, so an un-merged font renders "BNS 318" as " 318 " inside Kannada prose --
silently dropping the statute names the prompt promises to keep verbatim.

Run: python backend/tests/test_assistant_report.py
"""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant.skills.report import (  # noqa: E402
    FONT_DIR,
    FONT_FILE,
    html_to_pdf,
    render_report_html,
)

KANNADA = "ಹಣದ ಜಾಡು ಪತ್ತೆಯಾಗಿದೆ"
HINDI = "पैसे का पता चल गया है"


def pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


def has_script(text: str, lo: str, hi: str) -> bool:
    return any(lo <= ch <= hi for ch in text)


class TestFontsBundled(unittest.TestCase):
    def test_font_ships_with_the_code(self):
        # A missing font degrades silently to a blank report, so absence must fail loudly
        # here instead of on stage.
        path = FONT_DIR / FONT_FILE
        self.assertTrue(path.exists(), f"bundled font missing at {path}")
        self.assertGreater(path.stat().st_size, 50_000, f"{FONT_FILE} looks truncated")

    def test_one_font_covers_latin_and_both_indic_scripts(self):
        # Only the first Indic face registered in a process ever draws, so all three
        # scripts must live in a single face or one language silently renders blank.
        from reportlab.pdfbase.ttfonts import TTFontFile

        cmap = TTFontFile(str(FONT_DIR / FONT_FILE)).charToGlyph
        for label, sample in [
            ("latin (statute names)", "BNSITAct"),
            ("digits", "0123456789"),
            ("kannada", "ಹಣದಜಾಡುಪತ"),
            ("devanagari", "पैसेकाचल"),
        ]:
            missing = [c for c in sample if ord(c) not in cmap]
            self.assertEqual(missing, [], f"font lacks {label}: {missing}")


class TestPdfRendering(unittest.TestCase):
    def _render(self, language: str, body: str) -> bytes:
        return html_to_pdf(render_report_html(
            title="Case Report",
            language=language,
            meta="Digital arrest | Bengaluru",
            officer="PSI Deepa Kamath",
            sections=[{"heading": "Summary", "body_markdown": body}],
        ))

    def test_english_report_renders_readable_text(self):
        pdf = self._render("en", "Rs 9.3 lakh is still freezable.")
        self.assertTrue(pdf.startswith(b"%PDF-"))
        text = pdf_text(pdf)
        self.assertIn("lakh", text)
        self.assertIn("Karnataka State Police", text)

    def test_kannada_text_actually_reaches_the_page(self):
        pdf = self._render("kn", f"{KANNADA}. BNS 318 / IT Act 66D.")
        self.assertTrue(b"/FontFile2" in pdf, "no embedded font -> Kannada silently dropped")
        text = pdf_text(pdf)
        self.assertTrue(has_script(text, "ಀ", "೿"), "no Kannada codepoints in the rendered PDF")
        # Identifiers must survive inside an Indic report.
        self.assertIn("BNS", text)
        self.assertIn("318", text)

    def test_kannada_survives_after_an_english_render(self):
        """The order a real server hits: English report, then a Kannada one.

        xhtml2pdf/reportlab freeze font state after the first render -- a font registered
        later embeds but never draws. This exact sequence produced a blank Kannada page
        while Kannada-alone passed, which is why fonts are registered eagerly.
        """
        self._render("en", "English first, to warm the renderer.")
        pdf = self._render("kn", KANNADA)
        text = pdf_text(pdf)
        self.assertTrue(has_script(text, "ಀ", "೿"),
                        "Kannada dropped when rendered after an English report")

    def test_hindi_text_actually_reaches_the_page(self):
        pdf = self._render("hi", f"{HINDI}. PMLA 3.")
        self.assertTrue(b"/FontFile2" in pdf)
        text = pdf_text(pdf)
        self.assertTrue(has_script(text, "ऀ", "ॿ"), "no Devanagari codepoints in the rendered PDF")
        self.assertIn("PMLA", text)

    def test_artifacts_render_as_tables_and_edge_lists(self):
        pdf = html_to_pdf(render_report_html(
            title="Dossier", language="en", sections=[],
            artifacts=[
                {"kind": "table", "title": "Transfers", "columns": ["When", "Amount"],
                 "rows": [["2026-04-14 10:45", "Rs 12.00 lakh"]], "caption": "Time-ordered."},
                {"kind": "graph", "title": "Money trail",
                 "nodes": [{"id": "a", "label": "Victim A/c 1234", "type": "Victim"},
                           {"id": "b", "label": "AGG ACC 01", "type": "Mule"}],
                 "links": [{"source": "a", "target": "b", "relationship": "Rs 12.00 lakh",
                            "properties": {"when": "2026-04-14 10:45", "mode": "NEFT"}}]},
            ],
        ))
        text = pdf_text(pdf)
        self.assertIn("Transfers", text)
        # A graph becomes an edge list: the evidence, not an unreadable static layout.
        self.assertIn("Money trail", text)
        self.assertIn("Victim", text)

    def test_disclaimer_is_always_present(self):
        # Every exported artefact must carry the synthetic-data / decision-support framing.
        text = pdf_text(self._render("en", "anything"))
        self.assertIn("synthetic", text)
        self.assertIn("Decision support", text)

    def test_raw_html_in_content_is_escaped_not_rendered(self):
        # The rendered HTML is also served as a document artifact into the frontend's
        # iframe, and this body is LLM-authored from user input.
        html = render_report_html(
            title="T", language="en",
            sections=[{"heading": "S", "body_markdown": "Amount <script>alert(1)</script> & more"}],
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        # ...and it still reaches the page as visible text rather than vanishing.
        self.assertIn("script", pdf_text(html_to_pdf(html)))

    def test_markdown_still_renders_after_escaping(self):
        html = render_report_html(
            title="T", language="en",
            sections=[{"heading": "S", "body_markdown": "**bold** and a list:\n\n- one\n- two"}],
        )
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<li>one</li>", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
