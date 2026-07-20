# Frontend (React + Vite)

Demo UI: dashboard, ingest, scenarios, admin, and CLARA assistant.

Full setup and Catalyst / Docker Hub deploy: see the [root README](../README.md).

## Local run

```powershell
cd frontend
copy .env.example .env
npm install
npm run dev
```

Leave `VITE_API_BASE_URL` unset to use the Vite proxy to a local backend on port 9000.

## Deploy image

Set `BACKEND_URL` / `VITE_WS_BASE_URL` for your live backend before building (`frontend/Dockerfile.appsail`).

```powershell
docker build -f frontend/Dockerfile.appsail -t YOUR_DOCKERHUB_USER/ksp-catalyst-frontend:latest .
docker push YOUR_DOCKERHUB_USER/ksp-catalyst-frontend:latest
catalyst deploy appsail --name ksp-catalyst-frontend --source docker://YOUR_DOCKERHUB_USER/ksp-catalyst-frontend:latest --port 9000
```
