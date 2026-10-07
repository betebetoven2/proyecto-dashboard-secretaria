"""API: subida, consultas del tablero, vistas del perfil, exportaciones y seguridad."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.app import config
from backend.app.autoprueba import SECCIONES_CLASE, SECCIONES_LAB, construir_reporte

from .conftest import REAL_2025, REAL_2026, REAL_VACIO, subir

ENDPOINTS = ["/api/catalogos", "/api/kpis", "/api/cursos", "/api/ocupacion", "/api/docentes",
             "/api/auxiliares", "/api/heatmap", "/api/salones", "/api/distribucion/modalidad",
             "/api/distribucion/escuela", "/api/secciones", "/api/gestiones", "/api/tiempos",
             "/api/evolucion", "/api/export.csv", "/api/export/gestiones.csv"]


def test_sin_datos(cliente):
    assert cliente.get("/api/salud").json()["snapshots"] == 0
    r = cliente.get("/api/kpis")
    assert r.status_code == 404 and r.json()["detail"] == "sin_snapshots"
    assert cliente.get("/").status_code == 200


def test_subida_multiple_y_resumen(cliente):
    r = subir(cliente, REAL_2026, REAL_2025, REAL_VACIO, REAL_2026)
    assert r.status_code == 200
    assert r.json()["resumen"] == {"aceptado": 2, "reemplazo": 0, "duplicado": 1, "vacio": 1, "rechazado": 0}
    assert len(cliente.get("/api/cargas").json()["cargas"]) == 4


def test_subida_rechaza_basura_sin_romper(cliente, tmp_path):
    (tmp_path / "x.xlsx").write_bytes(b"hola")
    (tmp_path / "foto.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 100)
    r = subir(cliente, tmp_path / "x.xlsx", tmp_path / "foto.png").json()
    assert r["resumen"]["rechazado"] == 2
    assert all(x["mensaje"] for x in r["resultados"])


def test_subida_demasiado_grande(cliente, monkeypatch):
    monkeypatch.setattr(config, "MAX_BYTES", 10_000)
    r = subir(cliente, REAL_2026).json()["resultados"][0]
    assert r["resultado"] == "rechazado" and "máximo" in r["mensaje"]


def test_demasiados_archivos(cliente):
    r = subir(cliente, *([REAL_VACIO] * 31))
    assert r.status_code == 413


def test_todos_los_endpoints_con_y_sin_filtros(cliente):
    subir(cliente, REAL_2026, REAL_2025)
    filtros = [{}, {"escuela": "CIENCIAS Y SISTEMAS"}, {"tipo": "Laboratorio", "jornada": "Nocturna"},
               {"q": "redes"}, {"estado": "Sobrecupo"}, {"estado_gestion": "Pendiente"},
               {"snapshot_id": 2}, {"q": "'; DROP TABLE secciones; --"}, {"escuela": "NO EXISTE"}]
    for f in filtros:
        for e in ENDPOINTS:
            r = cliente.get(e, params=f)
            assert r.status_code == 200, (e, f, r.text[:200])
    assert cliente.get("/api/kpis").json()["secciones"] == 1378     # la tabla sigue ahí


def test_errores_de_parametros(cliente):
    subir(cliente, REAL_2026)
    assert cliente.get("/api/kpis", params={"snapshot_id": 999}).status_code == 404
    assert cliente.get("/api/distribucion/docente").status_code == 400
    assert cliente.get("/api/cursos", params={"orden": "drop"}).status_code == 422
    assert cliente.get("/api/secciones", params={"limite": 0}).status_code == 422
    assert cliente.get("/api/powerbi/inexistente.csv").status_code == 404
    assert cliente.get("/api/no-existe").status_code == 404


def test_coherencia_de_kpis(cliente):
    subir(cliente, REAL_2026)
    k = cliente.get("/api/kpis").json()
    o = cliente.get("/api/ocupacion").json()
    assert sum(e["secciones"] for e in o["por_estado"]) == k["secciones"]
    assert sum(h["secciones"] for h in o["histograma"]) == k["secciones"]
    for col in ("modalidad", "jornada", "escuela", "tipo", "estado_gestion"):
        d = cliente.get(f"/api/distribucion/{col}").json()["datos"]
        assert sum(x["asignados"] for x in d) == k["asignados"] == 40869
    ecys = cliente.get("/api/kpis", params={"escuela": "CIENCIAS Y SISTEMAS"}).json()
    assert 0 < ecys["asignados"] < k["asignados"]
    assert cliente.get("/api/secciones", params={"limite": 5000}).json()["total"] == 1378


def test_estado_de_gestiones(cliente, tmp_path):
    subir(cliente, construir_reporte(tmp_path / "a.xlsx"))
    g = cliente.get("/api/gestiones").json()
    tipos = {t["clave"]: t["secciones"] for t in g["por_tipo"]}
    assert tipos["catedratico"] == 1      # 0781-N con STAFF
    assert tipos["cupo"] == 1             # 0772-B 72/60
    assert tipos["cierre"] == 1           # 0796-C 9/100
    assert tipos["auxiliar"] >= 1         # 0772-B grande sin auxiliar
    assert all(d["codigo"] != "0101" for d in g["detalle"])   # la cerrada no genera gestiones
    estados = {e["estado"]: e["secciones"] for e in g["por_estado"]}
    assert estados["Cerrada"] == 1


def test_tiempos_de_atencion_entre_cortes(cliente, tmp_path):
    subir(cliente, construir_reporte(tmp_path / "a.xlsx", corte=datetime(2026, 9, 1, 8, 0)))
    assert cliente.get("/api/tiempos").json()["disponible"] is False
    # una semana después: a 0781-N ya le asignaron catedrático; 0772-B sigue en sobrecupo
    clase = [dict(s, docente="DOCENTE NUEVO") if s["codigo"] == "0781" else s for s in SECCIONES_CLASE]
    subir(cliente, construir_reporte(tmp_path / "b.xlsx", corte=datetime(2026, 9, 8, 8, 0), clase=clase))
    t = cliente.get("/api/tiempos").json()
    assert t["disponible"] and t["cortes"] == 2
    por = {x["clave"]: x for x in t["por_tipo"]}
    assert por["catedratico"]["resueltas"] == 1 and por["catedratico"]["promedio_dias"] == 7.0
    assert por["catedratico"]["sobre_meta"] == 1          # meta 6 días
    assert por["cupo"]["abiertas"] == 1 and por["cupo"]["resueltas"] == 0
    ev = cliente.get("/api/evolucion").json()
    assert len(ev["cortes"]) == 2 and ev["cambios"] is not None


def test_evolucion_muestra_cambios_por_curso(cliente, tmp_path):
    subir(cliente, construir_reporte(tmp_path / "a.xlsx", corte=datetime(2026, 9, 1)))
    clase = [dict(s, regulares=s["regulares"] + 10) if s["codigo"] == "0770" else s for s in SECCIONES_CLASE]
    subir(cliente, construir_reporte(tmp_path / "b.xlsx", corte=datetime(2026, 9, 8), clase=clase))
    cambios = cliente.get("/api/evolucion").json()["cambios"]["cursos"]
    assert cambios == [{"codigo": "0770", "curso": "INTROD A LA PROGRAMACION Y COMP 1", "antes": 175,
                        "ahora": 185, "delta": 10, "secciones_antes": 2, "secciones_ahora": 2}]


def test_snapshot_por_defecto_y_periodos(cliente):
    subir(cliente, REAL_2026, REAL_2025)
    assert cliente.get("/api/catalogos").json()["snapshot"]["anio"] == 2026
    arbol = cliente.get("/api/periodos").json()["periodos"]
    assert [a["anio"] for a in arbol] == [2026, 2025]


def test_exportacion_csv_y_proteccion_de_formulas(cliente, tmp_path):
    # (un texto que empieza con "=" openpyxl lo guarda como fórmula; se prueban +, - y @)
    clase = [dict(SECCIONES_CLASE[0], docente="@HYPERLINK(\"http://x\")", curso="+1+CMD|calc")]
    subir(cliente, construir_reporte(tmp_path / "a.xlsx", clase=clase, laboratorio=[]))
    r = cliente.get("/api/export.csv")
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")
    texto = r.content.decode("utf-8-sig")
    assert "# Fuente:" in texto and ";" in texto
    assert "'@HYPERLINK" in texto and ";@HYPERLINK" not in texto
    assert "'+1+CMD" in texto


def test_power_bi(cliente):
    subir(cliente, REAL_2026)
    tablas = cliente.get("/api/powerbi").json()["tablas"]
    assert {t["nombre"] for t in tablas} >= {"fact_seccion", "dim_snapshot", "dim_curso", "fact_gestion"}
    r = cliente.get("/api/powerbi/fact_seccion.csv")
    assert len(r.content.decode("utf-8-sig").strip().splitlines()) == 1378 + 1


def test_original_y_eliminacion(cliente):
    subir(cliente, REAL_2026)
    r = cliente.get("/api/snapshots/1/original")
    assert r.status_code == 200 and r.content == REAL_2026.read_bytes()
    assert cliente.delete("/api/snapshots/1").status_code == 200
    assert cliente.get("/api/kpis").status_code == 404
    assert cliente.delete("/api/snapshots/1").status_code == 404


def test_token_de_administracion(cliente, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "secreto-123")
    assert cliente.get("/api/salud").json()["requiere_token"] is True
    assert subir(cliente, REAL_2026).status_code == 401
    assert subir(cliente, REAL_2026, token="otro").status_code == 401
    assert subir(cliente, REAL_2026, token="secreto-123").status_code == 200
    assert cliente.get("/api/kpis").status_code == 200                    # leer no pide token
    assert cliente.delete("/api/snapshots/1").status_code == 401
    assert cliente.post("/api/reprocesar").status_code == 401
    assert cliente.delete("/api/snapshots/1", headers={"X-Admin-Token": "secreto-123"}).status_code == 200


def test_reprocesar_por_api(cliente):
    subir(cliente, REAL_2026, REAL_2025)
    r = cliente.post("/api/reprocesar").json()
    assert r["reprocesados"] == 2
    assert cliente.get("/api/kpis").json()["asignados"] == 40869


@pytest.mark.parametrize("ruta", ["/", "/cargas", "/manual", "/styles.css", "/app.js", "/common.js", "/cargas.js"])
def test_paginas(cliente, ruta):
    assert cliente.get(ruta).status_code == 200
