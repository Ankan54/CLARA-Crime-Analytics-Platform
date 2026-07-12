"""
embeddings.py — AWS Bedrock Titan embed wrapper with truncation and retry/backoff.
"""
from __future__ import annotations
import json
import time
import logging

log = logging.getLogger(__name__)

# Lazy singleton — created on first call to avoid SDK init overhead at import.
_client = None


def _get_client():
    global _client
    if _client is None:
        import boto3
        from . import config as cfg
        _client = boto3.client("bedrock-runtime", region_name=cfg.AWS_REGION)
    return _client


def embed(text: str, *, retries: int = 5, base_delay: float = 2.0) -> list[float]:
    """
    Embed text using Titan. Truncates at EMBED_TEXT_MAX_CHARS, retries on throttle.
    Returns a 1536-d float list.
    """
    from . import config as cfg
    import botocore.exceptions

    text = text[:cfg.EMBED_TEXT_MAX_CHARS]
    client = _get_client()
    body = json.dumps({"inputText": text})
    delay = base_delay

    for attempt in range(retries + 1):
        try:
            resp = client.invoke_model(
                modelId=cfg.BEDROCK_EMBEDDING_MODEL,
                body=body,
                accept="application/json",
                contentType="application/json",
            )
            return json.loads(resp["body"].read())["embedding"]
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code in {"ThrottlingException", "ServiceUnavailableException"} and attempt < retries:
                log.warning("Bedrock throttle (attempt %d/%d), sleeping %.1fs", attempt + 1, retries, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
            else:
                raise
    raise RuntimeError("embed: exceeded retry budget")  # unreachable
