# ingest_processor (Catalyst Job Function)

Two-phase ingestion job for the KSP platform.

- **Phase A (`extract`)** — read `raw/`, extract / classify / checkpoint to `processed/`, person matching, stop at `REVIEW_PENDING`
- **Phase B (`load`)** — apply review decisions, load Postgres / Neo4j / Pinecone, archive to `archive/`

Full env setup and deploy steps: see the [root README](../../README.md).

## Config

```powershell
copy catalyst-config.example.json catalyst-config.json
```

Fill in DB, Neo4j, Pinecone, Zoho Catalyst / QuickML, and set `DATA_INGESTION_LLM=zoho`. Point `SPLINK_ENDPOINT_URL` at the deployed backend.

## Deploy

```powershell
# From repo root (catalyst.json must list ingest_processor under functions.targets)
catalyst deploy --only functions:ingest_processor
```

## Stratus layout

```
raw/{batch_id}/...
processed/{case_id}/{run_id}/manifest.json
archive/{case_id}/{run_id}/...
```
