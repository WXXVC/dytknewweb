param(
  [int]$Port = 4173
)

$ErrorActionPreference = "Stop"

$frontendDir = Join-Path $PSScriptRoot "frontend"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python 未安装，无法启动前端静态服务。"
}

Write-Host "Starting frontend at http://127.0.0.1:$Port" -ForegroundColor Cyan
python -m http.server $Port --bind 127.0.0.1 --directory $frontendDir
