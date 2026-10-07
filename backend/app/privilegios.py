"""Los comandos de consola (`docker compose exec app python -m …`) entran como root.
Si escribieran así en /data dejarían archivos de root que el servidor —que corre
como el usuario `app`— después no podría modificar. Por eso cada comando cede los
privilegios al usuario `app` antes de tocar cualquier archivo."""

from __future__ import annotations

import os


def ceder() -> None:
    if os.name != "posix" or os.geteuid() != 0:
        return
    try:
        import pwd
        usuario = pwd.getpwnam("app")
    except (ImportError, KeyError):
        return   # fuera del contenedor no existe el usuario `app`: nada que hacer
    os.setgroups([])
    os.setgid(usuario.pw_gid)
    os.setuid(usuario.pw_uid)
    os.environ["HOME"] = usuario.pw_dir
