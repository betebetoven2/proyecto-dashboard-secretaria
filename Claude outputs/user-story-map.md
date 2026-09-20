# User Story Mapping — Dashboard de Asignados
### Secretaría Académica · Escuela de Ingeniería en Ciencias y Sistemas (ECYS) · Facultad de Ingeniería, USAC

> **Documento contrato.** Todo lo que se construya en el MVP debe poder trazarse a una historia de este mapa.
> Si una funcionalidad no aparece aquí, no entra; si una historia de Release 1 no está implementada, el MVP no está completo.

---

## 1. Contexto y naturaleza del dato

**Origen.** Centro de Cálculo / Facultad de Ingeniería emite el reporte *"TOTAL DE ASIGNADOS"* por semestre. Es un **snapshot**: una fotografía con fecha y hora (`09/09/2026 13:06` en el archivo de prueba, Primer Semestre 2026). No hay acceso a la base de datos transaccional.

**Consecuencias de diseño que no son negociables:**

| Hecho | Consecuencia |
|---|---|
| Solo lectura, sin API de origen | El sistema **nunca escribe** hacia el origen. Es un visor analítico. |
| El dato llega por archivo | El ETL debe ser idempotente y tolerante a variaciones de formato entre emisiones. |
| Es una fotografía, no un vivo | Todo número debe mostrarse **junto a la fecha/hora del snapshot**. Un KPI sin fecha es un KPI que engaña. |
| Llegarán varios archivos | El modelo guarda **N snapshots**, no "el actual". La comparación entre fotografías es la funcionalidad más valiosa a mediano plazo. |
| Datos agregados, sin carné ni nombre de estudiante | **No hay datos personales de estudiantes.** Solo conteos. Esto reduce el riesgo de protección de datos casi a cero y debe mantenerse así. Sí hay nombres de catedráticos y auxiliares (dato laboral, uso interno). |

**Lo que el archivo contiene realmente** (medido, no supuesto — snapshot 2026-S1):

- 2 hojas: `Clase` (926 secciones) y `Laboratorio` (452 secciones).
- 337 cursos distintos de **toda la Facultad**, no solo de ECYS.
- 40,869 asignaciones totales (30,865 en clase + 10,004 en laboratorio).
- 476 catedráticos, 179 auxiliares de cátedra en 367 secciones.
- 80 combinaciones edificio-salón; edificios `T-1, T-3, T-5, T-7, S-11, S-12, ET` (presencial) y `HIBR, MEET, EPS, EXT` (virtual/híbrido/externo).
- Columnas de procedencia (`Otra Fac.`, `Centros Reg.`, `Otra Univ.`, `No insc.`, `Est. Cierre`, `Otro caso`) **existen pero vienen en cero** en este snapshot. El modelo las conserva; la UI las oculta cuando no hay dato, en lugar de mostrar seis ceros que parecen un error.
- Del universo total, **87 secciones de clase y 62 de laboratorio** corresponden a códigos del área de Sistemas (0768–0799, 0960–0991, 2009, 7999) = 3,975 + 2,704 asignaciones.

**Decisión de alcance (acordada):** el dashboard cubre **toda la Facultad sin sesgo**, con el área como un filtro más. Razón: los estudiantes de ECYS consumen masivamente cursos de servicio (matemática, física, idioma técnico) que la Escuela no administra pero que determinan si sus estudiantes avanzan. Un dashboard recortado al código 07xx sería ciego justo donde está el cuello de botella.

---

## 2. La persona

**Rol:** Secretaría Académica de Escuela.
**Trabajo real:** es el punto donde se cruzan tres presiones — la demanda de los estudiantes, la disponibilidad de catedráticos y auxiliares, y los salones y horarios que asigna la Facultad. Su ciclo es semestral y repetitivo, y hoy se resuelve abriendo el Excel y filtrando a mano.

**Sus preguntas, en el orden en que le llegan:**

1. ¿Cómo va la asignación este semestre comparada con lo que esperábamos?
2. ¿Qué cursos se desbordaron y qué secciones quedaron vacías? ¿Abro, cierro o muevo?
3. ¿Con cuántos estudiantes por catedrático estamos operando? ¿A quién le pido auxiliar y con qué número lo justifico?
4. ¿Los salones y horarios que nos dieron alcanzan? ¿Hay traslapes?
5. Un estudiante pregunta por cupo en un curso: ¿dónde queda espacio?
6. Dirección de Escuela / Decanatura / acreditación me pide un número: ¿de dónde lo saco y cómo lo respaldo?

