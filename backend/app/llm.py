from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional, Sequence

import requests
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .config import settings

try:
    from langchain_core.rate_limiters import InMemoryRateLimiter
except Exception:  # pragma: no cover - older langchain-core
    InMemoryRateLimiter = None  # type: ignore[assignment]
    logging.getLogger(__name__).debug("langchain_core.InMemoryRateLimiter unavailable", exc_info=True)

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore[assignment]
    logging.getLogger(__name__).debug("langchain_openai unavailable", exc_info=True)

try:
    from langchain_anthropic import ChatAnthropic
except Exception:  # pragma: no cover
    ChatAnthropic = None  # type: ignore[assignment]
    logging.getLogger(__name__).debug("langchain_anthropic unavailable", exc_info=True)


_token_cache: dict[str, float | str | None] = {"token": None, "expires_at": 0.0}
logger = logging.getLogger(__name__)


def _get_access_token() -> str:
    now = time.time()
    token = _token_cache["token"]
    expires_at = float(_token_cache["expires_at"] or 0.0)
    if token and now < expires_at - 60:
        logger.debug("llm access token cache hit expires_at=%s", expires_at)
        return str(token)

    logger.debug("llm refreshing zoho access token auth_domain=%s", settings.zoho_auth_domain)
    try:
        resp = requests.post(
            f"{settings.zoho_auth_domain}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.zoho_client_id,
                "client_secret": settings.zoho_client_secret,
                "refresh_token": settings.zoho_refresh_token,
            },
            timeout=15,
        )
    except Exception:
        logger.exception("llm token refresh request failed")
        raise
    resp.raise_for_status()
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        logger.error("llm token refresh returned no access_token payload=%s", data)
        raise RuntimeError(f"Unable to refresh Zoho access token: {data}")

    _token_cache["token"] = access_token
    _token_cache["expires_at"] = now + float(data.get("expires_in", 3600))
    logger.debug("llm token refresh success expires_in=%s", data.get("expires_in", 3600))
    return str(access_token)


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
        parsed.append({"id": call["id"], "name": fn["name"], "args": args, "type": "tool_call"})
    return parsed


class ChatZohoGLM(BaseChatModel):
    """LangChain chat wrapper for Zoho QuickML GLM."""

    endpoint_url: str = settings.zoho_quickml_endpoint_url
    catalyst_org: str = settings.zoho_quickml_catalyst_org
    model_name: str = settings.zoho_quickml_model_name
    temperature: float = 0.2
    max_tokens: int = 1024
    request_timeout_seconds: int = 60
    max_retry_429: int = 3
    retry_backoff_seconds: float = 1.5
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
            logger.debug(
                "zoho_glm request attempt=%d/%d model=%s messages=%d",
                attempt,
                attempts,
                self.model_name,
                len(payload.get("messages", [])),
            )
            try:
                response = requests.post(
                    self.endpoint_url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.request_timeout_seconds,
                )
            except Exception:
                logger.exception(
                    "zoho_glm request failed endpoint=%s model=%s attempt=%d",
                    self.endpoint_url,
                    self.model_name,
                    attempt,
                )
                raise
            if response.status_code != 429:
                if response.status_code != 200:
                    logger.error("zoho_glm non-200 status=%s body=%s", response.status_code, response.text[:300])
                return response
            last_response = response
            logger.warning("zoho_glm rate limited status=429 attempt=%d/%d retry_in=%.1fs", attempt, attempts, delay)
            if attempt == attempts:
                break
            time.sleep(delay)
            delay *= 2

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

        data = response.json()
        logger.debug(
            "zoho_glm response model=%s tool_calls=%d usage=%s",
            data.get("model"),
            len(data.get("tool_calls") or []),
            data.get("usage", {}),
        )
        content = data.get("response") or data.get("choices", [{}])[0].get("message", {}).get("content", "")
        raw_calls = data.get("tool_calls") or []

        ai_msg = AIMessage(
            content=content,
            tool_calls=_parse_tool_calls(raw_calls) if raw_calls else [],
            response_metadata={
                "model": data.get("model"),
                "usage": data.get("usage", {}),
            },
        )
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ChatZohoGLM":
        from langchain_core.utils.function_calling import convert_to_openai_tool

        openai_tools = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=openai_tools, **kwargs)


