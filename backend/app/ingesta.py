"""
Pipeline único de ingesta.

Todas las vías de entrada terminan aquí —subida desde el navegador, archivo
copiado a la carpeta `entrada/`, línea de comandos, reprocesamiento— para que
las reglas sean las mismas sin importar cómo llegó el archivo:

    huella SHA-256 ──► ¿ya cargado? ── sí ──► «duplicado» (no se toca nada)
          │ no
          ▼
    lector.leer_reporte ──► ¿errores? ── sí ──► «rechazado» (con motivos)
          │ no
          ▼
    ¿sin secciones? ── sí ──► «vacío» (no se crea snapshot)
          │ no
          ▼
    ¿mismo período, año y fecha de corte que otro? ── sí ──► «reemplazo»
          │ no                                                   (el nuevo sustituye al anterior)
          ▼
    «aceptado»: se archiva el original, se inserta el snapshot en una sola
    transacción, se actualiza el catálogo de cursos y se reclasifican snapshots
    anteriores con lo aprendido.

Cada intento queda en la tabla `cargas`, aceptado o no.

Un mismo período con fecha de corte distinta NO reemplaza: es otra fotografía del
mismo período y alimenta las vistas de evolución y tiempos de atención.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import catalogos, config, db, documentos, gestiones, lector
from .catalogos import normalizar

log = logging.getLogger("asignados.ingesta")
_candado = threading.RLock()   # una carga a la vez: SQLite escribe en serie


@dataclass
class ResultadoCarga:
    resultado: str               # aceptado | reemplazo | duplicado | vacio | rechazado
    archivo: str
    mensaje: str
    sha256: str | None = None
    bytes: int | None = None
    snapshot_id: int | None = None
    reemplaza_a: int | None = None
    descripcion: str | None = None
    secciones: int = 0
    asignados: int = 0
    mensajes: list[dict] = field(default_factory=list)
    duracion_ms: int = 0

    @property
    def cargado(self) -> bool:
        return self.resultado in ("aceptado", "reemplazo")

    def a_dict(self) -> dict:
        d = dict(self.__dict__)
        d["cargado"] = self.cargado
        return d


def ahora_local() -> str:
    return datetime.now(ZoneInfo(config.ZONA_HORARIA)).replace(tzinfo=None).isoformat(
        timespec="seconds")


def huella(ruta: Path) -> str:
    h = hashlib.sha256()
    with Path(ruta).open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def nombre_seguro(nombre: str | None) -> str:
    """Solo el nombre base, sin rutas ni caracteres de control (no se usa para escribir)."""
    base = Path(str(nombre or "archivo")).name.replace("\\", "/").split("/")[-1]
    base = "".join(c for c in base if c.isprintable()).strip() or "archivo"
    return base[:180]


# ═══════════════════════════════════════════════════════════════════════════
# Arranque
# ═══════════════════════════════════════════════════════════════════════════
def asegurar_esquema() -> None:
    """Crea la base si no existe; si el esquema es de otra versión, la reconstruye
    desde los originales archivados (la base es derivada)."""
    for d in (config.DATA_DIR, config.ARCHIVO_DIR, config.ENTRADA_DIR,
              config.PROCESADOS_DIR, config.RECHAZADOS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    leeme = config.ENTRADA_DIR / "LEEME.txt"
    if not leeme.exists():
        try:
            leeme.write_text(
                "Copie aquí los reportes de asignados (.xlsx) descargados de Centro de Cálculo.\r\n"
                "El sistema los revisa cada pocos segundos y los carga solo.\r\n"
                "  procesados/  -> archivos cargados (o que ya estaban cargados)\r\n"
                "  rechazados/  -> archivos que no se pudieron cargar, con un .txt que explica por qué\r\n",
                encoding="utf-8")
        except OSError:
            pass

    with db.conexion() as con:
        version = db.version_actual(con)
        if version == db.ESQUEMA_VERSION:
            sembrar_catalogo(con)
            return
        if version is None:
            log.info("Base de datos nueva: se crea el esquema v%s.", db.ESQUEMA_VERSION)
        else:
            log.warning("Esquema v%s -> v%s: se reconstruye la base desde el archivo de originales.",
                        version, db.ESQUEMA_VERSION)
        db.crear_esquema(con, borrar=True)
        sembrar_catalogo(con)
    reprocesar(registrar=False)


def sembrar_catalogo(con) -> None:
    filas = catalogos.cargar_semilla()
    con.executemany(
        """INSERT OR IGNORE INTO catalogo_cursos
           (codigo, curso, escuela, area, subarea, fuente, actualizado_en)
           VALUES (?,?,?,?,?, 'semilla', ?)""",
        [(f["codigo"], f["curso"], normalizar(f["escuela"]), normalizar(f["area"]) or None,
          normalizar(f["subarea"]) or None, ahora_local()) for f in filas],
    )
    con.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Archivo de originales (fuente de verdad)
# ═══════════════════════════════════════════════════════════════════════════
def _ruta_archivo(sha: str) -> Path:
    return config.ARCHIVO_DIR / sha[:2] / f"{sha}.xlsx"


def _ficha(sha: str) -> Path:
    return config.ARCHIVO_DIR / sha[:2] / f"{sha}.json"


def _leer_ficha(sha: str) -> dict:
    try:
        return json.loads(_ficha(sha).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _escribir_ficha(sha: str, datos: dict) -> None:
    _ficha(sha).write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def archivados() -> list[dict]:
    """Fichas de todos los originales archivados, en orden de carga."""
    fichas = []
    for f in config.ARCHIVO_DIR.glob("*/*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _ruta_archivo(d.get("sha256", "")).exists():
            fichas.append(d)
    return sorted(fichas, key=lambda d: d.get("cargado_en", ""))


# ═══════════════════════════════════════════════════════════════════════════
# Carga
# ═══════════════════════════════════════════════════════════════════════════
def procesar_archivo(ruta: Path, nombre_original: str | None = None,
                     origen: str = "consola", registrar: bool = True) -> ResultadoCarga:
    """Punto de entrada único. Nunca lanza: todo resultado vuelve como ResultadoCarga."""
    t0 = time.perf_counter()
    ruta = Path(ruta)
    nombre = nombre_seguro(nombre_original or ruta.name)
    try:
        tam = ruta.stat().st_size
        sha = huella(ruta)
    except PermissionError:
        res = ResultadoCarga(
            "rechazado", nombre,
            "El sistema no tiene permiso para leer el archivo. En el equipo servidor, dé permiso "
            "de lectura al archivo (en Linux: chmod a+r) y vuelva a copiarlo.")
        return _cerrar(res, t0, origen, registrar)
    except OSError as exc:
        res = ResultadoCarga("rechazado", nombre, f"No se pudo leer el archivo: {exc}")
        return _cerrar(res, t0, origen, registrar)

    with _candado:
        try:
            res = _procesar(ruta, nombre, origen, sha, tam)
        except Exception as exc:  # noqa: BLE001 — la carga jamás debe tumbar el servidor
            log.exception("Error interno al procesar %s", nombre)
            res = ResultadoCarga(
                "rechazado", nombre,
                f"Error interno al procesar el archivo ({type(exc).__name__}). "
                "No se modificó ningún dato. Revise los registros del servidor.",
                sha256=sha, bytes=tam)
        return _cerrar(res, t0, origen, registrar)


def _cerrar(res: ResultadoCarga, t0: float, origen: str, registrar: bool) -> ResultadoCarga:
    res.duracion_ms = int((time.perf_counter() - t0) * 1000)
    if registrar:
        try:
            with db.conexion() as con:
                con.execute(
                    """INSERT INTO cargas (cuando, origen, archivo_nombre, sha256, bytes, resultado,
                       snapshot_id, descripcion, mensaje, mensajes_json, duracion_ms)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (ahora_local(), origen, res.archivo, res.sha256, res.bytes, res.resultado,
                     res.snapshot_id, res.descripcion, res.mensaje,
                     json.dumps(res.mensajes, ensure_ascii=False), res.duracion_ms))
                con.commit()
        except Exception:  # noqa: BLE001
            log.exception("No se pudo registrar la carga en la bitácora")
    log.info("[%s] %s -> %s: %s", origen, res.archivo, res.resultado, res.mensaje)
    return res


