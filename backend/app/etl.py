"""
ETL del reporte "TOTAL DE ASIGNADOS" (xlsx) -> SQLite.

Reglas de limpieza (todas verificadas contra el archivo real, ver
docs/user-story-map.md §5):

 1. El encabezado real no está en la fila 1: se localiza buscando la fila cuya
    primera celda es "No". Arriba de ella hay membrete institucional y la línea
    con el período y la fecha/hora de corte, que se conservan como metadatos.
 2. El encabezado tiene nombres repetidos ("Nombre" es curso y también
    catedrático; "Nombre miembro"/"Tipo miembro" se repite por cada auxiliar).
    Se resuelve por posición, no por nombre.
 3. UNA SECCIÓN PUEDE OCUPAR VARIAS FILAS. Las filas de continuación traen otro
    bloque de horario y dejan vacía la columna "Total". Si se cuenta por fila,
    los totales se inflan (1,378 filas frente a 1,378 "secciones" cuando en
    realidad son 926 + 452). El total se toma solo de la fila principal y los
    horarios se acumulan como bloques.
 4. Texto corrupto: la Ñ llega como "\\" en algunos nombres (DISE\\O). Se
    corrige y se normalizan espacios dobles en nombres de personas.
 5. Las columnas de procedencia se conservan aunque vengan en cero.
 6. Si el encabezado no coincide con el esperado, el ETL falla con un mensaje
    claro en lugar de cargar datos mal alineados en silencio.

El ETL es idempotente por archivo: recargar el mismo nombre reemplaza su
snapshot.
"""

from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

try:
    from . import config, db
except ImportError:  # ejecución directa: python backend/app/etl.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.app import config, db

HOJAS = {"Clase": "Clase", "Laboratorio": "Laboratorio"}

ENCABEZADO_ESPERADO = [
    "No", "Codigo", "Nombre", "Seccion", "Edificio", "Salon",
    "Hora Inicio", "Hora Final", "L", "Ma", "Mi", "J", "V", "S", "D",
    "Horas dia", "Horas semana", "Nombre",
    "Regulares", "Otra Fac.", "Centros Reg.", "Otra Univ.", "No insc.",
    "Est. Cierre", "Otro caso", "Total",
    "Límite de asignados", "Límite mínimo de asignados",
]
COL = {nombre: i for i, nombre in enumerate(ENCABEZADO_ESPERADO)}
COL["Curso"] = 2
COL["Docente"] = 17
PRIMERA_COL_MIEMBRO = 28  # a partir de aquí van pares (Nombre miembro, Tipo miembro)


