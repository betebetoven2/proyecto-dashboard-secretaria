"""
Consultas de lectura. Cada función indica la historia del user story mapping
(docs/user-story-map.md) que atiende.

Convención: las secciones CERRADAS (salón «CERRADO») se cuentan aparte y no
entran en cupo ni ocupación, porque su cupo no es capacidad real.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import config, gestiones, predicciones as pred

ABIERTA = "s.cerrada = 0"


# ═══════════════════════════════════════════════════════════════════════════
# Filtros comunes (R1-02)
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class Filtros:
    snapshot_id: int | None = None
    tipo: str | None = None
    escuela: str | None = None
    area: str | None = None
    jornada: str | None = None
    modalidad: str | None = None
    edificio: str | None = None
    estado: str | None = None
    estado_gestion: str | None = None
    docente: str | None = None
    codigo: str | None = None
    q: str | None = None

    SIMPLES = ("tipo", "escuela", "area", "jornada", "modalidad", "edificio", "estado",
               "estado_gestion", "docente", "codigo")

    def where(self, con_snapshot: bool = True) -> tuple[str, list]:
        cond, params = [], []
        if con_snapshot:
            cond.append("s.snapshot_id = ?")
            params.append(self.snapshot_id)
        for columna in self.SIMPLES:
            valor = getattr(self, columna)
            if valor:
                cond.append(f"s.{columna} = ?")
                params.append(valor)
        if self.q and self.q.strip():
            like = f"%{self.q.strip().upper()}%"
            cond.append(
                "(UPPER(s.curso) LIKE ? OR s.codigo LIKE ? OR UPPER(COALESCE(s.docente,'')) LIKE ?"
                " OR UPPER(COALESCE(s.salon,'')) LIKE ? OR UPPER(COALESCE(s.edificio,'')) LIKE ?"
                " OR UPPER(COALESCE(s.seccion,'')) = ?"
                " OR EXISTS (SELECT 1 FROM miembros m WHERE m.seccion_id = s.id"
                "            AND UPPER(m.nombre) LIKE ?))")
            params.extend([like] * 5 + [self.q.strip().upper(), like])
        return (" AND ".join(cond) or "1=1"), params


def _rows(con, sql, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


# ═══════════════════════════════════════════════════════════════════════════
# Snapshots y períodos (R1-12, R2-01)
# ═══════════════════════════════════════════════════════════════════════════
ORDEN_SNAPSHOTS = "anio DESC, periodo_orden DESC, fecha_corte DESC"


def snapshots(con) -> list[dict]:
    return _rows(con, f"""
        SELECT id, archivo_nombre, sha256, encabezado, periodo_codigo, periodo_nombre,
               periodo_orden, semestre, anio, fecha_corte, cargado_en, origen,
               total_secciones, total_asignados, trae_clasificacion, advertencias_json
        FROM snapshots ORDER BY {ORDEN_SNAPSHOTS}""")


def snapshot(con, snapshot_id: int) -> dict | None:
    r = con.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return dict(r) if r else None


def snapshot_vigente(con) -> dict | None:
    """El corte más reciente del período académico más reciente (no el último subido)."""
    r = con.execute(f"SELECT * FROM snapshots ORDER BY {ORDEN_SNAPSHOTS} LIMIT 1").fetchone()
    return dict(r) if r else None


def cortes_del_periodo(con, snap: dict) -> list[dict]:
    return _rows(con, """
        SELECT id, fecha_corte, total_asignados, total_secciones, archivo_nombre
        FROM snapshots WHERE anio = ? AND periodo_nombre = ?
        ORDER BY fecha_corte""", (snap["anio"], snap["periodo_nombre"]))


def periodos(con) -> list[dict]:
    """Árbol año -> período -> cortes, para los selectores del tablero."""
    salida: dict = {}
    for s in snapshots(con):
        anio = salida.setdefault(s["anio"], {})
        p = anio.setdefault(s["periodo_nombre"], {
            "periodo_nombre": s["periodo_nombre"], "periodo_codigo": s["periodo_codigo"],
            "periodo_orden": s["periodo_orden"], "cortes": []})
        p["cortes"].append({"id": s["id"], "fecha_corte": s["fecha_corte"],
                            "total_asignados": s["total_asignados"]})
    return [
        {"anio": a, "periodos": sorted(ps.values(), key=lambda x: -x["periodo_orden"])}
        for a, ps in sorted(salida.items(), reverse=True)
    ]


# ═══════════════════════════════════════════════════════════════════════════
# R1-01 · KPI de encabezado
# ═══════════════════════════════════════════════════════════════════════════
def kpis(con, f: Filtros) -> dict:
    w, p = f.where()
    k = dict(con.execute(f"""
        SELECT COUNT(*)                                         AS secciones,
               SUM(s.cerrada)                                   AS cerradas,
               COUNT(DISTINCT s.codigo)                         AS cursos,
               COUNT(DISTINCT s.docente)                        AS docentes,
               COALESCE(SUM(s.total), 0)                        AS asignados,
               COALESCE(SUM(CASE WHEN {ABIERTA} THEN s.limite END), 0) AS cupo,
               COALESCE(SUM(CASE WHEN {ABIERTA} AND s.limite > 0 THEN s.total END), 0)
                                                                AS asignados_con_cupo,
               SUM(CASE WHEN {ABIERTA} AND s.sin_docente = 1 THEN 1 ELSE 0 END) AS sin_docente,
               SUM(CASE WHEN s.estado_gestion = 'Pendiente' THEN 1 ELSE 0 END) AS con_pendientes,
               SUM(CASE WHEN {ABIERTA} AND s.con_auxiliar = 1 THEN 1 ELSE 0 END)
                                                                AS secciones_con_auxiliar,
               COUNT(DISTINCT CASE WHEN s.modalidad = 'Presencial'
                     THEN s.edificio || '-' || COALESCE(s.salon, '') END) AS salones
        FROM secciones s WHERE {w}""", p).fetchone())
    for clave in ("cerradas", "sin_docente", "con_pendientes", "secciones_con_auxiliar"):
        k[clave] = k[clave] or 0
    k["abiertas"] = k["secciones"] - k["cerradas"]
    k["ocupacion"] = (k["asignados_con_cupo"] / k["cupo"]) if k["cupo"] else None
    k["cupo_libre"] = max(k["cupo"] - k["asignados_con_cupo"], 0)
    k["promedio_seccion"] = (k["asignados"] / k["abiertas"]) if k["abiertas"] else 0
    k["cobertura_auxiliares"] = (k["secciones_con_auxiliar"] / k["abiertas"]) if k["abiertas"] else 0
    k["auxiliares"] = con.execute(f"""
        SELECT COUNT(DISTINCT m.nombre) FROM secciones s JOIN miembros m ON m.seccion_id = s.id
        WHERE {w} AND m.tipo LIKE '%AUXILIAR%'""", p).fetchone()[0]

    proc = con.execute(f"""
        SELECT {", ".join(f"COALESCE(SUM(s.{c}),0) AS {c}" for c, _ in config.COLUMNAS_PROCEDENCIA)}
        FROM secciones s WHERE {w}""", p).fetchone()
    k["procedencia"] = [{"clave": c, "etiqueta": e, "valor": proc[c]}
                        for c, e in config.COLUMNAS_PROCEDENCIA]
    k["procedencia_disponible"] = any(d["valor"] for d in k["procedencia"] if d["clave"] != "regulares")
    k["clasificacion"] = _rows(con, f"""
        SELECT s.clasificacion_origen AS origen, COUNT(*) AS secciones
        FROM secciones s WHERE {w} GROUP BY s.clasificacion_origen""", p)
    return k


# ═══════════════════════════════════════════════════════════════════════════
# R1-02 · Catálogos para los filtros
# ═══════════════════════════════════════════════════════════════════════════
def catalogos(con, snapshot_id: int, escuela: str | None = None) -> dict:
    def distintos(columna: str, extra: str = "", params: tuple = ()) -> list[str]:
        return [r[0] for r in con.execute(
            f"SELECT DISTINCT {columna} FROM secciones WHERE snapshot_id = ? "
            f"AND {columna} IS NOT NULL {extra} ORDER BY 1", (snapshot_id, *params))]

    presentes = set(distintos("estado"))
    return {
        "tipo": distintos("tipo"),
        "escuela": distintos("escuela"),
        "area": distintos("area", "AND escuela = ?", (escuela,)) if escuela else distintos("area"),
        "jornada": distintos("jornada"),
        "modalidad": distintos("modalidad"),
        "edificio": distintos("edificio"),
        "estado": [e for e in config.ESTADOS if e in presentes],
        "estado_gestion": [e for e in ("Pendiente", "En revisión", "Al día", "Cerrada")
                           if e in set(distintos("estado_gestion"))],
        "escuela_foco": config.ESCUELA_FOCO,
        "umbrales": {
            "riesgo_cierre": config.UMBRAL_RIESGO_CIERRE,
            "saludable_bajo": config.UMBRAL_SALUDABLE_BAJO,
            "llena": config.UMBRAL_LLENA,
            "seccion_grande": config.UMBRAL_SECCION_GRANDE,
            "meta_dias": config.META_DIAS_ATENCION,
        },
        "usa_limite_minimo": bool(con.execute(
            "SELECT 1 FROM secciones WHERE snapshot_id = ? AND limite_min > 0 LIMIT 1",
            (snapshot_id,)).fetchone()),
    }


# ═══════════════════════════════════════════════════════════════════════════
# R1-03 · Cursos por demanda
# ═══════════════════════════════════════════════════════════════════════════
def cursos(con, f: Filtros, limite: int = 20, orden: str = "asignados") -> list[dict]:
    w, p = f.where()
    ordenes = {"asignados": "asignados DESC", "secciones": "secciones DESC",
               "promedio": "promedio DESC", "ocupacion": "ocupacion DESC NULLS LAST",
               "codigo": "s.codigo ASC", "pendientes": "pendientes DESC, asignados DESC"}
    return _rows(con, f"""
        SELECT s.codigo, s.curso, s.escuela, s.area,
               SUM(CASE WHEN {ABIERTA} THEN 1 ELSE 0 END)           AS secciones,
               SUM(s.cerrada)                                        AS cerradas,
               COALESCE(SUM(s.total), 0)                             AS asignados,
               COALESCE(SUM(CASE WHEN {ABIERTA} THEN s.limite END), 0) AS cupo,
               ROUND(AVG(CASE WHEN {ABIERTA} THEN s.total END), 1)   AS promedio,
               CASE WHEN SUM(CASE WHEN {ABIERTA} THEN s.limite END) > 0 THEN
                    1.0 * SUM(CASE WHEN {ABIERTA} AND s.limite > 0 THEN s.total END)
                        / SUM(CASE WHEN {ABIERTA} THEN s.limite END) END AS ocupacion,
               SUM(CASE WHEN s.estado = 'Sobrecupo' THEN 1 ELSE 0 END) AS sobrecupo,
               SUM(CASE WHEN s.estado IN ('Riesgo de cierre','Sin asignados') THEN 1 ELSE 0 END)
                                                                     AS en_riesgo,
               SUM(CASE WHEN s.estado_gestion = 'Pendiente' THEN 1 ELSE 0 END) AS pendientes
        FROM secciones s WHERE {w}
        GROUP BY s.codigo, s.curso, s.escuela, s.area
        ORDER BY {ordenes.get(orden, ordenes['asignados'])}
        LIMIT ?""", [*p, limite])


# ═══════════════════════════════════════════════════════════════════════════
# R1-04 / R1-05 · Ocupación
# ═══════════════════════════════════════════════════════════════════════════
def ocupacion(con, f: Filtros) -> dict:
    w, p = f.where()
    por_estado = {r["estado"]: r for r in _rows(con, f"""
        SELECT s.estado, COUNT(*) AS secciones, COALESCE(SUM(s.total),0) AS asignados,
               COALESCE(SUM(s.limite),0) AS cupo
        FROM secciones s WHERE {w} GROUP BY s.estado""", p)}
    return {
        "por_estado": [por_estado.get(e, {"estado": e, "secciones": 0, "asignados": 0, "cupo": 0})
                       for e in config.ESTADOS],
        "histograma": _rows(con, f"""
            SELECT CASE
                     WHEN s.cerrada = 1 THEN 'cerrada'
                     WHEN s.limite = 0 THEN 'n/d'
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


