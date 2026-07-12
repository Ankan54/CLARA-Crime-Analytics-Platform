"""
graph_store.py — Wipe Neo4j, apply constraints, load 13 node CSVs + 13 rel CSVs.

Key normalisation applied before loading rels:
  rels_uses      : :START_ID P_SCN2_AN  -> ACC:200000N  (Scn2 alias resolution)
                   :END_ID   DEV_/UPI_/PHONE_ prefix stripped
  rels_charged_under: :END_ID ITACT_* -> IT Act_* (matches nodes_section.csv node_id format)

ponytail: empty CSVs (0 rows) are skipped — rels_failed_on, rels_satisfied_by.
"""
from __future__ import annotations
import csv
import re
from pathlib import Path
from typing import Any

from . import config as cfg

# ---------------------------------------------------------------------------
# Node-label and property mappings
# key = CSV stem, value = (label, merge_key, [extra_props])
# ---------------------------------------------------------------------------
_NODE_SPECS: dict[str, tuple[str, str, list[str]]] = {
    "nodes_crime":          ("Crime",        "node_id", [
        "crime_no", "case_no", "crime_type", "district_id", "district_name",
        "registered_date", "date_of_offence", "status", "latitude", "longitude",
        "amount_involved", "vector_id",
    ]),
    "nodes_person":         ("Person",       "node_id", [
        "full_name", "role", "age", "gender", "occupation", "district",
    ]),
    "nodes_account":        ("Account",      "node_id", [
        "bank", "ifsc", "branch_district", "open_date",
        "last_inbound", "last_outbound", "is_flagged_mule", "kyc_name",
    ]),
    "nodes_phone":          ("Phone",        "node_id", ["number"]),
    "nodes_device":         ("Device",       "node_id", ["imei"]),
    "nodes_upi":            ("UPI",          "node_id", ["vpa"]),
    "nodes_ip":             ("IP",           "node_id", [
        "ip_address", "geo_lat", "geo_long", "geo_city",
    ]),
    "nodes_wallet":         ("Wallet",       "node_id", ["address", "chain"]),
    "nodes_section":        ("Section",      "node_id", [
        "act", "section_number", "title",
    ]),
    "nodes_legal_element":  ("LegalElement", "node_id", ["section_id", "name"]),
    "nodes_evidence_type":  ("EvidenceType", "node_id", ["name", "requires_63"]),
    "nodes_precedent":      ("Precedent",    "node_id", [
        "case_name", "citation", "year", "outcome", "holding_summary",
    ]),
    "nodes_ipc_section":    ("IPCSection",   "node_id", ["section_number", "title"]),
}

# ---------------------------------------------------------------------------
# Constraints (from import.cypher + Section + LegalElement)
# ---------------------------------------------------------------------------
_CONSTRAINTS = [
    ("Crime",        "node_id"),
    ("Person",       "node_id"),
    ("Account",      "node_id"),
    ("Device",       "node_id"),
    ("UPI",          "node_id"),
    ("Phone",        "node_id"),
    ("IP",           "node_id"),
    ("Wallet",       "node_id"),
    ("Section",      "node_id"),
    ("LegalElement", "node_id"),
    ("EvidenceType", "node_id"),
    ("Precedent",    "node_id"),
    ("IPCSection",   "node_id"),
]

# ---------------------------------------------------------------------------
# Rel CSV specs: (start_label, start_key_col, end_label, end_key_col, rel_type, extra_cols)
# Uses generic UNWIND/MERGE pattern keyed on :START_ID + :END_ID.
# ---------------------------------------------------------------------------
_REL_SPECS: dict[str, tuple[str, str, str]] = {
    # stem: (rel_type, set_clause_extra_col_names...)
    "rels_accused_in":      ("ACCUSED_IN",),
    "rels_charged_under":   ("CHARGED_UNDER",),
    "rels_complainant_in":  ("COMPLAINANT_IN",),
    "rels_failed_on":       ("FAILED_ON",),
    "rels_interprets":      ("INTERPRETS",),
    "rels_mentions":        ("MENTIONS",),
    "rels_occurred_in":     ("OCCURRED_IN",),
    "rels_replaces":        ("REPLACES",),
    "rels_requires_element":("REQUIRES_ELEMENT",),
    "rels_satisfied_by":    ("SATISFIED_BY",),
    "rels_supports":        ("SUPPORTS",),
    "rels_transferred_to":  ("TRANSFERRED_TO",),
    "rels_uses":            ("USES",),
}

