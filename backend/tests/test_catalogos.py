"""Catálogo de períodos (21 de Centro de Cálculo) y heurística de clasificación de cursos."""

from __future__ import annotations

from backend.app import catalogos, config

# Lista tomada del diálogo «Contadores asignados (Condensado)» del sistema de Centro de Cálculo.
PERIODOS_SISTEMA = {
    "01": "PRIMER SEMESTRE", "02": "VACACIONES DEL PRIMER SEMESTRE",
    "03": "PRIMERA RETRASADA DEL PRIMER SEMESTRE", "04": "SEGUNDA RETRASADA DEL PRIMER SEMESTRE",
    "05": "SEGUNDO SEMESTRE", "06": "VACACIONES DEL SEGUNDO SEMESTRE",
    "07": "PRIMERA RETRASADA DEL SEGUNDO SEMESTRE", "08": "SEGUNDA RETRASADA DEL SEGUNDO SEMESTRE",
    "09": "SUFICIENCIA PRIMER SEMESTRE", "10": "SUFICIENCIA SEGUNDO SEMESTRE",
    "11": "EQUIVALENCIA SIN FECHA", "12": "CODIGO SIN UTILIZAR",
    "13": "SIN PERIODO PARA EXAMENES GENERALES", "14": "FINALES DEL PRIMER SEMESTRE",
    "15": "FINALES DEL SEGUNDO SEMESTRE", "16": "PRIMER INTENSIVO - PRIMER SEMESTRE",
    "17": "SEGUNDO INTENSIVO - PRIMER SEMESTRE", "18": "PRIMER INTENSIVO - SEGUNDO SEMESTRE",
    "19": "SEGUNDO INTENSIVO - SEGUNDO SEMESTRE",
    "20": "EXAMEN UBICACIÓN IDIOMA TÉCNICO - PRIMER SEMESTRE",
    "21": "EXAMEN UBICACIÓN IDIOMA TÉCNICO - SEGUNDO SEMESTRE",
}


def test_catalogo_de_periodos_completo():
    assert len(catalogos.PERIODOS) == 21
    for codigo, nombre in PERIODOS_SISTEMA.items():
        p = catalogos.periodo_por_nombre(nombre)
        assert p is not None and p.codigo == codigo, nombre
        assert catalogos.periodo_por_codigo(codigo).nombre == nombre


def test_periodos_sin_tildes_y_espacios():
    assert catalogos.periodo_por_nombre("examen  ubicacion idioma tecnico - primer semestre").codigo == "20"


def test_orden_cronologico():
    orden = lambda c: catalogos.periodo_por_codigo(c).orden  # noqa: E731
    assert orden("01") < orden("02") < orden("05") < orden("06")


def test_heuristica_contra_catalogo_real():
    """La regla por código debe coincidir con la escuela real en al menos 90% de los
    140 cursos del catálogo semilla (tomado de un reporte que sí trae Escuela)."""
    semilla = catalogos.cargar_semilla()
    aciertos = sum(1 for f in semilla
                   if (catalogos.clasificacion_heuristica(f["codigo"], f["curso"]) or ("",))[0]
                   == catalogos.normalizar(f["escuela"]))
    assert aciertos / len(semilla) >= 0.90, f"{aciertos}/{len(semilla)}"


def test_cursos_clave_de_sistemas():
    for codigo in ("0281", "0283", "0285", "0770", "0772", "0796", "0964", "0970", "0972"):
        assert catalogos.clasificacion_heuristica(codigo, "")[0] == config.ESCUELA_FOCO, codigo
    assert catalogos.clasificacion_heuristica("2009", "PRACTICAS FINALES CIENCIAS Y SISTEMAS")[0] == config.ESCUELA_FOCO
    assert catalogos.clasificacion_heuristica("7999", "SEMINARIO DE INV. E.P.S. SISTEMAS")[0] == config.ESCUELA_FOCO
    # 0960 Matemática para computación pertenece a CIENCIAS, no a Sistemas (dato real)
    assert catalogos.clasificacion_heuristica("0960", "")[0] == "CIENCIAS"
