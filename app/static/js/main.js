/* MotoExpres BI · lógica de la pantalla "Carga de datos" (JS puro, sin dependencias) */
window.MotoExpres = (function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const fmt = (n) => String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const EXT_OK = ['.xlsx', '.csv'];

  let archivo = null;      // File elegido por el usuario (o null -> respaldo en data/)
  let ocupado = false;

  /* ---------------- Terminal ---------------- */
  function claseLinea(t) {
    if (t.startsWith('$')) return 'cmd';
    if (t.startsWith('Listo')) return 'listo';
    if (t.startsWith('ERROR')) return 'fallo';
    if (/^\s{3,}/.test(t)) return 'detalle';
    return '';
  }
  function agregarLinea(texto) {
    const term = $('terminal');
    const div = document.createElement('div');
    div.className = claseLinea(texto);
    div.textContent = texto === '' ? '\u00A0' : texto;
    term.appendChild(div);
    term.scrollTop = term.scrollHeight;
  }
  function limpiarTerminal() { $('terminal').innerHTML = ''; }
  function pintarLogsIniciales() {
    const el = $('logs-iniciales');
    if (!el) return;
    let texto = '';
    try { texto = JSON.parse(el.textContent) || ''; } catch (e) { /* vacío */ }
    texto.split('\n').forEach((l) => { if (texto) agregarLinea(l); });
  }

  /* ---------------- Tarjetas del pipeline ---------------- */
  function tarjeta(n) { return document.querySelector(`.paso[data-paso="${n}"]`); }
  function pintarTarjeta(n, datos, estado) {
    const t = tarjeta(n);
    if (!t) return;
    if (datos) {
      t.querySelector('.paso-valor').textContent = datos.valor;
      t.querySelector('.paso-texto').textContent = datos.texto;
    }
    const b = t.querySelector('.barra-relleno');
    b.className = 'barra-relleno' + (estado ? ' ' + estado : '');
  }
  function reiniciarTarjetas() {
    for (let i = 1; i <= 5; i++) {
      const t = tarjeta(i);
      t.querySelector('.paso-valor').textContent = '–';
      t.querySelector('.paso-texto').textContent = 'pendiente';
      pintarTarjeta(i, null, '');
    }
  }

  /* ---------------- Mensajes ---------------- */
  function mensaje(tipo, html) {
    const m = $('mensaje-estado');
    if (!html) { m.hidden = true; return; }
    m.className = 'mensaje-estado ' + tipo;
    m.innerHTML = html;
    m.hidden = false;
  }
  function setOcupado(v) {
    ocupado = v;
    ['btn-ejecutar', 'btn-reiniciar', 'btn-elegir'].forEach((id) => { $(id).disabled = v; });
  }

  /* ---------------- Selector de archivo ---------------- */
  function elegirArchivo(f) {
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
    if (!EXT_OK.includes(ext)) {
      mensaje('error', `Formato <strong>${esc(ext)}</strong> no permitido. Seleccione un archivo .xlsx o .csv.`);
      return;
    }
    archivo = f;
    $('nombre-archivo').textContent = `${f.name} · ${(f.size / 1048576).toFixed(1).replace('.', ',')} MB`;
    $('zona-archivo').classList.add('con-archivo');
    $('btn-quitar').hidden = false;
    mensaje('', '');
  }
  function quitarArchivo() {
    archivo = null;
    $('archivo').value = '';
    $('nombre-archivo').innerHTML = 'Arrastre aquí su archivo o selecciónelo. Si no elige ninguno se usa <code>data/PROYECTO_MotoExpres.xlsx</code>.';
    $('zona-archivo').classList.remove('con-archivo');
    $('btn-quitar').hidden = true;
  }

  /* ---------------- Refresco de tablas desde PostgreSQL ---------------- */
  function chipDoble(h) {
    if (h.doble_carga === 'no_duplico') return '<span class="chip verde">✓ no duplicó</span>';
    if (h.doble_carga === 'primera') return '<span class="chip gris">primera</span>';
    return `<span class="chip ambar">+${fmt(h.filas_nuevas)} nuevas</span>`;
  }
  async function refrescar() {
    const r = await fetch('/api/resumen');
    const d = await r.json();
    if (!r.ok) return;

    $('origen').textContent = `Origen: ${d.archivo || 'ningún archivo cargado todavía'} · destino: PostgreSQL`;

    $('historial').innerHTML = (d.historial && d.historial.length)
      ? d.historial.map((h) => `<tr><td class="mono">${h.id}</td><td class="mono">${esc(h.hora)}</td>` +
          `<td class="mono num">${fmt(h.filas_nuevas)}</td><td class="mono num">${fmt(h.total_en_base)}</td>` +
          `<td>${chipDoble(h)}</td></tr>`).join('')
      : '<tr class="vacio"><td colspan="5">Aún no hay ejecuciones. Presione "Ejecutar carga".</td></tr>';

    $('descartes').innerHTML = (d.descartes && d.descartes.length)
      ? d.descartes.map((x) => `<tr><td>${esc(x.motivo)}</td><td class="mono num">${fmt(x.filas)}</td>` +
          `<td><span class="chip ${esc(x.chip)}">${esc(x.destino)}</span></td></tr>`).join('')
      : '<tr class="vacio"><td colspan="3">Se llena después de la primera carga.</td></tr>';

    $('cuarentena-total').textContent = fmt(d.cuarentena);

    if (d.tarjetas) d.tarjetas.forEach((t, i) => pintarTarjeta(i + 1, t, 'hecho'));
    else reiniciarTarjetas();
  }

  /* ---------------- Ejecutar carga (AJAX + sondeo) ---------------- */
  async function ejecutar() {
    if (ocupado) return;
    setOcupado(true);
    reiniciarTarjetas();
    pintarTarjeta(1, null, 'activo');
    mensaje('info', archivo
      ? `Subiendo <strong>${esc(archivo.name)}</strong> y procesando…`
      : 'Procesando <code>data/PROYECTO_MotoExpres.xlsx</code>…');

    const fd = new FormData();
    if (archivo) fd.append('archivo', archivo);

    let resp, job;
    try {
      resp = await fetch('/api/cargar', { method: 'POST', body: fd });
      job = await resp.json();
    } catch (e) {
      mensaje('error', 'No se pudo contactar al servidor: ' + esc(e.message));
      setOcupado(false);
      return;
    }
    if (!resp.ok) {
      mensaje('error', esc(job.error || 'Error al iniciar la carga'));
      reiniciarTarjetas();
      await refrescar();
      setOcupado(false);
      return;
    }

    if ($('terminal').childElementCount) agregarLinea('');
    sondear(job.job_id, 0);
  }

  async function sondear(jobId, desde) {
    let d;
    try {
      const r = await fetch(`/api/estado/${jobId}?desde=${desde}`);
      d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Estado no disponible');
    } catch (e) {
      mensaje('error', 'Se perdió la conexión con el servidor: ' + esc(e.message));
      setOcupado(false);
      return;
    }

    d.logs.forEach(agregarLinea);

    const hechos = Object.keys(d.pasos).map(Number);
    hechos.forEach((n) => pintarTarjeta(n, d.pasos[n], 'hecho'));
    if (d.estado === 'corriendo') {
      const siguiente = (hechos.length ? Math.max(...hechos) : 0) + 1;
      if (siguiente <= 5) pintarTarjeta(siguiente, null, 'activo');
      setTimeout(() => sondear(jobId, d.total_logs), 450);
      return;
    }

    if (d.estado === 'ok') {
      const r = d.resultado;
      const extra = r.nuevas === 0
        ? ' · <strong>✓ no duplicó</strong>'
        : '';
      mensaje('ok', `Carga terminada en ${String(r.duracion).replace('.', ',')} s: ` +
        `<strong>${fmt(r.nuevas)}</strong> nuevas · <strong>${fmt(r.total)}</strong> en fact_ordenes${extra}`);
    } else {
      mensaje('error', '<strong>La carga falló:</strong> ' + esc(d.error));
      reiniciarTarjetas();
    }
    await refrescar();
    setOcupado(false);
  }

  /* ---------------- Reiniciar base ---------------- */
  async function reiniciar() {
    if (ocupado) return;
    if (!window.confirm('Esto vacía TODAS las tablas (hechos, dimensiones, cuarentena e historial). ¿Continuar?')) return;
    setOcupado(true);
    try {
      const r = await fetch('/api/reiniciar', { method: 'POST' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'No se pudo reiniciar');
      limpiarTerminal();
      reiniciarTarjetas();
      mensaje('ok', 'Base reiniciada. Ya puede ejecutar la carga desde cero.');
      await refrescar();
    } catch (e) {
      mensaje('error', esc(e.message));
    }
    setOcupado(false);
  }

  /* ---------------- Inicio ---------------- */
  function initCarga() {
    pintarLogsIniciales();

    $('btn-elegir').addEventListener('click', () => $('archivo').click());
    $('archivo').addEventListener('change', (e) => elegirArchivo(e.target.files[0]));
    $('btn-quitar').addEventListener('click', quitarArchivo);
    $('btn-ejecutar').addEventListener('click', ejecutar);
    $('btn-reiniciar').addEventListener('click', reiniciar);

    const zona = $('zona-archivo');
    ['dragenter', 'dragover'].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add('arrastrando'); }));
    ['dragleave', 'drop'].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove('arrastrando'); }));
    zona.addEventListener('drop', (e) => elegirArchivo(e.dataTransfer.files[0]));
  }

  return { initCarga };
})();