**Dolores actuales (hipótesis a validar con la persona real):**

- El Excel tiene la información pero no la respuesta: filtrar 1,378 filas a mano para responder "¿cuántas secciones de Estructuras de Datos están sobre el 90% de cupo?" toma minutos y no queda registro.
- Cada consulta de Dirección se responde rearmando el mismo filtro desde cero.
- No hay memoria: no se puede comparar la fotografía de hoy contra la de la semana pasada ni contra el semestre anterior, aunque los archivos existan en alguna carpeta.
- Los datos de clase y de laboratorio viven en hojas separadas, así que la brecha entre asignados a clase y a laboratorio (que es deserción temprana o problema de cupo de lab) es invisible. **Medida: 154 estudiantes de diferencia en el curso 0147, 80 en el 0150, 70 en el 0348.**

---

## 3. El mapa

### Backbone — actividades del usuario (secuencia real de trabajo)

```
A. Tomar el      B. Dimensionar   C. Equilibrar    D. Justificar    E. Verificar     F. Atender       G. Reportar y
   pulso del        la oferta        cupos y          docentes y       horarios,        consultas        respaldar
   semestre         por curso        secciones        auxiliares       salones y        puntuales        decisiones
                                                                       modalidad
```

### Release 1 — MVP (el esqueleto que camina)

Criterio de corte de Release 1: **la persona puede responder sus seis preguntas sin abrir el Excel.** Nada más.

