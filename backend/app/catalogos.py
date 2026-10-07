"""
Catálogos de referencia: períodos académicos y clasificación de cursos.

Períodos
--------
Los 21 períodos son los que ofrece el sistema de Centro de Cálculo en el diálogo
«Contadores asignados (Condensado)». El reporte trae el NOMBRE del período en el
membrete (p. ej. «TOTAL DE ASIGNADOS VACACIONES DEL PRIMER SEMESTRE - 2025»); aquí
se resuelve a su código y a un orden cronológico dentro del año, que es lo que
permite elegir "el período más reciente" sin depender de la fecha de descarga.

Clasificación de cursos (escuela / área / subárea)
--------------------------------------------------
Algunas emisiones del reporte traen las columnas Escuela, Area y Subarea; otras
no. Para que todos los snapshots se puedan filtrar igual, la clasificación se
resuelve con esta prioridad:

  1. la columna del propio archivo, si existe;
  2. el catálogo aprendido (tabla `catalogo_cursos`): se siembra con
     `catalogo/cursos_semilla.csv` (140 cursos tomados de un reporte real) y se
     actualiza con cada archivo que trae las columnas;
  3. una heurística por rango de código, calibrada contra ese catálogo real;
  4. "SIN CLASIFICAR".

Cada sección guarda de dónde salió su clasificación (`clasificacion_origen`), y
la interfaz marca como «inferida» la que no viene del archivo.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import config


def normalizar(texto: str | None) -> str:
    """Mayúsculas, sin tildes, espacios simples. Para comparar textos del reporte."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().upper()


# ═══════════════════════════════════════════════════════════════════════════
# Períodos
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Periodo:
    codigo: str
    nombre: str
    semestre: int | None   # 1, 2 o None
    orden: int             # orden cronológico dentro del año
    regular: bool          # semestre ordinario (los demás son vacaciones, exámenes…)


PERIODOS: list[Periodo] = [
    Periodo("20", "EXAMEN UBICACIÓN IDIOMA TÉCNICO - PRIMER SEMESTRE", 1, 5, False),
    Periodo("01", "PRIMER SEMESTRE", 1, 10, True),
    Periodo("16", "PRIMER INTENSIVO - PRIMER SEMESTRE", 1, 11, False),
    Periodo("17", "SEGUNDO INTENSIVO - PRIMER SEMESTRE", 1, 12, False),
    Periodo("14", "FINALES DEL PRIMER SEMESTRE", 1, 13, False),
    Periodo("02", "VACACIONES DEL PRIMER SEMESTRE", 1, 14, False),
    Periodo("03", "PRIMERA RETRASADA DEL PRIMER SEMESTRE", 1, 15, False),
    Periodo("04", "SEGUNDA RETRASADA DEL PRIMER SEMESTRE", 1, 16, False),
    Periodo("09", "SUFICIENCIA PRIMER SEMESTRE", 1, 17, False),
    Periodo("21", "EXAMEN UBICACIÓN IDIOMA TÉCNICO - SEGUNDO SEMESTRE", 2, 25, False),
    Periodo("05", "SEGUNDO SEMESTRE", 2, 30, True),
    Periodo("18", "PRIMER INTENSIVO - SEGUNDO SEMESTRE", 2, 31, False),
    Periodo("19", "SEGUNDO INTENSIVO - SEGUNDO SEMESTRE", 2, 32, False),
    Periodo("15", "FINALES DEL SEGUNDO SEMESTRE", 2, 33, False),
    Periodo("06", "VACACIONES DEL SEGUNDO SEMESTRE", 2, 34, False),
    Periodo("07", "PRIMERA RETRASADA DEL SEGUNDO SEMESTRE", 2, 35, False),
    Periodo("08", "SEGUNDA RETRASADA DEL SEGUNDO SEMESTRE", 2, 36, False),
    Periodo("10", "SUFICIENCIA SEGUNDO SEMESTRE", 2, 37, False),
    Periodo("11", "EQUIVALENCIA SIN FECHA", None, 90, False),
    Periodo("12", "CODIGO SIN UTILIZAR", None, 91, False),
    Periodo("13", "SIN PERIODO PARA EXAMENES GENERALES", None, 92, False),
]
_POR_NOMBRE = {normalizar(p.nombre): p for p in PERIODOS}
_POR_CODIGO = {p.codigo: p for p in PERIODOS}