def _provider_for_purpose(purpose: str) -> str:
    purpose = purpose.lower()
    if purpose == "data_ingestion":
        logger.debug("llm provider for purpose=%s provider=%s", purpose, settings.data_ingestion_llm)
        return settings.data_ingestion_llm
    if purpose == "conv_ai":
        logger.debug("llm provider for purpose=%s provider=%s", purpose, settings.conv_ai_llm)
        return settings.conv_ai_llm
    raise ValueError(f"Unknown purpose: {purpose}")


def _build_single_model(provider: str) -> BaseChatModel:
    provider = provider.lower()
    logger.debug("build_single_model provider=%s", provider)
    rate_limiter = None
    if InMemoryRateLimiter is not None:
        rate_limiter = InMemoryRateLimiter(
            requests_per_second=settings.llm_requests_per_second,
            max_bucket_size=2,
            check_every_n_seconds=0.1,
        )

    if provider == "zoho":
        logger.debug("build_single_model using Zoho GLM model=%s endpoint=%s", settings.zoho_quickml_model_name, settings.zoho_quickml_endpoint_url)
        return ChatZohoGLM(rate_limiter=rate_limiter)

    if provider == "openai":
        if ChatOpenAI is None:
            logger.error("build_single_model provider=openai requested but langchain-openai not installed")
            raise RuntimeError("langchain-openai is not installed.")
        logger.debug("build_single_model using OpenAI model=%s", settings.openai_model)
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key or os.getenv("OPENAI_API_KEY", ""),
            temperature=0.2,
            max_retries=3,
            rate_limiter=rate_limiter,
        )

    if provider == "anthropic":
        if ChatAnthropic is None:
            logger.error("build_single_model provider=anthropic requested but langchain-anthropic not installed")
            raise RuntimeError("langchain-anthropic is not installed.")
        logger.debug("build_single_model using Anthropic model=%s", settings.anthropic_model)
        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", ""),
            temperature=0.2,
            max_retries=3,
            rate_limiter=rate_limiter,
        )

    raise ValueError(f"Unsupported provider '{provider}'. Expected one of zoho|openai|anthropic.")


def build_llm_pair(purpose: str) -> tuple[BaseChatModel, BaseChatModel]:
    primary_provider = _provider_for_purpose(purpose)
    if primary_provider == "zoho":
        fallback_provider = "openai"
    elif primary_provider == "anthropic":
        fallback_provider = "openai"
    elif primary_provider == "openai":
        fallback_provider = "anthropic"
    else:
        raise ValueError(f"Invalid provider '{primary_provider}' for {purpose}.")

    logger.info("build_llm_pair purpose=%s primary=%s fallback=%s", purpose, primary_provider, fallback_provider)
    primary = _build_single_model(primary_provider)
    fallback = _build_single_model(fallback_provider)
    return primary, fallback


def build_classifier(purpose: str = "data_ingestion"):
    logger.debug("build_classifier purpose=%s", purpose)
    primary, fallback = build_llm_pair(purpose=purpose)
    return primary.with_fallbacks([fallback])


def build_extractor(schema: Any, purpose: str = "data_ingestion"):
    logger.debug("build_extractor purpose=%s schema=%s", purpose, getattr(schema, "__name__", type(schema).__name__))
    primary, fallback = build_llm_pair(purpose=purpose)
    primary_structured = primary.with_structured_output(schema)
    fallback_structured = fallback.with_structured_output(schema)
    return primary_structured.with_fallbacks([fallback_structured])

