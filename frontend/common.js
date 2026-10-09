/* Utilidades compartidas por el tablero y la página de cargas.
   Sin dependencias: SVG generado a mano para que todo corra en la red interna sin CDN. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const nf = new Intl.NumberFormat('es-GT');
const num = n => nf.format(Math.round(n ?? 0));
const pct = v => (v === null || v === undefined) ? '—' : (v * 100).toFixed(1) + '%';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fechaCorta = iso => iso ? iso.replace('T', ' ').slice(0, 16) : '—';
const fechaHumana = iso => {
  if (!iso) return '—';
  const [f, h] = iso.split('T');
  const [y, m, d] = f.split('-');
  return `${d}/${m}/${y}${h ? ' ' + h.slice(0, 5) : ''}`;
};

/* ─────────────────────────── API ─────────────────────────── */
const almacen = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch { /* sin almacenamiento */ } },
};

class ErrorApi extends Error {
  constructor(status, detalle) { super(typeof detalle === 'string' ? detalle : JSON.stringify(detalle)); this.status = status; this.detalle = detalle; }
}

async function api(ruta, { metodo = 'GET', params = null, cuerpo = null, admin = false } = {}) {
  const url = params ? `${ruta}?${new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''))}` : ruta;
  const headers = {};
  if (admin && almacen.get('adminToken')) headers['X-Admin-Token'] = almacen.get('adminToken');
  const r = await fetch(url, { method: metodo, body: cuerpo, headers });
  if (!r.ok) {
    let detalle = r.statusText;
    try { detalle = (await r.json()).detail ?? detalle; } catch { /* no es JSON */ }
    throw new ErrorApi(r.status, detalle);
  }
  return r.json();
}

/* ─────────────────────────── tema ─────────────────────────── */
function conectarTema(boton, alCambiar) {
  const guardado = almacen.get('tema');
  if (guardado) document.documentElement.dataset.theme = guardado;
  boton?.addEventListener('click', () => {
    const actual = document.documentElement.dataset.theme;
    const oscuro = actual ? actual === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    const nuevo = oscuro ? 'light' : 'dark';
    document.documentElement.dataset.theme = nuevo;
    almacen.set('tema', nuevo);
    alCambiar?.();
  });
}

/* ─────────────────────────── tooltip ─────────────────────────── */
function tip() { return $('#tip'); }
function mostrarTip(ev, html) {
  const t = tip(); if (!t) return;
  t.innerHTML = html; t.style.opacity = 1;
  const r = t.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY - r.height - 10;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y < 8) y = ev.clientY + 16;
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
const ocultarTip = () => { const t = tip(); if (t) t.style.opacity = 0; };
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
function lienzo(w, h) {
  const svg = crear('svg', { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: 'img' });
  svg.setAttribute('style', `width:${w}px;max-width:100%;height:auto`);
  return svg;
}
const anchoDe = cont => Math.max(cont.clientWidth || 720, 360);
const recortar = (t, n) => t.length > n ? t.slice(0, n - 1) + '…' : t;

