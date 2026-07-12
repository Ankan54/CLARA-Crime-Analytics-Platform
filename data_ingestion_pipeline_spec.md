# Data Ingestion Pipeline — Functional Specification
### KSP Crime Analytics Platform — Datathon 2026

**Audience:** coding agent implementing this feature.
**What this document is:** a complete functional description of what the ingestion pipeline must do, what data it must produce and store, and which technologies handle which job. It does **not** prescribe code structure, class design, or file layout — that is left to you.
**Source of truth for the base schema:** the KSP-provided FIR schema PDF (already available in the project). Wherever this document says "KSP schema," go verify exact column names/types against that PDF — the names below (from prior schema analysis) should be correct but the PDF wins on any conflict.

---

## Table of Contents

1. Context (short)
2. The Feature, From the User's Point of View
3. Technology Stack — What Each Piece Is For
4. Where Data Lives
5. The Schema Configuration Feature (replaces schema.json)
6. Evidence Types In Scope, and What Gets Extracted
7. Vector Index — What Gets Embedded and What Metadata Goes With It
8. The Graph Layer — How Nodes and Edges Get Created (the part that was missing)
9. End-to-End Process Flow (the full pipeline, step by step)
10. Entity Resolution — Full Rules
11. API Surface
12. File Upload Constraints
13. Error Handling, Idempotency, Partial Failure
14. Designing For Change (brief)
15. Assumptions Made In This Document
16. Open Items — Needs Your Decision

---

## 1. Context

This is a crime-intelligence platform for KSP covering cyber and financial crime. Three stores hold the data: **SQLite** (records — this document assumes the single "SQL DB" in the process diagram is SQLite for this demo phase, see Section 15), **Neo4j** (a POLE graph — Person, Object, Location, Event — for connections and networks), and **Pinecone** (vector search over free-text narratives). This document specifies the pipeline that takes an uploaded document (FIR, Investigation Report, or Evidence) and turns it into rows in SQLite, nodes/edges in Neo4j, and chunks in Pinecone — correctly linked to each other.

---

## 2. The Feature, From the User's Point of View

### 2.1 Investigator — uploading documents

An investigator opens the upload screen. They:
1. Pick a case — either search/select an existing case, or start a new one. **If they start a new case, the only document type they are allowed to upload is an FIR** (a case has to begin with its FIR before any IR or evidence can attach to it). The upload screen enforces this: when "new case" is selected, the doc-type choice is locked to FIR. Once the FIR is processed and the case exists, IR and Evidence uploads become available for that case.
2. Pick what kind of document this is: **FIR**, **Investigation Report (IR)**, or **Evidence** (only FIR is selectable for a brand-new case, per point 1). If they pick Evidence, they don't need to know the sub-type (bank statement vs. screenshot etc.) — the system figures that out automatically.
3. Select one or more files from their device and hit upload. They can mix file types in one go (e.g., three screenshots and a bank statement PDF together).
4. Immediately after clicking upload, they see the files listed with a status badge each ("Queued" → "Reading document" → "Extracting details" → "Saving" → "Linking to case network" → "Done" / "Failed"). This updates live, without refreshing the page.
5. If a file fails at any point, they see which stage it failed at and can retry just that file.
6. If a piece of extracted information looks like it might belong to a person or account KSP already has on file elsewhere, that doesn't block the upload — it finishes normally, but a flag appears saying "some details are pending review" (see 2.4).

### 2.2 Investigator — watching progress

This is the real-time status view. Nothing new for them to learn beyond the checklist in 2.1 — the mechanics behind it (websocket) are invisible.

### 2.3 Admin — managing the schema