def _procesar(ruta: Path, nombre: str, origen: str, sha: str, tam: int) -> ResultadoCarga:
    base = {"archivo": nombre, "sha256": sha, "bytes": tam}

    with db.conexion() as con:
        previo = con.execute(
            "SELECT id, periodo_nombre, anio, fecha_corte, archivo_nombre FROM snapshots "
            "WHERE sha256 = ?", (sha,)).fetchone()
    if previo:
        return ResultadoCarga(
            "duplicado",
            mensaje=(f"Este archivo ya estaba cargado (snapshot #{previo['id']}, "
                     f"{previo['periodo_nombre']} {previo['anio']}, corte "
                     f"{previo['fecha_corte'].replace('T', ' ')[:16]}). No se modificó nada."),
            snapshot_id=previo["id"], **base)

    rep = leer_documento(ruta, nombre)
    mensajes = [m.a_dict() for m in rep.mensajes]
    if not rep.es_valido:
        primero = rep.errores[0].texto
        extra = f" (y {len(rep.errores) - 1} errores más)" if len(rep.errores) > 1 else ""
        return ResultadoCarga("rechazado", mensaje=primero + extra, mensajes=mensajes,
                              descripcion=rep.descripcion if rep.anio else None, **base)
    if rep.vacio:
        return ResultadoCarga(
            "vacio",
            mensaje=(f"El reporte de {rep.descripcion} no contiene secciones (TOTAL: 0). "
                     "Es un archivo válido, pero no hay nada que mostrar; no se creó un snapshot."),
            mensajes=mensajes, descripcion=rep.descripcion, **base)

    snap_id, reemplazado = _guardar(rep, ruta, nombre, origen, sha)
    advert = len(rep.advertencias)
    sufijo = f" Con {advert} advertencia{'s' if advert != 1 else ''}." if advert else ""
    if reemplazado:
        return ResultadoCarga(
            "reemplazo",
            mensaje=(f"Cargado {rep.descripcion}: {len(rep.secciones):,} secciones, "
                     f"{rep.total_asignados:,} asignados. Sustituye al snapshot #{reemplazado}, "
                     f"que tenía el mismo período y la misma fecha de corte.{sufijo}"),
            snapshot_id=snap_id, reemplaza_a=reemplazado, descripcion=rep.descripcion,
            secciones=len(rep.secciones), asignados=rep.total_asignados,
            mensajes=mensajes, **base)
    return ResultadoCarga(
        "aceptado",
        mensaje=(f"Cargado {rep.descripcion}: {len(rep.secciones):,} secciones, "
                 f"{rep.total_asignados:,} asignados. Totales verificados contra el pie "
                 f"del reporte.{sufijo}"),
        snapshot_id=snap_id, descripcion=rep.descripcion, secciones=len(rep.secciones),
        asignados=rep.total_asignados, mensajes=mensajes, **base)


