# Guía de instalación

Tiempo estimado: 10 minutos. Requiere **Docker** (Docker Desktop en Windows/macOS, Docker Engine en Linux)
y **Git**.

## 1. Instalar

```bash
git clone https://github.com/betebetoven2/proyecto-dashboard-secretaria.git
cd proyecto-dashboard-secretaria
docker compose up -d --build
```

La primera vez descarga la imagen base de Python y las dependencias (2–4 minutos). Al terminar:

```bash
docker compose ps
```

debe mostrar `dashboard-asignados ... Up ... (healthy)`. Abra **http://localhost:8000**.

Desde otro equipo de la red: `http://<IP-del-servidor>:8000` (en Windows, permita el puerto 8000 en el
firewall si lo pide).

## 2. Verificar la instalación

```bash
docker compose exec app python -m backend.app.autoprueba
```

Debe terminar con `Instalación verificada: 15/15 comprobaciones correctas.` La prueba usa reportes
sintéticos en una carpeta temporal: **no toca los datos reales**.

## 3. Primera carga

Opción A — navegador: **Cargar reportes** → arrastrar los `.xlsx` → cada archivo muestra su resultado.

Opción B — carpeta: copiar los `.xlsx` a la carpeta `entrada/` del repositorio. En ~10 segundos pasan a
`entrada/procesados/` (o a `entrada/rechazados/` con un `.txt` que explica el motivo).

Opción C — consola:

```bash
docker compose exec app python -m backend.app.etl carpeta
```

## 4. Configuración (opcional)

```bash
cp .env.example .env      # en Windows: copy .env.example .env
# editar .env
docker compose up -d
```

| Variable | Por defecto | Para qué |
|---|---|---|
| `PUERTO` | 8000 | puerto del equipo |
| `ADMIN_TOKEN` | (vacío) | si se define, subir y eliminar exigen este token |
| `META_DIAS_ATENCION` | 6 | meta de la vista «Tiempos de atención» |
| `UMBRAL_SECCION_GRANDE` | 60 | estudiantes a partir de los cuales falta auxiliar |
| `MAX_MB` | 25 | tamaño máximo por archivo |
| `INTERVALO_ENTRADA_SEG` | 10 | revisión de `entrada/` (0 = apagado) |

## 5. Operación diaria

| Acción | Comando |
|---|---|
| Ver registros | `docker compose logs -f` |
| Estado de los datos | `docker compose exec app python -m backend.app.etl estado` |
| Validar un archivo sin cargarlo | `docker compose exec app python -m backend.app.etl validar /entrada/archivo.xlsx` |
| Respaldo | `docker compose exec app python -m backend.app.etl respaldo` → queda en `entrada/respaldos/` |
| Restaurar | `docker compose exec app python -m backend.app.etl restaurar /entrada/respaldos/<archivo>.zip` |
| Detener | `docker compose down` (los datos se conservan) |
| **Borrar todos los datos** | `docker compose down -v` (¡irreversible! respalde antes) |

Los comandos de consola pueden ejecutarse como `root` sin riesgo: ceden privilegios al usuario del
servidor antes de escribir.

## 6. Actualizar a una versión nueva

```bash
docker compose exec app python -m backend.app.etl respaldo     # por precaución
git pull
docker compose up -d --build
docker compose exec app python -m backend.app.autoprueba
```

Si la versión nueva cambia el modelo de datos, la base se reconstruye sola desde los originales
archivados al arrancar; no hay migraciones manuales.

## 7. Dónde están los datos

| Qué | Dónde | Notas |
|---|---|---|
| Base SQLite y originales | volumen Docker `dashboard-asignados_datos` | sobrevive a `down`, `up`, `--build` y reinicios del equipo |
| Carpeta de entrada, procesados, rechazados, respaldos | `./entrada` en la carpeta del repositorio | visible desde el explorador de archivos |

Para llevar la instalación a otro equipo: respaldo → copiar el `.zip` → instalar en el equipo nuevo →
`restaurar`.

## 8. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `port is already allocated` | otro programa usa el 8000 | `PUERTO=8080` en `.env` y `docker compose up -d` |
| `docker: command not found` / no conecta al daemon | Docker Desktop no está abierto | abrirlo y esperar a que diga *running* |
| El contenedor no queda `healthy` | error al arrancar | `docker compose logs` |
| Un archivo de `entrada/` no se carga | sigue copiándose o está abierto en Excel | esperar; cerrar Excel; revisar `entrada/rechazados/*.motivo.txt` |
| «El sistema no tiene permiso para leer el archivo» (Linux) | permisos del archivo | `chmod a+r archivo.xlsx` y copiarlo otra vez |
| Un reporte se rechaza por «TOTAL del pie» | archivo editado o incompleto | descargarlo de nuevo de Centro de Cálculo sin abrirlo/guardarlo |
| «Falta el token de administración» | `ADMIN_TOKEN` definido | escribir el token en la tarjeta de la página «Cargar reportes» |
| Detrás de un proxy institucional, `--build` no descarga paquetes | sin salida a Internet | configurar el proxy en Docker Desktop (Settings → Resources → Proxies) |

## 9. Sin Docker (solo para desarrollo)

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m uvicorn backend.app.main:app --reload
```

Los datos quedan en `./datos` y la carpeta vigilada en `./datos/entrada`. Atajo: `run.ps1`.
