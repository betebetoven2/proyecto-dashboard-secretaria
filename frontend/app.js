/* Tablero · cada bloque está rotulado con la historia del user story mapping que atiende. */

const FILTROS = ['snapshot_id', 'tipo', 'escuela', 'area', 'jornada', 'modalidad', 'estado', 'estado_gestion', 'codigo', 'docente', 'q'];
const VISTAS = ['resumen', 'seguimiento', 'gestiones', 'tiempos', 'predicciones', 'docentes', 'secciones'];
const state = { filtros: {}, vista: 'resumen', offset: 0, limite: 100, orden: 'asignados', tabAux: 'ranking', periodos: [], catalogos: null };

const params = (extra = {}) => ({ ...state.filtros, ...extra });
const get = (ruta, extra) => api(ruta, { params: params(extra) });

/* ─────────────────────────── URL ─────────────────────────── */
function leerURL() {
  const p = new URLSearchParams(location.search);
  for (const k of FILTROS) if (p.get(k)) state.filtros[k] = p.get(k);
  const h = location.hash.replace('#', '');
  if (VISTAS.includes(h)) state.vista = h;
}
function escribirURL() {
  const p = new URLSearchParams();
  for (const k of FILTROS) if (state.filtros[k]) p.set(k, state.filtros[k]);
  history.replaceState(null, '', (p.toString() ? `?${p}` : location.pathname) + `#${state.vista}`);
}

/* ─────────────────────── selector año / período / corte ─────────────────────── */
function poblarSelector(snapId) {
  const arbol = state.periodos;
  let anio, periodo;
  for (const a of arbol) for (const p of a.periodos) if (p.cortes.some(c => c.id === snapId)) { anio = a; periodo = p; }
  if (!anio) { anio = arbol[0]; periodo = anio.periodos[0]; }

  $('#s-anio').innerHTML = arbol.map(a => `<option value="${a.anio}">${a.anio}</option>`).join('');
  $('#s-anio').value = anio.anio;
  $('#s-periodo').innerHTML = anio.periodos.map(p =>
    `<option value="${esc(p.periodo_nombre)}">${p.periodo_codigo ? p.periodo_codigo + ' : ' : ''}${esc(p.periodo_nombre)}</option>`).join('');
  $('#s-periodo').value = periodo.periodo_nombre;
  const cortes = [...periodo.cortes].sort((a, b) => b.fecha_corte.localeCompare(a.fecha_corte));
  $('#s-corte').innerHTML = cortes.map((c, i) =>
    `<option value="${c.id}">${fechaHumana(c.fecha_corte)}${i === 0 ? ' (más reciente)' : ''}</option>`).join('');
  $('#s-corte').value = snapId ?? cortes[0].id;
  $('#s-corte').disabled = cortes.length < 2;
  $('#s-corte').title = cortes.length < 2 ? 'Solo hay un corte cargado para este período' : '';
}

function elegirDesdeSelector(origen) {
  const anio = state.periodos.find(a => String(a.anio) === $('#s-anio').value);
  let periodo = anio.periodos.find(p => p.periodo_nombre === $('#s-periodo').value);
  if (origen === 'anio' || !periodo) periodo = anio.periodos[0];
  let id;
  if (origen === 'corte') id = +$('#s-corte').value;
  else id = [...periodo.cortes].sort((a, b) => b.fecha_corte.localeCompare(a.fecha_corte))[0].id;
  aplicar({ snapshot_id: String(id) }, { recargarCatalogos: true });
}

/* ═════════════════════ KPIs y notas (R1-01) ═════════════════════ */
async function renderKPIs() {
  const k = await get('/api/kpis');
  const tiles = [
    { k: 'Asignaciones', v: num(k.asignados), d: `${num(k.promedio_seccion)} por sección abierta` },
    { k: 'Ocupación del cupo', v: pct(k.ocupacion), d: `${num(k.cupo_libre)} lugares libres de ${num(k.cupo)}`, meter: k.ocupacion },
    { k: 'Secciones abiertas', v: num(k.abiertas), d: `${num(k.cursos)} cursos${k.cerradas ? ` · ${num(k.cerradas)} cerradas` : ''}` },
    { k: 'Con gestiones pendientes', v: num(k.con_pendientes), d: `secciones · ${k.sin_docente ? num(k.sin_docente) + ' sin catedrático' : 'todas con catedrático'}`, alerta: k.con_pendientes > 0 },
    { k: 'Cobertura de auxiliares', v: pct(k.cobertura_auxiliares), d: `${num(k.secciones_con_auxiliar)} secciones · ${num(k.auxiliares)} auxiliares`, meter: k.cobertura_auxiliares },
    { k: 'Catedráticos', v: num(k.docentes), d: `${num(k.salones)} salones presenciales en uso` },
  ];
  $('#kpis').innerHTML = tiles.map(t => `
    <div class="card tile">
      <div class="k">${t.k}</div><div class="v">${t.v}</div><div class="d">${t.d}</div>
      ${t.meter != null ? `<div class="meter"><i style="width:${Math.min(t.meter * 100, 100).toFixed(1)}%"></i></div>` : ''}
    </div>`).join('');

  const notas = [];
  if (!k.procedencia_disponible) {
    notas.push('<b>Procedencia.</b> Este corte trae en cero las columnas de otra facultad, centros regionales, otra universidad, no inscritos y cierre: todos los asignados aparecen como regulares.');
  } else {
    const d = k.procedencia.filter(p => p.valor).map(p => `${esc(p.etiqueta)} ${num(p.valor)}`).join(' · ');
    notas.push(`<b>Procedencia.</b> ${d}.`);
  }
  const inferidas = k.clasificacion.filter(c => c.origen !== 'archivo').reduce((a, c) => a + c.secciones, 0);
  if (inferidas) {
    const sin = k.clasificacion.find(c => c.origen === 'ninguna')?.secciones || 0;
    notas.push(`<b>Escuela y área.</b> Este reporte no trae esas columnas para ${num(inferidas)} secciones; se tomaron del catálogo de cursos aprendido de otros reportes o de reglas por código${sin ? `, y ${num(sin)} quedaron sin clasificar` : ''}. En las tablas se marcan como <span class="inferida">inferida</span>.`);
  }
  $('#notas').innerHTML = notas.map(n => `<p class="note">${n}</p>`).join('');
}

