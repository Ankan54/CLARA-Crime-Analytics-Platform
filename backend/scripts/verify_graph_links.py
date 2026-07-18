"""verify_graph_links.py -- post-reload check of the live stores.

Run AFTER the three loaders, as a set:
    python backend/migrations/migrate_sqlite_to_pg.py --target-db ksp_crime
    python backend/migrations/load_neo4j_from_pg.py
    python backend/migrations/load_pinecone_from_historical.py
    python backend/scripts/verify_graph_links.py

Needs Postgres + Neo4j (no LLM). Checks the things the demo actually stands on, each of
which was silently broken before and produced "no links found" rather than an error:

  * historical TRANSACTED_WITH edges carry amount/timestamp (they were bare arrows)
  * Person-[:OWNS]->(:Device) exists (scenario 2's alias collapse walks it)
  * IP and Wallet are nodes at all (scenarios 4 and 3)
  * the crypto cash-out hop reaches a :Wallet (scenario 3's endpoint)
  * the marquee join: one object mentioned by several cases
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

failures: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)


def main() -> int:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ["NEO4J_PASSWORD"]),
    )

    def q(cypher: str, **params):
        with driver.session() as s:
            return [dict(r) for r in s.run(cypher, **params)]

    print("Node counts by label")
    labels = q("""
        MATCH (n) UNWIND labels(n) AS label
        RETURN label, count(*) AS n ORDER BY n DESC
    """)
    for row in labels:
        print(f"    {row['label']:<22} {row['n']}")
    present = {row["label"] for row in labels}
    check("core labels loaded", {"CaseMaster", "Account"} <= present,
          f"{len(present)} labels present")
    # Gap 3: these were absent entirely -- no EntityMap rows meant no entity_uid to key on.
    check("IP nodes exist (scenario 4)", "IP" in present, f"IP present={('IP' in present)}")
    check("Wallet nodes exist (scenario 3)", "Wallet" in present, f"Wallet present={('Wallet' in present)}")

    print("\nMoney edges")
    # Gap 1: the historical loader wrote from/to only, so every temporal money question
    # was unanswerable in Cypher.
    rows = q("""
        MATCH ()-[r:TRANSACTED_WITH]->()
        RETURN count(r) AS total,
               count(r.amount) AS with_amount,
               count(r.txn_timestamp) AS with_ts
    """)[0]
    check("TRANSACTED_WITH edges exist", rows["total"] > 0, f"{rows['total']} edges")
    check("every money edge carries amount", rows["with_amount"] == rows["total"],
          f"{rows['with_amount']}/{rows['total']}")
    check("every money edge carries a timestamp", rows["with_ts"] == rows["total"],
          f"{rows['with_ts']}/{rows['total']}")

    # Gap 5: the wallet counterparty was dropped (to_account_id NULL), so the trail
    # dead-ended at the mules instead of leaving the banking system.
    crypto = q("MATCH (:Account)-[r:TRANSACTED_WITH]->(w:Wallet) RETURN count(r) AS n")
    check("crypto cash-out reaches a Wallet", crypto and crypto[0]["n"] > 0,
          f"{crypto[0]['n'] if crypto else 0} account->wallet edges")

    print("\nOwnership edges")
    # Gap 2: Device was missing from the OWNS loop AND had no holder column at all.
    owns = q("""
        MATCH (p)-[:OWNS]->(o) UNWIND labels(o) AS label
        RETURN label, count(*) AS n ORDER BY n DESC
    """)
    for row in owns:
        print(f"    OWNS -> {row['label']:<16} {row['n']}")
    owned = {row["label"] for row in owns}
    check("Person -> Device OWNS exists (scenario 2)", "Device" in owned,
          "alias collapse walks this edge")

    print("\nMarquee: one object, many cases")
    shared = q("""
        MATCH (c:CaseMaster)-[:MENTIONS]->(o)<-[:MENTIONS]-(c2:CaseMaster)
        WHERE c.case_id < c2.case_id
        WITH o, count(DISTINCT c.case_id) + count(DISTINCT c2.case_id) AS cases
        RETURN o.display_name AS name, labels(o) AS labels, cases
        ORDER BY cases DESC LIMIT 5
    """)
    for row in shared:
        kind = next((l for l in row["labels"] if l != "Object"), "?")
        print(f"    {kind:<12} {str(row['name'])[:34]:<34} shared across {row['cases']} cases")
    check("an object links 2+ cases", bool(shared),
          f"top object spans {shared[0]['cases'] if shared else 0} cases")

    print("\nOrigins (reset safety)")
    origins = q("MATCH (n) RETURN coalesce(n.origin,'(unset)') AS origin, count(*) AS n ORDER BY n DESC")
    for row in origins:
        print(f"    {row['origin']:<14} {row['n']}")
    # Gap 4: live ingestion used to overwrite origin='demo' onto shared historical nodes,
    # so reset_demo_data.py deleted the planted account and the demo stopped finding its
    # own links on the second run.
    check("historical nodes are tagged 'historical'",
          any(o["origin"] == "historical" and o["n"] > 0 for o in origins),
          "reset scopes on this tag")

    driver.close()
    print()
    if failures:
        print(f"FAILED ({len(failures)}): {', '.join(failures)}")
        return 1
    print("All graph link checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
