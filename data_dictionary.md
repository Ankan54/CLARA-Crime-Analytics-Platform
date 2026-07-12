# data_dictionary.md — Field-level documentation for the KSP Crime Intelligence Platform dataset

## Architecture: SQL DB as Single Source of Truth (Two-Route Model)

```
Historical Route (pre-loaded)          Demo Route (held-back for live pipeline demo)
─────────────────────────────          ─────────────────────────────────────────────
generate.py stages:                     generate.py stages:
  entities → historical_docs              live_docs (stage 10)
  → sql_csv → db_load                       └─ fir.txt, fir.kn.txt
  → graph_from_db                           └─ fir.expected.json
  → vector_embed_docs                       └─ investigation_report.txt
                                            └─ ir.expected.json
output/historical/
  docs/<CrimeNo>/fir.txt              output/live_demo/live_scn{1-4}/
  docs/<CrimeNo>/investigation_report.txt    fir.txt
  sql/ksp/*.csv (KSP-core)                   fir.expected.json
  sql/ksp/master/*.csv                       ir.expected.json
  sql/extension/*.csv
  db/ksp.sqlite  ◄─ canonical source  NEVER loaded into ksp.sqlite
  db/schema.sql     for graph build
  graph/nodes_*.csv
  graph/rels_*.csv
  graph/import.cypher
  vector/narratives.jsonl
```

**Both routes produce the same artifact shape. They differ only in who does the extraction:**
- Historical: generator creates docs + SQL rows + loads DB → graph and vector are derived from the loaded DB.
- Demo: generator creates held-back docs + `*.expected.json`. The ingestion pipeline (next step) does the extraction.

The graph is always built from `ksp.sqlite` via `graph_builder.py`, never from in-memory objects.

---

## KSP Core Tables

### CaseMaster
| Column              | Type         | Description                                                         |
|---------------------|--------------|---------------------------------------------------------------------|
| CaseMasterID        | INT PK       | Assigned by id_registry (base 1_000_000). Authoritative ID.         |
| CrimeNo             | VARCHAR(18)  | Format: C(1)+DistrictID(4)+UnitID(4)+Year(4)+Serial(5). E.g. `129011009202600001` |
| CaseNo              | VARCHAR(9)   | Last 9 digits of CrimeNo (Year(4)+Serial(5))                       |
| CrimeRegisteredDate | DATETIME     | ISO 8601 datetime of FIR registration                              |
| PolicePersonID      | INT FK       | -> Employee.EmployeeID (IO officer)                                 |
| PoliceStationID     | INT FK       | -> Unit.UnitID (police station)                                     |
| CaseCategoryID      | INT FK       | -> CaseCategory (1=FIR, 3=UDR, 4=PAR, 8=ZeroFIR). Default: 1      |
| GravityOffenceID    | INT FK       | -> GravityOffence (1=Heinous, 2=Non-Heinous, 3=Economic)           |
| CrimeMajorHeadID    | INT FK       | -> CrimeHead (101=Cyber Crime, 102=Economic Offences)              |
| CrimeMinorHeadID    | INT FK       | -> CrimeSubHead (1011-1020, one per crime_type code)               |
| CaseStatusID        | INT FK       | -> CaseStatusMaster (1=Under Investigation, 2=Charge Sheeted, 3=Undetected) |
| CourtID             | INT FK       | -> Court (derived from Unit.DistrictID)                            |
| IncidentFromDate    | DATETIME     | Start of offence period                                            |
| IncidentToDate      | DATETIME     | End of offence period                                              |
| InfoReceivedPSDate  | DATETIME     | When police station received the complaint                         |
| Latitude            | FLOAT        | Incident latitude (centroid of district for privacy)               |
| Longitude           | FLOAT        | Incident longitude                                                 |
| BriefFacts          | NVARCHAR(MAX)| Full narrative text (English for historical; Kannada for live FIRs). Embedded as FULL doc in vector store. |

**NOTE**: `pincode` is NOT on CaseMaster. It lives in `EXT_CaseGeo` (extension table).
District is derived via `PoliceStationID` → `Unit.DistrictID` (no direct DistrictID column on CaseMaster).

