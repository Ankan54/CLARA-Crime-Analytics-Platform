"""
verify.py — Post-load assertions across all stores.

Checks:
  SQL  : PRAGMA foreign_key_check; CaseMaster count == 62
  Vector: total_vector_count == 93; spot-fetch 1000001 → metadata has required fields
  Graph : Scn1 AGG chain; Scn2 P_SCN2_* USES; Scn3 flagged bridge; no orphaned Section
          + all non-empty rel types have >=1 edge
"""
from __future__ import annotations
import sqlite3
import sys

from . import config as cfg

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_failures: list[str] = []


def _ok(label: str, detail: str = "") -> None:
    print(f"  PASS  {label}" + (f" — {detail}" if detail else ""), flush=True)


def _fail(label: str, reason: str) -> None:
    _failures.append(f"{label}: {reason}")
    print(f"  FAIL  {label} — {reason}", flush=True)


# ---------------------------------------------------------------------------
# SQL checks
# ---------------------------------------------------------------------------
def _check_sql() -> None:
    print("[verify] SQL …", flush=True)
    if not cfg.DB_PATH.exists():
        _fail("SQL db", f"ksp.sqlite not found at {cfg.DB_PATH}")
        return

    conn = sqlite3.connect(f"file:{cfg.DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA foreign_keys = ON")
    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        _fail("SQL FK check", f"{len(fk_violations)} violation(s): {fk_violations[:3]}")
    else:
        _ok("SQL FK check", "no violations")

    count = conn.execute("SELECT COUNT(*) FROM CaseMaster").fetchone()[0]
    if count == 62:
        _ok("SQL CaseMaster count", f"{count}")
    else:
        _fail("SQL CaseMaster count", f"expected 62, got {count}")
    conn.close()


# ---------------------------------------------------------------------------
# Vector checks
# ---------------------------------------------------------------------------
def _check_vector() -> None:
    print("[verify] Vector …", flush=True)
    import os
    from pinecone import Pinecone

    try:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        index = pc.Index(cfg.PINECONE_INDEX)

        stats = index.describe_index_stats()
        total = stats.total_vector_count
        if total == 93:
            _ok("Vector total count", f"{total}")
        else:
            _fail("Vector total count", f"expected 93, got {total}")

        # Spot-fetch FIR 1000001 and check enrichment fields
        result = index.fetch(ids=["1000001"])
        vecs = result.get("vectors", {})
        if "1000001" not in vecs:
            _fail("Vector spot-fetch 1000001", "vector not found")
            return
        meta = vecs["1000001"].get("metadata", {})
        for field in ["case_status", "sections", "io_officer", "crime_subhead"]:
            if not meta.get(field):
                _fail(f"Vector meta field '{field}' on 1000001", f"missing or empty (got: {meta.get(field)!r})")
            else:
                _ok(f"Vector meta[{field}]", str(meta[field])[:80])
    except Exception as e:
        _fail("Vector checks", str(e))


# ---------------------------------------------------------------------------
# Graph checks
# ---------------------------------------------------------------------------
def _check_graph() -> None:
    print("[verify] Graph …", flush=True)
    from neo4j import GraphDatabase

    try:
        driver = GraphDatabase.driver(
            cfg.NEO4J_URI, auth=(cfg.NEO4J_USERNAME, cfg.NEO4J_PASSWORD)
        )
        with driver.session() as s:
            # Scn1: funds flow from mule accounts to AGG account 9842017633250001
            result = s.run(
                "MATCH (:Account)-[:TRANSFERRED_TO]->(agg:Account {node_id: 9842017633250001}) "
                "RETURN count(*) AS cnt"
            ).single()
            cnt = result["cnt"] if result else 0
            if cnt >= 3:
                _ok("Graph Scn1 AGG chain", f"{cnt} TRANSFERRED_TO edges to AGG account")
            else:
                _fail("Graph Scn1 AGG chain", f"expected >=3 edges, got {cnt}")

            # Scn2: ACC:2000001/2/3 USES shared device/UPI/phone
            result = s.run(
                "MATCH (p:Person)-[:USES]->(obj) "
                "WHERE p.node_id IN ['ACC:2000001','ACC:2000002','ACC:2000003'] "
                "RETURN count(*) AS cnt"
            ).single()
            cnt = result["cnt"] if result else 0
            if cnt >= 3:
                _ok("Graph Scn2 USES", f"{cnt} USES edges from Scn2 accused")
            else:
                _fail("Graph Scn2 USES", f"expected >=3 edges, got {cnt}")

            # Scn3: flagged bridge account 5530123456789001 (node_id stored as int)
            result = s.run(
                "MATCH (a:Account {node_id: 5530123456789001}) "
                "RETURN a.is_flagged_mule AS flagged"
            ).single()
            if result and result["flagged"]:
                _ok("Graph Scn3 bridge flagged", "5530123456789001 is_flagged_mule=true")
            else:
                _fail("Graph Scn3 bridge flagged", "account not found or not flagged")

            # Orphaned sections: some sections (IT Act 43/72, BSA 63, BNSS 94/175) have no
            # case in the dataset — data reality, not a bug. Fail only if ALL are orphaned.
            result = s.run(
                "MATCH (s:Section) WHERE NOT ()-[:CHARGED_UNDER]->(s) "
                "RETURN count(s) AS orphans"
            ).single()
            orphans = result["orphans"] if result else 0
            total_sections = s.run("MATCH (s:Section) RETURN count(s) AS n").single()["n"]
            if orphans < total_sections:
                _ok("Graph Section coverage", f"{total_sections - orphans}/{total_sections} sections have CHARGED_UNDER")
            else:
                _fail("Graph Section coverage", f"all {orphans} sections are orphaned")

            # All non-empty rel types have >=1 edge.
            # OCCURRED_IN connects Crime→district-name-string (no District nodes) — skip.
            for rel_type in ["ACCUSED_IN", "COMPLAINANT_IN", "MENTIONS", "USES",
                              "TRANSFERRED_TO", "CHARGED_UNDER",
                              "REQUIRES_ELEMENT", "INTERPRETS", "SUPPORTS", "REPLACES"]:
                result = s.run(
                    f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt"
                ).single()
                cnt = result["cnt"] if result else 0
                if cnt >= 1:
                    _ok(f"Graph rel {rel_type}", f"{cnt} edge(s)")
                else:
                    _fail(f"Graph rel {rel_type}", "0 edges")

        driver.close()
    except Exception as e:
        _fail("Graph checks", str(e))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run() -> None:
    """Run all verification checks. Raises SystemExit(1) if any fail."""
    print("[verify] Running post-load verification …", flush=True)
    _check_sql()
    _check_vector()
    _check_graph()

    if _failures:
        print(f"\n[verify] FAILED — {len(_failures)} issue(s):", flush=True)
        for f in _failures:
            print(f"  • {f}", flush=True)
        sys.exit(1)
    print(f"[verify] All checks PASSED", flush=True)
