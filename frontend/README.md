# Crime Analytics Assistant Frontend

React + TypeScript + Vite UI for the hackathon demo.

## What This Frontend Includes

- Minimal landing page with animated graph motif and one CTA to Dashboard.
- Dashboard, Ingest, Assistant (placeholder), and Admin pages.
- API wiring to existing FastAPI endpoints and pipeline WebSocket updates.
- Fixed demo user context:
  - `EmployeeID`: `5007`
  - `KGID`: `KG006001`
  - `Name`: `Deepa Kamath`

## Local Development

```bash
cd frontend
npm install
npm run dev
```

Environment template:

```bash
cp .env.example .env
```

By default, the app points to:

- `http://localhost:9000` for API calls
- `ws://localhost:9000/ws/pipeline/{run_id}` for live run status

Override API base URL with:

```bash
VITE_API_BASE_URL=https://<your-backend-host>
```

The default `.env.example` value is:

```bash
VITE_API_BASE_URL=http://localhost:9000
```

## Backend Endpoints Used

- `GET /api/v1/runs`
- `GET /api/v1/cases`
- `GET /api/v1/cases/{case_id}`
- `POST /api/v1/upload`
- `POST /api/v1/process/{batch_id}`
- `POST /api/v1/process/{run_id}/proceed`
- `POST /api/v1/process/{run_id}/retry`
- `GET /api/v1/pipeline-status/{run_id}`
- `WS /ws/pipeline/{run_id}`
- `GET /api/v1/process/{run_id}/findings`
- `GET /api/v1/review-queue?run_id=...`
- `GET/PUT /api/v1/admin/config/entity-review-threshold`
- `GET /api/v1/admin/schema`
- `GET /api/v1/admin/schema/{doc_type}`
- `GET /api/v1/admin/schema/{doc_type}/versions`
- `PUT /api/v1/admin/schema/{doc_type}/activate/{version}`

## Deployment Runbook (Backend + Function)

The frontend depends on these two runtime pieces:

1. **Catalyst job function** (`ingest_processor`)
2. **FastAPI backend on AppSail**

### 1) Deploy `ingest_processor` (serverless function)

```powershell
powershell -ExecutionPolicy Bypass -File "catalyst_functions/ingest_processor/deploy_function.ps1"
```

After deployment, verify function env vars in Catalyst:

- DB (`DATABASE_URL` or `DB_*`)
- Neo4j (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`)
- Pinecone (`PINECONE_API_KEY`, `PINECONE_INDEX`)
- AWS (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`)
- Zoho (`ZOHO_*`, `X_ZOHO_*`)
- Internal integration (`SPLINK_ENDPOINT_URL`, `SPLINK_SHARED_SECRET`, `SIGNALS_PIPELINE_PUBLISHER_URL`)

### 2) Deploy FastAPI backend to AppSail

```powershell
powershell -ExecutionPolicy Bypass -File "backend/scripts/deploy_appsail.ps1"
```

After deployment:

- Verify `GET /healthz` on the AppSail URL.
- Set function-side `SPLINK_ENDPOINT_URL` to this deployed AppSail URL.

## Iterative Demo Data Reset

The reset utility already exists and is safe for iterative demo testing:

- Script: `scripts/reset_demo_data.py`
- Scope: removes **demo-run** data from Postgres, Neo4j, Pinecone, and Stratus (`raw/`, `processed/`, `archive/`) while preserving historical seed data.

Commands:

```bash
python scripts/reset_demo_data.py --dry-run
python scripts/reset_demo_data.py --yes
```

Use `--yes` after each demo ingestion cycle to re-run the same scenario upload cleanly.

## Quick Demo Startup Checklist Script

Use the helper script from repo root to validate prerequisites and print the deployment/run sequence:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts/demo_startup_checklist.ps1"
```

Optional flags:

```powershell
# Skip live checks, print checklist only
powershell -ExecutionPolicy Bypass -File "scripts/demo_startup_checklist.ps1" -NoChecks

# Include reset dry-run in the checklist run
powershell -ExecutionPolicy Bypass -File "scripts/demo_startup_checklist.ps1" -RunResetDryRun
```

## Build

```bash
npm run build
```
