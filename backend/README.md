# Catalyst Ingestion Backend

FastAPI backend for KSP ingestion, designed for Catalyst AppSail + Catalyst Job Scheduling.

Ingestion is a two-phase, raw/processed/archive pipeline (see
[catalyst_functions/ingest_processor/README.md](../catalyst_functions/ingest_processor/README.md)
for the Stratus layout and job params):

1. `POST /api/v1/upload` stores files under `raw/{batch_id}/` and creates a `BatchUpload` row only — no processing starts yet. Accepts `txt, html, pdf, docx, png, jpg, jpeg, webp` (per-doc-type allow-list in `SchemaDefinition.allowed_file_extensions`); images are transcribed via the Zoho-hosted Qwen3 VLM before entering the normal classify → extract flow (no OCR binaries to install).
2. `POST /api/v1/process/{batch_id}` mints `case_id`/`run_id`, creates the `PipelineRun` row, and submits the Phase A (`extract`) job (409 if a non-terminal run already exists for the batch). Phase A extracts + transforms + checkpoints to `processed/{case_id}/{run_id}/manifest.json`, runs person entity matching, and stops at `status=REVIEW_PENDING`.
3. `GET /api/v1/process/{run_id}/findings` — the review screen's centrepiece: people/accounts/UPI/phones/devices found, the money-trail (`transactions`), a graph preview (`connections.nodes/edges`) of how everything links, and `potential_matches` against existing case records. All in case-file language, built straight from the checkpoint — no DB load needed yet.
4. Reviewers resolve `ReviewQueueItem`s via `GET/POST /api/v1/review-queue*` (pre-load: decision is only recorded, not applied live); `GET /review-queue` includes the resolved `matched_record` (the actual existing Accused/Victim/Complainant row) and plain-language `match_reasons`.
5. `POST /api/v1/process/{run_id}/proceed` submits the Phase B (`load`) job, which applies review decisions, loads Postgres/Neo4j/Pinecone, archives the raw files to `archive/{case_id}/{run_id}/`, and marks the run `COMPLETED`. `POST /api/v1/process/{run_id}/retry` resubmits a `FAILED` run's current phase.
6. `GET /api/v1/pipeline-status/{run_id}` and `WS /ws/pipeline/{run_id}` stream the `PipelineRun` row (incl. `files_progress`, each annotated with an officer-friendly `stage_label`/`status_label` — see `app/services/stage_labels.py`); the WS is push-first via the Signals webhook broadcast with a Postgres poll fallback.
7. `GET /api/v1/upload/{batch_id}` and `GET /api/v1/runs?case_id=&status=&limit=` let the FE rediscover batch/run state after a refresh (e.g. `status=REVIEW_PENDING` for "runs awaiting your review").

## API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/upload` | Upload one or more files (multipart) into `raw/{batch_id}/` |
| GET | `/api/v1/upload/{batch_id}` | Batch detail: stored files + runs for the batch |
| POST | `/api/v1/process/{batch_id}` | Start Phase A (extract/transform/checkpoint) |
| GET | `/api/v1/process/{run_id}/findings` | Officer-facing findings from the Phase A checkpoint |
| POST | `/api/v1/process/{run_id}/proceed` | Start Phase B (load/archive) after review |
| POST | `/api/v1/process/{run_id}/retry` | Resubmit a `FAILED` run's current phase |
| GET | `/api/v1/runs` | List `PipelineRun`s (filter by `case_id`/`status`) |
| GET | `/api/v1/pipeline-status/{run_id}` | Current run status (REST) |
| WS | `/ws/pipeline/{run_id}` | Live run status stream |
| GET | `/api/v1/review-queue` | Pending/resolved entity-match review items |
| POST | `/api/v1/review-queue/{review_id}/resolve` | Merge or keep-separate a review item |
| GET/PUT | `/api/v1/admin/config` / `/api/v1/admin/config/{key}` | Generic `AppConfig` list/upsert |
| GET/PUT | `/api/v1/admin/config/entity-review-threshold` | Splink auto-merge threshold |
| GET | `/api/v1/admin/schema` / `/api/v1/admin/schema/{doc_type}*` | `SchemaDefinition`/`SchemaField`/`SchemaRelationship` admin |
| POST/GET | `/api/v1/cases` | Create/list cases |
| GET | `/api/v1/cases/{case_id}` | Case detail + related-record counts + recent runs |
| POST | `/internal/entity/splink-match` | Splink-backed match check (called by the job function) |
| POST | `/internal/pipeline-event` | Signals webhook target (unwraps + broadcasts to WS) |

