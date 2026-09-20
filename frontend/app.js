/* Dashboard de Asignados · Secretaría Académica ECYS
   Front sin dependencias: SVG generado a mano para que el tablero corra en la red
   interna sin CDN. Cada bloque está rotulado con la historia que atiende. */

const API = '';
const $ = (s, r = document) => r.querySelector(s);
const FILTROS = ['snapshot_id', 'tipo', 'area', 'jornada', 'modalidad', 'edificio', 'estado', 'q'];

const state = { filtros: {}, offset: 0, limite: 100, orden: 'asignados', tabAux: 'ranking', catalogos: null };

/* ─────────────────────────── utilidades ─────────────────────────── */
const nf = new Intl.NumberFormat('es-GT');
const num = n => nf.format(Math.round(n ?? 0));
const pct = v => (v === null || v === undefined) ? '—' : (v * 100).toFixed(1) + '%';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function qs(extra = {}) {
  const p = new URLSearchParams();
  for (const k of FILTROS) if (state.filtros[k]) p.set(k, state.filtros[k]);
  for (const [k, v] of Object.entries(extra)) if (v !== undefined && v !== null) p.set(k, v);
  return p.toString();
}

async function get(ruta, extra) {
  const r = await fetch(`${API}${ruta}?${qs(extra)}`);
  if (!r.ok) throw new Error(`${ruta} → ${r.status} ${await r.text()}`);
  return r.json();
}

/* estado del tablero en la URL: el filtro es compartible (criterio de R1-02) */
function leerURL() {
  const p = new URLSearchParams(location.search);
  for (const k of FILTROS) if (p.get(k)) state.filtros[k] = p.get(k);
}
function escribirURL() {
  const p = new URLSearchParams();
  for (const k of FILTROS) if (state.filtros[k]) p.set(k, state.filtros[k]);
  history.replaceState(null, '', p.toString() ? `?${p}` : location.pathname);
}

/* ─────────────────────────── tooltip ─────────────────────────── */
const tip = $('#tip');
function mostrarTip(ev, html) {
  tip.innerHTML = html;
  tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY - r.height - 10;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y < 8) y = ev.clientY + 16;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
const ocultarTip = () => { tip.style.opacity = 0; };

function conTip(el, html, alClic) {
  el.addEventListener('mousemove', ev => mostrarTip(ev, html));
  el.addEventListener('mouseleave', ocultarTip);
  if (alClic) { el.style.cursor = 'pointer'; el.addEventListener('click', () => { ocultarTip(); alClic(); }); }
}

const SVG = 'http://www.w3.org/2000/svg';
const crear = (tag, attrs = {}) => {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};

/* ───────────────── barras horizontales (magnitud, una serie) ─────────────────
   Marcas delgadas, extremo del dato redondeado 4px, etiqueta directa a la
   derecha, sin cuadrícula compitiendo con el dato. */
function barrasH(cont, datos, op = {}) {
  cont.innerHTML = '';
  if (!datos.length) { cont.innerHTML = '<p class="loading">Sin datos para este filtro.</p>'; return; }

  /* El viewBox se dimensiona al ancho real del contenedor para que el tamaño de
     texto sea el mismo en todas las gráficas del tablero (escala 1:1). */
  const alto = 26, pad = 6, anchoVal = op.anchoValor ?? 116;
  const w = Math.max(cont.clientWidth || 720, 460);
  const anchoEtiq = Math.min(op.anchoEtiqueta ?? 250, w * 0.45);
  const h = datos.length * alto + 8;
  const x0 = anchoEtiq, x1 = w - anchoVal;
  const max = Math.max(...datos.map(d => d.valor), 1);
  const svg = crear('svg', { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: 'img' });
  svg.setAttribute('style', 'max-width:100%;height:auto');

  datos.forEach((d, i) => {
    const y = i * alto + 4;
    const ancho = Math.max((d.valor / max) * (x1 - x0), d.valor > 0 ? 2 : 0);

    const et = crear('text', { x: x0 - 10, y: y + alto / 2 - pad + 4, 'text-anchor': 'end', class: 'lbl' });
    et.textContent = d.etiqueta.length > 42 ? d.etiqueta.slice(0, 41) + '…' : d.etiqueta;
    svg.appendChild(et);

    const barra = crear('rect', {
      x: x0, y, width: ancho, height: alto - pad * 2, rx: 4,
      fill: d.color || 'var(--series-1)', class: 'bar'
    });
    svg.appendChild(barra);
    conTip(barra, d.tip, d.alClic);

    const val = crear('text', { x: x0 + ancho + 8, y: y + alto / 2 - pad + 4, class: 'val' });
    val.textContent = d.valorTexto ?? num(d.valor);
    svg.appendChild(val);
  });

  svg.appendChild(crear('line', { x1: x0, y1: 2, x2: x0, y2: h - 4, class: 'baseline' }));
  cont.appendChild(svg);
}

