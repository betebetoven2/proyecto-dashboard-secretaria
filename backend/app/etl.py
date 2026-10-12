"""
Línea de comandos del ETL.

    python -m backend.app.etl cargar archivo1.xlsx [archivo2.xlsx …]   (o paquete.zip)
    python -m backend.app.etl carpeta          # procesa lo que haya en entrada/
    python -m backend.app.etl reprocesar       # reconstruye la base desde el archivo
    python -m backend.app.etl validar archivo.xlsx   # solo valida, no carga nada
    python -m backend.app.etl estado           # snapshots cargados
    python -m backend.app.etl respaldo         # zip en entrada/respaldos/
    python -m backend.app.etl restaurar respaldo.zip

En Docker:
    docker compose exec app python -m backend.app.etl estado
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, ingesta, lector, paquetes, privilegios, queries, vigilante

ICONOS = {"aceptado": "✓", "reemplazo": "↻", "duplicado": "=", "vacio": "∅", "rechazado": "✗"}


def _imprimir(res: ingesta.ResultadoCarga, detalle: bool = True) -> None:
    print(f"{ICONOS.get(res.resultado, '?')} {res.archivo}: {res.resultado.upper()} — {res.mensaje}")
    if detalle:
        for m in res.mensajes:
            if m["nivel"] != "info":
                print(f"     [{m['nivel']}] {m['texto']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.app.etl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p_cargar = sub.add_parser("cargar", help="carga uno o más .xlsx o paquetes .zip")
    p_cargar.add_argument("archivos", nargs="+", type=Path)
    p_val = sub.add_parser("validar", help="valida sin cargar")
    p_val.add_argument("archivos", nargs="+", type=Path)
    sub.add_parser("carpeta", help="procesa la carpeta de entrada")
    sub.add_parser("reprocesar", help="reconstruye la base desde el archivo de originales")
    sub.add_parser("estado", help="lista los snapshots cargados")
    sub.add_parser("respaldo", help="genera un respaldo en entrada/respaldos/")
    p_rest = sub.add_parser("restaurar", help="restaura un respaldo .zip")
    p_rest.add_argument("zip", type=Path)
    args = ap.parse_args(argv)
    privilegios.ceder()

    ingesta.asegurar_esquema()
    if args.cmd in (None, "carpeta"):
        res = vigilante.revisar_una_vez(exigir_estable=False)
        if not res:
            print("No hay archivos en la carpeta de entrada.")
        for r in res:
            _imprimir(r)
        return 0 if all(r.resultado != "rechazado" for r in res) else 1

    if args.cmd == "cargar":
        res = [r for a in args.archivos for r in paquetes.procesar_entrada(a, a.name, "consola")]
        for r in res:
            _imprimir(r)
        return 0 if all(r.resultado != "rechazado" for r in res) else 1

    if args.cmd == "validar":
        codigo = 0
        for a in args.archivos:
            rep = lector.leer_reporte(a)
            estado = "VÁLIDO" if rep.es_valido else "INVÁLIDO"
            if rep.vacio:
                estado = "VÁLIDO PERO VACÍO"
            print(f"{a.name}: {estado} · {rep.descripcion} · {len(rep.secciones)} secciones · "
                  f"{rep.total_asignados:,} asignados")
            for m in rep.mensajes:
                print(f"   [{m.nivel}] {m.texto}")
            codigo |= 0 if rep.es_valido else 1
        return codigo

    if args.cmd == "reprocesar":
        res = ingesta.reprocesar()
        for r in res:
            _imprimir(r, detalle=False)
        print(f"{sum(r.cargado for r in res)} snapshots reconstruidos.")
        return 0

    if args.cmd == "respaldo":
        print(f"Respaldo creado: {ingesta.respaldo()}")
        return 0

    if args.cmd == "restaurar":
        res = ingesta.restaurar(args.zip)
        print(f"Restaurados {sum(r.cargado for r in res)} snapshots desde {args.zip.name}.")
        return 0

    if args.cmd == "estado":
        with db.conexion() as con:
            snaps = queries.snapshots(con)
        if not snaps:
            print("No hay snapshots cargados.")
        for s in snaps:
            print(f"#{s['id']:<4} {s['anio']} {s['periodo_nombre']:<45} corte {s['fecha_corte'][:16]}"
                  f"  {s['total_secciones']:>5} secc  {s['total_asignados']:>7,} asig  ({s['archivo_nombre']})")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
