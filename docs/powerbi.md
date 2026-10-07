# Contrato de datos para Power BI

El perfil del proyecto nombra a Power BI como capa de visualización y lo construye otro integrante del
equipo. Este sistema le entrega los datos ya limpios, validados y consolidados de todos los reportes
cargados, como **tablas planas por URL**: no requiere drivers ni acceso a la base.

## Conexión

Power BI Desktop → **Obtener datos → Web** → pegar la URL de cada tabla:

```
http://<servidor>:8000/api/powerbi/fact_seccion.csv
http://<servidor>:8000/api/powerbi/dim_snapshot.csv
http://<servidor>:8000/api/powerbi/dim_curso.csv
http://<servidor>:8000/api/powerbi/fact_gestion.csv
http://<servidor>:8000/api/powerbi/fact_miembro.csv
http://<servidor>:8000/api/powerbi/fact_horario.csv
http://<servidor>:8000/api/powerbi/bitacora_cargas.csv
```

Formato: CSV UTF-8 con BOM, separador `;`, primera fila = encabezados. En el asistente de Power Query:
*Origen del archivo: 65001 (UTF-8)*, *Delimitador: Punto y coma*.

Ejemplo de consulta M:

```m
let
    Origen = Csv.Document(
        Web.Contents("http://localhost:8000/api/powerbi/fact_seccion.csv"),
        [Delimiter=";", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),
    Tipos = Table.TransformColumnTypes(Encabezados, {
        {"seccion_id", Int64.Type}, {"snapshot_id", Int64.Type}, {"total", Int64.Type},
        {"limite", Int64.Type}, {"limite_min", Int64.Type}, {"ocupacion", type number},
        {"cerrada", Int64.Type}, {"sin_docente", Int64.Type}, {"con_auxiliar", Int64.Type}})
in
    Tipos
```

Actualizar en Power BI = volver a leer las URL: lo que la Secretaría cargue en el tablero aparece en Power BI
en la siguiente actualización. (Para actualización programada en Power BI Service se necesita una puerta de
enlace local, porque el servidor está en la red interna.)

## Modelo (esquema estrella)

```
                 dim_snapshot (snapshot_id)
                        │ 1
                        │ *
dim_curso (codigo) 1──* fact_seccion (seccion_id) 1──* fact_gestion
                                         │ 1──* fact_miembro
                                         └ 1──* fact_horario
```

| Relación | Cardinalidad |
|---|---|
| `dim_snapshot[snapshot_id]` → `fact_seccion[snapshot_id]` | 1 : * |
| `dim_curso[codigo]` → `fact_seccion[codigo]` | 1 : * |
| `fact_seccion[seccion_id]` → `fact_gestion[seccion_id]` | 1 : * |
| `fact_seccion[seccion_id]` → `fact_miembro[seccion_id]` | 1 : * |
| `fact_seccion[seccion_id]` → `fact_horario[seccion_id]` | 1 : * |

## Tablas

### dim_snapshot — un período en una fecha de corte
`snapshot_id, periodo_codigo (01–21), periodo_nombre, periodo_orden, semestre, anio, fecha_corte,
archivo_nombre, cargado_en, total_secciones, total_asignados`

Para el «último corte de cada período» filtrar por la `fecha_corte` máxima dentro de `anio + periodo_nombre`.
`periodo_orden` ordena los períodos cronológicamente dentro del año.

### fact_seccion — una sección en un snapshot
| Columna | Significado |
|---|---|
| `tipo` | Clase / Laboratorio |
| `escuela, area, subarea` | clasificación; `clasificacion_origen` dice si viene del archivo, del catálogo o de una regla |
| `modalidad` | Presencial, Híbrido, Virtual, Externo, Sin salón, Cerrada |
| `jornada` | Matutina, Vespertina, Nocturna |
| `docente` | vacío si el reporte dice STAFF (`sin_docente = 1`) |
| `regulares … otro_caso` | procedencia de los asignados |
| `total, limite, limite_min` | asignados, cupo, mínimo oficial |
| `ocupacion` | total / límite (vacío si cerrada o sin límite) |
| `estado` | Sobrecupo, Por llenarse, Saludable, Holgada, Riesgo de cierre, Sin asignados, Sin límite definido, Cerrada |
| `estado_gestion` | Al día, En revisión, Pendiente, Cerrada |
| `cerrada, con_auxiliar` | 0/1 |

**Medidas sugeridas (DAX):**

```dax
Asignados = SUM(fact_seccion[total])
Cupo abierto = CALCULATE(SUM(fact_seccion[limite]), fact_seccion[cerrada] = 0)
Ocupación = DIVIDE(CALCULATE([Asignados], fact_seccion[cerrada] = 0, fact_seccion[limite] > 0), [Cupo abierto])
Secciones abiertas = CALCULATE(COUNTROWS(fact_seccion), fact_seccion[cerrada] = 0)
Secciones con pendientes = CALCULATE(COUNTROWS(fact_seccion), fact_seccion[estado_gestion] = "Pendiente")
```

> Importante: **no sumar asignados entre snapshots distintos** (son fotografías del mismo período en fechas
> diferentes). Siempre filtrar por un `snapshot_id` o por el último corte.

### fact_gestion — una gestión derivada
`gestion_id, seccion_id, snapshot_id, clave, tipo, severidad (pendiente | revision), detalle`

Claves: `catedratico, salon, cupo, cierre, limite, auxiliar`. Reglas en `docs/user-story-map.md` §1.

### dim_curso
`codigo, curso, escuela, area, subarea, fuente (semilla | archivo)`

### fact_miembro, fact_horario
Terna de cada sección (`nombre, tipo`) y bloques de horario (`dia, hora_inicio, hora_fin`).

### bitacora_cargas
Cada intento de carga con su `resultado` (aceptado, reemplazo, duplicado, vacio, rechazado, eliminado).

## Tiempos de atención en Power BI

El cálculo de tiempos de atención (episodios entre cortes, cota superior, inicio censurado) ya está
implementado en `/api/tiempos`, que devuelve JSON. Para reproducirlo en Power BI: para cada
`(tipo, codigo, seccion, clave)` de `fact_gestion` dentro de un mismo `anio + periodo_nombre`, ordenar por
`fecha_corte` y medir los días entre el primer corte en que aparece y el primer corte posterior en que ya
no aparece.
