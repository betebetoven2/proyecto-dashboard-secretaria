"""Predicciones: propiedades estadísticas del modelo y aislamiento por tipo de documento/período."""

from __future__ import annotations

import math
import random
from datetime import datetime

import pytest

from backend.app import predicciones as P
from backend.app.autoprueba import SECCIONES_CLASE, SECCIONES_LAB, construir_reporte

from .conftest import REAL_2025, REAL_2026, subir


# ═══════════════════════════ simulación (verdad conocida) ═══════════════════════════
def simular(seed, k=150, anios=range(2020, 2027), sigma=0.10, tau=0.05, mu=0.04, sin_tendencia=False):
    rnd = random.Random(seed)
    filas = []
    for i in range(k):
        escuela = f"E{i % 5}"
        g = 0.0 if sin_tendencia else rnd.gauss(mu + (0.03 if escuela == "E0" else 0), tau)
        z = rnd.gauss(4, 1)
        for a in anios:
            filas.append(dict(anio=a, tipo="Clase", codigo=f"{i:04d}", curso=f"C{i}", escuela=escuela,
                              area=None, asignados=max(0, round(math.expm1(z))), abiertas=2, cupo=100,
                              limites="50,50"))
            z += g + rnd.gauss(0, sigma)
    return filas


def evaluar(filas, objetivo=2026):
    entreno = [f for f in filas if f["anio"] < objetivo]
    real = {f["codigo"]: f["asignados"] for f in filas if f["anio"] == objetivo}
    previo = {f["codigo"]: f["asignados"] for f in entreno if f["anio"] == objetivo - 1}
    r = P.predecir(entreno)
    cursos = r["cursos"]
    cobertura = sum(c["intervalo_bajo"] <= real[c["codigo"]] <= c["intervalo_alto"] for c in cursos) / len(cursos)
    em = sum(abs(real[c["codigo"]] - c["prediccion"]) for c in cursos)
    ei = sum(abs(real[c["codigo"]] - previo[c["codigo"]]) for c in cursos)
    return r, cobertura, em / ei


@pytest.mark.parametrize("escenario", [{}, {"sin_tendencia": True}, {"sigma": 0.25},
                                       {"anios": range(2024, 2027)}])
def test_intervalos_calibrados(escenario):
    """El intervalo del 80% debe contener ~80% de los valores reales (Monte Carlo)."""
    coberturas = [evaluar(simular(s, **escenario))[1] for s in range(8)]
    assert 0.72 <= sum(coberturas) / len(coberturas) <= 0.88, coberturas


def test_mejora_al_ingenuo_cuando_hay_tendencia():
    relativos = [evaluar(simular(s))[2] for s in range(8)]
    assert sum(relativos) / len(relativos) < 0.95


def test_recupera_parametros():
    r, _, _ = evaluar(simular(1))
    assert 0.08 <= r["modelo"]["ruido_anual_sigma"] <= 0.12
    assert 0.02 <= r["modelo"]["variacion_entre_cursos_tau"] <= 0.08


def test_validacion_con_origen_movil():
    r = P.predecir([f for f in simular(2) if f["anio"] < 2026])
    v = r["validacion"]
    assert v["disponible"] and v["anios_evaluados"] == [2022, 2023, 2024, 2025]
    assert 0.6 <= v["cobertura_intervalo"] <= 0.95


def test_con_un_solo_anio_no_predice():
    assert P.predecir([f for f in simular(3) if f["anio"] == 2025])["disponible"] is False


def test_curso_nuevo_recibe_crecimiento_de_su_escuela():
    filas = [f for f in simular(4) if f["anio"] >= 2023 and f["anio"] < 2026]
    filas.append(dict(anio=2025, tipo="Clase", codigo="9999", curso="NUEVO", escuela="E1", area=None,
                      asignados=40, abiertas=1, cupo=50, limites="50"))
    r = P.predecir(filas)
    nuevo = next(c for c in r["cursos"] if c["codigo"] == "9999")
    assert nuevo["peso_propio"] == 0 and nuevo["anios_historia"] == 1
    assert nuevo["intervalo_bajo"] < 40 < nuevo["intervalo_alto"]


def test_curso_no_ofertado_el_ultimo_anio():
    filas = [f for f in simular(5, k=20) if f["anio"] >= 2023 and f["anio"] < 2026]
    filas = [f for f in filas if not (f["codigo"] == "0003" and f["anio"] == 2025)]
    r = P.predecir(filas)
    assert "0003" not in {c["codigo"] for c in r["cursos"]}
    assert "0003" in {c["codigo"] for c in r["no_ofertados"]}


def test_ceros_y_anios_faltantes():
    filas = [dict(anio=a, tipo="Clase", codigo=c, curso=c, escuela="E", area=None, asignados=v,
                  abiertas=1, cupo=30, limites="30")
             for c, serie in {"A": {2020: 0, 2022: 10, 2025: 12}, "B": {2020: 20, 2022: 22, 2025: 25},
                              "C": {2020: 5, 2022: 0, 2025: 4}}.items() for a, v in serie.items()]
    r = P.predecir(filas)
    assert r["anio_objetivo"] == 2026
    for c in r["cursos"]:
        assert 0 <= c["intervalo_bajo"] <= c["prediccion"] <= c["intervalo_alto"]
        assert math.isfinite(c["intervalo_alto"])