def periodo_por_nombre(nombre: str | None) -> Periodo | None:
    return _POR_NOMBRE.get(normalizar(nombre))


def periodo_por_codigo(codigo: str | None) -> Periodo | None:
    return _POR_CODIGO.get(str(codigo or "").zfill(2))


# ═══════════════════════════════════════════════════════════════════════════
# Clasificación de cursos
# ═══════════════════════════════════════════════════════════════════════════
SEMILLA_CSV = Path(__file__).resolve().parent / "catalogo" / "cursos_semilla.csv"


def cargar_semilla() -> list[dict]:
    if not SEMILLA_CSV.exists():
        return []
    with SEMILLA_CSV.open(encoding="utf-8", newline="") as f:
        return [
            {k: (v or "").strip() for k, v in fila.items()}
            for fila in csv.DictReader(f)
            if (fila.get("codigo") or "").strip()
        ]


# Heurística por rango de código. Calibrada contra el catálogo real (ver
# tests/test_catalogos.py, que mide su acierto). Solo se incluyen rangos con
# evidencia; lo que no tiene evidencia queda SIN CLASIFICAR en lugar de adivinar.
#   (desde, hasta, escuela, área)  — límites inclusivos, comparación de texto
_RANGOS: list[tuple[str, str, str, str]] = [
    ("0006", "0011", "CIENCIAS", "IDIOMA TECNICO"),
    ("0001", "0019", "CIENCIAS", "SOCIAL HUMANISTICA"),
    ("0039", "0039", "CIENCIAS", "SOCIAL HUMANISTICA"),
    ("0069", "0074", "CIENCIAS", "TECNICA COMPLEMENTARIA"),
    ("0080", "0084", "CIVIL", "TOPOGRAFIA Y TRANSPORTES"),
    ("0090", "0092", "CIENCIAS Y SISTEMAS", "PROGRAMACION"),
    ("0101", "0123", "CIENCIAS", "MATEMATICA"),
    ("0147", "0173", "CIENCIAS", "FISICA"),
    ("0200", "0210", "MECANICA ELECTRICA", "CC. BASICAS Y ELECTROTECNIA"),
    ("0211", "0231", "MECANICA ELECTRICA", "POTENCIA"),
    ("0232", "0249", "MECANICA ELECTRICA", "ELECTRONICA"),
    ("0250", "0262", "CIVIL", "HIDRAULICA"),
    ("0281", "0281", "CIENCIAS Y SISTEMAS", "CIENCIAS DE LA COMPUTACION"),
    ("0283", "0283", "CIENCIAS Y SISTEMAS", "DESARROLLO DE SOFTWARE"),
    ("0285", "0285", "CIENCIAS Y SISTEMAS", "CIENCIAS DE LA COMPUTACION"),
    ("0280", "0284", "E.R.I.S.", "PREGRADO"),
    ("0300", "0346", "CIVIL", "ESTRUCTURAS"),
    ("0348", "0349", "CIENCIAS", "QUIMICA GENERAL"),
    ("0350", "0388", "QUIMICA", "QUIMICA"),
    ("0390", "0396", "MECANICA", "TERMICA"),
    ("0398", "0442", "QUIMICA", "OPERACIONES UNITARIAS"),
    ("0452", "0452", "MECANICA", "MATERIALES DE INGENIERIA"),
    ("0450", "0460", "CIVIL", "MATERIALES DE CONSTRUCCION Y OBRAS CIVILES"),
    ("0462", "0462", "MECANICA ELECTRICA", "CC. BASICAS Y ELECTROTECNIA"),
    ("0500", "0532", "MECANICA", "DISENO"),
    ("0550", "0585", "CIVIL", "TOPOGRAFIA Y TRANSPORTES"),
    ("0601", "0687", "MECANICA INDUSTRIAL", "INGENIERIA ADMINISTRATIVA"),
    ("0710", "0712", "CIVIL", "PLANEAMIENTO"),
    ("0720", "0729", "CIENCIAS Y SISTEMAS", "METODOLOGIA DE SISTEMAS"),
    ("0732", "0736", "CIENCIAS", "ESTADISTICA"),
    ("0770", "0799", "CIENCIAS Y SISTEMAS", "CIENCIAS DE LA COMPUTACION"),
    ("0960", "0962", "CIENCIAS", "MATEMATICA"),
    ("0964", "0975", "CIENCIAS Y SISTEMAS", "CIENCIAS DE LA COMPUTACION"),
    ("0980", "0991", "MECANICA ELECTRICA", "ELECTRONICA"),
    ("9000", "9099", "CIENCIAS", "PREINGENIERIA"),
    # Programas que no pertenecen a una escuela: se agrupan con un nombre propio
    # en lugar de quedar sin clasificar.
    ("1000", "1199", "DIPLOMADOS", "DIPLOMADO"),
    ("5000", "5099", "PROGRAMAS TECNICOS", "TECNICO"),
]

