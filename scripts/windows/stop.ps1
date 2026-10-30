# Stop T-Dashboard API (:8000) and Web (:5173) on Windows
$ErrorActionPreference = "Continue"

function Stop-PortListeners([int]$Port) {
  $pids = @(
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique
  )
  foreach ($procId in $pids) {
    if (-not $procId) { continue }
    Write-Host "Stopping PID $procId on port $Port"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  }
}

Stop-PortListeners 8000
Stop-PortListeners 5173
Start-Sleep -Seconds 1
Write-Host "Stopped. Ports 8000 / 5173 should be free."
