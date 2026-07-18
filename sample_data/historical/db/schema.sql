-- KSP Crime Intelligence Platform - Schema DDL
-- KSP-core/master tables are ER-exact (Police_FIR_ER_Diagram.pdf).
-- Extension tables (EXT_*) are additive and documented in data_dictionary.md.
PRAGMA foreign_keys = ON;

-- ============================================================
-- KSP MASTER / LOOKUP TABLES  (ER-exact)
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
    EmployeeDOB          TEXT,
    GenderID             INTEGER,
    BloodGroupID         INTEGER,
    PhysicallyChallenged INTEGER DEFAULT 0,
    AppointmentDate      TEXT
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
    CrimeHeadID  INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    ActCode      TEXT    NOT NULL REFERENCES Act(ActCode),
    SectionCode  TEXT    NOT NULL,
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
-- KSP CORE CASE TABLES  (ER-exact)
-- ============================================================

CREATE TABLE IF NOT EXISTS CaseMaster (
    CaseMasterID        INTEGER PRIMARY KEY,
    CrimeNo             TEXT    NOT NULL UNIQUE,
    CaseNo              TEXT    NOT NULL,
    CrimeRegisteredDate TEXT    NOT NULL,
    PolicePersonID      INTEGER NOT NULL REFERENCES Employee(EmployeeID),
    PoliceStationID     INTEGER NOT NULL REFERENCES Unit(UnitID),
    CaseCategoryID      INTEGER NOT NULL REFERENCES CaseCategory(CaseCategoryID),
    GravityOffenceID    INTEGER NOT NULL REFERENCES GravityOffence(GravityOffenceID),
    CrimeMajorHeadID    INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    CrimeMinorHeadID    INTEGER NOT NULL REFERENCES CrimeSubHead(CrimeSubHeadID),
    CaseStatusID        INTEGER NOT NULL REFERENCES CaseStatusMaster(CaseStatusID),
    CourtID             INTEGER NOT NULL REFERENCES Court(CourtID),
    IncidentFromDate    TEXT,
    IncidentToDate      TEXT,
    InfoReceivedPSDate  TEXT,
    Latitude            REAL,
    Longitude           REAL,
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
    ArrestSurrenderDate       TEXT,
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
    CaseMasterID  INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ActCode       TEXT    NOT NULL,
    SectionCode   TEXT    NOT NULL,
    ActOrderID    INTEGER DEFAULT 1,
    SectionOrderID INTEGER DEFAULT 1,
    PRIMARY KEY (CaseMasterID, ActCode, SectionCode),
    FOREIGN KEY (ActCode, SectionCode) REFERENCES Section(ActCode, SectionCode)
);

CREATE TABLE IF NOT EXISTS ChargesheetDetails (
    CSID           INTEGER PRIMARY KEY,
    CaseMasterID   INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    CSDate         TEXT,
    CSType         TEXT    NOT NULL DEFAULT 'C',
    PolicePersonID INTEGER REFERENCES Employee(EmployeeID)
);

-- ============================================================
-- EXTENSION TABLES  (additive; not in KSP ER; FKs to core tables)
-- ============================================================

-- -- Dimension tables: one row per unique identifier value --