| # | Actividad | Historia | Justificación | Dato que la alimenta | Criterio de aceptación |
|---|---|---|---|---|---|
| **R1-01** | A | Como secretaria académica quiero ver, al abrir el dashboard, **total de asignaciones, secciones, cursos y ocupación global**, con la fecha y hora del snapshot visible | Es el encabezado de cualquier conversación con Dirección. Hoy ese número se calcula a mano cada vez. La ocupación global del snapshot es 48.7% en clase y 62.7% en laboratorio: un dato que cambia la lectura de "estamos llenos". | `Total`, `Límite de asignados`, conteo de secciones/cursos, encabezado del reporte | Los KPI cuadran contra una suma directa en Excel. La fecha del snapshot aparece en pantalla, no en un tooltip. |
| **R1-02** | A | Quiero **filtrar todo el dashboard** por tipo (clase/laboratorio), área académica, jornada, modalidad y edificio | Sin filtros el dashboard es un reporte impreso. Con filtros es una herramienta. El área es el filtro que convierte un dashboard de Facultad en uno de ECYS. | Derivados: área por rango de código, jornada por hora de inicio, modalidad por edificio | Cada filtro recalcula KPI, gráficas y tabla de forma consistente; el estado del filtro es compartible por URL. |
| **R1-03** | B | Quiero ver los **cursos ordenados por demanda**, con número de secciones y promedio de estudiantes por sección | Es la base de la decisión de cuántas secciones abrir el próximo semestre. Ejemplo real: Matemática para Computación 1 tiene 282 asignados en 6 secciones (47/sección); Lógica de Sistemas tiene 197 en 3 (66/sección). Dos cursos del mismo nivel con densidades muy distintas. | Agregación por `Codigo`+`Nombre` | Top-N configurable; ordenable por asignados, secciones o promedio. |
| **R1-04** | C | Quiero una vista de **ocupación por sección**, clasificada en sobrecupo / saludable / en riesgo / vacía | Es la historia de mayor valor operativo del MVP. En el snapshot hay **29 secciones de clase en sobrecupo, 171 por debajo del 20% y 80 en cero**. Cada una de esas 280 secciones es una decisión pendiente: abrir otra, cerrar, o mover estudiantes. | `Total` vs `Límite de asignados` | Cada sección clasificada y navegable; se puede saltar de la categoría a la lista de secciones que la componen. |
| **R1-05** | C | Quiero identificar las **secciones vacías o casi vacías** para decidir cierres antes de que inicie el semestre | Una sección con 3 asignados consume un catedrático y un salón que otro curso necesita. Es dinero y es aula. | `Total`, `Límite mínimo de asignados` | Lista descargable, ordenada por ocupación ascendente. Nota visible: el campo `Límite mínimo` viene en cero en este snapshot, así que el umbral de cierre es un parámetro configurable, no un dato del archivo. |
| **R1-06** | D | Quiero ver **carga por catedrático**: secciones, estudiantes y horas semana | Con 476 catedráticos y casos de hasta 905 estudiantes en 10 secciones, la desigualdad de carga es real y hoy no es visible. Es el insumo de la conversación de asignación de cursos. | `Nombre` (docente), `Horas semana`, `Total` | Tabla ordenable; un docente lleva a sus secciones. |
| **R1-07** | D | Quiero ver **qué secciones tienen auxiliar de cátedra y cuántos estudiantes atiende cada auxiliar** | La solicitud de plazas de auxiliar se justifica con la relación estudiantes/auxiliar. Hoy: 367 de 926 secciones de clase tienen auxiliar (40%), 179 auxiliares distintos. Ese 60% sin auxiliar es exactamente el argumento que la Secretaría necesita documentar. | `Nombre miembro`, `Tipo miembro` (hasta 2 por sección) | Cobertura de auxiliares como KPI; lista de secciones de alta matrícula sin auxiliar. |
| **R1-08** | E | Quiero un **mapa de ocupación de salones por día y hora** | Permite ver si el horario que asignó la Facultad deja huecos aprovechables y en qué franjas hay saturación. | `Edificio`, `Salon`, `Hora Inicio/Final`, banderas `L…D` | Heatmap día × hora; celda muestra secciones y estudiantes. |
| **R1-09** | E | Quiero ver la **distribución presencial / híbrido / virtual** | Define necesidad de aula física y es un número que Decanatura pide. Medido: 311 de 926 secciones de clase son virtuales o híbridas, con 8,911 estudiantes. | `Edificio` ∈ {HIBR, MEET, EPS, EXT} | Desglose por secciones y por estudiantes (no son la misma historia). |
| **R1-10** | F | Quiero **buscar un curso, sección, docente o salón** y ver su ficha con todo lo asociado | Es la consulta puntual de mostrador: un estudiante pregunta, la Secretaría responde en segundos. | Todas las columnas | Búsqueda por texto libre sobre código, nombre, docente y salón, con respuesta inmediata. |
| **R1-11** | G | Quiero **exportar a CSV lo que estoy viendo filtrado** | Sin exportación, el dashboard se convierte en un lugar de donde se copia a mano. Con exportación, es la fuente del anexo de cualquier oficio. | Resultado de la consulta activa | El CSV respeta filtros y trae encabezado con fecha del snapshot. |
| **R1-12** | G | Quiero saber siempre **de qué archivo y de qué fecha** viene lo que veo | Trazabilidad. Un número sin procedencia no sirve para un oficio. | Metadatos del snapshot y nombre de archivo | Visible en el encabezado y en cada exportación. |

### Release 2 — lo que convierte el MVP en herramienta de decisión

| # | Actividad | Historia | Justificación |
|---|---|---|---|
| R2-01 | A, G | **Comparar dos snapshots** y ver el delta por curso y sección | Es el mayor salto de valor de todo el producto: contesta "¿cuánto creció la asignación desde el primer día?" y "¿qué curso se está desbordando ahora?". Requiere solo lo que el MVP ya guarda. |
| R2-02 | B | **Brecha clase vs laboratorio** por curso | Diferencias medidas de 154, 80 y 70 estudiantes. Señala falta de cupo en lab o abandono temprano. Hoy es invisible porque son dos hojas. |
| R2-03 | C | **Simulador**: "si cierro esta sección, ¿dónde caben sus estudiantes?" | Convierte el diagnóstico en decisión. Usa cupo libre por franja horaria. |
| R2-04 | E | **Detección de traslapes** de salón y de docente | El algoritmo preliminar detecta 123 solapes de salón. Requiere validación: los bloques contiguos de una misma sección producen falsos positivos, así que esta historia no entra al MVP sin reglas afinadas. |
| R2-05 | B | **Vista por nivel del pensum** (semestre 1–10) de Ciencias y Sistemas | Permite leer la demanda como cohortes y anticipar el próximo semestre. Requiere mapa código→semestre, que es dato externo al archivo. |
| R2-06 | D | **Histórico de carga docente** entre semestres | Insumo de equidad en la asignación y de la memoria de labores. |
| R2-07 | G | **Reporte PDF de una página**, listo para adjuntar a oficio | El formato en que la información realmente circula en la Facultad. |