/* ═════════════════════ RESUMEN ═════════════════════ */
async function renderResumen() {
  const [o, mod, jor, esc_] = await Promise.all([
    get('/api/ocupacion'), get('/api/distribucion/modalidad'), get('/api/distribucion/jornada'), get('/api/distribucion/escuela')]);
  const total = o.por_estado.reduce((a, b) => a + b.secciones, 0) || 1;
  barrasH($('#chart-estado'), o.por_estado.filter(e => e.secciones > 0).map(e => {
    const s = ESTILO_ESTADO[e.estado];
    return {
      etiqueta: `${s.icono}  ${e.estado}`, valor: e.secciones, color: s.color,
      valorTexto: `${num(e.secciones)} secc · ${((e.secciones / total) * 100).toFixed(0)}%`,
      tip: `<b>${e.estado}</b><span class="r">${num(e.secciones)} secciones<br>${num(e.asignados)} estudiantes<br>cupo ${num(e.cupo)}</span>`,
      alClic: () => aplicar({ estado: state.filtros.estado === e.estado ? '' : e.estado }),
    };
  }), { anchoEtiqueta: 210, anchoValor: 170 });

  const orden = ['0%', '1-20%', '21-40%', '41-60%', '61-80%', '81-100%', '>100%', 'n/d', 'cerrada'];
  const COL = ['#86b6ef', '#6da7ec', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', 'var(--text-muted)', 'var(--axis)'];
  const idx = Object.fromEntries(o.histograma.map(r => [r.rango, r.secciones]));
  barrasH($('#chart-histograma'), orden.filter(r => idx[r]).map(r => ({
    etiqueta: r === 'n/d' ? 'sin cupo definido' : r === 'cerrada' ? 'cerradas' : r, valor: idx[r], color: COL[orden.indexOf(r)],
    tip: `<b>${r === 'cerrada' ? 'Secciones cerradas' : 'Ocupación ' + r}</b><span class="r">${num(idx[r])} secciones</span>`,
  })), { anchoEtiqueta: 130, anchoValor: 70 });

  const u = state.catalogos.umbrales;
  $('#nota-umbral').innerHTML = `<b>Umbrales.</b> Sobrecupo &gt;100% · por llenarse ≥${u.llena * 100}% · saludable ≥${u.saludable_bajo * 100}%. ` +
    (state.catalogos.usa_limite_minimo
      ? 'Riesgo de cierre: por debajo del <b>límite mínimo de asignados</b> que trae el propio reporte.'
      : `Riesgo de cierre: menos del ${u.riesgo_cierre * 100}% del cupo. Este reporte trae el límite mínimo en cero, así que el umbral es un parámetro del tablero, no un dato del archivo.`);

  const CAT = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)'];
  const dist = (cont, datos, col) => barrasH(cont, datos.map((d, i) => ({
    etiqueta: d.etiqueta, valor: d.asignados, valorTexto: `${num(d.asignados)} · ${num(d.secciones)} secc`,
    color: datos.length <= 3 ? CAT[i] : 'var(--series-1)',
    tip: `<b>${esc(d.etiqueta)}</b><span class="r">${num(d.asignados)} estudiantes<br>${num(d.secciones)} secciones<br>cupo ${num(d.cupo)}</span>`,
    alClic: () => aplicar({ [col]: state.filtros[col] === d.etiqueta ? '' : d.etiqueta }),
  })), { anchoEtiqueta: 190, anchoValor: 170 });
  dist($('#chart-modalidad'), mod.datos, 'modalidad');
  dist($('#chart-jornada'), jor.datos, 'jornada');
  barrasH($('#chart-escuela'), esc_.datos.map(d => ({
    etiqueta: d.etiqueta, valor: d.asignados, valorTexto: `${num(d.asignados)} · ${num(d.secciones)} secc`,
    color: d.etiqueta === state.catalogos.escuela_foco ? 'var(--series-2)' : 'var(--series-1)',
    tip: `<b>${esc(d.etiqueta)}</b><span class="r">${num(d.asignados)} estudiantes<br>${num(d.secciones)} secciones</span>`,
    alClic: () => aplicar({ escuela: state.filtros.escuela === d.etiqueta ? '' : d.etiqueta, area: '' }, { recargarCatalogos: true }),
  })), { anchoEtiqueta: 220, anchoValor: 170 });
}

