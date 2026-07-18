"""Throwaway smoke test: does `catalyst deploy` (CLI) install dependencies AND a
COMPLETE botocore/data tree server-side? Manual zip upload strips botocore/data,
breaking boto3.client("bedrock-runtime"). If CLI deploy installs deps properly, the
plain boto3 + standard langchain_aws paths below succeed and we can drop vendoring +
the SigV4 workaround for the real ingest_processor.

Reports through TWO channels so the result is visible no matter the function type's
response quirks: (1) a printed/logged line BEDROCK_CLITEST_RESULT {json} — read it in
the Catalyst console Logs tab, same as ingest_processor; (2) an HTTP response body if
invoked as a Basic I/O function (just open the function URL)."""
from __future__ import annotations

import json
import logging
import os
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bedrock_clitest")

BUILD = "bedrock-clitest-1"


def _botocore_data_report() -> dict:
    """Filesystem-only check — needs no AWS creds. Directly answers 'is botocore/data
    present and complete at runtime?'. This is the core signal."""
    try:
        import botocore
        data_dir = os.path.join(os.path.dirname(botocore.__file__), "data")
        exists = os.path.isdir(data_dir)
        service_count = len(os.listdir(data_dir)) if exists else 0
        has_bedrock = exists and os.path.isdir(os.path.join(data_dir, "bedrock-runtime"))
        return {
            "botocore_version": getattr(botocore, "__version__", "?"),
            "data_dir_exists": exists,
            "service_dir_count": service_count,  # expect ~400 if complete, 0/low if stripped
            "has_bedrock_runtime_dir": has_bedrock,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _test_boto3_bedrock() -> dict:
    """The exact call that fails on the stripped manual-zip runtime. Fails at
    client() (service-model load) BEFORE credentials matter, so this is meaningful
    even if AWS creds aren't set."""
    try:
        import boto3
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("bedrock-runtime", region_name=region)
        resp = client.invoke_model(
            modelId=os.getenv("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v1"),
            body=json.dumps({"inputText": "cli deploy botocore test"}),
        )
        vec = json.loads(resp["body"].read().decode("utf-8")).get("embedding") or []
        return {"ok": True, "embedding_dim": len(vec)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-600:]}


def _test_langchain_aws() -> dict:
    try:
        from langchain_aws import ChatBedrockConverse
        from langchain_core.messages import HumanMessage
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        llm = ChatBedrockConverse(
            model=os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"),
            region_name=region,
            max_tokens=64,
        )
        out = llm.invoke([HumanMessage(content="Reply with exactly: BEDROCK OK")])
        return {"ok": True, "content": str(out.content)[:120]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-600:]}


def _run() -> dict:
    result = {
        "build": BUILD,
        "botocore_data": _botocore_data_report(),
        "boto3_bedrock_embed": _test_boto3_bedrock(),
        "langchain_aws_llm": _test_langchain_aws(),
    }
    line = "BEDROCK_CLITEST_RESULT " + json.dumps(result)
    print(line, flush=True)
    logger.info(line)
    return result


def handler(request=None, response=None, *args, **kwargs):
    result = _run()
    # Basic I/O: send JSON back if a usable response object was passed.
    if response is not None and hasattr(response, "send"):
        try:
            response.send(json.dumps(result, indent=2))
            return
        except Exception:
            logger.exception("response.send failed; result is in the logs above")
    return {"status": "ok", "result": result}


# Alias in case the runtime looks for `main`.
def main(request=None, response=None, *args, **kwargs):
    return handler(request, response, *args, **kwargs)


if __name__ == "__main__":
    print(json.dumps(_run(), indent=2))
