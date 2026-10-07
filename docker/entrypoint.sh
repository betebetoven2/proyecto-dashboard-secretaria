#!/bin/sh
# Prepara las carpetas y arranca el servidor como usuario sin privilegios (app).
set -e

DATA_DIR="${DATA_DIR:-/data}"
ENTRADA_DIR="${ENTRADA_DIR:-/entrada}"
mkdir -p "$DATA_DIR" "$ENTRADA_DIR/procesados" "$ENTRADA_DIR/rechazados" "$ENTRADA_DIR/respaldos"

if [ "$(id -u)" = "0" ]; then
  # /data es un volumen administrado por Docker: le pertenece a app.
  chown -R app:app "$DATA_DIR" 2>/dev/null || true
  # entrada/ es una carpeta del equipo anfitrión: NO se le cambia el dueño (la persona
  # debe poder seguir copiando archivos ahí); solo se abre para que app pueda moverlos.
  chmod a+rwx "$ENTRADA_DIR" "$ENTRADA_DIR/procesados" "$ENTRADA_DIR/rechazados" "$ENTRADA_DIR/respaldos" 2>/dev/null || true
  if setpriv --reuid=app --regid=app --init-groups sh -c "test -w '$DATA_DIR' && test -w '$ENTRADA_DIR'"; then
    exec setpriv --reuid=app --regid=app --init-groups "$@"
  fi
  # Algunos montajes no aceptan cambios de permisos: antes que dejar el sistema
  # sin poder escribir, se sigue como root.
  echo "Aviso: el usuario 'app' no puede escribir en $DATA_DIR o $ENTRADA_DIR; se ejecuta como root." >&2
fi
exec "$@"
