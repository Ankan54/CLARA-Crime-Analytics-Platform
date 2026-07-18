"""Sarvam streaming STT relay + chat-LLM transcript refine.

The browser cannot attach Sarvam's `Api-Subscription-Key` header on a WebSocket, so
audio flows Browser -> our `/ws/assistant/transcribe` -> Sarvam. On stop we flush,
return the accumulated transcript, and the client posts it to `/assistant/refine` for
a same-language cleanup pass through the chat LLM.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlencode

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import settings
from ..llm import build_llm_pair
from .events import AssistantLanguage

logger = logging.getLogger(__name__)

LANG_TO_SARVAM: dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "kn": "kn-IN",
}

_LANG_LABEL: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "kn": "Kannada",
}

SARVAM_WS_BASE = "wss://api.sarvam.ai/speech-to-text/ws"
SAMPLE_RATE = "16000"


def frame_audio_message(b64_pcm: str, sample_rate: str = SAMPLE_RATE) -> dict[str, Any]:
    """Wrap a browser base64 PCM chunk in Sarvam's audio message shape.

    `encoding` is legacy/`audio/wav`-only on the message; the real codec is declared
    via `input_audio_codec=pcm_s16le` on the connection URL.
    """
    return {
        "audio": {
            "data": b64_pcm,
            "sample_rate": sample_rate,
            "encoding": "audio/wav",
        }
    }


def build_sarvam_url(language: AssistantLanguage | str) -> str:
    code = LANG_TO_SARVAM.get(language, "en-IN")
    params = urlencode({
        "model": "saaras:v3",
        "mode": "transcribe",
        "language-code": code,
        "sample_rate": SAMPLE_RATE,
        "input_audio_codec": "pcm_s16le",
        "high_vad_sensitivity": "true",
        "flush_signal": "true",
    })
    return f"{SARVAM_WS_BASE}?{params}"


def build_refine_messages(text: str, language: AssistantLanguage | str) -> list[Any]:
    label = _LANG_LABEL.get(language, "English")
    system = (
        f"You clean up voice-dictated police queries. Fix garbled, incomplete, or vague "
        f"phrasing into a clear question an investigation assistant can act on. "
        f"Reply ONLY with the corrected text, in the SAME language ({label}); "
        f"do not translate, answer, or add anything else."
    )
    return [SystemMessage(content=system), HumanMessage(content=text)]


def refine_transcript(text: str, language: AssistantLanguage | str = "en") -> str:
    """Clean up a voice transcript with the chat LLM. Never returns worse than the raw text."""
    raw = (text or "").strip()
    if not raw:
        return raw
    try:
        primary, fallback = build_llm_pair(purpose="conv_ai")
        llm = primary.with_fallbacks([fallback])
        result = llm.invoke(build_refine_messages(raw, language))
        content = getattr(result, "content", None)
        if isinstance(content, list):
            # Some providers return content blocks; join text parts.
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        refined = (content or "").strip()
        return refined or raw
    except Exception:
        logger.exception("stt: refine_transcript failed; returning original")
        return raw


async def relay_transcription(ws_client: WebSocket, language: AssistantLanguage | str) -> None:
    """Bridge browser mic audio to Sarvam STT and stream partial/final transcripts back."""
    api_key = settings.sarvam_api_key
    if not api_key:
        await ws_client.send_json({"type": "error", "message": "Sarvam STT is not configured."})
        return

    url = build_sarvam_url(language)
    accumulated: list[str] = []
    stop_requested = asyncio.Event()

    try:
        async with websockets.connect(
            url,
            additional_headers={"Api-Subscription-Key": api_key},
            max_size=8 * 1024 * 1024,
            open_timeout=15,
        ) as sarvam:
            async def handle_sarvam_message(message: str | bytes) -> bool:
                """Return True if the relay should stop (Sarvam error)."""
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="replace")
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    return False
                kind = payload.get("type")
                data = payload.get("data") or {}
                if kind == "data":
                    transcript = (data.get("transcript") or "").strip()
                    if transcript:
                        accumulated.append(transcript)
                        text = " ".join(accumulated).strip()
                        await ws_client.send_json({"type": "partial", "text": text})
                elif kind == "error":
                    err = data.get("error") or data.get("message") or "Sarvam STT error"
                    await ws_client.send_json({"type": "error", "message": str(err)})
                    return True
                return False

            async def browser_to_sarvam() -> None:
                try:
                    while not stop_requested.is_set():
                        raw = await ws_client.receive_text()
                        if not raw:
                            continue
                        if raw.startswith("{"):
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                msg = None
                            if isinstance(msg, dict) and msg.get("type") == "stop":
                                stop_requested.set()
                                await sarvam.send(json.dumps({"type": "flush"}))
                                return
                            if isinstance(msg, dict) and "audio" in msg:
                                await sarvam.send(raw)
                                continue
                        await sarvam.send(json.dumps(frame_audio_message(raw)))
                except WebSocketDisconnect:
                    stop_requested.set()
                    try:
                        await sarvam.send(json.dumps({"type": "flush"}))
                    except Exception:
                        pass

            async def sarvam_to_browser() -> None:
                try:
                    while not stop_requested.is_set():
                        try:
                            message = await asyncio.wait_for(sarvam.recv(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        if await handle_sarvam_message(message):
                            stop_requested.set()
                            return
                except websockets.exceptions.ConnectionClosed:
                    pass

            browser_task = asyncio.create_task(browser_to_sarvam())
            sarvam_task = asyncio.create_task(sarvam_to_browser())
            done, pending = await asyncio.wait(
                {browser_task, sarvam_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            stop_requested.set()
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                    raise exc

            # After flush, drain a short window for the last utterance transcript.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 2.0
            while loop.time() < deadline:
                try:
                    message = await asyncio.wait_for(sarvam.recv(), timeout=0.4)
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    break
                if await handle_sarvam_message(message):
                    break
    except WebSocketDisconnect:
        logger.info("stt: browser disconnected lang=%s", language)
        return
    except Exception as exc:
        logger.exception("stt: relay failed lang=%s", language)
        try:
            await ws_client.send_json({"type": "error", "message": f"Transcription failed: {exc}"})
        except Exception:
            pass
        return

    final = " ".join(accumulated).strip()
    try:
        await ws_client.send_json({"type": "final", "text": final})
    except Exception:
        logger.debug("stt: could not send final transcript (client gone)")
