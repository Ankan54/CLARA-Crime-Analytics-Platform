# ingest_processor (Catalyst Job Function)

Two-phase ingestion job: **Phase A** (`extract`) reads `raw/`, extracts + transforms +
checkpoints to `processed/`, runs person entity matching, and stops at
`REVIEW_PENDING`. **Phase B** (`load`), triggered after manual review via
`POST /process/{run_id}/proceed`, resumes from the `processed/` checkpoint, applies
review decisions, loads Postgres/Neo4j/Pinecone, then moves the run's raw files to
`archive/`.

## Stratus layout

```
raw/{batch_id}/{file_type}_{filename}            # uploaded, pre-processing
processed/{case_id}/{run_id}/manifest.json       # Phase A checkpoint (resumable)
archive/{case_id}/{run_id}/{file_type}_{filename} # moved here at the end of Phase B
```

## Expected params

```json
{
  "batch_id": "uuid",
  "case_id": "int-as-string",
  "run_id": "{case_id}_{YYYYMMDDTHHMMSSZ}",
  "phase": "extract | load"
}
```

`batch_id`/`case_id`/`run_id` are minted by the backend's `POST /api/v1/process/{batch_id}`
(phase=`extract`) and `POST /api/v1/process/{run_id}/proceed` (phase=`load`) — see
[backend/app/routers/process.py](../../backend/app/routers/process.py).

## Accepted file types

`txt, html, pdf, docx, png, jpg, jpeg, webp` (per-doc-type allow-list lives in
`SchemaDefinition.allowed_file_extensions`, enforced by the backend at upload time).
`_extract_text` in [pipeline/processor.py](pipeline/processor.py) dispatches by extension:
`.docx` via `python-docx`; images via the Zoho-hosted Qwen3 VLM (`llm.py::describe_image`,
same OAuth token flow as the GLM classifier) — the transcribed text feeds the normal
classify → schema-extract flow, so no format-specific handling exists downstream of
extraction. Verify VLM connectivity first with `python scripts/test_zoho_vlm.py` (repo root).

## Local smoke run

```bash
python -c "from main import handler; print(handler({'params': {'batch_id':'b','case_id':'1','run_id':'1_20260101T000000Z','phase':'extract'}}))"
```

Or run the full Phase A -> Phase B self-check against a sample FIR (needs real
Postgres/Stratus/Neo4j/Pinecone credentials in `.env`, no backend server required):

```bash
python catalyst_functions/ingest_processor/self_check.py
```

`_extract_text`'s format branches (txt/html/pdf/docx/image) can be checked offline, with
no DB/Stratus network access, via:

```bash
python catalyst_functions/ingest_processor/test_extract_formats.py
```

## Deployment notes

1. Install Catalyst CLI globally: `npm i -g zcatalyst-cli`
2. Login India DC: `catalyst login`
3. Init/bind project and function: `catalyst init`
4. Deploy function: `catalyst deploy`

Set env vars in function configuration for:

- Postgres (`DATABASE_URL` or `DB_*`)
- Neo4j (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`)
- Pinecone (`PINECONE_API_KEY`, `PINECONE_INDEX`)
- AWS (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `BEDROCK_EMBEDDING_MODEL`)
- Zoho (`ZOHO_*`, `X_ZOHO_*`)
- LLM selection (`DATA_INGESTION_LLM`)
- Splink callback (`SPLINK_ENDPOINT_URL`, `SPLINK_SHARED_SECRET`)
- Signals (`SIGNALS_PIPELINE_PUBLISHER_URL`) — pushes `stage_update` events for the
  backend's `/ws/pipeline/{run_id}`; safe to leave unset (best-effort, Postgres poll
  is the fallback)