An admin opens a schema configuration screen, separate from the upload screen. Here they can, for any document type (FIR / IR / each evidence type):
- See the current list of fields the system extracts, grouped by what part of the data model they belong to (e.g., for FIR: a "Case" group, a "Complainant" group, an "Accused" group).
- Add a new field, remove one, mark one required, change the plain-English instruction that tells the extraction step what to look for.
- Add an entirely **new document type** (e.g., a new evidence type they didn't anticipate — say, a crypto-exchange screenshot) without needing a developer to redeploy anything.
- See version history of a schema and roll back if a change was wrong.

This is a genuinely new capability compared to the current KSP process (which uses a static schema file) — it means field-level changes and whole new evidence types can be handled live, including possibly during the datathon demo itself if a judge asks "what if evidence type X shows up."

### 2.4 Admin / senior investigator — resolving entity matches (Review Queue)

When the system extracts a person from a new document, it looks for people already in the system that might be the same individual (same phone/UPI/IMEI, or a similar name). It never merges anyone automatically. Instead, for each possible match it puts an item in a review queue showing the two records side by side, the fields that agree highlighted, and a **match score**.

The score is compared against a **review threshold that the admin can configure**. If the score is at or above the threshold, the match is shown in **green** (the system's suggestion: "these are probably the same person"). If it's below, it's shown in **red** ("these are probably different people"). The colour is only a suggestion — a human always makes the final call by clicking **"Merge — same person"** or **"Keep separate — different people."** Nothing changes in the graph until that click.

This deliberate human-in-the-loop step (no silent auto-merge, ever) is both the correct approach for anything that could feed a prosecution and a strong live-demo point: the system shows its reasoning and its confidence, but a person decides. The reviewer needs no technical knowledge to use this screen.

---

## 3. Technology Stack — What Each Piece Is For

| Technology | Purpose in this feature |
|---|---|
| **FastAPI** | The backend web framework. Serves the upload endpoint, status endpoints, schema-config endpoints, review-queue endpoints, and the websocket endpoint. |
| **SQLite** | The relational store: KSP base schema tables, this platform's extension tables, the schema-configuration tables, and pipeline/run tracking tables. One database file for the whole system in this demo phase. |
| **Neo4j** | The POLE graph database. Stores Person/Object/Location/Event nodes and the relationships between them. |
| **Pinecone** | Vector index for FIR and IR narrative text (and any evidence that contains free text worth searching semantically). |
| **LangChain, using `BaseChatModel`** | The abstraction layer for all LLM calls (classification and structured extraction). The concrete model/provider behind it is a config choice, not hardcoded, so it can be swapped later without touching pipeline logic. |
| **Zoho Stratus (object storage bucket)** | Where the actual uploaded file bytes are stored, keyed by case/batch/run. The bucket path/URL is a config value. |
| **`pypdf`** | Extracts text from PDF files, if any are uploaded. |
| **A small HTML text extractor** (e.g. BeautifulSoup, or a simple tag-strip) | Screenshots for the demo are provided as HTML files, so their text is read straight out of the HTML — no image handling or OCR needed. |
| **Splink** | Probabilistic record-linkage library used for matching *people* (names, partial demographic info) against existing Person entities when there's no exact hard identifier to rely on. |
| **In-memory task queue + FastAPI startup worker** | Runs each file's pipeline in the background so the upload request returns immediately. A plain `asyncio.Queue` filled by the upload endpoint and drained by one or more worker coroutines started at app startup. No Redis, no Celery — see Section 13 for the one caveat this brings. |
| **In-process event broadcast** | As each pipeline stage completes, a status event is pushed to any websocket connections watching that batch. Because everything runs in one process (in-memory queue), this is just an in-process structure (e.g. a dict of `asyncio.Queue`s keyed by `batch_id`) — no external message broker. |
| **FastAPI's native WebSocket support** | Streams live pipeline status to the investigator's screen. |

---

## 4. Where Data Lives

### 4.1 SQLite — KSP base tables (conform as-is, per the schema PDF)

`CaseMaster`, `ComplainantDetails`, `Victim`, `Accused`, `ActSectionAssociation`, `Act`, `Section`, `CrimeHead`, `CrimeSubHead`, `CaseStatusMaster`, `ChargesheetDetails`, `District`, `State`, `Unit`, `Employee`, `Rank`, `Designation`, `Court`, plus the small master/lookup tables (caste, religion, occupation, etc. — populate for schema completeness, never used for analysis). Use integer primary keys to match KSP's convention (e.g. `CaseMasterID`, `AccusedMasterID`). The FIR narrative lives in `CaseMaster.BriefFacts`.

### 4.2 SQLite — this platform's extension tables (full column specification)

None of these exist in the KSP schema — the coding agent will not find them in the PDF, so every column needed is spelled out below. Nothing here should require guessing.

**A note on identity before the tables:** extension tables never store their own `entity_uid` on themselves — that mapping lives only in `EntityMap` (`sql_table` + `sql_pk` → `entity_uid`), so there is exactly one place identity is recorded, never two places that could disagree. The one exception is `holder_entity_uid` columns below — those are a *different* relationship (which Person owns this Object), not the object's own identity, and they get filled in during Step 12/13 of the pipeline, not at SQL-commit time.

**`Account`** — a bank account appearing in evidence
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `account_id` | INTEGER | No | PK, autoincrement |
| `account_number_raw` | TEXT | No | exactly as extracted |
| `account_number_normalized` | TEXT | No | whitespace-stripped; **indexed**, used for entity-resolution lookup |
| `ifsc` | TEXT | Yes | |
| `bank_name` | TEXT | Yes | |
| `branch_name` | TEXT | Yes | |
| `branch_district` | TEXT | Yes | needed for the cross-district linking demo scenario |
| `holder_name_raw` | TEXT | Yes | as extracted, before entity resolution |
| `holder_entity_uid` | TEXT | Yes | FK → `EntityMap.entity_uid`; filled once the holder's Person entity is resolved |
| `account_open_date` | DATE | Yes | needed for temporal analysis |
| `linked_case_id` | INTEGER | No | FK → `CaseMaster.CaseMasterID` |
| `source_evidence_id` | INTEGER | Yes | FK → `Evidence.evidence_id`, provenance |
| `created_at` | DATETIME | No | default now |

**`Transaction`** — one money movement, extracted from a bank statement or UPI screenshot
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `txn_id` | INTEGER | No | PK, autoincrement |
| `from_account_id` | INTEGER | Yes | FK → `Account.account_id` (used when the source side is a bank account) |
| `from_upi_id` | INTEGER | Yes | FK → `UPIHandle.upi_id` (used when the source side is a UPI VPA instead) |
| `to_account_id` | INTEGER | Yes | FK → `Account.account_id` |
| `to_upi_id` | INTEGER | Yes | FK → `UPIHandle.upi_id` |
| `amount` | DECIMAL | No | |
| `txn_timestamp` | DATETIME | No | minute-level precision — required for layering-velocity analysis |
| `mode` | TEXT | Yes | e.g. IMPS / UPI / NEFT |
| `utr_ref` | TEXT | Yes | **indexed** — also usable as a soft cross-evidence linking key |
| `direction` | TEXT | Yes | debit/credit, relative to the account the source evidence belongs to |
| `source_evidence_id` | INTEGER | Yes | FK → `Evidence.evidence_id` |
| `created_at` | DATETIME | No | |

**`UPIHandle`** — a UPI VPA
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `upi_id` | INTEGER | No | PK, autoincrement |
| `vpa_raw` | TEXT | No | as extracted |
| `vpa_normalized` | TEXT | No | lowercased, trimmed; **indexed**, used for entity-resolution lookup |
| `linked_account_id` | INTEGER | Yes | FK → `Account.account_id`, if the evidence ties it to a bank account |
| `holder_entity_uid` | TEXT | Yes | FK → `EntityMap.entity_uid` |
| `source_evidence_id` | INTEGER | Yes | FK → `Evidence.evidence_id` |
| `created_at` | DATETIME | No | |

**`PhoneNumber`**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `phone_id` | INTEGER | No | PK, autoincrement |
| `number_raw` | TEXT | No | as extracted |
| `number_normalized` | TEXT | No | E.164 / last-10-digit form; **indexed** |
| `imei_ref` | INTEGER | Yes | FK → `Device.device_id` |
| `holder_entity_uid` | TEXT | Yes | FK → `EntityMap.entity_uid` |
| `source_evidence_id` | INTEGER | Yes | FK → `Evidence.evidence_id` |
| `created_at` | DATETIME | No | |

**`Device`**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `device_id` | INTEGER | No | PK, autoincrement |
| `imei_raw` | TEXT | Yes | |
| `imei_normalized` | TEXT | Yes | digits only, no separators; **indexed** |
| `model` | TEXT | Yes | |
| `source_evidence_id` | INTEGER | Yes | FK → `Evidence.evidence_id` |
| `created_at` | DATETIME | No | |

**`InvestigationReport`** — KSP's `ChargesheetDetails` is the *final* report only; this table holds the working IR
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `report_id` | INTEGER | No | PK, autoincrement |
| `case_id` | INTEGER | No | FK → `CaseMaster.CaseMasterID` |
| `accused_id` | INTEGER | Yes | FK → `Accused.AccusedMasterID` |
| `report_date` | DATE | Yes | |
| `findings_narrative` | TEXT | Yes | this is what gets embedded into Pinecone |
| `filed_by` | INTEGER | Yes | FK → `Employee` |
| `status` | TEXT | Yes | e.g. draft / final |
| `schema_id_used` | INTEGER | Yes | FK → `SchemaDefinition.schema_id`, records which schema version extracted this |
| `created_at` | DATETIME | No | |

**`Evidence`** — one row per uploaded evidence file
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `evidence_id` | INTEGER | No | PK, autoincrement |
| `case_id` | INTEGER | No | FK → `CaseMaster.CaseMasterID` |
| `doc_type` | TEXT | Yes | the classified value, e.g. `EVIDENCE_BANK_STATEMENT` |
| `file_ref` | TEXT | No | path/URL to the stored raw file |
| `original_filename` | TEXT | No | |
| `extraction_status` | TEXT | No | `success` / `partial` / `no_structured_data` / `failed` |
| `extraction_confidence_avg` | FLOAT | Yes | |
| `schema_id_used` | INTEGER | Yes | FK → `SchemaDefinition.schema_id` |
| `uploaded_by` | TEXT | Yes | |
| `upload_ts` | DATETIME | No | |
| `created_at` | DATETIME | No | |

**`EntityMap`** — the single bridge between every SQL row, every graph node, and every vector-metadata reference
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `entity_uid` | TEXT (UUID) | No | PK — generated once, at the moment an entity is first minted, never regenerated |
| `entity_type` | TEXT | No | `Person` / `Object` / `Location` / `Event` |
| `pole_subtype` | TEXT | No | the specific kind, e.g. `Accused`, `Victim`, `Complainant`, `Account`, `UPIHandle`, `PhoneNumber`, `Device`, `CaseEvent` — used directly as the Neo4j node label |
| `sql_table` | TEXT | No | which table this entity was minted from |
| `sql_pk` | TEXT | No | that row's primary key |
| `status` | TEXT | No | `active` (normal) / `merged_away` (this uid was collapsed into another by a human merge — kept for audit, references re-pointed) |
| `created_at` | DATETIME | No | |
| `updated_at` | DATETIME | No | |

**`PipelineRun`** — one row per uploaded file
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `run_id` | TEXT (UUID) | No | PK |
| `batch_id` | TEXT | No | FK → `BatchUpload.batch_id` |
| `case_id` | INTEGER | Yes | FK → `CaseMaster.CaseMasterID`; null until a new case's `CaseMaster` row is committed (Step 10) |
| `original_filename` | TEXT | No | |
| `file_path` | TEXT | No | |
| `doc_type` | TEXT | Yes | filled once Step 6 (classification) completes |
| `schema_id_used` | INTEGER | Yes | FK → `SchemaDefinition.schema_id` |
| `current_stage` | TEXT | No | one of the Section 9 step names |
| `status` | TEXT | No | `QUEUED` / `RUNNING` / `COMPLETED` / `COMPLETED_WITH_REVIEW_PENDING` / `FAILED` |
| `error_stage` | TEXT | Yes | |
| `error_message` | TEXT | Yes | |
| `created_at` | DATETIME | No | |
| `updated_at` | DATETIME | No | |

**`BatchUpload`** — groups the files from one upload action
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `batch_id` | TEXT (UUID) | No | PK |
| `case_id` | INTEGER | Yes | FK → `CaseMaster.CaseMasterID`; null for new-case uploads until committed |
| `uploaded_by` | TEXT | Yes | |
| `created_at` | DATETIME | No | |

**`ReviewQueueItem`**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `review_id` | INTEGER | No | PK, autoincrement |
| `source_run_id` | TEXT | No | FK → `PipelineRun.run_id` — which upload triggered this review |
| `entity_type` | TEXT | No | `Person` / `Object` |
| `candidate_record_json` | TEXT (JSON) | No | the newly extracted record |
| `matched_against_entity_uid` | TEXT | No | FK → `EntityMap.entity_uid` |
| `match_score` | FLOAT | No | |
| `matched_fields_json` | TEXT (JSON) | Yes | which fields agreed/disagreed, for the side-by-side UI |
| `status` | TEXT | No | `pending` / `merged` / `kept_separate` |
| `resolved_by` | TEXT | Yes | |
| `resolved_at` | DATETIME | Yes | |
| `created_at` | DATETIME | No | |

Skip Wallet, IP, and Precedent tables for this demo unless a specific demo scenario needs them — noted per your earlier scoping instruction.

### 4.3 Neo4j — the graph

POLE nodes (Person / Object / Location / Event) and relationships between them, keyed by `entity_uid`. Details in Section 8.

### 4.4 Vector DB (Pinecone)

Chunked FIR/IR narrative text (and any evidence free text), one vector per chunk, with metadata described in Section 7.

### 4.5 Raw files

The actual uploaded file bytes (text docs and HTML screenshots, plus PDF if any), stored in a **Zoho Stratus bucket**, keyed by `case_id/batch_id/run_id`. The bucket location is a config value.

---

## 5. The Schema Configuration Feature (replaces schema.json)

Instead of a static `schema.json`, the schema lives in three SQLite tables. This is what the admin screen in 2.3 reads and writes.

**`SchemaDefinition`**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `schema_id` | INTEGER | No | PK, autoincrement |
| `doc_type` | TEXT | No | e.g. `FIR`, `IR`, `EVIDENCE_BANK_STATEMENT`, `EVIDENCE_UPI_SCREENSHOT`, `EVIDENCE_CHAT_SCREENSHOT` — new evidence types are just new rows, no code change |
| `version` | INTEGER | No | |
| `is_active` | BOOLEAN | No | only one active version per `doc_type` at a time |
| `description` | TEXT | Yes | plain-English description, also fed into the LLM classification prompt |
| `allowed_file_extensions` | TEXT | No | comma-separated, e.g. `txt,html,pdf` |
| `max_file_size_mb` | INTEGER | No | |
| `created_at` | DATETIME | No | |
| `created_by` | TEXT | Yes | |

**`SchemaField`**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `field_id` | INTEGER | No | PK, autoincrement |
| `schema_id` | INTEGER | No | FK → `SchemaDefinition.schema_id` |
| `group_name` | TEXT | No | which sub-record this field belongs to, e.g. `CaseMaster`, `ComplainantDetails`, `Accused`, `Transaction` |
| `is_repeating_group` | BOOLEAN | No | true if multiple instances can occur in one document (e.g. several `Accused`, several `Transaction` rows) |
| `pole_entity_type` | TEXT | Yes | `Person` / `Object` / `Location` / `Event`, set once per `group_name`; blank if this group doesn't become a graph node (e.g. `Transaction`) |
| `field_name` | TEXT | No | logical name used in the extracted JSON, e.g. `account_number` |
| `data_type` | TEXT | No | `string` / `integer` / `float` / `date` / `boolean` |
| `is_required` | BOOLEAN | No | |
| `target_table` | TEXT | No | which SQLite table this field is written into |
| `target_column` | TEXT | No | which column |
| `is_identifier` | BOOLEAN | No | flags this field as a hard identifier usable for entity matching |
| `identifier_type` | TEXT | Yes | `phone` / `upi` / `imei` / `account_number` / `email` / null |
| `extraction_hint` | TEXT | Yes | plain-language instruction for the LLM, e.g. *"the 10-digit mobile number of the sender, often appears near 'From' or 'Paid by'"* |
| `display_order` | INTEGER | Yes | controls field order in the admin schema-editing screen |

**`SchemaRelationship`** (used to build graph edges, see Section 8)
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `relationship_id` | INTEGER | No | PK, autoincrement |
| `schema_id` | INTEGER | No | FK → `SchemaDefinition.schema_id` |
| `from_group` | TEXT | No | a `group_name` from `SchemaField` for this `schema_id` |
| `to_group` | TEXT | No | another `group_name`, or `CaseMaster`/`Evidence` for the fixed anchor relationships |
| `relationship_type` | TEXT | No | e.g. `OWNS`, `INVOLVES`, `MENTIONS`, `TRANSACTED_WITH` |
| `direction` | TEXT | No | `from_to` / `to_from` / `bidirectional` |
| `fixed_edge_properties` | TEXT | Yes | JSON of constant properties to stamp on the edge, e.g. `{"role": "accused"}` for an `INVOLVES` edge |
| `edge_property_source_fields` | TEXT | Yes | comma-separated `field_name`s (from the same document) that become edge properties instead of constants, e.g. `amount,txn_timestamp` for `TRANSACTED_WITH` |

**Seed rows for `SchemaRelationship`** (insert these when seeding `FIR` and the three evidence types — extend the same pattern for any future evidence type):

| doc_type | from_group | to_group | relationship_type | direction | fixed_edge_properties | edge_property_source_fields |
|---|---|---|---|---|---|---|
| `FIR` | `CaseMaster` | `Accused` | `INVOLVES` | from_to | `{"role":"accused"}` | |
| `FIR` | `CaseMaster` | `Victim` | `INVOLVES` | from_to | `{"role":"victim"}` | |
| `FIR` | `CaseMaster` | `ComplainantDetails` | `INVOLVES` | from_to | `{"role":"complainant"}` | |
| every evidence `doc_type` | `CaseMaster` | `Evidence` | `HAS_EVIDENCE` | from_to | | |
| `EVIDENCE_BANK_STATEMENT` | `Evidence` | `BankStatement` | `MENTIONS` | from_to | | |
| `EVIDENCE_BANK_STATEMENT` | `BankStatement` (holder) | `BankStatement` (account) | `OWNS` | from_to | | |
| `EVIDENCE_BANK_STATEMENT` | `Transaction` (from side) | `Transaction` (to side) | `TRANSACTED_WITH` | from_to | | `amount,txn_date` |
| `EVIDENCE_UPI_SCREENSHOT` | `Evidence` | `UPITransaction` | `MENTIONS` | from_to | | |
| `EVIDENCE_UPI_SCREENSHOT` | `UPITransaction` (payer) | `UPITransaction` (payee) | `TRANSACTED_WITH` | from_to | | `amount,timestamp` |
| `EVIDENCE_CHAT_SCREENSHOT` | `Evidence` | `ChatEvidence` | `MENTIONS` | from_to | | |

**How this drives the pipeline (no hardcoded per-doc-type logic needed):**
- **Classification** — the LLM is given the list of `doc_type` + `description` pairs currently marked active, and picks one. Add a schema row → it becomes a classification target automatically.
- **Extraction** — for the classified `doc_type`, pull all active `SchemaField` rows, build the structured-output request (LangChain's structured-output binding on the `BaseChatModel`) from those field names/types/hints, dynamically. No per-doc-type Python classes to maintain.
- **SQL write** — group extracted fields by `target_table`, write one row (or several, if `is_repeating_group`) per group into the SQLite table named.
- **Entity resolution input** — fields with `is_identifier = true` are automatically the fields checked for hard-identifier matching (Section 10). No hardcoded "phone is an identifier" logic — it's config.
- **Graph node creation** — every extracted group whose `pole_entity_type` is set becomes a candidate graph node (Section 8).

**Seeding:** initialize `SchemaDefinition`/`SchemaField` for `doc_type = FIR` and `doc_type = IR` from the KSP schema PDF's tables (`CaseMaster`, `ComplainantDetails`, `Victim`, `Accused`, `ActSectionAssociation` for FIR; the extension `InvestigationReport` table for IR), then add the three evidence types from Section 6 as additional seed rows.

**Versioning:** every extracted record stores which `schema_id`/version produced it (via `Evidence.extraction_status` metadata or a `schema_version_used` column on `PipelineRun`), so a later schema change doesn't retroactively reinterpret old data.

### 5.1 App-level config (admin-tunable settings)

A tiny key-value table holds settings the admin can change without a redeploy — most importantly the entity-match review threshold.

**`AppConfig`**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `config_key` | TEXT | No | PK, e.g. `entity_review_threshold` |
| `config_value` | TEXT | No | e.g. `0.80` |
| `updated_by` | TEXT | Yes | |
| `updated_at` | DATETIME | No | |

Seed `entity_review_threshold` with a sensible starting value (e.g. `0.80`). The review screen (Section 2.4) reads this to decide green vs. red. Changing it is a single admin action and affects how future matches are coloured — it never triggers an automatic merge.

---

## 6. Evidence Types In Scope, and What Gets Extracted

Three types, chosen because they cover every identifier your four demo scenarios link on (account, UPI, phone, IMEI). For this demo all inputs are synthetic **text or HTML files** — bank statements as text (or PDF, read with `pypdf`), screenshots as HTML. There is no image handling and no OCR anywhere in the pipeline.

**Bank statement** (text file, or PDF read with `pypdf`)
`group_name = BankStatement` (`pole_entity_type = Object`, target table `Account`): `account_holder_name`, `account_number` (`is_identifier`, `account_number`), `ifsc`, `bank_name`, `branch_name`, `branch_district` (needed for the cross-district scenario), `account_open_date` (needed for temporal analysis — only present on some statements; leave blank if not shown, don't guess).
`group_name = Transaction`, repeating (`pole_entity_type` blank — transactions become edges, not nodes; target table `Transaction`): `txn_date`, `amount`, `dr_cr`, `counterparty_name`, `counterparty_account_or_upi` (`is_identifier`, type depends on which it is), `utr_ref`, `balance`.

**UPI transaction screenshot** (HTML file)
`group_name = UPITransaction` (`pole_entity_type = Object` for each VPA, target table `UPIHandle` + `Transaction`): `payer_vpa` (`is_identifier`, `upi`), `payee_vpa` (`is_identifier`, `upi`), `amount`, `timestamp`, `utr_or_txn_id`, `app_name`, `status`.

**Chat screenshot** (WhatsApp/SMS, HTML file)
`group_name = ChatEvidence` (`pole_entity_type = Object` for phone numbers found; target table `PhoneNumber`): `participant_phone_numbers` (repeating, `is_identifier`, `phone`), `display_names`, `message_texts`, `timestamps`, and any `account_number` / `upi_vpa` / `url` / `telegram_handle` mentioned inside the message text (each flagged `is_identifier` with its matching type where applicable).

**Extraction confidence:** every extracted field carries a per-field `extraction_confidence` score from the LLM. Fields below a configurable threshold get flagged for manual correction in the UI before they're allowed to flow into entity resolution.

**Evidence with no structured yield:** if a file can't be classified into any active `doc_type`, or extraction produces nothing usable, it still gets stored (raw file + embedding of any free text it contained), the `Evidence` row is written with `extraction_status = 'no_structured_data'`, and the pipeline run is marked complete, not failed. This must be a real terminal path, not a silent drop.

---

## 7. Vector Index — What Gets Embedded and What Metadata Goes With It

**What gets embedded:** the FIR narrative (`CaseMaster.BriefFacts`), the IR narrative (`InvestigationReport.findings_narrative`), and — only if present — free text extracted from evidence (e.g. chat message text). Structured evidence with no free-text content (a bank statement's numeric fields) does **not** need its own embedding; it's represented in SQL and the graph instead.

**Metadata stored per chunk:**
`chunk_id`, `case_id`, `doc_id` (the FIR/IR/Evidence row it came from), `doc_type`, `district`, `police_station`, `crime_head`, `crime_subhead`, `date_of_offence`, `sql_source_pk`, `language` (`kn`/`en`), `chunk_index`, and `graph_node_ids` (a list, populated **after** graph write-back — see Step 13 in Section 9, initially empty at embedding time).

---

## 8. The Graph Layer — How Nodes and Edges Get Created

This is the part your original diagram left implicit. Here is exactly where it happens and what triggers it.

**When:** graph preparation happens *after* the SQL commit and *after* entity resolution has decided, for each extracted group, whether it matches an existing node or needs a new one. It is not a separate manual step — it is the direct output of entity resolution (Section 10).

**Which extracted groups become nodes:** any `SchemaField` group with a non-blank `pole_entity_type`. Examples: an `Accused` group → a `Person` node. An `Account` group → an `Object` node. `CaseMaster` itself → an `Event` node. A `Transaction` group does **not** become a node — it becomes a relationship (an edge) between two `Object` nodes, with `amount`/`date`/`direction` as edge properties.

**Node identity:** every node is created with `Neo4j MERGE` (Neo4j's create-if-absent / reuse-if-present operation) keyed on `entity_uid` — never on Neo4j's own internal ID, which isn't guaranteed stable. `entity_uid` comes from entity resolution: either the ID of an existing matched entity, or a freshly minted one.

**Default relationships (seeded for the three evidence types + FIR/IR):**

| From | To | Relationship | When created |
|---|---|---|---|
| Event (`CaseMaster`) | Person (Accused/Victim/Complainant) | `INVOLVES` (with a `role` property) | Every FIR |
| Event (`CaseMaster`) | Object (`Evidence`) | `HAS_EVIDENCE` | Every evidence upload |
| Object (`Evidence`) | Object (Account/Phone/UPI/Device) | `MENTIONS` | Every evidence extraction |
| Person | Object (Account/UPI/Phone) | `OWNS` / `ASSOCIATED_WITH` | When the extraction explicitly ties a holder name to an identifier |
| Object (Account/UPI) | Object (Account/UPI) | `TRANSACTED_WITH` | Every `Transaction` group, with amount/date/direction as edge properties |

These are configured via the `SchemaRelationship` table (Section 5) — not hardcoded — so a new evidence type can define its own relationship rules without touching pipeline code.

---

## 9. End-to-End Process Flow

Each step names its trigger, what it does, the technology involved, and where its output lands.

**Step 1 — Upload.** Investigator submits one or more files plus `case_id` (or "new case") and `doc_type` via the upload endpoint (FastAPI, `multipart/form-data`). A `BatchUpload` row is created; one `PipelineRun` row is created per file, `status = QUEUED`. The endpoint returns immediately with `batch_id` and the list of `run_id`s — it does **not** wait for processing.

**Step 2 — Validate.** Per file: check extension against the `doc_type`'s (or a default, if not yet classified) `allowed_file_extensions`, check size against `max_file_size_mb`, check the batch's total file count against the configured limit (Section 12). **Also enforce the new-case rule: if this upload is for a brand-new case, reject anything that isn't an FIR** (Section 2.1). Failures are per-file — one bad file in a batch doesn't block the others. Sets `status = VALIDATED` or `FAILED`.

**Step 3 — Enqueue background processing.** Each validated file's pipeline is pushed onto the in-memory `asyncio.Queue`. Worker coroutines started at app startup drain the queue and execute Steps 4–14 for each file. No external broker.

**Step 4 — Real-time status.** The frontend opens a websocket connection scoped to the `batch_id`. As each stage below updates `PipelineRun.current_stage`/`status`, that change is written to SQLite and pushed to any websocket watching this batch, via the in-process broadcast (Section 3), tagged with `run_id` so the UI updates the right row. A REST `GET` status endpoint exists as a fallback/reconnect path (Section 11).

**Step 5 — Get raw text.** Read the file's text based on its type: text file → read directly; HTML file (screenshots) → strip out the text content; PDF (if any) → extract with `pypdf`. No OCR, no image handling. Output: `raw_text` for this file, held in memory for this run.

**Step 6 — Classify the document.** Using LangChain's `BaseChatModel`, send `raw_text` (or a summary of it) plus the list of active `doc_type` descriptions from `SchemaDefinition`, and get back the matching `doc_type`. If the investigator already told the system it's an FIR/IR at upload time, this step only needs to pick the evidence *sub-type* (bank statement / UPI screenshot / chat screenshot) rather than the top-level type.

**Step 7 — Fetch active schema.** Load the active `SchemaDefinition` + all its `SchemaField` rows for the classified `doc_type`.

**Step 8 — Structured extraction.** Using LangChain's `BaseChatModel` with structured output bound to the field list from Step 7 (built dynamically, not from a hardcoded class), extract every field, each with an `extraction_confidence`. Low-confidence fields are flagged for manual correction (surfaced in the UI) rather than passed silently into SQL.

**Step 9 — Normalize identifiers.** For every field marked `is_identifier` in the schema, apply a normalization rule based on `identifier_type`: UPI → lowercase, trim; phone → E.164 / last 10 digits; IMEI → digits only, no separators; account number → strip whitespace. This is what prevents a case-mismatch (`Rahul@okaxis` vs `rahul@okaxis`) from breaking a link later — it's handled here, deterministically, before anything else touches the value.

**Step 10 — SQL commit.** Group extracted fields by `target_table` (from the schema), write one row per group (multiple rows if `is_repeating_group`) into the appropriate SQLite table — either a KSP base table (for FIR/IR core fields) or an extension table (Section 4.2). `PipelineRun.current_stage = SQL_COMMITTED`.

**Step 11 — Vector indexing** *(FIR/IR always; evidence only if it has free text)*. Chunk the narrative text, generate embeddings, write to Pinecone with the metadata schema from Section 7. `graph_node_ids` in the metadata is left empty for now — filled in Step 14.

**Step 12 — Entity matching (no merging here).** For every extracted group with a `pole_entity_type`:
- **Object nodes** (accounts, UPIs, phones, devices): look up the normalized identifier. If that exact identifier already exists as a node, reuse its `entity_uid` — this is plain identity ("the same account number is the same account"), not a merge decision, so it happens automatically. Otherwise mint a new `entity_uid`.
- **Person nodes**: always mint a **new** `entity_uid` for the extracted person. Separately, search for existing persons that might be the same individual (shared hard identifier, or a Splink name-similarity score) and, for each candidate, create a `ReviewQueueItem` with the match score. **No person is ever merged automatically** — the merge only happens later when a human clicks in the review screen (Step 16). This is why the alias-collapse in your demo is a visible, human-confirmed action rather than something that already happened silently.

**Step 13 — Graph upsert.** For every group from Step 12, `MERGE` a node in Neo4j keyed on its `entity_uid` (so re-running is safe). Create/reuse the relationships defined in `SchemaRelationship` (Section 8) between the nodes produced by this document.

**Step 14 — Cross-store write-back.** Now that `entity_uid`s exist:
- Write `entity_uid` into `EntityMap` (linking it to the SQL table/row it came from).
- Append the same `entity_uid`(s) to the `graph_node_ids` field in the relevant Pinecone chunk's metadata.
- Write the Pinecone `chunk_id`(s) onto a `source_chunks` property on the corresponding graph node(s), so an investigator clicking a node in the graph UI can jump to the source narrative.

**Step 15 — Complete.** `PipelineRun.status = COMPLETED` (or `COMPLETED_WITH_REVIEW_PENDING` if Step 12 created any `ReviewQueueItem`s). Final status pushed over the websocket. Note the file's own ingestion is now finished regardless of whether merges are pending — the person exists as its own node, and any suggested merges wait for a human.

**Step 16 — Human merge (manual, separate from the file's run).** In the review screen (Section 2.4), each `ReviewQueueItem` is shown green (score ≥ the admin threshold) or red (below it). When a reviewer clicks **"Merge — same person,"** the system re-points every reference to the just-created person's `entity_uid` (in `EntityMap`, Pinecone metadata, and the graph edges) onto the existing person's `entity_uid`, then removes the now-empty duplicate node — collapsing the two into one. When they click **"Keep separate,"** nothing changes and the item is marked resolved. The colour never forces the outcome; the click decides.

---

## 10. Entity Resolution — Full Rules

This directly answers: *how does new data connect to what's already in the graph, does a name-case mismatch block it, and is AI involved?*

**Hard identifiers (phone, UPI, IMEI, account number, email):** after normalization (Step 9), look up an exact match on the normalized value. For an **Object** (the phone/UPI/account itself), an exact match means it's the same object — reuse its `entity_uid` automatically. This is deterministic, not AI, and fully explainable. A shared hard identifier is *also* the strongest signal that two **Persons** are the same, but for persons it does not auto-merge — it produces a high match score that surfaces in the review screen (see below).

**Soft identifiers (person names, addresses):** exact string matching is wrong here (`Rahul Kumar` vs `R. Kumar` vs a transliterated Kannada spelling are the same person but not equal strings). Use **Splink**'s probabilistic record linkage — it scores how likely two records are the same person based on which fields agree and how *rare* that agreement is (two records sharing a phone number is strong evidence; two records both being named "Kumar" is weak). Search scope: first within the same case, then across all cases (this cross-case check is what surfaces hidden links between unrelated FIRs).

**How the score is used — no auto-merge (demo behaviour):** every possible person match becomes a `ReviewQueueItem` carrying its score. The score is compared to the admin-set `entity_review_threshold` (`AppConfig`, Section 5.1) purely to colour the item:
- Score ≥ threshold → shown **green** ("system suggests: same person").
- Score < threshold → shown **red** ("system suggests: different people").

The colour is a suggestion only. A human clicks **Merge** or **Keep separate** to decide, and only that click changes the graph (Step 16). The system never merges two persons on its own. This keeps the alias-collapse a visible, human-owned action in the demo, and keeps every merge defensible for a prosecution context.

**Is AI used?** Yes for *extraction* (the LLM pulls entities out of unstructured text). **Not** for the *merge decision* — that's deterministic identifier matching plus Splink's statistical score, both explainable, plus a human's final click. The LLM is deliberately kept out of "is A the same person as B." (Optional, non-blocking: the review screen could show an LLM-written one-line explanation of why two records look similar, purely as a reading aid — the human still decides.)

---

## 11. API Surface

| Method & Path | Purpose |
|---|---|
| `POST /api/v1/cases` | Create a new case |
| `GET /api/v1/cases` | Search/list existing cases (for the case-picker dropdown) |
| `POST /api/v1/upload` | Upload one or more files + `case_id` + `doc_type`. Returns `batch_id` and per-file `run_id`s immediately. |
| `GET /api/v1/pipeline-status/{run_id}` | REST fallback/reconnect status check |
| `WS /ws/pipeline/{batch_id}` | Live status stream for every file in a batch |
| `GET /api/v1/admin/schema` | List all doc types and their active schema version |
| `GET /api/v1/admin/schema/{doc_type}` | Get current field-level definition |
| `GET /api/v1/admin/schema/{doc_type}/versions` | Version history |
| `POST /api/v1/admin/schema/{doc_type}` | Create a new schema version (field list payload) |
| `PUT /api/v1/admin/schema/{doc_type}/activate/{version}` | Activate a specific version |
| `GET /api/v1/review-queue` | List pending entity-match reviews, each with its score and green/red flag |
| `POST /api/v1/review-queue/{review_id}/resolve` | Submit the human decision (`merge` / `keep_separate`) |
| `GET /api/v1/admin/config/entity-review-threshold` | Read the current review threshold |
| `PUT /api/v1/admin/config/entity-review-threshold` | Update the review threshold (`AppConfig`) |

---

## 12. File Upload Constraints

- **Allowed file types (demo default, configurable per `doc_type` via schema):** `.txt`, `.html`, `.pdf`. (No image types — screenshots are supplied as HTML for this demo, and there is no OCR.)
- **Per-file size limit (demo default):** 15 MB.
- **Max files per upload request:** 10.
- **Max total request size:** 60 MB.
- These are stored on `SchemaDefinition` (`allowed_file_extensions`, `max_file_size_mb`) plus a global batch-level config for file count — not hardcoded, so limits can differ per document type and be changed without a redeploy.

---

## 13. Error Handling, Idempotency, Partial Failure

- **Resumability:** each `PipelineRun` tracks `current_stage` and `status` in SQLite, so the current state of every file survives even though the queue itself is in-memory. If a file fails partway, it can be re-run from its record; Step 13 (graph upsert) is safe to re-run because `MERGE` on `entity_uid` is idempotent.
- **In-memory queue caveat (acceptable for the demo):** because the task queue lives in the app's memory (no Redis), if the server process restarts while files are mid-pipeline, those in-flight jobs are lost from the queue. Their `PipelineRun` rows remain in SQLite marked as whatever stage they'd reached, so on restart they can be detected (status still `RUNNING`/`QUEUED`) and requeued. For a live demo with a handful of synthetic files this is a non-issue; it's only a limitation to be aware of, not something to engineer around now.
- **Partial batch failure:** one file failing validation or extraction never blocks the others in the same batch.
- **No-structured-data terminal path:** covered in Section 6 — this must be a real, visible "done" state, not silently dropped.
- **Websocket disconnect/reconnect:** the REST status endpoint (Section 11) lets the frontend recover current state after a refresh or dropped connection, since the websocket alone doesn't persist state across a reconnect.

---

## 14. Designing For Change (brief)

- **New evidence type:** an admin adds it via the schema config feature (Section 5) — new `SchemaDefinition` + `SchemaField` rows. No code change needed, because classification, extraction, SQL writes, and identifier detection are all driven from that config at runtime.
- **Frequent schema edits:** every extraction result records which schema version produced it, so editing a schema never reinterprets already-ingested data.
- **Swappable LLM:** all LLM calls go through LangChain's `BaseChatModel` interface; the specific model/provider is a configuration value.
- **New identifier types later** (e.g. a crypto wallet address): add it as an `identifier_type` option plus its normalization rule — entity resolution logic reads identifier type from config, it isn't an hardcoded if/else per type.

---

## 15. Assumptions Made In This Document

1. The single "SQL DB" in your process diagram is **SQLite** for this demo phase, and the schema-configuration tables live in that same database file (not a separate database).
2. Vector DB is **Pinecone**.
3. Background processing uses an **in-memory `asyncio.Queue` + startup worker coroutines** — no Redis, no Celery. Confirmed simpler and sufficient for the demo's volume.
4. Raw files are stored in a **Zoho Stratus bucket**.
5. All inputs are synthetic **text or HTML files** (bank statements as text/PDF, screenshots as HTML). No images, no OCR anywhere. `pypdf` handles any PDF.
6. Evidence types are limited to the three in Section 6 for this demo, extensible later per Section 5.
7. **No automatic merging of persons.** Every possible match is surfaced to a human, coloured green/red against an admin-set threshold, and merged only on a manual click. Object nodes with identical normalized identifiers are treated as the same node automatically (that's identity, not a merge).
8. One `PipelineRun` per file, grouped under a `BatchUpload` per upload action.
9. A brand-new case can only receive an FIR as its first upload; IR and Evidence become available once the case exists.
10. LLM access is via LangChain's `BaseChatModel`, provider left to your choice, not fine-tuned.

---

## 16. Open Items — Needs Your Decision

- **Splink calibration:** the review threshold is admin-configurable and starts around `0.80`, but Splink's scoring still needs calibrating once synthetic data with known ground-truth aliases exists — otherwise the green/red suggestions won't be trustworthy. This ties directly to your alias-resolution demo scenario, so worth doing before the demo.
- **IR schema fields:** the exact field list for Investigation Reports isn't specified yet (KSP schema doesn't cover IR) — needs a first pass, likely modeled on the same Person/Object extraction pattern as FIR. The coding agent can seed a reasonable starting set into `SchemaDefinition`/`SchemaField`, but you should review it.
- **Object-node visibility in review:** this document has object nodes (accounts, phones) auto-linked on exact identifier match, and only *persons* going through manual review. If you'd rather have object links also confirmed by a human in the demo (more clicks, but even more "nothing happens without us"), say so and it's a small change.
