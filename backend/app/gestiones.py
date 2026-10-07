"""
Gestiones derivadas del reporte de asignados.

El perfil del proyecto pide dos vistas —«estado de gestiones» y «tiempos de
atención»— y el único insumo existente es el reporte de asignados. Este módulo
se acerca a ambas usando solo lo que el reporte sí contiene:

Estado de gestiones
    Cada sección abierta se revisa contra reglas que corresponden a trámites
    reales de la Secretaría (asignar catedrático, conseguir salón, ampliar cupo,
    revisar cierre, definir límite, pedir plaza de auxiliar). El resultado por
    sección es «Al día», «En revisión» o «Pendiente», que es exactamente la
    barra apilada por curso del boceto del perfil.

Tiempos de atención
    Una gestión que aparece pendiente en un corte y ya no aparece en un corte
    posterior del MISMO período se considera atendida. Como solo se observa en
    las fechas de corte, el tiempo se reporta como cota superior («atendida a
    más tardar en N días»), y la Secretaría ve también cuántas siguen abiertas y
    desde cuándo. Con un solo corte por período la vista explica qué falta.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median

from . import config


def derivar(seccion: dict) -> list[dict]:
    """Gestiones que una sección requiere, según su fila del reporte."""
    if seccion.get("cerrada"):
        return []
    g = []
    total, limite, minimo = seccion["total"], seccion["limite"], seccion.get("limite_min") or 0

    def agrega(clave, detalle):
        nombre, severidad = config.TIPOS_GESTION[clave]
        g.append({"clave": clave, "tipo": nombre, "severidad": severidad, "detalle": detalle})

    if seccion.get("sin_docente"):
        agrega("catedratico", "Sección abierta con catedrático «STAFF» (sin asignar).")
    if seccion.get("modalidad") == "Sin salón":
        agrega("salon", "Sección presencial sin salón asignado en el reporte.")
    if limite and total > limite:
        agrega("cupo", f"{total} asignados para {limite} lugares (+{total - limite}).")
    if seccion.get("estado") in ("Riesgo de cierre", "Sin asignados"):
        if 0 < minimo < (limite or 0):
            agrega("cierre", f"{total} asignados, por debajo del mínimo oficial de {minimo}.")
        else:
            umbral = int(config.UMBRAL_RIESGO_CIERRE * 100)
            agrega("cierre", f"{total} asignados (menos del {umbral}% del cupo de {limite}).")
    if not limite and total > 0:
        agrega("limite", f"{total} asignados en una sección sin límite de asignados.")
    if total >= config.UMBRAL_SECCION_GRANDE and not any(
            "AUXILIAR" in (m.get("tipo") or "") for m in seccion.get("miembros", [])):
        agrega("auxiliar", f"{total} estudiantes sin auxiliar de cátedra.")
    return g


def estado_seccion(gestiones: list[dict], cerrada: bool) -> str:
    if cerrada:
        return "Cerrada"
    if any(x["severidad"] == "pendiente" for x in gestiones):
        return "Pendiente"
    if gestiones:
        return "En revisión"
    return "Al día"


# ═══════════════════════════════════════════════════════════════════════════
# Tiempos de atención entre cortes
# ═══════════════════════════════════════════════════════════════════════════
def tiempos_de_atencion(cortes: list[dict], filas: list[dict]) -> dict:
    """
    cortes: [{"id", "fecha_corte"}] de UN mismo período, en cualquier orden.
    filas:  [{"snapshot_id", "tipo_seccion", "codigo", "seccion", "clave",
              "tipo", "curso"}] — una por gestión observada en cada corte.
    """
    cortes = sorted(cortes, key=lambda c: c["fecha_corte"])
    if len(cortes) < 2:
        return {"disponible": False, "cortes": len(cortes), "por_tipo": [], "episodios": []}

    fechas = {c["id"]: datetime.fromisoformat(c["fecha_corte"]) for c in cortes}
    orden = [c["id"] for c in cortes]
    presentes: dict[tuple, set] = defaultdict(set)
    info: dict[tuple, dict] = {}
    for f in filas:
        clave = (f["tipo_seccion"], f["codigo"], f["seccion"], f["clave"])
        presentes[clave].add(f["snapshot_id"])
        info[clave] = f

    episodios = []
    for clave, snaps in presentes.items():
        inicio = None
        for i, sid in enumerate(orden):
            if sid in snaps and inicio is None:
                inicio = i
            elif sid not in snaps and inicio is not None:
                anterior = orden[i - 1]
                episodios.append(_episodio(info[clave], fechas, orden[inicio], sid, anterior,
                                           censurada=inicio == 0))
                inicio = None
        if inicio is not None:
            episodios.append(_episodio(info[clave], fechas, orden[inicio], None, orden[-1],
                                       censurada=inicio == 0))

    por_tipo = []
    for clave_tipo, (nombre, severidad) in config.TIPOS_GESTION.items():
        eps = [e for e in episodios if e["clave"] == clave_tipo]
        resueltas = [e["dias_max"] for e in eps if e["resuelta"]]
        abiertas = [e for e in eps if not e["resuelta"]]
        por_tipo.append({
            "clave": clave_tipo,
            "tipo": nombre,
            "severidad": severidad,
            "resueltas": len(resueltas),
            "abiertas": len(abiertas),
            "promedio_dias": round(sum(resueltas) / len(resueltas), 1) if resueltas else None,
            "mediana_dias": round(median(resueltas), 1) if resueltas else None,
            "antiguedad_abiertas_dias": round(
                sum(e["dias_abierta"] for e in abiertas) / len(abiertas), 1) if abiertas else None,
            "sobre_meta": sum(1 for d in resueltas if d > config.META_DIAS_ATENCION),
        })
    return {
        "disponible": True,
        "cortes": len(cortes),
        "primer_corte": cortes[0]["fecha_corte"],
        "ultimo_corte": cortes[-1]["fecha_corte"],
        "meta_dias": config.META_DIAS_ATENCION,
        "por_tipo": por_tipo,
        # primero las atendidas (son las que miden el tiempo), las más largas arriba
        "episodios": sorted(episodios, key=lambda e: (not e["resuelta"], -e["dias_max"], e["codigo"])),
    }


def _dias(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 86400, 1)


def _episodio(f, fechas, desde, hasta, ultimo_visto, censurada) -> dict:
    ini = fechas[desde]
    if hasta is not None:
        return {
            **{k: f[k] for k in ("tipo_seccion", "codigo", "curso", "seccion", "clave", "tipo")},
            "desde": ini.isoformat(), "hasta": fechas[hasta].isoformat(), "resuelta": True,
            "dias_max": _dias(ini, fechas[hasta]),
            "dias_min": _dias(ini, fechas[ultimo_visto]),
            "dias_abierta": None, "inicio_censurado": censurada,
        }
    return {
        **{k: f[k] for k in ("tipo_seccion", "codigo", "curso", "seccion", "clave", "tipo")},
        "desde": ini.isoformat(), "hasta": None, "resuelta": False,
        "dias_max": _dias(ini, fechas[ultimo_visto]), "dias_min": None,
        "dias_abierta": _dias(ini, fechas[ultimo_visto]), "inicio_censurado": censurada,
    }
