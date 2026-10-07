"""Configuración común de la suite: cada prueba corre con su propia carpeta de datos."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.app import config

FIXTURES = Path(__file__).parent / "fixtures"
REAL_2026 = FIXTURES / "primer_semestre_2026.xlsx"            # 30 columnas, sin Escuela/Area
REAL_2025 = FIXTURES / "vacaciones_primer_semestre_2025.xlsx"  # 33 columnas, con Escuela/Area
REAL_VACIO = FIXTURES / "finales_primer_semestre_2023_vacio.xlsx"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Carpetas de datos aisladas + base recién creada."""
    datos, entrada = tmp_path / "datos", tmp_path / "entrada"
    rutas = {"DATA_DIR": datos, "DB_PATH": datos / "asignados.db", "ARCHIVO_DIR": datos / "archivo",
             "ENTRADA_DIR": entrada, "PROCESADOS_DIR": entrada / "procesados",
             "RECHAZADOS_DIR": entrada / "rechazados"}
    for k, v in rutas.items():
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    monkeypatch.setattr(config, "INTERVALO_ENTRADA_SEG", 0)
    from backend.app import ingesta
    ingesta.asegurar_esquema()
    return tmp_path


@pytest.fixture
def cliente(entorno):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def copia(tmp_path):
    """Copia un fixture real a un temporal (para mutarlo sin tocar el original)."""
    def _copia(origen: Path, nombre: str | None = None) -> Path:
        destino = tmp_path / "copias" / (nombre or origen.name)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(origen, destino)
        return destino
    return _copia


def subir(cliente, *rutas, token=None):
    archivos = [("archivos", (Path(r).name, Path(r).read_bytes(), "application/octet-stream")) for r in rutas]
    headers = {"X-Admin-Token": token} if token else {}
    return cliente.post("/api/cargas", files=archivos, headers=headers)
