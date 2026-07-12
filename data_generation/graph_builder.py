"""
graph_builder.py - Build Neo4j node/relationship CSVs by reading ksp.sqlite.

Key rules:
  - Object nodes (Account, Device, UPI, Phone, IP, Wallet) are keyed by
    natural identifier value. No CREATE-per-row; MERGE semantics enforced by
    pre-deduplicating node CSVs and using MERGE in import.cypher.
  - Every edge copies source_caseid/observed_date/confidence from the SQL
    link/fact table so context survives the SQL round-trip.
  - NO RESOLVED_AS, LINKED_TO, centrality, or community_id pre-baked.
  - Legal edges (CHARGED_UNDER, REQUIRES_ELEMENT etc.) are included.

Outputs under output/historical/graph/:
  nodes_crime.csv, nodes_person.csv, nodes_account.csv, nodes_phone.csv,
  nodes_device.csv, nodes_upi.csv, nodes_ip.csv, nodes_wallet.csv,
  nodes_section.csv, nodes_legal_element.csv, nodes_evidence_type.csv,
  nodes_precedent.csv, nodes_ipc_section.csv,
  rels_uses.csv, rels_mentions.csv, rels_accused_in.csv,
  rels_complainant_in.csv, rels_transferred_to.csv, rels_occurred_in.csv,
  rels_charged_under.csv, rels_has_evidence.csv,
  rels_replaces.csv, rels_requires_element.csv, rels_satisfied_by.csv,
  rels_supports.csv, rels_failed_on.csv, rels_interprets.csv,
  import.cypher

Run:  python graph_builder.py
      python graph_builder.py --db output/historical/db/ksp.sqlite --out output/historical/graph
"""
from __future__ import annotations
import argparse
import csv
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .legal_layer import (
    LEGAL_SECTIONS, LEGAL_ELEMENTS, EVIDENCE_TYPES, PRECEDENTS, IPC_SECTIONS,
    REPLACES_EDGES, REQUIRES_EDGES, SATISFIED_BY_EDGES,
    SUPPORTS_EDGES, FAILED_ON_EDGES, INTERPRETS_EDGES,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("graph_builder")

DEFAULT_DB  = "output/historical/db/ksp.sqlite"
DEFAULT_OUT = "output/historical/graph"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _query(conn: sqlite3.Connection, sql: str, params=()) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, params).fetchall()


def _r(row: sqlite3.Row, col: str, default=None):
    """Safe column accessor."""
    try:
        return row[col]
    except (IndexError, KeyError):
        return default


# ---------------------------------------------------------------------------
# Node builders (one node per unique identifier — MERGE semantics)
# ---------------------------------------------------------------------------