### ComplainantDetails / Victim / Accused
- `AccusedMasterID`: INT PK (base 2_000_000). Live accused have own AccusedMasterID. **NO pre-merging.**
- `ComplainantID`: INT PK (base 3_000_000).
- `VictimMasterID`: INT PK (base 4_000_000).
- `PersonID` (on Accused): VARCHAR label like "A1", "A2" within a case. Does NOT imply identity across cases.
- `VictimPolice` (on Victim): INT FK → Employee.EmployeeID (officer who recorded victim statement).
- `CasteID` / `ReligionID`: populated for KSP schema conformance ONLY.
  **Excluded from all platform demographic analysis.** Segment only by age/gender/occupation/education.

### ArrestSurrender
Full ER set of 12 columns including `IsAccused`, `IsComplainantAccused`, `IOID`.
One row per accused-case arrest/surrender event.

### ActSectionAssociation
Composite key: (`CaseMasterID`, `ActCode`, `SectionCode`, `ActOrderID`, `SectionOrderID`).
- `ActCode` (VARCHAR FK → Act.ActCode): "ITACT", "BNS", "PMLA", "BSA", "BNSS"
- `SectionCode` (VARCHAR FK → Section.SectionCode): "66C", "66D", "318", "319", "3", "63", etc.
- `ActOrderID` / `SectionOrderID`: ordering within a case.

### ChargesheetDetails
- `CSType`: "C" (Undetected ~85%), "A" (Charge Sheeted ~10%), "B" (False ~5%)
  Reflects low cyber-crime detection rate. Distribution set in `config.CSTYPE_DISTRIBUTION`.

---

## Master / Lookup Tables

| Table              | Description                                      |
|--------------------|--------------------------------------------------|
| State              | StateID=29 Karnataka                             |
| District           | 31 districts, 4-digit DistrictID (2901-2931)     |
| Unit               | 30 police stations, 4-digit UnitID (1001-1030)   |
| UnitType           | 1=Police Station, 2=CEN, 3=Cyber, 4=DHQ          |
| Rank / Designation | IO rank and designation lookup                   |
| Employee           | 12 IO officers with UnitID/RankID/DistrictID; ER cols: KGID, FirstName, EmployeeDOB, GenderID |
| Court              | 10 courts, one per anchor district               |
| CaseCategory       | FIR=1, UDR=3, PAR=4, ZeroFIR=8 (LookupValue populated) |
| GravityOffence     | Heinous=1, Non-Heinous=2, Economic=3 (LookupValue populated) |
| CrimeHead          | CrimeGroupName field; Cyber Crime=101, Economic Offences=102 |
| CrimeSubHead       | CrimeHeadName + SeqID; 10 rows (IDs 1011-1020) |
| CrimeHeadActSection| Maps CrimeHeadID → ActCode/SectionCode (canonical mappings) |
| CaseStatusMaster   | Under Investigation=1, Charge Sheeted=2, Undetected=3 |
| Act                | ActCode (VARCHAR PK), ActDescription, ShortName, Active |
| Section            | SectionCode (VARCHAR PK), SectionDescription, Active |
| CasteMaster        | caste_master_id, caste_master_name: General=1…NS=5 |
| ReligionMaster     | Hindu=1, Muslim=2, Christian=3, Other=4, NS=5   |
| OccupationMaster   | 39 occupations (seeded from config.DEMOGRAPHICS_BY_ROLE) |

---

## Extension Tables (FK to KSP core)

Extension tables are **additive** — they never alter KSP-ER columns. They carry the
platform-specific forensic and digital identifiers that the ER does not model.

### Dimension Tables (one row per unique natural key — deduplication enforced)
| Table           | Natural Key (PK) | Description                        |
|-----------------|------------------|------------------------------------|
| EXT_Account     | AccountNo        | Bank account dimension             |
| EXT_Phone       | Number           | Phone number dimension             |
| EXT_Device      | IMEI             | Device (handset) dimension         |
| EXT_UPI         | VPA              | UPI VPA dimension                  |
| EXT_IP          | IPAddress        | IP address dimension               |
| EXT_Wallet      | Address          | Crypto wallet dimension            |

