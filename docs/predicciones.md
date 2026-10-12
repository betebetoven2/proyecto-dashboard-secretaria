# Predicciones de demanda por curso

Versión 1.2 · módulo `backend/app/predicciones.py` · vista **Predicciones** del tablero · `GET /api/predicciones`

## 1. Para qué sirven (y para qué no)

La Secretaría decide **antes** de cada período cuántas secciones abrir por curso, a cuántos catedráticos
y auxiliares solicitar y cuántos salones pedir. Hoy esas decisiones se toman mirando el período
anterior. La predicción responde con un número y un rango:

| Pregunta | Salida del modelo |
|---|---|
| ¿Cuántos estudiantes se asignarán a este curso el próximo Primer Semestre? | demanda esperada + intervalo del 80% |
| ¿Cuántas secciones abro? | secciones sugeridas frente a las abiertas hoy |
| ¿Qué cursos van a reventar el cupo si no hago nada? | probabilidad de sobrecupo con el cupo actual |
| ¿Cuánto crece cada curso / escuela / la Facultad? | crecimiento anual estimado |
| ¿Puedo confiar en estos números? | validación contra el pasado: error relativo y cobertura real |

Esto coincide con el uso que reporta la literatura: los pronósticos de matrícula por curso se usan para
planificar cupos, secciones, salones, catedráticos y auxiliares, y reducir cancelaciones de última hora
(Shao, SDSU), y se entrenan con el mismo término de años previos (otoños para predecir el otoño
siguiente), igual que aquí.

**No sirve para** predecir el comportamiento de estudiantes individuales (el reporte no los trae), ni
para períodos sin historia del mismo tipo, ni para reemplazar el criterio de la Secretaría: es un insumo.

## 2. Lo más importante: qué se compara con qué

El sistema recibe archivos que varían en **tres dimensiones independientes**. El modelo las trata así:

| Dimensión | Ejemplos | Tratamiento en las predicciones |
|---|---|---|
| **Tipo de documento** | hoy solo «Contadores asignados (Condensado)»; mañana podrían llegar otros reportes | Cada snapshot guarda `tipo_documento` (registro en `documentos.py`). Las predicciones solo leen el tipo `ASIGNADOS_CONDENSADO`. Un documento de otro tipo se rechaza al cargarlo, nunca se mezcla. |
| **Tipo de período** | 01 Primer semestre, 02 Vacaciones, 14 Finales… (21 en total) | **Nunca se mezclan.** Cada predicción usa un solo tipo de período a lo largo de los años. Vacaciones 2025 tuvo 9,184 asignaciones y Primer Semestre 2026 40,869: mezclarlos fabricaría una «caída» o un «crecimiento» falsos. |
| **Formato** | 30, 32 o 33 columnas; con o sin Escuela/Área | Irrelevante para el modelo: la serie se identifica por **(Clase/Laboratorio, código de curso)**, que existe en todos los formatos. La escuela se resuelve con el catálogo aprendido. Probado en `test_formatos_distintos_forman_la_misma_serie`. |
| **Cortes** | varias descargas del mismo período en el mismo año | Se usa **el último corte de cada año** como dato de ese año (`test_usa_el_ultimo_corte_de_cada_anio`). |

Por eso la serie de un curso es:

```
(tipo de documento, tipo de período, Clase|Laboratorio, código)  →  asignados por año (último corte)
```

## 3. Modelo

### 3.1 Notación

- `y(t)`: asignados del curso en el año `t` (suma de sus secciones, último corte).
- `z(t) = log(1 + y(t))`: escala logarítmica. Convierte crecimientos porcentuales en diferencias, admite
  ceros y produce intervalos asimétricos que nunca bajan de cero.

### 3.2 Crecimiento observado

Para cada par de años consecutivos con dato:

```
r = (z(t₁) − z(t₀)) / (t₁ − t₀)          # admite años faltantes
r ← recortado a [−1, 1]                   # ×0.37 … ×2.7 por año
```

El recorte evita que un curso que pasa de 0 a 50 estudiantes domine la estimación de los parámetros.