/* ═════════════════════ VISTA 1 · SEGUIMIENTO ═════════════════════ */
async function renderSeguimiento() {
  const orden = $('#f-orden-cursos').value;
  const [{ cursos }, ev, hm] = await Promise.all([
    get('/api/cursos', { limite: 18, orden }), get('/api/evolucion'), get('/api/heatmap')]);

  barrasH($('#chart-cursos'), cursos.map(c => ({
    etiqueta: `${c.codigo} · ${c.curso}`,
    valor: orden === 'secciones' ? c.secciones : orden === 'promedio' ? (c.promedio || 0) : orden === 'ocupacion' ? (c.ocupacion ?? 0) * 100 : orden === 'pendientes' ? c.pendientes : c.asignados,
    valorTexto: orden === 'ocupacion' ? pct(c.ocupacion) : orden === 'secciones' ? `${c.secciones} secciones` : orden === 'promedio' ? `${num(c.promedio)} por sección` : orden === 'pendientes' ? `${c.pendientes} pendientes de ${c.secciones}` : `${num(c.asignados)} · ${c.secciones} secc`,
    color: orden === 'pendientes' ? 'var(--critical)' : 'var(--series-1)',
    tip: `<b>${esc(c.codigo)} ${esc(c.curso)}</b><span class="r">${num(c.asignados)} asignados en ${c.secciones} secciones abiertas<br>
          promedio ${num(c.promedio)} · ocupación ${pct(c.ocupacion)}<br>
          ${c.sobrecupo ? `▲ ${c.sobrecupo} en sobrecupo<br>` : ''}${c.en_riesgo ? `▼ ${c.en_riesgo} en riesgo o vacías<br>` : ''}
          ${c.pendientes ? `! ${c.pendientes} con gestiones pendientes<br>` : ''}${esc(c.escuela)}${c.area ? ' · ' + esc(c.area) : ''}</span>`,
    alClic: () => aplicar({ codigo: state.filtros.codigo === c.codigo ? '' : c.codigo }),
  })), { anchoEtiqueta: 330, anchoValor: 170, vacio: 'Sin cursos para este filtro.' });

  $('#hint-evolucion').textContent = `${ev.periodo}: asignados en cada fecha de corte cargada.`;
  linea($('#chart-evolucion'), ev.cortes.map(c => ({
    etiqueta: fechaHumana(c.fecha_corte).slice(0, 10), valor: c.asignados,
    tip: `<b>Corte ${fechaHumana(c.fecha_corte)}</b><span class="r">${num(c.asignados)} asignados<br>${num(c.abiertas)} secciones abiertas<br>${num(c.pendientes)} con gestiones pendientes</span>`,
    alClic: () => aplicar({ snapshot_id: String(c.id) }, { recargarCatalogos: true }),
  })), { vacio: `Solo hay ${ev.cortes.length} corte cargado de este período. Cargue el mismo reporte descargado en otras fechas (por ejemplo, cada semana durante la asignación) para ver aquí cómo evoluciona.` });

  barrasH($('#chart-historico'), ev.historico.map(h => ({
    etiqueta: `${h.anio} · ${h.periodo_nombre}`, valor: h.asignados,
    color: String(h.id) === String(state.filtros.snapshot_id) ? 'var(--series-2)' : 'var(--series-1)',
    valorTexto: `${num(h.asignados)} · ${num(h.abiertas)} secc`,
    tip: `<b>${h.anio} · ${esc(h.periodo_nombre)}</b><span class="r">${num(h.asignados)} asignados · ${num(h.abiertas)} secciones abiertas<br>corte ${fechaHumana(h.fecha_corte)}</span>`,
    alClic: () => aplicar({ snapshot_id: String(h.id) }, { recargarCatalogos: true }),
  })), { anchoEtiqueta: 300, anchoValor: 150, maxCar: 46 });

  if (ev.cambios) {
    $('#hint-cambios').textContent = `Cursos cuyo total de asignados o de secciones abiertas cambió entre el corte del ${fechaHumana(ev.cambios.desde)} y el del ${fechaHumana(ev.cambios.hasta)}.`;
    tabla($('#tbl-cambios'), [
      { titulo: 'Curso', ancho: 1, render: c => `${esc(c.codigo)} · ${esc(c.curso)}` },
      { titulo: 'Antes', num: 1, render: c => num(c.antes) },
      { titulo: 'Ahora', num: 1, render: c => num(c.ahora) },
      { titulo: 'Cambio', num: 1, render: c => `<b>${c.delta > 0 ? '+' : ''}${num(c.delta)}</b>` },
      { titulo: 'Secciones', num: 1, render: c => c.secciones_antes === c.secciones_ahora ? c.secciones_ahora : `${c.secciones_antes} → ${c.secciones_ahora}` },
    ], ev.cambios.cursos, { vacio: 'Sin cambios entre los dos cortes.', alClicFila: c => aplicar({ codigo: c.codigo }) });
  } else {
    $('#hint-cambios').textContent = 'Este es el primer corte cargado de su período: no hay uno anterior contra el cual comparar.';
    $('#tbl-cambios').innerHTML = '';
  }
  heatmap($('#chart-heatmap'), hm, $('#f-metrica-heat').value);
}

/* ═════════════════════ VISTA 2 · ESTADO DE GESTIONES ═════════════════════ */
const SERIES_GESTION = [
  { clave: 'al_dia', nombre: 'Al día', color: 'var(--good)' },
  { clave: 'en_revision', nombre: 'En revisión', color: 'var(--warning)' },
  { clave: 'pendiente', nombre: 'Pendiente', color: 'var(--critical)' },
];
async function renderGestiones() {
  const g = await get('/api/gestiones', { limite_cursos: 15 });
  const pe = Object.fromEntries(g.por_estado.map(e => [e.estado, e.secciones]));
  const tarjetas = [
    { k: 'Pendiente', v: pe['Pendiente'] || 0, d: 'secciones con algún trámite por resolver' },
    { k: 'En revisión', v: pe['En revisión'] || 0, d: 'secciones con observaciones no bloqueantes' },
    { k: 'Al día', v: pe['Al día'] || 0, d: 'secciones sin trámites pendientes' },
    ...g.por_tipo.map(t => ({ k: t.tipo, v: t.secciones, d: `${num(t.estudiantes)} estudiantes · ${t.severidad === 'pendiente' ? 'pendiente' : 'en revisión'}`, tipo: true })),
  ];
  $('#gest-kpis').innerHTML = tarjetas.map(t => `<div class="card"><div class="k">${t.tipo ? '' : (ESTILO_ESTADO[t.k]?.icono || '') + ' '}${esc(t.k)}</div><div class="v">${num(t.v)}</div><div class="d">${t.d}</div></div>`).join('');
  $('#leyenda-gestion').innerHTML = SERIES_GESTION.map(s => `<span><i style="background:${s.color}"></i>${s.nombre}</span>`).join('');
  barrasApiladas($('#chart-gestion-cursos'), g.por_curso.map(c => ({
    ...c, etiqueta: `${c.codigo} · ${c.curso}`, alClic: () => aplicar({ codigo: c.codigo }),
  })), SERIES_GESTION, { textoFila: f => `${f.abiertas} secc`, vacio: 'Sin secciones abiertas para este filtro.' });

  tabla($('#tbl-gestiones'), [
    { titulo: 'Gestión', render: x => insignia(x.severidad === 'pendiente' ? 'Pendiente' : 'En revisión') + ' ' + esc(x.tipo) },
    { titulo: 'Curso', ancho: 1, render: x => `${esc(x.codigo)} · ${esc(x.curso)}` },
    { titulo: 'Secc', render: x => esc(x.seccion) },
    { titulo: 'Tipo', render: x => esc(x.tipo_seccion) },
    { titulo: 'Detalle', ancho: 1, render: x => esc(x.detalle) },
    { titulo: 'Catedrático', ancho: 1, render: x => x.docente ? esc(x.docente) : '<span style="color:var(--critical)">sin asignar</span>' },
  ], g.detalle, { vacio: 'No hay gestiones por resolver con este filtro.', alClicFila: x => aplicar({ codigo: x.codigo }) });
}