def build_crime_nodes(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT cm.CaseMasterID, cm.CrimeNo, cm.CaseNo, cm.CrimeRegisteredDate,
               cm.IncidentFromDate,
               cm.PoliceStationID, cm.CaseStatusID, cm.Latitude, cm.Longitude,
               u.DistrictID, d.DistrictName,
               cs.CrimeSubHeadID, cs.CrimeHeadName,
               COALESCE(SUM(vd.LossAmount), 0) AS amount_involved
        FROM CaseMaster cm
        LEFT JOIN Victim v ON cm.CaseMasterID = v.CaseMasterID
        LEFT JOIN EXT_VictimDetail vd ON v.VictimMasterID = vd.VictimMasterID
        LEFT JOIN Unit u ON cm.PoliceStationID = u.UnitID
        LEFT JOIN District d ON u.DistrictID = d.DistrictID
        LEFT JOIN CrimeSubHead cs ON cm.CrimeMinorHeadID = cs.CrimeSubHeadID
        GROUP BY cm.CaseMasterID, cm.CrimeNo, cm.CaseNo, cm.CrimeRegisteredDate, cm.IncidentFromDate,
                 cm.PoliceStationID, cm.CaseStatusID, cm.Latitude, cm.Longitude,
                 u.DistrictID, d.DistrictName, cs.CrimeSubHeadID, cs.CrimeHeadName
    """)
    return [{
        "node_id":         r["CaseMasterID"],
        "crime_no":        r["CrimeNo"],
        "case_no":         r["CaseNo"],
        "crime_type":      (r["CrimeHeadName"] or "").lower().replace(" ", "_"),
        "district_id":     r["DistrictID"],
        "district_name":   r["DistrictName"] or "",
        "registered_date": r["CrimeRegisteredDate"],
        "date_of_offence": r["IncidentFromDate"] or "",
        "status":          r["CaseStatusID"],
        "latitude":        r["Latitude"],
        "longitude":       r["Longitude"],
        "amount_involved": r["amount_involved"] or 0,
        "vector_id":       r["CaseMasterID"],
    } for r in rows]


def build_person_nodes(conn: sqlite3.Connection) -> List[Dict]:
    nodes = {}
    # Accused -> Person
    for r in _query(conn, """
        SELECT a.AccusedMasterID, a.AccusedName, a.AgeYear, a.GenderID,
               ad.OccupationID, o.OccupationName, ad.Address, ad.ResidenceDistrict,
               u.DistrictID, d.DistrictName,
               cm.PoliceStationID
        FROM Accused a
        LEFT JOIN EXT_AccusedDetail ad ON a.AccusedMasterID = ad.AccusedMasterID
        LEFT JOIN OccupationMaster o   ON ad.OccupationID = o.OccupationID
        LEFT JOIN CaseMaster cm ON a.CaseMasterID = cm.CaseMasterID
        LEFT JOIN Unit u ON cm.PoliceStationID = u.UnitID
        LEFT JOIN District d ON u.DistrictID = d.DistrictID
    """):
        nid = f"ACC:{r['AccusedMasterID']}"
        if nid not in nodes:
            nodes[nid] = {
                "node_id":    nid,
                "full_name":  r["AccusedName"],
                "role":       "accused",
                "age":        r["AgeYear"] or 0,
                "gender":     r["GenderID"] or "M",
                "occupation": r["OccupationName"] or "Other",
                "district":   r["ResidenceDistrict"] or r["DistrictName"] or "",
            }
    # Complainant -> Person
    for r in _query(conn, """
        SELECT c.ComplainantID, c.ComplainantName, c.AgeYear, c.GenderID,
               o.OccupationName, c.Address,
               vd.ResidenceDistrict, u.DistrictID, d.DistrictName
        FROM ComplainantDetails c
        LEFT JOIN OccupationMaster o ON c.OccupationID = o.OccupationID
        LEFT JOIN CaseMaster cm ON c.CaseMasterID = cm.CaseMasterID
        LEFT JOIN Victim v ON cm.CaseMasterID = v.CaseMasterID
        LEFT JOIN EXT_VictimDetail vd ON v.VictimMasterID = vd.VictimMasterID
        LEFT JOIN Unit u ON cm.PoliceStationID = u.UnitID
        LEFT JOIN District d ON u.DistrictID = d.DistrictID
    """):
        nid = f"COMP:{r['ComplainantID']}"
        if nid not in nodes:
            nodes[nid] = {
                "node_id":    nid,
                "full_name":  r["ComplainantName"],
                "role":       "complainant",
                "age":        r["AgeYear"] or 0,
                "gender":     r["GenderID"] or "M",
                "occupation": r["OccupationName"] or "Other",
                "district":   r["ResidenceDistrict"] or r["DistrictName"] or "",
            }
    return list(nodes.values())

def build_object_nodes(conn: sqlite3.Connection) -> Dict[str, List[Dict]]:
    """Build de-duplicated Object node CSVs, keyed by natural identifier."""
    return {
        "account": [{
            "node_id": r["AccountNo"], "bank": r["Bank"] or "",
            "ifsc": r["IFSC"] or "",
            "branch_district": r["BranchDistrict"] or "",
            "is_flagged_mule": r["IsFlaggedMule"] or 0,
            "kyc_name": r["KYCName"] or "",
            "open_date": r["OpenDate"] or "",
            "last_inbound": r["LastInbound"] or "",
            "last_outbound": r["LastOutbound"] or "",
        } for r in _query(conn, "SELECT * FROM EXT_Account")],
        "phone": [{
            "node_id": r["Number"], "number": r["Number"],
        } for r in _query(conn, "SELECT DISTINCT Number FROM EXT_Phone")],
        "device": [{
            "node_id": r["IMEI"], "imei": r["IMEI"],
        } for r in _query(conn, "SELECT DISTINCT IMEI FROM EXT_Device")],
        "upi": [{
            "node_id": r["VPA"], "vpa": r["VPA"],
        } for r in _query(conn, "SELECT DISTINCT VPA FROM EXT_UPI")],
        "ip": [{
            "node_id": r["IPAddress"], "ip_address": r["IPAddress"],
            "geo_lat": r["GeoLat"] if r["GeoLat"] is not None else "",
            "geo_long": r["GeoLong"] if r["GeoLong"] is not None else "",
            "geo_city": r["GeoCity"] or "",
        } for r in _query(conn, "SELECT DISTINCT IPAddress, GeoLat, GeoLong, GeoCity FROM EXT_IP")],
        "wallet": [{
            "node_id": r["Address"], "address": r["Address"],
            "chain": r["Chain"] or "USDT",
        } for r in _query(conn, "SELECT DISTINCT Address, Chain FROM EXT_Wallet")],
    }


# ---------------------------------------------------------------------------
# Edge builders (all carry source_caseid/observed_date/confidence from SQL)
# ---------------------------------------------------------------------------

def build_uses_edges(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT from_person_id, to_object_id, object_type,
               source_caseid, observed_date, confidence, role
        FROM EXT_Uses
    """)
    return [{
        ":START_ID":     r["from_person_id"],
        ":END_ID":       r["to_object_id"],
        ":TYPE":         "USES",
        "object_type":   r["object_type"] or "",
        "source_caseid": r["source_caseid"] or "",
        "observed_date": r["observed_date"] or "",
        "confidence":    r["confidence"] or 1.0,
        "role":          r["role"] or "",
    } for r in rows]


