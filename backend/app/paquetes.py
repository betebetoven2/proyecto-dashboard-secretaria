"""
Paquetes .zip con varios reportes.

La forma más rápida de cargar la historia: un .zip con los .xlsx de varios
años o períodos (p. ej. «semestre_2021_a_2026.zip»), subido en «Cargar
reportes» o copiado a la carpeta de entrada. Cada .xlsx de adentro pasa por el
MISMO pipeline que un archivo suelto (validación, huella, bitácora) y recibe su
propio resultado.

Seguridad:
- solo se procesan miembros .xlsx; se ignoran carpetas y basura de sistema
  (__MACOSX, .DS_Store, ~$temporales); otros archivos se informan como rechazados;
- nunca se extrae con la ruta del miembro (sin «zip slip»): cada miembro se copia
  a un temporal propio, leyendo por bloques con tope de tamaño (no se confía en el
  tamaño declarado por el zip);
- tope de miembros y de tamaño total descomprimido;
- un .zip dentro del .zip no se abre;
- un respaldo del propio sistema (trae asignados.db) se reconoce y se explica que
  se usa «restaurar».
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from . import config, ingesta

log = logging.getLogger("asignados.paquetes")

MAX_MIEMBROS = 400
_BLOQUE = 1 << 20


def es_paquete(ruta: Path) -> bool:
    """True si es un .zip común (no un .xlsx, que también es zip por dentro)."""
    try:
        if not zipfile.is_zipfile(ruta):
            return False
        with zipfile.ZipFile(ruta) as z:
            nombres = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False
    return "xl/workbook.xml" not in nombres and "[Content_Types].xml" not in nombres


def _es_basura(nombre: str) -> bool:
    partes = PurePosixPath(nombre.replace("\\", "/")).parts
    base = partes[-1] if partes else ""
    return (any(p == "__MACOSX" for p in partes) or base.startswith((".", "~$"))
            or base.lower() in ("thumbs.db", "desktop.ini"))


def procesar_entrada(ruta: Path, nombre: str | None = None, origen: str = "consola",
                     registrar: bool = True) -> list[ingesta.ResultadoCarga]:
    """Punto de entrada para cualquier archivo recibido: un .xlsx da un resultado; un
    .zip con reportes da un resultado por cada archivo de adentro. Nunca lanza."""
    ruta = Path(ruta)
    nombre = ingesta.nombre_seguro(nombre or ruta.name)
    if not es_paquete(ruta):
        return [ingesta.procesar_archivo(ruta, nombre, origen, registrar)]
    try:
        return _procesar_paquete(ruta, nombre, origen, registrar)
    except Exception as exc:  # noqa: BLE001 — un paquete dañado nunca tumba el servidor
        log.exception("Error al abrir el paquete %s", nombre)
        return [_rechazo(nombre, f"No se pudo abrir el paquete .zip ({type(exc).__name__}). "
                                 "¿Está completo? Vuelva a comprimirlo o suba los .xlsx sueltos.",
                         origen, registrar)]


def _rechazo(nombre: str, mensaje: str, origen: str, registrar: bool) -> ingesta.ResultadoCarga:
    res = ingesta.ResultadoCarga("rechazado", nombre, mensaje)
    return ingesta._cerrar(res, 0.0, origen, registrar)


def _procesar_paquete(ruta: Path, nombre: str, origen: str,
                      registrar: bool) -> list[ingesta.ResultadoCarga]:
    with zipfile.ZipFile(ruta) as z:
        infos = [i for i in z.infolist() if not i.is_dir() and not _es_basura(i.filename)]
        if any(PurePosixPath(i.filename).name == "asignados.db" for i in infos):
            return [_rechazo(
                nombre,
                "Es un respaldo del propio sistema, no un paquete de reportes. Para recuperarlo use: "
                "docker compose exec app python -m backend.app.etl restaurar /entrada/respaldos/"
                f"{nombre}", origen, registrar)]
        reportes = [i for i in infos if i.filename.lower().endswith(".xlsx")]
        if not reportes:
            return [_rechazo(nombre, "El .zip no contiene reportes .xlsx.", origen, registrar)]
        if len(infos) > MAX_MIEMBROS:
            return [_rechazo(nombre, f"El .zip trae {len(infos)} archivos; el máximo por paquete es "
                                     f"{MAX_MIEMBROS}. Divídalo en paquetes más pequeños.",
                             origen, registrar)]
        declarado = sum(i.file_size for i in reportes)
        if declarado > config.MAX_DESCOMPRIMIDO_BYTES:
            return [_rechazo(nombre, f"El contenido del .zip ({declarado / 1048576:.0f} MB) excede el "
                                     "límite de seguridad. Divídalo en paquetes más pequeños.",
                             origen, registrar)]

        tmp_dir = config.DATA_DIR / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        resultados: list[ingesta.ResultadoCarga] = []
        # Orden por nombre: «2021_S1, 2021_S2, …» se cargan en orden cronológico.
        for info in sorted(infos, key=lambda i: i.filename.lower()):
            base = ingesta.nombre_seguro(info.filename)
            etiqueta = f"{nombre} › {base}"      # termina en el nombre real: su extensión cuenta
            if info not in reportes:
                motivo = ("Un .zip dentro de otro .zip no se abre; súbalo por separado."
                          if base.lower().endswith(".zip") else
                          "Dentro del paquete solo se procesan reportes .xlsx.")
                resultados.append(_rechazo(etiqueta, motivo, origen, registrar))
                continue
            if info.file_size > config.MAX_BYTES:
                resultados.append(_rechazo(
                    etiqueta, f"Pesa {info.file_size / 1048576:.1f} MB descomprimido; el máximo por "
                              f"reporte es {config.MAX_MB:g} MB.", origen, registrar))
                continue
            with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".xlsx", delete=False) as tmp:
                destino = Path(tmp.name)
                try:
                    excedido = False
                    with z.open(info) as fuente:
                        escritos = 0
                        while bloque := fuente.read(_BLOQUE):
                            escritos += len(bloque)
                            if escritos > config.MAX_BYTES:
                                excedido = True
                                break
                            tmp.write(bloque)
                except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as exc:
                    tmp.close()
                    destino.unlink(missing_ok=True)
                    resultados.append(_rechazo(
                        etiqueta, f"No se pudo extraer del .zip ({type(exc).__name__}); el paquete "
                                  "está dañado o protegido con contraseña.", origen, registrar))
                    continue
            try:
                if excedido:
                    resultados.append(_rechazo(
                        etiqueta, f"Excede el máximo de {config.MAX_MB:g} MB por reporte.",
                        origen, registrar))
                else:
                    resultados.append(ingesta.procesar_archivo(destino, etiqueta, origen, registrar))
            finally:
                destino.unlink(missing_ok=True)
        return resultados
