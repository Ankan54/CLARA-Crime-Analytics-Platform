# KSP Crime Intelligence Platform — Synthetic Data Generator

Karnataka State Police Datathon 2026 · Crime Intelligence Platform demo dataset.

---

## Architecture: Two Routes, Three Stores

```
┌─────────────────────────────────────────────────────────────────────┐
│  data_generation/generate.py (12 stages)                            │
│                                                                     │
│  Stage 1-3  preflight → reference → entities                        │
│  Stage 4    historical_docs  ──► sample_data/historical/docs/<CrimeNo>/  │
│  Stage 5    narratives       (Bedrock LLM, disk-cached)             │
│  Stage 6    sql_csv          ──► sample_data/historical/sql/             │
│  Stage 7    db_load          ──► sample_data/historical/db/ksp.sqlite    │
│  Stage 8    graph_from_db    ──► sample_data/historical/graph/           │
│  Stage 9    vector_embed_docs──► sample_data/historical/vector/          │
│  Stage 10   live_docs        ──► sample_data/live_demo/live_scn{1-4}/    │
│  Stage 11   evidence                                                │
│  Stage 12   validate                                                │
└─────────────────────────────────────────────────────────────────────┘

Historical route (pre-loaded)          Demo route (held-back)
──────────────────────────────         ─────────────────────────────
documents → SQL CSVs → ksp.sqlite      held-back FIR + IR docs
                ↓                      fir.expected.json (ground truth)
         graph_builder.py              ir.expected.json
                ↓
         vector embedder               NEVER loaded into ksp.sqlite
                ↓
       sample_data/historical/ ✓            sample_data/live_demo/ (upload target)
```

**The SQL DB is the single source of truth.** `graph_builder.py` reads `ksp.sqlite` to
build Neo4j CSVs — never from in-memory generator objects. Both routes produce the same
artifact shape; they differ only in who performs the extraction.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up credentials (.env)
cp .env.example .env   # fill in AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION

# Run full pipeline (all 12 stages)
python -m data_generation.generate

# Resume from a specific stage (checkpointed)
python -m data_generation.generate --stages db_load,graph_from_db,vector_embed_docs

# Validate only
python -m data_generation.validate --output-dir sample_data

# Run with strict mode (warnings become errors)
python -m data_generation.validate --output-dir sample_data --strict
```

---

## Output Structure

```
sample_data/
├── historical/
│   ├── docs/
│   │   └── <CrimeNo>/
│   │       ├── fir.txt                   # Full FIR with KSP header block
│   │       └── investigation_report.txt  # IR with digital forensics
│   ├── sql/
│   │   ├── ksp/
│   │   │   ├── CaseMaster.csv            # KSP-ER core tables
│   │   │   ├── ComplainantDetails.csv
│   │   │   ├── Victim.csv
│   │   │   ├── Accused.csv
│   │   │   ├── ArrestSurrender.csv
│   │   │   ├── ActSectionAssociation.csv
│   │   │   ├── ChargesheetDetails.csv
│   │   │   └── master/                   # All 18 master/lookup CSVs
│   │   └── extension/
│   │       ├── accounts.csv              # Dimension tables
│   │       ├── devices.csv               # (one row per unique identifier)
│   │       ├── upis.csv
│   │       ├── phones.csv
│   │       ├── ips.csv
│   │       ├── wallets.csv
│   │       ├── transactions.csv          # Link/fact tables
│   │       ├── uses.csv                  # (with context columns)
│   │       ├── mentions.csv
│   │       ├── accused_in.csv
│   │       └── complainant_in.csv
│   ├── db/
│   │   ├── schema.sql                    # DDL for all tables
│   │   └── ksp.sqlite                    # Canonical SQLite DB
│   ├── graph/
│   │   ├── nodes_crime.csv
│   │   ├── nodes_person.csv
│   │   ├── nodes_account.csv
│   │   ├── nodes_device.csv
│   │   ├── nodes_upi.csv
│   │   ├── nodes_phone.csv
│   │   ├── nodes_ip.csv
│   │   ├── nodes_wallet.csv
│   │   ├── rels_uses.csv                 # All edges carry source_caseid/observed_date/confidence
│   │   ├── rels_mentions.csv
│   │   ├── rels_accused_in.csv
│   │   ├── rels_complainant_in.csv
│   │   ├── rels_transferred_to.csv
│   │   ├── rels_charged_under.csv
│   │   ├── rels_occurred_in.csv
│   │   └── import.cypher                 # Neo4j bulk import script
│   ├── vector/
│   │   └── narratives.jsonl              # Full docs embedded; node_id=CaseMasterID
│   └── evidence/
│       └── scenario_{1-4}/evidence/
└── live_demo/
    ├── live_scn1/                        # Digital Arrest Ring reveal
    │   ├── fir.txt
    │   ├── fir.kn.txt                    # Kannada translation
    │   ├── fir.kn_backtranslation.txt
    │   ├── fir.expected.json             # Ground-truth extraction target
    │   ├── investigation_report.txt
    │   └── ir.expected.json
    ├── live_scn2/                        # Entity Resolution reveal
    ├── live_scn3/                        # Follow the Money bridge reveal
    └── live_scn4/                        # Surge continuation