/* ─────────── barras horizontales: magnitud de una serie, etiqueta directa ─────────── */
function barrasH(cont, datos, op = {}) {
  cont.innerHTML = '';
  if (!datos.length) { cont.innerHTML = `<p class="loading">${op.vacio || 'Sin datos para este filtro.'}</p>`; return; }
  const alto = 26, pad = 6, anchoVal = op.anchoValor ?? 116;
  const w = anchoDe(cont), anchoEtiq = Math.min(op.anchoEtiqueta ?? 250, w * 0.45);
  const h = datos.length * alto + (op.meta != null ? 22 : 8);
  const x0 = anchoEtiq, x1 = w - anchoVal;
  const max = Math.max(...datos.map(d => d.valor), op.meta ?? 0, 1);
  const svg = lienzo(w, h);
  datos.forEach((d, i) => {
    const y = i * alto + 4;
    const largo = Math.max((d.valor / max) * (x1 - x0), d.valor > 0 ? 2 : 0);
    const et = crear('text', { x: x0 - 10, y: y + alto / 2 - pad + 4, 'text-anchor': 'end', class: 'lbl' });
    et.textContent = recortar(d.etiqueta, Math.min(op.maxCar ?? 60, Math.floor((anchoEtiq - 14) / 6.4)));
    svg.appendChild(et);
    const barra = crear('rect', { x: x0, y, width: largo, height: alto - pad * 2, rx: 4, fill: d.color || 'var(--series-1)', class: 'bar' });
    svg.appendChild(barra);
    conTip(barra, d.tip ?? `<b>${esc(d.etiqueta)}</b><span class="r">${num(d.valor)}</span>`, d.alClic);
    const val = crear('text', { x: x0 + largo + 8, y: y + alto / 2 - pad + 4, class: 'val' });
    val.textContent = d.valorTexto ?? num(d.valor);
    svg.appendChild(val);
  });
  if (op.meta != null) {
    const xm = x0 + (op.meta / max) * (x1 - x0);
    svg.appendChild(crear('line', { x1: xm, y1: 0, x2: xm, y2: h - 18, stroke: 'var(--text-secondary)', 'stroke-dasharray': '4 4', 'stroke-width': 1.5 }));
    const t = crear('text', { x: xm, y: h - 4, 'text-anchor': 'middle', class: 'tick' });
    t.textContent = op.metaTexto ?? `meta ${op.meta}`;
    svg.appendChild(t);
  }
  svg.appendChild(crear('line', { x1: x0, y1: 2, x2: x0, y2: h - (op.meta != null ? 18 : 4), class: 'baseline' }));
  cont.appendChild(svg);
}

/* ─────────── barras apiladas al 100% (composición por categoría) ─────────── */
function barrasApiladas(cont, filas, series, op = {}) {
  cont.innerHTML = '';
  if (!filas.length) { cont.innerHTML = `<p class="loading">${op.vacio || 'Sin datos para este filtro.'}</p>`; return; }
  const alto = 28, pad = 7, w = anchoDe(cont);
  const anchoEtiq = Math.min(op.anchoEtiqueta ?? 280, w * 0.42), anchoVal = 64;
  const x0 = anchoEtiq, x1 = w - anchoVal, h = filas.length * alto + 30;
  const svg = lienzo(w, h);
  [0, .25, .5, .75, 1].forEach(p => {
    const x = x0 + p * (x1 - x0);
    svg.appendChild(crear('line', { x1: x, y1: 0, x2: x, y2: h - 22, class: 'gridline' }));
    const t = crear('text', { x, y: h - 6, 'text-anchor': 'middle', class: 'tick' });
    t.textContent = `${p * 100}%`; svg.appendChild(t);
  });
  filas.forEach((f, i) => {
    const y = i * alto + 2;
    const total = series.reduce((a, s) => a + (f[s.clave] || 0), 0) || 1;
    const et = crear('text', { x: x0 - 10, y: y + alto / 2 + 2, 'text-anchor': 'end', class: 'lbl' });
    et.textContent = recortar(f.etiqueta, Math.min(op.maxCar ?? 60, Math.floor((anchoEtiq - 14) / 6.4))); svg.appendChild(et);
    let x = x0;
    series.forEach(s => {
      const v = f[s.clave] || 0; if (!v) return;
      const largo = (v / total) * (x1 - x0);
      const r = crear('rect', { x: x + 1, y: y + pad / 2, width: Math.max(largo - 2, 1), height: alto - pad, rx: 3, fill: s.color, class: 'bar' });
      svg.appendChild(r);
      conTip(r, `<b>${esc(f.etiqueta)}</b><span class="r">${esc(s.nombre)}: ${num(v)} de ${num(total)} (${((v / total) * 100).toFixed(0)}%)</span>`, f.alClic);
      x += largo;
    });
    const t = crear('text', { x: x1 + 8, y: y + alto / 2 + 2, class: 'val' });
    t.textContent = op.textoFila ? op.textoFila(f, total) : num(total);
    svg.appendChild(t);
  });
  cont.appendChild(svg);
}

