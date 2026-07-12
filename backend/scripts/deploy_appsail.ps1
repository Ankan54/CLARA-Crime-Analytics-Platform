param(
    [string]$AppSailName = "ksp-catalyst-backend"
)

Write-Host "[deploy_appsail] Deploying AppSail app: $AppSailName"
Write-Host "[deploy_appsail] Ensure you already ran: catalyst login"

# Uses backend/app-config.json in this directory.
Push-Location (Join-Path $PSScriptRoot "..")
try {
    catalyst deploy
} finally {
    Pop-Location
}

Write-Host "[deploy_appsail] After deploy, set SPLINK_ENDPOINT_URL in function env."