# Prácticas y seminarios de EPS: la escuela viene en el NOMBRE del curso.
_RANGOS_POR_NOMBRE = [("2000", "2099"), ("7900", "7999")]
_PALABRAS_ESCUELA = [  # el orden importa: lo más específico primero
    ("SISTEMAS", "CIENCIAS Y SISTEMAS"),
    ("MEC. ELEC", "MECANICA ELECTRICA"),
    ("MECANICA ELECTRICA", "MECANICA ELECTRICA"),
    ("MEC. INDU", "MECANICA INDUSTRIAL"),
    ("MECANICA INDUSTRIAL", "MECANICA INDUSTRIAL"),
    ("ELECTRONICA", "MECANICA ELECTRICA"),
    ("ELECTRICA", "MECANICA ELECTRICA"),
    ("INDUSTRIAL", "MECANICA INDUSTRIAL"),
    ("MECANICA", "MECANICA"),
    ("CIVIL", "CIVIL"),
    ("QUIMICA", "QUIMICA"),
    ("AMBIENTAL", "E.R.I.S."),
]


def codigo_base(codigo: str) -> str | None:
    """Los cursos «(DIPLOMADO)» 3xxx son la versión del curso 0xxx (3116 ↔ 0116
    Matemática Aplicada 3, 3662 ↔ 0662 Legislación 1): comparten escuela."""
    if len(codigo) == 4 and codigo.startswith("3") and codigo.isdigit():
        return "0" + codigo[1:]
    return None


def clasificacion_heuristica(codigo: str, curso: str | None) -> tuple[str, str] | None:
    """(escuela, área) inferidas, o None si no hay evidencia suficiente."""
    base = codigo_base(codigo)
    if base:
        return clasificacion_heuristica(base, curso) or ("DIPLOMADOS", "DIPLOMADO")
    for desde, hasta in _RANGOS_POR_NOMBRE:
        if desde <= codigo <= hasta:
            nombre = normalizar(curso)
            for palabra, escuela in _PALABRAS_ESCUELA:
                if palabra in nombre:
                    area = "PRACTICAS" if codigo < "7000" else "SEMINARIO DE INVESTIGACION"
                    return escuela, area
            if desde == "2000":  # prácticas iniciales / intermedias: de toda la Facultad
                return "FACULTAD (GENERAL)", "PRACTICAS"
            return None
    for desde, hasta, escuela, area in _RANGOS:
        if desde <= codigo <= hasta:
            return escuela, area
    return None
