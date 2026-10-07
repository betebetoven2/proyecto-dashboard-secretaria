"""
Carpeta de entrada vigilada.

La forma más simple de cargar reportes: copiar los .xlsx a la carpeta
`entrada/` (en Docker es una carpeta compartida con el equipo anfitrión). Cada
pocos segundos el sistema la revisa, procesa lo que encuentre por el mismo
pipeline que la subida web y mueve cada archivo a:

    entrada/procesados/   cargado, reemplazó un corte, o ya estaba cargado
    entrada/rechazados/   no se cargó; al lado queda un .txt con el motivo

Un archivo solo se procesa cuando su tamaño dejó de cambiar entre dos
revisiones, para no leer copias a medias.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config, ingesta, lector

log = logging.getLogger("asignados.vigilante")

_IGNORAR_SUFIJOS = {".txt", ".md", ".tmp", ".part", ".crdownload", ".download", ".ini", ".db"}
_vistos: dict[str, tuple[int, float]] = {}
#: Errores que pueden deberse a una copia todavía en curso (Windows reserva el
#: tamaño final antes de terminar de escribir). Si el archivo es reciente, se
#: reintenta en la siguiente revisión en lugar de rechazarlo.
_TRANSITORIOS = {"zip_danado", "libro_ilegible", "archivo_vacio_bytes", "archivo_ilegible"}
_ESPERA_COPIA_SEG = 120


def _candidatos() -> list[Path]:
    if not config.ENTRADA_DIR.is_dir():
        return []
    out = []
    for p in sorted(config.ENTRADA_DIR.iterdir()):
        if not p.is_file():
            continue
        n = p.name
        if n.startswith(("~$", ".", "_")) or p.suffix.lower() in _IGNORAR_SUFIJOS:
            continue
        out.append(p)
    return out


def _destino(carpeta: Path, nombre: str) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = carpeta / f"{sello}_{nombre}"
    i = 1
    while destino.exists():
        destino = carpeta / f"{sello}-{i}_{nombre}"
        i += 1
    return destino


def revisar_una_vez(exigir_estable: bool = True) -> list[ingesta.ResultadoCarga]:
    resultados = []
    presentes = set()
    for p in _candidatos():
        presentes.add(str(p))
        try:                       # un archivo problemático nunca detiene a los demás
            res = _revisar_archivo(p, exigir_estable)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo procesar %s desde la carpeta de entrada", p.name)
            continue
        if res is not None:
            resultados.append(res)
    for clave in list(_vistos):
        if clave not in presentes:
            _vistos.pop(clave, None)
    return resultados


def _revisar_archivo(p: Path, exigir_estable: bool) -> ingesta.ResultadoCarga | None:
    clave = str(p)
    try:
        st = p.stat()
    except OSError:
        return None
    firma = (st.st_size, st.st_mtime)
    if exigir_estable:
        if _vistos.get(clave) != firma or time.time() - st.st_mtime < 2:
            _vistos[clave] = firma
            return None
    _vistos.pop(clave, None)

    if exigir_estable and time.time() - st.st_mtime < _ESPERA_COPIA_SEG:
        previos = {m.codigo for m in lector.inspeccionar_archivo(p) if m.nivel == "error"}
        if previos & _TRANSITORIOS:
            _vistos[clave] = firma
            return None

    res = ingesta.procesar_archivo(p, p.name, origen="carpeta")
    destino = _destino(
        config.PROCESADOS_DIR if res.resultado in ("aceptado", "reemplazo", "duplicado")
        else config.RECHAZADOS_DIR, p.name)
    try:
        p.replace(destino)
    except OSError:
        log.exception("No se pudo mover %s a %s", p, destino)
        return res
    if not res.cargado and res.resultado != "duplicado":
        lineas = [f"Archivo: {p.name}", f"Resultado: {res.resultado.upper()}",
                  f"Motivo: {res.mensaje}", ""]
        lineas += [f"- [{m['nivel']}] {m['texto']}" for m in res.mensajes]
        try:
            destino.with_name(destino.name + ".motivo.txt").write_text(
                "\r\n".join(lineas), encoding="utf-8")
        except OSError:
            pass
    return res


def iniciar(detener: threading.Event) -> threading.Thread | None:
    if config.INTERVALO_ENTRADA_SEG <= 0:
        log.info("Vigilante de carpeta desactivado (INTERVALO_ENTRADA_SEG=0).")
        return None

    def bucle():
        log.info("Vigilando %s cada %ss", config.ENTRADA_DIR, config.INTERVALO_ENTRADA_SEG)
        while not detener.is_set():
            try:
                revisar_una_vez()
            except Exception:  # noqa: BLE001 — el vigilante nunca debe morir
                log.exception("Error revisando la carpeta de entrada")
            detener.wait(config.INTERVALO_ENTRADA_SEG)

    hilo = threading.Thread(target=bucle, name="vigilante-entrada", daemon=True)
    hilo.start()
    return hilo