CREATE TABLE IF NOT EXISTS EXT_Account (
    AccountNo      TEXT    PRIMARY KEY,
    Bank           TEXT,
    IFSC           TEXT,
    BranchDistrict TEXT,
    AccountType    TEXT    DEFAULT 'Savings',
    OpenDate       TEXT,
    KYCName        TEXT,
    IsFlaggedMule  INTEGER DEFAULT 0,
    LastInbound    TEXT,
    LastOutbound   TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Phone (
    Number   TEXT PRIMARY KEY,
    PhoneID  TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Device (
    IMEI     TEXT PRIMARY KEY,
    DeviceID TEXT
);

CREATE TABLE IF NOT EXISTS EXT_UPI (
    VPA    TEXT PRIMARY KEY,
    UPIID  TEXT
);

CREATE TABLE IF NOT EXISTS EXT_IP (
    IPAddress TEXT PRIMARY KEY,
    IPID      TEXT,
    GeoLat    REAL,
    GeoLong   REAL,
    GeoCity   TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Wallet (
    Address   TEXT PRIMARY KEY,
    WalletID  TEXT,
    Chain     TEXT DEFAULT 'USDT'
);

-- -- Fact/link tables: FK to dimensions + context columns --

CREATE TABLE IF NOT EXISTS EXT_Transaction (
    TxnID        TEXT PRIMARY KEY,
    FromAccount  TEXT,
    ToAccount    TEXT,
    Amount       INTEGER,
    Timestamp    TEXT,
    Channel      TEXT,
    HopRole      TEXT,
    CaseMasterID INTEGER REFERENCES CaseMaster(CaseMasterID),
    -- Context columns
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TEXT,
    confidence     REAL DEFAULT 1.0,
    role           TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Uses (
    from_person_id TEXT,
    to_object_id   TEXT,
    object_type    TEXT,
    -- Context columns
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TEXT,
    confidence     REAL DEFAULT 1.0,
    role           TEXT,
    PRIMARY KEY (from_person_id, to_object_id, object_type)
);

CREATE TABLE IF NOT EXISTS EXT_Mentions (
    case_master_id INTEGER REFERENCES CaseMaster(CaseMasterID),
    object_id      TEXT,
    object_type    TEXT,
    -- Context columns
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TEXT,
    confidence     REAL DEFAULT 1.0,
    PRIMARY KEY (case_master_id, object_id, object_type)
);

CREATE TABLE IF NOT EXISTS EXT_AccusedIn (
    AccusedMasterID INTEGER REFERENCES Accused(AccusedMasterID),
    CaseMasterID    INTEGER REFERENCES CaseMaster(CaseMasterID),
    -- Context columns
    source_caseid   INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date   TEXT,
    confidence      REAL DEFAULT 1.0,
    role            TEXT,
    PRIMARY KEY (AccusedMasterID, CaseMasterID)
);

CREATE TABLE IF NOT EXISTS EXT_ComplainantIn (
    ComplainantID INTEGER REFERENCES ComplainantDetails(ComplainantID),
    CaseMasterID  INTEGER REFERENCES CaseMaster(CaseMasterID),
    -- Context columns
    source_caseid INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date TEXT,
    confidence    REAL DEFAULT 1.0,
    PRIMARY KEY (ComplainantID, CaseMasterID)
);

CREATE TABLE IF NOT EXISTS EXT_CaseGeo (
    GeoID            INTEGER PRIMARY KEY,
    CaseMasterID     INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    Pincode          TEXT,
    IncidentDistrict TEXT
);

CREATE TABLE IF NOT EXISTS EXT_InvestigationReport (
    ReportID           INTEGER PRIMARY KEY,
    CaseMasterID       INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ReportDate         TEXT,
    IOOfficer          TEXT,
    MoneyTrailNotes    TEXT,
    LinkedIdentifiers  TEXT,
    SeizedItems        TEXT,
    Arrests            TEXT,
    IsLive             INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_Evidence (
    EvidenceID       INTEGER PRIMARY KEY,
    CaseMasterID     INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    DocType          TEXT NOT NULL,
    FileRef          TEXT NOT NULL,
    OriginalFilename TEXT NOT NULL,
    ExtractionStatus TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS EXT_VictimDetail (
    VictimMasterID INTEGER PRIMARY KEY REFERENCES Victim(VictimMasterID),
    OccupationID   INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID        INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID     INTEGER REFERENCES ReligionMaster(ReligionID),
    Address        TEXT,
    Mobile         TEXT,
    LossAmount     INTEGER DEFAULT 0,
    ResidenceDistrict TEXT
);

CREATE TABLE IF NOT EXISTS EXT_AccusedDetail (
    AccusedMasterID INTEGER PRIMARY KEY REFERENCES Accused(AccusedMasterID),
    OccupationID    INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID         INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID      INTEGER REFERENCES ReligionMaster(ReligionID),
    Address         TEXT,
    IsArrested      INTEGER DEFAULT 0,
    ResidenceDistrict TEXT
);

CREATE TABLE IF NOT EXISTS EXT_SubEvent (
    SubEventID    INTEGER PRIMARY KEY,
    CaseMasterID  INTEGER REFERENCES CaseMaster(CaseMasterID),
    Label         TEXT,
    Timestamp     TEXT,
    source_caseid INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date TEXT,
    confidence    REAL DEFAULT 1.0
);

-- Legal extension tables

CREATE TABLE IF NOT EXISTS EXT_LegalElement (
    ElementID   TEXT PRIMARY KEY,
    SectionID   TEXT,
    Name        TEXT,
    Description TEXT
);

CREATE TABLE IF NOT EXISTS EXT_EvidenceType (
    EvidenceTypeID         TEXT PRIMARY KEY,
    Name                   TEXT,
    Description            TEXT,
    Requires63Certificate  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_Precedent (
    PrecedentID    TEXT PRIMARY KEY,
    CaseName       TEXT,
    Citation       TEXT,
    Year           INTEGER,
    Court          TEXT,
    Outcome        TEXT,
    ElementTurnedOn TEXT,
    SectionID      TEXT,
    HoldingSummary TEXT,
    IsOverruled    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_IPCSection (
    IPCSectionID  TEXT PRIMARY KEY,
    SectionNumber TEXT,
    Title         TEXT
);

-- Bridges the KSP-ER section identity to the legal layer's.
-- ActSectionAssociation keys charges as (ActCode='ITACT', SectionCode='66C'); the legal
-- layer keys elements and precedents as SectionID='IT_66C'. Nothing joined the two, so
-- "which elements must I prove for this case's charges?" was unanswerable from SQL --
-- the whole legal chain (charge -> element -> evidence -> precedent) dead-ended at the
-- first hop. Derived from LEGAL_SECTIONS, so it stays in step with the legal layer
-- instead of living as a prefix-guessing constant in the agent.
CREATE TABLE IF NOT EXISTS EXT_SectionMap (
    ActCode     TEXT NOT NULL,
    SectionCode TEXT NOT NULL,
    SectionID   TEXT NOT NULL,
    PRIMARY KEY (ActCode, SectionCode)
);

-- Which kinds of evidence can satisfy a given legal element. Real curated legal
-- reference data (ELEMENT_SATISFIED_BY), previously built in memory and returned by
-- get_legal_data() but never persisted anywhere -- leaving the checklist unable to say
-- what would actually close a gap.
CREATE TABLE IF NOT EXISTS EXT_ElementSatisfiedBy (
    ElementID      TEXT NOT NULL,
    EvidenceTypeID TEXT NOT NULL,
    PRIMARY KEY (ElementID, EvidenceTypeID)
);
