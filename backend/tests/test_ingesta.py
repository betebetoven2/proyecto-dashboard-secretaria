"""Pipeline de carga: duplicados, reemplazos, cortes, archivo, carpeta vigilada, respaldo."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from backend.app import catalogos, config, db, ingesta, queries, vigilante
from backend.app.autoprueba import SECCIONES_CLASE, construir_reporte

from .conftest import REAL_2025, REAL_2026, REAL_VACIO


def contar(tabla):
    with db.conexion() as con:
        return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


def test_carga_real_y_totales(entorno):
    r = ingesta.procesar_archivo(REAL_2026, "x.xlsx", "prueba")
    assert r.resultado == "aceptado" and r.secciones == 1378 and r.asignados == 40869
    with db.conexion() as con:
        k = queries.kpis(con, queries.Filtros(snapshot_id=r.snapshot_id))
    assert k["asignados"] == 40869 and k["secciones"] == 1378 and k["cerradas"] == 15


def test_duplicado_no_modifica_nada(entorno):
    a = ingesta.procesar_archivo(REAL_2026, "a.xlsx")
    b = ingesta.procesar_archivo(REAL_2026, "otro_nombre.xlsx")
    assert b.resultado == "duplicado" and b.snapshot_id == a.snapshot_id
    assert contar("snapshots") == 1 and contar("secciones") == 1378


def test_vacio_no_crea_snapshot(entorno):
    r = ingesta.procesar_archivo(REAL_VACIO, "v.xlsx")
    assert r.resultado == "vacio" and contar("snapshots") == 0
    assert contar("cargas") == 1


def test_rechazo_queda_en_bitacora_con_motivos(entorno, tmp_path):
    r = ingesta.procesar_archivo(construir_reporte(tmp_path / "m.xlsx", total_pie={"total": 1}), "m.xlsx")
    assert r.resultado == "rechazado" and contar("snapshots") == 0
    with db.conexion() as con:
        c = con.execute("SELECT * FROM cargas").fetchone()
    assert c["resultado"] == "rechazado"
    assert any(m["codigo"] == "control_total" for m in json.loads(c["mensajes_json"]))
    assert not list(config.ARCHIVO_DIR.glob("*/*.xlsx"))  # lo rechazado no se archiva


def test_mismo_corte_reemplaza(entorno, tmp_path):
    a = ingesta.procesar_archivo(construir_reporte(tmp_path / "a.xlsx"), "a.xlsx")
    b = ingesta.procesar_archivo(construir_reporte(tmp_path / "b.xlsx", clase=SECCIONES_CLASE[:2]), "b.xlsx")
    assert b.resultado == "reemplazo" and b.reemplaza_a == a.snapshot_id
    assert contar("snapshots") == 1
    ficha_a = json.loads(next(config.ARCHIVO_DIR.glob(f"*/{a.sha256}.json")).read_text())
    assert ficha_a["estado"] == "reemplazado"


def test_otro_corte_es_otro_snapshot(entorno, tmp_path):
    ingesta.procesar_archivo(construir_reporte(tmp_path / "a.xlsx"), "a.xlsx")
    b = ingesta.procesar_archivo(construir_reporte(tmp_path / "b.xlsx", corte=datetime(2026, 9, 8)), "b.xlsx")
    assert b.resultado == "aceptado" and contar("snapshots") == 2


def test_vigente_es_periodo_mas_reciente_no_ultima_subida(entorno):
    ingesta.procesar_archivo(REAL_2026, "a.xlsx")       # 2026 primer semestre
    ingesta.procesar_archivo(REAL_2025, "b.xlsx")       # se sube después, pero es 2025
    with db.conexion() as con:
        assert queries.snapshot_vigente(con)["anio"] == 2026


def test_original_archivado_con_ficha(entorno):
    r = ingesta.procesar_archivo(REAL_2026, "mi reporte.xlsx", "web")
    xlsx = config.ARCHIVO_DIR / r.sha256[:2] / f"{r.sha256}.xlsx"
    ficha = json.loads(xlsx.with_suffix(".json").read_text())
    assert xlsx.read_bytes() == REAL_2026.read_bytes()
    assert ficha["nombre"] == "mi reporte.xlsx" and ficha["estado"] == "activo"


def test_eliminar_y_reprocesar_no_lo_resucita(entorno):
    a = ingesta.procesar_archivo(REAL_2026, "a.xlsx")
    ingesta.procesar_archivo(REAL_2025, "b.xlsx")
    assert ingesta.eliminar_snapshot(a.snapshot_id)
    assert contar("snapshots") == 1
    ingesta.reprocesar()
    with db.conexion() as con:
        anios = [s["anio"] for s in queries.snapshots(con)]
    assert anios == [2025]
    # volver a subir el eliminado lo restaura
    assert ingesta.procesar_archivo(REAL_2026, "a.xlsx").resultado == "aceptado"


def test_reprocesar_reconstruye_igual(entorno):
    ingesta.procesar_archivo(REAL_2026, "a.xlsx")
    ingesta.procesar_archivo(REAL_2025, "b.xlsx")
    antes = (contar("secciones"), contar("gestiones"), contar("miembros"), contar("bloques"))
    res = ingesta.reprocesar()
    assert all(r.cargado for r in res)
    assert (contar("secciones"), contar("gestiones"), contar("miembros"), contar("bloques")) == antes


def test_cambio_de_esquema_reconstruye_desde_archivo(entorno):
    ingesta.procesar_archivo(REAL_2026, "a.xlsx")
    with db.conexion() as con:
        con.execute("UPDATE meta SET valor = '1' WHERE clave = 'esquema'")
        con.commit()
    ingesta.asegurar_esquema()
    assert contar("snapshots") == 1 and contar("secciones") == 1378


def test_base_borrada_se_reconstruye(entorno):
    ingesta.procesar_archivo(REAL_2026, "a.xlsx")
    for f in config.DATA_DIR.glob("asignados.db*"):
        f.unlink()
    ingesta.asegurar_esquema()
    assert contar("snapshots") == 1


def test_clasificacion_se_acopla_entre_archivos(entorno, monkeypatch, tmp_path):
    """Un reporte sin Escuela/Area se reclasifica cuando llega otro que sí las trae."""
    monkeypatch.setattr(catalogos, "SEMILLA_CSV", tmp_path / "no-existe.csv")
    with db.conexion() as con:
        con.execute("DELETE FROM catalogo_cursos")
        con.commit()
    a = ingesta.procesar_archivo(REAL_2026, "a.xlsx")
    with db.conexion() as con:
        antes = con.execute("SELECT clasificacion_origen, escuela FROM secciones WHERE snapshot_id = ? "
                            "AND codigo = '0960'", (a.snapshot_id,)).fetchone()
    assert antes["clasificacion_origen"] == "heuristica"
    ingesta.procesar_archivo(REAL_2025, "b.xlsx")       # trae 0960 -> CIENCIAS / MATEMATICA
    with db.conexion() as con:
        despues = con.execute("SELECT clasificacion_origen, escuela, area FROM secciones WHERE "
                              "snapshot_id = ? AND codigo = '0960'", (a.snapshot_id,)).fetchone()
    assert despues["clasificacion_origen"] == "catalogo"
    assert (despues["escuela"], despues["area"]) == ("CIENCIAS", "MATEMATICA")


def test_cargas_concurrentes(entorno, tmp_path):
    rutas = [construir_reporte(tmp_path / f"{i}.xlsx", corte=datetime(2026, 9, 1 + i)) for i in range(6)]
    resultados = []
    hilos = [threading.Thread(target=lambda r=r: resultados.append(ingesta.procesar_archivo(r, r.name))) for r in rutas]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(r.resultado for r in resultados) == ["aceptado"] * 6
    assert contar("snapshots") == 6


def test_nombre_seguro():
    assert ingesta.nombre_seguro("../../etc/passwd.xlsx") == "passwd.xlsx"
    assert ingesta.nombre_seguro("C:\\Users\\x\\rep.xlsx") == "rep.xlsx"
    assert ingesta.nombre_seguro("a\x00b\n.xlsx") == "ab.xlsx"
    assert ingesta.nombre_seguro("") == "archivo"


def test_respaldo_y_restauracion(entorno, monkeypatch, tmp_path):
    ingesta.procesar_archivo(REAL_2026, "a.xlsx")
    ingesta.procesar_archivo(REAL_2025, "b.xlsx")
    zip_ = ingesta.respaldo()
    assert zip_.exists() and zip_.parent == config.ENTRADA_DIR / "respaldos"
    # instalación nueva, vacía
    nuevo = tmp_path / "nuevo"
    for k, v in {"DATA_DIR": nuevo, "DB_PATH": nuevo / "a.db", "ARCHIVO_DIR": nuevo / "archivo"}.items():
        monkeypatch.setattr(config, k, v)
    ingesta.asegurar_esquema()
    assert contar("snapshots") == 0
    ingesta.restaurar(zip_)
    assert contar("snapshots") == 2 and contar("secciones") == 1378 + 343


# ═══════════════════════════ carpeta vigilada ═══════════════════════════
def test_carpeta_de_entrada(entorno, tmp_path):
    e = config.ENTRADA_DIR
    (e / "bueno.xlsx").write_bytes(REAL_2026.read_bytes())
    (e / "vacio.xlsx").write_bytes(REAL_VACIO.read_bytes())
    construir_reporte(e / "malo.xlsx", total_pie={"total": 3})
    (e / "~$abierto.xlsx").write_bytes(b"lock")
    (e / "descargando.xlsx.crdownload").write_bytes(b"...")
    viejo = time.time() - 60
    for f in e.iterdir():
        if f.is_file():
            os.utime(f, (viejo, viejo))

    assert vigilante.revisar_una_vez() == []          # primera pasada: solo observa tamaños
    res = vigilante.revisar_una_vez()                   # segunda: tamaños estables -> procesa
    assert sorted(r.resultado for r in res) == ["aceptado", "rechazado", "vacio"]
    assert len(list(config.PROCESADOS_DIR.glob("*bueno.xlsx"))) == 1
    assert len(list(config.RECHAZADOS_DIR.glob("*malo.xlsx"))) == 1
    motivo = next(config.RECHAZADOS_DIR.glob("*malo.xlsx.motivo.txt")).read_text(encoding="utf-8")
    assert "TOTAL" in motivo
    assert (e / "LEEME.txt").exists() and (e / "~$abierto.xlsx").exists()
    assert (e / "descargando.xlsx.crdownload").exists()


def test_carpeta_no_procesa_archivo_que_sigue_creciendo(entorno):
    f = config.ENTRADA_DIR / "copiando.xlsx"
    f.write_bytes(REAL_2026.read_bytes()[:1000])
    vigilante.revisar_una_vez()
    f.write_bytes(REAL_2026.read_bytes()[:5000])        # sigue creciendo
    assert vigilante.revisar_una_vez() == []


def test_copia_incompleta_reciente_se_reintenta(entorno):
    """Un .xlsx a medio copiar (zip truncado) recién modificado no se rechaza: se espera."""
    f = config.ENTRADA_DIR / "a_medias.xlsx"
    datos = REAL_2026.read_bytes()
    f.write_bytes(datos[:20000])
    hace = time.time() - 5
    os.utime(f, (hace, hace))
    vigilante.revisar_una_vez()
    assert vigilante.revisar_una_vez() == [] and f.exists()
    f.write_bytes(datos)                                 # terminó la copia
    os.utime(f, (hace, hace))
    vigilante.revisar_una_vez()
    res = vigilante.revisar_una_vez()
    assert [r.resultado for r in res] == ["aceptado"]


def test_archivo_sin_permiso_de_lectura_no_bloquea_los_demas(entorno):
    if os.geteuid() == 0:
        import pytest
        pytest.skip("root lee cualquier archivo; esta prueba necesita un usuario normal")
    e = config.ENTRADA_DIR
    sin_permiso = e / "a_sin_permiso.xlsx"
    sin_permiso.write_bytes(REAL_2026.read_bytes())
    sin_permiso.chmod(0o000)
    (e / "b_bueno.xlsx").write_bytes(REAL_2025.read_bytes())
    viejo = time.time() - 600
    for f in (sin_permiso, e / "b_bueno.xlsx"):
        os.utime(f, (viejo, viejo))
    vigilante.revisar_una_vez()
    res = {r.archivo: r for r in vigilante.revisar_una_vez()}
    assert res["b_bueno.xlsx"].resultado == "aceptado"
    assert res["a_sin_permiso.xlsx"].resultado == "rechazado"
    assert "permiso" in res["a_sin_permiso.xlsx"].mensaje
