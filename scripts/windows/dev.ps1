# Start T-Dashboard (Windows): API :8000 + Web :5173
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

$venvPython = Join-Path $Root "apps\server\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Host "Creating venv..."
  python -m venv (Join-Path $Root "apps\server\.venv")
  & $venvPython -m pip install -r (Join-Path $Root "apps\server\requirements.txt")
  & $venvPython -m playwright install chromium
}

$webModules = Join-Path $Root "apps\web\node_modules"
if (-not (Test-Path $webModules)) {
  Write-Host "Installing frontend deps..."
  Push-Location (Join-Path $Root "apps\web")
  npm install
  Pop-Location
}

Write-Host "Starting API on :8000 and Web on :5173 ..."
$api = Start-Process -PassThru -NoNewWindow -FilePath $venvPython -ArgumentList @(
  "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"
) -WorkingDirectory (Join-Path $Root "apps\server")

$npmCmd = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
if (-not (Test-Path $npmCmd)) { $npmCmd = "npm.cmd" }
$web = Start-Process -PassThru -NoNewWindow -FilePath $npmCmd -ArgumentList @("run", "dev") `
  -WorkingDirectory (Join-Path $Root "apps\web")

Write-Host "API PID=$($api.Id)  WEB PID=$($web.Id)"
Write-Host "Open http://localhost:5173"
Write-Host "Press Ctrl+C to stop."

try {
  Wait-Process -Id $api.Id
} finally {
  if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
  if (-not $web.HasExited) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
}