### 3.3 Encogimiento empírico-bayesiano (Efron y Morris, 1975)

Un curso con dos o tres años de historia tiene un crecimiento observado muy ruidoso. En lugar de creerle
por completo, se combina con el crecimiento de su escuela:

```
g_c = B_c · μ_escuela + (1 − B_c) · r̄_c

B_c = (σ² / n_c) / (σ² / n_c + τ²)
```

| Símbolo | Significado | Estimación |
|---|---|---|
| `r̄_c`, `n_c` | crecimiento promedio del curso y número de cambios anuales observados | directo |
| `σ²` | ruido año a año dentro de un curso | varianza combinada dentro de cursos (requiere ≥ 3 años); con 2 años, el 75% de la variación entre cursos |
| `τ²` | diferencias reales de crecimiento entre cursos | método de momentos, parte positiva: `max(0, Var(r̄) − media(σ²/n))` |
| `μ_escuela` | crecimiento típico de la escuela | promedio ponderado; si la escuela tiene < 3 cursos con historia, se usa el global (el resultado de Stein exige k ≥ 3) |

`1 − B_c` aparece en la tabla como **peso propio**: cuánto pesa la historia del curso frente a la de su
escuela. Un curso nuevo (un solo año) tiene peso propio 0 y recibe el crecimiento de su escuela.

En el ejemplo clásico de Efron y Morris (promedios de bateo), este estimador redujo el error cuadrático
total en ~71% frente a usar cada promedio por separado. La ganancia es mayor justamente cuando hay muchas
unidades parecidas y pocos datos por unidad, que es el caso de cientos de cursos con 2 a 6 años de
historia.

### 3.4 Tendencia amortiguada (Gardner y McKenzie, 1985)

El crecimiento no se proyecta como línea recta: se amortigua con `φ`:

```
ẑ(T + h) = z(T) + g_c · (φ + φ² + … + φʰ)          φ = 0.9 (configurable, 0.8–0.98)
```

La tendencia amortiguada es un método de referencia en la literatura de pronóstico (M-competition;
Hyndman y Athanasopoulos recomiendan `φ` entre 0.8 y 0.98) porque las tendencias en línea recta tienden a
sobre-pronosticar. Para el año siguiente (`h = 1`) equivale a usar el 90% del crecimiento estimado.

### 3.5 Incertidumbre

```
Var[ẑ] = h · σ² + (φ + … + φʰ)² · Var(g_c)

Var(g_c) = 1 / (n_c/σ² + 1/τ²)          si τ² > 0   (varianza posterior)
         = σ²/N + τ²/K                  si τ² = 0 o el curso no tiene historia

intervalo = exp(ẑ ± z_{0.90} · √Var) − 1                 # 80% por defecto
P(sobrecupo) = 1 − Φ((log(1 + cupo_actual) − ẑ) / √Var)
```

### 3.6 Secciones sugeridas

```
secciones = secciones_hoy + trunc( (predicción − asignados_hoy) / cupo típico por sección )
            (nunca menos de 1 si se espera demanda)
```

Se parte de la oferta actual y solo se suma (o quita) una sección por cada **cupo de sección completo**
de demanda que se espera ganar (o perder). La regla se eligió con los reportes reales 2021–2026
comparando, año por año, lo sugerido contra las secciones que de verdad se abrieron (§4.3): la oferta de
secciones es muy estable, y las reglas que escalaban las secciones con el crecimiento o cubrían el
escenario alto del intervalo sugerían entre 150 y 400 secciones de más.

Cuando un curso puede rebasar su cupo, la señal es la **probabilidad de sobrecupo** (§3.5): la decisión
puede ser abrir otra sección o subir el límite, y eso lo resuelve la Secretaría.

### 3.7 Totales

Los totales de la Facultad y de cada escuela se pronostican como series propias con el mismo método. Su
valor difiere en ~1% de la suma de las predicciones por curso (la mediana de una suma no es la suma de las
medianas): ambas son estimaciones válidas; la vista muestra las dos.

## 4. Validación

