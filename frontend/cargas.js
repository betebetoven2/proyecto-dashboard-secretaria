/* Página de carga de reportes (historia R1-15). */

const ICONO = { aceptado: '✓', reemplazo: '↻', duplicado: '=', vacio: '∅', rechazado: '✗', procesando: '…', eliminado: '🗑', reproceso: '⟳' };
const ETIQUETA = { aceptado: 'Cargado', reemplazo: 'Reemplazó un corte', duplicado: 'Ya estaba cargado', vacio: 'Reporte vacío', rechazado: 'Rechazado', procesando: 'Procesando', eliminado: 'Eliminado', reproceso: 'Reproceso' };
let salud = null;

function tarjeta(nombre, res) {
  const r = res?.resultado || 'procesando';
  const mensajes = (res?.mensajes || []).filter(m => m.nivel !== 'info' && m.texto !== res?.mensaje);
  return `<div class="resultado ${r}">
    <div class="icono" aria-hidden="true">${ICONO[r] || '?'}</div>
    <div>
      <div><span class="nombre">${esc(nombre)}</span><span class="etq">${ETIQUETA[r] || r}</span></div>
      <div class="msg">${res ? esc(res.mensaje) : 'Subiendo y validando…'}</div>
      ${mensajes.length ? `<ul>${mensajes.map(m => `<li><b>${m.nivel === 'error' ? 'Error' : 'Advertencia'}:</b> ${esc(m.texto)}${m.hoja ? ` <span class="hint">(${esc(m.hoja)}${m.fila ? `, fila ${m.fila}` : ''})</span>` : ''}</li>`).join('')}</ul>` : ''}
    </div></div>`;
}

async function subir(archivos) {
  const cont = $('#resultados');
  const lista = [...archivos];
  if (!lista.length) return;
  const ids = lista.map((f, i) => `res-${Date.now()}-${i}`);
  cont.insertAdjacentHTML('afterbegin', lista.map((f, i) => `<div id="${ids[i]}">${tarjeta(f.name, null)}</div>`).reverse().join(''));
  $('#siguiente').hidden = true;
  const cargados = [];
  for (let i = 0; i < lista.length; i++) {                       // de a uno: progreso visible por archivo
    const fd = new FormData();
    fd.append('archivos', lista[i], lista[i].name);
    let rs;
    try {
      const r = await api('/api/cargas', { metodo: 'POST', cuerpo: fd, admin: true });
      rs = r.resultados;
    } catch (e) {
      rs = [{ resultado: 'rechazado', mensaje: e.status === 401 ? 'Falta el token de administración o es incorrecto (arriba).' : e.status === 413 ? 'El archivo es demasiado grande para el servidor.' : `No se pudo subir: ${e.message}` }];
    }
    const esPaquete = rs.length > 1 || /\.zip$/i.test(lista[i].name);
    if (esPaquete) {                                               // un .zip: una tarjeta por reporte de adentro
      const cuenta = r => rs.filter(x => x.resultado === r).length;
      const partes = [['aceptado', 'cargados'], ['reemplazo', 'reemplazaron un corte'], ['duplicado', 'ya estaban'], ['vacio', 'vacíos'], ['rechazado', 'rechazados']]
        .filter(([r]) => cuenta(r)).map(([r, t]) => `${cuenta(r)} ${t}`);
      document.getElementById(ids[i]).innerHTML = `<div class="note" style="margin:8px 0 4px"><b>${esc(lista[i].name)}</b>: ${rs.length} reporte${rs.length === 1 ? '' : 's'} · ${partes.join(' · ')}</div>`
        + rs.map(x => tarjeta(x.archivo ? x.archivo.split(' › ').pop() : lista[i].name, x)).join('');
    } else {
      document.getElementById(ids[i]).innerHTML = tarjeta(lista[i].name, rs[0]);
    }
    rs.forEach(res => { if (res.cargado || res.resultado === 'duplicado') cargados.push(res); });
  }
  if (cargados.length) {
    const ultimo = cargados[cargados.length - 1];
    $('#siguiente').innerHTML = `<a class="btn primary" style="text-decoration:none" href="/?snapshot_id=${ultimo.snapshot_id}#resumen">Ver ${esc(ultimo.descripcion || 'el reporte')} en el tablero →</a>`;
    $('#siguiente').hidden = false;
  }
  await Promise.all([renderSnapshots(), renderCargas()]);
}