# ---------------------------------------------------------------------------
# Key normalisation helpers
# ---------------------------------------------------------------------------
_P_SCN2_RE = re.compile(r'^P_SCN2_A(\d+)$')


def _norm_start(val: str) -> str:
    """P_SCN2_AN -> ACC:200000N"""
    m = _P_SCN2_RE.match(val)
    if m:
        n = int(m.group(1))
        return f"ACC:{2_000_000 + n}"
    return val


def _norm_end(val: str) -> str:
    """Strip DEV_/UPI_/PHONE_ prefix; ITACT_/IT_ -> IT Act_"""
    for prefix in ("DEV_", "UPI_", "PHONE_"):
        if val.startswith(prefix):
            return val[len(prefix):]
    if val.startswith("ITACT_"):
        return "IT Act_" + val[6:]
    # IT_66C, IT_43 etc. (no 'ACT' infix) — same target label as ITACT_
    if val.startswith("IT_"):
        return "IT Act_" + val[3:]
    return val


def _load_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _coerce(v: str) -> Any:
    """Best-effort int/float coercion; empty string -> None."""
    if v == "":
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    return v


def _to_node_id(val: str):
    """Return int if purely numeric, otherwise string. Matches how nodes were stored."""
    v = str(val)
    if v.lstrip("-").isdigit():
        return int(v)
    return v


def _rows_to_params(rows: list[dict], start_col: str = ":START_ID", end_col: str = ":END_ID") -> list[dict]:
    """Convert CSV rows to param dicts, normalising start/end IDs."""
    out = []
    for r in rows:
        p = {k: _coerce(v) for k, v in r.items()}
        if start_col in r:
            p[start_col] = _to_node_id(_norm_start(str(r[start_col])))
        if end_col in r:
            p[end_col] = _to_node_id(_norm_end(str(r[end_col])))
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Wipe
# ---------------------------------------------------------------------------
def _wipe(session) -> None:
    print("[graph_store] Wiping graph …", flush=True)
    session.run(
        "MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS"
    )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------
def _create_constraints(session) -> None:
    print("[graph_store] Creating constraints …", flush=True)
    for label, prop in _CONSTRAINTS:
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_{prop} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )


# ---------------------------------------------------------------------------
# Node loading
# ---------------------------------------------------------------------------
def _load_node(session, stem: str, rows: list[dict]) -> int:
    label, merge_key, prop_cols = _NODE_SPECS[stem]
    params = []
    for r in rows:
        p = {k: _coerce(v) for k, v in r.items()}
        params.append(p)

    # Build SET clause for non-merge-key columns
    set_assignments = ", ".join(f"n.{c} = row.{c}" for c in prop_cols if c != merge_key)
    set_clause = f" SET {set_assignments}" if set_assignments else ""

    cypher = (
        f"UNWIND $rows AS row "
        f"MERGE (n:{label} {{node_id: row.node_id}})"
        f"{set_clause}"
    )

    # blob_uri for Crime nodes (from blob manifest, added later in vector_store; skip here)
    for start in range(0, len(params), cfg.NEO4J_BATCH):
        batch = params[start: start + cfg.NEO4J_BATCH]
        session.run(cypher, rows=batch)
    return len(params)


# ---------------------------------------------------------------------------
# Rel loading — generic UNWIND/MERGE on start node_id -> rel -> end node_id
# We need labels for start and end — derive from the node id prefix conventions.
# ---------------------------------------------------------------------------
_PREFIX_LABEL: dict[str, str] = {
    "ACC:":    "Person",
    "COMP:":   "Person",
    "IT Act_": "Section",
    "BNS_":    "Section",
    "PMLA_":   "Section",
    "BSA_":    "Section",
    "BNSS_":   "Section",
}


