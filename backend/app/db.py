"""
Réplica local en SQLite.

La base es DERIVADA: la fuente de verdad son los originales guardados en
`ARCHIVO_DIR`. Si el esquema cambia entre versiones, la base se reconstruye
sola al arrancar (ver `ingesta.asegurar_esquema`), sin migraciones manuales.

Conexiones: una por petición/operación (sqlite3 no se comparte entre hilos), en
modo WAL para que el tablero lea mientras se carga un archivo.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from . import config

ESQUEMA_VERSION = "3"   # v3: tipo_documento en snapshots

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (
    clave  TEXT PRIMARY KEY,
    valor  TEXT
);

-- Un snapshot = un archivo aceptado = una fotografía (período, año, corte).
CREATE TABLE IF NOT EXISTS snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256            TEXT    NOT NULL UNIQUE,
    tipo_documento    TEXT    NOT NULL DEFAULT 'ASIGNADOS_CONDENSADO',  -- ver documentos.py
    archivo_nombre    TEXT    NOT NULL,       -- nombre con que se subió
    archivo_ruta      TEXT    NOT NULL,       -- ruta relativa dentro de ARCHIVO_DIR
    encabezado        TEXT,
    periodo_codigo    TEXT,                   -- 01..21 (NULL si no está en el catálogo)
    periodo_nombre    TEXT    NOT NULL,
    periodo_orden     INTEGER NOT NULL,
    semestre          INTEGER,
    anio              INTEGER NOT NULL,
    fecha_corte       TEXT    NOT NULL,       -- ISO local (America/Guatemala)
    cargado_en        TEXT    NOT NULL,
    origen            TEXT    NOT NULL,       -- web | carpeta | consola | reproceso
    total_secciones   INTEGER NOT NULL,
    total_asignados   INTEGER NOT NULL,
    control_json      TEXT,                   -- totales del pie, por hoja
    trae_clasificacion INTEGER NOT NULL DEFAULT 0,
    advertencias_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_periodo ON snapshots(anio, periodo_orden, fecha_corte);
CREATE INDEX IF NOT EXISTS ix_snap_serie ON snapshots(tipo_documento, periodo_nombre, anio);

CREATE TABLE IF NOT EXISTS secciones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    tipo          TEXT    NOT NULL,           -- Clase | Laboratorio
    codigo        TEXT    NOT NULL,
    curso         TEXT    NOT NULL,
    seccion       TEXT,
    escuela       TEXT    NOT NULL,
    area          TEXT,
    subarea       TEXT,
    clasificacion_origen TEXT NOT NULL,       -- archivo | catalogo | heuristica | ninguna
    edificio      TEXT,
    salon         TEXT,
    modalidad     TEXT,
    jornada       TEXT,
    hora_inicio   TEXT,
    hora_fin      TEXT,
    dias          TEXT,
    horas_dia     REAL,
    horas_semana  REAL,
    docente       TEXT,                       -- NULL si el reporte dice STAFF
    sin_docente   INTEGER NOT NULL DEFAULT 0,
    cerrada       INTEGER NOT NULL DEFAULT 0,
    regulares     INTEGER DEFAULT 0,
    otra_fac      INTEGER DEFAULT 0,
    centros_reg   INTEGER DEFAULT 0,
    otra_univ     INTEGER DEFAULT 0,
    no_insc       INTEGER DEFAULT 0,
    est_cierre    INTEGER DEFAULT 0,
    otro_caso     INTEGER DEFAULT 0,
    total         INTEGER NOT NULL DEFAULT 0,
    limite        INTEGER NOT NULL DEFAULT 0,
    limite_min    INTEGER NOT NULL DEFAULT 0,
    ocupacion     REAL,
    estado        TEXT    NOT NULL,
    estado_gestion TEXT   NOT NULL,           -- Al día | En revisión | Pendiente | Cerrada
    con_auxiliar  INTEGER NOT NULL DEFAULT 0,
    fila_origen   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_sec_snapshot ON secciones(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_sec_codigo   ON secciones(snapshot_id, codigo);
CREATE INDEX IF NOT EXISTS ix_sec_escuela  ON secciones(snapshot_id, escuela);
CREATE INDEX IF NOT EXISTS ix_sec_docente  ON secciones(snapshot_id, docente);
CREATE INDEX IF NOT EXISTS ix_sec_estado   ON secciones(snapshot_id, estado);

CREATE TABLE IF NOT EXISTS bloques (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seccion_id   INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE,
    dia          TEXT    NOT NULL,
    hora_inicio  TEXT,
    hora_fin     TEXT
);
CREATE INDEX IF NOT EXISTS ix_bloq_seccion ON bloques(seccion_id);

CREATE TABLE IF NOT EXISTS miembros (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seccion_id  INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE,
    nombre      TEXT    NOT NULL,
    tipo        TEXT
);
CREATE INDEX IF NOT EXISTS ix_miem_seccion ON miembros(seccion_id);

-- Gestiones derivadas por sección (vista «estado de gestiones» del perfil).
CREATE TABLE IF NOT EXISTS gestiones (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seccion_id   INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    clave        TEXT    NOT NULL,
    tipo         TEXT    NOT NULL,
    severidad    TEXT    NOT NULL,           -- pendiente | revision
    detalle      TEXT
);
CREATE INDEX IF NOT EXISTS ix_gest_snapshot ON gestiones(snapshot_id, clave);

-- Clasificación aprendida de cursos: semilla + cada archivo que trae Escuela/Área.
CREATE TABLE IF NOT EXISTS catalogo_cursos (
    codigo        TEXT PRIMARY KEY,
    curso         TEXT,
    escuela       TEXT NOT NULL,
    area          TEXT,
    subarea       TEXT,
    fuente        TEXT NOT NULL,             -- semilla | archivo
    snapshot_id   INTEGER,
    actualizado_en TEXT NOT NULL
);

-- Bitácora de TODO intento de carga, aceptado o no.
CREATE TABLE IF NOT EXISTS cargas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cuando          TEXT    NOT NULL,
    origen          TEXT    NOT NULL,
    archivo_nombre  TEXT    NOT NULL,
    sha256          TEXT,
    bytes           INTEGER,
    resultado       TEXT    NOT NULL,        -- aceptado | reemplazo | duplicado | vacio | rechazado
    snapshot_id     INTEGER,
    descripcion     TEXT,
    mensaje         TEXT    NOT NULL,
    mensajes_json   TEXT,
    duracion_ms     INTEGER
);
CREATE INDEX IF NOT EXISTS ix_cargas_cuando ON cargas(cuando);
"""

TABLAS = ["gestiones", "miembros", "bloques", "secciones", "snapshots",
          "catalogo_cursos", "cargas", "meta"]


def conectar() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")
    return con


@contextmanager
def conexion():
    con = conectar()
    try:
        yield con
    finally:
        con.close()


def version_actual(con: sqlite3.Connection) -> str | None:
    try:
        r = con.execute("SELECT valor FROM meta WHERE clave = 'esquema'").fetchone()
        return r[0] if r else None
    except sqlite3.OperationalError:
        return None


def crear_esquema(con: sqlite3.Connection, borrar: bool = False) -> None:
    if borrar:
        for t in TABLAS:
            con.execute(f"DROP TABLE IF EXISTS {t}")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(ESQUEMA)
    con.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES ('esquema', ?)",
                (ESQUEMA_VERSION,))
    con.commit()
