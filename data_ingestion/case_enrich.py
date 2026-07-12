"""
case_enrich.py — Read ksp.sqlite and build {CaseMasterID: rich_metadata_dict}.
Runs once; the result dict is passed to vector_store.py for merge.

Rich metadata joins:
  core     : CaseMaster ← CaseStatusMaster, GravityOffence, CaseCategory,
             CrimeHead (major), CrimeSubHead (minor), Court,
             Unit (station) ← District,
             Employee (IO) ← Rank, Designation
  sections : ActSectionAssociation → acts list + sections list
  accused  : Accused + EXT_AccusedDetail  → count / known / any_arrested
  victims  : Victim → count
  ir       : EXT_InvestigationReport → is_live, report_date (merged later in vector_store)

ponytail check: assert case 1000001 has expected fields set (one runnable check).
"""
from __future__ import annotations
import sqlite3
from typing import Any

from . import config as cfg


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{cfg.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _to_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _to_bool(v: Any) -> bool:
    return bool(_to_int(v))


# ---------------------------------------------------------------------------
# Core join — one row per CaseMaster
# ---------------------------------------------------------------------------
_CORE_SQL = """
SELECT
    cm.CaseMasterID,
    cm.CrimeNo,
    cm.CrimeRegisteredDate,
    cm.IncidentFromDate         AS DateOfOffence,
    cm.IncidentToDate,
    cs.CaseStatusName           AS case_status,
    go.LookupValue              AS gravity,
    cc.LookupValue              AS case_category,
    ch.CrimeGroupName           AS crime_head,
    csh.CrimeHeadName           AS crime_subhead,
    co.CourtName                AS court,
    u.UnitName                  AS police_station,
    d.DistrictName              AS district,
    e.FirstName                 AS io_officer,
    r.RankName                  AS io_rank,
    des.DesignationName         AS io_designation
FROM CaseMaster cm
LEFT JOIN CaseStatusMaster  cs  ON cs.CaseStatusID     = cm.CaseStatusID
LEFT JOIN GravityOffence    go  ON go.GravityOffenceID  = cm.GravityOffenceID
LEFT JOIN CaseCategory      cc  ON cc.CaseCategoryID    = cm.CaseCategoryID
LEFT JOIN CrimeHead         ch  ON ch.CrimeHeadID       = cm.CrimeMajorHeadID
LEFT JOIN CrimeSubHead      csh ON csh.CrimeSubHeadID   = cm.CrimeMinorHeadID
LEFT JOIN Court             co  ON co.CourtID            = cm.CourtID
LEFT JOIN Unit              u   ON u.UnitID              = cm.PoliceStationID
LEFT JOIN District          d   ON d.DistrictID          = u.DistrictID
LEFT JOIN Employee          e   ON e.EmployeeID          = cm.PolicePersonID
LEFT JOIN Rank              r   ON r.RankID              = e.RankID
LEFT JOIN Designation       des ON des.DesignationID     = e.DesignationID
"""

_SECTIONS_SQL = """
SELECT CaseMasterID, ActCode, SectionCode
FROM ActSectionAssociation
ORDER BY CaseMasterID, ActCode, SectionCode
"""

_ACCUSED_SQL = """
SELECT
    a.CaseMasterID,
    COUNT(*)                                               AS accused_count,
    SUM(CASE WHEN a.AccusedName <> 'Unknown' THEN 1 ELSE 0 END) AS known_count,
    MAX(COALESCE(ad.IsArrested, 0))                        AS max_arrested
FROM Accused a
LEFT JOIN EXT_AccusedDetail ad ON ad.AccusedMasterID = a.AccusedMasterID
GROUP BY a.CaseMasterID
"""

# ArrestSurrender is an additional route for any_arrested
_ARREST_SQL = """
SELECT DISTINCT CaseMasterID FROM ArrestSurrender
"""

_VICTIM_SQL = """
SELECT CaseMasterID, COUNT(*) AS victim_count
FROM Victim
GROUP BY CaseMasterID
"""

# IR: report date + is_live (merged into IR-type vectors in vector_store)
_IR_SQL = """
SELECT CaseMasterID, ReportDate, IsLive FROM EXT_InvestigationReport
"""

# Amount: LossAmount from EXT_VictimDetail summed per case
_AMOUNT_SQL = """
SELECT v.CaseMasterID, SUM(vd.LossAmount) AS total_loss
FROM EXT_VictimDetail vd
JOIN Victim v ON v.VictimMasterID = vd.VictimMasterID
GROUP BY v.CaseMasterID
"""


# ---------------------------------------------------------------------------
# Public: build()
# ---------------------------------------------------------------------------
def build() -> dict[int, dict]:
    """Return {CaseMasterID: metadata_dict} by joining ksp.sqlite."""
    print("[case_enrich] Building metadata from ksp.sqlite …", flush=True)
    enriched: dict[int, dict] = {}

    with _conn() as conn:
        # --- core ---
        for row in conn.execute(_CORE_SQL).fetchall():
            cm_id = int(row["CaseMasterID"])
            crime_sub = row["crime_subhead"] or ""
            year = None
            date_str = row["CrimeRegisteredDate"] or ""
            if len(date_str) >= 4:
                try:
                    year = int(date_str[:4])
                except ValueError:
                    pass

            enriched[cm_id] = {
                "crime_no":               row["CrimeNo"],
                "case_master_id":         cm_id,
                "crime_registered_date":  date_str,
                "date_of_offence":        row["DateOfOffence"],
                "registered_year":        year,
                "case_status":            row["case_status"],
                "gravity":                row["gravity"],
                "case_category":          row["case_category"],
                "crime_head":             row["crime_head"],
                "crime_subhead":          crime_sub,
                # crime_type resolved below from subhead
                "crime_type":             cfg.CRIME_SUBHEAD_TO_TYPE.get(crime_sub),
                "court":                  row["court"],
                "police_station":         row["police_station"],
                "district":               row["district"],
                "io_officer":             row["io_officer"],
                "io_rank":                row["io_rank"],
                "io_designation":         row["io_designation"],
                # placeholders
                "acts":                   [],
                "sections":               [],
                "accused_count":          0,
                "accused_known":          False,
                "any_arrested":           False,
                "victim_count":           0,
                "amount_involved":        None,
                "amount_band":            None,
                # IR-specific defaults
                "report_date":            None,
                "is_live":                None,
            }

        # --- sections ---
        for row in conn.execute(_SECTIONS_SQL).fetchall():
            cm_id = int(row["CaseMasterID"])
            if cm_id not in enriched:
                continue
            act = row["ActCode"]
            sec = row["SectionCode"]
            acts_set: list = enriched[cm_id]["acts"]
            if act not in acts_set:
                acts_set.append(act)
            enriched[cm_id]["sections"].append(f"{act} {sec}")

        # --- accused ---
        arrested_cases: set[int] = {int(r["CaseMasterID"]) for r in conn.execute(_ARREST_SQL).fetchall()}
        for row in conn.execute(_ACCUSED_SQL).fetchall():
            cm_id = int(row["CaseMasterID"])
            if cm_id not in enriched:
                continue
            enriched[cm_id]["accused_count"] = int(row["accused_count"])
            enriched[cm_id]["accused_known"] = bool(int(row["known_count"] or 0))
            enriched[cm_id]["any_arrested"] = (
                bool(int(row["max_arrested"] or 0)) or cm_id in arrested_cases
            )

        # --- victims ---
        for row in conn.execute(_VICTIM_SQL).fetchall():
            cm_id = int(row["CaseMasterID"])
            if cm_id in enriched:
                enriched[cm_id]["victim_count"] = int(row["victim_count"])

        # --- amount (loss) ---
        for row in conn.execute(_AMOUNT_SQL).fetchall():
            cm_id = int(row["CaseMasterID"])
            if cm_id in enriched:
                amt = _to_int(row["total_loss"])
                enriched[cm_id]["amount_involved"] = amt
                enriched[cm_id]["amount_band"] = cfg.amount_band(amt) if amt else None

        # --- IR ---
        for row in conn.execute(_IR_SQL).fetchall():
            cm_id = int(row["CaseMasterID"])
            if cm_id in enriched:
                enriched[cm_id]["report_date"] = row["ReportDate"]
                enriched[cm_id]["is_live"] = bool(int(row["IsLive"] or 0))

    print(f"[case_enrich] Enriched {len(enriched)} cases", flush=True)
    _self_check(enriched)
    return enriched


# ---------------------------------------------------------------------------
# Self-check: assert case 1000001 has the fields we expect
# ponytail: this is the one runnable check for this module — fails if joins break.
# ---------------------------------------------------------------------------
def _self_check(enriched: dict[int, dict]) -> None:
    key = 1_000_001
    if key not in enriched:
        print(f"[case_enrich] WARNING: case {key} not found in enriched data (skipping self-check)", flush=True)
        return
    m = enriched[key]
    assert m.get("case_status"), f"self-check: case_status missing for {key}"
    assert m.get("district"), f"self-check: district missing for {key}"
    assert isinstance(m.get("sections"), list), f"self-check: sections not a list for {key}"
    assert m.get("io_officer"), f"self-check: io_officer missing for {key}"
    assert m.get("crime_subhead"), f"self-check: crime_subhead missing for {key}"
    print(f"[case_enrich] Self-check PASSED for case {key}: status={m['case_status']!r}, district={m['district']!r}", flush=True)
