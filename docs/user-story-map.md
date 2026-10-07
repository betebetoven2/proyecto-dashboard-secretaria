# User Story Mapping — Dashboard de Asignados (v2)
### Secretaría Académica · Escuela de Ingeniería en Ciencias y Sistemas (ECYS) · Facultad de Ingeniería, USAC

> **Documento contrato.** Todo lo que se construye debe trazarse a una historia de este mapa, y el mapa
> debe trazarse al **perfil de prácticas finales aprobado** («Gestión documental de secretaría académica»,
> 16/08/2026). Si una funcionalidad no aparece aquí, no entra.
>
> **Cambios respecto a v1:** se incorporaron los tres archivos reales recibidos (vacaciones 2025 con formato
> de 33 columnas, finales 2023 vacío), el catálogo de 21 períodos de Centro de Cálculo, y las historias que el
> perfil exige y v1 no cubría: estado de gestiones, tiempos de atención, carga de archivos, trazabilidad,
> respaldo e instalación. Ver §6.

---

## 1. Alineación con el perfil aprobado

| Elemento del perfil | Cómo se cumple | Historias |
|---|---|---|
| Objetivo: *mejorar la visibilidad de procesos con herramientas de visualización* | Tablero web con 6 vistas, filtros comunes y exportación | R1-01 … R1-12 |
| Objetivo: *mejorar el flujo de datos con software automatizador o facilitador* | Carga por arrastrar y soltar, carpeta vigilada que carga sola, validación automática | R1-15, R1-16 |
| Objetivo: *modelo de datos centralizado que consolide en una sola fuente* | Réplica SQLite con N snapshots + archivo de originales como fuente de verdad | R1-12, R1-16, R1-17 |
| Objetivo: *rutinas ETL en Python que normalicen y reduzcan el trabajo manual* | `lector.py` + `ingesta.py`: limpieza documentada, totales de control, catálogo de cursos aprendido | R1-15 |
| Objetivo: *tablero con al menos tres vistas: seguimiento de cursos, estado de gestiones y tiempos de atención* | Pestañas **Vista 1 · Seguimiento de cursos**, **Vista 2 · Estado de gestiones**, **Vista 3 · Tiempos de atención** | R1-03, R1-13, R1-14, R2-01 |
| Objetivo: *validar con sesiones de revisión con el asesor* | Este mapa es el guion de la sesión; §7 lista las preguntas abiertas | — |
| Detalle técnico: Python 3.x, SQL relacional, Git | Python 3.12, SQLite, repositorio con CI | — |
| Detalle técnico: *Power BI como capa de visualización* | Lo trabaja otro integrante; este sistema le entrega un **contrato de datos** (tablas planas por URL) | R1-18 |
| Detalle técnico: *archivos CSV y hojas de cálculo como entrada* | Entrada: el .xlsx de Centro de Cálculo. Salida: CSV con procedencia | R1-11, R1-15 |
| Producto: *dashboard de centralización* | `/` | — |
| Producto: *modelo de datos y rutinas de carga documentadas* | `docs/arquitectura.md` | — |
| Producto: *código fuente estructurado y documentado* | Repositorio + 88 pruebas automáticas | — |
| Producto: *manual de usuario para la Secretaría* | `/manual` dentro del propio sistema | — |
| Producto: *documentación técnica* | `docs/arquitectura.md`, `docs/instalacion.md`, `docs/powerbi.md` | — |

### La decisión de diseño más importante: «gestiones» con el único formato que existe

El perfil imagina gestiones como constancias, retiros o equivalencias. **El único archivo disponible es el
reporte de asignados**, que no trae esos trámites. Por instrucción expresa, no se inventaron datos ni se
pidió un formato nuevo. En su lugar, las vistas 2 y 3 se construyen con los trámites que la Secretaría
**sí** resuelve sobre la oferta de cursos y que el reporte **sí** permite detectar:

| Gestión | Cómo se detecta en el reporte | Severidad |
|---|---|---|
| Asignación de catedrático | Sección abierta con catedrático `STAFF` | Pendiente |
| Asignación de salón | Sección presencial con salón `0000` / vacío | Pendiente |
| Ampliación de cupo / nueva sección | Asignados > límite de asignados | Pendiente |
| Revisión de cierre o fusión | Asignados < límite mínimo (o < 20% del cupo si el mínimo viene en 0) | Pendiente |
| Definición de límite de asignados | Hay asignados pero el límite es 0 | Pendiente |
| Plaza de auxiliar de cátedra | ≥ 60 estudiantes y ningún miembro «AUXILIAR» | En revisión |

