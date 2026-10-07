"""
API REST + servidor del tablero.

Arranque:  uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
           (en Docker lo hace el contenedor; ver docker-compose.yml)

La API es de solo lectura sobre los datos de la Facultad. Lo único que escribe es
la carga de reportes (que pasa por `ingesta`) y la administración de snapshots,
protegidas con ADMIN_TOKEN cuando está definido.
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, ingesta, queries, vigilante
from .queries import Filtros

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("asignados")
FRONTEND = config.RAIZ_PROYECTO / "frontend"
MAX_ARCHIVOS_POR_SUBIDA = 30


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    ingesta.asegurar_esquema()
    detener = threading.Event()
    vigilante.iniciar(detener)
    log.info("Tablero listo. Datos en %s", config.DATA_DIR)
    yield
    detener.set()


app = FastAPI(
    title="Dashboard de Asignados · Secretaría Académica ECYS",
    description=("Visor de los reportes «TOTAL DE ASIGNADOS» de Centro de Cálculo, Facultad de "
                 "Ingeniería, USAC. Ver docs/user-story-map.md y docs/arquitectura.md."),
    version=config.VERSION,
    lifespan=ciclo_de_vida,
)


# ═══════════════════════════════════════════════════════════════════════════
# Dependencias
# ═══════════════════════════════════════════════════════════════════════════
def con():
    c = db.conectar()
    try:
        yield c
    finally:
        c.close()


def requiere_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not config.ADMIN_TOKEN:
        return
    if not x_admin_token or not hmac.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(401, "Esta acción requiere el token de administración.")


def filtros(
    c=Depends(con),
    snapshot_id: int | None = Query(None, description="Por defecto: corte más reciente del período más reciente"),
    tipo: str | None = None, escuela: str | None = None, area: str | None = None,
    jornada: str | None = None, modalidad: str | None = None, edificio: str | None = None,
    estado: str | None = None, estado_gestion: str | None = None, docente: str | None = None,
    codigo: str | None = None,
    q: str | None = Query(None, max_length=120),
) -> Filtros:
    f = Filtros(snapshot_id, tipo, escuela, area, jornada, modalidad, edificio, estado,
                estado_gestion, docente, codigo, q)
    if f.snapshot_id is None:
        vigente = queries.snapshot_vigente(c)
        if not vigente:
            raise HTTPException(404, detail="sin_snapshots")
        f.snapshot_id = vigente["id"]
    elif not queries.snapshot(c, f.snapshot_id):
        raise HTTPException(404, detail="snapshot_inexistente")
    return f


# ═══════════════════════════════════════════════════════════════════════════
# Metadatos
# ═══════════════════════════════════════════════════════════════════════════
@app.get("/api/salud", tags=["metadatos"])
def api_salud(c=Depends(con)):
    snaps = queries.snapshots(c)
    return {"estado": "ok", "version": config.VERSION, "snapshots": len(snaps),
            "requiere_token": bool(config.ADMIN_TOKEN), "max_mb": config.MAX_MB,
            "carpeta_entrada_activa": config.INTERVALO_ENTRADA_SEG > 0,
            "intervalo_entrada_seg": config.INTERVALO_ENTRADA_SEG,
            "escuela_foco": config.ESCUELA_FOCO}


@app.get("/api/snapshots", tags=["metadatos"])
def api_snapshots(c=Depends(con)):
    return {"snapshots": queries.snapshots(c)}


@app.get("/api/periodos", tags=["metadatos"])
def api_periodos(c=Depends(con)):
    """Árbol año → período → cortes para los selectores."""
    return {"periodos": queries.periodos(c)}


@app.get("/api/catalogos", tags=["metadatos"])
def api_catalogos(f: Filtros = Depends(filtros), c=Depends(con)):
    return {"snapshot": queries.snapshot(c, f.snapshot_id),
            **queries.catalogos(c, f.snapshot_id, f.escuela)}


# ═══════════════════════════════════════════════════════════════════════════
# Vistas
# ═══════════════════════════════════════════════════════════════════════════
@app.get("/api/kpis", tags=["tablero"])
def api_kpis(f: Filtros = Depends(filtros), c=Depends(con)):
    """R1-01"""
    return queries.kpis(c, f)


@app.get("/api/cursos", tags=["tablero"])
def api_cursos(f: Filtros = Depends(filtros), c=Depends(con),
               limite: int = Query(20, ge=1, le=500),
               orden: str = Query("asignados", pattern="^(asignados|secciones|promedio|ocupacion|codigo|pendientes)$")):
    """R1-03"""
    return {"cursos": queries.cursos(c, f, limite, orden)}


@app.get("/api/ocupacion", tags=["tablero"])
def api_ocupacion(f: Filtros = Depends(filtros), c=Depends(con)):
    """R1-04 / R1-05"""
    return queries.ocupacion(c, f)


@app.get("/api/docentes", tags=["tablero"])
def api_docentes(f: Filtros = Depends(filtros), c=Depends(con),
                 limite: int = Query(25, ge=1, le=1000),
                 orden: str = Query("asignados", pattern="^(asignados|secciones|horas|nombre)$")):
    """R1-06"""
    return {"docentes": queries.docentes(c, f, limite, orden)}


@app.get("/api/auxiliares", tags=["tablero"])
def api_auxiliares(f: Filtros = Depends(filtros), c=Depends(con),
                   limite: int = Query(25, ge=1, le=1000)):
    """R1-07"""
    return queries.auxiliares(c, f, limite)


@app.get("/api/heatmap", tags=["tablero"])
def api_heatmap(f: Filtros = Depends(filtros), c=Depends(con)):
    """R1-08"""
    return queries.heatmap(c, f)


@app.get("/api/salones", tags=["tablero"])
def api_salones(f: Filtros = Depends(filtros), c=Depends(con), limite: int = Query(25, ge=1, le=500)):
    """R1-08"""
    return {"salones": queries.salones(c, f, limite)}


@app.get("/api/distribucion/{columna}", tags=["tablero"])
def api_distribucion(columna: str, f: Filtros = Depends(filtros), c=Depends(con)):
    """R1-09"""
    try:
        return {"columna": columna, "datos": queries.distribucion(c, f, columna)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/secciones", tags=["tablero"])
def api_secciones(f: Filtros = Depends(filtros), c=Depends(con),
                  limite: int = Query(100, ge=1, le=5000), offset: int = Query(0, ge=0),
                  orden: str = Query("asignados")):
    """R1-10"""
    return queries.secciones(c, f, limite, offset, orden)


@app.get("/api/gestiones", tags=["perfil"])
def api_gestiones(f: Filtros = Depends(filtros), c=Depends(con),
                  limite_cursos: int = Query(15, ge=1, le=200)):
    """R1-13 · Vista «estado de gestiones» del perfil."""
    return queries.estado_gestiones(c, f, limite_cursos)


@app.get("/api/tiempos", tags=["perfil"])
def api_tiempos(f: Filtros = Depends(filtros), c=Depends(con)):
    """R1-14 · Vista «tiempos de atención» del perfil (requiere ≥2 cortes del período)."""
    return queries.tiempos_atencion(c, f)


@app.get("/api/evolucion", tags=["perfil"])
def api_evolucion(f: Filtros = Depends(filtros), c=Depends(con)):
    """R2-01 · Seguimiento entre cortes del período y entre períodos."""
    return queries.evolucion(c, f)


# ═══════════════════════════════════════════════════════════════════════════
# Exportaciones (R1-11) y contrato para Power BI
# ═══════════════════════════════════════════════════════════════════════════
def _celda_segura(v):
    """Evita inyección de fórmulas al abrir el CSV en Excel."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def _csv(encabezado_meta: list[str], columnas: list[str], filas, nombre: str) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")  # BOM: Excel en Windows respeta las tildes
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    for linea in encabezado_meta:
        w.writerow([_celda_segura(linea)])
    if encabezado_meta:
        w.writerow([])
    w.writerow(columnas)
    for fila in filas:
        w.writerow([_celda_segura(v) for v in fila])
    return StreamingResponse(io.BytesIO(buf.getvalue().encode("utf-8")),
                             media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _meta_filtros(c, f: Filtros, registros: int) -> list[str]:
    s = queries.snapshot(c, f.snapshot_id) or {}
    activos = {k: getattr(f, k) for k in (*Filtros.SIMPLES, "q") if getattr(f, k)}
    return [f"# Fuente: {s.get('archivo_nombre', 'n/d')} (sha256 {str(s.get('sha256', ''))[:12]})",
            f"# Período: {s.get('periodo_nombre', 'n/d')} {s.get('anio', '')} · corte {s.get('fecha_corte', 'n/d')}",
            f"# Filtros: {activos or 'ninguno'}", f"# Registros: {registros}"]


@app.get("/api/export.csv", tags=["exportación"])
def api_export(f: Filtros = Depends(filtros), c=Depends(con), orden: str = "asignados"):
    """R1-11 · Las secciones filtradas, con la procedencia del dato en la cabecera."""
    datos = queries.secciones(c, f, limite=100000, orden=orden)
    cols = [("tipo", "Tipo"), ("codigo", "Código"), ("curso", "Curso"), ("seccion", "Sección"),
            ("escuela", "Escuela"), ("area", "Área"), ("clasificacion_origen", "Origen clasificación"),
            ("docente", "Catedrático"), ("auxiliares", "Auxiliares"), ("otros_miembros", "Otros miembros"),
            ("edificio", "Edificio"), ("salon", "Salón"), ("modalidad", "Modalidad"),
            ("jornada", "Jornada"), ("dias", "Días"), ("hora_inicio", "Hora inicio"),
            ("hora_fin", "Hora final"), ("horas_semana", "Horas semana"), ("total", "Asignados"),
            ("limite", "Cupo"), ("limite_min", "Mínimo"), ("ocupacion", "Ocupación"),
            ("estado", "Estado"), ("estado_gestion", "Estado de gestión"),
            ("gestiones", "Gestiones"), ("fila_origen", "Fila en el xlsx")]
    filas = ([round(r[k], 4) if k == "ocupacion" and r[k] is not None else r[k] for k, _ in cols]
             for r in datos["filas"])
    s = queries.snapshot(c, f.snapshot_id)
    return _csv(_meta_filtros(c, f, datos["total"]), [e for _, e in cols], filas,
                f"secciones_{s['anio']}_{s['periodo_codigo'] or 'xx'}_{s['id']}.csv")


@app.get("/api/export/gestiones.csv", tags=["exportación"])
def api_export_gestiones(f: Filtros = Depends(filtros), c=Depends(con)):
    datos = queries.estado_gestiones(c, f)["detalle"]
    cols = ["codigo", "curso", "seccion", "tipo_seccion", "docente", "total", "limite",
            "tipo", "severidad", "detalle"]
    return _csv(_meta_filtros(c, f, len(datos)), cols, ([d[k] for k in cols] for d in datos),
                f"gestiones_{f.snapshot_id}.csv")


@app.get("/api/powerbi", tags=["power bi"])
def api_powerbi_indice(request: Request):
    base = str(request.base_url).rstrip("/")
    return {"tablas": [{"nombre": t, "url": f"{base}/api/powerbi/{t}.csv"}
                       for t in queries.TABLAS_POWERBI],
            "nota": "Ver docs/powerbi.md para el modelo y las relaciones."}


@app.get("/api/powerbi/{tabla}.csv", tags=["power bi"])
def api_powerbi(tabla: str, c=Depends(con)):
    try:
        cols, filas = queries.tabla_powerbi(c, tabla)
    except KeyError as exc:
        raise HTTPException(404, f"Tabla desconocida. Disponibles: {list(queries.TABLAS_POWERBI)}") from exc
    return _csv([], cols, filas, f"{tabla}.csv")


# ═══════════════════════════════════════════════════════════════════════════
# Carga de reportes (R1-15) y administración
# ═══════════════════════════════════════════════════════════════════════════
@app.post("/api/cargas", tags=["cargas"], dependencies=[Depends(requiere_admin)])
async def api_subir(archivos: list[UploadFile] = File(..., description="Uno o más .xlsx")):
    """Sube uno o varios reportes. Cada archivo se valida y carga por separado; la
    respuesta trae el resultado de cada uno (aceptado, reemplazo, duplicado, vacío
    o rechazado con sus motivos)."""
    if len(archivos) > MAX_ARCHIVOS_POR_SUBIDA:
        raise HTTPException(413, f"Máximo {MAX_ARCHIVOS_POR_SUBIDA} archivos por subida.")
    tmp_dir = config.DATA_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    resultados = []
    for up in archivos:
        nombre = ingesta.nombre_seguro(up.filename)
        with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".upload", delete=False) as tmp:
            ruta = Path(tmp.name)
            leidos, excedido = 0, False
            while bloque := await up.read(1 << 20):
                leidos += len(bloque)
                if leidos > config.MAX_BYTES:
                    excedido = True
                    break
                tmp.write(bloque)
        try:
            if excedido:
                res = ingesta.ResultadoCarga(
                    "rechazado", nombre,
                    f"El archivo excede el máximo de {config.MAX_MB:g} MB.")
                ingesta._cerrar(res, 0.0, "web", True)
            else:
                res = await _en_hilo(ingesta.procesar_archivo, ruta, nombre, "web")
            resultados.append(res.a_dict())
        finally:
            ruta.unlink(missing_ok=True)
            await up.close()
    return {"resultados": resultados,
            "resumen": {r: sum(1 for x in resultados if x["resultado"] == r)
                        for r in ("aceptado", "reemplazo", "duplicado", "vacio", "rechazado")}}