/* ─────────── línea simple (una serie a lo largo de cortes) ─────────── */
function linea(cont, puntos, op = {}) {
  cont.innerHTML = '';
  if (puntos.length < 2) { cont.innerHTML = `<p class="loading">${op.vacio || 'Se necesitan al menos dos puntos.'}</p>`; return; }
  const w = anchoDe(cont), h = op.alto ?? 210, ml = 56, mr = 24, mt = 18, mb = 34;
  const max = Math.max(...puntos.map(p => p.valor), 1) * 1.1;
  const X = i => ml + (i / (puntos.length - 1)) * (w - ml - mr);
  const Y = v => mt + (1 - v / max) * (h - mt - mb);
  const svg = lienzo(w, h);
  for (let k = 0; k <= 4; k++) {
    const v = (max / 4) * k, y = Y(v);
    svg.appendChild(crear('line', { x1: ml, y1: y, x2: w - mr, y2: y, class: k ? 'gridline' : 'baseline' }));
    const t = crear('text', { x: ml - 8, y: y + 4, 'text-anchor': 'end', class: 'tick' });
    t.textContent = num(v); svg.appendChild(t);
  }
  svg.appendChild(crear('path', { d: puntos.map((p, i) => `${i ? 'L' : 'M'}${X(i)},${Y(p.valor)}`).join(' '), fill: 'none', stroke: 'var(--series-1)', 'stroke-width': 2 }));
  puntos.forEach((p, i) => {
    const c = crear('circle', { cx: X(i), cy: Y(p.valor), r: 4.5, fill: 'var(--series-1)', stroke: 'var(--surface-1)', 'stroke-width': 2 });
    svg.appendChild(c);
    const hit = crear('circle', { cx: X(i), cy: Y(p.valor), r: 14, fill: 'transparent' });
    svg.appendChild(hit);
    conTip(hit, p.tip ?? `<b>${esc(p.etiqueta)}</b><span class="r">${num(p.valor)}</span>`, p.alClic);
    if (i === 0 || i === puntos.length - 1 || puntos.length <= 6) {
      const t = crear('text', { x: X(i), y: h - 12, 'text-anchor': 'middle', class: 'tick' });
      t.textContent = p.etiqueta; svg.appendChild(t);
    }
  });
  const ult = puntos[puntos.length - 1];
  const tv = crear('text', { x: X(puntos.length - 1) - 6, y: Y(ult.valor) - 10, 'text-anchor': 'end', class: 'val' });
  tv.textContent = num(ult.valor); svg.appendChild(tv);
  cont.appendChild(svg);
}