# ═══════════════════════════════════════════════════════════════════════════
# R1-06 · Carga docente
# ═══════════════════════════════════════════════════════════════════════════
def docentes(con, f: Filtros, limite: int = 25, orden: str = "asignados") -> list[dict]:
    w, p = f.where()
    ordenes = {"asignados": "asignados DESC", "secciones": "secciones DESC",
               "horas": "horas_semana DESC", "nombre": "s.docente ASC"}
    return _rows(con, f"""
        SELECT s.docente,
               COUNT(*)                                AS secciones,
               COUNT(DISTINCT s.codigo)                AS cursos,
               COALESCE(SUM(s.total), 0)               AS asignados,
               COALESCE(SUM(s.horas_semana), 0)        AS horas_semana,
               GROUP_CONCAT(DISTINCT s.escuela)        AS escuelas,
               (SELECT COUNT(DISTINCT m.nombre) FROM miembros m
                  JOIN secciones s2 ON s2.id = m.seccion_id
                 WHERE s2.snapshot_id = s.snapshot_id AND s2.docente = s.docente
                   AND m.tipo LIKE '%AUXILIAR%')       AS auxiliares
        FROM secciones s WHERE {w} AND s.docente IS NOT NULL AND {ABIERTA}
        GROUP BY s.docente
        ORDER BY {ordenes.get(orden, ordenes['asignados'])}
        LIMIT ?""", [*p, limite])


