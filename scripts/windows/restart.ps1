# Restart T-Dashboard API (:8000) and Web (:5173) on Windows
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

& (Join-Path $PSScriptRoot "stop.ps1")
Start-Sleep -Seconds 1

$venvPython = Join-Path $Root "apps\server\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Error "Missing server venv. Run .\scripts\windows\dev.ps1 first."
  exit 1
}

Write-Host "Starting API on :8000 ..."
Start-Process -FilePath $venvPython -ArgumentList @(
  "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"
) -WorkingDirectory (Join-Path $Root "apps\server") -WindowStyle Hidden

Write-Host "Starting Web on :5173 ..."
$npmCmd = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
if (-not (Test-Path $npmCmd)) { $npmCmd = "npm.cmd" }
Start-Process -FilePath $npmCmd -ArgumentList @("run", "dev") `
  -WorkingDirectory (Join-Path $Root "apps\web") -WindowStyle Hidden

Start-Sleep -Seconds 2
Write-Host "Restarted. Open http://localhost:5173"
Write-Host "API health: http://127.0.0.1:8000/api/health"