Y el **tiempo de atención** se mide comparando **cortes** del mismo período: una gestión pendiente en un
corte que ya no aparece en el siguiente fue atendida entre ambas fechas. El perfil ya lo permite
(*«las vistas definitivas se ajustarán según los requerimientos que se definan con la Secretaría»*), y
esta adaptación debe validarse con el asesor (§7).

---

## 2. Naturaleza del dato (medido en los tres archivos reales)

| Hecho | Consecuencia |
|---|---|
| Solo lectura, sin acceso a la base de la Facultad | El sistema nunca escribe hacia el origen |
| El dato llega por archivo, emitido en cualquier momento, de cualquiera de **21 períodos** | El período, año y fecha de corte se leen del membrete; el nombre del archivo no importa |
| Un mismo período se puede descargar varias veces | Cada descarga es un **corte**: se guarda aparte y habilita evolución y tiempos |
| El formato **varía entre emisiones**: 30, 32 o 33 columnas; `Escuela/Area/Subarea` a veces sí y a veces no | Columnas resueltas por nombre; la clasificación que falta se completa con la de otros archivos |
| Cada hoja trae **totales de control** al pie (`TOTAL REG:` / `TOTAL:`) | Suma de verificación: si la lectura no cuadra con el pie, el archivo se rechaza |
| Un reporte puede venir **vacío** (finales 2023: sin encabezado, `TOTAL: 0`) | Se informa, no se guarda |
| Secciones cerradas: edificio `ET`, salón `CERRADO`, catedrático `STAFF` (154 de 343 en vacaciones 2025) | Se cuentan aparte; su cupo no es capacidad real |
| Una sección ocupa varias filas (un bloque de horario por fila) | Sin agrupar, los totales se inflan |
| `Límite mínimo de asignados` en 0 (2026-S1) o con dato (65 en vacaciones 2025) | El umbral de cierre usa el dato si existe, si no un parámetro declarado |
| Sin datos personales de estudiantes; sí nombres de catedráticos y auxiliares | Uso interno; el repositorio debe ser privado |

---

## 3. La persona

**Secretaría Académica de Escuela** (el perfil indica *«Cantidad de personas que atiende: 1»*). Su trabajo es
el cruce de tres presiones: demanda de estudiantes, disponibilidad de catedráticos y auxiliares, y salones y
horarios que asigna la Facultad. Hoy lo resuelve abriendo el Excel y filtrando a mano.

**Sus preguntas:**
1. ¿Cómo va la asignación de este período y cómo cambió desde la semana pasada?
2. ¿Qué secciones se desbordaron, cuáles no abren y qué trámite requiere cada una?
3. ¿Con cuántos estudiantes por catedrático estamos? ¿Dónde hace falta auxiliar y con qué número lo justifico?
4. ¿Los salones y horarios alcanzan?
5. Un estudiante pregunta por cupo: ¿dónde queda espacio?
6. Dirección me pide un número: ¿de dónde lo saco y cómo lo respaldo?
7. **(nueva)** ¿Cuánto estamos tardando en resolver cada tipo de trámite?
8. **(nueva)** Me llegó otro reporte: ¿cómo lo agrego sin pedirle nada a nadie?

---

## 4. El mapa

### Backbone

```
0. Alimentar    A. Tomar el   B. Dimensionar  C. Equilibrar   D. Justificar  E. Verificar   F. Atender   G. Reportar
   el tablero      pulso         la oferta       cupos           docentes y     horarios y     consultas    y respaldar
                                                                 auxiliares     salones
```

### Release 1 — MVP entregable (implementado y probado)