### Release 3 — madurez

| # | Historia | Justificación |
|---|---|---|
| R3-01 | Tendencia multi-semestre por curso, con proyección de secciones a abrir | Planificación en lugar de reacción. |
| R3-02 | Alertas por umbral (sobrecupo, sección vacía, sección sin auxiliar) al cargar un snapshot | El sistema avisa en lugar de esperar a ser consultado. |
| R3-03 | Carga de snapshots desde la interfaz, con validación y control de versiones | Quita al equipo técnico del camino: la Secretaría carga sus propios archivos. |
| R3-04 | Panel público / para Dirección con vista restringida | Separa la vista operativa de la vista de gobierno. |
| R3-05 | Desagregación por procedencia (otra facultad, centros regionales, cierre de pensum) | Las columnas ya existen; cuando el origen las llene, la vista está lista. |

---

## 4. Fuera de alcance (explícito)

- Escribir o corregir datos del origen. El sistema es de lectura.
- Datos individuales de estudiantes (el archivo no los trae y no deben agregarse).
- Notas, actas, retiros, historial académico.
- Autenticación con el sistema de la Facultad (el MVP corre local, en red interna).
- Cualquier decisión automática. El dashboard informa; la persona decide.

---

## 5. Riesgos y supuestos

| Riesgo / supuesto | Manejo en el MVP |
|---|---|
| El área académica se infiere del rango de código, no viene en el archivo | Mapa de rangos explícito y editable en un solo archivo de configuración. Se documenta como heurística, no como verdad. |
| Una sección puede ocupar **varias filas** (bloques de horario), y las filas de continuación repiten el total | El ETL toma el total solo de la fila que lo trae y acumula los bloques de horario. Sin esta regla, los totales se inflan (1,378 filas → 1,378 secciones en lugar de 926+452). **Validado contra el archivo.** |
| `Límite mínimo de asignados` viene en cero | El umbral de "riesgo de cierre" es parámetro configurable, y se avisa en la UI que no proviene del archivo. |
| Columnas de procedencia en cero | Se conservan en el modelo; se ocultan en la UI cuando la suma es cero. |
| El formato del reporte puede cambiar entre emisiones | El ETL valida encabezados y falla con mensaje claro en lugar de cargar datos silenciosamente mal. |
| Nombres de docentes con dobles espacios, tildes inconsistentes y caracteres corruptos (`DISE\O`) | Normalización en el ETL; se conserva el valor original para trazabilidad. |
| Los dolores de la persona son hipótesis mías, no entrevista | Este mapa es el guion de la primera sesión de validación con la Secretaría. Las historias que no resuenen se bajan del Release 1. |

---

## 6. Trazabilidad implementación ↔ historia

| Historia | Endpoint / componente |
|---|---|
| R1-01, R1-12 | `GET /api/kpis`, encabezado del dashboard |
| R1-02 | Parámetros de filtro comunes en todos los endpoints |
| R1-03 | `GET /api/cursos` |
| R1-04, R1-05 | `GET /api/ocupacion`, `GET /api/secciones?estado=` |
| R1-06 | `GET /api/docentes` |
| R1-07 | `GET /api/auxiliares` |
| R1-08 | `GET /api/heatmap` |
| R1-09 | `GET /api/modalidad` |
| R1-10 | `GET /api/secciones?q=` |
| R1-11 | `GET /api/export.csv` |
| R2-01 | `GET /api/snapshots` (el modelo ya soporta N snapshots) |

---

*Elaborado a partir del análisis del snapshot `Asignados_Condensado testeo.xlsx` (Primer Semestre 2026, corte 09/09/2026 13:06) y de la estructura curricular publicada de la carrera. Pendiente de validación con la Secretaría Académica de ECYS.*