**Critical**: Each dimension table has exactly ONE row per unique value. Link/fact tables
FK to these natural keys. This ensures identifiers survive the SQL round-trip and graph
nodes can be MERGE'd on the natural key during `graph_builder.py`.

### Link / Fact Tables (with context columns)
| Table              | FK to                          | Context columns                          |
|--------------------|--------------------------------|------------------------------------------|
| EXT_Transaction    | EXT_Account (From/To), CaseMasterID | source_caseid, observed_date, confidence, amount, channel |
| EXT_Uses           | Accused/Complainant + EXT_*    | source_caseid, observed_date, confidence, role |
| EXT_Mentions       | CaseMaster + EXT_*             | source_caseid, observed_date, confidence, role |
| EXT_AccusedIn      | Accused + CaseMaster           | source_caseid, observed_date, confidence, role |
| EXT_ComplainantIn  | ComplainantDetails + CaseMaster| source_caseid, observed_date, confidence |

### Other Extension Tables
| Table                  | FK to         | Description                                      |
|------------------------|---------------|--------------------------------------------------|
| EXT_CaseGeo            | CaseMasterID  | Pincode + precise incident coordinates           |
| EXT_InvestigationReport| CaseMasterID  | IR text, date, IO officer                        |
| EXT_VictimDetail       | VictimMasterID| Extended victim attributes                       |
| EXT_AccusedDetail      | AccusedMasterID| Extended accused attributes                     |
| EXT_LegalElement       | (section_id)  | Ingredient elements of a section                |
| EXT_EvidenceType       | (standalone)  | Evidence type catalogue                          |
| EXT_Precedent          | (section_id)  | Case law citations                               |
| EXT_IPCSection         | (standalone)  | Legacy IPC section cross-reference              |

---

## Graph Layer

Built by `graph_builder.py` reading `ksp.sqlite`. Uses **MERGE semantics** on natural keys
for object nodes, so each unique identifier maps to exactly one node.

| Node Label    | node_id                     | Source table               |
|---------------|-----------------------------|----------------------------|
| Crime         | INT CaseMasterID            | CaseMaster                 |
| Person        | `ACC:<AccusedMasterID>`     | Accused (KSP core)         |
| Person        | `COMP:<ComplainantID>`      | ComplainantDetails         |
| Account       | AccountNo (natural key)     | EXT_Account                |
| Phone         | Number (natural key)        | EXT_Phone                  |
| Device        | IMEI (natural key)          | EXT_Device                 |
| UPI           | VPA (natural key)           | EXT_UPI                    |
| IP            | IPAddress (natural key)     | EXT_IP                     |
| Wallet        | Address (natural key)       | EXT_Wallet                 |

### Context properties on discovery-critical edges
Every `USES`, `MENTIONS`, `COMPLAINANT_IN`, `ACCUSED_IN`, `TRANSFERRED_TO` edge carries:
- `source_caseid`: INT CaseMasterID of the document/case that asserted this link
- `observed_date`: ISO date when the link was recorded in the FIR/IR
- `confidence`: 1.0 for directly-stated facts, lower for inferred links
- `role`: functional role label (e.g. "mule", "controller", "victim") where applicable
- `amount`/`channel`: on TRANSFERRED_TO edges

### Four context kinds (all present)
1. **Provenance**: `source_caseid` on every edge
2. **Edge qualifiers**: `confidence`, `role` on every link
3. **Time/place**: `observed_date`, `Timestamp` on transaction edges
4. **Legal meaning**: `ActCode`+`SectionCode` on `CHARGED_UNDER` edges from `ActSectionAssociation`

### Prohibited (NEVER pre-baked into the graph)
- `RESOLVED_AS` — entity resolution is the platform's job
- `LINKED_TO` — case linkage is the platform's job
- `centrality` property — computed by GDS at load time
- `community_id` property — computed by GDS at load time

---

## Vector Store

Full documents are embedded (not just `BriefFacts`).

