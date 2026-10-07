# Dashboard de Asignados · imagen única (API + tablero + SQLite)
#
#   docker compose up -d --build        (ver docker-compose.yml y docs/instalacion.md)
#
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    ENTRADA_DIR=/entrada \
    TZ=America/Guatemala

WORKDIR /app

# Dependencias primero: esta capa se reutiliza mientras requirements.txt no cambie.
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r requirements.txt
ENV PATH=/opt/venv/bin:$PATH

COPY backend ./backend
COPY frontend ./frontend
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# Usuario sin privilegios. El entrypoint arranca como root solo para dejar los
# volúmenes escribibles y luego cede los privilegios a este usuario.
# sed: si el repositorio se clonó en Windows con fin de línea CRLF, el script igual corre.
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
 && sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
 && chmod 0755 /usr/local/bin/entrypoint.sh \
 && mkdir -p /data /entrada \
 && chown -R app:app /data /entrada \
 && python -m compileall -q backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/salud', timeout=4)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
