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

from sqlalchemy import bindparam, text
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
            VALUES (:op_id, :key, :ikey, :gen, CAST(:plan AS jsonb), 'RUNNING', NOW())
            ON CONFLICT (scenario_key, idempotency_key)
            DO UPDATE SET operation_id = :op_id, generation = :gen,
                          cleanup_plan = CAST(:plan AS jsonb), status = 'RUNNING',
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
        db.rollback()
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
        row["casemasterid"]
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
    """Delete vectors from Pinecone. Returns count deleted.

    This previously used a raw REST call gated on PINECONE_INDEX_HOST, an env
    var nothing else in the codebase sets (_load_vector uses the pinecone SDK
    with PINECONE_INDEX, an index *name*) -- so this silently no-op'd on every
    reset (confirmed live: pinecone_deleted=0 across every DemoResetOperation).
    It also filtered by metadata (`filter: {"run_id": ...}`), which Pinecone
    serverless indexes don't support for delete at all -- would never have
    worked even with the host configured. Fixed to use the SDK like the rest
    of the codebase, and to enumerate ids via index.list(prefix=...) (chunk
    ids are deterministically "demo::{run_id}::{filename}::{chunk_index}",
    confirmed live) since serverless only supports delete-by-id.
    """
    import os

    api_key = os.environ.get("PINECONE_API_KEY", "")
    if not api_key:
        logger.debug("Pinecone not configured, skipping vector cleanup")
        return 0

    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=api_key)
        index = pc.Index(os.environ.get("PINECONE_INDEX", "ksp-crime-intel"))
    except Exception:
        logger.warning("Pinecone cleanup: could not init client", exc_info=True)
        return 0

    deleted = 0

    if pinecone_ids:
        try:
            index.delete(ids=list(pinecone_ids))
            deleted += len(pinecone_ids)
        except Exception:
            logger.warning("Pinecone delete-by-id failed count=%d", len(pinecone_ids), exc_info=True)

    for rid in run_ids:
        try:
            ids = [item.id for page in index.list(prefix=f"demo::{rid}::") for item in page.vectors]
            if ids:
                index.delete(ids=ids)
                deleted += len(ids)
        except Exception:
            logger.warning("Pinecone list/delete failed run_id=%s", rid, exc_info=True)

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
            # origin='demo' guard is load-bearing: _load_graph stamps the demo run_id
            # (and, for new nodes, case_id) onto shared *historical* identifier nodes it
            # merely MERGEs onto — but keeps origin='historical' via coalesce. Deleting
            # by case_id/run_id ALONE therefore DETACH-deletes those planted historical
            # nodes and severs their OWNS edges to the historical aliases, so the
            # live→historical fusion breaks on the *next* demo run (confirmed live: scn2's
            # 4-alias collapse regressed to 1 on the 2nd reset+ingest cycle). Scoping the
            # delete to origin='demo' preserves shared historical nodes, matching
            # reset_demo_data.py's `MATCH (n {origin:'demo'})` approach.
            if case_ids:
                # _load_graph stamps n.case_id as an integer (RunParams.case_id: int) —
                # matching against strings here would silently match nothing.
                result = session.run(
                    "MATCH (n) WHERE n.case_id IN $case_ids AND n.origin = 'demo' "
                    "DETACH DELETE n RETURN count(n) AS cnt",
                    case_ids=[int(c) for c in case_ids],
                )
                deleted += result.single()["cnt"]
            for rid in run_ids:
                # _load_graph stamps the property as n.run_id, not n.source_run_id.
                result = session.run(
                    "MATCH (n) WHERE n.run_id = $rid AND n.origin = 'demo' "
                    "DETACH DELETE n RETURN count(n) AS cnt",
                    rid=rid,
                )
                deleted += result.single()["cnt"]
            # Demo edges between two *historical* nodes are never reached by node deletion
            # (both endpoints survive). They carry the demo run_id, so remove them here.
            for rid in run_ids:
                session.run("MATCH ()-[r]->() WHERE r.run_id = $rid DELETE r", rid=rid)
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
    """Delete Postgres rows in FK order. Returns total rows deleted.

    Account/UPIHandle/PhoneNumber/Device are a deduplicated identifier pool that is
    deliberately shared between historical (pre-loaded) and live cases (see
    data_generation README "shared entity pool" + migrate_sqlite_to_pg.py, which loads
    historical identifiers into these same tables) — a scenario reset must never delete
    rows from them, only detach this case's evidence-provenance pointer.
    """
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
        r = db.execute(
            text("DELETE FROM BatchUpload WHERE batch_id IN :bids").bindparams(bindparam("bids", expanding=True)),
            {"bids": batch_ids},
        )
        deleted += r.rowcount

    if case_ids:
        evidence_ids = [
            int(row["evidence_id"])
            for row in db.execute(text("SELECT evidence_id FROM Evidence WHERE case_id = ANY(:ids)"), {"ids": case_ids}).mappings().all()
        ]
        accused_ids = [
            int(row["accusedmasterid"])
            for row in db.execute(text("SELECT AccusedMasterID FROM Accused WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids}).mappings().all()
        ]
        victim_ids = [
            int(row["victimmasterid"])
            for row in db.execute(text("SELECT VictimMasterID FROM Victim WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids}).mappings().all()
        ]
        complainant_ids = [
            int(row["complainantid"])
            for row in db.execute(text("SELECT ComplainantID FROM ComplainantDetails WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids}).mappings().all()
        ]
        report_ids = [
            int(row["report_id"])
            for row in db.execute(text("SELECT report_id FROM InvestigationReport WHERE case_id = ANY(:ids)"), {"ids": case_ids}).mappings().all()
        ]

        # Transaction rows are always freshly inserted per case (never deduped), so they're
        # safe to hard-delete. They're the only thing still pointing at this case's Evidence
        # via source_evidence_id, so they must go before Evidence.
        if evidence_ids:
            r = db.execute(text("DELETE FROM Transaction WHERE source_evidence_id = ANY(:eids)"), {"eids": evidence_ids})
            deleted += r.rowcount

            # Detach (never delete) the shared identifier pool's provenance pointer so the
            # Evidence row can be removed without an FK violation.
            for table in ("Account", "UPIHandle", "PhoneNumber", "Device"):
                db.execute(
                    text(f"UPDATE {table} SET source_evidence_id = NULL WHERE source_evidence_id = ANY(:eids)"),
                    {"eids": evidence_ids},
                )

        # _write_object_row also stamps Account.linked_case_id (RESTRICT -> CaseMaster) the
        # first time a case references that account; clear it too or CaseMaster delete fails.
        db.execute(text("UPDATE Account SET linked_case_id = NULL WHERE linked_case_id = ANY(:ids)"), {"ids": case_ids})

        # InvestigationReport and ActSectionAssociation reference CaseMaster directly.
        r = db.execute(text("DELETE FROM InvestigationReport WHERE case_id = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        r = db.execute(text("DELETE FROM ActSectionAssociation WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        r = db.execute(text("DELETE FROM ChargesheetDetails WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        r = db.execute(text("DELETE FROM ArrestSurrender WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount

        # Historical extension tables are seeded too; scope deletes to this demo case set
        # and person ids before deleting parent rows.
        for table in ("EXT_Uses", "EXT_Mentions", "EXT_SubEvent"):
            r = db.execute(text(f"DELETE FROM {table} WHERE source_caseid = ANY(:ids)"), {"ids": case_ids})
            deleted += r.rowcount
        r = db.execute(text("DELETE FROM EXT_Mentions WHERE case_master_id = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        r = db.execute(text("DELETE FROM EXT_CaseGeo WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        if accused_ids:
            r = db.execute(text("DELETE FROM EXT_AccusedDetail WHERE AccusedMasterID = ANY(:aids)"), {"aids": accused_ids})
            deleted += r.rowcount
            r = db.execute(text("DELETE FROM EXT_AccusedIn WHERE AccusedMasterID = ANY(:aids) OR CaseMasterID = ANY(:ids) OR source_caseid = ANY(:ids)"), {"aids": accused_ids, "ids": case_ids})
            deleted += r.rowcount
        else:
            r = db.execute(text("DELETE FROM EXT_AccusedIn WHERE CaseMasterID = ANY(:ids) OR source_caseid = ANY(:ids)"), {"ids": case_ids})
            deleted += r.rowcount
        if victim_ids:
            r = db.execute(text("DELETE FROM EXT_VictimDetail WHERE VictimMasterID = ANY(:vids)"), {"vids": victim_ids})
            deleted += r.rowcount
        if complainant_ids:
            r = db.execute(text("DELETE FROM EXT_ComplainantIn WHERE ComplainantID = ANY(:cids) OR CaseMasterID = ANY(:ids) OR source_caseid = ANY(:ids)"), {"cids": complainant_ids, "ids": case_ids})
            deleted += r.rowcount
        else:
            r = db.execute(text("DELETE FROM EXT_ComplainantIn WHERE CaseMasterID = ANY(:ids) OR source_caseid = ANY(:ids)"), {"ids": case_ids})
            deleted += r.rowcount

        # Person rows (Accused/Victim/ComplainantDetails) reference CaseMaster too.
        r = db.execute(text("DELETE FROM Accused WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        r = db.execute(text("DELETE FROM Victim WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount
        r = db.execute(text("DELETE FROM ComplainantDetails WHERE CaseMasterID = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount

        # Evidence now has nothing left pointing at it.
        r = db.execute(text("DELETE FROM Evidence WHERE case_id = ANY(:ids)"), {"ids": case_ids})
        deleted += r.rowcount

        # EntityMap: clean up only this case's own Case/Person/Evidence/IR entities — never
        # the shared Object pool (Account/UPIHandle/PhoneNumber/Device), matching leaving
        # those rows intact above.
        entity_scopes = [
            ("CaseMaster", [str(c) for c in case_ids]),
            ("Accused", [str(a) for a in accused_ids]),
            ("Victim", [str(v) for v in victim_ids]),
            ("ComplainantDetails", [str(c) for c in complainant_ids]),
            ("Evidence", [str(e) for e in evidence_ids]),
            ("InvestigationReport", [str(r_id) for r_id in report_ids]),
        ]
        for sql_table, pks in entity_scopes:
            if not pks:
                continue
            r = db.execute(
                text("DELETE FROM EntityMap WHERE sql_table = :table AND sql_pk = ANY(:pks)"),
                {"table": sql_table, "pks": pks},
            )
            deleted += r.rowcount

        # CaseMaster last — everything referencing it is now gone.
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
