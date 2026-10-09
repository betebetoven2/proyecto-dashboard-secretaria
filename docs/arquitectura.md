# Documentación técnica

Dashboard de Asignados · Secretaría Académica ECYS · versión 1.1.0

## 1. Vista general

```
                     ┌───────────────────────── contenedor «app» (Docker) ─────────────────────────┐
  Navegador ──HTTP──►│ FastAPI (uvicorn)                                                            │
  /  /cargas         │   ├─ main.py        API REST + archivos estáticos del tablero                │
  /manual            │   ├─ queries.py     consultas de lectura (una por historia)
                     │   ├─ predicciones.py demanda esperada por curso (próximo período)                  │
                     │   │                                                                          │
  Subida (.xlsx) ───►│   ├─ ingesta.py     PIPELINE ÚNICO: huella → validar → archivar → cargar     │
                     │   │     ▲   ▲  └── lector.py   lectura y validación del reporte              │
  entrada/ (carpeta  │   │     │   │  └── gestiones.py gestiones derivadas y tiempos de atención    │
  del equipo) ──────►│   ├─ vigilante.py   revisa entrada/ cada 10 s                                │
                     │   │         │                                                                │
  consola ──────────►│   └─ etl.py         cargar · validar · reprocesar · respaldo · restaurar     │
                     │                                                                              │
                     │   /data (volumen)                 /entrada (carpeta del equipo anfitrión)    │
                     │    ├─ asignados.db  SQLite         ├─ procesados/                            │
                     │    └─ archivo/      originales     ├─ rechazados/  (+ .motivo.txt)           │
                     │       por SHA-256  ← FUENTE        └─ respaldos/                             │
                     │                       DE VERDAD                                              │
                     └──────────────────────────────────────────────────────────────────────────────┘
                                     │
                     Power BI ◄──────┘ /api/powerbi/*.csv  (contrato de datos, ver powerbi.md)
```

Un solo proceso, un solo contenedor, sin dependencias externas en tiempo de ejecución (sin CDN, sin base
de datos aparte). El tablero funciona en la red interna sin Internet.

## 2. Principios

1. **Solo lectura sobre la Facultad.** Lo único que se escribe es la réplica local.
2. **El original es la fuente de verdad.** Cada archivo aceptado se guarda tal cual en `archivo/` por su
   SHA-256, con una ficha JSON (nombre, vía, fecha, estado). La base SQLite es derivada: si se borra, o si
   cambia el esquema, se reconstruye sola desde el archivo (`ingesta.asegurar_esquema`).
3. **Un solo pipeline.** Navegador, carpeta y consola llaman a `ingesta.procesar_archivo`, que nunca lanza
   excepciones: todo resultado vuelve como `ResultadoCarga` y queda en la bitácora `cargas`.
4. **La identidad del snapshot sale del contenido**, no del nombre del archivo: período, año y fecha de
   corte del membrete.
5. **Validar por contenido, explicar en español.** Cada mensaje tiene un código estable (para pruebas) y
   un texto accionable (para la Secretaría).

## 3. Pipeline de ingesta

```
archivo ─► SHA-256 ─► ¿ya existe ese SHA? ──sí──► DUPLICADO (nada cambia)
                            │ no
                            ▼
                  lector.leer_reporte ──errores──► RECHAZADO (motivos en bitácora; no se archiva)
                            │
                  ¿sin secciones? ──sí──► VACÍO (se informa; no se guarda)
                            │
            ¿mismo año + período + fecha de corte? ──sí──► REEMPLAZO del snapshot anterior
                            │ no
                            ▼
                         ACEPTADO
   (una transacción: snapshot + secciones + bloques + miembros + gestiones;
    actualización del catálogo de cursos; reclasificación de snapshots anteriores)
```

Concurrencia: un candado (`threading.RLock`) serializa las cargas; SQLite en modo WAL permite que el
tablero lea mientras se carga. Probado con 6 cargas simultáneas.

## 4. Validaciones

### 4.1 Del archivo (`lector.inspeccionar_archivo`, antes de abrirlo)