def build_mentions_edges(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT case_master_id, object_id, object_type,
               source_caseid, observed_date, confidence
        FROM EXT_Mentions
    """)
    return [{
        ":START_ID":     r["case_master_id"],
        ":END_ID":       r["object_id"],
        ":TYPE":         "MENTIONS",
        "object_type":   r["object_type"] or "",
        "source_caseid": r["source_caseid"] or "",
        "observed_date": r["observed_date"] or "",
        "confidence":    r["confidence"] or 1.0,
    } for r in rows]


def build_accused_in_edges(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT AccusedMasterID, CaseMasterID,
               source_caseid, observed_date, confidence, role
        FROM EXT_AccusedIn
    """)
    return [{
        ":START_ID":     f"ACC:{r['AccusedMasterID']}",
        ":END_ID":       r["CaseMasterID"],
        ":TYPE":         "ACCUSED_IN",
        "source_caseid": r["source_caseid"] or r["CaseMasterID"],
        "observed_date": r["observed_date"] or "",
        "confidence":    r["confidence"] or 1.0,
        "role":          r["role"] or "",
    } for r in rows]


def build_complainant_in_edges(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT ComplainantID, CaseMasterID,
               source_caseid, observed_date, confidence
        FROM EXT_ComplainantIn
    """)
    return [{
        ":START_ID":     f"COMP:{r['ComplainantID']}",
        ":END_ID":       r["CaseMasterID"],
        ":TYPE":         "COMPLAINANT_IN",
        "source_caseid": r["source_caseid"] or r["CaseMasterID"],
        "observed_date": r["observed_date"] or "",
        "confidence":    r["confidence"] or 1.0,
    } for r in rows]


def build_transferred_to_edges(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT FromAccount, ToAccount, Amount, Timestamp, Channel, HopRole,
               source_caseid, observed_date, confidence, role, timestamp AS ts
        FROM EXT_Transaction
        WHERE FromAccount IS NOT NULL AND ToAccount IS NOT NULL
    """)
    return [{
        ":START_ID":     r["FromAccount"],
        ":END_ID":       r["ToAccount"],
        ":TYPE":         "TRANSFERRED_TO",
        "amount":        r["Amount"] or 0,
        "timestamp":     r["Timestamp"] or "",
        "channel":       r["Channel"] or "",
        "hop_role":      r["HopRole"] or "",
        "source_caseid": r["source_caseid"] or "",
        "observed_date": r["observed_date"] or "",
        "confidence":    r["confidence"] or 1.0,
    } for r in rows]