/* ───────────────── heatmap (magnitud continua, un solo tono) ───────────────── */
function heatmap(cont, data, metrica) {
  cont.innerHTML = '';
  const { dias, horas, celdas, dias_nombre } = data;
  if (!dias.length) { cont.innerHTML = '<p class="loading">Sin bloques de horario para este filtro.</p>'; return; }

  const RAMPA = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
  const max = Math.max(...celdas.map(c => c[metrica]), 1);
  const ml = 44, mt = 22;
  const disponible = Math.max((cont.clientWidth || 760) - ml, 320);
  const cw = Math.max(Math.min(disponible / horas.length, 56), 26);
  const ch = Math.max(Math.min(cw * 0.72, 34), 22);
  const w = ml + horas.length * cw, h = mt + dias.length * ch + 30;
  const svg = crear('svg', { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: 'img' });
  svg.setAttribute('style', 'max-width:100%;height:auto');

  horas.forEach((hh, j) => {
    const t = crear('text', { x: ml + j * cw + cw / 2, y: mt - 8, 'text-anchor': 'middle', class: 'tick' });
    t.textContent = hh; svg.appendChild(t);
  });
  dias.forEach((d, i) => {
    const t = crear('text', { x: ml - 10, y: mt + i * ch + ch / 2 + 4, 'text-anchor': 'end', class: 'tick' });
    t.textContent = d; svg.appendChild(t);
  });

  celdas.forEach(c => {
    const i = dias.indexOf(c.dia), j = horas.indexOf(c.hora);
    if (i < 0 || j < 0) return;
    const v = c[metrica];
    const paso = v === 0 ? null : RAMPA[Math.min(RAMPA.length - 1, Math.floor((v / max) * RAMPA.length * 0.999))];
    const r = crear('rect', {
      x: ml + j * cw, y: mt + i * ch, width: cw, height: ch, rx: 3,
      fill: paso || 'var(--surface-2)', class: 'cell'
    });
    svg.appendChild(r);
    if (v > 0 && v / max > 0.55) {
      const t = crear('text', {
        x: ml + j * cw + cw / 2, y: mt + i * ch + ch / 2 + 4,
        'text-anchor': 'middle', fill: '#fff', style: 'font-size:10.5px;font-weight:600'
      });
      t.textContent = v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v;
      svg.appendChild(t);
    }
    conTip(r, `<b>${dias_nombre[c.dia]} ${c.hora}:00</b>
      <span class="r">${num(c.asignados)} estudiantes<br>${num(c.secciones)} secciones</span>`);
  });

  /* leyenda de la rampa: la identidad del color no queda al aire */
  const ly = mt + dias.length * ch + 14;
  RAMPA.forEach((c, k) => svg.appendChild(crear('rect', { x: ml + k * 22, y: ly, width: 20, height: 8, rx: 2, fill: c })));
  const t0 = crear('text', { x: ml + RAMPA.length * 22 + 8, y: ly + 8, class: 'tick' });
  t0.textContent = `0 → ${num(max)} ${metrica === 'asignados' ? 'estudiantes' : 'secciones'} por franja`;
  svg.appendChild(t0);
  cont.appendChild(svg);
}