# ═══════════════════════════════════════════════════════════════════════════
# R1-07 · Auxiliares y demás miembros de terna
# ═══════════════════════════════════════════════════════════════════════════
def auxiliares(con, f: Filtros, limite: int = 25) -> dict:
    w, p = f.where()
    ranking = _rows(con, f"""
        SELECT m.nombre, m.tipo, COUNT(DISTINCT s.id) AS secciones,
               COUNT(DISTINCT s.codigo) AS cursos, COALESCE(SUM(s.total), 0) AS asignados
        FROM secciones s JOIN miembros m ON m.seccion_id = s.id
        WHERE {w} AND m.tipo LIKE '%AUXILIAR%'
        GROUP BY m.nombre, m.tipo ORDER BY asignados DESC LIMIT ?""", [*p, limite])
    sin_auxiliar = _rows(con, f"""
        SELECT s.codigo, s.curso, s.seccion, s.tipo, s.docente, s.total, s.limite, s.estado
        FROM secciones s WHERE {w} AND {ABIERTA} AND s.con_auxiliar = 0
        ORDER BY s.total DESC LIMIT ?""", [*p, limite])
    resumen = dict(con.execute(f"""
        SELECT SUM(CASE WHEN {ABIERTA} THEN 1 ELSE 0 END) AS secciones,
               SUM(CASE WHEN {ABIERTA} AND s.con_auxiliar = 1 THEN 1 ELSE 0 END) AS con_auxiliar,
               COALESCE(SUM(CASE WHEN {ABIERTA} AND s.con_auxiliar = 0 THEN s.total END), 0)
                   AS asignados_sin_auxiliar
        FROM secciones s WHERE {w}""", p).fetchone())
    tipos = _rows(con, f"""
        SELECT m.tipo, COUNT(DISTINCT m.nombre) AS personas, COUNT(DISTINCT s.id) AS secciones
        FROM secciones s JOIN miembros m ON m.seccion_id = s.id WHERE {w}
        GROUP BY m.tipo ORDER BY secciones DESC""", p)
    return {"ranking": ranking, "sin_auxiliar": sin_auxiliar, "resumen": resumen,
            "tipos_miembro": tipos}


