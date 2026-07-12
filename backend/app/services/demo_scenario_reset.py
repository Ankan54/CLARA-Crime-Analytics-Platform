"""Fenced, idempotent prepare/reset saga for demo scenarios.

Cleanup order:
1. Snapshot old artifacts
2. Fence old jobs via generation increment
3. Delete Pinecone vectors
4. Delete Neo4j nodes/relationships for this scenario's runs
5. Delete Stratus objects
6. Delete Postgres rows in FK order
7. Mark scenario READY
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..demo_scenarios import SCENARIO_ALLOWLIST, get_crime_no

logger = logging.getLogger(__name__)


class ResetError(Exception):
    pass


def _ensure_scenario_state(db: Session, scenario_key: str) -> dict:
    """Lazily create the DemoScenarioState row if missing."""
    row = db.execute(
        text("SELECT * FROM DemoScenarioState WHERE scenario_key = :key"),
        {"key": scenario_key},
    ).mappings().first()
    if row:
        return dict(row)

    crime_no = get_crime_no(scenario_key)
    db.execute(
        text(
            """
            INSERT INTO DemoScenarioState (scenario_key, crime_no, generation, lifecycle_state, created_at, updated_at)
            VALUES (:key, :crime_no, 0, 'IDLE', NOW(), NOW())
            ON CONFLICT (scenario_key) DO NOTHING
            """
        ),
        {"key": scenario_key, "crime_no": crime_no},
    )
    db.flush()
    row = db.execute(
        text("SELECT * FROM DemoScenarioState WHERE scenario_key = :key"),
        {"key": scenario_key},
    ).mappings().first()
    return dict(row)


def _acquire_advisory_lock(db: Session, scenario_key: str) -> None:
    """Acquire a Postgres advisory lock keyed on the scenario."""
    lock_id = hash(scenario_key) & 0x7FFFFFFF
    db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})


def prepare_scenario(db: Session, scenario_key: str, idempotency_key: str) -> dict:
    """Main entry point: increment generation, run cleanup saga, return token."""
    if scenario_key not in SCENARIO_ALLOWLIST:
        raise ResetError(f"Unknown scenario: {scenario_key}")

    _acquire_advisory_lock(db, scenario_key)
    state = _ensure_scenario_state(db, scenario_key)
    crime_no = state["crime_no"]

    # Check for existing operation with this idempotency key
    existing_op = db.execute(
        text(
            "SELECT operation_id, generation, status FROM DemoResetOperation "
            "WHERE scenario_key = :key AND idempotency_key = :ikey"
        ),
        {"key": scenario_key, "ikey": idempotency_key},
    ).mappings().first()

    if existing_op:
        if existing_op["status"] == "COMPLETED":
            return {
                "scenario_key": scenario_key,
                "generation": existing_op["generation"],
                "reset_token": str(existing_op["operation_id"]),
                "status": "COMPLETED",
            }
        # Failed — allow retry by falling through

    # Increment generation
    new_generation = state["generation"] + 1
    operation_id = str(uuid.uuid4())

    db.execute(
        text(
            """
            UPDATE DemoScenarioState
            SET generation = :gen, lifecycle_state = 'RESETTING',
                active_operation_id = :op_id, error_message = NULL, updated_at = NOW()
            WHERE scenario_key = :key
            """
        ),
        {"gen": new_generation, "op_id": operation_id, "key": scenario_key},
    )

    # Build cleanup plan: snapshot what needs deleting
    cleanup_plan = _build_cleanup_plan(db, scenario_key, crime_no)

    # Insert or update reset operation
    db.execute(
        text(
            """
            INSERT INTO DemoResetOperation
                (operation_id, scenario_key, idempotency_key, generation, cleanup_plan, status, created_at)
            VALUES (:op_id, :key, :ikey, :gen, :plan::jsonb, 'RUNNING', NOW())
            ON CONFLICT (scenario_key, idempotency_key)
            DO UPDATE SET operation_id = :op_id, generation = :gen,
                          cleanup_plan = :plan::jsonb, status = 'RUNNING',
                          error_message = NULL, created_at = NOW(), completed_at = NULL
            """
        ),
        {
            "op_id": operation_id,
            "key": scenario_key,
            "ikey": idempotency_key,
            "gen": new_generation,
            "plan": _json_dumps(cleanup_plan),
        },
    )
    db.flush()

    # Execute the cleanup saga
    try:
        _execute_cleanup(db, operation_id, scenario_key, crime_no, cleanup_plan)
    except Exception as exc:
        logger.exception("Reset saga failed scenario=%s op=%s", scenario_key, operation_id)
        db.execute(
            text(
                """
                UPDATE DemoResetOperation SET status = 'FAILED', error_message = :err, completed_at = NOW()
                WHERE operation_id = :op_id
                """
            ),
            {"err": str(exc)[:1000], "op_id": operation_id},
        )
        db.execute(
            text(
                """
                UPDATE DemoScenarioState SET lifecycle_state = 'RESET_FAILED', error_message = :err, updated_at = NOW()
                WHERE scenario_key = :key
                """
            ),
            {"err": str(exc)[:500], "key": scenario_key},
        )
        db.commit()
        raise ResetError(f"Reset failed: {exc}") from exc

    # Mark complete
    db.execute(
        text("UPDATE DemoResetOperation SET status = 'COMPLETED', completed_at = NOW() WHERE operation_id = :op_id"),
        {"op_id": operation_id},
    )
    db.execute(
        text(
            "UPDATE DemoScenarioState SET lifecycle_state = 'READY', error_message = NULL, updated_at = NOW() "
            "WHERE scenario_key = :key"
        ),
        {"key": scenario_key},
    )
    db.commit()

    return {
        "scenario_key": scenario_key,
        "generation": new_generation,
        "reset_token": operation_id,
        "status": "COMPLETED",
    }


def _build_cleanup_plan(db: Session, scenario_key: str, crime_no: str) -> dict:
    """Snapshot IDs that need cleanup."""
    # Find case IDs by crime_no
    case_ids = [
        row["CaseMasterID"]
        for row in db.execute(
            text("SELECT CaseMasterID FROM CaseMaster WHERE CrimeNo = :cno"),
            {"cno": crime_no},
        ).mappings().all()
    ]

    # Find batches and runs for these cases
    batch_ids = []
    run_ids = []
    if case_ids:
        batches = db.execute(
            text("SELECT batch_id FROM BatchUpload WHERE case_id = ANY(:ids) OR scenario_key = :skey"),
            {"ids": case_ids, "skey": scenario_key},
        ).mappings().all()
        batch_ids = [str(b["batch_id"]) for b in batches]

        runs = db.execute(
            text("SELECT run_id FROM PipelineRun WHERE case_id = ANY(:ids) OR scenario_key = :skey"),
            {"ids": case_ids, "skey": scenario_key},
        ).mappings().all()
        run_ids = [r["run_id"] for r in runs]
    else:
        # No cases yet — check by scenario_key
        batches = db.execute(
            text("SELECT batch_id FROM BatchUpload WHERE scenario_key = :skey"),
            {"skey": scenario_key},
        ).mappings().all()
        batch_ids = [str(b["batch_id"]) for b in batches]

        runs = db.execute(
            text("SELECT run_id FROM PipelineRun WHERE scenario_key = :skey"),
            {"skey": scenario_key},
        ).mappings().all()
        run_ids = [r["run_id"] for r in runs]

    # Stratus prefixes to delete
    stratus_prefixes = []
    for bid in batch_ids:
        stratus_prefixes.append(f"raw/{bid}/")
    for cid in case_ids:
        for rid in run_ids:
            stratus_prefixes.append(f"processed/{cid}/{rid}/")
            stratus_prefixes.append(f"archive/{cid}/{rid}/")

    # Artifact keys from IngestArtifact
    artifact_rows = db.execute(
        text(
            "SELECT store, artifact_key, artifact_type FROM IngestArtifact "
            "WHERE scenario_key = :skey OR run_id = ANY(:rids)"
        ),
        {"skey": scenario_key, "rids": run_ids if run_ids else ["__none__"]},
    ).mappings().all()

    pinecone_ids = [a["artifact_key"] for a in artifact_rows if a["store"] == "pinecone"]
    neo4j_keys = [a["artifact_key"] for a in artifact_rows if a["store"] == "neo4j"]

    return {
        "case_ids": case_ids,
        "batch_ids": batch_ids,
        "run_ids": run_ids,
        "stratus_prefixes": stratus_prefixes,
        "pinecone_ids": pinecone_ids,
        "neo4j_keys": neo4j_keys,
        "crime_no": crime_no,
    }


def _execute_cleanup(db: Session, operation_id: str, scenario_key: str, crime_no: str, plan: dict) -> None:
    """Run the cleanup saga across all stores."""
    case_ids = plan.get("case_ids", [])
    batch_ids = plan.get("batch_ids", [])
    run_ids = plan.get("run_ids", [])
    stratus_prefixes = plan.get("stratus_prefixes", [])
    pinecone_ids = plan.get("pinecone_ids", [])

    # 1. Pinecone cleanup (best-effort, log failures)
    pinecone_count = _cleanup_pinecone(pinecone_ids, run_ids)
    db.execute(
        text("UPDATE DemoResetOperation SET pinecone_status = 'DONE', pinecone_deleted = :c WHERE operation_id = :op"),
        {"c": pinecone_count, "op": operation_id},
    )
    db.flush()

    # 2. Neo4j cleanup (best-effort)
    neo4j_count = _cleanup_neo4j(case_ids, run_ids)
    db.execute(
        text("UPDATE DemoResetOperation SET neo4j_status = 'DONE', neo4j_deleted = :c WHERE operation_id = :op"),
        {"c": neo4j_count, "op": operation_id},
    )
    db.flush()

    # 3. Stratus cleanup
    stratus_count = _cleanup_stratus(stratus_prefixes)
    db.execute(
        text("UPDATE DemoResetOperation SET stratus_status = 'DONE', stratus_deleted = :c WHERE operation_id = :op"),
        {"c": stratus_count, "op": operation_id},
    )
    db.flush()

    # 4. Postgres cleanup (FK-ordered, single transaction)
    pg_count = _cleanup_postgres(db, case_ids, batch_ids, run_ids, scenario_key)
    db.execute(
        text("UPDATE DemoResetOperation SET postgres_status = 'DONE', postgres_deleted = :c WHERE operation_id = :op"),
        {"c": pg_count, "op": operation_id},
    )
    db.flush()


def _cleanup_pinecone(pinecone_ids: list[str], run_ids: list[str]) -> int:
    """Delete vectors from Pinecone. Returns count deleted."""
    import os
    import requests

    api_key = os.environ.get("PINECONE_API_KEY", "")
    index_host = os.environ.get("PINECONE_INDEX_HOST", "")
    if not api_key or not index_host:
        logger.debug("Pinecone not configured, skipping vector cleanup")
        return 0

    headers = {"Api-Key": api_key, "Content-Type": "application/json"}
    deleted = 0

    if pinecone_ids:
        for i in range(0, len(pinecone_ids), 100):
            batch = pinecone_ids[i : i + 100]
            try:
                resp = requests.post(
                    f"{index_host}/vectors/delete",
                    headers=headers,
                    json={"ids": batch},
                    timeout=30,
                )
                if resp.ok:
                    deleted += len(batch)
            except Exception:
                logger.warning("Pinecone batch delete failed batch_size=%d", len(batch), exc_info=True)

    for rid in run_ids:
        try:
            resp = requests.post(
                f"{index_host}/vectors/delete",
                headers=headers,
                json={"filter": {"run_id": {"$eq": rid}}},
                timeout=30,
            )
            if resp.ok:
                deleted += 1
        except Exception:
            logger.warning("Pinecone filter delete failed run_id=%s", rid, exc_info=True)

    return deleted


def _cleanup_neo4j(case_ids: list[int], run_ids: list[str]) -> int:
    """Delete Neo4j nodes/relationships for these cases."""
    import os

    neo4j_uri = os.environ.get("NEO4J_URI", "")
    neo4j_user = os.environ.get("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "")

    if not neo4j_uri:
        logger.debug("Neo4j not configured, skipping")
        return 0

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        deleted = 0
        with driver.session() as session:
            if case_ids:
                result = session.run(
                    "MATCH (n) WHERE n.case_id IN $case_ids DETACH DELETE n RETURN count(n) AS cnt",
                    case_ids=[str(c) for c in case_ids],
                )
                deleted += result.single()["cnt"]
            for rid in run_ids:
                result = session.run(
                    "MATCH (n) WHERE n.source_run_id = $rid DETACH DELETE n RETURN count(n) AS cnt",
                    rid=rid,
                )
                deleted += result.single()["cnt"]
        driver.close()
        return deleted
    except Exception:
        logger.warning("Neo4j cleanup failed", exc_info=True)
        return 0


def _cleanup_stratus(prefixes: list[str]) -> int:
    """Delete all objects under the given Stratus prefixes."""
    if not prefixes:
        return 0

    try:
        from ..services.catalyst_queue import _init_app
        from ..config import settings

        app = _init_app()
        bucket = app.stratus().bucket(settings.zoho_stratus_bucket)
        deleted = 0

        for prefix in prefixes:
            try:
                next_token = None
                while True:
                    page = bucket.list_paged_objects(prefix=prefix, next_token=next_token)
                    for obj in page.get("contents", []):
                        key = obj.to_dict().get("key") if hasattr(obj, "to_dict") else obj.get("key")
                        if key:
                            try:
                                bucket.delete_object(key)
                                deleted += 1
                            except Exception:
                                logger.debug("Stratus delete failed key=%s (not found is OK)", key)
                                deleted += 1  # not-found counts as success
                    if not page.get("truncated"):
                        break
                    next_token = page.get("next_continuation_token")
            except Exception:
                logger.warning("Stratus prefix cleanup failed prefix=%s", prefix, exc_info=True)

        return deleted
    except Exception:
        logger.warning("Stratus cleanup failed entirely", exc_info=True)
        return 0


def _cleanup_postgres(db: Session, case_ids: list[int], batch_ids: list[str], run_ids: list[str], scenario_key: str) -> int:
    """Delete Postgres rows in FK order. Returns total rows deleted."""
    deleted = 0

    if run_ids:
        # IngestFileLoad
        r = db.execute(text("DELETE FROM IngestFileLoad WHERE run_id = ANY(:rids)"), {"rids": run_ids})
        deleted += r.rowcount
        # IngestArtifact
        r = db.execute(text("DELETE FROM IngestArtifact WHERE run_id = ANY(:rids)"), {"rids": run_ids})
        deleted += r.rowcount
        # ReviewQueueItem
        r = db.execute(text("DELETE FROM ReviewQueueItem WHERE source_run_id = ANY(:rids)"), {"rids": run_ids})
        deleted += r.rowcount
        # PipelineRun
        r = db.execute(text("DELETE FROM PipelineRun WHERE run_id = ANY(:rids)"), {"rids": run_ids})
        deleted += r.rowcount

    if batch_ids:
        r = db.execute(text("DELETE FROM BatchUpload WHERE batch_id = ANY(:bids::uuid[])"), {"bids": batch_ids})
        deleted += r.rowcount

    if case_ids:
        # Evidence, InvestigationReport, then entities referencing the case
        r = db.execute(text("DELETE FROM Evidence WHERE case_id = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        r = db.execute(text("DELETE FROM InvestigationReport WHERE case_id = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount

        # POLE tables (Account, UPIHandle, PhoneNumber, Device, Transaction) reference case
        for table in ("Transaction", "Account", "UPIHandle", "PhoneNumber", "Device"):
            try:
                r = db.execute(text(f"DELETE FROM {table} WHERE case_id = ANY(:ids)"), {"ids": case_ids})
                deleted += r.rowcount
            except Exception:
                logger.debug("Table %s cleanup skipped (may not exist or no case_id column)", table)

        # Accused references case
        try:
            r = db.execute(text("DELETE FROM Accused WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
            deleted += r.rowcount
        except Exception:
            pass

        # EntityMap: delete only entities owned solely by these cases
        try:
            r = db.execute(
                text(
                    "DELETE FROM EntityMap WHERE entity_uid IN ("
                    "  SELECT entity_uid FROM IngestArtifact "
                    "  WHERE scenario_key = :skey AND entity_uid IS NOT NULL AND is_owner = TRUE"
                    ")"
                ),
                {"skey": scenario_key},
            )
            deleted += r.rowcount
        except Exception:
            logger.debug("EntityMap cleanup skipped", exc_info=True)

        # CaseMaster last
        r = db.execute(text("DELETE FROM CaseMaster WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount

    # Cleanup DemoResetOperation history (keep last 3)
    db.execute(
        text(
            "DELETE FROM DemoResetOperation WHERE scenario_key = :key "
            "AND operation_id NOT IN ("
            "  SELECT operation_id FROM DemoResetOperation "
            "  WHERE scenario_key = :key ORDER BY created_at DESC LIMIT 3"
            ")"
        ),
        {"key": scenario_key},
    )

    return deleted


def _json_dumps(obj: dict) -> str:
    import json
    return json.dumps(obj, default=str)
