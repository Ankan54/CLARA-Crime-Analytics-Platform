"""Compact schema cards injected into specialist system prompts.

Each card gives the specialist enough schema knowledge to author correct SQL/Cypher/vector
queries through the generic tools, without needing the full DDL.
"""

SQL_SCHEMA_CARD = """## SQL Schema (Postgres, key tables) -- column names are exactly as written; Postgres folds unquoted identifiers to lowercase, so casing does not matter.

Core case tables:
CaseMaster(CaseMasterID PK, CrimeNo UNIQUE, CaseNo, CrimeRegisteredDate [= FIR date], PolicePersonID FK->Employee [the IO], PoliceStationID FK->Unit, CaseCategoryID FK->CaseCategory, GravityOffenceID FK->GravityOffence, CrimeMajorHeadID FK->CrimeHead, CrimeMinorHeadID FK->CrimeSubHead, CaseStatusID FK->CaseStatusMaster, CourtID FK->Court, IncidentFromDate, IncidentToDate, Latitude, Longitude, BriefFacts)
  -- CaseMaster has NO district/unit/crime-name/IO-name/status-name columns; those come from joins below.
Accused(AccusedMasterID PK, CaseMasterID FK, PersonID, AccusedName, AgeYear, GenderID)
Victim(VictimMasterID PK, CaseMasterID FK, VictimName, AgeYear, GenderID)
ComplainantDetails(ComplainantID PK, CaseMasterID FK, ComplainantName, AgeYear, GenderID, Address)
ChargesheetDetails(CSID PK, CaseMasterID FK, CSDate, CSType, PolicePersonID)

Lookups (join FROM CaseMaster):
Unit(UnitID PK, UnitName, DistrictID FK->District)          -- CaseMaster.PoliceStationID = Unit.UnitID (the POLICE-STATION district)
District(DistrictID PK, DistrictName)                        -- Unit.DistrictID = District.DistrictID
  -- For "cases by district" use the INCIDENT district (EXT_CaseGeo.IncidentDistrict) to match the query_case_stats tool; CaseMaster->Unit->District is the police-station district, a different number.
CrimeHead(CrimeHeadID PK, CrimeGroupName)                    -- CaseMaster.CrimeMajorHeadID = CrimeHead.CrimeHeadID   (crime GROUP)
CrimeSubHead(CrimeSubHeadID PK, CrimeHeadName)               -- CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID (crime TYPE/head)
CaseStatusMaster(CaseStatusID PK, CaseStatusName)            -- CaseMaster.CaseStatusID
CaseCategory(CaseCategoryID PK, LookupValue)                 -- CaseMaster.CaseCategoryID
Employee(EmployeeID PK, FirstName, DistrictID, UnitID)       -- CaseMaster.PolicePersonID = Employee.EmployeeID (the IO's name = FirstName)

Financial:
Account(account_id PK, account_number_normalized UNIQUE, account_number_raw, bank_name, ifsc, branch_district, account_type, holder_name_raw, kyc_name, holder_entity_uid, is_flagged_mule, linked_case_id [nullable; shared accounts span cases])
Transaction(txn_id PK, from_account_id FK->Account.account_id, to_account_id FK->Account.account_id, from_upi_id, to_upi_id, amount, txn_timestamp, mode, utr_ref, direction, to_wallet_address)
UPIHandle(upi_id PK, vpa_normalized UNIQUE, vpa_raw, linked_account_id FK->Account.account_id, holder_entity_uid)
Device(device_id PK, imei_normalized UNIQUE, model, holder_entity_uid)
PhoneNumber(phone_id PK, number_normalized UNIQUE, imei_ref, holder_entity_uid)

Analytics / extension:
EXT_SubEvent(SubEventID PK, CaseMasterID FK, label, timestamp, source_caseid, observed_date, confidence)
EXT_VictimDetail(VictimMasterID PK/FK, LossAmount, Mobile, ResidenceDistrict)
EXT_CaseGeo(GeoID PK, CaseMasterID FK, Pincode, IncidentDistrict)
Evidence(evidence_id PK, case_id FK->CaseMaster.CaseMasterID, doc_type, file_ref, original_filename, extraction_status, uploaded_by, upload_ts)

Legal chain (join order): ActSectionAssociation -> EXT_SectionMap -> EXT_LegalElement -> EXT_ElementSatisfiedBy -> EXT_EvidenceType; precedents via EXT_Precedent.
ActSectionAssociation(CaseMasterID FK, ActCode, SectionCode)                -- the sections charged in a case
EXT_SectionMap(ActCode, SectionCode, SectionID PK)                          -- (ActCode,SectionCode) -> SectionID
EXT_LegalElement(ElementID PK, SectionID FK, name, description)             -- what each section requires proving
EXT_ElementSatisfiedBy(ElementID FK, EvidenceTypeID FK)
EXT_EvidenceType(EvidenceTypeID PK, name, description, requires63certificate)
EXT_Precedent(PrecedentID PK, SectionID FK, casename, citation, year, court, outcome, elementturnedon, holdingsummary, isoverruled)

Join keys: CaseMaster.CaseMasterID -> Accused/Victim/ComplainantDetails/ChargesheetDetails/EXT_SubEvent/EXT_CaseGeo/ActSectionAssociation via CaseMasterID; Evidence via case_id; EXT_VictimDetail via VictimMasterID.
Transaction joins Account on from_account_id/to_account_id = Account.account_id."""

