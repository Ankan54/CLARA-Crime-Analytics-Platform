"""verify_seed_links.py -- offline pre-flight for the demo's planted links.

Reads the sqlite seed and asserts the facts the four scenarios depend on, using the
SAME resolution rules migrate_sqlite_to_pg.py + load_neo4j_from_pg.py apply. Catches a
broken corpus BEFORE a three-store reload, instead of after -- every failure here
showed up in practice as a demo that silently found nothing.

Needs no Postgres/Neo4j/Pinecone. Run:
    python backend/scripts/verify_seed_links.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "migrations"))

from migrate_sqlite_to_pg import (  # noqa: E402
    SQLITE_PATH_DEFAULT,
    _norm_account,
    _norm_imei,
    _norm_phone,
    _norm_upi,
)

failures: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


def main() -> int:
    conn = sqlite3.connect(SQLITE_PATH_DEFAULT)
    conn.row_factory = sqlite3.Row
    q = lambda sql: [dict(r) for r in conn.execute(sql)]  # noqa: E731

    print(f"seed: {SQLITE_PATH_DEFAULT}\n")

    # -- Identifier uniqueness: the join key that merges live onto historical ---------
    # These are UNIQUE indexes in schema_pg.sql; a collision fails the reload loudly.
    print("Identifier normalization (UNIQUE index pre-flight)")
    for table, col, fn in [
        ("EXT_Account", "AccountNo", _norm_account),
        ("EXT_UPI", "VPA", _norm_upi),
        ("EXT_Phone", "Number", _norm_phone),
        ("EXT_Device", "IMEI", _norm_imei),
    ]:
        vals = [fn(r[col]) for r in q(f"SELECT {col} FROM {table}")]
        non_null = [v for v in vals if v is not None]
        dupes = {k: n for k, n in Counter(non_null).items() if n > 1}
        check(f"{table} normalized-unique", not dupes, f"{len(non_null)} rows, {len(dupes)} collisions")

    # -- Money trail terminates somewhere resolvable ----------------------------------
    # Every counterparty must be an Account or a Wallet. Anything else resolves to
    # to_account_id=NULL + to_wallet_address=NULL and the trail silently dead-ends.
    print("\nMoney trail")
    accounts = {str(r["AccountNo"]) for r in q("SELECT AccountNo FROM EXT_Account")}
    wallets = {str(r["Address"]) for r in q("SELECT Address FROM EXT_Wallet")}
    txns = q("SELECT TxnID, FromAccount, ToAccount, Channel FROM EXT_Transaction")
    orphans = [
        t for t in txns
        if str(t["ToAccount"]) not in accounts and str(t["ToAccount"]) not in wallets
    ]
    check("every txn counterparty resolves", not orphans,
          f"{len(txns)} txns, {len(orphans)} unresolvable")
    for t in orphans[:5]:
        print(f"        orphan: {t['TxnID']} -> {t['ToAccount']}")

    crypto = [t for t in txns if str(t["ToAccount"]) in wallets]
    check("crypto cash-out hop exists", bool(crypto),
          f"{len(crypto)} account->wallet txns to {len(wallets)} wallet(s)")

    # -- Scenario 2: aliases collapse via a shared device -----------------------------
    print("\nScenario 2 (alias collapse)")
    uses = q("SELECT from_person_id, to_object_id, object_type, source_caseid FROM EXT_Uses")
    devices_by_person = {
        u["from_person_id"]: u["to_object_id"]
        for u in uses if str(u["object_type"]).lower() == "device"
    }
    shared = Counter(devices_by_person.values())
    check("2+ alias identities share one device", any(n >= 2 for n in shared.values()),
          f"{len(devices_by_person)} person->device links, most-shared device used by {max(shared.values(), default=0)}")

    # EXT_Uses holder resolution keys on source_caseid -> that case's single Accused.
    accused_cases = {r["CaseMasterID"] for r in q("SELECT CaseMasterID FROM Accused")}
    unresolvable = {u["source_caseid"] for u in uses} - accused_cases
    check("every EXT_Uses row resolves to an Accused", not unresolvable,
          f"{len(unresolvable)} case(s) with EXT_Uses but no Accused row")

    multi = [r for r in q(
        "SELECT CaseMasterID, COUNT(*) n FROM Accused GROUP BY CaseMasterID HAVING n > 1")]
    check("no case has 2+ Accused", not multi,
          f"{len(multi)} case(s) would break the case-keyed holder join")

    # -- Scenario 4: IP co-location ---------------------------------------------------
    print("\nScenario 4 (operator co-location)")
    ip_mentions = q("SELECT object_id FROM EXT_Mentions WHERE lower(object_type) = 'ips'")
    ips = {str(r["IPAddress"]) for r in q("SELECT IPAddress FROM EXT_IP")}
    resolvable = [m for m in ip_mentions if str(m["object_id"]) in ips]
    check("IP mentions resolve to EXT_IP rows", len(resolvable) == len(ip_mentions),
          f"{len(resolvable)}/{len(ip_mentions)} resolve across {len(ips)} IPs")

    # -- Legal chain: charge -> element -> evidence -> precedent ----------------------
    # Every hop needs EXT_SectionMap to bridge (ActCode, SectionCode) to SectionID.
    print("\nLegal chain")
    mapped = q("""
        SELECT COUNT(DISTINCT asa.ActCode || '/' || asa.SectionCode) AS n
        FROM ActSectionAssociation asa
        JOIN EXT_SectionMap sm ON sm.ActCode = asa.ActCode AND sm.SectionCode = asa.SectionCode
    """)[0]["n"]
    charged = q("SELECT COUNT(DISTINCT ActCode || '/' || SectionCode) AS n FROM ActSectionAssociation")[0]["n"]
    check("every charged section maps to a SectionID", mapped == charged,
          f"{mapped}/{charged} charged sections bridge to the legal layer")

    orphan_elements = q("""
        SELECT COUNT(*) AS n FROM EXT_LegalElement le
        WHERE le.SectionID NOT IN (SELECT SectionID FROM EXT_SectionMap)
    """)[0]["n"]
    check("no element points at an unknown SectionID", orphan_elements == 0,
          f"{orphan_elements} orphaned elements")

    no_evidence = q("""
        SELECT COUNT(*) AS n FROM EXT_LegalElement le
        WHERE le.ElementID NOT IN (SELECT ElementID FROM EXT_ElementSatisfiedBy)
    """)[0]["n"]
    total_elements = q("SELECT COUNT(*) AS n FROM EXT_LegalElement")[0]["n"]
    # Not every element is closable by a catalogued evidence type (intent, for one), so
    # this reports rather than fails -- it just must not be *all* of them.
    check("elements have satisfying evidence types", no_evidence < total_elements,
          f"{total_elements - no_evidence}/{total_elements} elements have a satisfying evidence type")

    reachable = q("""
        SELECT COUNT(DISTINCT p.PrecedentID) AS n
        FROM ActSectionAssociation asa
        JOIN EXT_SectionMap sm ON sm.ActCode = asa.ActCode AND sm.SectionCode = asa.SectionCode
        JOIN EXT_Precedent p ON p.SectionID = sm.SectionID
    """)[0]["n"]
    check("precedents reachable from real charges", reachable > 0,
          f"{reachable} precedents cite-able from charged sections")

    # The planted amber gap: evidence types needing a s63 certificate must exist, or
    # scenario 1's headline legal finding has nothing to fire on.
    needs63 = q("SELECT COUNT(*) AS n FROM EXT_EvidenceType WHERE Requires63Certificate = 1")[0]["n"]
    check("s63-certificate evidence types exist", needs63 > 0,
          f"{needs63} evidence types require a BSA s63 certificate")

    # -- Scenario 1/3: cross-case shared objects (the marquee join) --------------------
    print("\nMarquee: shared objects spanning cases")
    rows = q("""
        SELECT object_id, object_type, COUNT(DISTINCT case_master_id) AS cases
        FROM EXT_Mentions GROUP BY object_id, object_type
        HAVING cases > 1 ORDER BY cases DESC LIMIT 5
    """)
    check("an object is mentioned by 2+ cases", bool(rows),
          f"top shared object spans {rows[0]['cases'] if rows else 0} cases")
    for r in rows:
        print(f"        {r['object_type']:<9} {r['object_id']}  -> {r['cases']} cases")

    conn.close()
    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All seed link checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