/* ═════════════════════ VISTA 3 · TIEMPOS DE ATENCIÓN ═════════════════════ */
async function renderTiempos() {
  const t = await get('/api/tiempos');
  const cont = $('#tiempos-contenido');
  if (!t.disponible) {
    cont.innerHTML = `<div class="empty">
      <h2>Se necesitan al menos dos cortes del mismo período</h2>
      <p>Para <b>${esc(t.periodo || 'este período')}</b> hay ${t.cortes} corte cargado${t.cortes === 1 ? '' : 's'}.
         El tiempo de atención se mide comparando fotografías: una gestión que aparece pendiente en un corte y ya no aparece
         en el siguiente quedó atendida entre ambas fechas.</p>
      <p>Descargue el mismo reporte de este período en otras fechas (por ejemplo, cada lunes durante la asignación)
         y cárguelos: el sistema los reconoce como cortes del mismo período y esta vista se llena sola.</p>
      <p style="margin-top:16px"><a class="btn primary" href="/cargas" style="text-decoration:none">Cargar otro corte</a></p></div>`;
    return;
  }
  const res = t.por_tipo.filter(x => x.resueltas || x.abiertas);
  const resueltas = res.reduce((a, x) => a + x.resueltas, 0), abiertas = res.reduce((a, x) => a + x.abiertas, 0);
  cont.innerHTML = `
    <div class="kpi-mini">
      <div class="card"><div class="k">Cortes comparados</div><div class="v">${t.cortes}</div><div class="d">${fechaHumana(t.primer_corte).slice(0, 10)} → ${fechaHumana(t.ultimo_corte).slice(0, 10)}</div></div>
      <div class="card"><div class="k">Gestiones atendidas</div><div class="v">${num(resueltas)}</div><div class="d">desaparecieron en un corte posterior</div></div>
      <div class="card"><div class="k">Siguen abiertas</div><div class="v">${num(abiertas)}</div><div class="d">al último corte</div></div>
      <div class="card"><div class="k">Meta institucional</div><div class="v">${t.meta_dias} días</div><div class="d">configurable (META_DIAS_ATENCION)</div></div>
    </div>
    <div class="card">
      <h2>Tiempo promedio de atención por tipo de gestión <span class="story">R1-14</span></h2>
      <p class="hint">Días hasta que la gestión dejó de aparecer, como cota superior: solo se observa en las fechas de corte. Línea punteada: meta.</p>
      <div class="stack-legend"><span><i style="background:var(--good)"></i>✓ dentro de la meta</span><span><i style="background:var(--critical)"></i>▲ sobre la meta</span></div>
      <div id="chart-tiempos"></div>
      <p class="note">Las gestiones que ya estaban pendientes en el primer corte tienen inicio desconocido (pudieron empezar antes); se marcan en la tabla. Cuantos más cortes, más preciso el tiempo.</p>
    </div>
    <div class="grid two" style="margin-top:14px">
      <div class="card"><h2>Resumen por tipo</h2><div class="tablewrap"><table id="tbl-tiempos"></table></div></div>
      <div class="card"><h2>Detalle de gestiones</h2><p class="hint">Las más largas primero.</p><div class="tablewrap"><table id="tbl-episodios"></table></div></div>
    </div>`;
  const conDatos = t.por_tipo.filter(x => x.promedio_dias != null);
  barrasH($('#chart-tiempos'), conDatos.map(x => {
    const sobre = x.promedio_dias > t.meta_dias;
    return {
      etiqueta: `${sobre ? '▲' : '✓'} ${x.tipo}`, valor: x.promedio_dias, valorTexto: `${x.promedio_dias} d`,
      color: sobre ? 'var(--critical)' : 'var(--good)',
      tip: `<b>${esc(x.tipo)}</b><span class="r">promedio ${x.promedio_dias} d · mediana ${x.mediana_dias} d<br>${x.resueltas} atendidas · ${x.sobre_meta} sobre la meta<br>${x.abiertas} siguen abiertas</span>`,
    };
  }), { anchoEtiqueta: 290, anchoValor: 70, meta: t.meta_dias, metaTexto: `meta ${t.meta_dias} días`, vacio: 'Ninguna gestión se ha atendido todavía entre los cortes cargados.' });
  tabla($('#tbl-tiempos'), [
    { titulo: 'Gestión', ancho: 1, render: x => esc(x.tipo) },
    { titulo: 'Atendidas', num: 1, render: x => x.resueltas },
    { titulo: 'Promedio', num: 1, render: x => x.promedio_dias != null ? `${x.promedio_dias} d` : '—' },
    { titulo: 'Sobre meta', num: 1, render: x => x.sobre_meta },
    { titulo: 'Abiertas', num: 1, render: x => x.abiertas },
    { titulo: 'Antigüedad', num: 1, render: x => x.antiguedad_abiertas_dias != null ? `${x.antiguedad_abiertas_dias} d` : '—' },
  ], t.por_tipo);
  tabla($('#tbl-episodios'), [
    { titulo: 'Estado', render: e => e.resuelta ? insignia('Al día') : insignia('Pendiente') },
    { titulo: 'Curso', ancho: 1, render: e => `${esc(e.codigo)}-${esc(e.seccion)} ${esc(e.curso)}` },
    { titulo: 'Gestión', ancho: 1, render: e => esc(e.tipo) },
    { titulo: 'Desde', render: e => fechaHumana(e.desde).slice(0, 10) + (e.inicio_censurado ? ' <span class="inferida" title="Ya estaba pendiente en el primer corte">o antes</span>' : '') },
    { titulo: 'Días', num: 1, render: e => `${e.resuelta ? '≤ ' : ''}${e.dias_max}` },
  ], t.episodios, { vacio: 'Sin gestiones en los cortes comparados.' });
}

