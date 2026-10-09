# Comandos para el día de la instalación

Guía de una página para instalar en el servidor de la Secretaría. Cada bloque indica si es para
**Windows (PowerShell)** o **Linux (bash)**; donde no se indica, el comando es igual en ambos.

---

## 0. Verificar requisitos (2 min)

```bash
docker --version            # Docker 24 o superior
docker compose version      # Compose v2 (comando "docker compose", con espacio)
git --version
```

- **Windows:** Docker Desktop instalado y abierto (ícono de la ballena en verde, «Engine running»).
- **Linux:** `sudo systemctl enable --now docker` y, para no usar sudo en cada comando,
  `sudo usermod -aG docker $USER` (cerrar sesión y volver a entrar).

## 1. Descargar el código (3 min)

El repositorio es privado: la primera vez Git pedirá iniciar sesión en GitHub.

```bash
git clone https://github.com/betebetoven2/proyecto-dashboard-secretaria.git
cd proyecto-dashboard-secretaria
```

- **Windows:** se abre una ventana del navegador para iniciar sesión (Git Credential Manager). Aceptar.
- **Linux:** usuario de GitHub y, como contraseña, un *Personal Access Token* (GitHub → Settings →
  Developer settings → Fine-grained tokens → acceso de solo lectura al repositorio).
- **Sin acceso a GitHub en el servidor:** en otro equipo, GitHub → *Code* → *Download ZIP*, copiar el zip
  al servidor y descomprimir. Todo lo demás es igual.

## 2. Configurar (opcional, 1 min)

Solo si se quiere proteger la carga de archivos con un token o cambiar el puerto:

```powershell
# Windows
copy .env.example .env
notepad .env
```
```bash
# Linux
cp .env.example .env
nano .env
```

Recomendado si el tablero será visible para más personas en la red: definir `ADMIN_TOKEN=<una clave>`.

## 3. Levantar (3–5 min la primera vez)

```bash
docker compose up -d --build
docker compose ps
```

Esperar a que `docker compose ps` muestre **`Up … (healthy)`** (unos 20 segundos después de arrancar).

## 4. Verificar (1 min)

```bash
docker compose exec app python -m backend.app.autoprueba
```

Debe terminar con: **`Instalación verificada: 16/16 comprobaciones correctas.`**
(Usa datos de prueba en una carpeta temporal; no toca los datos reales.)

Abrir en el navegador del servidor: **http://localhost:8000**

## 5. Acceso desde otros equipos de la red

Averiguar la IP del servidor:

```powershell
ipconfig            # Windows: "Dirección IPv4"
```
```bash
hostname -I         # Linux
```

Abrir el puerto 8000 en el firewall:

```powershell
# Windows (PowerShell como administrador)
New-NetFirewallRule -DisplayName "Dashboard Asignados" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```
```bash
# Linux (si usa ufw)
sudo ufw allow 8000/tcp
```

Desde otro equipo: **http://<IP-del-servidor>:8000**

## 6. Que arranque solo al encender el servidor

El contenedor ya tiene `restart: unless-stopped`; solo falta que Docker arranque con el equipo:

- **Windows:** Docker Desktop → Settings → General → ✔ *Start Docker Desktop when you sign in to your
  computer*. (El servidor debe iniciar sesión con ese usuario.)
- **Linux:** `sudo systemctl enable docker` (ya hecho en el paso 0).

## 7. Primera carga de datos

1. En el sistema de Centro de Cálculo → *Contadores asignados (Condensado)* → elegir Año y Período →
   descargar en Excel. Repetir para **varios años del mismo período** (p. ej. Primer Semestre 2021–2026)
   para habilitar las predicciones.
2. En el tablero: **Cargar reportes** → arrastrar todos los archivos juntos.
   *(Alternativa: copiarlos a la carpeta `entrada` dentro de `proyecto-dashboard-secretaria`.)*
3. Revisar que cada archivo diga «Cargado». Luego **Tablero** → pestañas.

## 8. Respaldo

```bash
docker compose exec app python -m backend.app.etl respaldo
```

El `.zip` queda en `entrada/respaldos/`. Copiarlo fuera del servidor periódicamente.

Programarlo cada noche (opcional):

```powershell
# Windows (PowerShell como administrador; ajustar la ruta)
$ruta = "C:\ruta\a\proyecto-dashboard-secretaria"
$accion = New-ScheduledTaskAction -Execute "docker" -Argument "compose exec -T app python -m backend.app.etl respaldo" -WorkingDirectory $ruta
Register-ScheduledTask -TaskName "Respaldo Dashboard Asignados" -Action $accion -Trigger (New-ScheduledTaskTrigger -Daily -At 11pm)
```
```bash
# Linux: crontab -e  y agregar (ajustar la ruta)
0 23 * * * cd /ruta/a/proyecto-dashboard-secretaria && docker compose exec -T app python -m backend.app.etl respaldo
```

## 9. Comandos de uso frecuente

| Para | Comando |
|---|---|
| Ver si está corriendo | `docker compose ps` |
| Ver registros | `docker compose logs -f` (salir con Ctrl+C) |
| Qué reportes hay cargados | `docker compose exec app python -m backend.app.etl estado` |
| Reiniciar | `docker compose restart` |
| Detener (conserva datos) | `docker compose down` |
| Actualizar a una versión nueva | `git pull` y luego `docker compose up -d --build` |
| Restaurar un respaldo | `docker compose exec app python -m backend.app.etl restaurar /entrada/respaldos/<archivo>.zip` |

⚠ **Nunca** usar `docker compose down -v` salvo que se quiera **borrar todos los datos**.

## 10. Si algo falla

| Síntoma | Solución |
|---|---|
| `port is already allocated` | En `.env` poner `PUERTO=8080`, luego `docker compose up -d` y abrir `http://localhost:8080` |
| `Cannot connect to the Docker daemon` / `error during connect` | Abrir Docker Desktop (Windows) o `sudo systemctl start docker` (Linux) |
| `--build` falla al descargar paquetes | El servidor no tiene Internet o hay proxy: Docker Desktop → Settings → Resources → Proxies |
| No queda `healthy` | `docker compose logs --tail 100` y revisar el error |
| Desde otro equipo no abre | Firewall (paso 5) y que ambos estén en la misma red |
| Un archivo se rechaza | Leer el motivo en «Cargar reportes» o en `entrada/rechazados/*.motivo.txt` |

Más detalle: [instalacion.md](instalacion.md).
