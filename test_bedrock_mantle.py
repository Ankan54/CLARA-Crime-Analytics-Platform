"""Standalone probe for the Bedrock **Mantle** endpoint (OpenAI-compatible).

Why: some newer models in .env (CHAT_LLM_ID=xai.grok-4.3, BEDROCK_MODEL_ID=zai.glm-5)
are NOT served by the bedrock-runtime Converse API our llm.py currently uses. Mantle
(https://bedrock-mantle.{region}.api.aws/v1) serves them via the OpenAI Chat Completions
API. This script proves the auth + chat + tool-calling path BEFORE we touch llm.py.

Auth: Mantle takes a Bedrock bearer API key OR SigV4. The OpenAI SDK can only send a
bearer, so we mint a short-term bearer from the .env IAM creds using botocore's
SigV4QueryAuth (same algorithm as the aws-bedrock-token-generator package -- inlined to
avoid a new dependency; botocore is already installed).

Run: python test_bedrock_mantle.py
"""
from __future__ import annotations

import base64
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
MANTLE_BASE_URL = f"https://bedrock-mantle.{REGION}.api.aws/v1"
CHAT_MODEL = os.getenv("CHAT_LLM_ID", "xai.grok-4.3")
INGEST_MODEL = os.getenv("BEDROCK_MODEL_ID", "zai.glm-5")


def mint_bedrock_bearer_token(region: str, duration: int = 43200) -> str:
    """Short-term (<=12h) Bedrock API key from the default AWS credential chain.

    Format: bedrock-api-key-<base64(presigned CallWithBearerToken url)>&Version=1
    (copied from aws/aws-bedrock-token-generator-python -- stable, versioned wire format).
    """
    import boto3
    from botocore.auth import SigV4QueryAuth
    from botocore.awsrequest import AWSRequest

    creds = boto3.Session().get_credentials()
    if creds is None:
        raise RuntimeError("No AWS credentials found (AWS_ACCESS_KEY_ID/SECRET not set?)")
    frozen = creds.get_frozen_credentials()

    request = AWSRequest(
        method="POST",
        url="https://bedrock.amazonaws.com/",
        headers={"host": "bedrock.amazonaws.com"},
        params={"Action": "CallWithBearerToken"},
    )
    SigV4QueryAuth(frozen, "bedrock", region, expires=duration).add_auth(request)
    presigned = request.url.replace("https://", "") + "&Version=1"
    encoded = base64.b64encode(presigned.encode("utf-8")).decode("utf-8")
    return f"bedrock-api-key-{encoded}"


def divider(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> int:
    divider("0. Config")
    print(f"region      = {REGION}")
    print(f"base_url    = {MANTLE_BASE_URL}")
    print(f"chat model  = {CHAT_MODEL}")
    print(f"ingest model= {INGEST_MODEL}")

    divider("1. Auth: prefer MANTLE_API_KEY (long-term), else mint short-term bearer")
    token = os.getenv("MANTLE_API_KEY", "").strip()
    if token:
        print(f"OK using MANTLE_API_KEY prefix={token[:8]}... len={len(token)}")
    else:
        try:
            token = mint_bedrock_bearer_token(REGION)
            print(f"OK minted bearer prefix={token[:24]}... len={len(token)}")
        except Exception as exc:
            print(f"FAIL minting token: {exc!r}")
            return 1

    from openai import OpenAI

    client = OpenAI(base_url=MANTLE_BASE_URL, api_key=token)

    divider("2. GET /v1/models (discover what Mantle actually serves)")
    available: set[str] = set()
    try:
        for m in client.models.list().data:
            available.add(m.id)
        print(f"OK {len(available)} models. Sample: {sorted(available)[:15]}")
        for want in {CHAT_MODEL, INGEST_MODEL}:
            print(f"  {'PRESENT' if want in available else 'MISSING '} {want}")
    except Exception as exc:
        print(f"WARN models.list failed ({exc!r}); continuing with configured ids anyway")

    divider("3. Raw OpenAI SDK chat.completions for each model")
    for model in [CHAT_MODEL, INGEST_MODEL]:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with exactly: PONG"}],
                max_tokens=64,
                temperature=0.0,
            )
            print(f"OK  {model}: {resp.choices[0].message.content!r}")
        except Exception as exc:
            print(f"FAIL {model}: {type(exc).__name__}: {str(exc)[:400]}")

    # grok is gated on this account ("Berm is not enabled"), so also probe fallbacks that
    # ARE enabled, to prove the LangChain + tool-calling path end to end.
    candidates = [CHAT_MODEL, INGEST_MODEL, "anthropic.claude-sonnet-5"]
    from langchain_openai import ChatOpenAI
    from langchain_core.tools import tool

    @tool
    def get_case_count(district: str) -> int:
        """Return the number of open cases in a district."""
        return 42

    divider("4. LangChain ChatOpenAI pointed at Mantle (plain)")
    for model in candidates:
        lc = ChatOpenAI(model=model, base_url=MANTLE_BASE_URL, api_key=token,
                        temperature=0.0, max_tokens=64)
        try:
            out = lc.invoke("Reply with exactly: PONG")
            print(f"OK  {model}: content={out.content!r}")
        except Exception as exc:
            print(f"FAIL {model}: {type(exc).__name__}: {str(exc)[:300]}")

    divider("5. LangChain ChatOpenAI tool-calling (the agent relies on bind_tools)")
    for model in candidates:
        lc = ChatOpenAI(model=model, base_url=MANTLE_BASE_URL, api_key=token,
                        temperature=0.0, max_tokens=256)
        try:
            bound = lc.bind_tools([get_case_count])
            out = bound.invoke("How many open cases are in Bengaluru? Use the tool.")
            tcs = getattr(out, "tool_calls", [])
            if tcs:
                print(f"OK  {model}: tool_calls={[(t['name'], t['args']) for t in tcs]}")
            else:
                print(f"WARN {model}: no tool_calls; content={out.content!r}")
        except Exception as exc:
            print(f"FAIL {model}: {type(exc).__name__}: {str(exc)[:300]}")

    divider("6. Contrast: same models via bedrock-runtime Converse (langchain_aws)")
    try:
        from langchain_aws import ChatBedrockConverse
        for model in [CHAT_MODEL, INGEST_MODEL]:
            try:
                cv = ChatBedrockConverse(model=model, region_name=REGION,
                                         temperature=0.0, max_tokens=64)
                out = cv.invoke("Reply with exactly: PONG")
                print(f"OK  {model}: content={out.content!r}")
            except Exception as exc:
                print(f"FAIL {model}: {type(exc).__name__}: {str(exc)[:300]}")
    except Exception as exc:
        print(f"WARN langchain_aws unavailable: {exc!r}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