| Field      | Value                                                           |
|------------|-----------------------------------------------------------------|
| node_id    | INT CaseMasterID (for FIRs)                                     |
| node_id    | `IR:<ReportID>` (for investigation reports)                     |
| text       | Full `fir.txt` content (includes all SQL fields verbatim)       |
| metadata.CrimeNo | Crime number                                              |
| metadata.district | District name derived via Unit.DistrictID                |
| metadata.crime_type | Crime type code                                        |
| metadata.CrimeRegisteredDate | ISO registration date                         |
| metadata.lang | Language (`en` for historical, `kn` for Kannada variants)  |
| metadata.doc_type | `"fir"` or `"ir"`                                       |

---

## Historical Document Structure

Every historical case emits two documents under `output/historical/docs/<CrimeNo>/`:

```
output/historical/docs/129011009202600001/
  fir.txt                    ← Full FIR with header block; all SQL identifiers verbatim
  investigation_report.txt   ← Full IR; reveals digital forensics findings
```

**Document invariant**: Every field loaded into SQL (CrimeNo, CaseMasterID, AccountNo,
IMEI, etc.) appears verbatim in the corresponding document. This allows doc↔SQL consistency
validation and supports the demo ingestion pipeline.

---

## Live Document Contract

Each live demo scenario (`output/live_demo/live_scn{1-4}/`) emits:
- `fir.txt` — English FIR with realistic KSP header block (Police Station, District,
  **pre-assigned CrimeNo**, dates, complainant, accused, charged sections)
- `fir.kn.txt` — Kannada translation (Bedrock Claude). Identifiers preserved byte-for-byte.
- `fir.kn_backtranslation.txt` — English back-translation for verification
- `investigation_report.txt` — reveals live-only identifiers (controller, bridge account)
- `fir.expected.json` — ground-truth extraction target for the ingestion pipeline:
  - KSP-core fields: CrimeNo, PoliceStationID, CaseCategoryID, CaseStatusID, accused names,
    charged sections
  - Extension fields: account numbers, IMEIs, UPIs (must byte-match historical pool values)
  - Connectivity assertions: `connects_to` (historical CaseMasterID via which identifier)
- `ir.expected.json` — ground-truth target for IR ingestion

**Live CrimeNo reservation**: `id_registry.reserve_live_cases()` is called at the start
of the pipeline (stage `reference`), allocating live CrimeNos before historical assignments
begin. This guarantees no collision and allows live FIR headers to be self-consistent.

**Live identifier linking**: Live docs must use the **same literal identifier values**
(account numbers, IMEIs, UPIs) already present in historical extension data. When the
ingestion pipeline creates these nodes, graph `MERGE` on the natural key forms the link.

**Live Accused invariant**: Live accused rows have their own `AccusedMasterID` (never
pre-merged). They share identifiers with historical aliases via `USES` edges, which the
platform resolves at runtime.

---

## SQLite DB (`ksp.sqlite`)

`output/historical/db/ksp.sqlite` is the canonical source layer.

- Built by `db_loader.py` from `schema.sql` + CSVs
- `PRAGMA foreign_keys = ON` enforced; build fails on any FK violation
- `PRAGMA foreign_key_check` must return 0 rows
- Graph is built by reading this DB, never from in-memory generator objects
- Live demo data is **never** loaded here (Suite H validation enforces this)

`output/historical/db/schema.sql` contains DDL for:
- All KSP-ER tables (byte-faithful to ER diagram)
- All extension tables (additive, EXT_ prefix)
- All PK/FK constraints

---
*Last updated: two-route model (sql_source_layer plan). Generated by the KSP synthetic data pipeline.*


---

## KSP Core Tables