def _guess_label(node_id: str) -> str:
    for prefix, label in _PREFIX_LABEL.items():
        if str(node_id).startswith(prefix):
            return label
    # Numeric-looking: Crime or Account or Device etc.
    if str(node_id).isdigit() and len(str(node_id)) >= 7:
        n = int(str(node_id))
        if 1_000_000 <= n < 2_000_000:
            return "Crime"
        if n >= 5_000_000:
            return "Account"
    # Default: we use a generic MATCH across all node types via node_id property
    return None  # type: ignore[return-value]


_ALL_LABELS_CYPHER = (
    "MATCH (a {node_id: row.start_id}), (b {node_id: row.end_id}) "
    "MERGE (a)-[r:{rel_type}]->(b) "
    "SET r += row.props"
)


def _rel_props(row: dict) -> dict:
    skip = {":START_ID", ":END_ID", ":TYPE"}
    return {k: v for k, v in row.items() if k not in skip and v is not None}


def _load_rel(session, stem: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    rel_type = _REL_SPECS[stem][0]
    normalised = _rows_to_params(rows)

    params = []
    for r in normalised:
        params.append({
            "start_id": r[":START_ID"],
            "end_id":   r[":END_ID"],
            "props":    _rel_props(r),
        })

    cypher = (
        f"UNWIND $rows AS row "
        f"MATCH (a {{node_id: row.start_id}}), (b {{node_id: row.end_id}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        f"SET r += row.props"
    )
    for start in range(0, len(params), cfg.NEO4J_BATCH):
        batch = params[start: start + cfg.NEO4J_BATCH]
        session.run(cypher, rows=batch)
    return len(params)


# ---------------------------------------------------------------------------
# Stub node creation — ensures every :START_ID / :END_ID in every rel CSV
# has a corresponding node in the graph so no relationship is silently dropped.
# Stubs carry only node_id + a 'stub' flag so they're identifiable.
# ---------------------------------------------------------------------------

# object_type in rels_mentions -> Node label for stub
_OBJECT_TYPE_LABEL: dict[str, str] = {
    "phones":   "Phone",
    "accounts": "Account",
    "upis":     "UPI",
    "devices":  "Device",
    "ips":      "IP",
    "wallets":  "Wallet",
}

# Prefix patterns -> label for rels_transferred_to start IDs (victim account aliases)
_STUB_LABEL_PATTERNS: list[tuple[str, str]] = [
    ("VICTIM_ACC_", "Account"),
    ("INDP_ACC_",   "Account"),
]


def _infer_label(node_id: str, object_type: str | None = None) -> str:
    """Guess the label for a stub node from its ID or object_type hint."""
    if object_type and object_type in _OBJECT_TYPE_LABEL:
        return _OBJECT_TYPE_LABEL[object_type]
    nid = str(node_id)
    for prefix, label in _STUB_LABEL_PATTERNS:
        if nid.startswith(prefix):
            return label
    # Heuristic: 10-digit numbers look like phone numbers
    if nid.isdigit() and len(nid) == 10:
        return "Phone"
    # IMEI = 15 digits
    if nid.isdigit() and len(nid) == 15:
        return "Device"
    # Contains @ → UPI VPA
    if "@" in nid:
        return "UPI"
    return "Account"  # fallback — generic enough for most cross-case refs


def _collect_dangling_ids(graph_dir: Path, existing_ids: set) -> dict[str, str]:
    """
    Scan all rel CSVs for IDs (after normalisation) not yet in existing_ids.
    Returns {normalised_id: inferred_label}.
    """
    dangling: dict[str, str] = {}
    for f in graph_dir.glob("rels_*.csv"):
        rows = _load_csv(f)
        if not rows:
            continue
        # rels_mentions has 'object_type' column we can use for label inference
        has_object_type = "object_type" in (rows[0] if rows else {})
        for row in rows:
            s_raw = str(row.get(":START_ID", ""))
            e_raw = str(row.get(":END_ID", ""))
            s = str(_to_node_id(_norm_start(s_raw)))
            e = str(_to_node_id(_norm_end(e_raw)))
            ot = row.get("object_type", "") if has_object_type else ""
            if s and s not in existing_ids:
                dangling[s] = _infer_label(s, None)
            if e and e not in existing_ids:
                dangling[e] = _infer_label(e, ot or None)
    return dangling


def _ensure_stub_nodes(session, graph_dir: Path) -> int:
    """
    Create stub nodes for any rel endpoint that has no matching node yet.
    Stubs are created with MERGE so re-runs are idempotent.
    Returns count of stubs created.
    """
    # Gather all node_ids currently in the graph
    result = session.run("MATCH (n) RETURN n.node_id AS nid")
    existing: set[str] = {str(r["nid"]) for r in result if r["nid"] is not None}

    dangling = _collect_dangling_ids(graph_dir, existing)
    if not dangling:
        print("[graph_store] No stub nodes needed — all rel endpoints resolved.", flush=True)
        return 0

    print(f"[graph_store] Creating {len(dangling)} stub nodes for unresolved rel endpoints …", flush=True)

    # Group by label for efficient UNWIND
    by_label: dict[str, list[str]] = {}
    for nid, label in dangling.items():
        by_label.setdefault(label, []).append(nid)

    created = 0
    for label, ids in by_label.items():
        # _to_node_id: coerce numeric strings to int so they match MERGE keys
        params = [{"node_id": _to_node_id(nid), "stub": True} for nid in ids]
        for start in range(0, len(params), cfg.NEO4J_BATCH):
            batch = params[start: start + cfg.NEO4J_BATCH]
            session.run(
                f"UNWIND $rows AS row "
                f"MERGE (n:{label} {{node_id: row.node_id}}) "
                f"SET n.stub = row.stub",
                rows=batch,
            )
        created += len(ids)
        print(f"[graph_store]   stub {label}: {len(ids)}", flush=True)

    return created


# ---------------------------------------------------------------------------
# Public: run()
# ---------------------------------------------------------------------------
def run(wipe: bool = True) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        cfg.NEO4J_URI, auth=(cfg.NEO4J_USERNAME, cfg.NEO4J_PASSWORD)
    )
    graph_dir = cfg.GRAPH_DIR

    with driver.session() as session:
        if wipe:
            _wipe(session)
        _create_constraints(session)

        # --- Nodes ---
        print("[graph_store] Loading node CSVs …", flush=True)
        for stem in _NODE_SPECS:
            csv_path = graph_dir / f"{stem}.csv"
            if not csv_path.exists():
                print(f"[graph_store]   SKIP {stem}.csv (not found)", flush=True)
                continue
            rows = _load_csv(csv_path)
            if not rows:
                print(f"[graph_store]   SKIP {stem}.csv (empty)", flush=True)
                continue
            count = _load_node(session, stem, rows)
            print(f"[graph_store]   {stem}: {count} nodes", flush=True)

        # --- Stub nodes for any rel endpoint not covered by node CSVs ---
        _ensure_stub_nodes(session, graph_dir)

        # --- Rels ---
        print("[graph_store] Loading rel CSVs …", flush=True)
        for stem in _REL_SPECS:
            csv_path = graph_dir / f"{stem}.csv"
            if not csv_path.exists():
                print(f"[graph_store]   SKIP {stem}.csv (not found)", flush=True)
                continue
            rows = _load_csv(csv_path)
            if not rows:
                print(f"[graph_store]   SKIP {stem}.csv (empty)", flush=True)
                continue
            count = _load_rel(session, stem, rows)
            print(f"[graph_store]   {stem}: {count} rels", flush=True)

    driver.close()
    print("[graph_store] Done.", flush=True)
