"""
API REST + servidor del dashboard.

Solo lectura: el único proceso que escribe en la base es el ETL.
Cada endpoint está anotado con la historia del user story mapping que atiende.

Arranque:  uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, etl, queries
from .queries import Filtros

RAIZ = Path(__file__).resolve().parents[2]
FRONTEND = RAIZ / "frontend"

app = FastAPI(
    title="Dashboard de Asignados · Secretaría Académica ECYS",
    description=(
        "Visor analítico de los snapshots del reporte 'TOTAL DE ASIGNADOS' de la "
        "Facultad de Ingeniería, USAC. Solo lectura. Ver docs/user-story-map.md."
    ),
    version="0.1.0-mvp",
)

_con = None


def con():
    global _con
    if _con is None:
        _con = db.connect()
        db.init_schema(_con)
    return _con


@app.on_event("startup")
def arranque() -> None:
    """Si la base está vacía, carga los snapshots que haya en data/snapshots/."""
    c = con()
    if not queries.snapshots(c):
        try:
            for r in etl.cargar_carpeta():
                print(f"[startup] snapshot cargado: {r['archivo']} ({r['secciones']} secciones)")
        except Exception as exc:  # noqa: BLE001 - el arranque no debe caerse por esto
            print(f"[startup] no se pudo cargar automáticamente: {exc}")


def filtros(
    snapshot_id: int | None = Query(None, description="Snapshot; por defecto el más reciente"),
    tipo: str | None = Query(None, description="Clase | Laboratorio"),
    area: str | None = None,
    jornada: str | None = None,
    modalidad: str | None = None,
    edificio: str | None = None,
    estado: str | None = None,
    docente: str | None = None,
    codigo: str | None = None,
    q: str | None = Query(None, description="Búsqueda libre: curso, código, docente, salón, auxiliar"),
) -> Filtros:
    """Filtros comunes a todos los endpoints (historia R1-02)."""
    f = Filtros(snapshot_id, tipo, area, jornada, modalidad, edificio, estado, docente, codigo, q)
    if f.snapshot_id is None:
        vigente = queries.snapshot_vigente(con())
        if not vigente:
            raise HTTPException(
                status_code=503,
                detail=("No hay snapshots cargados. Coloque el archivo .xlsx en "
                        "backend/data/snapshots/ y ejecute: python -m backend.app.etl"),
            )
        f.snapshot_id = vigente["id"]
    return f


# --------------------------------------------------------------------------- #
# Metadatos y trazabilidad  (R1-12)
# --------------------------------------------------------------------------- #
@app.get("/api/snapshots", tags=["metadatos"])
def api_snapshots():
    """Snapshots disponibles. Base de la comparación entre fotografías (R2-01)."""
    return {"snapshots": queries.snapshots(con())}


@app.get("/api/catalogos", tags=["metadatos"])
def api_catalogos(f: Filtros = Depends(filtros)):
    """Valores disponibles para poblar los filtros (R1-02)."""
    c = con()
    snap = next((s for s in queries.snapshots(c) if s["id"] == f.snapshot_id), None)
    return {"snapshot": snap, **queries.catalogos(c, f.snapshot_id)}


# --------------------------------------------------------------------------- #
# Vistas del dashboard
# --------------------------------------------------------------------------- #
@app.get("/api/kpis", tags=["dashboard"])
def api_kpis(f: Filtros = Depends(filtros)):
    """R1-01 · Encabezado: asignados, secciones, cursos, ocupación, cobertura de auxiliares."""
    return queries.kpis(con(), f)


@app.get("/api/cursos", tags=["dashboard"])
def api_cursos(
    f: Filtros = Depends(filtros),
    limite: int = Query(20, ge=1, le=400),
    orden: str = Query("asignados", pattern="^(asignados|secciones|promedio|ocupacion|codigo)$"),
):
    """R1-03 · Cursos ordenados por demanda, con secciones y promedio por sección."""
    return {"cursos": queries.cursos(con(), f, limite, orden)}


@app.get("/api/ocupacion", tags=["dashboard"])
def api_ocupacion(f: Filtros = Depends(filtros)):
    """R1-04 / R1-05 · Secciones clasificadas por ocupación."""
    return queries.ocupacion(con(), f)


@app.get("/api/docentes", tags=["dashboard"])
def api_docentes(
    f: Filtros = Depends(filtros),
    limite: int = Query(25, ge=1, le=500),
    orden: str = Query("asignados", pattern="^(asignados|secciones|horas|nombre)$"),
):
    """R1-06 · Carga por catedrático."""
    return {"docentes": queries.docentes(con(), f, limite, orden)}


@app.get("/api/auxiliares", tags=["dashboard"])
def api_auxiliares(f: Filtros = Depends(filtros), limite: int = Query(25, ge=1, le=500)):
    """R1-07 · Auxiliares de cátedra y secciones grandes sin auxiliar."""
    return queries.auxiliares(con(), f, limite)


@app.get("/api/heatmap", tags=["dashboard"])
def api_heatmap(f: Filtros = Depends(filtros)):
    """R1-08 · Ocupación por día y hora."""
    return queries.heatmap(con(), f)


@app.get("/api/salones", tags=["dashboard"])
def api_salones(f: Filtros = Depends(filtros), limite: int = Query(25, ge=1, le=300)):
    """R1-08 · Salones físicos por horas-semana ocupadas."""
    return {"salones": queries.salones(con(), f, limite)}


@app.get("/api/distribucion/{columna}", tags=["dashboard"])
def api_distribucion(columna: str, f: Filtros = Depends(filtros)):
    """R1-09 · Distribución por modalidad, jornada, área o tipo."""
    try:
        return {"columna": columna, "datos": queries.distribucion(con(), f, columna)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/secciones", tags=["dashboard"])
def api_secciones(
    f: Filtros = Depends(filtros),
    limite: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    orden: str = Query("asignados"),
):
    """R1-10 · Tabla explorable y búsqueda libre."""
    return queries.secciones(con(), f, limite, offset, orden)


# --------------------------------------------------------------------------- #
# R1-11 · Exportación
# --------------------------------------------------------------------------- #
@app.get("/api/export.csv", tags=["exportación"])
def api_export(f: Filtros = Depends(filtros), orden: str = "asignados"):
    """R1-11 · CSV de lo que está viendo el usuario, con la procedencia del dato."""
    c = con()
    snap = next((s for s in queries.snapshots(c) if s["id"] == f.snapshot_id), None)
    datos = queries.secciones(c, f, limite=5000, orden=orden)

    buffer = io.StringIO()
    buffer.write("﻿")  # BOM: Excel en Windows abre el CSV con acentos correctos
    w = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    w.writerow([f"# Fuente: {snap['archivo'] if snap else 'n/d'}"])
    w.writerow([f"# Período: {snap['periodo'] if snap else 'n/d'}"
                f" · Corte: {snap['fecha_corte'] if snap else 'n/d'}"])
    filtros_activos = {
        k: v for k, v in
        {"tipo": f.tipo, "area": f.area, "jornada": f.jornada, "modalidad": f.modalidad,
         "edificio": f.edificio, "estado": f.estado, "docente": f.docente,
         "codigo": f.codigo, "busqueda": f.q}.items() if v
    }
    w.writerow([f"# Filtros: {filtros_activos or 'ninguno'}"])
    w.writerow([f"# Registros: {datos['total']}"])
    w.writerow([])

    columnas = [
        ("tipo", "Tipo"), ("codigo", "Código"), ("curso", "Curso"), ("seccion", "Sección"),
        ("area", "Área"), ("docente", "Catedrático"), ("auxiliares", "Auxiliares"),
        ("edificio", "Edificio"), ("salon", "Salón"), ("modalidad", "Modalidad"),
        ("jornada", "Jornada"), ("dias", "Días"), ("hora_inicio", "Hora inicio"),
        ("hora_fin", "Hora final"), ("horas_semana", "Horas semana"),
        ("total", "Asignados"), ("limite", "Cupo"), ("ocupacion", "Ocupación"),
        ("estado", "Estado"), ("fila_origen", "Fila en el xlsx"),
    ]
    w.writerow([et for _, et in columnas])
    for fila in datos["filas"]:
        w.writerow([
            round(fila[k], 4) if k == "ocupacion" and fila[k] is not None else
            ("" if fila[k] is None else fila[k])
            for k, _ in columnas
        ])

    nombre = f"asignados_{(snap or {}).get('anio', '')}_{f.tipo or 'todo'}.csv".replace(" ", "_")
    return StreamingResponse(
        io.BytesIO(buffer.getvalue().encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# --------------------------------------------------------------------------- #
# Salud y front
# --------------------------------------------------------------------------- #
@app.get("/api/salud", tags=["metadatos"])
def api_salud():
    snaps = queries.snapshots(con())
    return {
        "estado": "ok" if snaps else "sin datos",
        "snapshots": len(snaps),
        "base": str(db.DB_PATH),
        "area_foco": config.AREA_FOCO,
        "version": app.version,
    }


@app.get("/", include_in_schema=False)
def raiz():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
