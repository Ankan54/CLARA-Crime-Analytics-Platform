# Backend (FastAPI)

API, pipeline orchestration, review queue, and CLARA assistant for the KSP Crime Intelligence Platform.

Full setup, env vars, sample-data load, and Catalyst / Docker Hub deploy: see the [root README](../README.md).

## Local run

```powershell
# From repo root — requires root `.env` (copy from `.env.example`)
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 9000
```

## Layout

- `app/` — FastAPI routers, services, assistant (LangGraph)
- `migrations/` — Postgres schema, historical reload scripts
- `Dockerfile.appsail` — AppSail / Docker Hub image
- `requirements.txt` / `requirements.appsail.txt` — deps

## Deploy image

```powershell
docker build -f backend/Dockerfile.appsail -t YOUR_DOCKERHUB_USER/ksp-catalyst-backend:latest .
docker push YOUR_DOCKERHUB_USER/ksp-catalyst-backend:latest
catalyst deploy appsail --name ksp-catalyst-backend --source docker://YOUR_DOCKERHUB_USER/ksp-catalyst-backend:latest --port 9000
```
