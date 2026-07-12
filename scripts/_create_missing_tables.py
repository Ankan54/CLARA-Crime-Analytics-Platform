"""Run the missing table creates in correct dependency order."""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parents[1] / ".env", override=True)
import os, psycopg
from psycopg.rows import dict_row

pw = os.environ["DB_PASSWORD"].strip('"\'')
url = "postgresql://{}:{}@{}:{}/{}?sslmode={}".format(
    os.environ["DB_USER"], pw, os.environ["DB_HOST"],
    os.environ["DB_PORT"], os.environ["DB_NAME"], os.environ["DB_SSL"]
)
conn = psycopg.connect(url, row_factory=dict_row, prepare_threshold=0, autocommit=False)

statements = [
    # SchemaDefinition first (no deps on new tables)
    """CREATE TABLE IF NOT EXISTS SchemaDefinition (
        schema_id                BIGSERIAL PRIMARY KEY,
        doc_type                 TEXT NOT NULL,
        version                  INTEGER NOT NULL,
        is_active                BOOLEAN NOT NULL DEFAULT FALSE,
        description              TEXT,
        allowed_file_extensions  TEXT NOT NULL DEFAULT 'txt,html,pdf,docx,png,jpg,jpeg,webp',
        max_file_size_mb         INTEGER NOT NULL DEFAULT 15,
        created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by               TEXT,
        UNIQUE (doc_type, version)
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_schemadef_doc_active
        ON SchemaDefinition(doc_type) WHERE is_active = true""",
    # Evidence depends on SchemaDefinition + CaseMaster (already exists)
    """CREATE TABLE IF NOT EXISTS Evidence (
        evidence_id               BIGSERIAL PRIMARY KEY,
        case_id                   INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
        doc_type                  TEXT,
        file_ref                  TEXT NOT NULL,
        original_filename         TEXT NOT NULL,
        extraction_status         TEXT NOT NULL CHECK (extraction_status IN ('success', 'partial', 'no_structured_data', 'failed')),
        extraction_confidence_avg DOUBLE PRECISION,
        schema_id_used            BIGINT REFERENCES SchemaDefinition(schema_id),
        uploaded_by               TEXT,
        upload_ts                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS InvestigationReport (
        report_id           BIGSERIAL PRIMARY KEY,
        case_id             INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
        accused_id          INTEGER REFERENCES Accused(AccusedMasterID),
        report_date         DATE,
        findings_narrative  TEXT,
        filed_by            INTEGER REFERENCES Employee(EmployeeID),
        status              TEXT,
        schema_id_used      BIGINT REFERENCES SchemaDefinition(schema_id),
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    # Device depends on Evidence
    """CREATE TABLE IF NOT EXISTS Device (
        device_id          BIGSERIAL PRIMARY KEY,
        imei_raw           TEXT,
        imei_normalized    TEXT,
        model              TEXT,
        holder_name_raw    TEXT,
        source_evidence_id BIGINT REFERENCES Evidence(evidence_id),
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_device_imei_norm ON Device(imei_normalized)",
    # Account depends on Evidence + EntityMap (already exists)
    """CREATE TABLE IF NOT EXISTS Account (
        account_id                BIGSERIAL PRIMARY KEY,
        account_number_raw        TEXT NOT NULL,
        account_number_normalized TEXT NOT NULL,
        ifsc                      TEXT,
        bank_name                 TEXT,
        branch_name               TEXT,
        branch_district           TEXT,
        account_type              TEXT,
        holder_name_raw           TEXT,
        holder_entity_uid         UUID REFERENCES EntityMap(entity_uid),
        account_open_date         DATE,
        kyc_name                  TEXT,
        is_flagged_mule           BOOLEAN DEFAULT FALSE,
        linked_case_id            INTEGER REFERENCES CaseMaster(CaseMasterID),
        source_evidence_id        BIGINT REFERENCES Evidence(evidence_id),
        created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_account_number_norm ON Account(account_number_normalized)",
    """CREATE TABLE IF NOT EXISTS UPIHandle (
        upi_id             BIGSERIAL PRIMARY KEY,
        vpa_raw            TEXT NOT NULL,
        vpa_normalized     TEXT NOT NULL,
        holder_name_raw    TEXT,
        linked_account_id  BIGINT REFERENCES Account(account_id),
        holder_entity_uid  UUID REFERENCES EntityMap(entity_uid),
        source_evidence_id BIGINT REFERENCES Evidence(evidence_id),
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_upi_vpa_norm ON UPIHandle(vpa_normalized)",
    """CREATE TABLE IF NOT EXISTS PhoneNumber (
        phone_id           BIGSERIAL PRIMARY KEY,
        number_raw         TEXT NOT NULL,
        number_normalized  TEXT NOT NULL,
        holder_name_raw    TEXT,
        imei_ref           BIGINT REFERENCES Device(device_id),
        holder_entity_uid  UUID REFERENCES EntityMap(entity_uid),
        source_evidence_id BIGINT REFERENCES Evidence(evidence_id),
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_phone_number_norm ON PhoneNumber(number_normalized)",
    """CREATE TABLE IF NOT EXISTS Transaction (
        txn_id             BIGSERIAL PRIMARY KEY,
        from_account_id    BIGINT REFERENCES Account(account_id),
        from_upi_id        BIGINT REFERENCES UPIHandle(upi_id),
        to_account_id      BIGINT REFERENCES Account(account_id),
        to_upi_id          BIGINT REFERENCES UPIHandle(upi_id),
        amount             NUMERIC(18,2) NOT NULL,
        txn_timestamp      TIMESTAMPTZ NOT NULL,
        mode               TEXT,
        utr_ref            TEXT,
        direction          TEXT,
        source_evidence_id BIGINT REFERENCES Evidence(evidence_id),
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_transaction_utr_ref ON Transaction(utr_ref)",
    "CREATE INDEX IF NOT EXISTS idx_transaction_timestamp ON Transaction(txn_timestamp)",
    # SchemaField + SchemaRelationship depend on SchemaDefinition
    """CREATE TABLE IF NOT EXISTS SchemaField (
        field_id           BIGSERIAL PRIMARY KEY,
        schema_id          BIGINT NOT NULL REFERENCES SchemaDefinition(schema_id),
        group_name         TEXT NOT NULL,
        is_repeating_group BOOLEAN NOT NULL DEFAULT FALSE,
        pole_entity_type   TEXT,
        field_name         TEXT NOT NULL,
        data_type          TEXT NOT NULL,
        is_required        BOOLEAN NOT NULL DEFAULT FALSE,
        target_table       TEXT NOT NULL,
        target_column      TEXT NOT NULL,
        is_identifier      BOOLEAN NOT NULL DEFAULT FALSE,
        identifier_type    TEXT,
        extraction_hint    TEXT,
        display_order      INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS idx_schemafield_schema_group ON SchemaField(schema_id, group_name)",
    """CREATE TABLE IF NOT EXISTS SchemaRelationship (
        rel_id                 BIGSERIAL PRIMARY KEY,
        schema_id              BIGINT NOT NULL REFERENCES SchemaDefinition(schema_id),
        from_group             TEXT NOT NULL,
        to_group               TEXT NOT NULL,
        relationship_type      TEXT NOT NULL,
        direction              TEXT NOT NULL DEFAULT 'from_to',
        fixed_edge_properties  JSONB
    )""",
]

for stmt in statements:
    label = stmt.strip().split("\n")[0][:80]
    try:
        conn.execute(stmt)
        conn.commit()
        print(f"  OK: {label}")
    except Exception as exc:
        conn.rollback()
        print(f"  ERR [{label}]: {exc}")

conn.close()
print("Done.")