| # | Act. | Historia | Justificación (con dato real) | Criterio de aceptación |
|---|---|---|---|---|
| **R1-15** | 0 | Como secretaria quiero **subir uno o varios reportes arrastrándolos** y saber de inmediato si se cargaron | Es la única forma en que el dato entra. Sin esto, cada actualización depende de un técnico | Cada archivo recibe un resultado: cargado, ya estaba, reemplazó un corte, vacío o rechazado **con el motivo en español** |
| **R1-16** | 0 | Quiero **copiar los archivos a una carpeta** y que se carguen solos | Para cargas masivas o descargas automáticas | Lo cargado pasa a `procesados/`; lo rechazado a `rechazados/` con un `.txt` del motivo |
| **R1-17** | G | Quiero **respaldar y restaurar** todo con un comando | El dato se acumula semestre a semestre; perderlo es perder el historial | Un zip con los originales reconstruye la base completa |
| **R1-01** | A | Ver al abrir: asignaciones, ocupación, secciones abiertas y cerradas, secciones con gestiones pendientes, cobertura de auxiliares, con período y fecha de corte visibles | 2026-S1: 51.3% de ocupación del cupo abierto; 344 secciones con algún trámite pendiente | Los KPI cuadran con el pie del reporte (verificado en pruebas) |
| **R1-02** | A | Filtrar todo por tipo, **escuela**, área, jornada, modalidad, estado de ocupación y de gestión, y elegir **año → período → corte** | El selector replica el diálogo de Centro de Cálculo que la persona ya conoce | El filtro viaja en la URL y sobrevive al cambio de período |
| **R1-03** | B | Cursos por demanda, con secciones, promedio y gestiones pendientes | Base para decidir cuántas secciones abrir | Ordenable por 5 criterios |
| **R1-04** | C | Ocupación por sección: sobrecupo / por llenarse / saludable / holgada / riesgo de cierre / sin asignados / cerrada | 2026-S1: 46 en sobrecupo, 206 en riesgo, 74 vacías, 15 cerradas | Clic en una categoría filtra el tablero |
| **R1-05** | C | Riesgo de cierre usando el **mínimo oficial cuando viene en el reporte** | Vacaciones 2025 trae mínimo 65; 2026-S1 trae 0 | La interfaz dice cuál regla se aplicó |
| **R1-06** | D | Carga por catedrático (sin contar STAFF) | — | Clic lleva a sus secciones |
| **R1-07** | D | Auxiliares, secciones grandes sin auxiliar y **tipos de miembro** (p. ej. «responsable de carga de notas») | 2026-S1: 29% de secciones abiertas con auxiliar | — |
| **R1-08** | E | Ocupación por día y hora; salones más usados | — | Solo secciones abiertas |
| **R1-09** | E | Modalidad (presencial, híbrido, virtual, externo, sin salón, cerrada) y jornada | — | — |
| **R1-10** | F | Búsqueda libre por curso, código, sección, catedrático, salón o auxiliar | Consulta de mostrador | — |
| **R1-11** | G | Exportar a CSV lo filtrado, con archivo de origen, huella y corte en la cabecera | Anexo de oficio con procedencia | Abre bien en Excel (tildes) y no ejecuta fórmulas |
| **R1-12** | G | Saber siempre de qué archivo y corte viene lo que veo, y **descargar el original** | Trazabilidad | Visible en el encabezado |
| **R1-13** | C | **Vista 2 · Estado de gestiones**: proporción al día / en revisión / pendiente por curso, y lista de trabajo | Es el boceto del perfil, alimentado con dato real | Exportable a CSV |
| **R1-14** | A | **Vista 3 · Tiempos de atención**: días promedio por tipo de gestión contra la meta institucional | Boceto del perfil (meta de 6 días, configurable) | Con un solo corte, la vista explica qué falta en vez de mostrar ceros |
| **R1-18** | G | Entregar al equipo de Power BI **tablas planas por URL** (hechos y dimensiones) | El perfil nombra Power BI; otro integrante lo construye | `docs/powerbi.md` |

### Release 2 — siguiente iteración

| # | Historia | Estado |
|---|---|---|
| R2-01 | Evolución entre cortes y cambios por curso; histórico por período | **Adelantado al MVP** (Vista 1) |
| R2-02 | Brecha clase vs laboratorio por curso | Pendiente |
| R2-03 | Simulador: «si cierro esta sección, ¿dónde caben?» | Pendiente |
| R2-04 | Traslapes de salón y de catedrático | Pendiente (requiere afinar reglas de bloques contiguos) |
| R2-05 | Vista por nivel del pensum de Sistemas | Pendiente (requiere el mapa código → semestre) |
| R2-06 | Reporte PDF de una página para oficios | Pendiente |
| R2-07 | Descarga automática del reporte desde el sistema de Centro de Cálculo hacia la carpeta de entrada | Pendiente (depende de acceso institucional) |

