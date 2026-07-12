"""
llm_client.py - LangChain Bedrock client with rate limiting and retries.

This module centralizes LLM invocation behavior so both historical narrative
generation and live-demo document generation share identical resilience policy.
"""
from __future__ import annotations

import os
from typing import Optional

from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import BaseMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import RunnableLambda

from . import config

load_dotenv()


class RetryableLLMError(RuntimeError):
    """Transient failure (throttle/timeout/service unavailable)."""


class FatalLLMError(RuntimeError):
    """Non-retryable failure (auth/validation/resource-not-found)."""


_RETRYABLE_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "RequestTimeoutException",
    "InternalServerException",
}

_FATAL_CODES = {
    "AccessDeniedException",
    "ValidationException",
    "ResourceNotFoundException",
    "UnrecognizedClientException",
}

_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_second=config.BEDROCK_REQUESTS_PER_SECOND,
    max_bucket_size=config.BEDROCK_MAX_BUCKET,
)


def _effective_region() -> str:
    return (
        os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def _effective_boto_config() -> Config:
    return Config(
        retries={"max_attempts": config.LLM_MAX_RETRIES, "mode": "adaptive"},
        read_timeout=config.LLM_TIMEOUT,
        connect_timeout=30,
    )


def _classify_exc(exc: Exception) -> Exception:
    """Convert provider exceptions into explicit retryable/fatal classes."""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "UnknownClientError")
        if code in _FATAL_CODES:
            return FatalLLMError(f"Fatal Bedrock error [{code}]: {exc}")
        if code in _RETRYABLE_CODES:
            return RetryableLLMError(f"Retryable Bedrock error [{code}]: {exc}")
        return RetryableLLMError(f"Unclassified Bedrock error [{code}]: {exc}")

    text = str(exc)
    if any(k in text for k in ("429", "TooManyRequests", "Throttling", "timeout", "timed out")):
        return RetryableLLMError(f"Retryable LLM error: {exc}")
    return FatalLLMError(f"Fatal LLM error: {exc}")


_CONTENT_FILTER_MARKERS = (
    "generated text has been blocked",
    "content filters",
    "content policy",
    "unable to fulfill this request",
    "i cannot fulfill",
    "i'm unable to generate",
)


def _message_to_text(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        text = content.strip()
    else:
        parts: list[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    t = item.get("text")
                    if t:
                        parts.append(str(t))
                else:
                    parts.append(str(item))
        text = "\n".join(parts).strip()

    lower = text.lower()
    if any(marker in lower for marker in _CONTENT_FILTER_MARKERS):
        raise FatalLLMError(f"Model response blocked by content filter: {text[:120]!r}")
    return text


def invoke_text(
    *,
    prompt: str,
    model_id: str,
    temperature: float,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Invoke Bedrock through LangChain with proactive rate limiting and retries.
    """
    max_tokens = max_tokens or config.NARRATIVE_MAX_TOKENS

    model = ChatBedrockConverse(
        model=model_id,
        region_name=_effective_region(),
        temperature=temperature,
        max_tokens=max_tokens,
        rate_limiter=_RATE_LIMITER,
        config=_effective_boto_config(),
        max_retries=config.LLM_MAX_RETRIES,
    )

    # Wrap invoke to classify exceptions first, then retry only retryable ones.
    def _invoke_once(raw_prompt: str) -> BaseMessage:
        try:
            return model.invoke(raw_prompt)
        except Exception as exc:
            raise _classify_exc(exc) from exc

    runnable = RunnableLambda(_invoke_once)
    try:
        runnable = runnable.with_retry(
            stop_after_attempt=config.LLM_MAX_RETRIES,
            wait_exponential_jitter=True,
            retry_if_exception_type=(RetryableLLMError,),
        )
    except TypeError:
        runnable = runnable.with_retry(stop_after_attempt=config.LLM_MAX_RETRIES)

    try:
        response = runnable.invoke(prompt)
        text = _message_to_text(response)
        if not text:
            raise FatalLLMError("Model response was empty")
        return text
    except (RetryableLLMError, FatalLLMError):
        raise
    except Exception as exc:  # Normalize provider/library exceptions
        raise _classify_exc(exc) from exc