# ═══════════════════════════════════════════════════════════════════════════
# R1-08 · Horarios y salones
# ═══════════════════════════════════════════════════════════════════════════
def heatmap(con, f: Filtros) -> dict:
    w, p = f.where()
    filas = _rows(con, f"""
        SELECT b.dia, substr(b.hora_inicio, 1, 2) AS hora,
               COUNT(DISTINCT s.id) AS secciones, COALESCE(SUM(s.total), 0) AS asignados
        FROM secciones s JOIN bloques b ON b.seccion_id = s.id
        WHERE {w} AND {ABIERTA} AND b.hora_inicio IS NOT NULL
        GROUP BY b.dia, hora""", p)
    horas = sorted({r["hora"] for r in filas})
    dias = [d for d in config.DIAS if any(r["dia"] == d for r in filas)]
    celdas = {(r["dia"], r["hora"]): r for r in filas}
    return {
        "dias": dias, "dias_nombre": config.DIAS_NOMBRE, "horas": horas,
        "celdas": [{"dia": d, "hora": h,
                    "secciones": celdas.get((d, h), {}).get("secciones", 0),
                    "asignados": celdas.get((d, h), {}).get("asignados", 0)}
                   for d in dias for h in horas],
    }


def salones(con, f: Filtros, limite: int = 25) -> list[dict]:
    w, p = f.where()
    return _rows(con, f"""
        SELECT s.edificio, s.salon, COUNT(*) AS secciones, COALESCE(SUM(s.total), 0) AS asignados,
               COALESCE(SUM(s.horas_semana), 0) AS horas_semana, MAX(s.total) AS seccion_mas_grande
        FROM secciones s WHERE {w} AND s.modalidad = 'Presencial'
        GROUP BY s.edificio, s.salon ORDER BY horas_semana DESC LIMIT ?""", [*p, limite])


# ═══════════════════════════════════════════════════════════════════════════
# R1-09 · Distribuciones
# ═══════════════════════════════════════════════════════════════════════════
COLUMNAS_DISTRIBUCION = {"modalidad", "jornada", "escuela", "area", "tipo", "estado_gestion",
                         "edificio"}


def distribucion(con, f: Filtros, columna: str) -> list[dict]:
    if columna not in COLUMNAS_DISTRIBUCION:
        raise ValueError(f"columna no permitida: {columna}")
    w, p = f.where()
    return _rows(con, f"""
        SELECT COALESCE(s.{columna}, '(sin dato)') AS etiqueta, COUNT(*) AS secciones,
               COALESCE(SUM(s.total), 0) AS asignados,
               COALESCE(SUM(CASE WHEN {ABIERTA} THEN s.limite END), 0) AS cupo
        FROM secciones s WHERE {w} GROUP BY s.{columna} ORDER BY asignados DESC, secciones DESC""", p)