### Release 3

Tendencia multi-semestre con proyección · alertas por umbral al cargar un corte · vista restringida para
Dirección · desagregación por procedencia (las columnas ya se cargan; vacaciones 2025 ya trae otra facultad
y centros regionales).

---

## 5. Fuera de alcance

Escribir en sistemas de la Facultad · datos individuales de estudiantes · notas, actas, retiros · autenticación
con el sistema de la Facultad (hay un token de administración opcional para subir/eliminar) · decisiones
automáticas.

---

## 6. Riesgos y supuestos

| Riesgo | Manejo |
|---|---|
| El formato del reporte cambia | Columnas por nombre; columnas nuevas se ignoran con advertencia; faltantes obligatorias rechazan el archivo con su nombre |
| Archivo editado a mano o incompleto | Suma de verificación contra el pie; rechazo con ambos números |
| Archivo equivocado (.xls viejo, con contraseña, CSV renombrado, HTML, descarga interrumpida) | Se detecta por contenido, no por extensión, con mensaje accionable |
| Archivos maliciosos (zip bomb, XML con entidades) | Tope de tamaño descomprimido y `defusedxml` |
| Clasificación por escuela sin columnas en el archivo | Catálogo aprendido de otros archivos → regla por código (93% de acierto medido) → «sin clasificar». Se marca «inferida» |
| «Gestiones» adaptadas al reporte de asignados | Validar con el asesor (§7). El modelo admite agregar tipos en `config.py` |
| Tiempos de atención con pocos cortes | Se reportan como cota superior y se marcan los de inicio desconocido |

---

## 7. Preguntas para la sesión de validación con el asesor

1. ¿Las seis gestiones derivadas corresponden a trámites reales de la Secretaría? ¿Falta alguna que el reporte permita detectar?
2. ¿La meta de 6 días aplica igual a todas las gestiones, o cada tipo tiene la suya?
3. ¿Con qué frecuencia se puede descargar el reporte durante la asignación (diaria, semanal)? Define la precisión de los tiempos.
4. ¿El umbral de 60 estudiantes para pedir auxiliar es el criterio institucional?
5. ¿La vista por defecto debe abrir en toda la Facultad o en Ciencias y Sistemas?

---

## 8. Trazabilidad historia ↔ implementación

| Historia | API | Interfaz | Prueba |
|---|---|---|---|
| R1-01 | `/api/kpis` | tarjetas superiores | `test_coherencia_de_kpis` |
| R1-02 | filtros comunes, `/api/periodos`, `/api/catalogos` | encabezado | `test_todos_los_endpoints_con_y_sin_filtros` |
| R1-03 | `/api/cursos` | Vista 1 | — |
| R1-04/05 | `/api/ocupacion` | Resumen | `test_real_vacaciones_2025_formato_33_columnas` |
| R1-06/07 | `/api/docentes`, `/api/auxiliares` | Docentes y auxiliares | — |
| R1-08/09 | `/api/heatmap`, `/api/salones`, `/api/distribucion/*` | Resumen, Vista 1 | — |
| R1-10 | `/api/secciones?q=` | Secciones | — |
| R1-11 | `/api/export.csv` | Exportar CSV | `test_exportacion_csv_y_proteccion_de_formulas` |
| R1-12 | `/api/snapshots/{id}/original` | encabezado | `test_original_y_eliminacion` |
| R1-13 | `/api/gestiones` | Vista 2 | `test_estado_de_gestiones` |
| R1-14 | `/api/tiempos` | Vista 3 | `test_tiempos_de_atencion_entre_cortes` |
| R1-15 | `POST /api/cargas` | `/cargas` | `test_lector.py`, `test_subida_*` |
| R1-16 | vigilante de carpeta | `entrada/` | `test_carpeta_de_entrada` |
| R1-17 | `etl respaldo` / `restaurar` | consola | `test_respaldo_y_restauracion` |
| R1-18 | `/api/powerbi/*` | — | `test_power_bi` |
| R2-01 | `/api/evolucion` | Vista 1 | `test_evolucion_muestra_cambios_por_curso` |
