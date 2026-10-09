"""
Configuración del sistema.

Dos tipos de valores viven aquí:

1. **Parámetros de instalación** (rutas, token, límites): se leen de variables de
   entorno para que Docker los controle desde `docker-compose.yml` / `.env` sin
   tocar código.
2. **Reglas de negocio** derivadas del reporte (modalidad, jornada, umbrales,
   reglas de gestiones): son heurísticas documentadas. El archivo no trae esos
   conceptos como columnas; se infieren. Este es el único archivo que hay que
   editar cuando la Facultad cambie un edificio, un umbral o una regla.

Referencia funcional: docs/user-story-map.md
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_int(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


def _env_float(nombre: str, defecto: float) -> float:
    try:
        return float(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


# ═══════════════════════════════════════════════════════════════════════════
# 1. Parámetros de instalación
# ═══════════════════════════════════════════════════════════════════════════
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

#: Carpeta de datos. En Docker es el volumen /data. Fuera de Docker, ./datos
DATA_DIR = Path(os.environ.get("DATA_DIR", RAIZ_PROYECTO / "datos")).resolve()

#: Base SQLite: réplica DERIVADA. Se puede borrar y reconstruir desde ARCHIVO_DIR.
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "asignados.db"))

#: Originales aceptados, guardados por su huella SHA-256. Es la FUENTE DE VERDAD:
#: con esta carpeta se reconstruye la base completa (`python -m backend.app.etl reprocesar`).
ARCHIVO_DIR = Path(os.environ.get("ARCHIVO_DIR", DATA_DIR / "archivo"))

#: Carpeta vigilada: todo .xlsx que se copie aquí se carga solo.
ENTRADA_DIR = Path(os.environ.get("ENTRADA_DIR", DATA_DIR / "entrada"))
PROCESADOS_DIR = ENTRADA_DIR / "procesados"
RECHAZADOS_DIR = ENTRADA_DIR / "rechazados"

#: Segundos entre revisiones de la carpeta de entrada. 0 desactiva el vigilante.
INTERVALO_ENTRADA_SEG = _env_int("INTERVALO_ENTRADA_SEG", 10)

#: Si se define, subir y borrar exige este token (cabecera X-Admin-Token).
#: Vacío = sin restricción (adecuado solo dentro de la red interna).
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()

#: Tamaño máximo por archivo subido. El reporte real más grande pesa ~165 KB.
MAX_MB = _env_float("MAX_MB", 25.0)
MAX_BYTES = int(MAX_MB * 1024 * 1024)

#: Tope de tamaño descomprimido (un .xlsx es un zip): defensa contra zip bombs.
MAX_DESCOMPRIMIDO_BYTES = _env_int("MAX_DESCOMPRIMIDO_MB", 300) * 1024 * 1024

#: Zona horaria de las fechas de corte del reporte.
ZONA_HORARIA = os.environ.get("TZ", "America/Guatemala") or "America/Guatemala"

#: Meta institucional de días para atender una gestión (vista "tiempos de atención").
#: El boceto del perfil usa 6 días como ejemplo; ajustable por la Secretaría.
META_DIAS_ATENCION = _env_float("META_DIAS_ATENCION", 6.0)

#: Predicciones: amortiguamiento de la tendencia (0.8–0.98) y nivel del intervalo.
PRED_AMORTIGUAMIENTO = _env_float("PRED_AMORTIGUAMIENTO", 0.9)
PRED_NIVEL = _env_float("PRED_NIVEL", 0.8)

VERSION = "1.1.0"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Reglas de negocio
# ═══════════════════════════════════════════════════════════════════════════

#: Escuela que solicita el tablero (botón "Solo Ciencias y Sistemas").
ESCUELA_FOCO = "CIENCIAS Y SISTEMAS"
SIN_CLASIFICAR = "SIN CLASIFICAR"

# --- Modalidad (por edificio) ------------------------------------------------
EDIFICIOS_VIRTUALES = {"MEET"}
EDIFICIOS_HIBRIDOS = {"HIBR"}
EDIFICIOS_EXTERNOS = {"EPS", "EXT"}
#: Valores que el reporte usa cuando NO hay salón asignado.
SALONES_SIN_ASIGNAR = {"", "0", "0000", "00000000", "SIN SALON", "SIN SALÓN"}
EDIFICIOS_SIN_ASIGNAR = {"", "0000"}
#: Salón que marca una sección cerrada (va con edificio ET y catedrático STAFF).
SALON_CERRADO = "CERRADO"
#: Marcador del reporte cuando la sección no tiene catedrático asignado.
DOCENTES_SIN_ASIGNAR = {"", "STAFF", "SIN ASIGNAR"}


def modalidad_de(edificio: str | None, salon: str | None) -> str:
    e = (edificio or "").strip().upper()
    s = (salon or "").strip().upper()
    if s == SALON_CERRADO:
        return "Cerrada"
    if e in EDIFICIOS_VIRTUALES:
        return "Virtual"
    if e in EDIFICIOS_HIBRIDOS:
        return "Híbrido"
    if e in EDIFICIOS_EXTERNOS:
        return "Externo"
    if e in EDIFICIOS_SIN_ASIGNAR or s in SALONES_SIN_ASIGNAR:
        return "Sin salón"
    return "Presencial"


# --- Jornada (por hora de inicio del primer bloque) ----------------------------
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


# --- Ocupación -----------------------------------------------------------------
#: Cuando el reporte trae "Límite mínimo de asignados" > 0, ese es el umbral de
#: riesgo de cierre. Si viene en 0 (como en el primer semestre 2026) se usa este
#: porcentaje del cupo como respaldo, y la interfaz lo declara.
UMBRAL_RIESGO_CIERRE = _env_float("UMBRAL_RIESGO_CIERRE", 0.20)
UMBRAL_SALUDABLE_BAJO = 0.50
UMBRAL_LLENA = 0.85

ESTADOS = [
    "Sobrecupo",
    "Por llenarse",
    "Saludable",
    "Holgada",
    "Riesgo de cierre",
    "Sin asignados",
    "Sin límite definido",
    "Cerrada",
]


def estado_de(total: int, limite: int, limite_min: int, cerrada: bool) -> str:
    """Clasifica una sección según su ocupación (historia R1-04)."""
    if cerrada:
        return "Cerrada"
    if total == 0:
        return "Sin asignados"
    if not limite:
        return "Sin límite definido"
    if total > limite:
        return "Sobrecupo"
    # El mínimo oficial solo es informativo si es menor que el cupo: en algunos
    # laboratorios el reporte trae mínimo == cupo, lo que marcaría en riesgo a
    # cualquier sección que no esté llena.
    usa_minimo = 0 < (limite_min or 0) < limite
    if usa_minimo and total < limite_min:
        return "Riesgo de cierre"
    ocup = total / limite
    if ocup >= UMBRAL_LLENA:
        return "Por llenarse"
    if ocup >= UMBRAL_SALUDABLE_BAJO:
        return "Saludable"
    if usa_minimo:
        # Sobre el mínimo oficial: no está en riesgo aunque la ocupación sea baja.
        return "Holgada"
    if ocup >= UMBRAL_RIESGO_CIERRE:
        return "Holgada"
    return "Riesgo de cierre"


# --- Gestiones derivadas (vista "estado de gestiones" del perfil) ----------------
#: Una sección con al menos esta cantidad de estudiantes y sin auxiliar de cátedra
#: queda "en revisión" para la gestión de plaza de auxiliar.
UMBRAL_SECCION_GRANDE = _env_int("UMBRAL_SECCION_GRANDE", 60)

#: Tipos de gestión que se derivan del reporte. Clave -> (nombre, severidad)
#: Severidad "pendiente" bloquea el estado de la sección; "revision" no.
TIPOS_GESTION: dict[str, tuple[str, str]] = {
    "catedratico": ("Asignación de catedrático", "pendiente"),
    "salon": ("Asignación de salón", "pendiente"),
    "cupo": ("Ampliación de cupo / nueva sección", "pendiente"),
    "cierre": ("Revisión de cierre o fusión", "pendiente"),
    "limite": ("Definición de límite de asignados", "pendiente"),
    "auxiliar": ("Plaza de auxiliar de cátedra", "revision"),
}

DIAS = ["L", "Ma", "Mi", "J", "V", "S", "D"]
DIAS_NOMBRE = {
    "L": "Lunes", "Ma": "Martes", "Mi": "Miércoles", "J": "Jueves",
    "V": "Viernes", "S": "Sábado", "D": "Domingo",
}

#: Columnas de procedencia del estudiante (cabecera del reporte -> clave interna).
COLUMNAS_PROCEDENCIA = [
    ("regulares", "Regulares"),
    ("otra_fac", "Otra Facultad"),
    ("centros_reg", "Centros Regionales"),
    ("otra_univ", "Otra Universidad"),
    ("no_insc", "No inscritos"),
    ("est_cierre", "Estudiantes de cierre"),
    ("otro_caso", "Otro caso"),
]