### CaseMaster
| Column              | Type         | Description                                                         |
|---------------------|--------------|---------------------------------------------------------------------|
| CaseMasterID        | INT PK       | Assigned by id_registry (base 1_000_000). Authoritative ID.         |
| CrimeNo             | VARCHAR(18)  | Format: C(1)+DistrictID(4)+UnitID(4)+Year(4)+Serial(5). E.g. `129011009202600001` |
| CaseNo              | VARCHAR(9)   | Last 9 digits of CrimeNo (Year(4)+Serial(5))                       |
| CrimeRegisteredDate | DATETIME     | ISO 8601 datetime of FIR registration                              |
| PolicePersonID      | INT FK       | -> Employee.EmployeeID (IO officer)                                 |
| PoliceStationID     | INT FK       | -> Unit.UnitID (police station)                                     |
| CaseCategoryID      | INT FK       | -> CaseCategory (1=FIR, 3=UDR, 4=PAR, 8=ZeroFIR). Default: 1      |
| GravityOffenceID    | INT FK       | -> GravityOffence (1=Heinous, 2=Non-Heinous, 3=Economic)           |
| CrimeMajorHeadID    | INT FK       | -> CrimeHead (101=Cyber Crime, 102=Economic Offences)              |
| CrimeMinorHeadID    | INT FK       | -> CrimeSubHead (1011-1020, one per crime_type code)               |
| CaseStatusID        | INT FK       | -> CaseStatusMaster (1=Under Investigation, 2=Charge Sheeted, 3=Undetected) |
| CourtID             | INT FK       | -> Court (derived from Unit.DistrictID)                            |
| IncidentFromDate    | DATETIME     | Start of offence period                                            |
| IncidentToDate      | DATETIME     | End of offence period                                              |
| InfoReceivedPSDate  | DATETIME     | When police station received the complaint                         |
| Latitude            | FLOAT        | Incident latitude (centroid of district for privacy)               |
| Longitude           | FLOAT        | Incident longitude                                                 |
| BriefFacts          | NVARCHAR(MAX)| Narrative text (English for historical; Kannada for live FIRs). Embedded in vector store. |

**NOTE**: `pincode` is NOT on CaseMaster. It lives in `CaseGeo` (extension table).

### ComplainantDetails / Victim / Accused
- `AccusedMasterID`: INT PK (base 2_000_000). Live accused have own AccusedMasterID. NO pre-merging.
- `ComplainantID`: INT PK (base 3_000_000).
- `VictimMasterID`: INT PK (base 4_000_000).
- `CasteID` / `ReligionID`: populated for KSP schema conformance ONLY.
  **Excluded from all platform demographic analysis.** Segment only by age/gender/occupation/education.
- `PersonIDLabel`: "A1", "A2", etc. within a case. Does NOT imply identity across cases.

### ActSectionAssociation
- `ActCode` (VARCHAR FK -> Act): "ITACT", "BNS", "PMLA", "BSA", "BNSS"
- `SectionCode` (VARCHAR FK -> Section): "66C", "66D", "318", "319", "3", "63", etc.
- One row per (case, act/section) combination.

### ChargesheetDetails
- `CSType`: "C" (Undetected ~85%), "A" (Charge Sheeted ~10%), "B" (False ~5%)
  Reflects low cyber-crime detection rate. Distribution set in `config.CSTYPE_DISTRIBUTION`.

---

## Master / Lookup Tables

| Table              | Description                                      |
|--------------------|--------------------------------------------------|
| State              | StateID=29 Karnataka                             |
| District           | 31 districts, 4-digit DistrictID (2901-2931)     |
| Unit               | 30 police stations, 4-digit UnitID (1001-1030)   |
| UnitType           | 1=Police Station, 2=CEN, 3=Cyber, 4=DHQ          |
| Rank / Designation | IO rank and designation lookup                   |
| Employee           | 12 IO officers with UnitID/RankID/DistrictID     |
| Court              | 10 courts, one per anchor district               |
| CaseCategory       | FIR=1, UDR=3, PAR=4, ZeroFIR=8                  |
| GravityOffence     | Heinous=1, Non-Heinous=2, Economic=3             |
| CrimeHead          | Cyber Crime=101, Economic Offences=102           |
| CrimeSubHead       | 10 rows (one per crime_type code, IDs 1011-1020) |
| CrimeHeadActSection| Canonical crime_type -> Act/Section mappings     |
| CaseStatusMaster   | Under Investigation=1, Charge Sheeted=2, Undetected=3 |
| Act                | ITACT, BNS, PMLA, BSA, BNSS                     |
| Section            | 10 sections (66C, 66D, 43, 72, 318, 319, 3, 63, 94, 175) |
| CasteMaster        | General=1, OBC=2, SC=3, ST=4, Not Specified=5   |
| ReligionMaster     | Hindu=1, Muslim=2, Christian=3, Other=4, NS=5   |
| OccupationMaster   | 39 occupations (seeded from config.DEMOGRAPHICS_BY_ROLE) |