def test_secciones_sugeridas_y_probabilidad_de_sobrecupo():
    filas = [dict(anio=a, tipo="Clase", codigo="X", curso="X", escuela="E", area=None,
                  asignados=v, abiertas=2, cupo=100, limites="50,50")
             for a, v in {2022: 80, 2023: 95, 2024: 110, 2025: 125}.items()]
    filas += [dict(anio=a, tipo="Clase", codigo=f"Y{i}", curso="Y", escuela="E", area=None,
                   asignados=50 + i, abiertas=1, cupo=60, limites="60")
              for a in (2022, 2023, 2024, 2025) for i in range(3)]
    c = next(x for x in P.predecir(filas)["cursos"] if x["codigo"] == "X")
    assert c["secciones_sugeridas"] >= 3 and c["cambio_secciones"] >= 1     # 125 ya excede 2×50
    assert c["prob_sobrecupo"] > 0.9


# ═══════════════════════════ integración: tipos de período y documento ═══════════════════════════
def escalar(secciones, factor):
    return [dict(s, regulares=round(s["regulares"] * factor), otra_fac=0) for s in secciones]


def test_no_mezcla_tipos_de_periodo(cliente, tmp_path):
    for i, anio in enumerate((2024, 2025, 2026)):
        subir(cliente, construir_reporte(tmp_path / f"s{anio}.xlsx", anio=anio,
                                         corte=datetime(anio, 3, 1), clase=escalar(SECCIONES_CLASE, 1 + 0.1 * i),
                                         laboratorio=escalar(SECCIONES_LAB, 1 + 0.1 * i)))
    subir(cliente, construir_reporte(tmp_path / "v.xlsx", periodo="VACACIONES DEL PRIMER SEMESTRE",
                                     anio=2025, corte=datetime(2025, 7, 1),
                                     clase=escalar(SECCIONES_CLASE, 5), laboratorio=[]))
    r = cliente.get("/api/predicciones", params={"periodo": "PRIMER SEMESTRE"}).json()
    assert r["disponible"] and r["anios"] == [2024, 2025, 2026] and r["anio_objetivo"] == 2027
    assert [a["anio"] for a in r["anios_base"]] == [2024, 2025, 2026]
    ipc = next(c for c in r["cursos"] if c["codigo"] == "0770" and c["tipo"] == "Clase")
    assert [h["asignados"] for h in ipc["historia"]] == [88, 97, 106]        # sin los ×5 de vacaciones
    v = cliente.get("/api/predicciones", params={"periodo": "VACACIONES DEL PRIMER SEMESTRE"}).json()
    assert v["disponible"] is False
    series = {s["periodo_nombre"]: s["anios"] for s in r["series_disponibles"]}
    assert series == {"PRIMER SEMESTRE": 3, "VACACIONES DEL PRIMER SEMESTRE": 1}


def test_usa_el_ultimo_corte_de_cada_anio(cliente, tmp_path):
    for anio in (2025, 2026):
        subir(cliente, construir_reporte(tmp_path / f"a{anio}.xlsx", anio=anio, corte=datetime(anio, 2, 1)))
    # segundo corte de 2026 con más asignados en 0770: debe ser el que cuente
    subir(cliente, construir_reporte(tmp_path / "b2026.xlsx", anio=2026, corte=datetime(2026, 3, 1),
                                     clase=[dict(s, regulares=s["regulares"] + 30) if s["codigo"] == "0770" else s
                                            for s in SECCIONES_CLASE]))
    r = cliente.get("/api/predicciones").json()
    assert r["anios_base"][-1]["fecha_corte"].startswith("2026-03-01")
    ipc = next(c for c in r["cursos"] if c["codigo"] == "0770" and c["tipo"] == "Clase")
    assert ipc["ultimo_valor"] == 120


def test_formatos_distintos_forman_la_misma_serie(cliente, tmp_path):
    """Un año con Escuela/Area (33 col.) y otro sin ellas (30 col.): misma serie por curso."""
    subir(cliente, construir_reporte(tmp_path / "a.xlsx", anio=2025, corte=datetime(2025, 3, 1), clasificacion=True))
    subir(cliente, construir_reporte(tmp_path / "b.xlsx", anio=2026, corte=datetime(2026, 3, 1), clasificacion=False))
    r = cliente.get("/api/predicciones").json()
    assert r["disponible"]
    claves = [(c["tipo"], c["codigo"]) for c in r["cursos"]]
    assert len(claves) == len(set(claves))
    assert all(c["anios_historia"] == 2 for c in r["cursos"])


def test_filtros_y_exportacion(cliente, tmp_path):
    for anio in (2025, 2026):
        subir(cliente, construir_reporte(tmp_path / f"a{anio}.xlsx", anio=anio, corte=datetime(anio, 3, 1)))
    todos = cliente.get("/api/predicciones").json()
    lab = cliente.get("/api/predicciones", params={"tipo": "Laboratorio", "jornada": "Nocturna"}).json()
    assert {c["tipo"] for c in lab["cursos"]} == {"Laboratorio"}
    assert lab["filtros_ignorados"] == ["jornada"]
    assert len(lab["cursos"]) < len(todos["cursos"])
    csv = cliente.get("/api/export/predicciones.csv")
    assert csv.status_code == 200 and "Predicción 2027" in csv.content.decode("utf-8-sig")


def test_sin_historia_suficiente_con_datos_reales(cliente):
    subir(cliente, REAL_2026, REAL_2025)
    r = cliente.get("/api/predicciones").json()
    assert r["disponible"] is False and r["periodo"] == "PRIMER SEMESTRE"
    assert cliente.get("/api/export/predicciones.csv").status_code == 409


def test_tipo_de_documento_no_soportado(cliente, tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Notas"
    wb.active.append(["Carné", "Nombre", "Nota"])
    wb.save(tmp_path / "notas.xlsx")
    r = subir(cliente, tmp_path / "notas.xlsx").json()["resultados"][0]
    assert r["resultado"] == "rechazado"
    assert "tipo de documento soportado" in r["mensaje"] and "Contadores asignados" in r["mensaje"]
