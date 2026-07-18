"""Offline checks for assistant voice STT helpers.

No Sarvam, no LLM, no mic — pins the language map, audio framing, and the
refine-fallback-to-original path that must never leave the officer worse off.

Run: python backend/tests/test_assistant_transcription.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant import stt  # noqa: E402


class TestLangMap(unittest.TestCase):
    def test_ui_languages_map_to_sarvam(self):
        self.assertEqual(stt.LANG_TO_SARVAM["en"], "en-IN")
        self.assertEqual(stt.LANG_TO_SARVAM["hi"], "hi-IN")
        self.assertEqual(stt.LANG_TO_SARVAM["kn"], "kn-IN")

    def test_build_sarvam_url_includes_language_and_pcm(self):
        url = stt.build_sarvam_url("kn")
        self.assertIn("language-code=kn-IN", url)
        self.assertIn("input_audio_codec=pcm_s16le", url)
        self.assertIn("model=saaras%3Av3", url)  # urlencoded colon, or unencoded
        # Accept either encoding of the colon.
        self.assertTrue("saaras:v3" in url or "saaras%3Av3" in url)
        self.assertIn("mode=transcribe", url)
        self.assertIn("flush_signal=true", url)


class TestAudioFraming(unittest.TestCase):
    def test_frame_audio_message_shape(self):
        msg = stt.frame_audio_message("YWJj")
        self.assertEqual(msg["audio"]["data"], "YWJj")
        self.assertEqual(msg["audio"]["sample_rate"], "16000")
        self.assertEqual(msg["audio"]["encoding"], "audio/wav")


class TestRefine(unittest.TestCase):
    def test_build_refine_messages_same_language(self):
        messages = stt.build_refine_messages("follow money trail", "hi")
        self.assertEqual(len(messages), 2)
        system = messages[0].content.lower()
        self.assertIn("hindi", system)
        self.assertIn("same language", system)
        self.assertIn("do not translate", system)
        self.assertEqual(messages[1].content, "follow money trail")

    def test_refine_returns_original_when_llm_empty(self):
        fake_result = MagicMock()
        fake_result.content = "   "
        fake_llm = MagicMock()
        fake_llm.invoke.return_value = fake_result
        fake_llm.with_fallbacks.return_value = fake_llm
        with patch("app.assistant.stt.build_llm_pair", return_value=(fake_llm, fake_llm)):
            out = stt.refine_transcript("raw garbled query", "en")
        self.assertEqual(out, "raw garbled query")

    def test_refine_returns_original_on_llm_failure(self):
        fake_llm = MagicMock()
        fake_llm.with_fallbacks.return_value = fake_llm
        fake_llm.invoke.side_effect = RuntimeError("boom")
        with patch("app.assistant.stt.build_llm_pair", return_value=(fake_llm, fake_llm)):
            out = stt.refine_transcript("keep me", "kn")
        self.assertEqual(out, "keep me")

    def test_refine_returns_llm_text_when_present(self):
        fake_result = MagicMock()
        fake_result.content = "Show the money trail for this case"
        fake_llm = MagicMock()
        fake_llm.invoke.return_value = fake_result
        fake_llm.with_fallbacks.return_value = fake_llm
        with patch("app.assistant.stt.build_llm_pair", return_value=(fake_llm, fake_llm)):
            out = stt.refine_transcript("show money trail case", "en")
        self.assertEqual(out, "Show the money trail for this case")

    def test_refine_empty_input(self):
        self.assertEqual(stt.refine_transcript("  "), "")


if __name__ == "__main__":
    unittest.main()
