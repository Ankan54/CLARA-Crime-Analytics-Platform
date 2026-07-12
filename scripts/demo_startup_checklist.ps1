param(
    [string]$BackendBaseUrl = "http://localhost:9000",
    [switch]$NoChecks,
    [switch]$RunResetDryRun
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    Write-Host "  [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "  [WARN] $Text" -ForegroundColor Yellow
}

function Test-Command {
    param([string]$Name)
    try {
        $null = Get-Command $Name -ErrorAction Stop
        Write-Ok "$Name is available"
        return $true
    }
    catch {
        Write-Warn "$Name is not available"
        return $false
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "Crime Analytics Assistant - Demo Startup Checklist" -ForegroundColor Magenta
Write-Host "Repository: $repoRoot"
Write-Host "Backend URL: $BackendBaseUrl"

Write-Step "Tooling checks"
$hasPython = Test-Command -Name "python"
$hasNpm = Test-Command -Name "npm"
$hasCatalyst = Test-Command -Name "catalyst"

Write-Step "Frontend environment file"
$frontendEnvPath = Join-Path $repoRoot "frontend\.env"
$frontendEnvExamplePath = Join-Path $repoRoot "frontend\.env.example"
if (Test-Path $frontendEnvPath) {
    Write-Ok "frontend/.env exists"
}
elseif (Test-Path $frontendEnvExamplePath) {
    Write-Warn "frontend/.env missing. Copy frontend/.env.example before running npm run dev."
}
else {
    Write-Warn "frontend/.env.example missing."
}

Push-Location $repoRoot
try {
    if (-not $NoChecks) {
        Write-Step "Backend route registration check"
        if ($hasPython) {
            python "backend/scripts/verify_routes.py"
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Route check passed"
            }
            else {
                Write-Warn "Route check failed with exit code $LASTEXITCODE"
            }
        }
        else {
            Write-Warn "Skipping route check because python is unavailable"
        }

        Write-Step "Backend health check"
        try {
            $health = Invoke-RestMethod -Method Get -Uri "$BackendBaseUrl/healthz" -TimeoutSec 8
            if ($health.status -eq "ok") {
                Write-Ok "Backend health is OK"
            }
            else {
                Write-Warn "Backend responded but status was unexpected: $($health | ConvertTo-Json -Compress)"
            }
        }
        catch {
            Write-Warn "Backend health check failed for $BackendBaseUrl/healthz"
            Write-Warn "Ensure backend is running locally or update -BackendBaseUrl."
        }
    }

    if ($RunResetDryRun) {
        Write-Step "Demo data reset dry-run"
        if ($hasPython) {
            python "scripts/reset_demo_data.py" --dry-run
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Reset dry-run completed"
            }
            else {
                Write-Warn "Reset dry-run failed with exit code $LASTEXITCODE"
            }
        }
        else {
            Write-Warn "Skipping reset dry-run because python is unavailable"
        }
    }
}
finally {
    Pop-Location
}

Write-Step "Manual deployment sequence"
Write-Host "  1) Deploy ingestion job function:"
Write-Host "     powershell -ExecutionPolicy Bypass -File `"catalyst_functions/ingest_processor/deploy_function.ps1`""
Write-Host "  2) Deploy backend to AppSail:"
Write-Host "     powershell -ExecutionPolicy Bypass -File `"backend/scripts/deploy_appsail.ps1`""
Write-Host "  3) Set function env SPLINK_ENDPOINT_URL to your deployed AppSail URL"
Write-Host "  4) Verify AppSail health:"
Write-Host "     curl <appsail-url>/healthz"
Write-Host "  5) For iterative demo runs, clear demo data:"
Write-Host "     python scripts/reset_demo_data.py --yes"

Write-Step "Frontend run commands"
if ($hasNpm) {
    Write-Host "  cd frontend"
    Write-Host "  npm install"
    Write-Host "  npm run dev"
}
else {
    Write-Warn "npm not found; install Node.js to run the frontend"
}

if (-not $hasCatalyst) {
    Write-Warn "Catalyst CLI missing. Install with: npm i -g zcatalyst-cli"
}

Write-Host ""
Write-Host "Checklist complete." -ForegroundColor Green
