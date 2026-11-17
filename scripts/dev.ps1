param([ValidateSet('api', 'web')][string]$Target = 'web')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ($Target -eq 'api') {
    Set-Location (Join-Path $projectRoot 'api')
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8010 --workers 1
} else {
    Set-Location (Join-Path $projectRoot 'web')
    npm run dev
}