/* ─────────── heatmap (magnitud continua, un solo tono) ─────────── */
function heatmap(cont, data, metrica) {
  cont.innerHTML = '';
  const { dias, horas, celdas, dias_nombre } = data;
  if (!dias.length) { cont.innerHTML = '<p class="loading">Sin bloques de horario para este filtro.</p>'; return; }
  const RAMPA = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
  const max = Math.max(...celdas.map(c => c[metrica]), 1);
  const ml = 44, mt = 22, disponible = Math.max(anchoDe(cont) - ml, 320);
  const cw = Math.max(Math.min(disponible / horas.length, 56), 26), ch = Math.max(Math.min(cw * 0.72, 34), 22);
  const w = ml + horas.length * cw, h = mt + dias.length * ch + 30;
  const svg = lienzo(w, h);
  horas.forEach((hh, j) => { const t = crear('text', { x: ml + j * cw + cw / 2, y: mt - 8, 'text-anchor': 'middle', class: 'tick' }); t.textContent = hh; svg.appendChild(t); });
  dias.forEach((d, i) => { const t = crear('text', { x: ml - 10, y: mt + i * ch + ch / 2 + 4, 'text-anchor': 'end', class: 'tick' }); t.textContent = d; svg.appendChild(t); });
  celdas.forEach(c => {
    const i = dias.indexOf(c.dia), j = horas.indexOf(c.hora); if (i < 0 || j < 0) return;
    const v = c[metrica];
    const paso = v === 0 ? null : RAMPA[Math.min(RAMPA.length - 1, Math.floor((v / max) * RAMPA.length * 0.999))];
    const r = crear('rect', { x: ml + j * cw, y: mt + i * ch, width: cw, height: ch, rx: 3, fill: paso || 'var(--surface-2)', class: 'cell' });
    svg.appendChild(r);
    if (v > 0 && v / max > 0.55) {
      const t = crear('text', { x: ml + j * cw + cw / 2, y: mt + i * ch + ch / 2 + 4, 'text-anchor': 'middle', fill: '#fff', style: 'font-size:10.5px;font-weight:600' });
      t.textContent = v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v; svg.appendChild(t);
    }
    conTip(r, `<b>${dias_nombre[c.dia]} ${c.hora}:00</b><span class="r">${num(c.asignados)} estudiantes<br>${num(c.secciones)} secciones</span>`);
  });
  const ly = mt + dias.length * ch + 14;
  RAMPA.forEach((c, k) => svg.appendChild(crear('rect', { x: ml + k * 22, y: ly, width: 20, height: 8, rx: 2, fill: c })));
  const t0 = crear('text', { x: ml + RAMPA.length * 22 + 8, y: ly + 8, class: 'tick' });
  t0.textContent = `0 → ${num(max)} ${metrica === 'asignados' ? 'estudiantes' : 'secciones'} por franja`;
  svg.appendChild(t0);
  cont.appendChild(svg);
}