def leer_documento(ruta: Path, nombre: str | None) -> lector.Reporte:
    """Identifica el TIPO de documento y lo lee con su lector.

    Un .xlsx válido que no corresponde a ningún tipo registrado se rechaza aquí,
    con la lista de tipos soportados, en lugar de pasarlo por un lector ajeno."""
    previos = lector.inspeccionar_archivo(ruta, nombre)
    if any(m.nivel == "error" for m in previos):
        rep = lector.Reporte(ruta=ruta)
        rep.mensajes.extend(previos)
        return rep
    tipo = documentos.identificar(ruta)
    if tipo is None:
        rep = lector.Reporte(ruta=ruta)
        rep.error("tipo_no_soportado",
                  "El archivo es un Excel válido, pero no es de un tipo de documento soportado. "
                  f"Tipos soportados: {documentos.nombres_soportados()}.")
        return rep
    rep = tipo.leer(ruta, nombre)
    rep.tipo_documento = tipo.clave
    return rep


def _clasificador(con):
    catalogo = {r["codigo"]: r for r in con.execute("SELECT * FROM catalogo_cursos")}

    def clasificar(s: dict) -> tuple[str, str | None, str | None, str]:
        if s.get("escuela"):
            return s["escuela"], s.get("area"), s.get("subarea"), "archivo"
        c = catalogo.get(s["codigo"]) or catalogo.get(catalogos.codigo_base(s["codigo"]) or "")
        if c:
            return c["escuela"], c["area"], c["subarea"], "catalogo"
        h = catalogos.clasificacion_heuristica(s["codigo"], s["curso"])
        if h:
            return h[0], h[1], None, "heuristica"
        return config.SIN_CLASIFICAR, None, None, "ninguna"
    return clasificar


