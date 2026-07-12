from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional, Sequence

import requests
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

logger = logging.getLogger(__name__)

try:
    from langchain_core.rate_limiters import InMemoryRateLimiter
except Exception:  # pragma: no cover
    InMemoryRateLimiter = None  # type: ignore[assignment]
    logger.debug("langchain_core InMemoryRateLimiter unavailable", exc_info=True)

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore[assignment]
    logger.debug("langchain_openai unavailable", exc_info=True)

try:
    from langchain_anthropic import ChatAnthropic
except Exception:  # pragma: no cover
    ChatAnthropic = None  # type: ignore[assignment]
    logger.debug("langchain_anthropic unavailable", exc_info=True)


_token_cache: dict[str, str | float | None] = {"token": None, "expires_at": 0.0}


def _cfg(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _get_access_token() -> str:
    now = time.time()
    token = _token_cache["token"]
    expires_at = float(_token_cache["expires_at"] or 0.0)
    if token and now < expires_at - 60:
        return str(token)

    auth_domain = _cfg("ZOHO_CATALYST_AUTH_DOMAIN", "https://accounts.zohoportal.in")
    client_id = _cfg("ZOHO_CATALYST_CLIENT_ID")
    logger.debug("token_refresh: auth_domain=%s client_id=%s", auth_domain, client_id)
    try:
        response = requests.post(
            f"{auth_domain}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": _cfg("ZOHO_CATALYST_CLIENT_SECRET"),
                "refresh_token": _cfg("ZOHO_CATALYST_REFRESH_TOKEN"),
            },
            timeout=20,
        )
    except requests.exceptions.ConnectionError as exc:
        logger.error("token_refresh: connection error — is ZOHO_CATALYST_AUTH_DOMAIN reachable? %s", exc)
        raise
    except requests.exceptions.Timeout:
        logger.error("token_refresh: timed out connecting to %s", auth_domain)
        raise
    if response.status_code != 200:
        logger.error("token_refresh: HTTP %s body=%s", response.status_code, response.text[:300])
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        logger.error("token_refresh: no access_token in response — error=%s message=%s",
                     payload.get("error"), payload.get("error_description"))
        raise RuntimeError(f"Unable to refresh Zoho token: {payload}")
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + float(payload.get("expires_in", 3600))
    logger.debug("token_refresh: ok expires_in=%s scope=%s", payload.get("expires_in"), payload.get("scope"))
    return str(token)


def describe_image(image_bytes: bytes, prompt: str | None = None) -> str:
    """Transcribe visible text/fields from a document image via the Zoho-hosted
    Qwen3 VLM (vlm/chat) — same OAuth token as ChatZohoGLM. The returned text
    is fed into the normal classify -> schema-extract flow, so images need no
    special-casing downstream."""
    endpoint_url = _cfg("ZOHO_QUICKML_VLM_ENDPOINT_URL")
    if not endpoint_url:
        raise RuntimeError("ZOHO_QUICKML_VLM_ENDPOINT_URL not configured.")
    logger.debug("describe_image: endpoint=%s image_bytes=%d", endpoint_url, len(image_bytes))
    payload = {
        "prompt": prompt or (
            "Transcribe every piece of visible text in this document image exactly as written "
            "(names, numbers, dates, amounts, account/UPI/phone details, message bubbles). "
            "Preserve line breaks and reading order. Output only the transcribed text."
        ),
        "model": _cfg("ZOHO_QUICKML_VLM_MODEL_NAME", "VL-Qwen3.6-35B-A3B"),
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "system_prompt": "Be concise and factual.",
        "top_k": 50,
        "top_p": 0.9,
        "temperature": 0.2,
        "max_tokens": 2000,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Zoho-oauthtoken {_get_access_token()}",
        "CATALYST-ORG": _cfg("ZOHO_QUICKML_CATALYST_ORG"),
    }
    try:
        response = requests.post(endpoint_url, json=payload, headers=headers, timeout=60)
    except requests.exceptions.ConnectionError as exc:
        logger.error("describe_image: connection error endpoint=%s: %s", endpoint_url, exc)
        raise
    except requests.exceptions.Timeout:
        logger.error("describe_image: timed out (60s) endpoint=%s", endpoint_url)
        raise
    if response.status_code != 200:
        logger.error("describe_image: HTTP %s body=%s", response.status_code, response.text[:300])
        raise RuntimeError(f"VLM API error {response.status_code}: {response.text[:300]}")
    body = response.json()
    text = str(body.get("response") or body.get("choices", [{}])[0].get("message", {}).get("content", ""))
    logger.debug("describe_image: ok text_length=%d", len(text))
    return text


