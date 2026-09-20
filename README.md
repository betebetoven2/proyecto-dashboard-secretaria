# Dashboard de Asignados — MVP fase 1

Visor analítico de los snapshots del reporte **«TOTAL DE ASIGNADOS»** (Centro de Cálculo,
Facultad de Ingeniería, USAC), para la **Secretaría Académica de la Escuela de Ingeniería
en Ciencias y Sistemas**.

**Solo lectura.** No hay conexión a la base de datos de la Facultad: el sistema consume los
archivos `.xlsx` que se entregan por semestre y su única meta es la visualización.

El alcance funcional está definido en **[`docs/user-story-map.md`](docs/user-story-map.md)**.
Cada endpoint y cada tarjeta del tablero está rotulada con la historia que atiende
(`R1-01` … `R1-12`). Si una funcionalidad no está en ese documento, no pertenece al MVP.

---

## Cómo correrlo (Windows)

```powershell
cd "Dashboard testing"

py -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 1) cargar el snapshot al SQLite local
.venv\Scripts\python -m backend.app.etl

# 2) levantar la API + el tablero
.venv\Scripts\python -m uvicorn backend.app.main:app --reload
```

Abrir <http://127.0.0.1:8000>. Documentación interactiva de la API en
<http://127.0.0.1:8000/docs>.

Atajo: `run.ps1` hace los tres pasos (crea el entorno si no existe, carga los snapshots
nuevos y levanta el servidor).

### Linux / macOS

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m backend.app.etl
.venv/bin/python -m uvicorn backend.app.main:app --reload
```

## Cargar más snapshots

Copie los archivos a `backend/data/snapshots/` y vuelva a ejecutar el ETL:

```powershell
.venv\Scripts\python -m backend.app.etl
```

La carga es **idempotente por nombre de archivo**: recargar el mismo archivo reemplaza su
snapshot en lugar de duplicarlo. El modelo guarda N snapshots desde ya; el selector del
encabezado permite cambiar entre ellos y con dos o más queda habilitada la comparación
entre cortes (historia R2-01).

## Verificación

```powershell
.venv\Scripts\python -m backend.tests.verificar http://127.0.0.1:8000
```

Recalcula los totales **directamente del `.xlsx`**, sin pasar por el ETL, y los compara
contra la base y contra la API: 24 verificaciones que cubren totales, coherencia de las
categorías de ocupación, reglas de limpieza y consistencia de los filtros. Es el criterio
de aceptación de la historia R1-01 («los KPI cuadran contra una suma directa en Excel»).

---

## Estructura

```
backend/
  app/
    config.py     reglas derivadas: áreas, modalidad, jornada, umbrales  ← editar aquí
    db.py         esquema SQLite (snapshots, secciones, bloques, miembros)
    etl.py        xlsx → SQLite, con las reglas de limpieza documentadas
    queries.py    consultas de lectura, una por historia
    main.py       API REST + servidor del tablero
  data/
    snapshots/    los .xlsx que entrega la Facultad
    asignados.db  réplica local (se regenera con el ETL)
  tests/
    verificar.py  verificación contra el archivo original
frontend/
  index.html      tablero, con el ID de historia visible en cada tarjeta
  app.js          gráficas en SVG, sin dependencias externas
  styles.css      paleta con modo claro y oscuro
docs/
  user-story-map.md   el contrato funcional
```

### Por qué FastAPI + SQLite

- El reporte es un `.xlsx`: `openpyxl` lo lee nativamente y el ETL queda en un solo archivo
  legible y auditable.
- SQLite no necesita servidor, vive en un archivo dentro del proyecto y soporta los
  **N snapshots** que el producto necesitará para comparar cortes. Migrar a PostgreSQL más
  adelante es cambiar la cadena de conexión, no el modelo.
- El tablero no usa CDN ni framework: corre en la red interna de la Facultad sin internet.

---

## Lo que el ETL corrige del archivo

| Situación en el reporte | Regla aplicada |
|---|---|
| El encabezado no está en la fila 1 (membrete institucional arriba) | Se localiza la fila cuya primera celda es `No`; el período y la fecha/hora de corte se guardan como metadatos del snapshot |
| Nombres de columna repetidos (`Nombre` es curso y catedrático; `Nombre miembro` se repite) | Se resuelven por posición, no por nombre |
| **Una sección puede ocupar varias filas** (un bloque de horario por fila) y la fila de continuación deja vacío `Total` | El total se toma solo de la fila principal; los horarios se acumulan como bloques. Sin esta regla los totales se inflan: 1,378 filas contra 926 + 452 secciones reales |
| La `Ñ` llega corrupta como `\` (`DISE\O`) | Se corrige y se normalizan espacios dobles en nombres de personas |
| El mismo auxiliar repetido en ambas columnas de miembro (9 casos) | Se deduplica por sección para no inflar la cobertura de auxiliares |
| Columnas de procedencia en cero | Se conservan en el modelo; la UI avisa que el snapshot no las trae en lugar de mostrar seis ceros |
| `Límite mínimo de asignados` en cero | El umbral de riesgo de cierre es un parámetro de `config.py`, y la UI lo declara como tal |
| El formato del reporte podría cambiar | El ETL valida el encabezado y falla con un mensaje explícito antes de cargar datos mal alineados |

## Endpoints

| Endpoint | Historia | Devuelve |
|---|---|---|
| `GET /api/snapshots` | R1-12 / R2-01 | snapshots cargados |
| `GET /api/catalogos` | R1-02 | valores para los filtros + metadatos del snapshot |
| `GET /api/kpis` | R1-01 | asignados, secciones, cursos, ocupación, cobertura de auxiliares |
| `GET /api/ocupacion` | R1-04 / R1-05 | secciones por estado e histograma de llenado |
| `GET /api/cursos` | R1-03 | cursos por demanda |
| `GET /api/docentes` | R1-06 | carga por catedrático |
| `GET /api/auxiliares` | R1-07 | carga por auxiliar y secciones grandes sin auxiliar |
| `GET /api/heatmap` | R1-08 | ocupación por día y hora |
| `GET /api/salones` | R1-08 | salones por horas-semana ocupadas |
| `GET /api/distribucion/{modalidad\|jornada\|area\|tipo}` | R1-09 | distribuciones |
| `GET /api/secciones` | R1-10 | tabla explorable y búsqueda libre |
| `GET /api/export.csv` | R1-11 | CSV de lo filtrado, con la procedencia del dato en la cabecera |

Todos aceptan los mismos filtros: `snapshot_id`, `tipo`, `area`, `jornada`, `modalidad`,
`edificio`, `estado`, `docente`, `codigo`, `q`.

---

## Privacidad

El reporte **no contiene datos personales de estudiantes**, únicamente conteos agregados
por sección. Sí contiene nombres de catedráticos y auxiliares (dato laboral de uso
interno). El sistema no agrega ninguna otra fuente y no escribe hacia ningún sistema de la
Facultad.

## Pendiente (Release 2, ver el story map)

Comparación entre snapshots · brecha clase–laboratorio · simulador de cierre de secciones ·
detección de traslapes de salón y docente (el algoritmo preliminar marca 123 solapes, pero
los bloques contiguos de una misma sección producen falsos positivos y las reglas necesitan
afinarse antes de mostrarse) · vista por nivel del pensum · reporte PDF de una página.