/* ─────────────────────────── tablas ─────────────────────────── */
function tabla(el, columnas, filas, op = {}) {
  const th = columnas.map(c => `<th class="${c.num ? 'num' : ''}" ${c.orden ? `data-orden="${c.orden}" title="Ordenar"` : ''}>${esc(c.titulo)}</th>`).join('');
  const tb = filas.map((f, i) => `<tr data-i="${i}">` + columnas.map(c => `<td class="${c.num ? 'num' : (c.ancho ? 'name' : '')}">${c.render(f)}</td>`).join('') + '</tr>').join('');
  el.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${tb || `<tr><td colspan="${columnas.length}">${op.vacio || 'Sin resultados.'}</td></tr>`}</tbody>`;
  if (op.alOrdenar) $$('th[data-orden]', el).forEach(h => h.addEventListener('click', () => op.alOrdenar(h.dataset.orden)));
  if (op.alClicFila) $$('tbody tr[data-i]', el).forEach(tr => { tr.style.cursor = 'pointer'; tr.addEventListener('click', () => op.alClicFila(filas[+tr.dataset.i])); });
}

/* Estados: color reservado + icono + etiqueta. El color nunca va solo. */
const ESTILO_ESTADO = {
  'Sobrecupo': { color: 'var(--critical)', cls: 'b-critical', icono: '▲' },
  'Por llenarse': { color: 'var(--warning)', cls: 'b-warning', icono: '●' },
  'Saludable': { color: 'var(--good)', cls: 'b-good', icono: '✓' },
  'Holgada': { color: 'var(--series-1)', cls: 'b-info', icono: '○' },
  'Riesgo de cierre': { color: 'var(--serious)', cls: 'b-serious', icono: '▼' },
  'Sin asignados': { color: 'var(--text-muted)', cls: 'b-info', icono: '—' },
  'Sin límite definido': { color: 'var(--text-muted)', cls: 'b-info', icono: '?' },
  'Cerrada': { color: 'var(--axis)', cls: 'b-info', icono: '✕' },
  'Pendiente': { color: 'var(--critical)', cls: 'b-critical', icono: '!' },
  'En revisión': { color: 'var(--warning)', cls: 'b-warning', icono: '●' },
  'Al día': { color: 'var(--good)', cls: 'b-good', icono: '✓' },
};
const insignia = e => {
  const s = ESTILO_ESTADO[e] || ESTILO_ESTADO['Sin asignados'];
  return `<span class="badge ${s.cls}" data-icon="${s.icono}">${esc(e)}</span>`;
};


/* ─────────── histórico + pronóstico con intervalo ─────────── */
function pronosticoChart(cont, serie, anioObjetivo) {
  cont.innerHTML = '';
  if (!serie) { cont.innerHTML = '<p class="loading">Sin datos.</p>'; return; }
  const hist = serie.historia;
  const w = anchoDe(cont), h = 230, ml = 64, mr = 70, mt = 18, mb = 34;
  const anios = [...hist.map(x => x.anio), anioObjetivo];
  const a0 = Math.min(...anios), a1 = Math.max(...anios);
  const max = Math.max(...hist.map(x => x.asignados), serie.intervalo_alto) * 1.08;
  const X = a => ml + (a1 === a0 ? 0.5 : (a - a0) / (a1 - a0)) * (w - ml - mr);
  const Y = v => mt + (1 - v / max) * (h - mt - mb);
  const svg = lienzo(w, h);
  for (let k = 0; k <= 4; k++) {
    const v = (max / 4) * k, y = Y(v);
    svg.appendChild(crear('line', { x1: ml, y1: y, x2: w - mr, y2: y, class: k ? 'gridline' : 'baseline' }));
    const t = crear('text', { x: ml - 8, y: y + 4, 'text-anchor': 'end', class: 'tick' }); t.textContent = num(v); svg.appendChild(t);
  }
  anios.forEach(a => { const t = crear('text', { x: X(a), y: h - 12, 'text-anchor': 'middle', class: 'tick' }); t.textContent = a; svg.appendChild(t); });
  svg.appendChild(crear('path', { d: hist.map((p, i) => `${i ? 'L' : 'M'}${X(p.anio)},${Y(p.asignados)}`).join(' '), fill: 'none', stroke: 'var(--series-1)', 'stroke-width': 2 }));
  const ult = hist[hist.length - 1];
  svg.appendChild(crear('line', { x1: X(ult.anio), y1: Y(ult.asignados), x2: X(anioObjetivo), y2: Y(serie.prediccion), stroke: 'var(--series-2)', 'stroke-width': 2, 'stroke-dasharray': '5 4' }));
  const xa = X(anioObjetivo);
  svg.appendChild(crear('rect', { x: xa - 7, y: Y(serie.intervalo_alto), width: 14, height: Math.max(Y(serie.intervalo_bajo) - Y(serie.intervalo_alto), 2), rx: 3, fill: 'var(--series-2)', opacity: 0.22 }));
  hist.forEach(p => {
    const c = crear('circle', { cx: X(p.anio), cy: Y(p.asignados), r: 4.5, fill: 'var(--series-1)', stroke: 'var(--surface-1)', 'stroke-width': 2 });
    svg.appendChild(c); conTip(c, `<b>${p.anio}</b><span class="r">${num(p.asignados)} asignados</span>`);
  });
  const cp = crear('circle', { cx: xa, cy: Y(serie.prediccion), r: 5.5, fill: 'var(--series-2)', stroke: 'var(--surface-1)', 'stroke-width': 2 });
  svg.appendChild(cp);
  conTip(cp, `<b>Predicción ${anioObjetivo}</b><span class="r">${num(serie.prediccion)} asignados<br>rango ${num(serie.intervalo_bajo)} – ${num(serie.intervalo_alto)}</span>`);
  const t = crear('text', { x: xa + 12, y: Y(serie.prediccion) + 4, class: 'val' }); t.textContent = num(serie.prediccion); svg.appendChild(t);
  const leyenda = crear('text', { x: ml, y: 12, class: 'tick' }); leyenda.textContent = '● histórico   ● predicción (barra = intervalo)'; svg.appendChild(leyenda);
  cont.appendChild(svg);
}
