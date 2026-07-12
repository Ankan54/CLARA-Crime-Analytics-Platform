Write-Host "[deploy_function] Deploying ingest_processor Catalyst Job Function"
Write-Host "[deploy_function] Ensure you already ran: catalyst login"

Push-Location (Join-Path $PSScriptRoot "..\..")
try {
    catalyst deploy
} finally {
    Pop-Location
}

Write-Host "[deploy_function] Create/verify Function Job Pool in Catalyst console:"
Write-Host "  Cloud Scale -> Job Scheduling -> Job Pools -> New -> target type Function"
Write-Host "[deploy_function] Then set env vars for DB/Neo4j/Pinecone/AWS/SPLINK endpoint."
Write-Host "[deploy_function] Also set SIGNALS_PIPELINE_PUBLISHER_URL and SPLINK_SHARED_SECRET"
Write-Host "  (the publish call to Signals runs inside this function, not the backend)."
Write-Host "[deploy_function] Also set ZOHO_QUICKML_VLM_ENDPOINT_URL (+ ZOHO_QUICKML_VLM_MODEL_NAME)"
Write-Host "  for image (.png/.jpg/.jpeg/.webp) extraction. Verify first: python scripts/test_zoho_vlm.py"

