"""verify_historical_neo4j.py -- durable check that historical data loaded into
Neo4j by load_neo4j_from_pg.py actually connects the cases each demo scenario
depends on, and that the Case->MENTIONS->Account graph shape is really there --
*before* any live document is ever uploaded, since a scenario's live "reveal"
only works if its historical side is already connected.

Note: MENTIONS goes directly CaseMaster->Account/UPIHandle/Device/PhoneNumber,
no Evidence node in between. Confirmed live (by uploading scenario 1's live FIR
and inspecting the resulting graph) that live ingestion never creates an
Evidence node or a HAS_EVIDENCE edge -- its _load_graph/_build_edges
(schema-driven off SchemaRelationship) only ever produces direct
CaseMaster->MENTIONS edges. An earlier version of this script (and of
load_neo4j_from_pg.py) assumed a Case->HAS_EVIDENCE->Evidence->MENTIONS->Account
shape; that shape has no live counterpart and a live/historical pair sharing an
account never actually connected under it -- fixed to match live exactly.

Note: IP addresses (identifier_pool.IP_POOL_04) are deliberately NOT modeled
as their own graph nodes here -- confirmed live that
catalyst_functions/ingest_processor/pipeline/processor.py (live ingestion)
has no IP node type either, so historical data intentionally doesn't invent
one Neo4j wouldn't be able to MERGE against later. Scenario 4's graph
connectivity runs through the shared Device (IMEI) pool instead, which both
sides do model.

Exit code 0 and "ALL CHECKS PASSED" iff every check passes. Read-only
(MATCH-only Cypher, no writes).

Usage:
    python scripts/verify_historical_neo4j.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from data_generation import identifier_pool as pool  # noqa: E402


def _distinct_case_count_via_mentions(session, label: str, display_name: str) -> int:
    result = session.run(
        f"""
        MATCH (c:CaseMaster {{origin: 'historical'}})-[:MENTIONS]->(o:{label} {{display_name: $name}})
        RETURN count(DISTINCT c) AS c
        """,
        name=display_name,
    )
    return result.single()["c"]


def _distinct_case_count_via_txn_bridge(session, hub_account_no: str) -> int:
    # Cases connected to the hub account not by directly mentioning it (it may
    # have no owner/mentions of its own -- e.g. scenario1's AGG_ACC_01), but by
    # mentioning an account that TRANSACTED_WITH the hub.
    result = session.run(
        """
        MATCH (hub:Account {display_name: $hub_no})
        MATCH (hub)-[:TRANSACTED_WITH]-(adjacent:Account)
        MATCH (c:CaseMaster {origin: 'historical'})-[:MENTIONS]->(adjacent)
        RETURN count(DISTINCT c) AS c
        """,
        hub_no=hub_account_no,
    )
    return result.single()["c"]


def main() -> int:
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ["NEO4J_PASSWORD"]),
    )
    failures: list[str] = []

    with driver.session() as session:
        print("[1/5] Case->MENTIONS->Account shape exists (matches live ingestion)")
        result = session.run(
            """
            MATCH (c:CaseMaster {origin: 'historical'})-[:MENTIONS]->(:Account)
            RETURN count(DISTINCT c) AS c
            """
        )
        shape_count = result.single()["c"]
        if shape_count > 0:
            print(f"  OK    {shape_count} historical cases have a direct Case->Account MENTIONS edge")
        else:
            failures.append("no CaseMaster reaches an Account via MENTIONS -- historical graph shape doesn't match live ingestion")

        result = session.run(
            """
            MATCH (c:CaseMaster {origin: 'historical'})-[:HAS_EVIDENCE]->(:InvestigationReport)
            RETURN count(DISTINCT c) AS c
            """
        )
        ir_shape_count = result.single()["c"]
        if ir_shape_count > 0:
            print(f"  OK    {ir_shape_count} historical cases have a Case->HAS_EVIDENCE->InvestigationReport edge")
        else:
            failures.append("no CaseMaster reaches an InvestigationReport via HAS_EVIDENCE")

        print("\n[2/5] Scenario 1 (digital-arrest): AGG_ACC_01 bridges the collection accounts")
        n = _distinct_case_count_via_txn_bridge(session, pool.AGG_ACC_01["account_no"])
        if n >= 3:
            print(f"  OK    {n} historical cases reachable via AGG_ACC_01 transaction bridge")
        else:
            failures.append(f"scenario1: only {n} cases reachable via AGG_ACC_01 bridge, expected >= 3")

        print("\n[3/5] Scenario 2 (many-names): shared UPI/phone connects the alias cases")
        n_upi = _distinct_case_count_via_mentions(session, "UPIHandle", pool.UPI_02)
        n_phone = _distinct_case_count_via_mentions(session, "PhoneNumber", pool.PHONE_02)
        if n_upi >= 2 and n_phone >= 2:
            print(f"  OK    shared UPI connects {n_upi} cases, shared phone connects {n_phone} cases")
        else:
            failures.append(f"scenario2: shared UPI connects {n_upi} cases, shared phone connects {n_phone} cases, expected >= 2 each")

        print("\n[4/5] Scenario 3 (follow-money): BRIDGE_ACC_03 / HUB_ACC_03 reachable")
        n_bridge = _distinct_case_count_via_mentions(session, "Account", pool.BRIDGE_ACC_03["account_no"])
        n_hub = _distinct_case_count_via_txn_bridge(session, pool.HUB_ACC_03["account_no"])
        if n_bridge >= 1 and n_hub >= 1:
            print(f"  OK    bridge account mentioned by {n_bridge} case(s), hub reachable from {n_hub} case(s) via transaction adjacency")
        else:
            failures.append(f"scenario3: bridge mentioned by {n_bridge} case(s), hub reachable from {n_hub} case(s), expected >= 1 each")

        print("\n[5/5] Scenario 4 (surge): shared device (IMEI) pool connects burst cases")
        device_counts = {imei: _distinct_case_count_via_mentions(session, "Device", imei) for imei in pool.DEV_POOL_04}
        multi_case_devices = {imei: c for imei, c in device_counts.items() if c >= 2}
        if multi_case_devices:
            print(f"  OK    {len(multi_case_devices)}/{len(pool.DEV_POOL_04)} pooled IMEIs connect 2+ cases each: {multi_case_devices}")
        else:
            failures.append(f"scenario4: no pooled IMEI connects 2+ cases (counts: {device_counts})")

    driver.close()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s) failed.")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
