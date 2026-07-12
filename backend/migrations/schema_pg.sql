-- KSP Catalyst ingestion schema for PostgreSQL.
-- Includes:
--   1) KSP core/master tables (ported from sample_data/historical/db/schema.sql)
--   2) Existing out-of-pipeline EXT_* tables kept as-is
--   3) Spec Section 4.2 operational + extension tables (EntityMap, PipelineRun, etc.)

-- ============================================================
-- KSP MASTER / LOOKUP TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS State (
    StateID   INTEGER PRIMARY KEY,
    StateName TEXT    NOT NULL,
    Active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS District (
    DistrictID   INTEGER PRIMARY KEY,
    DistrictName TEXT    NOT NULL,
    StateID      INTEGER NOT NULL REFERENCES State(StateID),
    Active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS UnitType (
    UnitTypeID    INTEGER PRIMARY KEY,
    UnitTypeName  TEXT    NOT NULL,
    CityDistState TEXT,
    Hierarchy     INTEGER,
    Active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Unit (
    UnitID        INTEGER PRIMARY KEY,
    UnitName      TEXT    NOT NULL,
    TypeID        INTEGER NOT NULL REFERENCES UnitType(UnitTypeID),
    ParentUnit    INTEGER REFERENCES Unit(UnitID),
    NationalityID INTEGER,
    StateID       INTEGER NOT NULL REFERENCES State(StateID),
    DistrictID    INTEGER NOT NULL REFERENCES District(DistrictID),
    Active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Rank (
    RankID    INTEGER PRIMARY KEY,
    RankName  TEXT    NOT NULL,
    Hierarchy INTEGER,
    Active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Designation (
    DesignationID   INTEGER PRIMARY KEY,
    DesignationName TEXT    NOT NULL,
    Active          INTEGER NOT NULL DEFAULT 1,
    SortOrder       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS Employee (
    EmployeeID           INTEGER PRIMARY KEY,
    DistrictID           INTEGER NOT NULL REFERENCES District(DistrictID),
    UnitID               INTEGER NOT NULL REFERENCES Unit(UnitID),
    RankID               INTEGER NOT NULL REFERENCES Rank(RankID),
    DesignationID        INTEGER NOT NULL REFERENCES Designation(DesignationID),
    KGID                 TEXT,
    FirstName            TEXT    NOT NULL,
    EmployeeDOB          DATE,
    GenderID             INTEGER,
    BloodGroupID         INTEGER,
    PhysicallyChallenged INTEGER DEFAULT 0,
    AppointmentDate      DATE
);

CREATE TABLE IF NOT EXISTS Court (
    CourtID    INTEGER PRIMARY KEY,
    CourtName  TEXT    NOT NULL,
    DistrictID INTEGER NOT NULL REFERENCES District(DistrictID),
    StateID    INTEGER NOT NULL REFERENCES State(StateID),
    Active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS CaseCategory (
    CaseCategoryID INTEGER PRIMARY KEY,
    LookupValue    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS GravityOffence (
    GravityOffenceID INTEGER PRIMARY KEY,
    LookupValue      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS CaseStatusMaster (
    CaseStatusID   INTEGER PRIMARY KEY,
    CaseStatusName TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS CrimeHead (
    CrimeHeadID    INTEGER PRIMARY KEY,
    CrimeGroupName TEXT    NOT NULL,
    Active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS CrimeSubHead (
    CrimeSubHeadID INTEGER PRIMARY KEY,
    CrimeHeadID    INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    CrimeHeadName  TEXT    NOT NULL,
    SeqID          INTEGER DEFAULT 0,
    Active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Act (
    ActCode        TEXT PRIMARY KEY,
    ActDescription TEXT NOT NULL,
    ShortName      TEXT,
    Active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Section (
    ActCode            TEXT NOT NULL REFERENCES Act(ActCode),
    SectionCode        TEXT NOT NULL,
    SectionDescription TEXT NOT NULL,
    Active             INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (ActCode, SectionCode)
);

CREATE TABLE IF NOT EXISTS CrimeHeadActSection (
    CrimeHeadID INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    ActCode     TEXT    NOT NULL REFERENCES Act(ActCode),
    SectionCode TEXT    NOT NULL,
    PRIMARY KEY (CrimeHeadID, ActCode, SectionCode),
    FOREIGN KEY (ActCode, SectionCode) REFERENCES Section(ActCode, SectionCode)
);

CREATE TABLE IF NOT EXISTS CasteMaster (
    caste_master_id   INTEGER PRIMARY KEY,
    caste_master_name TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ReligionMaster (
    ReligionID   INTEGER PRIMARY KEY,
    ReligionName TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS OccupationMaster (
    OccupationID   INTEGER PRIMARY KEY,
    OccupationName TEXT    NOT NULL
);

-- ============================================================
-- KSP CORE CASE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS CaseMaster (
    CaseMasterID        INTEGER PRIMARY KEY,
    CrimeNo             TEXT    NOT NULL UNIQUE,
    CaseNo              TEXT    NOT NULL,
    CrimeRegisteredDate TIMESTAMPTZ NOT NULL,
    PolicePersonID      INTEGER NOT NULL REFERENCES Employee(EmployeeID),
    PoliceStationID     INTEGER NOT NULL REFERENCES Unit(UnitID),
    CaseCategoryID      INTEGER NOT NULL REFERENCES CaseCategory(CaseCategoryID),
    GravityOffenceID    INTEGER NOT NULL REFERENCES GravityOffence(GravityOffenceID),
    CrimeMajorHeadID    INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    CrimeMinorHeadID    INTEGER NOT NULL REFERENCES CrimeSubHead(CrimeSubHeadID),
    CaseStatusID        INTEGER NOT NULL REFERENCES CaseStatusMaster(CaseStatusID),
    CourtID             INTEGER NOT NULL REFERENCES Court(CourtID),
    IncidentFromDate    TIMESTAMPTZ,
    IncidentToDate      TIMESTAMPTZ,
    InfoReceivedPSDate  TIMESTAMPTZ,
    Latitude            DOUBLE PRECISION,
    Longitude           DOUBLE PRECISION,
    BriefFacts          TEXT
);

CREATE TABLE IF NOT EXISTS ComplainantDetails (
    ComplainantID   INTEGER PRIMARY KEY,
    CaseMasterID    INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ComplainantName TEXT    NOT NULL,
    AgeYear         INTEGER,
    GenderID        TEXT,
    OccupationID    INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID         INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID      INTEGER REFERENCES ReligionMaster(ReligionID),
    Address         TEXT
);

CREATE TABLE IF NOT EXISTS Victim (
    VictimMasterID INTEGER PRIMARY KEY,
    CaseMasterID   INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    VictimName     TEXT    NOT NULL,
    AgeYear        INTEGER,
    GenderID       TEXT,
    VictimPolice   INTEGER REFERENCES Employee(EmployeeID)
);

CREATE TABLE IF NOT EXISTS Accused (
    AccusedMasterID INTEGER PRIMARY KEY,
    CaseMasterID    INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    PersonID        TEXT,
    AccusedName     TEXT    NOT NULL,
    AgeYear         INTEGER,
    GenderID        TEXT
);

CREATE TABLE IF NOT EXISTS ArrestSurrender (
    ArrestSurrenderID         INTEGER PRIMARY KEY,
    CaseMasterID              INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ArrestSurrenderTypeID     INTEGER,
    ArrestSurrenderDate       DATE,
    ArrestSurrenderStateId    INTEGER REFERENCES State(StateID),
    ArrestSurrenderDistrictId INTEGER REFERENCES District(DistrictID),
    PoliceStationID           INTEGER REFERENCES Unit(UnitID),
    IOID                      INTEGER REFERENCES Employee(EmployeeID),
    CourtID                   INTEGER REFERENCES Court(CourtID),
    AccusedMasterID           INTEGER NOT NULL REFERENCES Accused(AccusedMasterID),
    IsAccused                 INTEGER DEFAULT 1,
    IsComplainantAccused      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ActSectionAssociation (
    CaseMasterID   INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ActCode        TEXT    NOT NULL,
    SectionCode    TEXT    NOT NULL,
    ActOrderID     INTEGER DEFAULT 1,
    SectionOrderID INTEGER DEFAULT 1,
    PRIMARY KEY (CaseMasterID, ActCode, SectionCode),
    FOREIGN KEY (ActCode, SectionCode) REFERENCES Section(ActCode, SectionCode)
);

CREATE TABLE IF NOT EXISTS ChargesheetDetails (
    CSID           INTEGER PRIMARY KEY,
    CaseMasterID   INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    CSDate         TIMESTAMPTZ,
    CSType         TEXT    NOT NULL DEFAULT 'C',
    PolicePersonID INTEGER REFERENCES Employee(EmployeeID)
);

-- ============================================================
-- EXISTING EXTENSION TABLES KEPT AS-IS (OUT OF PIPELINE)
-- ============================================================

CREATE TABLE IF NOT EXISTS EXT_IP (
    IPAddress TEXT PRIMARY KEY,
    IPID      TEXT,
    GeoLat    DOUBLE PRECISION,
    GeoLong   DOUBLE PRECISION,
    GeoCity   TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Wallet (
    Address  TEXT PRIMARY KEY,
    WalletID TEXT,
    Chain    TEXT DEFAULT 'USDT'
);

CREATE TABLE IF NOT EXISTS EXT_Uses (
    from_person_id TEXT,
    to_object_id   TEXT,
    object_type    TEXT,
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TIMESTAMPTZ,
    confidence     DOUBLE PRECISION DEFAULT 1.0,
    role           TEXT,
    PRIMARY KEY (from_person_id, to_object_id, object_type)
);

CREATE TABLE IF NOT EXISTS EXT_Mentions (
    case_master_id INTEGER REFERENCES CaseMaster(CaseMasterID),
    object_id      TEXT,
    object_type    TEXT,
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TIMESTAMPTZ,
    confidence     DOUBLE PRECISION DEFAULT 1.0,
    PRIMARY KEY (case_master_id, object_id, object_type)
);

CREATE TABLE IF NOT EXISTS EXT_AccusedIn (
    AccusedMasterID INTEGER REFERENCES Accused(AccusedMasterID),
    CaseMasterID    INTEGER REFERENCES CaseMaster(CaseMasterID),
    source_caseid   INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date   TIMESTAMPTZ,
    confidence      DOUBLE PRECISION DEFAULT 1.0,
    role            TEXT,
    PRIMARY KEY (AccusedMasterID, CaseMasterID)
);

CREATE TABLE IF NOT EXISTS EXT_ComplainantIn (
    ComplainantID INTEGER REFERENCES ComplainantDetails(ComplainantID),
    CaseMasterID  INTEGER REFERENCES CaseMaster(CaseMasterID),
    source_caseid INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date TIMESTAMPTZ,
    confidence    DOUBLE PRECISION DEFAULT 1.0,
    PRIMARY KEY (ComplainantID, CaseMasterID)
);

CREATE TABLE IF NOT EXISTS EXT_CaseGeo (
    GeoID            INTEGER PRIMARY KEY,
    CaseMasterID     INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    Pincode          TEXT,
    IncidentDistrict TEXT
);

CREATE TABLE IF NOT EXISTS EXT_VictimDetail (
    VictimMasterID     INTEGER PRIMARY KEY REFERENCES Victim(VictimMasterID),
    OccupationID       INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID            INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID         INTEGER REFERENCES ReligionMaster(ReligionID),
    Address            TEXT,
    Mobile             TEXT,
    LossAmount         INTEGER DEFAULT 0,
    ResidenceDistrict  TEXT
);

CREATE TABLE IF NOT EXISTS EXT_AccusedDetail (
    AccusedMasterID    INTEGER PRIMARY KEY REFERENCES Accused(AccusedMasterID),
    OccupationID       INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID            INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID         INTEGER REFERENCES ReligionMaster(ReligionID),
    Address            TEXT,
    IsArrested         INTEGER DEFAULT 0,
    ResidenceDistrict  TEXT
);

CREATE TABLE IF NOT EXISTS EXT_SubEvent (
    SubEventID    INTEGER PRIMARY KEY,
    CaseMasterID  INTEGER REFERENCES CaseMaster(CaseMasterID),
    Label         TEXT,
    Timestamp     TIMESTAMPTZ,
    source_caseid INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date TIMESTAMPTZ,
    confidence    DOUBLE PRECISION DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS EXT_LegalElement (
    ElementID   TEXT PRIMARY KEY,
    SectionID   TEXT,
    Name        TEXT,
    Description TEXT
);

CREATE TABLE IF NOT EXISTS EXT_EvidenceType (
    EvidenceTypeID        TEXT PRIMARY KEY,
    Name                  TEXT,
    Description           TEXT,
    Requires63Certificate INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_Precedent (
    PrecedentID     TEXT PRIMARY KEY,
    CaseName        TEXT,
    Citation        TEXT,
    Year            INTEGER,
    Court           TEXT,
    Outcome         TEXT,
    ElementTurnedOn TEXT,
    SectionID       TEXT,
    HoldingSummary  TEXT,
    IsOverruled     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_IPCSection (
    IPCSectionID  TEXT PRIMARY KEY,
    SectionNumber TEXT,
    Title         TEXT
);

-- ============================================================
-- SPEC SECTION 4.2 TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS SchemaDefinition (
    schema_id                BIGSERIAL PRIMARY KEY,
    doc_type                 TEXT NOT NULL,
    version                  INTEGER NOT NULL,
    is_active                BOOLEAN NOT NULL DEFAULT FALSE,
    description              TEXT,
    allowed_file_extensions  TEXT NOT NULL,
    max_file_size_mb         INTEGER NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by               TEXT,
    UNIQUE (doc_type, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_schemadef_doc_active
    ON SchemaDefinition(doc_type)
    WHERE is_active = true;

CREATE TABLE IF NOT EXISTS BatchUpload (
    batch_id     UUID PRIMARY KEY,
    case_id      INTEGER REFERENCES CaseMaster(CaseMasterID),
    uploaded_by  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Grain changed from per-file to per-process-run (raw/processed/archive rework).
-- Demo DB is synthetic, so drop+recreate rather than in-place ALTER.
DROP TABLE IF EXISTS ReviewQueueItem;
DROP TABLE IF EXISTS PipelineRun;

CREATE TABLE IF NOT EXISTS PipelineRun (
    run_id            TEXT PRIMARY KEY,              -- {case_id}_{YYYYMMDDTHHMMSSZ}
    batch_id          UUID NOT NULL REFERENCES BatchUpload(batch_id),
    case_id           INTEGER REFERENCES CaseMaster(CaseMasterID),
    phase             TEXT NOT NULL DEFAULT 'EXTRACT' CHECK (phase IN ('EXTRACT', 'REVIEW', 'LOAD', 'DONE')),
    checkpoint_prefix TEXT,                           -- processed/{case_id}/{run_id}/
    files_progress    JSONB NOT NULL DEFAULT '{}'::jsonb, -- {filename: {stage, status}} for WS badges
    current_stage     TEXT NOT NULL DEFAULT 'QUEUED',
    status            TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'REVIEW_PENDING', 'COMPLETED', 'COMPLETED_WITH_REVIEW_PENDING', 'FAILED')),
    error_stage       TEXT,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipelinerun_batch_id ON PipelineRun(batch_id);
CREATE INDEX IF NOT EXISTS idx_pipelinerun_status ON PipelineRun(status);
CREATE INDEX IF NOT EXISTS idx_pipelinerun_case_id ON PipelineRun(case_id);

CREATE TABLE IF NOT EXISTS Evidence (
    evidence_id                 BIGSERIAL PRIMARY KEY,
    case_id                     INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    doc_type                    TEXT,
    file_ref                    TEXT NOT NULL,
    original_filename           TEXT NOT NULL,
    extraction_status           TEXT NOT NULL CHECK (extraction_status IN ('success', 'partial', 'no_structured_data', 'failed')),
    extraction_confidence_avg   DOUBLE PRECISION,
    schema_id_used              BIGINT REFERENCES SchemaDefinition(schema_id),
    uploaded_by                 TEXT,
    upload_ts                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS InvestigationReport (
    report_id           BIGSERIAL PRIMARY KEY,
    case_id             INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    accused_id          INTEGER REFERENCES Accused(AccusedMasterID),
    report_date         DATE,
    findings_narrative  TEXT,
    filed_by            INTEGER REFERENCES Employee(EmployeeID),
    status              TEXT,
    schema_id_used      BIGINT REFERENCES SchemaDefinition(schema_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS EntityMap (
    entity_uid   UUID PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    pole_subtype TEXT NOT NULL,
    sql_table    TEXT NOT NULL,
    sql_pk       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged_away')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sql_table, sql_pk)
);

CREATE TABLE IF NOT EXISTS Device (
    device_id            BIGSERIAL PRIMARY KEY,
    imei_raw             TEXT,
    imei_normalized      TEXT,
    model                TEXT,
    holder_name_raw      TEXT,
    source_evidence_id   BIGINT REFERENCES Evidence(evidence_id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_device_imei_norm ON Device(imei_normalized);

CREATE TABLE IF NOT EXISTS Account (
    account_id                  BIGSERIAL PRIMARY KEY,
    account_number_raw          TEXT NOT NULL,
    account_number_normalized   TEXT NOT NULL,
    ifsc                        TEXT,
    bank_name                   TEXT,
    branch_name                 TEXT,
    branch_district             TEXT,
    account_type                TEXT,
    holder_name_raw             TEXT,
    holder_entity_uid           UUID REFERENCES EntityMap(entity_uid),
    account_open_date           DATE,
    kyc_name                    TEXT,
    is_flagged_mule             BOOLEAN DEFAULT FALSE,
    linked_case_id              INTEGER REFERENCES CaseMaster(CaseMasterID),
    source_evidence_id          BIGINT REFERENCES Evidence(evidence_id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_number_norm ON Account(account_number_normalized);

CREATE TABLE IF NOT EXISTS UPIHandle (
    upi_id               BIGSERIAL PRIMARY KEY,
    vpa_raw              TEXT NOT NULL,
    vpa_normalized       TEXT NOT NULL,
    holder_name_raw      TEXT,
    linked_account_id    BIGINT REFERENCES Account(account_id),
    holder_entity_uid    UUID REFERENCES EntityMap(entity_uid),
    source_evidence_id   BIGINT REFERENCES Evidence(evidence_id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_upi_vpa_norm ON UPIHandle(vpa_normalized);

CREATE TABLE IF NOT EXISTS PhoneNumber (
    phone_id             BIGSERIAL PRIMARY KEY,
    number_raw           TEXT NOT NULL,
    number_normalized    TEXT NOT NULL,
    holder_name_raw      TEXT,
    imei_ref             BIGINT REFERENCES Device(device_id),
    holder_entity_uid    UUID REFERENCES EntityMap(entity_uid),
    source_evidence_id   BIGINT REFERENCES Evidence(evidence_id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_phone_number_norm ON PhoneNumber(number_normalized);

CREATE TABLE IF NOT EXISTS Transaction (
    txn_id              BIGSERIAL PRIMARY KEY,
    from_account_id     BIGINT REFERENCES Account(account_id),
    from_upi_id         BIGINT REFERENCES UPIHandle(upi_id),
    to_account_id       BIGINT REFERENCES Account(account_id),
    to_upi_id           BIGINT REFERENCES UPIHandle(upi_id),
    amount              NUMERIC(18,2) NOT NULL,
    txn_timestamp       TIMESTAMPTZ NOT NULL,
    mode                TEXT,
    utr_ref             TEXT,
    direction           TEXT,
    source_evidence_id  BIGINT REFERENCES Evidence(evidence_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transaction_utr_ref ON Transaction(utr_ref);
CREATE INDEX IF NOT EXISTS idx_transaction_timestamp ON Transaction(txn_timestamp);

CREATE TABLE IF NOT EXISTS ReviewQueueItem (
    review_id                   BIGSERIAL PRIMARY KEY,
    source_run_id               TEXT NOT NULL REFERENCES PipelineRun(run_id),
    entity_type                 TEXT NOT NULL,
    candidate_record_json       JSONB NOT NULL,
    matched_against_entity_uid  UUID NOT NULL REFERENCES EntityMap(entity_uid),
    match_score                 DOUBLE PRECISION NOT NULL,
    matched_fields_json         JSONB,
    status                      TEXT NOT NULL CHECK (status IN ('pending', 'merged', 'kept_separate')),
    resolved_by                 TEXT,
    resolved_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reviewqueue_status ON ReviewQueueItem(status);
CREATE INDEX IF NOT EXISTS idx_reviewqueue_run_id ON ReviewQueueItem(source_run_id);

CREATE TABLE IF NOT EXISTS SchemaField (
    field_id              BIGSERIAL PRIMARY KEY,
    schema_id             BIGINT NOT NULL REFERENCES SchemaDefinition(schema_id),
    group_name            TEXT NOT NULL,
    is_repeating_group    BOOLEAN NOT NULL DEFAULT FALSE,
    pole_entity_type      TEXT,
    field_name            TEXT NOT NULL,
    data_type             TEXT NOT NULL,
    is_required           BOOLEAN NOT NULL DEFAULT FALSE,
    target_table          TEXT NOT NULL,
    target_column         TEXT NOT NULL,
    is_identifier         BOOLEAN NOT NULL DEFAULT FALSE,
    identifier_type       TEXT,
    extraction_hint       TEXT,
    display_order         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_schemafield_schema_group ON SchemaField(schema_id, group_name);

CREATE TABLE IF NOT EXISTS SchemaRelationship (
    relationship_id            BIGSERIAL PRIMARY KEY,
    schema_id                  BIGINT NOT NULL REFERENCES SchemaDefinition(schema_id),
    from_group                 TEXT NOT NULL,
    to_group                   TEXT NOT NULL,
    relationship_type          TEXT NOT NULL,
    direction                  TEXT NOT NULL DEFAULT 'from_to',
    fixed_edge_properties      JSONB,
    edge_property_source_fields TEXT
);

CREATE INDEX IF NOT EXISTS idx_schemarel_schema ON SchemaRelationship(schema_id);

CREATE TABLE IF NOT EXISTS AppConfig (
    config_key   TEXT PRIMARY KEY,
    config_value TEXT NOT NULL,
    updated_by   TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

