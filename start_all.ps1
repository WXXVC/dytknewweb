param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 4173,
  [switch]$Reload
)

$ErrorActionPreference = "Stop"

$shellPath = (Get-Process -Id $PID).Path
$backendScript = Join-Path $PSScriptRoot "start_backend.ps1"
$frontendScript = Join-Path $PSScriptRoot "start_frontend.ps1"

$backendArgs = @(
  "-NoExit",
  "-ExecutionPolicy", "Bypass",
  "-File", $backendScript,
  "-Port", $BackendPort
)

if ($Reload) {
  $backendArgs += "-Reload"
}

$frontendArgs = @(
  "-NoExit",
  "-ExecutionPolicy", "Bypass",
  "-File", $frontendScript,
  "-Port", $FrontendPort
)

Start-Process -FilePath $shellPath -ArgumentList $backendArgs | Out-Null
Start-Process -FilePath $shellPath -ArgumentList $frontendArgs | Out-Null

Write-Host "Backend:  http://127.0.0.1:$BackendPort" -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:$FrontendPort" -ForegroundColor Green
Write-Host "Two PowerShell windows were opened for the panel services." -ForegroundColor Green