/* ═════════════════════ PREDICCIONES (R1-19) ═════════════════════ */
const pctSigno = v => (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
async function renderPredicciones() {
  const periodo = $('#f-periodo-pred').value || undefined;
  const p = await get('/api/predicciones', { periodo });
  const sel = $('#f-periodo-pred');
  sel.innerHTML = p.series_disponibles.map(s =>
    `<option value="${esc(s.periodo_nombre)}">${s.periodo_codigo ? s.periodo_codigo + ' : ' : ''}${esc(s.periodo_nombre)} — ${s.anios} año${s.anios === 1 ? '' : 's'}</option>`).join('');
  sel.value = p.periodo;
  const cont = $('#pred-contenido');
  const codigo = p.series_disponibles.find(s => s.periodo_nombre === p.periodo)?.periodo_codigo;

  if (!p.disponible) {
    const anios = p.anios_base.map(a => a.anio);
    const otros = p.series_disponibles.filter(s => s.anios >= 2);
    cont.innerHTML = `<div class="empty">
      <h2>Se necesitan al menos dos años de ${esc(p.periodo)}</h2>
      <p>Las predicciones comparan el mismo tipo de período año contra año (un semestre con semestres, vacaciones con
         vacaciones). De <b>${esc(p.periodo)}</b> hay ${anios.length ? 'solo ' + anios.join(', ') : 'ningún año'}.</p>
      <p>En el sistema de Centro de Cálculo, en <b>Contadores asignados (Condensado)</b>, elija el período
         <b>${codigo ? codigo + ' : ' : ''}${esc(p.periodo)}</b> de años anteriores (por ejemplo ${anios.length ? anios[0] - 1 + ' y ' + (anios[0] - 2) : 'los últimos cuatro'}),
         descargue cada uno y cárguelos. Con tres años o más, el sistema además mide qué tan bien acierta.</p>
      ${otros.length ? `<p>Ya se puede predecir: ${otros.map(o => `<a href="#" data-periodo="${esc(o.periodo_nombre)}">${esc(o.periodo_nombre)}</a>`).join(', ')}.</p>` : ''}
      <p style="margin-top:16px"><a class="btn primary" href="/cargas" style="text-decoration:none">Cargar reportes de años anteriores</a></p></div>`;
    $$('[data-periodo]', cont).forEach(a => a.addEventListener('click', e => { e.preventDefault(); $('#f-periodo-pred').value = a.dataset.periodo; renderPredicciones(); }));
    return;
  }

  const r = p.resumen, v = p.validacion, m = p.modelo;
  const cambio = r.ultimo_valor ? (r.prediccion - r.ultimo_valor) / r.ultimo_valor : 0;
  const nivel = Math.round(m.nivel_intervalo * 100);
  // Honesto: < 0.95 mejora, 0.95–1.05 empata (dentro del ruido de pocos años), > 1.05 empeora.
  const er = v.disponible ? Math.round(v.error_relativo * 100) / 100 : null;   // el mismo valor que se muestra
  const veredicto = !v.disponible ? null : er < 0.95 ? 'mejor' : er <= 1.05 ? 'igual' : 'peor';
  const errTipico = v.disponible && v.wape_modelo != null ? ` · error típico por curso ${(v.wape_modelo * 100).toFixed(0)}%` : '';
  const validacionTxt = !v.disponible ? 'requiere 3 años o más'
    : veredicto === 'mejor' ? `${((1 - v.error_relativo) * 100).toFixed(0)}% menos error que repetir el año anterior${errTipico}`
    : veredicto === 'igual' ? `tan preciso como repetir el año anterior${errTipico}; su aporte es el intervalo y el riesgo`
    : `menos preciso que repetir el año anterior${errTipico}; use el intervalo como rango`;
  const tituloValidacion = !v.disponible ? 'Sin validar' : veredicto === 'mejor' ? '✓ Mejora' : veredicto === 'igual' ? '≈ Empata' : '! No mejora';
  const aniosVistos = p.anios_base.map(a => a.anio);
  const faltan = [];
  for (let a = aniosVistos[0]; a < aniosVistos[aniosVistos.length - 1]; a++) if (!aniosVistos.includes(a)) faltan.push(a);
  const ordenar = { prediccion: c => -c.prediccion, cambio: c => -(c.cambio_secciones ?? -99), riesgo: c => -(c.prob_sobrecupo ?? -1), crecimiento: c => -c.crecimiento_anual };
  const cursos = [...p.cursos].sort((a, b) => ordenar[$('#f-orden-pred').value](a) - ordenar[$('#f-orden-pred').value](b));
  const total = state.filtros.escuela && p.totales[state.filtros.escuela] ? [state.filtros.escuela, p.totales[state.filtros.escuela]] : ['FACULTAD', p.totales.FACULTAD];

  cont.innerHTML = `
    <p class="note" style="margin:0 0 12px"><b>Qué se predice.</b> Asignados por curso en <b>${esc(p.periodo)} ${p.anio_objetivo}</b>,
      con base en ${p.anios_base.map(a => `${a.anio} (corte ${fechaHumana(a.fecha_corte).slice(0, 10)})`).join(', ')}.
      Solo se comparan reportes del mismo tipo de período. Si el último año todavía está en asignación, su dato está incompleto y la predicción saldrá baja.
      ${faltan.length ? `<br><b>Falta${faltan.length > 1 ? 'n' : ''} ${faltan.join(', ')}</b>: el modelo lo tolera (mide el crecimiento por año transcurrido), pero cargarlo mejora la estimación.` : ''}
      ${p.filtros_ignorados.length ? `Los filtros de ${p.filtros_ignorados.join(', ')} no aplican aquí porque cambian de un año a otro.` : ''}</p>
    <div class="kpi-mini">
      <div class="card"><div class="k">Demanda esperada ${p.anio_objetivo}</div><div class="v">${num(r.prediccion)}</div><div class="d">${pctSigno(cambio)} frente a ${num(r.ultimo_valor)} en ${p.anios[p.anios.length - 1]} · ${num(r.cursos)} cursos</div></div>
      <div class="card"><div class="k">Secciones sugeridas</div><div class="v">${num(r.secciones_sugeridas)}</div><div class="d">frente a ${num(r.secciones_actuales)} abiertas hoy</div></div>
      <div class="card"><div class="k">Cursos que necesitan más secciones</div><div class="v">${num(r.abrir_mas)}</div><div class="d">${num(r.abrir_menos)} podrían abrir menos</div></div>
      <div class="card"><div class="k">Riesgo de sobrecupo</div><div class="v">${num(r.riesgo_sobrecupo)}</div><div class="d">cursos con probabilidad ≥ 50% de superar su cupo actual</div></div>
      <div class="card"><div class="k">Validación del modelo</div><div class="v" style="font-size:16px">${tituloValidacion}</div><div class="d">${validacionTxt}</div></div>
    </div>
    <div class="grid two">
      <div class="card">
        <h2>Total ${total[0] === 'FACULTAD' ? 'de la Facultad' : esc(total[0])} <span class="story">R1-19</span></h2>
        <p class="hint">Asignados por año en ${esc(p.periodo)} y predicción con su intervalo del ${nivel}%.</p>
        <div id="chart-pred-total"></div>
        <p class="hint" id="nota-coherencia" style="margin:6px 0 0"></p>
      </div>
      <div class="card">
        <h2>Cómo se calcula</h2>
        <ul style="margin:4px 0 0;padding-left:18px;font-size:13px;color:var(--text-secondary)">
          <li><b>Crecimiento de cada curso</b> año contra año, en escala logarítmica.</li>
          <li>Cursos con poca historia se acercan al crecimiento de su escuela (<i>encogimiento empírico-bayesiano</i>, Efron y Morris). La columna «peso propio» dice cuánto pesa la historia del curso.</li>
          <li>La tendencia se <b>amortigua</b> (φ = ${m.amortiguamiento_phi}) para no proyectar una línea recta sin fin (Gardner y McKenzie).</li>
          <li><b>Secciones sugeridas</b>: las de hoy, más (o menos) una por cada cupo de sección completo de demanda que se espera ganar (o perder). La oferta de secciones es muy estable año con año; esta regla solo propone cambios cuando la demanda llena o vacía una sección entera.</li>
          <li><b>Validación</b>: se esconde cada año, se predice con los anteriores y se compara contra «igual que el año pasado».</li>
        </ul>
        <p class="hint" style="margin-top:8px">Ruido anual estimado ${(m.ruido_anual_sigma * 100).toFixed(1)}% · crecimiento global ${pctSigno(m.crecimiento_global_anual)} por año.</p>
      </div>
    </div>
    <div class="card" style="margin-top:14px">
      <div class="card-head"><div>
        <h2>Predicción por curso <span class="story">R1-19</span></h2>
        <p class="hint">Intervalo: rango donde caerá la demanda con ${nivel}% de probabilidad. Clic en un curso para ver sus secciones actuales.</p></div>
        <button class="btn" id="btn-export-pred">Exportar predicciones CSV</button></div>
      <div class="tablewrap" style="max-height:560px"><table id="tbl-pred"></table></div>
      ${cursos.length > 300 ? `<p class="hint" style="margin:6px 0 0">Se muestran los primeros 300 de ${num(cursos.length)} cursos según el orden elegido. Use el buscador, los filtros o «Exportar predicciones CSV» para verlos todos.</p>` : ''}
    </div>
    ${v.disponible ? `<div class="card" style="margin-top:14px"><h2>Validación año por año</h2>
      <p class="hint">Error relativo &lt; 1: el modelo se equivocó menos que repetir el año anterior. Cobertura: proporción de cursos que cayeron dentro del intervalo (lo ideal es cerca de ${nivel}%).</p>
      <div class="tablewrap"><table id="tbl-val"></table></div></div>` : ''}
    ${p.no_ofertados.length ? `<p class="note">${p.no_ofertados.length} cursos con historia en ${esc(p.periodo)} no se ofrecieron en ${p.anios[p.anios.length - 1]} y no se predicen.</p>` : ''}`;

  pronosticoChart($('#chart-pred-total'), total[1], p.anio_objetivo);
  if (total[1] && !state.filtros.tipo && !state.filtros.q && !state.filtros.codigo && !state.filtros.area) {
    const suma = r.prediccion, agr = total[1].prediccion;
    $('#nota-coherencia').textContent = `Este total se pronostica como serie propia (${num(agr)}). La suma de las predicciones por curso da ${num(suma)} `
      + `(${((suma - agr) / agr * 100).toFixed(1)}% de diferencia): son dos estimaciones válidas; para planificar secciones use la de cada curso.`;
  }
  const conf = { alta: 'Al día', media: 'En revisión', baja: 'Pendiente' };
  tabla($('#tbl-pred'), [
    { titulo: 'Curso', ancho: 1, render: c => `${esc(c.codigo)} · ${esc(c.curso)}<br><span class="hint" style="margin:0">${esc(c.tipo)} · ${esc(c.escuela)}</span>` },
    { titulo: `Historia ${p.anios[0]}–${p.anios[p.anios.length - 1]}`, render: c => c.historia.map(h => `<span title="${h.anio}">${num(h.asignados)}</span>`).join(' <span style="color:var(--text-muted)">→</span> ') + (c.anios_historia < p.anios.length ? ` <span class="hint" style="margin:0">(${c.anios_historia} de ${p.anios.length} años)</span>` : '') },
    { titulo: `Predicción ${p.anio_objetivo}`, num: 1, render: c => `<b>${num(c.prediccion)}</b>` },
    { titulo: `Intervalo ${nivel}%`, num: 1, render: c => `${num(c.intervalo_bajo)} – ${num(c.intervalo_alto)}` },
    { titulo: 'Crec. anual', num: 1, render: c => pctSigno(c.crecimiento_anual) },
    { titulo: 'Peso propio', num: 1, render: c => `${Math.round(c.peso_propio * 100)}%` },
    { titulo: 'Secciones', num: 1, render: c => c.secciones_sugeridas == null ? '—' : `${c.secciones_actuales} → <b>${c.secciones_sugeridas}</b>${c.cambio_secciones ? ` <span style="color:${c.cambio_secciones > 0 ? 'var(--critical)' : 'var(--text-muted)'}">(${c.cambio_secciones > 0 ? '+' : ''}${c.cambio_secciones})</span>` : ''}` },
    { titulo: 'P(sobrecupo)', num: 1, render: c => c.prob_sobrecupo == null ? '—' : `${Math.round(c.prob_sobrecupo * 100)}%` },
    { titulo: 'Confiabilidad', render: c => insignia(conf[c.confiabilidad]).replace(/>[^<]*<\/span>$/, `>${c.confiabilidad}</span>`) },
  ], cursos.slice(0, 300), { vacio: 'Sin cursos para este filtro.', alClicFila: c => { aplicar({ codigo: c.codigo }); irA('secciones'); } });
  if (v.disponible) tabla($('#tbl-val'), [
    { titulo: 'Año predicho', render: x => x.anio }, { titulo: 'Cursos', num: 1, render: x => x.cursos },
    { titulo: 'Error relativo', num: 1, render: x => x.error_relativo ?? '—' },
    { titulo: 'Error % ponderado', num: 1, render: x => x.wape != null ? (x.wape * 100).toFixed(1) + '%' : '—' },
    { titulo: 'Cobertura', num: 1, render: x => (x.cobertura * 100).toFixed(0) + '%' },
  ], v.detalle);
  $('#btn-export-pred').addEventListener('click', () => {
    location.href = `/api/export/predicciones.csv?${new URLSearchParams(Object.entries(params({ periodo: p.periodo })).filter(([, x]) => x))}`;
  });
}

/* ═════════════════════ DOCENTES Y AUXILIARES ═════════════════════ */
async function renderDocentes() {
  const [{ docentes }, a] = await Promise.all([
    get('/api/docentes', { limite: 60, orden: $('#f-orden-docentes').value }), get('/api/auxiliares', { limite: 60 })]);
  tabla($('#tbl-docentes'), [
    { titulo: 'Catedrático', ancho: 1, render: d => esc(d.docente) },
    { titulo: 'Secc', num: 1, render: d => d.secciones }, { titulo: 'Cursos', num: 1, render: d => d.cursos },
    { titulo: 'Estudiantes', num: 1, render: d => num(d.asignados) }, { titulo: 'H/sem', num: 1, render: d => num(d.horas_semana) },
    { titulo: 'Aux', num: 1, render: d => d.auxiliares },
  ], docentes, { alClicFila: d => { aplicar({ q: d.docente }); irA('secciones'); } });

  const r = a.resumen;
  $('#aux-resumen').innerHTML = `<span><b>${num(r.con_auxiliar)}</b> de ${num(r.secciones)} secciones abiertas con auxiliar</span>
    <span><b>${num(r.asignados_sin_auxiliar)}</b> estudiantes en secciones sin auxiliar</span>`;
  if (state.tabAux === 'ranking') {
    tabla($('#tbl-aux'), [
      { titulo: 'Auxiliar', ancho: 1, render: x => esc(x.nombre) }, { titulo: 'Secc', num: 1, render: x => x.secciones },
      { titulo: 'Cursos', num: 1, render: x => x.cursos }, { titulo: 'Estudiantes', num: 1, render: x => num(x.asignados) },
    ], a.ranking, { alClicFila: x => { aplicar({ q: x.nombre }); irA('secciones'); } });
  } else if (state.tabAux === 'sin') {
    tabla($('#tbl-aux'), [
      { titulo: 'Curso', ancho: 1, render: x => `${esc(x.codigo)} · ${esc(x.curso)}` }, { titulo: 'Secc', render: x => esc(x.seccion) },
      { titulo: 'Tipo', render: x => esc(x.tipo) }, { titulo: 'Estudiantes', num: 1, render: x => num(x.total) },
      { titulo: 'Estado', render: x => insignia(x.estado) },
    ], a.sin_auxiliar, { alClicFila: x => aplicar({ codigo: x.codigo }) });
  } else {
    tabla($('#tbl-aux'), [
      { titulo: 'Tipo de miembro', ancho: 1, render: x => esc(x.tipo) },
      { titulo: 'Personas', num: 1, render: x => x.personas }, { titulo: 'Secciones', num: 1, render: x => x.secciones },
    ], a.tipos_miembro, { vacio: 'Este reporte no trae miembros de terna.' });
  }
}

/* ═════════════════════ SECCIONES ═════════════════════ */
async function renderSecciones() {
  const d = await get('/api/secciones', { limite: state.limite, offset: state.offset, orden: state.orden });
  tabla($('#tbl-secciones'), [
    { titulo: 'Tipo', render: f => esc(f.tipo) },
    { titulo: 'Código', orden: 'codigo', render: f => esc(f.codigo) },
    { titulo: 'Curso', orden: 'curso', ancho: 1, render: f => esc(f.curso) },
    { titulo: 'Secc', render: f => esc(f.seccion) },
    { titulo: 'Escuela', ancho: 1, render: f => esc(f.escuela) + (f.clasificacion_origen !== 'archivo' ? '<span class="inferida">inferida</span>' : '') },
    { titulo: 'Catedrático', orden: 'docente', ancho: 1, render: f => f.docente ? esc(f.docente) : (f.cerrada ? '—' : '<span style="color:var(--critical)">sin asignar (STAFF)</span>') },
    { titulo: 'Auxiliares', ancho: 1, render: f => esc(f.auxiliares) || '<span style="color:var(--text-muted)">—</span>' },
    { titulo: 'Salón', render: f => esc([f.edificio, f.salon].filter(Boolean).join(' ')) },
    { titulo: 'Días', render: f => esc(f.dias) },
    { titulo: 'Horario', render: f => esc([f.hora_inicio, f.hora_fin].filter(Boolean).join('–')) },
    { titulo: 'Asignados', num: 1, orden: 'asignados', render: f => num(f.total) },
    { titulo: 'Cupo', num: 1, render: f => num(f.limite) + (f.limite_min ? `<br><span class="hint" style="margin:0">mín ${num(f.limite_min)}</span>` : '') },
    { titulo: 'Ocup.', num: 1, orden: 'ocupacion', render: f => pct(f.ocupacion) },
    { titulo: 'Estado', render: f => insignia(f.estado) },
    { titulo: 'Gestión', ancho: 1, render: f => insignia(f.estado_gestion) + (f.gestiones ? `<br><span class="hint" style="margin:0">${esc(f.gestiones)}</span>` : '') },
  ], d.filas, {
    alOrdenar: o => { state.orden = (state.orden === o && o === 'ocupacion') ? 'ocupacion_asc' : o; state.offset = 0; renderSecciones(); },
  });
  const desde = d.total ? state.offset + 1 : 0;
  $('#paginacion').textContent = `${num(desde)}–${num(Math.min(state.offset + state.limite, d.total))} de ${num(d.total)} secciones`;
  $('#btn-prev').disabled = state.offset === 0;
  $('#btn-next').disabled = state.offset + state.limite >= d.total;
}

/* ═════════════════════ orquestación ═════════════════════ */
const RENDER = { resumen: renderResumen, seguimiento: renderSeguimiento, gestiones: renderGestiones, tiempos: renderTiempos, predicciones: renderPredicciones, docentes: renderDocentes, secciones: renderSecciones };

function mostrarError(e) {
  console.error(e);
  $('#notas').insertAdjacentHTML('afterbegin', `<p class="note" style="border-left-color:var(--critical)"><b>Error al consultar la API.</b> ${esc(e.message)}</p>`);
}

async function renderTodo() {
  escribirURL();
  $$('#viewtabs a').forEach(a => a.setAttribute('aria-selected', String(a.dataset.vista === state.vista)));
  $$('.vista').forEach(v => { v.hidden = v.dataset.vista !== state.vista; });
  await Promise.all([renderKPIs(), RENDER[state.vista]()]).catch(mostrarError);
}

function irA(vista) {
  state.vista = vista;
  renderTodo();
}

async function aplicar(cambios, { recargarCatalogos = false } = {}) {
  for (const [k, v] of Object.entries(cambios)) { if (v) state.filtros[k] = v; else delete state.filtros[k]; }
  state.offset = 0;
  if (recargarCatalogos) await cargarCatalogos();
  sincronizarControles();
  await renderTodo();
}

function sincronizarControles() {
  $$('[data-filter]').forEach(el => { el.value = state.filtros[el.dataset.filter] ?? ''; });
  const foco = state.catalogos.escuela_foco;
  $('#btn-foco').textContent = state.filtros.escuela === foco ? 'Ver toda la Facultad' : 'Solo Ciencias y Sistemas';
  $('#btn-foco').disabled = !state.catalogos.escuela.includes(foco);
}

function llenar(sel, valores, todos) {
  const actual = sel.value;
  sel.innerHTML = `<option value="">${todos}</option>` + valores.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  sel.value = actual;
}

async function cargarCatalogos() {
  const [c, { periodos }] = await Promise.all([get('/api/catalogos'), api('/api/periodos')]);
  state.catalogos = c;
  state.periodos = periodos;
  const s = c.snapshot;
  state.filtros.snapshot_id = String(s.id);
  // Un filtro que no existe en este corte se descarta para no dejar el tablero vacío sin explicación.
  for (const k of ['tipo', 'escuela', 'jornada', 'modalidad', 'estado', 'estado_gestion']) {
    if (state.filtros[k] && !c[k].includes(state.filtros[k])) delete state.filtros[k];
  }
  if (state.filtros.area && !c.area.includes(state.filtros.area)) delete state.filtros.area;

  $('#provenance').innerHTML = `
    <span class="pill">📄 <b>${esc(s.archivo_nombre)}</b></span>
    <span class="pill">🗓 ${s.periodo_codigo ? s.periodo_codigo + ' · ' : ''}${esc(s.periodo_nombre)} ${s.anio}</span>
    <span class="pill">⏱ corte ${fechaHumana(s.fecha_corte)}</span>
    <span class="pill">${num(s.total_secciones)} secciones · ${num(s.total_asignados)} asignaciones</span>
    <a class="pill" href="/api/snapshots/${s.id}/original" title="Descargar el archivo original">⬇ original</a>`;
  poblarSelector(s.id);
  llenar($('#f-tipo'), c.tipo, 'Clase y laboratorio');
  llenar($('#f-escuela'), c.escuela, 'Todas');
  llenar($('#f-area'), c.area, state.filtros.escuela ? 'Todas las áreas' : 'Todas (elija escuela)');
  llenar($('#f-jornada'), c.jornada, 'Todas');
  llenar($('#f-modalidad'), c.modalidad, 'Todas');
  llenar($('#f-estado'), c.estado, 'Todos');
  llenar($('#f-estado_gestion'), c.estado_gestion, 'Todos');
}

function conectarEventos() {
  $$('select[data-filter], input[data-filter]').forEach(el => {
    const evento = el.tagName === 'INPUT' ? 'input' : 'change';
    let t;
    el.addEventListener(evento, () => {
      clearTimeout(t);
      t = setTimeout(() => {
        const cambio = { [el.dataset.filter]: el.value };
        if (el.dataset.filter === 'escuela') cambio.area = '';
        aplicar(cambio, { recargarCatalogos: el.dataset.filter === 'escuela' });
      }, evento === 'input' ? 320 : 0);
    });
  });
  $('#s-anio').addEventListener('change', () => elegirDesdeSelector('anio'));
  $('#s-periodo').addEventListener('change', () => elegirDesdeSelector('periodo'));
  $('#s-corte').addEventListener('change', () => elegirDesdeSelector('corte'));
  $$('#viewtabs a').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); irA(a.dataset.vista); }));
  addEventListener('hashchange', () => { const h = location.hash.slice(1); if (VISTAS.includes(h) && h !== state.vista) irA(h); });
  $('#f-orden-cursos').addEventListener('change', renderSeguimiento);
  $('#f-orden-docentes').addEventListener('change', renderDocentes);
  $('#f-periodo-pred').addEventListener('change', renderPredicciones);
  $('#f-orden-pred').addEventListener('change', renderPredicciones);
  $('#f-metrica-heat').addEventListener('change', () => get('/api/heatmap').then(hm => heatmap($('#chart-heatmap'), hm, $('#f-metrica-heat').value)));
  $('#f-pagina').addEventListener('change', e => { state.limite = +e.target.value; state.offset = 0; renderSecciones(); });
  $('#btn-prev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limite); renderSecciones(); });
  $('#btn-next').addEventListener('click', () => { state.offset += state.limite; renderSecciones(); });
  $('#btn-reset').addEventListener('click', () => { state.filtros = { snapshot_id: state.filtros.snapshot_id }; aplicar({}, { recargarCatalogos: true }); });
  $('#btn-foco').addEventListener('click', () => {
    const foco = state.catalogos.escuela_foco;
    aplicar({ escuela: state.filtros.escuela === foco ? '' : foco, area: '' }, { recargarCatalogos: true });
  });
  $('#btn-export').addEventListener('click', () => { location.href = `/api/export.csv?${new URLSearchParams(Object.entries(params({ orden: state.orden })).filter(([, v]) => v))}`; });
  $('#btn-export-gestiones').addEventListener('click', () => { location.href = `/api/export/gestiones.csv?${new URLSearchParams(Object.entries(params()).filter(([, v]) => v))}`; });
  $('#tabs-aux').addEventListener('click', e => {
    const b = e.target.closest('button[data-tab]'); if (!b) return;
    state.tabAux = b.dataset.tab;
    $$('#tabs-aux button').forEach(x => x.setAttribute('aria-selected', String(x === b)));
    renderDocentes();
  });
  let rz;
  addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(() => RENDER[state.vista]().catch(mostrarError), 250); });
}

(async function iniciar() {
  conectarTema($('#btn-theme'), () => RENDER[state.vista]?.().catch(mostrarError));
  leerURL();
  try {
    const salud = await api('/api/salud');
    if (!salud.snapshots) throw new ErrorApi(404, 'sin_snapshots');
    await cargarCatalogos();
  } catch (e) {
    if (e.status === 404 && (e.detalle === 'sin_snapshots' || e.detalle === 'snapshot_inexistente')) {
      if (e.detalle === 'snapshot_inexistente') { location.href = '/'; return; }
      $('#provenance').innerHTML = '<span class="pill">Sin reportes cargados</span>';
      $('#selector-corte').hidden = true; $('#filters').hidden = true;
      $('#vacio').hidden = false;
      return;
    }
    $('#provenance').innerHTML = `<span class="pill">⚠ ${esc(e.message)}</span>`;
    return;
  }
  $('#contenido').hidden = false;
  conectarEventos();
  sincronizarControles();
  await renderTodo();
})();
