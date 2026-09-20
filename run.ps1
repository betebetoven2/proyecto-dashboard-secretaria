# Dashboard de Asignados - arranque para Windows
# Uso:  powershell -ExecutionPolicy Bypass -File run.ps1
#       powershell -ExecutionPolicy Bypass -File run.ps1 -Recargar   (fuerza recarga del ETL)

param([switch]$Recargar, [int]$Puerto = 8000)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

if (-not (Test-Path ".venv")) {
    Write-Host "[1/3] Creando entorno virtual..." -ForegroundColor Cyan
    & $py -m venv .venv
    & .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    & .venv\Scripts\pip.exe install -r requirements.txt
} else {
    Write-Host "[1/3] Entorno virtual ya existe." -ForegroundColor DarkGray
}

$base = "backend\data\asignados.db"
if ($Recargar -or -not (Test-Path $base)) {
    Write-Host "[2/3] Cargando snapshots desde backend\data\snapshots ..." -ForegroundColor Cyan
    if ($Recargar -and (Test-Path $base)) { Remove-Item "backend\data\asignados.db*" -Force }
    & .venv\Scripts\python.exe -m backend.app.etl
} else {
    Write-Host "[2/3] Base ya cargada (use -Recargar para rehacerla)." -ForegroundColor DarkGray
}

Write-Host "[3/3] Tablero en http://127.0.0.1:$Puerto  ·  API en /docs" -ForegroundColor Green
& .venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port $Puerto
