"""
Réplica local (SQLite) de los snapshots de asignación.

Por qué una base y no leer el xlsx en memoria: el proyecto recibirá VARIOS
archivos del mismo reporte a lo largo del semestre, y la comparación entre
fotografías (historia R2-01) es el mayor salto de valor del producto. Guardar
N snapshots desde el MVP evita rehacer el modelo después.

La base es de solo lectura desde la API: solo el ETL escribe.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
DB_PATH = DATA_DIR / "asignados.db"

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo         TEXT    NOT NULL UNIQUE,
    encabezado      TEXT,               -- línea original del reporte
    periodo         TEXT,               -- "PRIMER SEMESTRE - 2026"
    anio            INTEGER,
    fecha_corte     TEXT,               -- ISO, del encabezado del reporte
    cargado_en      TEXT    NOT NULL,
    total_secciones INTEGER,
    total_asignados INTEGER,
    hash_archivo    TEXT
);

CREATE TABLE IF NOT EXISTS secciones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    tipo          TEXT    NOT NULL,     -- Clase | Laboratorio
    codigo        TEXT    NOT NULL,
    curso         TEXT    NOT NULL,
    seccion       TEXT,
    area          TEXT,
    edificio      TEXT,
    salon         TEXT,
    modalidad     TEXT,
    jornada       TEXT,
    hora_inicio   TEXT,
    hora_fin      TEXT,
    dias          TEXT,                 -- "L,Mi,V"
    horas_dia     REAL,
    horas_semana  REAL,
    docente       TEXT,
    regulares     INTEGER DEFAULT 0,
    otra_fac      INTEGER DEFAULT 0,
    centros_reg   INTEGER DEFAULT 0,
    otra_univ     INTEGER DEFAULT 0,
    no_insc       INTEGER DEFAULT 0,
    est_cierre    INTEGER DEFAULT 0,
    otro_caso     INTEGER DEFAULT 0,
    total         INTEGER DEFAULT 0,
    limite        INTEGER DEFAULT 0,
    limite_min    INTEGER DEFAULT 0,
    ocupacion     REAL,                 -- total / limite, NULL si no hay límite
    estado        TEXT,
    fila_origen   INTEGER               -- trazabilidad hacia el xlsx
);

CREATE TABLE IF NOT EXISTS bloques (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seccion_id   INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE,
    dia          TEXT    NOT NULL,
    hora_inicio  TEXT,
    hora_fin     TEXT
);

CREATE TABLE IF NOT EXISTS miembros (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seccion_id  INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE,
    nombre      TEXT    NOT NULL,
    tipo        TEXT
);

CREATE INDEX IF NOT EXISTS ix_sec_snapshot ON secciones(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_sec_codigo   ON secciones(snapshot_id, codigo);
CREATE INDEX IF NOT EXISTS ix_sec_area     ON secciones(snapshot_id, area);
CREATE INDEX IF NOT EXISTS ix_sec_docente  ON secciones(snapshot_id, docente);
CREATE INDEX IF NOT EXISTS ix_sec_estado   ON secciones(snapshot_id, estado);
CREATE INDEX IF NOT EXISTS ix_bloq_seccion ON bloques(seccion_id);
CREATE INDEX IF NOT EXISTS ix_miem_seccion ON miembros(seccion_id);
CREATE INDEX IF NOT EXISTS ix_miem_nombre  ON miembros(nombre);
"""


def connect(read_only: bool = False) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if read_only and DB_PATH.exists():
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    else:
        con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()
