# Install project-local Allure CLI into tools/allure (requires Node + Java 8+)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Dir = Join-Path $Root "tools\allure"

Write-Host "Checking Java..."
java -version

Push-Location $Dir
try {
  npm install
} finally {
  Pop-Location
}

$cli = Join-Path $Dir "node_modules\allure-commandline\dist\bin\allure.bat"
if (-not (Test-Path $cli)) {
  Write-Error "Install finished but allure.bat not found at $cli"
  exit 1
}

Write-Host "Allure installed: $cli"
& $cli --version
Write-Host "Restart the API if it was already running, then click Allure report again."