def build_occurred_in_edges(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT cm.CaseMasterID, d.DistrictName
        FROM CaseMaster cm
        LEFT JOIN Unit u ON cm.PoliceStationID = u.UnitID
        LEFT JOIN District d ON u.DistrictID = d.DistrictID
    """)
    return [{
        ":START_ID": r["CaseMasterID"],
        ":END_ID":   r["DistrictName"] or "Unknown",
        ":TYPE":     "OCCURRED_IN",
    } for r in rows]


def build_charged_under_edges(conn: sqlite3.Connection) -> List[Dict]:
    rows = _query(conn, """
        SELECT asa.CaseMasterID, asa.ActCode, asa.SectionCode
        FROM ActSectionAssociation asa
    """)
    return [{
        ":START_ID":     r["CaseMasterID"],
        ":END_ID":       f"{r['ActCode']}_{r['SectionCode']}",
        ":TYPE":         "CHARGED_UNDER",
        "source_caseid": r["CaseMasterID"],
    } for r in rows]

# ---------------------------------------------------------------------------
# import.cypher (MERGE semantics for Object nodes)
# ---------------------------------------------------------------------------

_CYPHER = """// KSP Crime Intelligence Platform - Neo4j Import Script
// GENERATED by graph_builder.py — DO NOT EDIT
// Object nodes use MERGE on natural key to preserve cross-case links.

// Crime nodes
LOAD CSV WITH HEADERS FROM 'file:///nodes_crime.csv' AS row
MERGE (c:Crime {node_id: toInteger(row.node_id)})
SET c.crime_no=row.crime_no, c.case_no=row.case_no,
    c.crime_type=row.crime_type,
    c.district_id=toInteger(coalesce(row.district_id,'0')),
    c.district_name=row.district_name,
    c.registered_date=row.registered_date,
    c.date_of_offence=row.date_of_offence,
    c.latitude=toFloat(coalesce(row.latitude,'0')),
    c.longitude=toFloat(coalesce(row.longitude,'0')),
    c.amount_involved=toInteger(coalesce(row.amount_involved,'0'));

// Person nodes
LOAD CSV WITH HEADERS FROM 'file:///nodes_person.csv' AS row
MERGE (p:Person {node_id: row.node_id})
SET p.full_name=row.full_name, p.role=row.role,
    p.age=toInteger(coalesce(row.age,'0')),
    p.gender=row.gender, p.occupation=row.occupation,
    p.district=row.district;

// Account nodes  — MERGE on account_no
LOAD CSV WITH HEADERS FROM 'file:///nodes_account.csv' AS row
MERGE (a:Account {node_id: row.node_id})
SET a.bank=row.bank, a.ifsc=row.ifsc,
    a.branch_district=row.branch_district,
    a.open_date=row.open_date,
    a.last_inbound=row.last_inbound,
    a.last_outbound=row.last_outbound,
    a.is_flagged_mule=toBoolean(row.is_flagged_mule),
    a.kyc_name=row.kyc_name;

// Phone nodes  — MERGE on number
LOAD CSV WITH HEADERS FROM 'file:///nodes_phone.csv' AS row
MERGE (ph:Phone {node_id: row.node_id}) SET ph.number=row.number;

// Device nodes  — MERGE on imei
LOAD CSV WITH HEADERS FROM 'file:///nodes_device.csv' AS row
MERGE (d:Device {node_id: row.node_id}) SET d.imei=row.imei;

// UPI nodes  — MERGE on vpa
LOAD CSV WITH HEADERS FROM 'file:///nodes_upi.csv' AS row
MERGE (u:UPI {node_id: row.node_id}) SET u.vpa=row.vpa;

// IP nodes  — MERGE on ip_address
LOAD CSV WITH HEADERS FROM 'file:///nodes_ip.csv' AS row
MERGE (i:IP {node_id: row.node_id})
SET i.ip_address=row.ip_address,
    i.geo_lat=toFloat(coalesce(row.geo_lat,'0')),
    i.geo_long=toFloat(coalesce(row.geo_long,'0')),
    i.geo_city=row.geo_city;

// Wallet nodes  — MERGE on address
LOAD CSV WITH HEADERS FROM 'file:///nodes_wallet.csv' AS row
MERGE (w:Wallet {node_id: row.node_id})
SET w.address=row.address, w.chain=row.chain;

// Legal nodes
LOAD CSV WITH HEADERS FROM 'file:///nodes_section.csv' AS row
MERGE (s:Section {node_id: row.node_id})
SET s.act=row.act, s.section_number=row.section_number, s.title=row.title;

LOAD CSV WITH HEADERS FROM 'file:///nodes_legal_element.csv' AS row
MERGE (le:LegalElement {node_id: row.node_id})
SET le.section_id=row.section_id, le.name=row.name;

LOAD CSV WITH HEADERS FROM 'file:///nodes_evidence_type.csv' AS row
MERGE (et:EvidenceType {node_id: row.node_id}) SET et.name=row.name;

LOAD CSV WITH HEADERS FROM 'file:///nodes_precedent.csv' AS row
MERGE (pr:Precedent {node_id: row.node_id})
SET pr.case_name=row.case_name, pr.citation=row.citation,
    pr.year=toInteger(row.year), pr.outcome=row.outcome;

LOAD CSV WITH HEADERS FROM 'file:///nodes_ipc_section.csv' AS row
MERGE (ipc:IPCSection {node_id: row.node_id})
SET ipc.section_number=row.section_number, ipc.title=row.title;

// Constraints and indexes
CREATE CONSTRAINT crime_id IF NOT EXISTS FOR (c:Crime) REQUIRE c.node_id IS UNIQUE;
CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.node_id IS UNIQUE;
CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.node_id IS UNIQUE;
CREATE CONSTRAINT device_id IF NOT EXISTS FOR (d:Device) REQUIRE d.node_id IS UNIQUE;
CREATE CONSTRAINT upi_id IF NOT EXISTS FOR (u:UPI) REQUIRE u.node_id IS UNIQUE;
CREATE CONSTRAINT phone_id IF NOT EXISTS FOR (ph:Phone) REQUIRE ph.node_id IS UNIQUE;
CREATE CONSTRAINT ip_id IF NOT EXISTS FOR (i:IP) REQUIRE i.node_id IS UNIQUE;
CREATE CONSTRAINT wallet_id IF NOT EXISTS FOR (w:Wallet) REQUIRE w.node_id IS UNIQUE;
"""


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_graph(db_path: str = DEFAULT_DB, out_dir: str = DEFAULT_OUT) -> str:
    """
    Read ksp.sqlite and emit all graph CSVs + import.cypher.
    Returns path to out_dir.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"ksp.sqlite not found: {db_file}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    log.info("Building Crime nodes...")
    n = _write_csv(out / "nodes_crime.csv", build_crime_nodes(conn),
        ["node_id","crime_no","case_no","crime_type","district_id","district_name",
         "registered_date","date_of_offence","status","latitude","longitude",
         "amount_involved","vector_id"])
    log.info(f"  nodes_crime: {n}")

    log.info("Building Person nodes...")
    n = _write_csv(out / "nodes_person.csv", build_person_nodes(conn),
        ["node_id","full_name","role","age","gender","occupation","district"])
    log.info(f"  nodes_person: {n}")

    log.info("Building Object nodes (MERGE on natural key)...")
    obj = build_object_nodes(conn)
    n = _write_csv(out / "nodes_account.csv", obj["account"],
        ["node_id","bank","ifsc","branch_district","open_date",
         "last_inbound","last_outbound","is_flagged_mule","kyc_name"])
    log.info(f"  nodes_account: {n}")
    n = _write_csv(out / "nodes_phone.csv",  obj["phone"],  ["node_id","number"])
    log.info(f"  nodes_phone: {n}")
    n = _write_csv(out / "nodes_device.csv", obj["device"], ["node_id","imei"])
    log.info(f"  nodes_device: {n}")
    n = _write_csv(out / "nodes_upi.csv",    obj["upi"],    ["node_id","vpa"])
    log.info(f"  nodes_upi: {n}")
    n = _write_csv(out / "nodes_ip.csv",     obj["ip"],     ["node_id","ip_address","geo_lat","geo_long","geo_city"])
    log.info(f"  nodes_ip: {n}")
    n = _write_csv(out / "nodes_wallet.csv", obj["wallet"], ["node_id","address","chain"])
    log.info(f"  nodes_wallet: {n}")

    # Legal nodes (from legal_layer constants)
    _write_csv(out / "nodes_section.csv",
        [{"node_id": f"{s.act}_{s.section_number}", "act": s.act,
          "section_number": s.section_number, "title": s.title}
         for s in LEGAL_SECTIONS],
        ["node_id","act","section_number","title"])
    _write_csv(out / "nodes_legal_element.csv",
        [{"node_id": e.element_id, "section_id": e.section_id, "name": e.name}
         for e in LEGAL_ELEMENTS],
        ["node_id","section_id","name"])
    _write_csv(out / "nodes_evidence_type.csv",
        [{"node_id": e.evidence_type_id, "name": e.name,
          "requires_63": int(e.requires_63_certificate)}
         for e in EVIDENCE_TYPES],
        ["node_id","name","requires_63"])
    _write_csv(out / "nodes_precedent.csv",
        [{"node_id": p.precedent_id, "case_name": p.case_name,
          "citation": p.citation, "year": p.year,
          "outcome": p.outcome, "holding_summary": p.holding_summary}
         for p in PRECEDENTS],
        ["node_id","case_name","citation","year","outcome","holding_summary"])
    _write_csv(out / "nodes_ipc_section.csv",
        [{"node_id": s.ipc_section_id, "section_number": s.section_number,
          "title": s.title}
         for s in IPC_SECTIONS],
        ["node_id","section_number","title"])

    log.info("Building relationship edges (with context columns from SQL)...")

    n = _write_csv(out / "rels_uses.csv", build_uses_edges(conn),
        [":START_ID",":END_ID",":TYPE","object_type","source_caseid","observed_date","confidence","role"])
    log.info(f"  rels_uses: {n}")

    n = _write_csv(out / "rels_mentions.csv", build_mentions_edges(conn),
        [":START_ID",":END_ID",":TYPE","object_type","source_caseid","observed_date","confidence"])
    log.info(f"  rels_mentions: {n}")

    n = _write_csv(out / "rels_accused_in.csv", build_accused_in_edges(conn),
        [":START_ID",":END_ID",":TYPE","source_caseid","observed_date","confidence","role"])
    log.info(f"  rels_accused_in: {n}")

    n = _write_csv(out / "rels_complainant_in.csv", build_complainant_in_edges(conn),
        [":START_ID",":END_ID",":TYPE","source_caseid","observed_date","confidence"])
    log.info(f"  rels_complainant_in: {n}")

    n = _write_csv(out / "rels_transferred_to.csv", build_transferred_to_edges(conn),
        [":START_ID",":END_ID",":TYPE","amount","timestamp","channel",
         "hop_role","source_caseid","observed_date","confidence"])
    log.info(f"  rels_transferred_to: {n}")

    n = _write_csv(out / "rels_occurred_in.csv", build_occurred_in_edges(conn),
        [":START_ID",":END_ID",":TYPE"])
    log.info(f"  rels_occurred_in: {n}")

    n = _write_csv(out / "rels_charged_under.csv", build_charged_under_edges(conn),
        [":START_ID",":END_ID",":TYPE","source_caseid"])
    log.info(f"  rels_charged_under: {n}")

    # Legal static edges
    _write_csv(out / "rels_replaces.csv",          REPLACES_EDGES,    [":START_ID",":END_ID",":TYPE"])
    _write_csv(out / "rels_requires_element.csv",  REQUIRES_EDGES,    [":START_ID",":END_ID",":TYPE"])
    _write_csv(out / "rels_satisfied_by.csv",      SATISFIED_BY_EDGES,[":START_ID",":END_ID",":TYPE","fir_id","element_id"])
    _write_csv(out / "rels_supports.csv",          SUPPORTS_EDGES,    [":START_ID",":END_ID",":TYPE"])
    _write_csv(out / "rels_failed_on.csv",         FAILED_ON_EDGES,   [":START_ID",":END_ID",":TYPE","fir_id"])
    _write_csv(out / "rels_interprets.csv",        INTERPRETS_EDGES,  [":START_ID",":END_ID",":TYPE"])

    # import.cypher
    (out / "import.cypher").write_text(_CYPHER, encoding="utf-8")
    log.info(f"import.cypher written")

    conn.close()
    log.info(f"Graph build complete: {out}")
    return str(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Neo4j graph from ksp.sqlite")
    parser.add_argument("--db",  default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    try:
        build_graph(args.db, args.out)
    except Exception as e:
        log.error(str(e))
        sys.exit(1)
