# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Karnataka State Police Datathon 2026 — "Crime Intelligence Platform". Three cooperating pieces:

1. **`data_generation/`** — offline synthetic-data pipeline that builds the demo dataset (FIRs, investigation reports, SQL DB, graph CSVs, vectors) from scratch.
2. **`backend/`** (FastAPI) + **`catalyst_functions/ingest_processor/`** (Zoho Catalyst job function) — the live ingestion pipeline: upload → extract/classify → entity-match review → load into Postgres/Neo4j/Pinecone.
3. **`frontend/`** (React + TypeScript + Vite) — the demo UI (Dashboard, Ingest, Assistant, Admin) driving the backend API + WebSocket.

`data_ingestion/` (repo root) is an older/lower-level ingestion library (Pinecone/Neo4j/Stratus/Supabase clients) that `catalyst_functions/ingest_processor` and `backend` build on top of.

## Commands

### Data generation pipeline
```bash
pip install -r requirements.txt
cp .env.example .env   # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION

python -m data_generation.generate                                          # full 12-stage pipeline
python -m data_generation.generate --stages db_load,graph_from_db,vector_embed_docs  # resume from a checkpoint
python -m data_generation.validate --output-dir sample_data                 # validation suites A-I
python -m data_generation.validate --output-dir sample_data --strict        # warnings become errors
```
LLM narrative calls are disk-cached in `.cache/llm/`; re-runs skip Bedrock. Checkpoints live under `.checkpoints/`. All randomness is seeded from `data_generation/config.py:SEED` — full reruns are byte-identical except on LLM cache misses.

### Backend (FastAPI)
```bash
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 9000

# offline checks (no Postgres/Stratus needed)
python backend/scripts/verify_routes.py
python catalyst_functions/ingest_processor/test_extract_formats.py

# needs a live backend + Postgres/Stratus
python backend/scripts/smoke_e2e.py

# apply/migrate schema
python backend/migrations/migrate_sqlite_to_pg.py --target-db ksp_crime

# wipe only demo-run data (preserves migrated historical data)
python scripts/reset_demo_data.py --dry-run
python scripts/reset_demo_data.py --yes
```
Root-level unit tests (mocked, no live services):
```bash
python -m unittest tests.test_demo_scenarios
python -m unittest tests.test_demo_scenarios.TestScenarioAllowlist.test_known_scenarios   # single test
```

### Frontend
```bash
cd frontend
npm install
npm run dev       # vite dev server, expects backend on http://localhost:9000
npm run build     # tsc -b && vite build
npm run lint       # oxlint
npm run preview
```
`cp frontend/.env.example frontend/.env`; override backend URL via `VITE_API_BASE_URL`.

### ingest_processor (Catalyst job function)
```bash
# local smoke, no network
python -c "from main import handler; print(handler({'params': {'batch_id':'b','case_id':'1','run_id':'1_20260101T000000Z','phase':'extract'}}))"

# full Phase A -> Phase B against a sample FIR (needs real Postgres/Stratus/Neo4j/Pinecone creds)
python catalyst_functions/ingest_processor/self_check.py
```

### Deployment (never run these yourself — always hand the exact commands to the user; the local terminal cannot execute `docker build`/`docker push`/`catalyst deploy` and they exit silently)
```powershell
docker build -f backend/Dockerfile.appsail -t ksp-catalyst-backend:latest .
docker tag ksp-catalyst-backend:latest 667736132441.dkr.ecr.us-east-1.amazonaws.com/default/ankan-repo:latest
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 667736132441.dkr.ecr.us-east-1.amazonaws.com
docker push 667736132441.dkr.ecr.us-east-1.amazonaws.com/default/ankan-repo:latest
catalyst deploy appsail --name ksp-catalyst-backend --source docker://667736132441.dkr.ecr.us-east-1.amazonaws.com/default/ankan-repo:latest --port 9000
```
Function deploy is portal-only on Windows (CLI hangs): zip `catalyst_functions/ingest_processor/*` and upload via Catalyst console, or run `catalyst_functions/ingest_processor/deploy_function.ps1` / `backend/scripts/deploy_appsail.ps1`.

