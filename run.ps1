# Dashboard de Asignados - ejecución SIN Docker (desarrollo en Windows)
# Para instalar en producción use Docker:  docker compose up -d --build
#
# Uso:  powershell -ExecutionPolicy Bypass -File run.ps1 [-Pruebas] [-Puerto 8000]

param([switch]$Pruebas, [int]$Puerto = 8000)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[1/3] Creando entorno virtual..." -ForegroundColor Cyan
    & $py -m venv .venv
}
Write-Host "[2/3] Instalando dependencias..." -ForegroundColor Cyan
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\pip.exe install --quiet -r requirements-dev.txt

if ($Pruebas) {
    & .venv\Scripts\python.exe -m pytest
    exit $LASTEXITCODE
}

Write-Host "[3/3] Tablero en http://127.0.0.1:$Puerto  (datos en .\datos, carpeta vigilada en .\datos\entrada)" -ForegroundColor Green
& .venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port $Puerto
