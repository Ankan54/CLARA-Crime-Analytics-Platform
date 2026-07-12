# planted_links.md — Ground-truth manifest for the KSP Crime Intelligence Platform demo dataset
# This file is the ONLY place where pre-resolved identities and cross-case links are recorded.
# The base graph the platform loads does NOT contain RESOLVED_AS, LINKED_TO, centrality,
# or community_id edges — those are discovered at runtime. This file is used only for
# validation and as a fallback if live resolution underperforms on stage.
#
# ID FORMAT NOTE (KSP Schema Integration):
# All case identities are now expressed with INT CaseMasterID (from id_registry.py)
# alongside the logical key for traceability. The INT PK is authoritative for SQL/graph/vector.

## Scenario 1 — Digital Arrest Ring

### Historical Cases (3 FIRs)
| CaseMasterID (INT) | Logical Key     | CrimeNo (assigned at runtime) | District        | Status      |
|--------------------|-----------------|-------------------------------|-----------------|-------------|
| 1000001+           | FIR_SCN1_H01   | CaseMasterID-derived          | Mysuru          | Historical  |
| 1000002+           | FIR_SCN1_H02   | CaseMasterID-derived          | Mangaluru       | Historical  |
| 1000003+           | FIR_SCN1_H03   | CaseMasterID-derived          | Hubballi-Dharwad| Historical  |

### Planted Ring Link
- **AGG_ACC_01** account `9842017633250001` (HDFC0004217) is the aggregation account.
- All 3 historical cases route funds there via intermediate collection accounts.
- Pre-loaded with `kyc_name=""` and NO owner Person node.
- **Live Reveal**: The live investigation report adds the KYC name (`Ravi Kumar G`) and
  controller identifiers (`CTRL_IMEI_01`, `CTRL_UPI_01`).
- Platform must discover the ring at runtime via `TRANSFERRED_TO` edge traversal.

### Decoy
- 1 FIR with a similar digital-arrest narrative but NO shared identifiers with the ring.
- Must surface in similarity search (Tier A/B borderline) but link query returns nothing.

---

## Scenario 2 — Many Names, One Man (entity resolution)

### Alias Person Nodes (4, all separate AccusedMasterIDs — NO pre-merging)
| AccusedMasterID (INT) | Logical Key  | Full Name      | Crime Type      | Case Year |
|-----------------------|--------------|----------------|-----------------|-----------|
| 2000001+              | P_SCN2_A1   | Imraan Sheikh  | loan_app        | 2024      |
| 2000002+              | P_SCN2_A2   | I. Shaikh      | otp_fraud       | 2025      |
| 2000003+              | P_SCN2_A3   | Imran Shek     | job_scam        | 2025      |
| 2000004+              | P_SCN2_A4   | Imran S.       | investment_scam | 2026 LIVE |

### Shared Identifiers (binding all 4 alias nodes)
- `DEV_IMEI_02 = 351756078901234` — USES edge from each alias Person
- `UPI_02 = imran.transactions@axl` — USES edge from each alias Person
- `PHONE_02 = 9611234567` — USES edge from each alias Person

### Ground truth
- All 4 alias nodes are ONE physical person.
- `true_merged_case_count = 4` (1 loan_app + 1 otp_fraud + 1 job_scam + 1 investment_scam)
- Platform must resolve at runtime via entity resolution; NO RESOLVED_AS pre-baked.
- **Live Accused P_SCN2_A4 ("Imran S.")** has its own `AccusedMasterID`, shares
  `DEV_IMEI_02`/`UPI_02` with historical aliases via USES edges. Un-merged.

---

## Scenario 3 — Follow the Money (bridge account)

### Historical Cases (2 FIRs)
| CaseMasterID (INT) | Logical Key     | District    | Notes                          |
|--------------------|-----------------|-------------|--------------------------------|
| 1000007+           | FIR_SCN3_H01   | Belagavi    | BRIDGE_ACC_03 in transaction ledger |
| 1000008+           | FIR_SCN3_H02   | Hubballi-Dharwad | HUB_ACC_03 anchor FIR      |

### Bridge Account
- `BRIDGE_ACC_03 = 5530123456789001` (Union Bank, UBIN0557301, Belagavi branch)
- Pre-loaded as flagged mule; no link until live Dharwad case is uploaded.
- **Live Reveal**: Scn3 live case routes funds through `BRIDGE_ACC_03` -> platform
  graphs the bridge, showing Bengaluru->Belagavi->Dharwad money flow.
- ~Rs 6,20,000 still in a downstream account (freezable amount, demo beat).

---

## Scenario 4 — The Surge (spike detection)

### Burst Ring (14 FIRs, last 21 days)
- All share identifiers from `DEV_POOL_04` and `IP_POOL_04`.
- `MULE_SET_04` contains the mule accounts for this ring.
- Pre-loaded community is discoverable at runtime via graph community detection.

### Baseline (5 FIRs, Jan-May 2026)
- **Independent identifiers** — do NOT use DEV_POOL_04/IP_POOL_04/MULE_SET_04.
- Purpose: establish baseline for spike detection (weekly count comparison).
- Platform's spike detection should show weekly count rising sharply in last 21 days.

### Ground truth
- Community centroid: task_scam ring.
- Ringleader identity: not pre-loaded; revealed only via live IR.

---

## Caste / Religion exclusion rule
Caste (`CasteID`) and Religion (`ReligionID`) are populated on `ComplainantDetails`,
`Victim`, and `Accused` rows for KSP schema conformance ONLY.
These fields MUST be excluded from all platform demographic analysis, visualisations,
and exports. Segment demographic analysis exclusively by: age, gender, occupation, education.

---

## KSP-core vs Extension split
| Layer         | Tables                                                                              | PK type |
|---------------|-------------------------------------------------------------------------------------|---------|
| KSP core      | CaseMaster, ComplainantDetails, Victim, Accused, ArrestSurrender,                   | INT     |
|               | ActSectionAssociation, ChargesheetDetails + all master/lookup tables                |         |
| Extension     | EXT_Account, EXT_Transaction, EXT_Phone, EXT_Device, EXT_UPI, EXT_IP, EXT_Wallet,  | natural |
|               | EXT_InvestigationReport, EXT_CaseGeo (pincode), plus link tables:                  | string  |
|               | EXT_Uses, EXT_Mentions, EXT_AccusedIn, EXT_ComplainantIn                            |         |
| Foreign keys  | Extension FKs to KSP: CaseMaster.CaseMasterID, Accused.AccusedMasterID             | INT     |

## Two-Route Model Summary
| Artifact              | Historical route           | Demo route                         |
|-----------------------|----------------------------|------------------------------------|
| Documents             | output/historical/docs/    | output/live_demo/live_scnN/        |
| SQL CSVs              | output/historical/sql/     | (none — not pre-loaded)            |
| SQLite DB             | output/historical/db/ksp.sqlite | (never loaded)                |
| Graph Neo4j CSVs      | output/historical/graph/   | (derived from DB after demo ingest)|
| Vector JSONL          | output/historical/vector/  | (populated after demo ingest)      |
| Ground-truth contract | (manifests in planted_links.md) | output/live_demo/*/fir.expected.json |

## Dimension Table Deduplication Invariant
Every unique account number, IMEI, UPI, phone number, IP address, and wallet address
has exactly ONE row in its dimension table. Link/fact tables FK to the natural key.
This is enforced by `dimension_utils.dedup_corpus()` called in `stage_entities`.
Validation Suite F checks this invariant.

---
*Generated manifest — do NOT edit by hand. Updated by generate.py run summary.*
