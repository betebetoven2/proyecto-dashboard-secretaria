"""
Predicción de la demanda por curso para el siguiente período del mismo tipo.

Pregunta que responde
---------------------
«¿Cuántos estudiantes se asignarán a cada curso en el PRÓXIMO <período> y,
por lo tanto, cuántas secciones conviene abrir?» — p. ej., con los reportes de
Primer Semestre 2023-2026, estimar Primer Semestre 2027.

Por qué se compara solo el mismo tipo de período
-------------------------------------------------
Vacaciones, finales, retrasadas e intensivos tienen escalas y dinámicas que no
tienen nada que ver con el semestre ordinario (en vacaciones 2025 hubo 9,184
asignaciones; en Primer Semestre 2026, 40,869). Mezclarlos produciría
"tendencias" falsas. Cada serie es:

    (tipo de documento, tipo de período, Clase/Laboratorio, código de curso)

y su observación anual es la suma de asignados en el ÚLTIMO corte de ese año.
Es el mismo criterio que usa la literatura de pronóstico de matrícula por curso
(p. ej. Shao, SDSU: se entrena con los otoños previos para predecir el otoño
siguiente).

Modelo
------
Sobre z = log(1 + asignados):

1. Crecimiento anual observado de cada curso: r = Δz / Δaños (admite años
   faltantes), recortado a ±1 (×0.37 … ×2.7 por año) para que un curso que pasa
   de 0 a 50 no domine las estimaciones.

2. Encogimiento empírico-bayesiano (Efron y Morris, 1975): el crecimiento de un
   curso con pocos años se «encoge» hacia el crecimiento de su escuela:

       g_c = B_c·μ_escuela + (1 − B_c)·r̄_c,   B_c = (σ²/n_c) / (σ²/n_c + τ²)

   σ² = ruido año a año dentro de un curso, τ² = diferencias reales de
   crecimiento entre cursos (método de momentos, parte positiva), n_c = número de
   cambios anuales observados del curso. Con pocos años B_c ≈ 1 (se confía en la
   escuela); con muchos años estables B_c → 0 (se confía en el curso). Un curso
   nuevo, sin historia, recibe el crecimiento de su escuela.

3. Tendencia amortiguada (Gardner y McKenzie, 1985; Hyndman y Athanasopoulos):
   el crecimiento no se proyecta en línea recta sino amortiguado por φ:

       ẑ(T+h) = z_T + g_c·(φ + φ² + … + φ^h),   φ = 0.9 por defecto (rango 0.8–0.98)

4. Incertidumbre: Var = h·σ² + (Σφ^i)²·Var(g_c), con Var(g_c) la varianza
   posterior del crecimiento encogido. Intervalo al 80% (configurable) en escala
   logarítmica, transformado de vuelta (asimétrico, nunca negativo).

5. Validación honesta (Tashman, 2000; Hyndman y Koehler, 2006): origen móvil.
   Para cada año con al menos dos años previos se entrena solo con el pasado y se
   predice ese año; se compara contra el pronóstico ingenuo «igual que el año
   pasado». Se reporta el error relativo (< 1 = mejor que el ingenuo), el error
   porcentual ponderado y la cobertura real de los intervalos.

Uso para planificación
----------------------
- secciones sugeridas = secciones de hoy + una por cada cupo de sección COMPLETO
  de demanda que se espera ganar (o − una por cada cupo completo que se espera
  perder):

      sugeridas = abiertas + trunc((predicción − asignados hoy) / cupo típico por sección)

  La oferta de secciones es muy estable año con año: con los reportes reales de
  2021-2026, «las mismas secciones del año pasado» acierta mejor que escalar las
  secciones por el crecimiento o que cubrir el escenario alto (que sugería 150-400
  secciones de más). Esta regla conserva esa estabilidad y solo propone cambios
  cuando la demanda esperada llena o vacía una sección entera;
- probabilidad de sobrecupo = P(demanda > cupo actual del curso): señala los
  cursos donde hará falta más cupo (más secciones o un límite mayor).

Sin dependencias externas: solo la biblioteca estándar de Python.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist, median

from . import config

LIM_TASA = 1.0              # recorte de la tasa anual de crecimiento logarítmico
SIGMA_PREVIA = 0.15         # ruido anual supuesto cuando aún no se puede estimar (~15%)
PROPORCION_RUIDO = 0.75     # con 2 años: parte de la variación entre cursos tratada como ruido
MIN_SERIES_GRUPO = 3        # Efron-Morris: el encogimiento hacia un grupo requiere k ≥ 3


@dataclass
class Serie:
    clave: tuple
    grupo: str
    puntos: dict[int, float]                     # año -> asignados
    info: dict = field(default_factory=dict)     # curso, cupo, secciones… del último año

    def anios(self) -> list[int]:
        return sorted(self.puntos)

    def tasas(self) -> list[float]:
        a = self.anios()
        out = []
        for t0, t1 in zip(a, a[1:]):
            r = (math.log1p(self.puntos[t1]) - math.log1p(self.puntos[t0])) / (t1 - t0)
            out.append(max(-LIM_TASA, min(LIM_TASA, r)))
        return out


@dataclass
class Modelo:
    phi: float
    nivel: float
    sigma2: float
    tau2: float
    mu_global: float
    mu_grupo: dict[str, float]
    var_mu: float
    series_con_tasas: int
    sigma_estimada: bool
    tau_estimada: bool

    def resumen(self) -> dict:
        return {
            "metodo": "Crecimiento logarítmico con encogimiento empírico-bayesiano y tendencia amortiguada",
            "amortiguamiento_phi": self.phi,
            "nivel_intervalo": self.nivel,
            "ruido_anual_sigma": round(math.sqrt(self.sigma2), 4),
            "variacion_entre_cursos_tau": round(math.sqrt(self.tau2), 4),
            "crecimiento_global_anual": round(math.expm1(self.mu_global), 4),
            "crecimiento_por_grupo": {g: round(math.expm1(m), 4) for g, m in sorted(self.mu_grupo.items())},
            "series_con_historia": self.series_con_tasas,
            "sigma_estimada_con_datos": self.sigma_estimada,
            "tau_estimada_con_datos": self.tau_estimada,
        }


def ajustar(series: list[Serie], phi: float, nivel: float) -> Modelo | None:
    """Estima σ², τ², μ global y μ por grupo. None si ninguna serie tiene dos años."""
    con_tasas = [(s, s.tasas()) for s in series]
    con_tasas = [(s, r) for s, r in con_tasas if r]
    if not con_tasas:
        return None

    # σ²: variación de las tasas alrededor de la media de cada curso (dentro de curso)
    ss = sum(sum((x - sum(r) / len(r)) ** 2 for x in r) for _, r in con_tasas if len(r) >= 2)
    gl = sum(len(r) - 1 for _, r in con_tasas if len(r) >= 2)
    medias = [(s, sum(r) / len(r), len(r)) for s, r in con_tasas]
    pesos = sum(n for _, _, n in medias)
    mu = sum(m * n for _, m, n in medias) / pesos

    if len(medias) >= 2:
        v_entre = sum((m - mu) ** 2 for _, m, _ in medias) / (len(medias) - 1)
    else:
        v_entre = None

    sigma_estimada = gl >= 2
    if sigma_estimada:
        sigma2 = ss / gl
    elif v_entre is not None and v_entre > 0:
        sigma2 = PROPORCION_RUIDO * v_entre       # con un solo cambio por curso no se separan
    else:
        sigma2 = SIGMA_PREVIA ** 2
    sigma2 = max(sigma2, 1e-4)

    tau_estimada = v_entre is not None
    if v_entre is None:
        tau2 = 0.0
    else:
        tau2 = max(0.0, v_entre - sum(sigma2 / n for _, _, n in medias) / len(medias))

    mu_grupo: dict[str, float] = {}
    grupos: dict[str, list] = {}
    for s, m, n in medias:
        grupos.setdefault(s.grupo, []).append((m, n))
    for g, lst in grupos.items():
        if len(lst) >= MIN_SERIES_GRUPO:
            mu_grupo[g] = sum(m * n for m, n in lst) / sum(n for _, n in lst)

    return Modelo(phi=phi, nivel=nivel, sigma2=sigma2, tau2=tau2, mu_global=mu,
                  mu_grupo=mu_grupo, var_mu=sigma2 / pesos + tau2 / len(medias),
                  series_con_tasas=len(medias), sigma_estimada=sigma_estimada,
                  tau_estimada=tau_estimada)


def pronosticar(modelo: Modelo, serie: Serie, anio_objetivo: int) -> dict | None:
    if not serie.puntos:
        return None
    ultimo = max(serie.puntos)
    h = anio_objetivo - ultimo
    if h < 1:
        return None
    r = serie.tasas()
    n = len(r)
    mu = modelo.mu_grupo.get(serie.grupo, modelo.mu_global)
    if n == 0:
        b, g = 1.0, mu
        var_g = modelo.tau2 + modelo.var_mu
    else:
        rbar = sum(r) / n
        if modelo.tau2 > 0:
            b = (modelo.sigma2 / n) / (modelo.sigma2 / n + modelo.tau2)
            var_g = 1.0 / (n / modelo.sigma2 + 1.0 / modelo.tau2)
        else:
            b = 1.0
            var_g = modelo.var_mu
        g = b * mu + (1 - b) * rbar

    suma_phi = sum(modelo.phi ** i for i in range(1, h + 1))
    z0 = math.log1p(serie.puntos[ultimo])
    zh = z0 + g * suma_phi
    sd = math.sqrt(h * modelo.sigma2 + suma_phi ** 2 * var_g)
    q = NormalDist().inv_cdf(0.5 + modelo.nivel / 2)
    p50 = max(0.0, math.expm1(zh))
    bajo = max(0.0, math.expm1(zh - q * sd))
    alto = max(0.0, math.expm1(zh + q * sd))

    out = {
        "ultimo_anio": ultimo,
        "ultimo_valor": serie.puntos[ultimo],
        "historia": [{"anio": a, "asignados": serie.puntos[a]} for a in serie.anios()],
        "anios_historia": len(serie.puntos),
        "prediccion": round(p50, 1),
        "intervalo_bajo": round(bajo, 1),
        "intervalo_alto": round(alto, 1),
        "crecimiento_anual": round(math.expm1(g), 4),
        "peso_propio": round(1 - b, 3),
        "z": zh, "sd": sd,
    }
    out["confiabilidad"] = ("alta" if len(serie.puntos) >= 4 and sd < 0.15
                            else "media" if len(serie.puntos) >= 3 or sd < 0.30 else "baja")

    cupo = serie.info.get("cupo") or 0
    cupo_seccion = serie.info.get("cupo_por_seccion")
    abiertas = serie.info.get("abiertas") or 0
    out["secciones_actuales"] = abiertas
    out["cupo_actual"] = cupo
    out["cupo_por_seccion"] = cupo_seccion
    if cupo_seccion:
        # Incremental: se conserva la oferta actual y solo se agrega (o quita) una sección
        # por cada cupo completo de demanda que se espera ganar (o perder). Ver docstring.
        cambio = int((p50 - serie.puntos[ultimo]) / cupo_seccion)
        out["secciones_sugeridas"] = max(abiertas + cambio, 1 if p50 >= 1 else 0)
        out["cambio_secciones"] = out["secciones_sugeridas"] - abiertas
    else:
        out["secciones_sugeridas"] = None
        out["cambio_secciones"] = None
    out["prob_sobrecupo"] = (round(1 - NormalDist(zh, sd).cdf(math.log1p(cupo)), 3)
                             if cupo > 0 else None)
    return out


def validar(series: list[Serie], phi: float, nivel: float) -> dict:
    """Validación con origen móvil contra el pronóstico ingenuo."""
    anios = sorted({a for s in series for a in s.puntos})
    detalle = []
    e_mod = e_ing = total_real = 0.0
    dentro = n_total = 0
    for j in range(2, len(anios)):
        objetivo = anios[j]
        previos = [a for a in anios if a < objetivo]
        entreno = [Serie(s.clave, s.grupo, {a: v for a, v in s.puntos.items() if a < objetivo}, s.info)
                   for s in series]
        modelo = ajustar([s for s in entreno if s.puntos], phi, nivel)
        if modelo is None:
            continue
        em = ei = real = 0.0
        d = n = 0
        for s, completo in zip(entreno, series):
            if not s.puntos or max(s.puntos) != previos[-1] or objetivo not in completo.puntos:
                continue
            p = pronosticar(modelo, s, objetivo)
            y = completo.puntos[objetivo]
            em += abs(y - p["prediccion"])
            ei += abs(y - s.puntos[previos[-1]])
            real += y
            d += int(p["intervalo_bajo"] <= y <= p["intervalo_alto"])
            n += 1
        if n:
            detalle.append({"anio": objetivo, "cursos": n,
                            "error_modelo": round(em, 1), "error_ingenuo": round(ei, 1),
                            "error_relativo": round(em / ei, 3) if ei else None,
                            "wape": round(em / real, 4) if real else None,
                            "cobertura": round(d / n, 3)})
            e_mod += em
            e_ing += ei
            total_real += real
            dentro += d
            n_total += n
    if not detalle:
        return {"disponible": False,
                "motivo": "Se necesitan al menos 3 años del mismo período para validar el modelo."}
    return {
        "disponible": True,
        "anios_evaluados": [x["anio"] for x in detalle],
        "error_relativo": round(e_mod / e_ing, 3) if e_ing else None,
        "wape_modelo": round(e_mod / total_real, 4) if total_real else None,
        "wape_ingenuo": round(e_ing / total_real, 4) if total_real else None,
        "cobertura_intervalo": round(dentro / n_total, 3),
        "nivel_intervalo": nivel,
        "detalle": detalle,
    }


def construir_series(filas: list[dict], clave_cols: tuple[str, ...], grupo_col: str) -> list[Serie]:
    """filas: una por (año, serie) con 'anio', 'asignados' y las columnas de clave.
    La información descriptiva se toma del año más reciente de cada serie."""
    series: dict[tuple, Serie] = {}
    for f in sorted(filas, key=lambda x: x["anio"]):
        clave = tuple(f[c] for c in clave_cols)
        s = series.get(clave)
        if s is None:
            s = series[clave] = Serie(clave, f.get(grupo_col) or config.SIN_CLASIFICAR, {})
        s.puntos[f["anio"]] = float(f["asignados"] or 0)
        s.grupo = f.get(grupo_col) or s.grupo
        limites = [int(x) for x in str(f.get("limites") or "").split(",") if x.strip()]
        s.info = {k: f.get(k) for k in ("curso", "escuela", "area", "tipo", "codigo", "abiertas", "cupo")}
        s.info["cupo_por_seccion"] = median(limites) if limites else None
    return list(series.values())


def predecir(filas: list[dict], anio_objetivo: int | None = None) -> dict:
    """Punto de entrada: filas por (año, tipo de sección, curso) de UN tipo de período."""
    phi = min(0.98, max(0.8, config.PRED_AMORTIGUAMIENTO))
    nivel = min(0.95, max(0.5, config.PRED_NIVEL))
    anios = sorted({f["anio"] for f in filas})
    if len(anios) < 2:
        return {"disponible": False, "anios": anios}
    objetivo = anio_objetivo or anios[-1] + 1

    cursos = construir_series(filas, ("tipo", "codigo"), "escuela")
    modelo = ajustar(cursos, phi, nivel)
    if modelo is None:
        return {"disponible": False, "anios": anios}
    resultados = []
    no_ofertados = []
    for s in cursos:
        if max(s.puntos) != anios[-1]:
            no_ofertados.append({**s.info, "ultimo_anio": max(s.puntos)})
            continue
        p = pronosticar(modelo, s, objetivo)
        if p:
            resultados.append({**s.info, **p})

    # Totales por escuela y de la Facultad: misma técnica sobre series agregadas.
    agregadas: dict[tuple, dict[int, float]] = {}
    for f in filas:
        for clave in (("FACULTAD",), ("ESCUELA", f.get("escuela") or config.SIN_CLASIFICAR)):
            agregadas.setdefault(clave, {}).setdefault(f["anio"], 0.0)
            agregadas[clave][f["anio"]] += float(f["asignados"] or 0)
    series_tot = [Serie(k, "TOTALES", v) for k, v in agregadas.items()]
    modelo_tot = ajustar(series_tot, phi, nivel)
    totales = {}
    for s in series_tot:
        if max(s.puntos) == anios[-1] and modelo_tot:
            p = pronosticar(modelo_tot, s, objetivo)
            totales[" / ".join(s.clave[1:]) or "FACULTAD"] = {
                k: p[k] for k in ("historia", "prediccion", "intervalo_bajo", "intervalo_alto",
                                  "crecimiento_anual")}
    return {
        "disponible": True,
        "anios": anios,
        "anio_objetivo": objetivo,
        "modelo": modelo.resumen(),
        "validacion": validar(cursos, phi, nivel),
        "cursos": resultados,
        "no_ofertados": no_ofertados,
        "totales": totales,
    }
