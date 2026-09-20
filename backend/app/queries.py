"""
Consultas de lectura sobre la réplica local.

Cada función responde a una historia concreta del user story mapping; la
referencia (R1-xx) está en su docstring para que la trazabilidad no se pierda.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import config

# --------------------------------------------------------------------------- #
# Filtros comunes  (historia R1-02)
# --------------------------------------------------------------------------- #
@dataclass
class Filtros:
    snapshot_id: int | None = None
    tipo: str | None = None
    area: str | None = None
    jornada: str | None = None
    modalidad: str | None = None
    edificio: str | None = None
    estado: str | None = None
    docente: str | None = None
    codigo: str | None = None
    q: str | None = None
    _params: list = field(default_factory=list, repr=False)

    def where(self) -> tuple[str, list]:
        cond = ["s.snapshot_id = ?"]
        params: list = [self.snapshot_id]
        simples = [
            ("tipo", self.tipo), ("area", self.area), ("jornada", self.jornada),
            ("modalidad", self.modalidad), ("edificio", self.edificio),
            ("estado", self.estado), ("docente", self.docente), ("codigo", self.codigo),
        ]
        for columna, valor in simples:
            if valor:
                cond.append(f"s.{columna} = ?")
                params.append(valor)
        if self.q:
            like = f"%{self.q.strip().upper()}%"
            cond.append(
                "(UPPER(s.curso) LIKE ? OR s.codigo LIKE ? OR UPPER(COALESCE(s.docente,'')) LIKE ?"
                " OR UPPER(COALESCE(s.salon,'')) LIKE ? OR UPPER(COALESCE(s.edificio,'')) LIKE ?"
                " OR EXISTS (SELECT 1 FROM miembros m WHERE m.seccion_id = s.id"
                "            AND UPPER(m.nombre) LIKE ?))"
            )
            params.extend([like] * 6)
        return " AND ".join(cond), params


def _rows(con, sql, params) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


# --------------------------------------------------------------------------- #
# Snapshots  (historias R1-12 y R2-01)
# --------------------------------------------------------------------------- #
def snapshots(con: sqlite3.Connection) -> list[dict]:
    return _rows(con, "SELECT * FROM snapshots ORDER BY COALESCE(fecha_corte, cargado_en) DESC", [])


def snapshot_vigente(con: sqlite3.Connection) -> dict | None:
    s = snapshots(con)
    return s[0] if s else None


# --------------------------------------------------------------------------- #
# R1-01 / R1-12 · KPI de encabezado
# --------------------------------------------------------------------------- #
def kpis(con, f: Filtros) -> dict:
    w, p = f.where()
    base = con.execute(f"""
        SELECT COUNT(*)                        AS secciones,
               COUNT(DISTINCT s.codigo)        AS cursos,
               COUNT(DISTINCT s.docente)       AS docentes,
               COALESCE(SUM(s.total), 0)       AS asignados,
               COALESCE(SUM(s.limite), 0)      AS cupo,
               COUNT(DISTINCT CASE WHEN s.edificio NOT IN ('HIBR','MEET','EPS','EXT','0000')
                                   THEN s.edificio || '-' || COALESCE(s.salon,'') END) AS salones
        FROM secciones s WHERE {w}""", p).fetchone()
    k = dict(base)
    k["ocupacion"] = (k["asignados"] / k["cupo"]) if k["cupo"] else None
    k["cupo_libre"] = max(k["cupo"] - k["asignados"], 0)
    k["promedio_seccion"] = (k["asignados"] / k["secciones"]) if k["secciones"] else 0

    aux = con.execute(f"""
        SELECT COUNT(DISTINCT m.nombre)   AS auxiliares,
               COUNT(DISTINCT s.id)       AS secciones_con_auxiliar
        FROM secciones s JOIN miembros m ON m.seccion_id = s.id
        WHERE {w}""", p).fetchone()
    k.update(dict(aux))
    k["cobertura_auxiliares"] = (
        k["secciones_con_auxiliar"] / k["secciones"] if k["secciones"] else 0
    )

    # Las columnas de procedencia se reportan solo si traen dato (ver §1 del mapa).
    proc = con.execute(f"""
        SELECT {','.join(f'COALESCE(SUM(s.{c}),0) AS {c}' for c, _ in config.COLUMNAS_PROCEDENCIA)}
        FROM secciones s WHERE {w}""", p).fetchone()
    k["procedencia"] = [
        {"clave": c, "etiqueta": et, "valor": proc[c]}
        for c, et in config.COLUMNAS_PROCEDENCIA
    ]
    k["procedencia_disponible"] = any(
        d["valor"] for d in k["procedencia"] if d["clave"] != "regulares"
    )
    return k


# --------------------------------------------------------------------------- #
# R1-02 · Catálogos para los filtros
# --------------------------------------------------------------------------- #
def catalogos(con, snapshot_id: int) -> dict:
    def distintos(columna: str, orden: str = "1") -> list[str]:
        return [
            r[0] for r in con.execute(
                f"SELECT DISTINCT {columna} FROM secciones "
                f"WHERE snapshot_id = ? AND {columna} IS NOT NULL ORDER BY {orden}",
                (snapshot_id,),
            )
        ]
    return {
        "tipo": distintos("tipo"),
        "area": distintos("area"),
        "jornada": distintos("jornada"),
        "modalidad": distintos("modalidad"),
        "edificio": distintos("edificio"),
        "estado": [
            e for e in config.ESTADOS
            if e in set(distintos("estado"))
        ],
        "area_foco": config.AREA_FOCO,
        "umbrales": {
            "riesgo_cierre": config.UMBRAL_RIESGO_CIERRE,
            "saludable_bajo": config.UMBRAL_SALUDABLE_BAJO,
            "llena": config.UMBRAL_LLENA,
        },
    }


# --------------------------------------------------------------------------- #
# R1-03 · Cursos por demanda
# --------------------------------------------------------------------------- #
def cursos(con, f: Filtros, limite: int = 20, orden: str = "asignados") -> list[dict]:
    w, p = f.where()
    ordenes = {
        "asignados": "asignados DESC",
        "secciones": "secciones DESC",
        "promedio": "promedio DESC",
        "ocupacion": "ocupacion DESC",
        "codigo": "s.codigo ASC",
    }
    return _rows(con, f"""
        SELECT s.codigo, s.curso, s.area,
               COUNT(*)                          AS secciones,
               COALESCE(SUM(s.total), 0)         AS asignados,
               COALESCE(SUM(s.limite), 0)        AS cupo,
               ROUND(AVG(s.total), 1)            AS promedio,
               CASE WHEN SUM(s.limite) > 0
                    THEN 1.0 * SUM(s.total) / SUM(s.limite) END AS ocupacion,
               SUM(CASE WHEN s.estado = 'Sobrecupo' THEN 1 ELSE 0 END)        AS sobrecupo,
               SUM(CASE WHEN s.estado IN ('Riesgo de cierre','Sin asignados')
                        THEN 1 ELSE 0 END)                                    AS en_riesgo
        FROM secciones s WHERE {w}
        GROUP BY s.codigo, s.curso, s.area
        ORDER BY {ordenes.get(orden, ordenes['asignados'])}
        LIMIT ?""", [*p, limite])


# --------------------------------------------------------------------------- #
# R1-04 / R1-05 · Ocupación y secciones en riesgo
# --------------------------------------------------------------------------- #
def ocupacion(con, f: Filtros) -> dict:
    w, p = f.where()
    por_estado = _rows(con, f"""
        SELECT s.estado, COUNT(*) AS secciones, COALESCE(SUM(s.total),0) AS asignados,
               COALESCE(SUM(s.limite),0) AS cupo
        FROM secciones s WHERE {w} GROUP BY s.estado""", p)
    indice = {r["estado"]: r for r in por_estado}
    return {
        "por_estado": [
            indice.get(e, {"estado": e, "secciones": 0, "asignados": 0, "cupo": 0})
            for e in config.ESTADOS
        ],
        "histograma": _rows(con, f"""
            SELECT CASE
                     WHEN s.limite = 0 OR s.limite IS NULL THEN 'n/d'
                     WHEN s.total = 0 THEN '0%'
                     WHEN 1.0*s.total/s.limite <= 0.20 THEN '1-20%'
                     WHEN 1.0*s.total/s.limite <= 0.40 THEN '21-40%'
                     WHEN 1.0*s.total/s.limite <= 0.60 THEN '41-60%'
                     WHEN 1.0*s.total/s.limite <= 0.80 THEN '61-80%'
                     WHEN 1.0*s.total/s.limite <= 1.00 THEN '81-100%'
                     ELSE '>100%' END AS rango,
                   COUNT(*) AS secciones
            FROM secciones s WHERE {w} GROUP BY rango""", p),
    }


# --------------------------------------------------------------------------- #
# R1-06 · Carga docente
# --------------------------------------------------------------------------- #
def docentes(con, f: Filtros, limite: int = 25, orden: str = "asignados") -> list[dict]:
    w, p = f.where()
    ordenes = {
        "asignados": "asignados DESC",
        "secciones": "secciones DESC",
        "horas": "horas_semana DESC",
        "nombre": "s.docente ASC",
    }
    return _rows(con, f"""
        SELECT s.docente,
               COUNT(*)                                     AS secciones,
               COUNT(DISTINCT s.codigo)                      AS cursos,
               COALESCE(SUM(s.total), 0)                     AS asignados,
               COALESCE(SUM(s.horas_semana), 0)              AS horas_semana,
               GROUP_CONCAT(DISTINCT s.area)                 AS areas,
               (SELECT COUNT(DISTINCT m.nombre) FROM miembros m
                 JOIN secciones s2 ON s2.id = m.seccion_id
                WHERE s2.snapshot_id = s.snapshot_id AND s2.docente = s.docente) AS auxiliares
        FROM secciones s WHERE {w} AND s.docente IS NOT NULL
        GROUP BY s.docente
        ORDER BY {ordenes.get(orden, ordenes['asignados'])}
        LIMIT ?""", [*p, limite])


# --------------------------------------------------------------------------- #
# R1-07 · Auxiliares de cátedra
# --------------------------------------------------------------------------- #
def auxiliares(con, f: Filtros, limite: int = 25) -> dict:
    w, p = f.where()
    ranking = _rows(con, f"""
        SELECT m.nombre, m.tipo,
               COUNT(DISTINCT s.id)      AS secciones,
               COUNT(DISTINCT s.codigo)  AS cursos,
               COALESCE(SUM(s.total), 0) AS asignados
        FROM secciones s JOIN miembros m ON m.seccion_id = s.id
        WHERE {w}
        GROUP BY m.nombre, m.tipo
        ORDER BY asignados DESC
        LIMIT ?""", [*p, limite])
    # El argumento para pedir plazas: secciones grandes que hoy no tienen auxiliar.
    sin_auxiliar = _rows(con, f"""
        SELECT s.codigo, s.curso, s.seccion, s.tipo, s.docente, s.total, s.limite, s.estado
        FROM secciones s
        WHERE {w} AND NOT EXISTS (SELECT 1 FROM miembros m WHERE m.seccion_id = s.id)
        ORDER BY s.total DESC
        LIMIT ?""", [*p, limite])
    resumen = con.execute(f"""
        SELECT COUNT(*) AS secciones,
               SUM(CASE WHEN EXISTS (SELECT 1 FROM miembros m WHERE m.seccion_id = s.id)
                        THEN 1 ELSE 0 END) AS con_auxiliar,
               COALESCE(SUM(CASE WHEN NOT EXISTS
                        (SELECT 1 FROM miembros m WHERE m.seccion_id = s.id)
                        THEN s.total ELSE 0 END), 0) AS asignados_sin_auxiliar
        FROM secciones s WHERE {w}""", p).fetchone()
    return {"ranking": ranking, "sin_auxiliar": sin_auxiliar, "resumen": dict(resumen)}


# --------------------------------------------------------------------------- #
# R1-08 · Uso de salones por día y hora
# --------------------------------------------------------------------------- #
def heatmap(con, f: Filtros) -> dict:
    w, p = f.where()
    filas = _rows(con, f"""
        SELECT b.dia,
               substr(b.hora_inicio, 1, 2) AS hora,
               COUNT(DISTINCT s.id)        AS secciones,
               COALESCE(SUM(s.total), 0)   AS asignados
        FROM secciones s JOIN bloques b ON b.seccion_id = s.id
        WHERE {w} AND b.hora_inicio IS NOT NULL
        GROUP BY b.dia, hora""", p)
    horas = sorted({r["hora"] for r in filas})
    celdas = {(r["dia"], r["hora"]): r for r in filas}
    return {
        "dias": [d for d in config.DIAS if any(r["dia"] == d for r in filas)],
        "dias_nombre": config.DIAS_NOMBRE,
        "horas": horas,
        "celdas": [
            {
                "dia": d, "hora": h,
                "secciones": celdas.get((d, h), {}).get("secciones", 0),
                "asignados": celdas.get((d, h), {}).get("asignados", 0),
            }
            for d in config.DIAS if any(r["dia"] == d for r in filas)
            for h in horas
        ],
    }


def salones(con, f: Filtros, limite: int = 25) -> list[dict]:
    w, p = f.where()
    return _rows(con, f"""
        SELECT s.edificio, s.salon,
               COUNT(*) AS secciones,
               COALESCE(SUM(s.total), 0)        AS asignados,
               COALESCE(SUM(s.horas_semana), 0) AS horas_semana,
               MAX(s.total)                     AS seccion_mas_grande
        FROM secciones s
        WHERE {w} AND s.edificio NOT IN ('HIBR','MEET','EPS','EXT','0000')
        GROUP BY s.edificio, s.salon
        ORDER BY horas_semana DESC
        LIMIT ?""", [*p, limite])


# --------------------------------------------------------------------------- #
# R1-09 · Modalidad y jornada
# --------------------------------------------------------------------------- #
def distribucion(con, f: Filtros, columna: str) -> list[dict]:
    if columna not in {"modalidad", "jornada", "area", "tipo", "edificio"}:
        raise ValueError(f"columna no permitida: {columna}")
    w, p = f.where()
    return _rows(con, f"""
        SELECT s.{columna} AS etiqueta, COUNT(*) AS secciones,
               COALESCE(SUM(s.total), 0) AS asignados,
               COALESCE(SUM(s.limite), 0) AS cupo
        FROM secciones s WHERE {w}
        GROUP BY s.{columna} ORDER BY asignados DESC""", p)


# --------------------------------------------------------------------------- #
# R1-10 · Tabla explorable / búsqueda
# --------------------------------------------------------------------------- #
ORDENES_SECCIONES = {
    "asignados": "s.total DESC",
    "ocupacion": "s.ocupacion DESC NULLS LAST",
    "ocupacion_asc": "s.ocupacion ASC NULLS LAST",
    "curso": "s.curso ASC, s.seccion ASC",
    "codigo": "s.codigo ASC, s.seccion ASC",
    "docente": "s.docente ASC",
}


def secciones(con, f: Filtros, limite: int = 100, offset: int = 0,
              orden: str = "asignados") -> dict:
    w, p = f.where()
    total = con.execute(f"SELECT COUNT(*) FROM secciones s WHERE {w}", p).fetchone()[0]
    filas = _rows(con, f"""
        SELECT s.id, s.tipo, s.codigo, s.curso, s.seccion, s.area, s.edificio, s.salon,
               s.modalidad, s.jornada, s.hora_inicio, s.hora_fin, s.dias, s.horas_semana,
               s.docente, s.total, s.limite, s.ocupacion, s.estado, s.fila_origen,
               (SELECT GROUP_CONCAT(m.nombre, ' · ') FROM miembros m
                 WHERE m.seccion_id = s.id) AS auxiliares
        FROM secciones s WHERE {w}
        ORDER BY {ORDENES_SECCIONES.get(orden, ORDENES_SECCIONES['asignados'])}
        LIMIT ? OFFSET ?""", [*p, limite, offset])
    return {"total": total, "limite": limite, "offset": offset, "filas": filas}