/* ─────────────────────────── tablas ─────────────────────────── */
function tabla(el, columnas, filas, op = {}) {
  const th = columnas.map(c =>
    `<th class="${c.num ? 'num' : ''}" ${c.orden ? `data-orden="${c.orden}"` : ''}>${esc(c.titulo)}</th>`
  ).join('');
  const tb = filas.map((f, i) => '<tr data-i="' + i + '">' + columnas.map(c =>
    `<td class="${c.num ? 'num' : (c.ancho ? 'name' : '')}">${c.render(f)}</td>`).join('') + '</tr>').join('');
  el.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${tb || '<tr><td>Sin resultados.</td></tr>'}</tbody>`;
  if (op.alOrdenar) el.querySelectorAll('th[data-orden]').forEach(h =>
    h.addEventListener('click', () => op.alOrdenar(h.dataset.orden)));
  if (op.alClicFila) el.querySelectorAll('tbody tr[data-i]').forEach(tr =>
    tr.addEventListener('click', () => op.alClicFila(filas[+tr.dataset.i])));
}

/* Estados: color reservado + icono + etiqueta. El color nunca va solo. */
const ESTILO_ESTADO = {
  'Sobrecupo':           { color: 'var(--critical)', cls: 'b-critical', icono: '▲' },
  'Por llenarse':        { color: 'var(--warning)',  cls: 'b-warning',  icono: '●' },
  'Saludable':           { color: 'var(--good)',     cls: 'b-good',     icono: '✓' },
  'Holgada':             { color: 'var(--series-1)', cls: 'b-info',     icono: '○' },
  'Riesgo de cierre':    { color: 'var(--serious)',  cls: 'b-serious',  icono: '▼' },
  'Sin asignados':       { color: 'var(--text-muted)', cls: 'b-info',   icono: '—' },
  'Sin límite definido': { color: 'var(--text-muted)', cls: 'b-info',   icono: '?' },
};
const insigniaEstado = e => {
  const s = ESTILO_ESTADO[e] || ESTILO_ESTADO['Sin asignados'];
  return `<span class="badge ${s.cls}" data-icon="${s.icono}">${esc(e)}</span>`;
};

/* ═════════════════════ render de cada bloque ═════════════════════ */

/* R1-01 + R1-12 */
async function renderKPIs() {
  const k = await get('/api/kpis');
  const tiles = [
    { k: 'Asignaciones', v: num(k.asignados), d: `${num(k.promedio_seccion)} por sección en promedio` },
    {
      k: 'Ocupación del cupo', v: pct(k.ocupacion),
      d: `${num(k.asignados)} de ${num(k.cupo)} · ${num(k.cupo_libre)} lugares libres`,
      meter: k.ocupacion
    },
    { k: 'Secciones', v: num(k.secciones), d: `${num(k.cursos)} cursos distintos` },
    { k: 'Catedráticos', v: num(k.docentes), d: `${(k.asignados / Math.max(k.docentes, 1)).toFixed(0)} estudiantes por catedrático` },
    {
      k: 'Cobertura de auxiliares', v: pct(k.cobertura_auxiliares),
      d: `${num(k.secciones_con_auxiliar)} de ${num(k.secciones)} secciones · ${num(k.auxiliares)} auxiliares`,
      meter: k.cobertura_auxiliares
    },
    { k: 'Salones en uso', v: num(k.salones), d: 'combinaciones edificio–salón con clase presencial' },
  ];
  $('#kpis').innerHTML = tiles.map(t => `
    <div class="card tile">
      <div class="k">${t.k}</div>
      <div class="v">${t.v}</div>
      <div class="d">${t.d}</div>
      ${t.meter != null ? `<div class="meter"><i style="width:${Math.min(t.meter * 100, 100).toFixed(1)}%"></i></div>` : ''}
    </div>`).join('');

  /* Las columnas de procedencia existen en el reporte pero llegan vacías:
     se avisa en lugar de mostrar seis ceros que parecen un error del sistema. */
  const nota = $('#nota-procedencia');
  if (!k.procedencia_disponible) {
    nota.hidden = false;
    nota.innerHTML = '<b>Nota sobre el dato.</b> Este snapshot trae las columnas de procedencia ' +
      '(otra facultad, centros regionales, otra universidad, no inscritos, estudiantes de cierre) ' +
      'en cero, así que los ' + num(k.asignados) + ' asignados aparecen todos como regulares. ' +
      'El modelo ya guarda esas columnas: cuando el reporte las emita con dato, la vista las muestra sin cambios.';
  } else { nota.hidden = true; }
}

/* R1-04 y R1-05 */
async function renderOcupacion() {
  const o = await get('/api/ocupacion');
  const total = o.por_estado.reduce((a, b) => a + b.secciones, 0) || 1;

  barrasH($('#chart-estado'), o.por_estado.filter(e => e.secciones > 0).map(e => {
    const s = ESTILO_ESTADO[e.estado];
    return {
      etiqueta: `${s.icono}  ${e.estado}`,
      valor: e.secciones,
      valorTexto: `${num(e.secciones)} secc · ${((e.secciones / total) * 100).toFixed(0)}%`,
      color: s.color,
      tip: `<b>${e.estado}</b><span class="r">${num(e.secciones)} secciones<br>
            ${num(e.asignados)} estudiantes<br>cupo ${num(e.cupo)}</span>`,
      alClic: () => aplicar({ estado: state.filtros.estado === e.estado ? '' : e.estado })
    };
  }), { anchoEtiqueta: 210, anchoValor: 180 });

  const orden = ['0%', '1-20%', '21-40%', '41-60%', '61-80%', '81-100%', '>100%', 'n/d'];
  const ORD = ['#86b6ef', '#6da7ec', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', 'var(--text-muted)'];
  const idx = Object.fromEntries(o.histograma.map(r => [r.rango, r.secciones]));
  barrasH($('#chart-histograma'), orden.filter(r => idx[r]).map(r => ({
    etiqueta: r === 'n/d' ? 'sin cupo definido' : r,
    valor: idx[r],
    color: ORD[orden.indexOf(r)],
    tip: `<b>Ocupación ${r}</b><span class="r">${num(idx[r])} secciones</span>`
  })), { anchoEtiqueta: 130, anchoValor: 80 });

  const u = state.catalogos.umbrales;
  $('#nota-umbral').innerHTML = `<b>Umbrales.</b> Sobrecupo &gt;100% · por llenarse ≥${u.llena * 100}% · ` +
    `saludable ≥${u.saludable_bajo * 100}% · riesgo de cierre &lt;${u.riesgo_cierre * 100}%. ` +
    `El campo «Límite mínimo de asignados» viene en cero en el reporte, así que el umbral de cierre ` +
    `es un parámetro configurable del tablero, no un dato del archivo.`;
}

/* R1-03 */
async function renderCursos() {
  const orden = $('#f-orden-cursos').value;
  const { cursos } = await get('/api/cursos', { limite: 18, orden });
  barrasH($('#chart-cursos'), cursos.map(c => ({
    etiqueta: `${c.codigo} · ${c.curso}`,
    valor: orden === 'secciones' ? c.secciones : orden === 'promedio' ? c.promedio
      : orden === 'ocupacion' ? (c.ocupacion ?? 0) * 100 : c.asignados,
    valorTexto: orden === 'ocupacion' ? pct(c.ocupacion)
      : orden === 'secciones' ? `${c.secciones} secciones`
        : orden === 'promedio' ? `${num(c.promedio)} por sección`
          : `${num(c.asignados)} · ${c.secciones} secc`,
    tip: `<b>${esc(c.codigo)} ${esc(c.curso)}</b><span class="r">
          ${num(c.asignados)} asignados en ${c.secciones} secciones<br>
          promedio ${num(c.promedio)} · ocupación ${pct(c.ocupacion)}<br>
          ${c.sobrecupo ? `⚠ ${c.sobrecupo} en sobrecupo<br>` : ''}
          ${c.en_riesgo ? `▼ ${c.en_riesgo} en riesgo o vacías<br>` : ''}
          área: ${esc(c.area)}</span>`,
    alClic: () => aplicar({ codigo: undefined, q: c.codigo })
  })), { anchoEtiqueta: 330, anchoValor: 150 });
}

/* R1-09 · dos medidas de escalas distintas no llevan dos ejes:
   la barra codifica estudiantes y la etiqueta directa dice las secciones. */
async function renderDistribucion(columna, cont, colores) {
  const { datos } = await get(`/api/distribucion/${columna}`);
  barrasH(cont, datos.map((d, i) => ({
    etiqueta: d.etiqueta ?? '(sin dato)',
    valor: d.asignados,
    valorTexto: `${num(d.asignados)} · ${num(d.secciones)} secc`,
    color: colores[i % colores.length],
    tip: `<b>${esc(d.etiqueta)}</b><span class="r">${num(d.asignados)} estudiantes<br>
          ${num(d.secciones)} secciones<br>cupo ${num(d.cupo)}</span>`,
    alClic: () => aplicar({ [columna]: state.filtros[columna] === d.etiqueta ? '' : d.etiqueta })
  })), { anchoEtiqueta: 170, anchoValor: 175 });
}

/* R1-08 */
async function renderHeatmap() {
  const data = await get('/api/heatmap');
  heatmap($('#chart-heatmap'), data, $('#f-metrica-heat').value);
}

/* R1-06 */
async function renderDocentes() {
  const { docentes } = await get('/api/docentes', { limite: 40, orden: $('#f-orden-docentes').value });
  tabla($('#tbl-docentes'), [
    { titulo: 'Catedrático', ancho: 1, render: d => esc(d.docente) },
    { titulo: 'Secc', num: 1, render: d => d.secciones },
    { titulo: 'Cursos', num: 1, render: d => d.cursos },
    { titulo: 'Estudiantes', num: 1, render: d => num(d.asignados) },
    { titulo: 'H/sem', num: 1, render: d => num(d.horas_semana) },
    { titulo: 'Aux', num: 1, render: d => d.auxiliares },
  ], docentes, { alClicFila: d => aplicar({ docente: undefined, q: d.docente }) });
}

/* R1-07 */
async function renderAuxiliares() {
  const a = await get('/api/auxiliares', { limite: 40 });
  const r = a.resumen;
  $('#aux-resumen').innerHTML =
    `<span><b>${num(r.con_auxiliar)}</b> de ${num(r.secciones)} secciones con auxiliar</span>
     <span><b>${num(r.asignados_sin_auxiliar)}</b> estudiantes en secciones sin auxiliar</span>`;

  if (state.tabAux === 'ranking') {
    tabla($('#tbl-aux'), [
      { titulo: 'Auxiliar', ancho: 1, render: x => esc(x.nombre) },
      { titulo: 'Secc', num: 1, render: x => x.secciones },
      { titulo: 'Cursos', num: 1, render: x => x.cursos },
      { titulo: 'Estudiantes', num: 1, render: x => num(x.asignados) },
    ], a.ranking, { alClicFila: x => aplicar({ q: x.nombre }) });
  } else {
    tabla($('#tbl-aux'), [
      { titulo: 'Curso', ancho: 1, render: x => `${esc(x.codigo)} · ${esc(x.curso)}` },
      { titulo: 'Secc', render: x => esc(x.seccion) },
      { titulo: 'Tipo', render: x => esc(x.tipo) },
      { titulo: 'Estudiantes', num: 1, render: x => num(x.total) },
      { titulo: 'Estado', render: x => insigniaEstado(x.estado) },
    ], a.sin_auxiliar, { alClicFila: x => aplicar({ q: x.codigo }) });
  }
}

/* R1-10 */
async function renderSecciones() {
  const d = await get('/api/secciones', { limite: state.limite, offset: state.offset, orden: state.orden });
  tabla($('#tbl-secciones'), [
    { titulo: 'Tipo', render: f => esc(f.tipo) },
    { titulo: 'Código', orden: 'codigo', render: f => esc(f.codigo) },
    { titulo: 'Curso', orden: 'curso', ancho: 1, render: f => esc(f.curso) },
    { titulo: 'Secc', render: f => esc(f.seccion) },
    { titulo: 'Catedrático', orden: 'docente', ancho: 1, render: f => esc(f.docente) },
    { titulo: 'Auxiliares', ancho: 1, render: f => esc(f.auxiliares) || '<span style="color:var(--text-muted)">—</span>' },
    { titulo: 'Salón', render: f => esc([f.edificio, f.salon].filter(Boolean).join(' ')) },
    { titulo: 'Días', render: f => esc(f.dias) },
    { titulo: 'Horario', render: f => esc([f.hora_inicio, f.hora_fin].filter(Boolean).join('–')) },
    { titulo: 'Asignados', num: 1, orden: 'asignados', render: f => num(f.total) },
    { titulo: 'Cupo', num: 1, render: f => num(f.limite) },
    { titulo: 'Ocup.', num: 1, orden: 'ocupacion', render: f => pct(f.ocupacion) },
    { titulo: 'Estado', render: f => insigniaEstado(f.estado) },
  ], d.filas, {
    alOrdenar: o => {
      state.orden = (state.orden === o && o === 'ocupacion') ? 'ocupacion_asc' : o;
      state.offset = 0; renderSecciones();
    }
  });
  const desde = d.total ? state.offset + 1 : 0;
  $('#paginacion').textContent =
    `${num(desde)}–${num(Math.min(state.offset + state.limite, d.total))} de ${num(d.total)} secciones`;
  $('#btn-prev').disabled = state.offset === 0;
  $('#btn-next').disabled = state.offset + state.limite >= d.total;
}

/* ═════════════════════ orquestación ═════════════════════ */
async function renderTodo() {
  escribirURL();
  await Promise.all([
    renderKPIs(), renderOcupacion(), renderCursos(),
    renderDistribucion('modalidad', $('#chart-modalidad'), ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']),
    renderDistribucion('jornada', $('#chart-jornada'), ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']),
    renderHeatmap(), renderDocentes(), renderAuxiliares(), renderSecciones(),
  ]).catch(e => {
    console.error(e);
    $('#kpis').innerHTML = `<div class="card"><b>Error al consultar la API.</b><br>
      <span class="hint">${esc(e.message)}</span></div>`;
  });
}

function aplicar(cambios) {
  for (const [k, v] of Object.entries(cambios)) {
    if (v) state.filtros[k] = v; else delete state.filtros[k];
  }
  state.offset = 0;
  sincronizarControles();
  renderTodo();
  scrollTo({ top: 0, behavior: 'smooth' });
}

function sincronizarControles() {
  document.querySelectorAll('[data-filter]').forEach(el => {
    el.value = state.filtros[el.dataset.filter] ?? '';
  });
  $('#btn-foco').textContent = state.filtros.area === state.catalogos.area_foco
    ? 'Ver toda la Facultad' : 'Solo Ciencias y Sistemas';
}

async function cargarCatalogos() {
  const c = await get('/api/catalogos');
  state.catalogos = c;
  const snap = c.snapshot || {};
  $('#provenance').innerHTML = `
    <span class="pill">📄 <b>${esc(snap.archivo || 'sin archivo')}</b></span>
    <span class="pill">🗓 ${esc(snap.periodo || 'período n/d')}</span>
    <span class="pill">⏱ corte ${esc((snap.fecha_corte || '').replace('T', ' ').slice(0, 16) || 'n/d')}</span>
    <span class="pill">${num(snap.total_secciones)} secciones · ${num(snap.total_asignados)} asignaciones</span>
    <span style="color:var(--text-muted)">Snapshot de solo lectura: refleja el corte del reporte, no el estado en vivo.</span>`;

  const llenar = (sel, valores, etiquetaTodos) => {
    sel.innerHTML = `<option value="">${etiquetaTodos}</option>` +
      valores.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  };
  llenar($('#f-tipo'), c.tipo, 'Clase y laboratorio');
  llenar($('#f-area'), c.area, 'Todas las áreas');
  llenar($('#f-jornada'), c.jornada, 'Todas');
  llenar($('#f-modalidad'), c.modalidad, 'Todas');
  llenar($('#f-edificio'), c.edificio, 'Todos');
  llenar($('#f-estado'), c.estado, 'Todos');

  const { snapshots } = await get('/api/snapshots');
  $('#f-snapshot').innerHTML = snapshots.map(s =>
    `<option value="${s.id}">${esc(s.periodo || s.archivo)} — corte ${esc((s.fecha_corte || '').slice(0, 10))}</option>`
  ).join('');
  if (snap.id) state.filtros.snapshot_id = String(snap.id);
  $('#f-snapshot').value = snap.id ?? '';
  if (snapshots.length < 2) {
    $('#f-snapshot').title = 'Con dos o más snapshots se habilita la comparación entre cortes (Release 2).';
  }
}

/* ─────────────────────────── eventos ─────────────────────────── */
function conectarEventos() {
  document.querySelectorAll('select[data-filter], input[data-filter]').forEach(el => {
    const evento = el.tagName === 'INPUT' ? 'input' : 'change';
    let t;
    el.addEventListener(evento, () => {
      clearTimeout(t);
      t = setTimeout(() => aplicar({ [el.dataset.filter]: el.value }), evento === 'input' ? 320 : 0);
    });
  });
  $('#f-orden-cursos').addEventListener('change', renderCursos);
  $('#f-orden-docentes').addEventListener('change', renderDocentes);
  $('#f-metrica-heat').addEventListener('change', renderHeatmap);
  $('#f-pagina').addEventListener('change', e => {
    state.limite = +e.target.value; state.offset = 0; renderSecciones();
  });
  $('#btn-prev').addEventListener('click', () => {
    state.offset = Math.max(0, state.offset - state.limite); renderSecciones();
  });
  $('#btn-next').addEventListener('click', () => { state.offset += state.limite; renderSecciones(); });
  $('#btn-reset').addEventListener('click', () => {
    const s = state.filtros.snapshot_id;
    state.filtros = s ? { snapshot_id: s } : {};
    aplicar({});
  });
  $('#btn-foco').addEventListener('click', () => {
    const foco = state.catalogos.area_foco;
    aplicar({ area: state.filtros.area === foco ? '' : foco });
  });
  $('#btn-export').addEventListener('click', () => { location.href = `/api/export.csv?${qs({ orden: state.orden })}`; });
  $('#tabs-aux').addEventListener('click', e => {
    const b = e.target.closest('button[data-tab]');
    if (!b) return;
    state.tabAux = b.dataset.tab;
    $('#tabs-aux').querySelectorAll('button').forEach(x =>
      x.setAttribute('aria-selected', String(x === b)));
    renderAuxiliares();
  });
  $('#btn-theme').addEventListener('click', () => {
    const actual = document.documentElement.dataset.theme;
    const oscuro = actual ? actual === 'dark'
      : matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.dataset.theme = oscuro ? 'light' : 'dark';
    renderTodo();
  });
  addEventListener('resize', () => { clearTimeout(window.__rz); window.__rz = setTimeout(renderHeatmap, 200); });
}

(async function iniciar() {
  leerURL();
  try {
    await cargarCatalogos();
  } catch (e) {
    $('#provenance').innerHTML = `<span class="pill">⚠ ${esc(e.message)}</span>`;
    return;
  }
  conectarEventos();
  sincronizarControles();
  await renderTodo();
})();