# ═══════════════════════════════════════════════════════════════════════════
# R1-10 · Tabla de secciones
# ═══════════════════════════════════════════════════════════════════════════
ORDENES_SECCIONES = {
    "asignados": "s.total DESC", "ocupacion": "s.ocupacion DESC NULLS LAST",
    "ocupacion_asc": "s.ocupacion ASC NULLS LAST", "curso": "s.curso ASC, s.seccion ASC",
    "codigo": "s.codigo ASC, s.seccion ASC", "docente": "s.docente ASC NULLS LAST",
}


def secciones(con, f: Filtros, limite: int = 100, offset: int = 0, orden: str = "asignados") -> dict:
    w, p = f.where()
    total = con.execute(f"SELECT COUNT(*) FROM secciones s WHERE {w}", p).fetchone()[0]
    filas = _rows(con, f"""
        SELECT s.id, s.tipo, s.codigo, s.curso, s.seccion, s.escuela, s.area, s.subarea,
               s.clasificacion_origen, s.edificio, s.salon, s.modalidad, s.jornada,
               s.hora_inicio, s.hora_fin, s.dias, s.horas_semana, s.docente, s.sin_docente,
               s.cerrada, s.total, s.limite, s.limite_min, s.ocupacion, s.estado,
               s.estado_gestion, s.fila_origen,
               (SELECT GROUP_CONCAT(m.nombre, ' · ') FROM miembros m
                 WHERE m.seccion_id = s.id AND m.tipo LIKE '%AUXILIAR%') AS auxiliares,
               (SELECT GROUP_CONCAT(m.nombre || ' (' || m.tipo || ')', ' · ') FROM miembros m
                 WHERE m.seccion_id = s.id AND m.tipo NOT LIKE '%AUXILIAR%') AS otros_miembros,
               (SELECT GROUP_CONCAT(g.tipo, ' · ') FROM gestiones g
                 WHERE g.seccion_id = s.id) AS gestiones
        FROM secciones s WHERE {w}
        ORDER BY {ORDENES_SECCIONES.get(orden, ORDENES_SECCIONES['asignados'])}
        LIMIT ? OFFSET ?""", [*p, limite, offset])
    return {"total": total, "limite": limite, "offset": offset, "filas": filas}


# ═══════════════════════════════════════════════════════════════════════════
# Perfil · Vista 2: estado de gestiones (R1-13)
# ═══════════════════════════════════════════════════════════════════════════
def estado_gestiones(con, f: Filtros, limite_cursos: int = 15) -> dict:
    w, p = f.where()
    por_tipo = _rows(con, f"""
        SELECT g.clave, g.tipo, g.severidad, COUNT(*) AS secciones,
               COUNT(DISTINCT s.codigo) AS cursos, COALESCE(SUM(s.total), 0) AS estudiantes
        FROM gestiones g JOIN secciones s ON s.id = g.seccion_id
        WHERE {w} GROUP BY g.clave, g.tipo, g.severidad ORDER BY secciones DESC""", p)
    vistos = {r["clave"] for r in por_tipo}
    for clave, (nombre, sev) in config.TIPOS_GESTION.items():
        if clave not in vistos:
            por_tipo.append({"clave": clave, "tipo": nombre, "severidad": sev,
                             "secciones": 0, "cursos": 0, "estudiantes": 0})
    por_estado = _rows(con, f"""
        SELECT s.estado_gestion AS estado, COUNT(*) AS secciones
        FROM secciones s WHERE {w} GROUP BY s.estado_gestion""", p)
    por_curso = _rows(con, f"""
        SELECT s.codigo, s.curso,
               SUM(CASE WHEN s.estado_gestion = 'Al día' THEN 1 ELSE 0 END)      AS al_dia,
               SUM(CASE WHEN s.estado_gestion = 'En revisión' THEN 1 ELSE 0 END) AS en_revision,
               SUM(CASE WHEN s.estado_gestion = 'Pendiente' THEN 1 ELSE 0 END)   AS pendiente,
               SUM(CASE WHEN {ABIERTA} THEN 1 ELSE 0 END)                        AS abiertas
        FROM secciones s WHERE {w}
        GROUP BY s.codigo, s.curso HAVING abiertas > 0
        ORDER BY pendiente DESC, en_revision DESC, abiertas DESC
        LIMIT ?""", [*p, limite_cursos])
    pendientes = _rows(con, f"""
        SELECT s.codigo, s.curso, s.seccion, s.tipo AS tipo_seccion, s.docente, s.total,
               s.limite, g.tipo, g.severidad, g.detalle
        FROM gestiones g JOIN secciones s ON s.id = g.seccion_id
        WHERE {w}
        ORDER BY CASE g.severidad WHEN 'pendiente' THEN 0 ELSE 1 END, s.total DESC
        LIMIT 300""", p)
    return {"por_tipo": por_tipo, "por_estado": por_estado, "por_curso": por_curso,
            "detalle": pendientes}