async def _en_hilo(fn, *args):
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(fn, *args)


@app.get("/api/cargas", tags=["cargas"])
def api_cargas(c=Depends(con), limite: int = Query(100, ge=1, le=1000)):
    """Bitácora de todos los intentos de carga."""
    return {"cargas": queries.cargas(c, limite)}


@app.post("/api/cargas/revisar-carpeta", tags=["cargas"], dependencies=[Depends(requiere_admin)])
def api_revisar_carpeta():
    """Procesa ya lo que haya en la carpeta de entrada, sin esperar al vigilante."""
    return {"resultados": [r.a_dict() for r in vigilante.revisar_una_vez(exigir_estable=False)]}


@app.delete("/api/snapshots/{snapshot_id}", tags=["cargas"], dependencies=[Depends(requiere_admin)])
def api_eliminar(snapshot_id: int):
    s = ingesta.eliminar_snapshot(snapshot_id)
    if not s:
        raise HTTPException(404, "Snapshot inexistente.")
    return {"eliminado": snapshot_id, "archivo": s["archivo_nombre"]}


@app.post("/api/reprocesar", tags=["cargas"], dependencies=[Depends(requiere_admin)])
def api_reprocesar():
    """Reconstruye la base desde los originales archivados (tras cambiar reglas del ETL)."""
    res = ingesta.reprocesar()
    return {"reprocesados": len(res), "resultados": [r.a_dict() for r in res]}