---

## Extension Tables (FK to KSP core)

| Table              | FK to               | Key identifier fields     |
|--------------------|---------------------|---------------------------|
| Account            | (standalone)        | account_no, ifsc, bank    |
| Transaction        | CaseMasterID        | txn_id, from/to account   |
| Phone              | (standalone)        | phone_id, number          |
| Device             | (standalone)        | device_id, imei           |
| UPI                | (standalone)        | upi_id, vpa               |
| IP                 | (standalone)        | ip_id, ip_address         |
| Wallet             | (standalone)        | wallet_id, address, chain |
| CaseGeo            | CaseMasterID        | pincode, incident_district|
| InvestigationReport| CaseMasterID        | report_id, report_date    |
| Evidence           | CaseMasterID        | evidence_id, admissible   |
| LegalElement       | (section_id)        | element_id, name          |
| EvidenceType       | (standalone)        | evidence_type_id, name    |
| Precedent          | (section_id, element_id) | precedent_id, citation |
| IPCSection         | (standalone)        | ipc_section_id, number    |

---

## Graph Layer

| Node Label    | node_id                  | Source                    |
|---------------|--------------------------|---------------------------|
| Crime         | INT CaseMasterID         | CaseMaster                |
| Person        | ACC:<AccusedMasterID>    | Accused (KSP core)        |
| Person        | COMP:<ComplainantID>     | ComplainantDetails        |
| Account       | account_no               | Extension Account         |
| Phone         | phone_id                 | Extension Phone           |
| Device        | device_id                | Extension Device          |
| UPI           | upi_id                   | Extension UPI             |
| IP            | ip_id                    | Extension IP              |
| Wallet        | wallet_id                | Extension Wallet          |
| Section       | section_id (e.g. IT_66C) | LegalSection (extension)  |

### Context properties on discovery-critical edges
Every `USES`, `MENTIONS`, `COMPLAINANT_IN`, `ACCUSED_IN`, `TRANSFERRED_TO` edge carries:
- `source_fir_id`: INT CaseMasterID of the document that asserted this link
- `observed_date`: ISO date when the link was recorded
- `confidence`: 1.0 for directly-stated, lower for inferred

### Prohibited edges (NEVER pre-baked)
- `RESOLVED_AS` — entity resolution is the platform's job
- `LINKED_TO` — case linkage is the platform's job
- `centrality` property — computed by GDS at load time
- `community_id` property — computed by GDS at load time

---

## Vector Store

| Field      | Value                              |
|------------|------------------------------------|
| node_id    | INT CaseMasterID (for FIRs)        |
| node_id    | `IR:<ReportID>` (for IRs)          |
| text       | BriefFacts narrative (English)     |
| metadata   | CrimeNo, district_id, crime_type, CrimeRegisteredDate, lang |

---

## Live Document Contract

Each live demo scenario emits:
- `fir.txt` — English FIR with realistic header block (Police Station, District,
  CrimeNo, CaseNo, dates, complainant, accused, sections)
- `fir.kn.txt` — Kannada translation (Bedrock Sonnet). Identifiers preserved verbatim.
- `fir.kn_backtranslation.txt` — English back-translation for verification
- `investigation_report.txt` — reveals live-only identifiers
- `fir.expected.json` — ground-truth extraction target for ingestion pipeline
- `ir.expected.json` — ground-truth target for IR ingestion

CrimeNos for live FIRs are RESERVED at generation time via `id_registry.reserve_live_cases()`
before historical assignments begin, ensuring no collision.

---
*This data dictionary was generated by the KSP Schema Integration plan (334bd6c5).*