# ═══════════════════════════════════════════════════════════════════════════
# Perfil · Vista 3: tiempos de atención (R1-14)
# ═══════════════════════════════════════════════════════════════════════════
def tiempos_atencion(con, f: Filtros) -> dict:
    snap = snapshot(con, f.snapshot_id)
    if not snap:
        return {"disponible": False, "cortes": 0, "por_tipo": [], "episodios": []}
    cortes = cortes_del_periodo(con, snap)
    w, p = f.where(con_snapshot=False)
    ids = [c["id"] for c in cortes]
    marcas = ",".join("?" * len(ids))
    filas = _rows(con, f"""
        SELECT g.snapshot_id, s.tipo AS tipo_seccion, s.codigo, s.curso, s.seccion,
               g.clave, g.tipo
        FROM gestiones g JOIN secciones s ON s.id = g.seccion_id
        WHERE g.snapshot_id IN ({marcas}) AND {w}""", [*ids, *p])
    res = gestiones.tiempos_de_atencion(cortes, filas)
    res["periodo"] = f"{snap['periodo_nombre']} {snap['anio']}"
    res["cortes_detalle"] = cortes
    res["meta_dias"] = config.META_DIAS_ATENCION
    res["episodios"] = res.get("episodios", [])[:300]
    return res


# ═══════════════════════════════════════════════════════════════════════════
# Perfil · Vista 1 ampliada: seguimiento entre cortes y períodos (R2-01)
# ═══════════════════════════════════════════════════════════════════════════
def evolucion(con, f: Filtros) -> dict:
    snap = snapshot(con, f.snapshot_id)
    if not snap:
        return {"cortes": [], "historico": [], "cambios": None}
    w, p = f.where(con_snapshot=False)
    cortes = _rows(con, f"""
        SELECT sn.id, sn.fecha_corte,
               COALESCE(SUM(s.total), 0) AS asignados,
               SUM(CASE WHEN s.cerrada = 0 THEN 1 ELSE 0 END) AS abiertas,
               SUM(s.cerrada) AS cerradas,
               SUM(CASE WHEN s.estado_gestion = 'Pendiente' THEN 1 ELSE 0 END) AS pendientes
        FROM snapshots sn LEFT JOIN secciones s ON s.snapshot_id = sn.id AND {w}
        WHERE sn.anio = ? AND sn.periodo_nombre = ?
        GROUP BY sn.id ORDER BY sn.fecha_corte""", [*p, snap["anio"], snap["periodo_nombre"]])
    historico = _rows(con, f"""
        WITH ultimos AS (
            SELECT id, anio, periodo_nombre, periodo_orden, fecha_corte,
                   ROW_NUMBER() OVER (PARTITION BY anio, periodo_nombre
                                      ORDER BY fecha_corte DESC) AS n
            FROM snapshots)
        SELECT u.id, u.anio, u.periodo_nombre, u.periodo_orden, u.fecha_corte,
               COALESCE(SUM(s.total), 0) AS asignados,
               SUM(CASE WHEN s.cerrada = 0 THEN 1 ELSE 0 END) AS abiertas,
               SUM(s.cerrada) AS cerradas
        FROM ultimos u LEFT JOIN secciones s ON s.snapshot_id = u.id AND {w}
        WHERE u.n = 1
        GROUP BY u.id ORDER BY u.anio, u.periodo_orden""", p)

    anterior = next((c for c in reversed(cortes) if c["fecha_corte"] < snap["fecha_corte"]), None)
    cambios = None
    if anterior:
        cambios = {"desde": anterior["fecha_corte"], "hasta": snap["fecha_corte"],
                   "cursos": cambios_por_curso(con, f, anterior["id"])}
    return {"periodo": f"{snap['periodo_nombre']} {snap['anio']}", "cortes": cortes,
            "historico": historico, "cambios": cambios}