def _guardar(rep: lector.Reporte, ruta: Path, nombre: str, origen: str, sha: str,
             cargado_en: str | None = None) -> tuple[int, int | None]:
    """Archiva el original e inserta el snapshot en UNA transacción."""
    destino = _ruta_archivo(sha)
    destino.parent.mkdir(parents=True, exist_ok=True)
    copiado_ahora = False
    if not destino.exists():
        shutil.copy2(ruta, destino)
        copiado_ahora = True
    cargado_en = cargado_en or ahora_local()

    periodo = rep.periodo
    fecha = rep.fecha_corte.isoformat(timespec="seconds")
    con = db.conectar()
    try:
        con.execute("BEGIN IMMEDIATE")
        reemplazado = con.execute(
            "SELECT id, sha256 FROM snapshots WHERE tipo_documento = ? AND anio = ? "
            "AND periodo_nombre = ? AND fecha_corte = ?",
            (rep.tipo_documento, rep.anio,
             periodo.nombre if periodo else normalizar(rep.periodo_nombre), fecha),
        ).fetchone()
        if reemplazado:
            con.execute("DELETE FROM snapshots WHERE id = ?", (reemplazado["id"],))

        cur = con.execute(
            """INSERT INTO snapshots
               (sha256, tipo_documento, archivo_nombre, archivo_ruta, encabezado, periodo_codigo,
                periodo_nombre, periodo_orden, semestre, anio, fecha_corte, cargado_en, origen,
                total_secciones, total_asignados, control_json, trae_clasificacion,
                advertencias_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sha, rep.tipo_documento, nombre, str(destino.relative_to(config.ARCHIVO_DIR)),
             rep.encabezado,
             periodo.codigo if periodo else None,
             periodo.nombre if periodo else normalizar(rep.periodo_nombre),
             periodo.orden if periodo else 80, periodo.semestre if periodo else None,
             rep.anio, fecha, cargado_en, origen, len(rep.secciones), rep.total_asignados,
             json.dumps(rep.control), int(rep.trae_clasificacion),
             json.dumps([m.a_dict() for m in rep.advertencias], ensure_ascii=False)))
        snap_id = cur.lastrowid

        if rep.trae_clasificacion:
            con.executemany(
                """INSERT INTO catalogo_cursos (codigo, curso, escuela, area, subarea, fuente,
                   snapshot_id, actualizado_en) VALUES (?,?,?,?,?, 'archivo', ?, ?)
                   ON CONFLICT(codigo) DO UPDATE SET curso=excluded.curso,
                     escuela=excluded.escuela, area=excluded.area, subarea=excluded.subarea,
                     fuente='archivo', snapshot_id=excluded.snapshot_id,
                     actualizado_en=excluded.actualizado_en""",
                [(s["codigo"], s["curso"], s["escuela"], s["area"], s["subarea"], snap_id,
                  cargado_en) for s in rep.secciones if s["escuela"]])

        clasificar = _clasificador(con)
        for s in rep.secciones:
            escuela, area, subarea, origen_clasif = clasificar(s)
            g = gestiones.derivar(s)
            dias = sorted({b["dia"] for b in s["bloques"]}, key=config.DIAS.index)
            con_aux = any("AUXILIAR" in (m["tipo"] or "") for m in s["miembros"])
            ocup = (s["total"] / s["limite"]) if s["limite"] and not s["cerrada"] else None
            cur = con.execute(
                """INSERT INTO secciones
                   (snapshot_id, tipo, codigo, curso, seccion, escuela, area, subarea,
                    clasificacion_origen, edificio, salon, modalidad, jornada, hora_inicio,
                    hora_fin, dias, horas_dia, horas_semana, docente, sin_docente, cerrada,
                    regulares, otra_fac, centros_reg, otra_univ, no_insc, est_cierre, otro_caso,
                    total, limite, limite_min, ocupacion, estado, estado_gestion, con_auxiliar,
                    fila_origen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (snap_id, s["tipo"], s["codigo"], s["curso"], s["seccion"], escuela, area,
                 subarea, origen_clasif, s["edificio"], s["salon"], s["modalidad"], s["jornada"],
                 s["hora_inicio"], s["hora_fin"], ",".join(dias), s["horas_dia"],
                 s["horas_semana"], s["docente"], int(s["sin_docente"]), int(s["cerrada"]),
                 s["regulares"], s["otra_fac"], s["centros_reg"], s["otra_univ"], s["no_insc"],
                 s["est_cierre"], s["otro_caso"], s["total"], s["limite"], s["limite_min"], ocup,
                 s["estado"], gestiones.estado_seccion(g, s["cerrada"]), int(con_aux),
                 s["fila_origen"]))
            sec_id = cur.lastrowid
            if s["bloques"]:
                con.executemany(
                    "INSERT INTO bloques (seccion_id, dia, hora_inicio, hora_fin) VALUES (?,?,?,?)",
                    [(sec_id, b["dia"], b["hora_inicio"], b["hora_fin"]) for b in s["bloques"]])
            if s["miembros"]:
                con.executemany(
                    "INSERT INTO miembros (seccion_id, nombre, tipo) VALUES (?,?,?)",
                    [(sec_id, m["nombre"], m["tipo"]) for m in s["miembros"]])
            if g:
                con.executemany(
                    """INSERT INTO gestiones (seccion_id, snapshot_id, clave, tipo, severidad,
                       detalle) VALUES (?,?,?,?,?,?)""",
                    [(sec_id, snap_id, x["clave"], x["tipo"], x["severidad"], x["detalle"])
                     for x in g])

        if rep.trae_clasificacion:
            _reclasificar(con)
        con.commit()
    except Exception:
        con.rollback()
        if copiado_ahora:
            destino.unlink(missing_ok=True)
        raise
    finally:
        con.close()

    ficha = _leer_ficha(sha)
    ficha.update({"sha256": sha, "nombre": nombre, "origen": ficha.get("origen", origen),
                  "cargado_en": ficha.get("cargado_en", cargado_en), "estado": "activo",
                  "descripcion": rep.descripcion})
    _escribir_ficha(sha, ficha)
    if reemplazado:
        anterior = _leer_ficha(reemplazado["sha256"])
        if anterior:
            anterior.update({"estado": "reemplazado", "reemplazado_por": sha})
            _escribir_ficha(reemplazado["sha256"], anterior)
    return snap_id, (reemplazado["id"] if reemplazado else None)


def _reclasificar(con) -> int:
    """Aplica lo aprendido del catálogo a secciones que no traían clasificación propia."""
    cur = con.execute(
        """UPDATE secciones SET escuela = c.escuela, area = c.area, subarea = c.subarea,
                  clasificacion_origen = 'catalogo'
           FROM catalogo_cursos c
           WHERE secciones.codigo = c.codigo
             AND secciones.clasificacion_origen IN ('catalogo', 'heuristica', 'ninguna')
             AND (secciones.escuela IS NOT c.escuela OR secciones.area IS NOT c.area
                  OR secciones.clasificacion_origen != 'catalogo')""")
    return cur.rowcount


# ═══════════════════════════════════════════════════════════════════════════
# Administración
# ═══════════════════════════════════════════════════════════════════════════
def eliminar_snapshot(snapshot_id: int, origen: str = "web") -> dict | None:
    """Quita un snapshot del tablero. El original queda archivado y marcado como
    eliminado, para que un reprocesamiento no lo resucite."""
    with _candado, db.conexion() as con:
        s = con.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if not s:
            return None
        con.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        descripcion = f"{s['periodo_nombre']} {s['anio']} · corte {s['fecha_corte'][:16].replace('T', ' ')}"
        con.execute(
            """INSERT INTO cargas (cuando, origen, archivo_nombre, sha256, bytes, resultado,
               snapshot_id, descripcion, mensaje, mensajes_json, duracion_ms)
               VALUES (?,?,?,?,NULL,'eliminado',?,?,?, '[]', 0)""",
            (ahora_local(), origen, s["archivo_nombre"], s["sha256"], snapshot_id, descripcion,
             f"Snapshot #{snapshot_id} eliminado del tablero. El original sigue archivado."))
        con.commit()
    ficha = _leer_ficha(s["sha256"])
    if ficha:
        ficha["estado"] = "eliminado"
        _escribir_ficha(s["sha256"], ficha)
    return dict(s)


def reprocesar(registrar: bool = True) -> list[ResultadoCarga]:
    """Reconstruye la base completa desde los originales archivados, en el orden en
    que se cargaron. Útil cuando cambian las reglas del ETL. Conserva la bitácora."""
    resultados = []
    with _candado:
        with db.conexion() as con:
            for t in ("gestiones", "miembros", "bloques", "secciones", "snapshots"):
                con.execute(f"DELETE FROM {t}")
            con.execute("DELETE FROM catalogo_cursos")
            con.commit()
            sembrar_catalogo(con)
        for ficha in archivados():
            if ficha.get("estado") == "eliminado":
                continue
            sha = ficha["sha256"]
            ruta = _ruta_archivo(sha)
            t0 = time.perf_counter()
            rep = leer_documento(ruta, ficha.get("nombre"))
            if not rep.es_valido or rep.vacio:
                res = ResultadoCarga("rechazado", ficha.get("nombre", sha),
                                     "Ya no pasa las validaciones vigentes: "
                                     + (rep.errores[0].texto if rep.errores else "sin secciones"),
                                     sha256=sha)
            else:
                snap_id, reemp = _guardar(rep, ruta, ficha.get("nombre", sha),
                                          ficha.get("origen", "reproceso"), sha,
                                          cargado_en=ficha.get("cargado_en"))
                res = ResultadoCarga("reemplazo" if reemp else "aceptado",
                                     ficha.get("nombre", sha), f"Reprocesado: {rep.descripcion}",
                                     sha256=sha, snapshot_id=snap_id, descripcion=rep.descripcion,
                                     secciones=len(rep.secciones), asignados=rep.total_asignados)
            res.duracion_ms = int((time.perf_counter() - t0) * 1000)
            resultados.append(res)
        if registrar:
            ok = sum(r.cargado for r in resultados)
            with db.conexion() as con:
                con.execute(
                    """INSERT INTO cargas (cuando, origen, archivo_nombre, resultado, mensaje,
                       mensajes_json, duracion_ms) VALUES (?, 'reproceso', '(todos)',
                       'reproceso', ?, '[]', ?)""",
                    (ahora_local(), f"Base reconstruida desde el archivo: {ok} snapshots.",
                     sum(r.duracion_ms for r in resultados)))
                con.commit()
    return resultados


# ═══════════════════════════════════════════════════════════════════════════
# Respaldo y restauración
# ═══════════════════════════════════════════════════════════════════════════
_NOMBRE_EN_RESPALDO = __import__("re").compile(r"^archivo/[0-9a-f]{2}/[0-9a-f]{64}\.(xlsx|json)$")


def respaldo() -> Path:
    """Zip con los originales archivados (suficientes para reconstruir todo) y una
    copia consistente de la base. Queda en entrada/respaldos/, visible desde el equipo."""
    import sqlite3
    import zipfile

    respaldos = config.ENTRADA_DIR / "respaldos"
    respaldos.mkdir(parents=True, exist_ok=True)
    destino = respaldos / f"respaldo_{datetime.now():%Y%m%d-%H%M%S}.zip"
    copia_db = config.DATA_DIR / "tmp" / "respaldo.db"
    copia_db.parent.mkdir(parents=True, exist_ok=True)
    with _candado:
        origen = db.conectar()
        dst = sqlite3.connect(copia_db)
        try:
            origen.backup(dst)
        finally:
            dst.close()
            origen.close()
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(config.ARCHIVO_DIR.glob("*/*")):
                if f.suffix in (".xlsx", ".json"):
                    z.write(f, f"archivo/{f.parent.name}/{f.name}")
            z.write(copia_db, "asignados.db")
            z.writestr("LEEME.txt",
                       "Respaldo del Dashboard de Asignados.\n"
                       "Restaurar: docker compose exec app python -m backend.app.etl restaurar "
                       f"/entrada/respaldos/{destino.name}\n")
    copia_db.unlink(missing_ok=True)
    return destino


def restaurar(ruta_zip: Path) -> list[ResultadoCarga]:
    """Recupera los originales de un respaldo y reconstruye la base con ellos."""
    import zipfile

    with zipfile.ZipFile(ruta_zip) as z:
        for nombre in z.namelist():
            if not _NOMBRE_EN_RESPALDO.match(nombre):   # evita rutas maliciosas (zip slip)
                continue
            destino = config.ARCHIVO_DIR / nombre.split("/", 1)[1]
            destino.parent.mkdir(parents=True, exist_ok=True)
            with z.open(nombre) as src, destino.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return reprocesar()