GRAPH_SCHEMA_CARD = """## Neo4j Graph Schema

Nodes (keyed by entity_uid):
- CaseMaster {entity_uid, case_id (INTEGER case id, e.g. 1000064), display_name (= crime_no)}
  - To find a case node, match on case_id or display_name, NOT entity_uid (which is a UUID):
    MATCH (c:CaseMaster {case_id: 1000064})   or   MATCH (c:CaseMaster {display_name: '129011005202690002'})
  - Its accused:  MATCH (c:CaseMaster {case_id: 1000064})<-[:INVOLVES]-(a:Accused) RETURN a.display_name
- Account {entity_uid, account_number_normalized, bank_name, holder_name_display}
- UPIHandle {entity_uid, vpa_normalized}
- Device {entity_uid, imei_normalized, device_model}
- PhoneNumber {entity_uid, number_normalized}
- Accused / Victim / ComplainantDetails {entity_uid, display_name, case_id}
  - Accused may also carry role (caller | mule_handler | recruiter | controller) when the
    person is a seized-device ring operator. For an "operator org chart / role map", match
    (op:Accused) WHERE op.role IS NOT NULL and return op.display_name, op.role, plus the
    device/UPI they OWN — that IS the org chart.

Relationships:
- (CaseMaster)-[:MENTIONS]->(Account | UPIHandle | Device | PhoneNumber)
- (Account)-[:TRANSACTED_WITH]->(Account)
- (Accused)-[:INVOLVES]->(CaseMaster)
- (Victim)-[:INVOLVES]->(CaseMaster)
- (Accused)-[:OWNS]->(Account | UPIHandle | Device | PhoneNumber) [operators OWN their device/UPI]
- (CaseMaster)-[:HAS_EVIDENCE]->(InvestigationReport) [IR files only]

MERGE key is always entity_uid (label-less MERGE). Same real-world identifier shares one node across cases.
Node display uses display_name (not name)."""

VECTOR_SCHEMA_CARD = """## Pinecone Vector Store

Index: ksp-crime-narratives (dimension=1536, metric=cosine)
Metadata fields per vector: case_id (int), crime_no (str), doc_type (fir|ir|evidence), district (str), crime_group (str), fir_date (str ISO).
Query by semantic text similarity; filter by metadata. Returns top_k matches with score 0-1 (higher = more similar)."""

SCHEMA_BY_AGENT = {
    "sql": SQL_SCHEMA_CARD,
    "legal": SQL_SCHEMA_CARD,
    "graph": GRAPH_SCHEMA_CARD,
    "vector": VECTOR_SCHEMA_CARD,
}