### 4.1 En cada instalación, con sus propios datos

Origen móvil (Tashman, 2000): para cada año que tiene al menos dos años previos, se entrena **solo con el
pasado**, se predice ese año y se compara con lo ocurrido y con el pronóstico ingenuo «igual que el año
pasado». La vista muestra:

| Métrica | Lectura |
|---|---|
| **Error relativo** = Σ\|error del modelo\| / Σ\|error del ingenuo\| | < 1: el modelo se equivoca menos que repetir el año anterior. Es una medida relativa libre de escala en el espíritu del MASE (Hyndman y Koehler, 2006) y, a diferencia del MAPE, no se indefine con cursos de 0 asignados. |
| **Error % ponderado (WAPE)** | error absoluto total / asignados totales |
| **Cobertura** | proporción de cursos que cayeron dentro del intervalo; debe acercarse al 80% |

Si el modelo no le gana al ingenuo, la vista lo dice.

### 4.2 Simulación con verdad conocida (`backend/tests/test_predicciones.py`)

150 cursos, 5 escuelas, crecimientos reales distintos por curso, 8 repeticiones por escenario:

| Escenario | Cobertura del intervalo 80% | Error relativo vs ingenuo |
|---|---|---|
| Con tendencia (σ = 0.10, τ = 0.05) | 0.80 | **0.84** (16% menos error) |
| Sin tendencia (paseo aleatorio) | 0.81 | 1.00 (empata: no hay nada que aprender) |
| Ruido alto (σ = 0.25) | 0.80 | 0.97 |
| Solo 2 años de historia | 0.79 | 0.87 |

Además recupera los parámetros (σ estimado 0.104 para σ real 0.10; τ 0.045 para τ real ≈ 0.05).

### 4.3 Con los reportes reales de la Facultad (Primer y Segundo Semestre 2021–2026)

Se cargaron los 12 reportes de 2021 a 2026. Los de 2024 venían recortados a 1000 filas por la herramienta
que los generó y se rechazaron (§6); la validación usa 2021, 2022, 2023, 2025 y 2026 y evalúa 2023, 2025 y
2026 (2025 se predice a dos años, desde 2023).

| Período | Error relativo vs ingenuo | Error típico por curso (WAPE) | Ingenuo | Cobertura del intervalo 80% |
|---|---|---|---|---|
| Primer Semestre | 1.05 | 26% | 25% | 78% |
| Segundo Semestre | 0.96 | 25% | 26% | 83% |

**Lectura honesta.** A nivel de curso, la demanda de un semestre se comporta casi como un paseo aleatorio:
el modelo **empata** con «igual que el año pasado» (±5%, dentro del ruido de tres años de prueba). Se
probaron alternativas sobre los mismos datos (amortiguamiento 0.5, tendencia solo del último año,
tendencia suavizada de Holt con β = 0.3–0.7, suavizado exponencial del nivel) y ninguna mejora de forma
consistente en ambos semestres (rango 0.92–1.07); cambiar el modelo por esas diferencias sería ajustarse
al ruido. El aporte del modelo en estos datos está en:

- **Intervalos calibrados**: 78–83% de los cursos cayeron dentro del intervalo del 80%. Dicen cuánto
  puede moverse cada curso, algo que «el año pasado» no dice.
- **Riesgo de sobrecupo** por curso con el cupo actual.
- **Secciones sugeridas** que siguen la demanda sin inventar cambios (§3.6).
- **Totales** de Facultad y escuela con su rango.

Las secciones sugeridas se validaron igual, contra las secciones realmente abiertas:

| Regla | Error absoluto total (secciones, promedio de 6 evaluaciones) |
|---|---|
| Versión 1.1: máx(al ritmo, escenario alto / cupo) | ≈ 410 |
| Al ritmo del crecimiento | ≈ 183 |
| **Versión 1.2: incremental por cupos completos** | **≈ 130** |
| «Las mismas del año pasado» | ≈ 130 |

**La validación que cuenta es la que la vista calcula con los reportes que estén cargados**: se recalcula
sola al agregar años.

