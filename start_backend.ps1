param(
  [int]$Port = 8000,
  [switch]$Reload
)

$ErrorActionPreference = "Stop"

function Test-PanelStoreSqlite {
  param(
    [Parameter(Mandatory = $true)]
    [string]$SqlitePath
  )

  @'
import sqlite3
import sys

path = sys.argv[1]
try:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA schema_version;").fetchone()
    conn.close()
    print("ok")
except Exception as exc:
    print(exc)
    sys.exit(1)
'@ | python - $SqlitePath

  return $LASTEXITCODE -eq 0
}

function Repair-PanelStoreSqliteIfNeeded {
  param(
    [Parameter(Mandatory = $true)]
    [string]$DataDir
  )

  $sqlitePath = Join-Path $DataDir "panel_store.sqlite3"
  if (-not (Test-Path $sqlitePath)) {
    return
  }

  if (Test-PanelStoreSqlite -SqlitePath $sqlitePath) {
    return
  }

  $timestamp = Get-Date -Format "yyyyMMddHHmmss"
  $candidates = @(
    $sqlitePath,
    "$sqlitePath-journal",
    "$sqlitePath-wal",
    "$sqlitePath-shm"
  )

  Write-Host "Detected broken panel sqlite store, backing it up and rebuilding from panel_store.json ..." -ForegroundColor Yellow

  foreach ($path in $candidates) {
    if (-not (Test-Path $path)) {
      continue
    }

    $backupPath = "$path.broken.$timestamp"
    try {
      Move-Item -LiteralPath $path -Destination $backupPath -Force
    }
    catch {
      throw "面板数据库文件正在被占用，无法自动修复：$path。请先关闭正在运行的 NEWWEB 后端进程后再重试。"
    }
  }
}

$backendDir = Join-Path $PSScriptRoot "backend"
$dataDir = Join-Path $PSScriptRoot "data"
Push-Location $backendDir

try {
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 未安装，无法启动后端。"
  }

  Repair-PanelStoreSqliteIfNeeded -DataDir $dataDir

  $args = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $Port)
  if ($Reload) {
    $args += "--reload"
  }

  Write-Host "Starting backend at http://127.0.0.1:$Port" -ForegroundColor Cyan
  python @args
}
finally {
  Pop-Location
}