async function renderSnapshots() {
  const { snapshots } = await api('/api/snapshots');
  tabla($('#tbl-snapshots'), [
    { titulo: '#', num: 1, render: s => s.id },
    { titulo: 'Año', render: s => s.anio },
    { titulo: 'Período', ancho: 1, render: s => `${s.periodo_codigo ? s.periodo_codigo + ' · ' : ''}${esc(s.periodo_nombre)}` },
    { titulo: 'Corte', render: s => fechaHumana(s.fecha_corte) },
    { titulo: 'Secciones', num: 1, render: s => num(s.total_secciones) },
    { titulo: 'Asignados', num: 1, render: s => num(s.total_asignados) },
    { titulo: 'Archivo', ancho: 1, render: s => esc(s.archivo_nombre) },
    { titulo: 'Cargado', render: s => `${fechaHumana(s.cargado_en)}<br><span class="hint" style="margin:0">${esc(s.origen)}</span>` },
    { titulo: '', render: s => `<a href="/?snapshot_id=${s.id}#resumen">Ver</a> · <a href="/api/snapshots/${s.id}/original">Original</a> · <a href="#" data-eliminar="${s.id}" style="color:var(--critical)">Eliminar</a>` },
  ], snapshots, { vacio: 'Todavía no hay reportes cargados.' });
  $$('[data-eliminar]').forEach(a => a.addEventListener('click', async ev => {
    ev.preventDefault();
    const s = snapshots.find(x => String(x.id) === a.dataset.eliminar);
    if (!window.confirm(`¿Quitar del tablero ${s.periodo_nombre} ${s.anio} (corte ${fechaHumana(s.fecha_corte)})?\n\nEl archivo original queda guardado y se puede volver a subir.`)) return;
    try { await api(`/api/snapshots/${s.id}`, { metodo: 'DELETE', admin: true }); }
    catch (e) { alert(e.status === 401 ? 'Falta el token de administración.' : e.message); }
    await Promise.all([renderSnapshots(), renderCargas()]);
  }));
}

async function renderCargas() {
  const { cargas } = await api('/api/cargas', { params: { limite: 200 } });
  tabla($('#tbl-cargas'), [
    { titulo: 'Cuándo', render: c => fechaHumana(c.cuando) },
    { titulo: 'Vía', render: c => esc(c.origen) },
    { titulo: 'Archivo', ancho: 1, render: c => esc(c.archivo_nombre) },
    { titulo: 'Resultado', render: c => `<span class="badge ${c.resultado === 'rechazado' ? 'b-critical' : c.resultado === 'vacio' ? 'b-warning' : ['aceptado', 'reemplazo'].includes(c.resultado) ? 'b-good' : 'b-info'}" data-icon="${ICONO[c.resultado] || ''}">${ETIQUETA[c.resultado] || esc(c.resultado)}</span>` },
    { titulo: 'Detalle', ancho: 1, render: c => esc(c.mensaje) },
  ], cargas, {
    vacio: 'Sin intentos de carga todavía.',
    alClicFila: c => {
      let mensajes = [];
      try { mensajes = JSON.parse(c.mensajes_json || '[]'); } catch { /* vacío */ }
      $('#resultados').insertAdjacentHTML('afterbegin', tarjeta(`${c.archivo_nombre} · ${fechaHumana(c.cuando)}`, { ...c, mensajes }));
      $('#resultados').scrollIntoView({ behavior: 'smooth' });
    },
  });
}

function conectar() {
  const dz = $('#dropzone'), input = $('#archivo');
  dz.addEventListener('click', () => input.click());
  dz.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', () => { subir(input.files); input.value = ''; });
  ['dragenter', 'dragover'].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.remove('over'); }));
  dz.addEventListener('drop', e => subir(e.dataTransfer.files));
  // Soltar fuera de la zona no debe hacer que el navegador abra el archivo.
  addEventListener('dragover', e => e.preventDefault());
  addEventListener('drop', e => e.preventDefault());

  $('#btn-carpeta').addEventListener('click', async () => {
    $('#carpeta-estado').textContent = 'Revisando…';
    try {
      const { resultados } = await api('/api/cargas/revisar-carpeta', { metodo: 'POST', admin: true });
      $('#carpeta-estado').textContent = resultados.length ? `${resultados.length} archivo(s) procesado(s).` : 'La carpeta está vacía.';
      if (resultados.length) $('#resultados').insertAdjacentHTML('afterbegin', resultados.map(r => tarjeta(r.archivo, r)).join(''));
    } catch (e) {
      $('#carpeta-estado').textContent = e.status === 401 ? 'Falta el token de administración.' : e.message;
    }
    await Promise.all([renderSnapshots(), renderCargas()]);
  });
  $('#btn-token').addEventListener('click', () => {
    almacen.set('adminToken', $('#token').value.trim());
    $('#token-estado').textContent = $('#token').value.trim() ? 'Guardado en este navegador.' : 'Token borrado.';
  });
}

(async function iniciar() {
  conectarTema($('#btn-theme'));
  conectar();
  try {
    salud = await api('/api/salud');
    $('#max-mb').textContent = salud.max_mb;
    if (salud.max_paquete_mb) $('#max-paquete-mb').textContent = salud.max_paquete_mb;
    $('#intervalo').textContent = salud.intervalo_entrada_seg;
    if (salud.requiere_token) {
      $('#token-card').hidden = false;
      $('#token').value = almacen.get('adminToken') || '';
    }
  } catch (e) {
    $('#resultados').innerHTML = `<p class="note">No se pudo contactar al servidor: ${esc(e.message)}</p>`;
  }
  await Promise.all([renderSnapshots(), renderCargas()]).catch(e => console.error(e));
})();