@app.get("/api/snapshots/{snapshot_id}/original", tags=["cargas"])
def api_original(snapshot_id: int, c=Depends(con)):
    """Descarga el .xlsx original de un snapshot (trazabilidad)."""
    s = queries.snapshot(c, snapshot_id)
    if not s:
        raise HTTPException(404, "Snapshot inexistente.")
    ruta = (config.ARCHIVO_DIR / s["archivo_ruta"]).resolve()
    if config.ARCHIVO_DIR.resolve() not in ruta.parents or not ruta.exists():
        raise HTTPException(404, "El original no está en el archivo.")
    return FileResponse(ruta, filename=s["archivo_nombre"],
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ═══════════════════════════════════════════════════════════════════════════
# Front
# ═══════════════════════════════════════════════════════════════════════════
@app.exception_handler(404)
async def no_encontrado(request: Request, exc):
    if request.url.path.startswith("/api/"):
        detalle = getattr(exc, "detail", "No encontrado")
        return JSONResponse({"detail": detalle}, status_code=404)
    return FileResponse(FRONTEND / "index.html", status_code=200)


@app.get("/", include_in_schema=False)
def raiz():
    return FileResponse(FRONTEND / "index.html")


@app.get("/cargas", include_in_schema=False)
def pagina_cargas():
    return FileResponse(FRONTEND / "cargas.html")


@app.get("/manual", include_in_schema=False)
def pagina_manual():
    return FileResponse(FRONTEND / "manual.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")

