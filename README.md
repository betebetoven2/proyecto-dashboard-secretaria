# Dashboard de Asignados

Tablero para la **Secretaría Académica de la Escuela de Ingeniería en Ciencias y Sistemas** (Facultad de
Ingeniería, USAC) alimentado por los reportes **«Contadores asignados (Condensado)»** de Centro de Cálculo.

Solo lectura: no se conecta a la base de la Facultad. La Secretaría sube los `.xlsx` que descarga (o los
copia a una carpeta) y el sistema los valida, los consolida y los muestra.

## Instalación

```bash
git clone https://github.com/betebetoven2/proyecto-dashboard-secretaria.git
cd proyecto-dashboard-secretaria
docker compose up -d --build
docker compose exec app python -m backend.app.autoprueba   # debe decir 16/16
```

Abrir **http://localhost:8000** → **Cargar reportes** → arrastrar los archivos.

Guía completa (configuración, respaldo, actualización, solución de problemas): **[docs/instalacion.md](docs/instalacion.md)**.

## Qué hace

| | |
|---|---|
| **Carga** | Arrastrar y soltar varios archivos, o copiarlos a `entrada/`. Cada archivo se valida por contenido (no por nombre), se verifica contra los totales del pie del reporte y recibe un resultado claro: cargado, ya estaba, reemplazó un corte, vacío o rechazado con el motivo. |
| **Períodos y cortes** | Los 21 períodos de Centro de Cálculo. Varias descargas del mismo período se guardan como cortes y habilitan evolución y tiempos de atención. |
| **Vistas** | Resumen · Vista 1 Seguimiento de cursos · Vista 2 Estado de gestiones · Vista 3 Tiempos de atención · Predicciones · Docentes y auxiliares · Secciones. |
| **Predicciones** | Demanda esperada por curso en el próximo período del mismo tipo, con intervalo, secciones sugeridas y riesgo de sobrecupo. Modelo empírico-bayesiano con tendencia amortiguada, validado contra el pasado. Ver [docs/predicciones.md](docs/predicciones.md). |
| **Salidas** | CSV con procedencia, descarga del original, tablas para Power BI. |
| **Trazabilidad** | Cada original se archiva por su huella SHA-256 y toda carga queda en una bitácora. La base se reconstruye desde los originales. |

## Documentación

| Documento | Para |
|---|---|
| [Manual de usuario](frontend/manual.html) (también en `/manual` dentro del sistema) | Secretaría Académica |
| [User story mapping](docs/user-story-map.md) | alcance, alineación con el perfil, criterios de aceptación |
| [Documentación técnica](docs/arquitectura.md) | arquitectura, pipeline, validaciones, modelo de datos, API |
| [Instalación y operación](docs/instalacion.md) | soporte técnico |
| [Predicciones](docs/predicciones.md) | método, validación, requisitos de datos y referencias |
| [Contrato de datos para Power BI](docs/powerbi.md) | equipo de Power BI |
| [Comandos para el servidor](docs/comandos-servidor.md) | día de la instalación |
| [Perfil aprobado y referencias](docs/referencias/) | perfil de prácticas finales, capturas del sistema de Centro de Cálculo |

## Desarrollo

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\...
python -m pytest                                  # suite completa
python -m uvicorn backend.app.main:app --reload   # http://127.0.0.1:8000
```

Integración continua (opcional): copie `docs/ci/ci.yml` a `.github/workflows/ci.yml` y cada push ejecutará
en GitHub Actions la suite completa y una instalación real con `docker compose` (imagen oficial, autoprueba,
subida de los reportes reales, carpeta de entrada y persistencia tras reiniciar).

## Privacidad

Los reportes no contienen datos personales de estudiantes (solo conteos), pero sí nombres de catedráticos y
auxiliares. Los reportes reales en `backend/tests/fixtures/` se usan para las pruebas: **mantenga este
repositorio privado**.