def _to_openai_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    role_map: dict[type[BaseMessage], str] = {
        HumanMessage: "user",
        AIMessage: "assistant",
        SystemMessage: "system",
        ToolMessage: "tool",
    }
    out: list[dict[str, Any]] = []
    for message in messages:
        role = role_map.get(type(message), "user")
        entry: dict[str, Any] = {"role": role, "content": message.content}
        if isinstance(message, ToolMessage):
            entry["tool_call_id"] = message.tool_call_id
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            entry["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                }
                for tc in message.tool_calls
            ]
        out.append(entry)
    return out


def _parse_tool_calls(raw_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for call in raw_calls:
        fn = call.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        parsed.append({"id": call.get("id"), "name": fn.get("name"), "args": args, "type": "tool_call"})
    return parsed


class ChatZohoGLM(BaseChatModel):
    endpoint_url: str = _cfg("ZOHO_QUICKML_ENDPOINT_URL")
    catalyst_org: str = _cfg("ZOHO_QUICKML_CATALYST_ORG")
    model_name: str = _cfg("ZOHO_QUICKML_MODEL_NAME", "crm-di-glm47b_30b_it")
    temperature: float = 0.2
    max_tokens: int = 1024
    max_retry_429: int = 3
    retry_backoff_seconds: float = 1.5
    request_timeout_seconds: int = 60
    rate_limiter: Any = None

    @property
    def _llm_type(self) -> str:
        return "zoho-quickml-glm"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Zoho-oauthtoken {_get_access_token()}",
            "CATALYST-ORG": self.catalyst_org,
            "Content-Type": "application/json",
        }

    def _acquire_rate_limit(self) -> None:
        limiter = self.rate_limiter
        if limiter is None:
            return
        acquire = getattr(limiter, "acquire", None)
        if acquire is None:
            return
        try:
            acquire(blocking=True)
        except TypeError:
            acquire()

    def _post_with_retry(self, payload: dict[str, Any]) -> requests.Response:
        delay = self.retry_backoff_seconds
        attempts = max(1, self.max_retry_429)
        last_response: requests.Response | None = None
        for attempt in range(1, attempts + 1):
            self._acquire_rate_limit()
            logger.debug("glm_request: attempt=%d/%d model=%s messages=%d",
                         attempt, attempts, self.model_name, len(payload.get("messages", [])))
            try:
                response = requests.post(
                    self.endpoint_url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.request_timeout_seconds,
                )
            except requests.exceptions.ConnectionError as exc:
                logger.error("glm_request: connection error endpoint=%s: %s", self.endpoint_url, exc)
                raise
            except requests.exceptions.Timeout:
                logger.error("glm_request: timed out (%ds) endpoint=%s", self.request_timeout_seconds, self.endpoint_url)
                raise
            if response.status_code == 429:
                logger.warning("glm_request: 429 rate-limited attempt=%d backoff=%.1fs", attempt, delay)
                last_response = response
                if attempt < attempts:
                    time.sleep(delay)
                    delay *= 2
                continue
            if response.status_code != 200:
                logger.error("glm_request: HTTP %s body=%s", response.status_code, response.text[:300])
            return response
        assert last_response is not None
        return last_response

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": _to_openai_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if stop:
            payload["stop"] = stop
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")

        response = self._post_with_retry(payload)
        if response.status_code != 200:
            raise RuntimeError(f"GLM API error {response.status_code}: {response.text[:300]}")

        body = response.json()
        if body.get("code") and body.get("message"):
            logger.error("glm_response: error code=%s message=%s", body["code"], body["message"])
            raise RuntimeError(f"GLM API error: {body['code']} — {body['message']}")
        content = body.get("response") or body.get("choices", [{}])[0].get("message", {}).get("content", "")
        calls = body.get("tool_calls") or []
        usage = body.get("usage", {})
        logger.debug("glm_response: ok content_length=%d tool_calls=%d tokens=%s",
                     len(str(content)), len(calls), usage)

        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=content,
                        tool_calls=_parse_tool_calls(calls),
                        response_metadata={"model": body.get("model"), "usage": body.get("usage", {})},
                    )
                )
            ]
        )

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ChatZohoGLM":
        from langchain_core.utils.function_calling import convert_to_openai_tool

        openai_tools = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=openai_tools, **kwargs)