def cambios_por_curso(con, f: Filtros, id_anterior: int, limite: int = 40) -> list[dict]:
    w, p = f.where(con_snapshot=False)
    return _rows(con, f"""
        WITH a AS (SELECT s.codigo, s.curso, SUM(s.total) AS asignados,
                          SUM(CASE WHEN s.cerrada = 0 THEN 1 ELSE 0 END) AS abiertas
                   FROM secciones s WHERE s.snapshot_id = ? AND {w} GROUP BY s.codigo),
             b AS (SELECT s.codigo, s.curso, SUM(s.total) AS asignados,
                          SUM(CASE WHEN s.cerrada = 0 THEN 1 ELSE 0 END) AS abiertas
                   FROM secciones s WHERE s.snapshot_id = ? AND {w} GROUP BY s.codigo),
             todos AS (SELECT codigo, curso FROM a UNION SELECT codigo, curso FROM b)
        SELECT t.codigo, t.curso,
               COALESCE(a.asignados, 0) AS antes, COALESCE(b.asignados, 0) AS ahora,
               COALESCE(b.asignados, 0) - COALESCE(a.asignados, 0) AS delta,
               COALESCE(a.abiertas, 0) AS secciones_antes, COALESCE(b.abiertas, 0) AS secciones_ahora
        FROM todos t LEFT JOIN a ON a.codigo = t.codigo LEFT JOIN b ON b.codigo = t.codigo
        GROUP BY t.codigo
        HAVING delta != 0 OR secciones_antes != secciones_ahora
        ORDER BY ABS(delta) DESC LIMIT ?""", [id_anterior, *p, f.snapshot_id, *p, limite])


# ═══════════════════════════════════════════════════════════════════════════
# R1-15 · Bitácora de cargas
# ═══════════════════════════════════════════════════════════════════════════
def cargas(con, limite: int = 100) -> list[dict]:
    return _rows(con, "SELECT * FROM cargas ORDER BY id DESC LIMIT ?", (limite,))


# ═══════════════════════════════════════════════════════════════════════════
# Contrato de datos para Power BI (tablas planas)
# ═══════════════════════════════════════════════════════════════════════════
TABLAS_POWERBI = {
    "dim_snapshot": """SELECT id AS snapshot_id, periodo_codigo, periodo_nombre, periodo_orden,
                              semestre, anio, fecha_corte, archivo_nombre, cargado_en,
                              total_secciones, total_asignados FROM snapshots""",
    "dim_curso": """SELECT codigo, curso, escuela, area, subarea, fuente FROM catalogo_cursos""",
    "fact_seccion": """SELECT s.id AS seccion_id, s.snapshot_id, s.tipo, s.codigo, s.curso,
                              s.seccion, s.escuela, s.area, s.subarea, s.clasificacion_origen,
                              s.edificio, s.salon, s.modalidad, s.jornada, s.hora_inicio,
                              s.hora_fin, s.dias, s.horas_semana, s.docente, s.sin_docente,
                              s.cerrada, s.regulares, s.otra_fac, s.centros_reg, s.otra_univ,
                              s.no_insc, s.est_cierre, s.otro_caso, s.total, s.limite,
                              s.limite_min, s.ocupacion, s.estado, s.estado_gestion,
                              s.con_auxiliar FROM secciones s""",
    "fact_gestion": """SELECT g.id AS gestion_id, g.seccion_id, g.snapshot_id, g.clave, g.tipo,
                              g.severidad, g.detalle FROM gestiones g""",
    "fact_miembro": """SELECT m.seccion_id, m.nombre, m.tipo FROM miembros m""",
    "fact_horario": """SELECT b.seccion_id, b.dia, b.hora_inicio, b.hora_fin FROM bloques b""",
    "bitacora_cargas": """SELECT id, cuando, origen, archivo_nombre, resultado, snapshot_id,
                                 descripcion, mensaje FROM cargas""",
}


def tabla_powerbi(con: sqlite3.Connection, nombre: str):
    if nombre not in TABLAS_POWERBI:
        raise KeyError(nombre)
    cur = con.execute(TABLAS_POWERBI[nombre])
    return [d[0] for d in cur.description], cur.fetchall()


# ═══════════════════════════════════════════════════════════════════════════
# R1-19 · Predicciones (ver predicciones.py)
# ═══════════════════════════════════════════════════════════════════════════
TIPO_DOCUMENTO_PREDICCION = "ASIGNADOS_CONDENSADO"


def series_de_periodo(con) -> list[dict]:
    """Tipos de período cargados y cuántos años distintos tiene cada uno."""
    return _rows(con, """
        SELECT periodo_nombre, periodo_codigo, MIN(periodo_orden) AS periodo_orden,
               COUNT(DISTINCT anio) AS anios, MIN(anio) AS desde, MAX(anio) AS hasta
        FROM snapshots WHERE tipo_documento = ?
        GROUP BY periodo_nombre, periodo_codigo
        ORDER BY anios DESC, periodo_orden""", (TIPO_DOCUMENTO_PREDICCION,))


