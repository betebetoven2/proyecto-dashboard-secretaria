"""
Autoprueba de la instalación.

    docker compose exec app python -m backend.app.autoprueba

Verifica, sin tocar los datos reales:

1. que las carpetas de datos y de entrada existan y se puedan escribir;
2. que la base abra con el esquema vigente;
3. que el servidor responda;
4. el pipeline completo de carga, en una carpeta temporal y con reportes
   sintéticos generados aquí mismo con el formato real de Centro de Cálculo:
   aceptado, duplicado, reemplazo, otro corte, vacío, totales alterados,
   formato .xls, hoja faltante, columnas faltantes.

Termina con código 0 si todo pasa. También provee `construir_reporte`, que la
suite de pruebas usa para fabricar variantes del archivo.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

ENCABEZADO_BASE = [
    "No", "Codigo", "Nombre", "Seccion", "Edificio", "Salon", "Hora Inicio", "Hora Final",
    "L", "Ma", "Mi", "J", "V", "S", "D", "Horas dia", "Horas semana", "Nombre",
    "Regulares", "Otra Fac.", "Centros Reg.", "Otra Univ.", "No insc.", "Est. Cierre",
    "Otro caso", "Total", "Límite de asignados", "Límite mínimo de asignados",
]
PROC = ["Regulares", "Otra Fac.", "Centros Reg.", "Otra Univ.", "No insc.", "Est. Cierre", "Otro caso"]

SECCIONES_CLASE = [
    dict(codigo="0770", curso="INTROD A LA PROGRAMACION Y COMP 1", seccion="A", edificio="T-3",
         salon=401, hi="07:10", hf="08:50", dias=["L", "Mi", "V"], docente="DOCENTE UNO",
         regulares=88, otra_fac=2, limite=100, limite_min=0, escuela="CIENCIAS Y SISTEMAS",
         area="PROGRAMACION DE SISTEMAS", miembros=[("AUXILIAR UNO", "AUXILIAR DE CATEDRA")]),
    dict(codigo="0772", curso="ESTRUCTURAS DE DATOS", seccion="B", edificio="T-3", salon=402,
         hi="09:00", hf="10:40", dias=["Ma", "J"], docente="DOCENTE DOS", regulares=72,
         limite=60, limite_min=0, escuela="CIENCIAS Y SISTEMAS", area="PROGRAMACION DE SISTEMAS",
         extra=[("10:40", "11:30", ["S"])]),
    dict(codigo="0781", curso="ORG DE LENGUAJES Y COMPILADORES 2", seccion="N", edificio="MEET",
         salon="VIRTUAL", hi="19:00", hf="20:40", dias=["L", "Mi"], docente="STAFF",
         regulares=45, limite=80, limite_min=0, escuela="CIENCIAS Y SISTEMAS",
         area="CIENCIAS DE LA COMPUTACION"),
    dict(codigo="0796", curso="LENGUAJES FORMALES Y DE PROGRAMACION", seccion="C", edificio="S-12",
         salon=105, hi="14:00", hf="15:40", dias=["Ma", "J"], docente="DOCENTE TRES",
         regulares=9, limite=100, limite_min=0, escuela="CIENCIAS Y SISTEMAS",
         area="CIENCIAS DE LA COMPUTACION"),
    dict(codigo="0101", curso="AREA MATEMATICA BASICA 1", seccion="E", edificio="ET",
         salon="CERRADO", hi="07:00", hf="09:00", dias=["L"], docente="STAFF", regulares=0,
         limite=110, limite_min=0, escuela="CIENCIAS", area="MATEMATICA"),
]
SECCIONES_LAB = [
    dict(codigo="0770", curso="INTROD A LA PROGRAMACION Y COMP 1", seccion="A", edificio="T-1",
         salon="LAB-COMP", hi="11:00", hf="12:40", dias=["S"], docente="DOCENTE UNO",
         regulares=85, limite=90, limite_min=0, escuela="CIENCIAS Y SISTEMAS",
         area="PROGRAMACION DE SISTEMAS"),
]


def construir_reporte(ruta: Path, periodo: str = "PRIMER SEMESTRE", anio: int = 2026,
                      corte: datetime = datetime(2026, 9, 1, 8, 0),
                      clase: list[dict] | None = None, laboratorio: list[dict] | None = None,
                      clasificacion: bool = True, total_pie: dict | None = None,
                      sin_pie: bool = False, vacio: bool = False,
                      hojas: tuple[str, ...] = ("Clase", "Laboratorio"),
                      quitar_columnas: tuple[str, ...] = (),
                      columnas_extra: tuple[str, ...] = (), membrete: str | None = None) -> Path:
    """Fabrica un .xlsx con la misma estructura que el reporte real de Centro de Cálculo."""
    clase = SECCIONES_CLASE if clase is None else clase
    laboratorio = SECCIONES_LAB if laboratorio is None else laboratorio
    wb = Workbook()
    wb.remove(wb.active)
    texto = membrete or (f"TOTAL DE ASIGNADOS {periodo} - {anio}, "
                         f"FECHA/HORA: {corte:%d/%m/%Y}  {corte:%H:%M}")
    encabezado = [c for c in ENCABEZADO_BASE if c not in quitar_columnas]
    if clasificacion:
        encabezado += ["Escuela", "Area", "Subarea"]
    encabezado += list(columnas_extra) + ["Nombre miembro", "Tipo miembro"]
    pos = {c: i for i, c in enumerate(encabezado)}
    n_cols = len(encabezado)

    for hoja in hojas:
        ws = wb.create_sheet(hoja)
        filas = [[None] * n_cols for _ in range(6)]
        filas[1][0], filas[2][0], filas[3][0] = "CENTRO DE CÁLCULO", "FACULTAD DE INGENIERÍA", texto
        for f in filas:
            ws.append(f)
        secs = [] if vacio else (clase if hoja == "Clase" else laboratorio)
        if not vacio:
            ws.append(encabezado)
        else:
            ws.append([None] * n_cols)
        suma_total = suma_reg = 0
        n = 0
        for s in secs:
            n += 1
            fila = [None] * n_cols
            proc = {"Regulares": s.get("regulares", 0), "Otra Fac.": s.get("otra_fac", 0)}
            total = s.get("total", sum(proc.values()))
            valores = {
                "No": n, "Codigo": s["codigo"], "Seccion": s["seccion"], "Edificio": s["edificio"],
                "Salon": s["salon"], "Hora Inicio": s["hi"], "Hora Final": s["hf"],
                "Horas dia": 2, "Horas semana": 2 * len(s["dias"]), "Total": total,
                "Límite de asignados": s["limite"], "Límite mínimo de asignados": s.get("limite_min", 0),
                "Escuela": s.get("escuela"), "Area": s.get("area"), "Subarea": None,
            }
            for c in PROC:
                valores[c] = proc.get(c, 0)
            for d in ["L", "Ma", "Mi", "J", "V", "S", "D"]:
                valores[d] = "X" if d in s["dias"] else None
            for c, v in valores.items():
                if c in pos:
                    fila[pos[c]] = v
            nombres = [i for i, c in enumerate(encabezado) if c == "Nombre"]
            if nombres:
                fila[nombres[0]] = s["curso"]
            if len(nombres) > 1:
                fila[nombres[1]] = s["docente"]
            for j, (nom, tip) in enumerate(s.get("miembros", [])[:1]):
                fila[pos["Nombre miembro"]], fila[pos["Tipo miembro"]] = nom, tip
            ws.append(fila)
            suma_total += total if isinstance(total, int) else 0
            suma_reg += proc["Regulares"]
            for hi, hf, dias in s.get("extra", []):  # filas de continuación (otro bloque)
                n += 1
                cont = [None] * n_cols
                for c, v in {"No": n, "Codigo": s["codigo"], "Seccion": s["seccion"],
                             "Edificio": s["edificio"], "Salon": s["salon"], "Hora Inicio": hi,
                             "Hora Final": hf, "Horas dia": 1, "Horas semana": len(dias)}.items():
                    if c in pos:
                        cont[pos[c]] = v
                if nombres:
                    cont[nombres[0]] = s["curso"]
                if len(nombres) > 1:
                    cont[nombres[1]] = s["docente"]
                for d in dias:
                    cont[pos[d]] = "X"
                ws.append(cont)
        ws.append([None] * n_cols)
        ws.append([None] * n_cols)
        if not sin_pie:
            pie = [None] * max(n_cols, 26)
            pie[17], pie[18] = "TOTAL REG: ", (total_pie or {}).get("reg", suma_reg)
            pie[24], pie[25] = "TOTAL: ", (total_pie or {}).get("total", suma_total)
            ws.append(pie)
    ruta = Path(ruta)
    wb.save(ruta)
    return ruta


# ═══════════════════════════════════════════════════════════════════════════
def _chequeo(nombre: str, ok: bool, detalle: str = "") -> bool:
    print(f"  {'✓' if ok else '✗'} {nombre}" + (f" — {detalle}" if detalle else ""))
    return ok


def main() -> int:
    from . import config, db, privilegios

    privilegios.ceder()
    resultados = []
    print("\n[1] Carpetas y base de datos")
    for nombre, carpeta in (("datos", config.DATA_DIR), ("entrada", config.ENTRADA_DIR)):
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            prueba = carpeta / ".autoprueba"
            prueba.write_text("ok")
            prueba.unlink()
            resultados.append(_chequeo(f"carpeta de {nombre} escribible", True, str(carpeta)))
        except OSError as exc:
            resultados.append(_chequeo(f"carpeta de {nombre} escribible", False, str(exc)))
    try:
        from . import ingesta as _ing
        _ing.asegurar_esquema()   # lo mismo que hace el servidor al arrancar
        with db.conexion() as con:
            v = db.version_actual(con)
            n = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] if v else 0
        resultados.append(_chequeo("base de datos", v == db.ESQUEMA_VERSION,
                                   f"esquema v{v}, {n} snapshots cargados"))
    except Exception as exc:  # noqa: BLE001
        resultados.append(_chequeo("base de datos", False, str(exc)))

    print("\n[2] Servidor")
    puerto = os.environ.get("PUERTO_INTERNO", "8000")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        salud = json.loads(opener.open(f"http://127.0.0.1:{puerto}/api/salud", timeout=5).read())
        resultados.append(_chequeo("API responde", salud.get("estado") == "ok",
                                   f"versión {salud.get('version')}"))
    except Exception as exc:  # noqa: BLE001
        resultados.append(_chequeo("API responde", False,
                                   f"{exc} (normal si el servidor no está corriendo)"))

    print("\n[3] Pipeline de carga (en carpeta temporal, sin tocar los datos reales)")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for attr, valor in {"DATA_DIR": tmp / "d", "DB_PATH": tmp / "d" / "a.db",
                            "ARCHIVO_DIR": tmp / "d" / "archivo", "ENTRADA_DIR": tmp / "e",
                            "PROCESADOS_DIR": tmp / "e" / "procesados",
                            "RECHAZADOS_DIR": tmp / "e" / "rechazados"}.items():
            setattr(config, attr, valor)
        from . import ingesta, queries

        ingesta.asegurar_esquema()
        f = tmp / "f"
        f.mkdir()
        casos = [
            ("reporte válido", construir_reporte(f / "a.xlsx"), "aceptado"),
            ("mismo archivo otra vez", f / "a.xlsx", "duplicado"),
            ("mismo corte, contenido distinto",
             construir_reporte(f / "b.xlsx", clase=SECCIONES_CLASE[:3]), "reemplazo"),
            ("mismo período, otro corte",
             construir_reporte(f / "c.xlsx", corte=datetime(2026, 9, 8, 8, 0)), "aceptado"),
            ("reporte vacío", construir_reporte(f / "d.xlsx", vacio=True), "vacio"),
            ("totales del pie alterados",
             construir_reporte(f / "e.xlsx", total_pie={"total": 999999},
                               corte=datetime(2026, 9, 15)), "rechazado"),
            ("falta una columna obligatoria",
             construir_reporte(f / "g.xlsx", quitar_columnas=("Total",),
                               corte=datetime(2026, 9, 16)), "rechazado"),
        ]
        xls = f / "viejo.xls"
        xls.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512)
        casos.append(("formato .xls antiguo", xls, "rechazado"))
        for nombre, ruta, esperado in casos:
            r = ingesta.procesar_archivo(ruta, ruta.name, "autoprueba")
            resultados.append(_chequeo(nombre, r.resultado == esperado,
                                       f"esperado {esperado}, obtenido {r.resultado}"))
        with db.conexion() as con:
            snap = queries.snapshot_vigente(con)
            f_ = queries.Filtros(snapshot_id=snap["id"])
            t = queries.tiempos_atencion(con, f_)
            g = queries.estado_gestiones(con, f_)
        resultados.append(_chequeo("tiempos de atención con 2 cortes", t["disponible"],
                                   f"{t['cortes']} cortes"))
        resultados.append(_chequeo("gestiones derivadas", any(x["secciones"] for x in g["por_tipo"])))
        resp = ingesta.respaldo()
        resultados.append(_chequeo("respaldo", resp.exists() and resp.stat().st_size > 0, resp.name))

    print()
    ok = sum(resultados)
    if ok == len(resultados):
        print(f"Instalación verificada: {ok}/{len(resultados)} comprobaciones correctas.")
        return 0
    print(f"ATENCIÓN: {len(resultados) - ok} de {len(resultados)} comprobaciones fallaron.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
