"""
Configuración y reglas derivadas del snapshot.

Todo lo que aquí aparece es una HEURÍSTICA sobre el reporte "TOTAL DE ASIGNADOS":
el archivo no trae área académica, jornada ni modalidad como columnas, así que se
derivan de código de curso, hora de inicio y edificio. Este es el único archivo que
hay que tocar cuando la Facultad cambie códigos, abra un edificio o se ajuste un
umbral.

Referencia: docs/user-story-map.md, sección 5 (Riesgos y supuestos).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Áreas académicas (heurística por código de curso)
# ---------------------------------------------------------------------------
# Se evalúa en orden: primero códigos exactos, luego rangos. El primer match gana.
# Los códigos exactos existen porque hay cursos de una escuela con código fuera de
# su rango natural: p.ej. 0281 SISTEMAS OPERATIVOS 1 y 0283 ANALISIS Y DISEÑO DE
# SISTEMAS 1 son de Ciencias y Sistemas aunque su código esté en el bloque 02xx,
# que es mayoritariamente Eléctrica.

AREA_CODIGOS_EXACTOS: dict[str, str] = {
    "0090": "Ciencias y Sistemas",
    "0092": "Ciencias y Sistemas",
    "0281": "Ciencias y Sistemas",
    "0283": "Ciencias y Sistemas",
    "0285": "Ciencias y Sistemas",
    "2009": "Ciencias y Sistemas",
    "7999": "Ciencias y Sistemas",
    "0610": "Ciencias y Sistemas",  # INFORMATICA (servicio)
    "0060": "Ciencias y Sistemas",  # TALLER DE SIG
    "0022": "Industrial",
    "0201": "Civil",
    "0073": "Mecánica",
    "0349": "Química",
}

AREA_RANGOS: list[tuple[str, str, str]] = [
    # (desde, hasta, área)   límites inclusivos, comparación de cadenas
    ("0001", "0039", "Social Humanística"),
    ("0006", "0011", "Idiomas"),
    ("0069", "0089", "Área Técnica Complementaria"),
    ("0080", "0084", "Civil"),
    ("0101", "0123", "Matemática"),
    ("0147", "0173", "Física"),
    ("0196", "0198", "Ambiental / Sanitaria"),
    ("0200", "0249", "Eléctrica / Electrónica"),
    ("0250", "0262", "Mecánica de Fluidos / Hidráulica"),
    ("0280", "0289", "Ambiental / Sanitaria"),
    ("0300", "0346", "Civil"),
    ("0348", "0398", "Química"),
    ("0409", "0486", "Ingeniería Química"),
    ("0450", "0460", "Civil"),
    ("0500", "0532", "Mecánica"),
    ("0550", "0585", "Civil"),
    ("0601", "0687", "Industrial"),
    ("0700", "0736", "Industrial"),
    ("0768", "0799", "Ciencias y Sistemas"),
    ("0960", "0991", "Ciencias y Sistemas"),
    ("1000", "1199", "Diplomados"),
    ("2000", "2099", "EPS / Prácticas"),
    ("3000", "3999", "Diplomados"),
    ("5000", "5099", "Técnicos / Construcción"),
    ("7900", "7999", "Seminarios de Investigación"),
    ("9000", "9099", "Programa de Apoyo (PAP)"),
]

AREA_POR_DEFECTO = "Sin clasificar"

#: Área de interés principal del proyecto (la Escuela que solicita el dashboard).
AREA_FOCO = "Ciencias y Sistemas"


def area_de(codigo: str) -> str:
    """Devuelve el área académica inferida para un código de curso."""
    if codigo in AREA_CODIGOS_EXACTOS:
        return AREA_CODIGOS_EXACTOS[codigo]
    for desde, hasta, area in AREA_RANGOS:
        if desde <= codigo <= hasta:
            return area
    return AREA_POR_DEFECTO


# ---------------------------------------------------------------------------
# Modalidad (heurística por edificio)
# ---------------------------------------------------------------------------
EDIFICIOS_VIRTUALES = {"MEET"}
EDIFICIOS_HIBRIDOS = {"HIBR"}
EDIFICIOS_EXTERNOS = {"EPS", "EXT", "0000", None, ""}


def modalidad_de(edificio: str | None) -> str:
    e = (edificio or "").strip().upper()
    if e in EDIFICIOS_VIRTUALES:
        return "Virtual"
    if e in EDIFICIOS_HIBRIDOS:
        return "Híbrido"
    if e in EDIFICIOS_EXTERNOS:
        return "Externo / sin aula"
    return "Presencial"


# ---------------------------------------------------------------------------
# Jornada (heurística por hora de inicio del primer bloque)
# ---------------------------------------------------------------------------
def jornada_de(hora_inicio: str | None) -> str:
    if not hora_inicio:
        return "Sin horario"
    try:
        h = int(str(hora_inicio).split(":")[0])
    except (ValueError, IndexError):
        return "Sin horario"
    if h < 12:
        return "Matutina"
    if h < 17:
        return "Vespertina"
    return "Nocturna"


# ---------------------------------------------------------------------------
# Umbrales de ocupación  (historias R1-04 y R1-05)
# ---------------------------------------------------------------------------
# El archivo trae "Límite mínimo de asignados" en cero en todos los registros del
# snapshot de prueba, así que el umbral de riesgo de cierre NO viene del dato: es
# un parámetro que la Secretaría debe poder ajustar. La UI lo declara como tal.

UMBRAL_RIESGO_CIERRE = 0.20   # < 20% de su cupo -> candidata a cierre / fusión
UMBRAL_SALUDABLE_BAJO = 0.50  # 20%-50% -> holgada
UMBRAL_LLENA = 0.85           # 85%-100% -> por llenarse

ESTADOS = [
    "Sobrecupo",
    "Por llenarse",
    "Saludable",
    "Holgada",
    "Riesgo de cierre",
    "Sin asignados",
    "Sin límite definido",
]


def estado_de(total: int, limite: int) -> str:
    """Clasifica una sección según su ocupación. Ver historia R1-04."""
    if total == 0:
        return "Sin asignados"
    if not limite:
        return "Sin límite definido"
    ocup = total / limite
    if ocup > 1.0:
        return "Sobrecupo"
    if ocup >= UMBRAL_LLENA:
        return "Por llenarse"
    if ocup >= UMBRAL_SALUDABLE_BAJO:
        return "Saludable"
    if ocup >= UMBRAL_RIESGO_CIERRE:
        return "Holgada"
    return "Riesgo de cierre"


DIAS = ["L", "Ma", "Mi", "J", "V", "S", "D"]
DIAS_NOMBRE = {
    "L": "Lunes", "Ma": "Martes", "Mi": "Miércoles", "J": "Jueves",
    "V": "Viernes", "S": "Sábado", "D": "Domingo",
}

#: Columnas de procedencia del estudiante. Existen en el reporte pero vienen en
#: cero en el snapshot de prueba; se conservan en el modelo y la UI las oculta
#: cuando la suma es cero (ver user-story-map.md §1).
COLUMNAS_PROCEDENCIA = [
    ("regulares", "Regulares"),
    ("otra_fac", "Otra Facultad"),
    ("centros_reg", "Centros Regionales"),
    ("otra_univ", "Otra Universidad"),
    ("no_insc", "No inscritos"),
    ("est_cierre", "Estudiantes de cierre"),
    ("otro_caso", "Otro caso"),
]