## What this folder contains

- `app/main.py` FastAPI app and route wiring
- `app/routers/` upload, process (Phase A/B triggers), status websocket, schema-admin, review queue, internal endpoints (Splink callback + Signals webhook)
- `app/services/catalyst_queue.py` Stratus raw/processed/archive key helpers (incl. `get_checkpoint_manifest`) + Job Scheduling submit (SDK + REST fallback)
- `app/services/pipeline_broadcast.py` in-process fan-out from the Signals webhook to `/ws/pipeline/{run_id}` subscribers
- `app/services/stage_labels.py` officer-friendly `stage_label`/`status_label` mapping applied to every status/run payload
- `app/services/findings.py` builds the `/process/{run_id}/findings` response (entities, money trail, graph preview, potential matches) from the Phase A checkpoint
- `app/services/entity_resolution.py` Splink match helpers + `resolve_person_record`/`match_reasons` (side-by-side review display)
- `app/llm.py` shared LLM adapter (`zoho|anthropic|openai` with fallback chain)
- `migrations/schema_pg.sql` PostgreSQL schema (KSP core + new spec tables)
- `migrations/seed_schema_config.sql` `SchemaDefinition/SchemaField/SchemaRelationship` + `AppConfig` seeds
- `migrations/migrate_sqlite_to_pg.py` SQLite -> Postgres migration transform
- `scripts/smoke_e2e.py` assert-style end-to-end smoke check (upload -> process -> proceed -> terminal status)
- `scripts/verify_routes.py` route-registration assert check — no DB/server needed, just imports `app.main:app`
- `app-config.json` AppSail deployment config

## Setup

```bash
pip install -r backend/requirements.txt
```

Environment:

- Postgres: `DATABASE_URL` or `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD/DB_SSL`
- Zoho Catalyst + Stratus: `ZOHO_*`, `X_ZOHO_*`
- LLM: `DATA_INGESTION_LLM`, `CONV_AI_LLM`, provider keys
- Zoho QuickML VLM (image extraction): `ZOHO_QUICKML_VLM_ENDPOINT_URL`, `ZOHO_QUICKML_VLM_MODEL_NAME` — reuses the same OAuth token flow as the GLM classifier/extractor. Verify with `python scripts/test_zoho_vlm.py` (repo root) before relying on it.
- Splink internal auth: `SPLINK_SHARED_SECRET` (also used as the inbound secret for the `/internal/pipeline-event` Signals webhook)
- Signals: `SIGNALS_PIPELINE_PUBLISHER_URL` (outbound, set on the job function); `WS_POLL_SECONDS` controls the WebSocket's Postgres poll fallback interval

## Apply DB schema and migrate historical data

```bash
python backend/migrations/migrate_sqlite_to_pg.py --target-db ksp_crime
```

## Run backend locally

```bash
uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 9000
```

## Deploy to AppSail

```bash
catalyst deploy
```

After AppSail deploy, set the public URL as `SPLINK_ENDPOINT_URL` for the `ingest_processor` job function.

## Resetting demo data

`scripts/reset_demo_data.py` (repo root) deletes only demo-run data — Postgres rows tied to
demo `case_id`s (plus the always-demo `BatchUpload`/`PipelineRun`/`ReviewQueueItem` tracking
tables), Neo4j nodes/edges with `origin='demo'`, Pinecone vectors with `demo::` ids, and Stratus
objects under `raw/`/`processed/`/`archive/` — leaving the migrated historical data untouched.

```bash
python scripts/reset_demo_data.py --dry-run   # preview counts, no deletes
python scripts/reset_demo_data.py --yes        # actually delete
```

## Verifying without a live DB

Two checks work offline (no Postgres/Stratus network access needed):

```bash
python backend/scripts/verify_routes.py                            # every expected route is registered
python catalyst_functions/ingest_processor/test_extract_formats.py  # txt/html/pdf/docx/image extraction branches
```

`backend/scripts/smoke_e2e.py` and `catalyst_functions/ingest_processor/self_check.py` need a running backend
and live Postgres/Stratus (and, for self_check, direct Stratus access) — see their module docstrings.