class FormatoInesperado(RuntimeError):
    """El archivo no tiene la estructura del reporte de asignados."""


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #
def limpiar_texto(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("\\", "Ñ")           # DISE\O -> DISEÑO
    s = re.sub(r"\s+", " ", s)          # espacios dobles en nombres de personas
    s = unicodedata.normalize("NFC", s)
    return s or None


def limpiar_entero(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(float(str(v).replace(",", "")))
    except ValueError:
        return 0


def limpiar_decimal(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0.0


def limpiar_hora(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})[:.](\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    return s or None


def limpiar_codigo(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if s.isdigit():
        return s.zfill(4)
    return s


def limpiar_salon(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


# --------------------------------------------------------------------------- #
# Lectura del archivo
# --------------------------------------------------------------------------- #
def _localizar_encabezado(ws) -> tuple[int, list]:
    for i, fila in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
        if fila and str(fila[0]).strip() if fila[0] else False:
            if str(fila[0]).strip() == "No":
                return i, list(fila)
    raise FormatoInesperado(
        f"En la hoja '{ws.title}' no se encontró la fila de encabezado "
        f"(se busca una fila cuya primera celda sea 'No' en las primeras 20 filas)."
    )


def _validar_encabezado(hoja: str, fila_encabezado: list) -> None:
    encontrados = [limpiar_texto(c) for c in fila_encabezado[: len(ENCABEZADO_ESPERADO)]]
    for i, esperado in enumerate(ENCABEZADO_ESPERADO):
        if (encontrados[i] or "") != esperado:
            raise FormatoInesperado(
                f"Hoja '{hoja}', columna {i + 1}: se esperaba '{esperado}' y se encontró "
                f"'{encontrados[i]}'. El formato del reporte cambió; revise el ETL antes "
                f"de cargar este archivo."
            )


def _leer_metadatos(ws) -> dict:
    """Extrae período y fecha de corte del membrete del reporte."""
    meta = {"encabezado": None, "periodo": None, "anio": None, "fecha_corte": None}
    for fila in ws.iter_rows(min_row=1, max_row=8, values_only=True):
        txt = limpiar_texto(fila[0]) if fila else None
        if txt and "TOTAL DE ASIGNADOS" in txt.upper():
            meta["encabezado"] = txt
            m = re.search(r"TOTAL DE ASIGNADOS\s+(.*?),\s*FECHA/HORA:\s*(.*)$", txt, re.I)
            if m:
                meta["periodo"] = m.group(1).strip()
                anio = re.search(r"(\d{4})", m.group(1))
                if anio:
                    meta["anio"] = int(anio.group(1))
                fh = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", m.group(2).strip())
                if fh:
                    d, mo, y, h, mi = fh.groups()
                    meta["fecha_corte"] = f"{y}-{mo}-{d}T{h}:{mi}:00"
            break
    return meta


def _parsear_hoja(ws, tipo: str) -> list[dict]:
    fila_enc, encabezado = _localizar_encabezado(ws)
    _validar_encabezado(ws.title, encabezado)

    secciones: list[dict] = []
    actual: dict | None = None

    for n_fila, r in enumerate(
        ws.iter_rows(min_row=fila_enc + 1, values_only=True), start=fila_enc + 1
    ):
        codigo = limpiar_codigo(r[COL["Codigo"]])
        if not codigo:
            continue  # filas en blanco o pies de página

        seccion = limpiar_texto(r[COL["Seccion"]])
        trae_total = r[COL["Total"]] is not None
        es_continuacion = (
            not trae_total
            and actual is not None
            and actual["codigo"] == codigo
            and actual["seccion"] == seccion
        )

        dias = [d for d, f in zip(config.DIAS, r[COL["L"]: COL["D"] + 1]) if limpiar_texto(f)]
        h_ini, h_fin = limpiar_hora(r[COL["Hora Inicio"]]), limpiar_hora(r[COL["Hora Final"]])

        if es_continuacion:
            # Regla 3: otro bloque de horario de la MISMA sección.
            for d in dias:
                actual["bloques"].append({"dia": d, "hora_inicio": h_ini, "hora_fin": h_fin})
            actual["horas_semana"] += limpiar_decimal(r[COL["Horas semana"]])
            continue

        total = limpiar_entero(r[COL["Total"]])
        limite = limpiar_entero(r[COL["Límite de asignados"]])
        edificio = limpiar_texto(r[COL["Edificio"]])

        actual = {
            "tipo": tipo,
            "codigo": codigo,
            "curso": limpiar_texto(r[COL["Curso"]]) or "(sin nombre)",
            "seccion": seccion,
            "area": config.area_de(codigo),
            "edificio": edificio,
            "salon": limpiar_salon(r[COL["Salon"]]),
            "modalidad": config.modalidad_de(edificio),
            "jornada": config.jornada_de(h_ini),
            "hora_inicio": h_ini,
            "hora_fin": h_fin,
            "horas_dia": limpiar_decimal(r[COL["Horas dia"]]),
            "horas_semana": limpiar_decimal(r[COL["Horas semana"]]),
            "docente": limpiar_texto(r[COL["Docente"]]),
            "regulares": limpiar_entero(r[COL["Regulares"]]),
            "otra_fac": limpiar_entero(r[COL["Otra Fac."]]),
            "centros_reg": limpiar_entero(r[COL["Centros Reg."]]),
            "otra_univ": limpiar_entero(r[COL["Otra Univ."]]),
            "no_insc": limpiar_entero(r[COL["No insc."]]),
            "est_cierre": limpiar_entero(r[COL["Est. Cierre"]]),
            "otro_caso": limpiar_entero(r[COL["Otro caso"]]),
            "total": total,
            "limite": limite,
            "limite_min": limpiar_entero(r[COL["Límite mínimo de asignados"]]),
            "ocupacion": (total / limite) if limite else None,
            "estado": config.estado_de(total, limite),
            "fila_origen": n_fila,
            "bloques": [{"dia": d, "hora_inicio": h_ini, "hora_fin": h_fin} for d in dias],
            "miembros": [],
        }

        # Miembros de la terna (auxiliares). El reporte repite el mismo nombre en
        # ambas columnas de miembro en 9 secciones del snapshot de prueba, así que
        # se deduplica por sección para no inflar la cobertura de auxiliares.
        i, vistos = PRIMERA_COL_MIEMBRO, set()
        while i + 1 < len(r):
            nombre, tipo_m = limpiar_texto(r[i]), limpiar_texto(r[i + 1])
            if nombre and nombre not in vistos:
                vistos.add(nombre)
                actual["miembros"].append({"nombre": nombre, "tipo": tipo_m or "SIN TIPO"})
            i += 2

        secciones.append(actual)

    return secciones


# --------------------------------------------------------------------------- #
# Carga
# --------------------------------------------------------------------------- #
def cargar_archivo(ruta: Path, con=None) -> dict:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(ruta)

    propia = con is None
    con = con or db.connect()
    db.init_schema(con)

    wb = load_workbook(ruta, read_only=True, data_only=True)
    faltantes = [h for h in HOJAS if h not in wb.sheetnames]
    if faltantes:
        raise FormatoInesperado(
            f"El archivo no trae la(s) hoja(s) {faltantes}. Hojas encontradas: {wb.sheetnames}"
        )

    meta = _leer_metadatos(wb[next(iter(HOJAS))])
    secciones: list[dict] = []
    for hoja, tipo in HOJAS.items():
        secciones.extend(_parsear_hoja(wb[hoja], tipo))
    wb.close()

    digest = hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]
    total_asignados = sum(s["total"] for s in secciones)

    cur = con.cursor()
    cur.execute("DELETE FROM snapshots WHERE archivo = ?", (ruta.name,))
    cur.execute(
        """INSERT INTO snapshots
           (archivo, encabezado, periodo, anio, fecha_corte, cargado_en,
            total_secciones, total_asignados, hash_archivo)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            ruta.name, meta["encabezado"], meta["periodo"], meta["anio"],
            meta["fecha_corte"], datetime.now(timezone.utc).isoformat(timespec="seconds"),
            len(secciones), total_asignados, digest,
        ),
    )
    snap_id = cur.lastrowid

    campos = [
        "snapshot_id", "tipo", "codigo", "curso", "seccion", "area", "edificio", "salon",
        "modalidad", "jornada", "hora_inicio", "hora_fin", "dias", "horas_dia",
        "horas_semana", "docente", "regulares", "otra_fac", "centros_reg", "otra_univ",
        "no_insc", "est_cierre", "otro_caso", "total", "limite", "limite_min",
        "ocupacion", "estado", "fila_origen",
    ]
    sql = f"INSERT INTO secciones ({','.join(campos)}) VALUES ({','.join('?' * len(campos))})"

    for s in secciones:
        dias_unicos = sorted({b["dia"] for b in s["bloques"]}, key=config.DIAS.index)
        cur.execute(sql, (
            snap_id, s["tipo"], s["codigo"], s["curso"], s["seccion"], s["area"],
            s["edificio"], s["salon"], s["modalidad"], s["jornada"], s["hora_inicio"],
            s["hora_fin"], ",".join(dias_unicos), s["horas_dia"], s["horas_semana"],
            s["docente"], s["regulares"], s["otra_fac"], s["centros_reg"], s["otra_univ"],
            s["no_insc"], s["est_cierre"], s["otro_caso"], s["total"], s["limite"],
            s["limite_min"], s["ocupacion"], s["estado"], s["fila_origen"],
        ))
        sec_id = cur.lastrowid
        if s["bloques"]:
            cur.executemany(
                "INSERT INTO bloques (seccion_id, dia, hora_inicio, hora_fin) VALUES (?,?,?,?)",
                [(sec_id, b["dia"], b["hora_inicio"], b["hora_fin"]) for b in s["bloques"]],
            )
        if s["miembros"]:
            cur.executemany(
                "INSERT INTO miembros (seccion_id, nombre, tipo) VALUES (?,?,?)",
                [(sec_id, m["nombre"], m["tipo"]) for m in s["miembros"]],
            )

    con.commit()
    resumen = {
        "snapshot_id": snap_id,
        "archivo": ruta.name,
        "periodo": meta["periodo"],
        "fecha_corte": meta["fecha_corte"],
        "secciones": len(secciones),
        "asignados": total_asignados,
        "clase": sum(1 for s in secciones if s["tipo"] == "Clase"),
        "laboratorio": sum(1 for s in secciones if s["tipo"] == "Laboratorio"),
        "bloques": sum(len(s["bloques"]) for s in secciones),
        "miembros": sum(len(s["miembros"]) for s in secciones),
    }
    if propia:
        con.close()
    return resumen


def cargar_carpeta(carpeta: Path | None = None) -> list[dict]:
    carpeta = Path(carpeta or db.SNAPSHOTS_DIR)
    archivos = sorted(p for p in carpeta.glob("*.xlsx") if not p.name.startswith("~$"))
    if not archivos:
        print(f"[etl] No hay .xlsx en {carpeta}")
        return []
    con = db.connect()
    resultados = [cargar_archivo(p, con) for p in archivos]
    con.close()
    return resultados


if __name__ == "__main__":
    rutas = [Path(a) for a in sys.argv[1:]]
    salidas = (
        [cargar_archivo(r) for r in rutas] if rutas else cargar_carpeta()
    )
    for s in salidas:
        print(
            f"[etl] {s['archivo']}: {s['secciones']} secciones "
            f"({s['clase']} clase / {s['laboratorio']} laboratorio), "
            f"{s['asignados']:,} asignados, {s['bloques']} bloques de horario, "
            f"{s['miembros']} miembros de terna · corte {s['fecha_corte']}"
        )