```

---

## Key Modules

| File                   | Role                                                                 |
|------------------------|----------------------------------------------------------------------|
| `data_generation/generate.py`          | Pipeline orchestrator (12 stages, checkpointed)                      |
| `ksp_master.py`        | Static KSP master data + CrimeNo/CaseNo formatting                  |
| `id_registry.py`       | Deterministic logical-key → INT PK mapping; live CrimeNo reservation |
| `models.py`            | Dataclasses for all entities (KSP-core + extension)                  |
| `scenario_generator.py`| Scenario-specific entity generation (planted links)                  |
| `background_generator.py`| Background decoy case generation (34 cases)                        |
| `data_generation/narrative_generator.py` | AWS Bedrock/LangChain narrative integration (LLM generation + cache) |
| `document_generator.py`| Full fir.txt + investigation_report.txt for historical cases         |
| `export.py`            | Projects Corpus → SQL CSVs (KSP-core + extension)                   |
| `sql_schema.py`        | Generates `schema.sql` DDL for all tables                            |
| `db_loader.py`         | Loads CSVs into `ksp.sqlite` (enforces FK constraints)               |
| `graph_builder.py`     | Builds Neo4j CSVs from `ksp.sqlite`; MERGE semantics on natural keys |
| `dimension_utils.py`   | Deduplicates identifier pool (one row per natural key)               |
| `live_demo_generator.py`| Generates held-back live demo docs + `*.expected.json`             |
| `legal_layer.py`       | Act/Section → BNS/ITACT/PMLA/BSA mappings                           |
| `identifier_pool.py`   | Fixed, named identifier constants for planted links                  |
| `data_generation/validate.py`          | Comprehensive validation (Suites A-I)                                |
| `data_generation/config.py`            | Seed, volume targets, model names, output paths                      |

---

## Demo Scenarios

### Scenario 1 — Digital Arrest Ring
- 3 historical FIRs across Mysuru, Mangaluru, Hubballi-Dharwad
- All route funds to `AGG_ACC_01` (aggregation account, no owner)
- Live IR reveals: controller identity + `CTRL_IMEI_01` / `CTRL_UPI_01`
- Platform demo: financial graph traversal discovers ring; legal checklist flags BSA 63 gap

### Scenario 2 — Many Names, One Man (Entity Resolution)
- 4 alias Accused rows with different names across 3 historical + 1 live case
- Shared: `DEV_IMEI_02`, `UPI_02`, `PHONE_02`
- Platform demo: entity resolution via shared identifiers merges aliases at runtime

### Scenario 3 — Follow the Money (Bridge Account)
- 2 historical FIRs across Belagavi + Hubballi-Dharwad
- `BRIDGE_ACC_03` pre-loaded as flagged mule; no cross-case link yet
- Live case routes funds through it → platform graphs Bengaluru→Belagavi→Dharwad flow

### Scenario 4 — The Surge (Spike Detection)
- 5 baseline FIRs (Jan–May 2026) with independent identifiers
- 14 burst FIRs (last 21 days) sharing `DEV_POOL_04` / `IP_POOL_04` / `MULE_SET_04`
- Platform demo: temporal spike detection; community detection reveals ring structure

### Decoys
- 34 background cases covering all 10 crime types
- Similar-MO decoys calibrated to appear near Tier B similarity threshold
- No shared identifiers with scenario planted links

---

## Validation Suites

| Suite | What it checks                                                            |
|-------|---------------------------------------------------------------------------|
| A     | ER DDL superset; ksp.sqlite FK integrity; DB row-count parity; ER columns |
| B     | CrimeNo format; CaseNo derivation; district resolution; CSType distribution |
| C     | Doc↔SQL consistency; live expected.json validity; pool identifier FK resolution |
| D     | Vector completeness (one record per case + IR); metadata fields present   |
| E     | Graph-from-DB parity (Crime nodes == CaseMaster rows; object node counts) |
| F     | Dimension uniqueness; Scn2 shared IMEI node; cross-case graph links; byte-identity |
| G     | SQL context columns on link tables; all graph edges carry source_caseid/confidence |
| H     | Two-route separation (live CrimeNos absent from ksp.sqlite)               |
| I     | Volume targets ±10%; IFSC format; identifier cross-store consistency; evidence artifacts; Kannada translation; narrative tiers |

---

## Configuration

Key settings in `data_generation/config.py`:
- `SEED`: RNG seed for reproducibility (default: 42)
- `OUTPUT_DIR`: root output directory (default: `sample_data/`)
- `BEDROCK_REGION`: AWS region for Bedrock API
- `BEDROCK_MODEL_ID`: Claude model for narrative generation
- `VALIDATION_EMBEDDING_MODEL`: sentence-transformers model for tier similarity checks

LLM responses are disk-cached in `.cache/llm/`. Re-runs skip Bedrock API calls.

---

## Requirements

```
boto3
python-dotenv
faker
sentence-transformers
```

See `requirements.txt` for pinned versions.

---

## Reproducibility

- All random state seeded from `config.SEED` at pipeline start
- LLM narratives disk-cached keyed by deterministic prompt hash
- `id_registry.py` assigns INT PKs in a fixed, deterministic order
- Re-running from scratch produces byte-identical CSVs (except LLM cache misses)
- Checkpoint system (`python -m data_generation.generate --stages ...`) resumes from durable stage artifacts

---

## KSP Schema Compliance

- All KSP-ER core tables (CaseMaster, Accused, etc.) are **byte-faithful** to the ER diagram
- Extension tables use `EXT_` prefix and **never alter** KSP-ER columns
- `PRAGMA foreign_keys = ON` enforced during DB load; any FK violation aborts the build
- `CrimeNo` format: `C(1)+DistrictID(4)+UnitID(4)+Year(4)+Serial(5)` — Category 1 for all FIRs
- `Act.ActCode` and `Section.SectionCode` are VARCHAR PKs (per ER); no surrogate INT
- `ActSectionAssociation` uses a composite key (no surrogate ID)

---

*Karnataka State Police Datathon 2026 · Synthetic data pipeline*