| Código | Nivel | Situación |
|---|---|---|
| `archivo_vacio_bytes` | error | 0 bytes |
| `archivo_muy_grande` | error | > `MAX_MB` (25 MB por defecto; el reporte real pesa ~165 KB) |
| `archivo_ilegible` | error | sin permiso de lectura u otro error de E/S |
| `formato_xls_o_protegido` | error | contenido OLE2: .xls antiguo o .xlsx con contraseña |
| `no_es_xlsx` | error | texto, CSV o HTML con extensión de Excel |
| `zip_danado` | error | descarga interrumpida |
| `zip_no_xlsx` | error | zip que no contiene `xl/workbook.xml` |
| `zip_bomba` | error | contenido descomprimido > `MAX_DESCOMPRIMIDO_MB` |
| `con_macros` | advertencia | .xlsm: las macros se ignoran |
| `extension_inesperada` | advertencia | extensión distinta pero contenido .xlsx válido |

El XML interno se lee con `defusedxml` (protección contra entidades maliciosas).

### 4.2 Del reporte (`lector.leer_reporte`)

| Código | Nivel | Situación |
|---|---|---|
| `libro_ilegible` | error | openpyxl no puede leer el libro |
| `sin_hojas` / `falta_hoja` | error / advertencia | no hay «Clase» ni «Laboratorio» / falta una |
| `sin_encabezado` | error | ninguna fila empieza con «No» y «Codigo» (y no es un reporte vacío) |
| `faltan_columnas` | error | falta una columna obligatoria (dice cuál) |
| `columna_nueva` | advertencia | columna no reconocida: se ignora |
| `sin_membrete` / `membrete_ilegible` / `membretes_distintos` | error | no se puede identificar período/año/corte, o las hojas no coinciden |
| `periodo_desconocido` | advertencia | período fuera del catálogo de 21 |
| `corte_futuro` / `anio_inusual` | advertencia | fechas incoherentes |
| `valor_no_numerico` / `valor_negativo` | error | cantidades inválidas (indica hoja y fila) |
| `control_total` / `control_regulares` | error | la suma leída no coincide con el pie del reporte |
| `sin_pie_control` | advertencia | no trae pie: no se pudo verificar |
| `suma_procedencia` | advertencia | Total ≠ suma de las columnas de procedencia |
| `hora_invalida`, `codigo_inusual`, `seccion_duplicada`, `filas_sin_codigo`, `fila_sin_total` | advertencia | calidad de filas (agrupadas, con ejemplos) |
| `hoja_vacia` | info | hoja con `TOTAL: 0` |

### 4.3 De la carpeta vigilada

- Solo se procesa un archivo cuyo tamaño no cambió entre dos revisiones (copia terminada).
- Si un archivo reciente (< 2 min) parece dañado o ilegible, se reintenta en lugar de rechazarlo
  (Windows reserva el tamaño final antes de terminar de copiar).
- Se ignoran `~$*.xlsx` (Excel abierto), `.crdownload`, `.part`, `.tmp`, `.txt`.
- Un archivo problemático nunca detiene el procesamiento de los demás.

## 5. Reglas de limpieza y normalización

| Regla | Dónde |
|---|---|
| Columnas resueltas **por nombre**; «Nombre» 1.º = curso, 2.º = catedrático; parejas «Nombre/Tipo miembro» | `lector._mapear_columnas` |
| Filas de continuación (sin Total) = otro bloque de horario de la misma sección | `lector._parsear_hoja` |
| `\` → `Ñ` (Ñ corrupta del origen), espacios dobles, Unicode NFC | `lector.limpiar_texto` |
| Códigos numéricos → 4 dígitos (`770` → `0770`); horas como texto u objeto `time` | `lector.limpiar_*` |
| `STAFF` → sin catedrático; salón `CERRADO` → sección cerrada | `config.DOCENTES_SIN_ASIGNAR`, `SALON_CERRADO` |
| Miembros repetidos en la misma sección se deduplican | `lector._parsear_hoja` |
| Escuela/área: archivo → catálogo aprendido → regla por código → «SIN CLASIFICAR» | `ingesta._clasificador`, `catalogos.py` |
| Cursos «(DIPLOMADO)» 3xxx heredan la escuela del 0xxx equivalente | `catalogos.codigo_base` |

## 5 bis. Tipos de documento, formatos y períodos

Tres dimensiones independientes, cada una en su capa:

| Dimensión | Capa | Qué pasa con lo desconocido |
|---|---|---|
| Tipo de documento | `documentos.identificar` (firma del membrete u hojas características) | se rechaza: «no es de un tipo de documento soportado» + lista de tipos |
| Formato (columnas) | lector del tipo, columnas por nombre | columnas nuevas: advertencia; obligatorias faltantes: rechazo |
| Tipo de período | `catalogos.PERIODOS` (21) | se carga con advertencia y orden 80 |

Cada snapshot guarda `tipo_documento`. Las vistas y las predicciones filtran por tipo de documento y las
predicciones, además, por tipo de período. Agregar un tipo de documento = escribir su lector y registrarlo
en `documentos.TIPOS`.

## 6. Modelo de datos (SQLite, esquema v3)

```
snapshots 1───* secciones 1───* bloques       (día, hora inicio, hora fin)
    │              │      1───* miembros      (nombre, tipo: AUXILIAR DE CATEDRA, RESPONSABLE…)
    │              │      1───* gestiones     (clave, tipo, severidad, detalle)
    │              └── codigo ··· catalogo_cursos (codigo PK, escuela, área, subárea, fuente)
    └── (bitácora independiente) cargas
