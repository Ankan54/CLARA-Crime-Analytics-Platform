"""Read-only clients for the assistant's three stores.

All three are synchronous, which is why every caller runs inside asyncio.to_thread.
Clients are cached module-level: the Neo4j driver and Pinecone index own connection
pools that are expensive to rebuild per tool call, and boto3 client construction is
slow enough to notice on a streaming answer.

Neo4j/Pinecone/AWS config is read from os.environ rather than settings, matching every
other call site in the repo (demo_scenario_reset.py, processor.py, the loaders) --
settings has no fields for them.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Titan v1 emits 1536-d vectors; the Pinecone index was created out-of-band to match.
# Changing the model without reindexing silently breaks similarity search.
EMBED_DIM = 1536


@lru_cache(maxsize=1)
def neo4j_driver():
    from neo4j import GraphDatabase

    uri = os.environ["NEO4J_URI"]
    driver = GraphDatabase.driver(
        uri,
        auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ["NEO4J_PASSWORD"]),
    )
    logger.info("assistant: neo4j driver ready uri=%s", uri)
    return driver


@lru_cache(maxsize=1)
def pinecone_index():
    from pinecone import Pinecone

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    name = os.environ.get("PINECONE_INDEX", "ksp-crime-intel")
    logger.info("assistant: pinecone index ready name=%s", name)
    return pc.Index(name)


@lru_cache(maxsize=1)
def _bedrock_runtime():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("bedrock-runtime", region_name=region)


def embed(text: str) -> list[float]:
    """Embed a query with the same Titan model the corpus was indexed with.

    Mirrors load_pinecone_from_historical.py::_embed -- query and document vectors must
    come from the same model or cosine similarity is meaningless.
    """
    model = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v1")
    response = _bedrock_runtime().invoke_model(
        modelId=model,
        body=json.dumps({"inputText": text[:40000]}),
    )
    return json.loads(response["body"].read())["embedding"]


def run_cypher(cypher: str, **params: Any) -> list[dict[str, Any]]:
    """Run a query in a READ transaction and materialize the rows.

    execute_read is a real guarantee, not a hint: Neo4j rejects any write clause inside a
    read transaction (ForbiddenDueToTransactionType), so an LLM-authored Cypher string
    that slips a MERGE past the keyword check still cannot mutate the graph. Every
    assistant graph query goes through here for that reason.

    Records are materialized inside the session -- a neo4j Record is bound to its session
    and raises once it closes, so returning a lazy result would fail at the call site.
    """
    with neo4j_driver().session() as session:
        return session.execute_read(
            lambda tx: [dict(record) for record in tx.run(cypher, **params)]
        )