## Architecture

### 1. Data generation: two routes, three stores (`data_generation/generate.py`, 12 checkpointed stages)

The **historical route** (pre-loaded) and **demo/live route** (held-back) both produce the same artifact shape but differ in who does the extraction:

```
documents → SQL CSVs → ksp.sqlite  →  graph_builder.py → Neo4j CSVs
                                    →  vector embedder  → narratives.jsonl
sample_data/historical/     (loaded)          sample_data/live_demo/   (upload target, never loaded into ksp.sqlite)
```

**`ksp.sqlite` is the single source of truth.** Key modules: `ksp_master.py` (static KSP master data / CrimeNo format), `id_registry.py` (deterministic logical-key → INT PK mapping), `models.py` (entity dataclasses), `export.py` (Corpus → SQL CSVs), `db_loader.py` (CSV → sqlite, enforces FKs), `legal_layer.py` (Act/Section → BNS/ITACT/PMLA/BSA mappings + `LEGAL_SECTION_TO_KSP`, the bridge exported as `EXT_SectionMap`), `identifier_pool.py` (fixed identifiers used to plant cross-case links for the 4 demo scenarios — see README.md for what each scenario plants and reveals).

**`graph_builder.py` is NOT the graph loader for the live instance** — `backend/migrations/load_neo4j_from_pg.py` replaced it (graph_builder keys nodes on natural ids, which can never MERGE with live ingestion's `entity_uid`-keyed nodes, and its `import.cypher` uses `LOAD CSV FROM 'file:///'`, which Aura rejects). Read `load_neo4j_from_pg.py` for the real graph shape.

Rebuilding sqlite after changing `export.py`/`sql_schema.py` needs no LLM — the corpus is checkpointed:
```bash
python -m data_generation.generate --stages sql_csv,db_load --no-resume
python backend/scripts/verify_seed_links.py   # offline pre-flight for the planted links
```

KSP-ER core tables (`CaseMaster`, `Accused`, etc.) must stay byte-faithful to the ER diagram; extension tables use an `EXT_` prefix and never alter KSP-ER columns. `CrimeNo` format is `C(1)+DistrictID(4)+UnitID(4)+Year(4)+Serial(5)`.

### 2. Live ingestion: two-phase pipeline, raw/processed/archive on Stratus

Flow (backend routers in `backend/app/routers/`, job logic in `catalyst_functions/ingest_processor/pipeline/processor.py`):

1. `POST /api/v1/upload` → stores files under `raw/{batch_id}/`, creates a `BatchUpload` row. No processing yet.
2. `POST /api/v1/process/{batch_id}` → mints `case_id`/`run_id`, creates `PipelineRun`, submits **Phase A** (`extract`) job. Extracts (dispatches by extension in `_extract_text`; images go through the Zoho-hosted Qwen3 VLM first) → classifies → schema-extracts → checkpoints to `processed/{case_id}/{run_id}/manifest.json` → runs **person** entity matching (`rapidfuzz.token_set_ratio` — Splink is an upgrade path, not wired; accounts/UPIs/devices are not fuzzy-matched at all, they join deterministically on their normalized identifier) → stops at `REVIEW_PENDING`.
3. `GET /api/v1/process/{run_id}/findings` (`backend/app/services/findings.py`) builds the officer-facing review screen (entities, money trail, graph preview, potential matches) straight from the checkpoint — no DB load needed yet.
4. Reviewers resolve `ReviewQueueItem`s via `/api/v1/review-queue*` (`backend/app/services/entity_resolution.py`); decisions are only recorded, not applied.
5. `POST /api/v1/process/{run_id}/proceed` → submits **Phase B** (`load`) job: applies review decisions, loads Postgres/Neo4j/Pinecone, archives raw files to `archive/{case_id}/{run_id}/`, marks `COMPLETED`. `.../retry` resubmits a `FAILED` run's current phase.
6. `GET /api/v1/pipeline-status/{run_id}` and `WS /ws/pipeline/{run_id}` stream `PipelineRun` state (`backend/app/services/stage_labels.py` adds officer-friendly labels); push-first via the Signals webhook (`/internal/pipeline-event` → `pipeline_broadcast.py` fan-out), with a Postgres poll fallback (`WS_POLL_SECONDS`).

`backend/app/llm.py` is a shared LLM adapter with a `zoho|anthropic|openai` fallback chain, used by both the backend and (via its own copy) `catalyst_functions/ingest_processor/llm.py`.

Job submission and Stratus key layout live in `backend/app/services/catalyst_queue.py` (`raw/`, `processed/`, `archive/` helpers + SDK/REST job submit fallback).

### 3. How live data merges with historical (the demo's whole payoff)

The "four separate cases are one network" moment depends on a live upload landing on the
**same row and same node** as pre-loaded historical data. It works like this:

1. Live ingestion looks up `Account WHERE account_number_normalized = ...`
   (`processor.py::_write_object_row`) and **reuses the existing pk** — the normalizers in
   `migrate_sqlite_to_pg.py` and `processor.py` are byte-identical, which is load-bearing.
2. `_ensure_entity` returns that row's existing `EntityMap.entity_uid`.
3. Both origins therefore MERGE onto one `entity_uid`-keyed Neo4j node (multi-labelled,
   e.g. `:Account:BankStatement`).

The normalized identifier indexes are **UNIQUE** — that constraint is what makes the join
deterministic; a duplicate would silently split the node and sever the planted links.

**Shared objects must never be claimed by the demo.** Live ingestion deliberately does
*not* stamp `source_evidence_id` on rows it didn't create, and sets
`origin = coalesce(n.origin, 'demo')` rather than overwriting. Both were bugs: they let
`scripts/reset_demo_data.py` delete the planted aggregation account, so the demo stopped
finding its own links on the second run. Reset also deletes demo *edges* separately — a
demo edge between two historical nodes is never reached by `DETACH DELETE`.

Pinecone has no object-level join: pivot live→historical through Postgres/Neo4j first,
then filter vectors by the resulting `case_id`.

### 4. Demo scenarios

Four scripted scenarios (`digital-arrest`, `many-names`, `follow-money`, `surge` — allowlisted in `backend/app/demo_scenarios.py`) each plant specific shared identifiers (accounts/IMEIs/UPIs/device or IP pools) across historical + live documents so the platform can demonstrate a specific capability (financial graph traversal, entity resolution, cross-district money-flow bridging, temporal spike/community detection). Scenario documents ship under `frontend/public/scenarios/scn{1-4}/`; `backend/app/services/demo_scenario_reset.py` re-stages a scenario's live documents/state for a repeatable demo run. `scripts/reset_demo_data.py` wipes only demo-tagged rows/nodes/vectors (Postgres rows tied to demo `case_id`s, Neo4j nodes with `origin='demo'`, Pinecone `demo::` ids, Stratus `raw/processed/archive`) — historical seed data is untouched.

### 5. The assistant (`backend/app/assistant/`)

A single LangGraph ReAct agent (`create_react_agent`) over a toolbox tagged
`sql|graph|vector|legal`. The UI's "four specialist agents" are a presentation of that one
loop: each tool emits its own step under its specialist's label, so the reasoning trail
reads as a team while the runtime stays one reliable loop. Multi-hop (vector → graph →
legal) falls out of ReAct, because each tool returns the refs the next one needs.

```
POST /api/v1/assistant/message -> {run_id, session_id}   (schedules an asyncio.Task)
WS   /ws/assistant/{run_id}                              (NOT under /api/v1)
POST /api/v1/assistant/runs/{run_id}/cancel
GET  /api/v1/assistant/artifacts/{artifact_id}
```

- `events.py` mirrors `frontend/src/lib/assistantTypes.ts`. **Casing is load-bearing**:
  frames are snake_case (`run_id`), everything nested is camelCase (`artifactRefs`). Wrong
  casing renders nothing — it does not raise.
- `bus.py` — per-run queue + **full replay buffer**. The client POSTs then connects, so
  without replay the opening events (and a fast run's whole answer) are lost.
- `emitter.py` — publishes inline on the loop thread, marshals via `call_soon_threadsafe`
  from tool threads (asyncio.Queue is not thread-safe).
- `tools.py` — every body is sync and runs through `asyncio.to_thread` (Postgres, Neo4j and
  Pinecone clients are all blocking). `run_sql_select`/`run_cypher_read` are the guarded
  escape hatches that let off-script questions work; graph reads also go through
  `execute_read`, so Neo4j rejects writes at the transaction level.
- `service.py` — a run **always** terminates with `done`/`error`; the frontend has no
  onclose handler, so a silent close hangs the UI. Cancellation lands between tool calls
  (a thread can't be interrupted mid-query).
- Money trail runs in **Postgres** (recursive CTE over `Transaction`), not Cypher.
- Legal chain runs in **Postgres** (the legal layer isn't in Neo4j):
  `ActSectionAssociation → EXT_SectionMap → EXT_LegalElement → EXT_ElementSatisfiedBy →
  EXT_EvidenceType`, plus `EXT_Precedent`. §63 status is derived from the case's actual
  uploaded evidence, not scripted.
- `skills/report.py` — PDF via xhtml2pdf. See its header before touching fonts: Indic text
  fails **silently** (valid PDF, no error, no text) in several distinct ways.

Provider: `CHAT_LLM_PROVIDER` (`zoho|openai|anthropic|bedrock`) + `CHAT_LLM_ID`; always
falls back to OpenAI (`llm.py::_FALLBACK_PROVIDER`).

```bash
python backend/tests/test_assistant_{events,tools,service,report,router}.py  # no DB/LLM
python backend/scripts/verify_graph_links.py    # after a reload; PG + Neo4j
python backend/scripts/assistant_smoke.py       # live: PG + Neo4j + Pinecone + LLM
```

**Do not add canned answers.** The frontend's scripted brain (`assistantScenarios.ts`) was
deleted deliberately; suggested prompts are starter questions, every answer is generated.

### 6. Frontend

Vite + React Router SPA (`frontend/src/App.tsx`) with a fixed demo user context (`frontend/src/config/demoUser.ts`). `frontend/src/lib/api.ts` wraps the backend REST surface; `assistantClient.ts` drives the live assistant (POST + WS + cancel). Scenario metadata lives in `frontend/src/data/scenarios.ts`; `assistantTranslations.ts` holds **UI chrome only** (prompt chips + static labels) — answers are generated by the agent in the officer's language.

`VITE_API_BASE_URL` **must include `/api/v1`** (both clients append paths straight to it). Leave it unset to use `vite.config.ts`'s dev proxy, which forwards `/api` and `/ws` (the latter with `ws: true`) to the hosted backend, sidestepping AppSail's CORS preflight gap.

## External services & required env vars

Postgres (Supabase pooler — **must** use the transaction pooler on port 6543 with `prepare_threshold=0` / `?prepared_statements=false`; port 5432 always times out from this network), Neo4j (`NEO4J_*`), Pinecone (`PINECONE_*`), AWS Bedrock (`AWS_*`, narrative generation + embeddings), Zoho Catalyst + Stratus (`ZOHO_*`, `X_ZOHO_*` — the `X_ZOHO_*` India-DC overrides **must** be set before any `zcatalyst_sdk` import, since the SDK reads them at import time), Zoho QuickML GLM/VLM (`ZOHO_QUICKML_*`). Full variable lists and troubleshooting for each service are in `AGENTS.md` — consult it for OAuth scope errors, Stratus hangs, and Supabase pooler connection errors before re-deriving fixes from scratch.
