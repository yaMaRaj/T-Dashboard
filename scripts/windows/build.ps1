# Build frontend production bundle (apps/web/dist) on Windows
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Web = Join-Path $Root "apps\web"

Push-Location $Web
try {
  if (-not (Test-Path (Join-Path $Web "node_modules"))) {
    Write-Host "Installing frontend deps..."
    npm install
  }
  Write-Host "Building frontend..."
  npm run build
  Write-Host "Done. Output: apps\web\dist"
} finally {
  Pop-Location
}