def filas_prediccion(con, periodo_nombre: str) -> tuple[list[dict], list[dict]]:
    """Una fila por (año, tipo de sección, curso) usando el ÚLTIMO corte de cada año
    de ese tipo de período. Nunca mezcla tipos de período ni tipos de documento."""
    cortes = _rows(con, """
        WITH u AS (SELECT id, anio, fecha_corte,
                          ROW_NUMBER() OVER (PARTITION BY anio ORDER BY fecha_corte DESC) AS n
                   FROM snapshots WHERE tipo_documento = ? AND periodo_nombre = ?)
        SELECT id, anio, fecha_corte FROM u WHERE n = 1 ORDER BY anio""",
                   (TIPO_DOCUMENTO_PREDICCION, periodo_nombre))
    if not cortes:
        return [], []
    marcas = ",".join("?" * len(cortes))
    filas = _rows(con, f"""
        SELECT sn.anio, s.tipo, s.codigo, MAX(s.curso) AS curso, MAX(s.escuela) AS escuela,
               MAX(s.area) AS area, COALESCE(SUM(s.total), 0) AS asignados,
               SUM(CASE WHEN s.cerrada = 0 THEN 1 ELSE 0 END) AS abiertas,
               COALESCE(SUM(CASE WHEN s.cerrada = 0 THEN s.limite END), 0) AS cupo,
               GROUP_CONCAT(CASE WHEN s.cerrada = 0 AND s.limite > 0 THEN s.limite END) AS limites
        FROM secciones s JOIN snapshots sn ON sn.id = s.snapshot_id
        WHERE s.snapshot_id IN ({marcas})
        GROUP BY sn.anio, s.tipo, s.codigo""", [c["id"] for c in cortes])
    return cortes, filas


FILTROS_PREDICCION = ("tipo", "escuela", "area", "codigo", "q")


def predicciones(con, f: Filtros, periodo_nombre: str | None = None) -> dict:
    snap = snapshot(con, f.snapshot_id)
    periodo_nombre = periodo_nombre or snap["periodo_nombre"]
    cortes, filas = filas_prediccion(con, periodo_nombre)
    base = {
        "periodo": periodo_nombre,
        "tipo_documento": TIPO_DOCUMENTO_PREDICCION,
        "series_disponibles": series_de_periodo(con),
        "anios_base": [{"anio": c["anio"], "fecha_corte": c["fecha_corte"],
                        "asignados": sum(x["asignados"] for x in filas if x["anio"] == c["anio"])}
                       for c in cortes],
        "filtros_aplicados": {k: getattr(f, k) for k in FILTROS_PREDICCION if getattr(f, k)},
        "filtros_ignorados": [k for k in Filtros.SIMPLES if getattr(f, k) and k not in FILTROS_PREDICCION],
    }
    res = pred.predecir(filas)
    if not res["disponible"]:
        return {**base, "disponible": False}

    def pasa(c: dict) -> bool:
        if f.tipo and c["tipo"] != f.tipo:
            return False
        if f.escuela and c["escuela"] != f.escuela:
            return False
        if f.area and c["area"] != f.area:
            return False
        if f.codigo and c["codigo"] != f.codigo:
            return False
        if f.q and f.q.strip():
            t = f.q.strip().upper()
            if t not in (c["curso"] or "").upper() and t not in c["codigo"]:
                return False
        return True

    cursos = [{k: v for k, v in c.items() if k not in ("z", "sd")} for c in res["cursos"] if pasa(c)]
    cursos.sort(key=lambda c: -c["prediccion"])
    resumen = {
        "cursos": len(cursos),
        "prediccion": round(sum(c["prediccion"] for c in cursos)),
        "ultimo_valor": round(sum(c["ultimo_valor"] for c in cursos)),
        "secciones_actuales": sum(c["secciones_actuales"] or 0 for c in cursos),
        "secciones_sugeridas": sum(c["secciones_sugeridas"] or 0 for c in cursos),
        "riesgo_sobrecupo": sum(1 for c in cursos if (c["prob_sobrecupo"] or 0) >= 0.5),
        "abrir_mas": sum(1 for c in cursos if (c["cambio_secciones"] or 0) > 0),
        "abrir_menos": sum(1 for c in cursos if (c["cambio_secciones"] or 0) < 0),
    }
    return {**base, **{k: v for k, v in res.items() if k not in ("cursos",)},
            "cursos": cursos, "resumen": resumen,
            "no_ofertados": [n for n in res["no_ofertados"] if pasa(n)]}