def _build_single(provider: str) -> BaseChatModel:
    provider = provider.lower()
    logger.debug("build_llm: provider=%s", provider)
    limiter = None
    if InMemoryRateLimiter is not None:
        limiter = InMemoryRateLimiter(
            requests_per_second=float(_cfg("LLM_REQUESTS_PER_SECOND", "0.8")),
            max_bucket_size=2,
            check_every_n_seconds=0.1,
        )

    if provider == "zoho":
        logger.debug("build_llm: zoho endpoint=%s org=%s model=%s",
                     _cfg("ZOHO_QUICKML_ENDPOINT_URL"), _cfg("ZOHO_QUICKML_CATALYST_ORG"), _cfg("ZOHO_QUICKML_MODEL_NAME", "crm-di-glm47b_30b_it"))
        return ChatZohoGLM(rate_limiter=limiter)
    if provider == "openai":
        if ChatOpenAI is None:
            raise RuntimeError("langchain-openai is not installed.")
        logger.debug("build_llm: openai model=%s", _cfg("OPENAI_MODEL", "gpt-4o-mini"))
        return ChatOpenAI(
            model=_cfg("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=_cfg("OPENAI_API_KEY"),
            temperature=0.2,
            max_retries=3,
            rate_limiter=limiter,
        )
    if provider == "anthropic":
        if ChatAnthropic is None:
            raise RuntimeError("langchain-anthropic is not installed.")
        logger.debug("build_llm: anthropic model=%s", _cfg("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"))
        return ChatAnthropic(
            model=_cfg("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            api_key=_cfg("ANTHROPIC_API_KEY"),
            temperature=0.2,
            max_retries=3,
            rate_limiter=limiter,
        )
    raise ValueError(f"Unsupported LLM provider: {provider}")


def _provider_for_data_ingestion() -> str:
    return _cfg("DATA_INGESTION_LLM", "zoho").lower()


def build_llm_pair() -> tuple[BaseChatModel, BaseChatModel]:
    primary_provider = _provider_for_data_ingestion()
    if primary_provider == "zoho":
        fallback_provider = "openai"
    elif primary_provider == "anthropic":
        fallback_provider = "openai"
    elif primary_provider == "openai":
        fallback_provider = "anthropic"
    else:
        raise ValueError(f"Unsupported DATA_INGESTION_LLM value: {primary_provider}")
    return _build_single(primary_provider), _build_single(fallback_provider)


def build_classifier():
    primary, fallback = build_llm_pair()
    return primary.with_fallbacks([fallback])


def build_extractor(schema: Any):
    primary, fallback = build_llm_pair()
    return primary.with_structured_output(schema).with_fallbacks([fallback.with_structured_output(schema)])