```

| Tabla | Grano | Claves importantes |
|---|---|---|
| `snapshots` | un archivo aceptado = un período en una fecha de corte | `sha256` único; `tipo_documento`; `anio`, `periodo_nombre`, `periodo_orden`, `fecha_corte` |
| `secciones` | una sección (clase o laboratorio) en un snapshot | `estado` (ocupación), `estado_gestion`, `clasificacion_origen`, `cerrada`, `sin_docente` |
| `bloques` | un bloque de horario | — |
| `miembros` | un miembro de terna | `tipo` |
| `gestiones` | una gestión derivada de una sección | `clave` ∈ catedratico, salon, cupo, cierre, limite, auxiliar |
| `catalogo_cursos` | un curso | `fuente` ∈ semilla, archivo |
| `cargas` | un intento de carga (cualquier resultado) | `resultado`, `mensajes_json` |

**Snapshot vigente por defecto:** el corte más reciente del período académico más reciente
(`anio DESC, periodo_orden DESC, fecha_corte DESC`), no el último archivo subido. Así, cargar un reporte
viejo de 2023 no cambia lo que la Secretaría ve al abrir.

## 7. Estructura del código

| Archivo | Responsabilidad |
|---|---|
| `backend/app/config.py` | Parámetros de instalación (variables de entorno) y reglas de negocio editables |
| `backend/app/catalogos.py` | 21 períodos, normalización de texto, heurística de clasificación |
| `backend/app/catalogo/cursos_semilla.csv` | 140 cursos con escuela/área reales (de vacaciones 2025) |
| `backend/app/documentos.py` | Registro de **tipos de documento** (hoy: Contadores asignados condensado); identifica el tipo antes de leer |
| `backend/app/lector.py` | Inspección y lectura del .xlsx; produce `Reporte` con mensajes |
| `backend/app/predicciones.py` | Modelo de predicción de demanda por curso (ver `docs/predicciones.md`) |
| `backend/app/gestiones.py` | Gestiones por sección; tiempos de atención entre cortes |
| `backend/app/db.py` | Esquema, conexión |
| `backend/app/ingesta.py` | Pipeline, archivo de originales, eliminación, reproceso, respaldo |
| `backend/app/vigilante.py` | Carpeta de entrada |
| `backend/app/queries.py` | Consultas del tablero y contrato Power BI |
| `backend/app/main.py` | API y páginas |
| `backend/app/etl.py` | Consola |
| `backend/app/autoprueba.py` | Verificación de instalación + generador de reportes sintéticos |
| `backend/app/privilegios.py` | Los comandos de consola ceden privilegios al usuario `app` |
| `frontend/` | `index.html` + `app.js` (tablero), `cargas.html` + `cargas.js`, `manual.html`, `common.js` (gráficas SVG sin dependencias), `styles.css` |

## 8. API

Todos los `GET` del tablero aceptan los mismos filtros: `snapshot_id, tipo, escuela, area, jornada,
modalidad, edificio, estado, estado_gestion, docente, codigo, q`. Documentación interactiva en `/docs`.

| Método y ruta | Uso |
|---|---|
| `GET /api/salud` | estado, versión, si exige token |
| `GET /api/snapshots`, `/api/periodos`, `/api/catalogos` | metadatos y selectores |
| `GET /api/kpis`, `/cursos`, `/ocupacion`, `/docentes`, `/auxiliares`, `/heatmap`, `/salones`, `/distribucion/{col}`, `/secciones` | vistas |
| `GET /api/gestiones`, `/api/tiempos`, `/api/evolucion` | vistas 2, 3 y 1 del perfil |
| `GET /api/predicciones?periodo=…` | demanda esperada por curso, secciones sugeridas, validación |
| `GET /api/export/predicciones.csv` | predicciones en CSV |
| `GET /api/export.csv`, `/api/export/gestiones.csv` | exportación |
| `GET /api/powerbi`, `/api/powerbi/{tabla}.csv` | contrato de datos |
| `POST /api/cargas` 🔒 | subir 1–30 archivos (multipart, campo `archivos`) |
| `GET /api/cargas` | bitácora |
| `POST /api/cargas/revisar-carpeta` 🔒 | procesar `entrada/` ya |
| `DELETE /api/snapshots/{id}` 🔒 | quitar del tablero (el original queda archivado) |
| `POST /api/reprocesar` 🔒 | reconstruir la base desde el archivo |
| `GET /api/snapshots/{id}/original` | descargar el .xlsx original |

🔒 = exige cabecera `X-Admin-Token` si `ADMIN_TOKEN` está definido.

## 9. Seguridad

- Usuario sin privilegios (`app`, uid 10001) dentro del contenedor; el entrypoint solo usa root para
  preparar permisos de los volúmenes.
- Token de administración opcional, comparado en tiempo constante.
- Nombres de archivo saneados; los originales se guardan con su huella, nunca con el nombre recibido.
- Restauración de respaldos con lista blanca de rutas (evita *zip slip*).
- CSV protegidos contra inyección de fórmulas (`=`, `+`, `-`, `@`).
- Consultas SQL parametrizadas; columnas dinámicas solo desde listas blancas.
- Límite de 30 archivos y `MAX_MB` por archivo por subida.

## 10. Pruebas

```
pip install -r requirements-dev.txt
python -m pytest
```

| Archivo | Cubre |
|---|---|
| `test_lector.py` | los 3 archivos reales y ~30 variantes dañadas o inusuales |
| `test_ingesta.py` | duplicado, reemplazo, cortes, archivo, reproceso, esquema, reclasificación, concurrencia, carpeta, permisos, respaldo |
| `test_api.py` | todos los endpoints con y sin filtros, token, exportación, gestiones, tiempos, evolución |
| `test_catalogos.py` | 21 períodos y precisión de la heurística (≥ 90%) |
| `test_predicciones.py` | calibración de intervalos por simulación, mejora sobre el ingenuo, recuperación de parámetros, validación móvil, cursos nuevos/discontinuados, ceros, aislamiento por tipo de período y de documento, formatos mezclados, último corte por año |

Además: `python -m backend.app.autoprueba` (verificación de la instalación) y el flujo de GitHub Actions
`docs/ci/ci.yml` (cópielo a `.github/workflows/` para activarlo), que construye la imagen oficial, levanta `docker compose`, sube los reportes
reales y verifica persistencia tras reiniciar.

## 11. Cómo extender

| Necesidad | Cambio |
|---|---|
| Nuevo umbral o meta | variable en `.env` (ver `.env.example`) o `config.py` |
| Nueva gestión derivada | agregar a `config.TIPOS_GESTION` y una regla en `gestiones.derivar` |
| La Facultad agrega una columna | agregarla a `lector.COLUMNAS` (y al esquema si debe guardarse) |
| Cambió una regla de limpieza | modificar y ejecutar `etl reprocesar` (o `POST /api/reprocesar`) |
| Nuevo período en el sistema de Centro de Cálculo | agregarlo a `catalogos.PERIODOS` |
| Cambio de esquema | subir `db.ESQUEMA_VERSION`: la base se reconstruye sola desde los originales |
| Nuevo tipo de documento | lector propio + registro en `documentos.TIPOS` (y decidir si `alimenta_predicciones`) |
| Ajustar el modelo de predicción | `PRED_AMORTIGUAMIENTO`, `PRED_NIVEL` en `.env`; el método está en `predicciones.py` |