## 5. Requisitos de datos

| Años del mismo tipo de período | Qué se obtiene |
|---|---|
| 1 | Nada. La vista explica qué cargar. |
| 2 | Predicciones con intervalos amplios; el ruido se aproxima (§3.3). Sin validación. |
| 3 | Predicciones + validación de un año. |
| 4 a 6 | Lo recomendable: σ y τ bien estimados, validación de varios años. |

**Cómo conseguir la historia hoy mismo:** en el sistema de Centro de Cálculo, *Contadores asignados
(Condensado)* permite elegir **cualquier año**. Descargue, por ejemplo, *01 : PRIMER SEMESTRE* de 2021 a
2026 y *05 : SEGUNDO SEMESTRE* de 2021 a 2025, y cárguelos todos de una vez en **Cargar reportes** (sueltos o
en un solo **.zip**).

## 6. Limitaciones

- **Período en curso:** si el último año todavía está en asignación, su dato está incompleto y la
  predicción saldrá baja. Use años cerrados o espere al corte final.
- **Cambios de pensum o de código** (un curso que cambia de código) rompen la serie: el curso nuevo arranca
  sin historia y recibe el crecimiento de su escuela.
- **Choques no recurrentes** (pandemia, cierres, cambios de reglamento) no se anticipan. En los datos reales,
  2021–2022 (clases virtuales) tienen 46–52 mil asignados por semestre y 2025–2026, 35–41 mil: esa caída
  pesa en el crecimiento estimado de la Facultad (−5% anual), aunque 2025→2026 subió. El intervalo lo
  refleja. Si la Secretaría considera que esos años ya no representan la situación, puede eliminarlos del
  tablero en «Cargar reportes» y la predicción se recalcula.
- **Archivos incompletos**: un reporte recortado por otra herramienta (p. ej. «truncated at 1000 rows»)
  se rechaza al cargarlo; si se cargara, el modelo creería que los cursos que faltan dejaron de ofrecerse.
  Faltar un año completo no es problema: el crecimiento se mide por año transcurrido.
- **Los cursos no ofertados el último año** no se predicen (se listan aparte).
- **Las secciones sugeridas** no consideran jornadas ni horarios: son un punto de partida, no un horario.

## 7. Configuración

| Variable (`.env`) | Por defecto | Efecto |
|---|---|---|
| `PRED_AMORTIGUAMIENTO` | 0.9 | `φ`; se limita a 0.8–0.98 |
| `PRED_NIVEL` | 0.8 | nivel del intervalo; se limita a 0.5–0.95 |

## 8. API

```
GET /api/predicciones?periodo=PRIMER SEMESTRE[&escuela=…&tipo=…&area=…&codigo=…&q=…]
GET /api/export/predicciones.csv?periodo=…
```

Los filtros de jornada, modalidad, edificio y estado **no** se aplican (cambian de un año a otro y
partirían las series); la respuesta los lista en `filtros_ignorados`.

## Referencias

- Efron, B. y Morris, C. (1975). *Data Analysis Using Stein's Estimator and Its Generalizations*. Journal
  of the American Statistical Association, 70(350), 311–319.
- Gardner, E. S. y McKenzie, E. (1985). *Forecasting Trends in Time Series*. Management Science, 31(10),
  1237–1246. Véase también Gardner y McKenzie, *Damped trend exponential smoothing: a modelling viewpoint*.
- Hyndman, R. J. y Athanasopoulos, G. *Forecasting: Principles and Practice* (3.ª ed.), §8.2 «Methods with
  trend». OTexts.
- Hyndman, R. J. y Koehler, A. B. (2006). *Another look at measures of forecast accuracy*. International
  Journal of Forecasting, 22(4), 679–688.
- Tashman, L. J. (2000). *Out-of-sample tests of forecasting accuracy: an analysis and review*.
  International Journal of Forecasting, 16(4), 437–450.
- Shao, L. et al. *Machine Learning Methods for Course Enrollment Prediction*. San Diego State University,
  Analytic Studies & Institutional Research.
