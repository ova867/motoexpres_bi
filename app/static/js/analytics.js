/**
 * MotoExpres BI · Analítica Hito 2
 * Implementación 100% DINÁMICA conectada a PostgreSQL.
 * AUDITORÍA: Cero mock data, cero arrays con números prefijados.
 */
window.MotoAnalytics = (function () {
  'use strict';

  let chartIngresos = null;
  let chartAlertas = null;

  /* ---------------- Gestión de Controles Globales de la Barra Superior ---------------- */
  function initTopbarGlobal() {
    // 1. Selector "Ver como:" dinámico
    const selVerComo = document.getElementById('selector-ver-como');
    if (selVerComo) {
      const urlParams = new URLSearchParams(window.location.search);
      const regUrl = urlParams.get('region');
      
      // Valida si la opción existe en el selector dinámico generado por la BD
      if (regUrl) {
        const opcionExiste = Array.from(selVerComo.options).some(opt => opt.value === regUrl);
        if (opcionExiste) {
          selVerComo.value = regUrl;
        } else {
          selVerComo.value = 'gerencia';
        }
      } else {
        selVerComo.value = 'gerencia';
      }

      selVerComo.addEventListener('change', (e) => {
        const val = e.target.value;
        const url = new URL(window.location.href);
        if (val === 'gerencia') {
          url.searchParams.delete('region');
        } else {
          url.searchParams.set('region', val);
        }
        window.location.href = url.toString();
      });
    }

    // 2. Checkbox "Notas del curso"
    const checkNotas = document.getElementById('check-notas-curso');
    const bannerNotas = document.getElementById('banner-notas-curso');
    if (checkNotas && bannerNotas) {
      const ocultar = localStorage.getItem('motoexpres_ocultar_notas') === '1';
      checkNotas.checked = !ocultar;
      bannerNotas.style.display = ocultar ? 'none' : 'flex';

      checkNotas.addEventListener('change', (e) => {
        const visible = e.target.checked;
        bannerNotas.style.display = visible ? 'flex' : 'none';
        localStorage.setItem('motoexpres_ocultar_notas', visible ? '0' : '1');
      });
    }

    // 3. Switch MotoExpres / NovaApp
    const btnsApp = document.querySelectorAll('.switch-app .btn-app');
    btnsApp.forEach(btn => {
      btn.addEventListener('click', () => {
        btnsApp.forEach(b => b.classList.remove('activo'));
        btn.classList.add('activo');
      });
    });
  }

  /* ---------------- VISTA 1: Tablero (Imagen 1) ---------------- */
  function initTableroExacto() {
    initTopbarGlobal();

    const canvas = document.getElementById('chart-ingresos-mes');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Leer datos dinámicos generados desde PostgreSQL en el backend
    let serie = [];
    let metaCallout = { idx_pico: -1, texto: '' };

    const elScript = document.getElementById('datos-tablero');
    if (elScript) {
      try {
        const dataJson = JSON.parse(elScript.textContent);
        if (Array.isArray(dataJson.serie_mensual)) {
          serie = dataJson.serie_mensual;
        }
        if (dataJson.meta_callout) {
          metaCallout = dataJson.meta_callout;
        }
      } catch (err) {
        console.error('Error al procesar serie del tablero:', err);
      }
    }

    // Manejo de estado vacío sin mocks
    if (serie.length === 0) {
      if (chartIngresos) chartIngresos.destroy();
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.font = '14px "Source Sans 3", sans-serif';
      ctx.fillStyle = '#8d9ab5';
      ctx.textAlign = 'center';
      ctx.fillText('No hay órdenes registradas para el período o región seleccionada.', canvas.width / 2, 100);
      return;
    }

    const meses = [];
    const ingresos = [];
    const pointRadii = [];
    const pointColors = [];
    const idxPico = metaCallout.idx_pico;
    const textoCallout = metaCallout.texto || '';

    serie.forEach((item, i) => {
      const anio = item.anio;
      const mesNum = item.mes;
      const esPico = (i === idxPico && idxPico >= 0);

      // Label del eje x: mostrar año en mes 1, o el mes del pico
      if (esPico) {
        const nomMes = item.nombre_mes ? item.nombre_mes.substring(0, 3) : 'Mes';
        meses.push(nomMes + ' ' + String(anio).substring(2));
      } else if (mesNum === 1) {
        meses.push(String(anio));
      } else {
        meses.push('');
      }

      ingresos.push(item.ingresos_m);
      pointRadii.push(esPico ? 6.5 : 0);
      pointColors.push(esPico ? '#dc2626' : '#1bb0c4');
    });

    const maxIngreso = Math.max(...ingresos, 50);
    const yMax = Math.ceil((maxIngreso * 1.2) / 50) * 50;

    // Plugin dinámico de Chart.js para dibujar el callout del pico
    const calloutPlugin = {
      id: 'calloutPicoDinamico',
      afterDatasetsDraw(chart) {
        if (idxPico < 0 || !textoCallout) return;
        const meta = chart.getDatasetMeta(0);
        const punto = meta.data[idxPico];
        if (!punto) return;

        const { x, y } = punto;
        const ctx2 = chart.ctx;
        ctx2.save();

        // Círculo rojo exterior
        ctx2.strokeStyle = '#dc2626';
        ctx2.lineWidth = 2.2;
        ctx2.beginPath();
        ctx2.arc(x, y, 7, 0, Math.PI * 2);
        ctx2.stroke();

        // Texto del callout
        ctx2.font = '600 12px "Source Sans 3", sans-serif';
        ctx2.fillStyle = '#dc2626';
        ctx2.fillText(textoCallout, x + 10, y - 8);

        ctx2.restore();
      }
    };

    if (chartIngresos) chartIngresos.destroy();

    chartIngresos = new Chart(ctx, {
      type: 'line',
      data: {
        labels: meses,
        datasets: [{
          data: ingresos,
          borderColor: '#1bb0c4',
          borderWidth: 2.2,
          backgroundColor: 'rgba(27, 176, 196, 0.1)',
          fill: true,
          tension: 0.3,
          pointRadius: pointRadii,
          pointBackgroundColor: pointColors,
          pointBorderColor: pointColors,
          pointHoverRadius: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#131b2d',
            callbacks: {
              label: (c) => `Ingresos: $ ${c.parsed.y} M`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#8d9ab5',
              font: { family: 'Source Sans 3', size: 12 },
              autoSkip: false,
            }
          },
          y: {
            min: 0,
            max: yMax,
            ticks: {
              stepSize: yMax > 400 ? 100 : (yMax > 150 ? 50 : 25),
              color: '#8d9ab5',
              font: { family: 'JetBrains Mono', size: 11 },
              callback: (v) => v
            },
            grid: { color: 'rgba(255,255,255,0.06)' }
          }
        }
      },
      plugins: [calloutPlugin]
    });
  }

  /* ---------------- VISTA 2: Explorar (Imagen 2) ---------------- */
  function initExplorarExacto() {
    initTopbarGlobal();
  }

  function toggleModoClase() {
    const body = document.body;
    body.classList.toggle('modo-clase-activo');
    const btn = document.getElementById('btn-modo-clase');
    if (btn) {
      const activo = body.classList.contains('modo-clase-activo');
      btn.textContent = activo ? '⏹ Salir modo clase' : '▶ Modo clase';
    }
  }

  /* ---------------- VISTA 3: Alertas (Imagen 3) ---------------- */
  function initAlertasExacto() {
    initTopbarGlobal();

    const canvas = document.getElementById('chart-ordenes-alertas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Leer datos dinámicos generados desde PostgreSQL en el backend
    let serie = [];
    const elScript = document.getElementById('datos-alertas');
    if (elScript) {
      try {
        const dataJson = JSON.parse(elScript.textContent);
        if (Array.isArray(dataJson.serie_ordenes)) {
          serie = dataJson.serie_ordenes;
        }
      } catch (err) {
        console.error('Error al procesar serie de alertas:', err);
      }
    }

    // Manejo de estado vacío sin mocks
    if (serie.length === 0) {
      if (chartAlertas) chartAlertas.destroy();
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.font = '14px "Source Sans 3", sans-serif';
      ctx.fillStyle = '#8d9ab5';
      ctx.textAlign = 'center';
      ctx.fillText('No hay órdenes registradas para evaluar alertas estadísticas.', canvas.width / 2, 100);
      return;
    }

    const labels = [];
    const dataOrds = [];
    const bgColors = [];

    serie.forEach((item) => {
      const anio = item.anio;
      const mesNum = item.mes;
      const esAnomalo = Boolean(item.es_anomalo);

      if (esAnomalo) {
        const nomMes = item.nombre_mes ? item.nombre_mes.substring(0, 3) : 'Mes';
        labels.push(nomMes + ' ' + String(anio).substring(2));
      } else if (mesNum === 1) {
        labels.push(String(anio));
      } else {
        labels.push('');
      }

      dataOrds.push(item.ordenes);
      bgColors.push(esAnomalo ? '#c2410c' : '#38476d');
    });

    const maxOrd = Math.max(...dataOrds, 500);
    const yMax = Math.ceil((maxOrd * 1.25) / 1000) * 1000;

    if (chartAlertas) chartAlertas.destroy();

    chartAlertas = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          data: dataOrds,
          backgroundColor: bgColors,
          borderRadius: 2,
          barPercentage: 0.85,
          categoryPercentage: 0.95,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#131b2d',
            callbacks: {
              label: (c) => `Órdenes: ${c.parsed.y.toLocaleString('es-CO')}`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#8d9ab5',
              font: { family: 'Source Sans 3', size: 12 },
              autoSkip: false,
            }
          },
          y: {
            min: 0,
            max: yMax,
            ticks: {
              stepSize: yMax > 6000 ? 2500 : (yMax > 2000 ? 1000 : 500),
              color: '#8d9ab5',
              font: { family: 'JetBrains Mono', size: 11 },
              callback: (v) => v === 0 ? '0' : (v.toLocaleString('es-CO'))
            },
            grid: { color: 'rgba(255,255,255,0.06)' }
          }
        }
      }
    });
  }

  /* ---------------- VISTA 4: Accesos por rol (Imagen 4) ---------------- */
  function initAccesosExacto() {
    initTopbarGlobal();
  }

  return {
    initTableroExacto,
    initExplorarExacto,
    initAlertasExacto,
    initAccesosExacto,
    toggleModoClase,
  };
})();
