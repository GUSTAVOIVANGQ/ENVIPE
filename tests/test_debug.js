// Usamos DASHBOARD_DATA cargado desde resultados/dashboard_data.js
const DATA = typeof DASHBOARD_DATA !== 'undefined' ? DASHBOARD_DATA : null;

if (!DATA) {
  document.body.innerHTML = `
    <div style="padding:40px; color:white; font-family: sans-serif;">
      <h1>Error de carga de datos</h1>
      <p>No se pudo cargar <code>resultados/dashboard_data.js</code>.</p>
      <p>Asegúrate de haber ejecutado <code>python main.py</code> primero para que se generen los datos de todos los años.</p>
    </div>`;
  throw new Error("Datos no encontrados");
}

let CURRENT_YEAR = DATA.ultimo_año;

// ─── COLOR MAP ────────────────────────────────────────────────────────────
const COLORS = {
  "Presencial (cara a cara)":        "#64748b",
  "No aplica (delito de hogar)":     "#94a3b8",
  "Teléfono (sin detalle)":          "#d97706",
  "Internet / redes sociales":       "#059669",
  "Correo / mensajería física":      "#7c3aed",
  "Teléfono — llamada de voz":       "#ea580c",
  "Teléfono — SMS / WhatsApp":       "#eab308",
  "Otro medio":                      "#cbd5e1",
  "Sin información":                 "#cbd5e1",
  "Presencial + seguimiento digital":"#0284c7",
};

function getColor(label) { return COLORS[label] || "#3b82f6"; }

function fmt(n) {
  if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(0) + 'K';
  return n.toLocaleString('es-MX');
}
function fmtFull(n) { return Number(n).toLocaleString('es-MX'); }

Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = '#252b3a';
Chart.defaults.font.family = "'IBM Plex Sans', sans-serif";

let chartMedioInstance = null;
let chartDelitoInstance = null;
let chartExtorsionInstance = null;
let chartTendenciaInstance = null;

// ─── AGGREGATION HELPER ───────────────────────────────────────────────────
function groupBySum(array, key1, key2 = null) {
  const result = {};
  array.forEach(item => {
    const k = key2 ? item[key1] + '|||' + item[key2] : item[key1];
    if (!result[k]) {
      result[k] = { ...item, estimacion: 0 };
    }
    result[k].estimacion += item.estimacion;
  });
  return Object.values(result).sort((a,b) => b.estimacion - a.estimacion);
}

// ─── RENDER FUNCTIONS ─────────────────────────────────────────────────────
function updateDashboard() {
  const anioInicio = DATA.años[0];
  const anioFin = DATA.años[DATA.años.length - 1];
  const rangoTexto = `Acumulado ${anioInicio}–${anioFin}`;

  document.getElementById('rango-años').textContent = rangoTexto;
  document.getElementById('lbl-año1').textContent = rangoTexto;

  // Update KPIs
  const totalHistorico = DATA.serie_anual.reduce((acc, s) => acc + s.total, 0);
  const digitalHistorico = DATA.serie_anual.reduce((acc, s) => acc + s.digital, 0);
  const pctDigital = totalHistorico > 0 ? ((digitalHistorico / totalHistorico) * 100).toFixed(1) : 0;

  document.getElementById('kpi-total').textContent = fmt(totalHistorico);
  document.getElementById('kpi-digital').textContent = fmt(digitalHistorico);
  document.getElementById('kpi-digital-sub').textContent = `de ${fmtFull(totalHistorico)} totales`;
  document.getElementById('kpi-pct').textContent = pctDigital + '%';

  const delitosTotales = groupBySum(DATA.delito_por_año, 'delito');
  if (delitosTotales.length > 0) {
    const top = delitosTotales[0];
    document.getElementById('kpi-top').textContent = top.delito;
    document.getElementById('kpi-top-sub').textContent = fmt(top.estimacion) + ' casos estimados';
  } else {
    document.getElementById('kpi-top').textContent = "—";
    document.getElementById('kpi-top-sub').textContent = "Sin datos";
  }

  // Update Medio Chart
  let medios = groupBySum(DATA.medio_por_año, 'medio_etiqueta');
  medios = medios.filter(d => d.estimacion > 50000).slice(0, 10);
  
  if (chartMedioInstance) chartMedioInstance.destroy();
  chartMedioInstance = new Chart(document.getElementById('chartMedio'), {
    type: 'bar',
    data: {
      labels: medios.map(d => d.medio_etiqueta),
      datasets: [{
        data: medios.map(d => d.estimacion),
        backgroundColor: medios.map(d => getColor(d.medio_etiqueta)),
        borderRadius: 4
      }]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ' ' + fmtFull(c.raw) } } },
      scales: { x: { ticks: { callback: v => fmt(v), font: { family: "'IBM Plex Mono', monospace", size: 10 } }, grid: { color: '#e2e8f0' } }, y: { grid: { display: false }, ticks: { font: { size: 11 } } } }
    }
  });

  // Update Delito Chart
  if (chartDelitoInstance) chartDelitoInstance.destroy();
  const cMap = { "Fraude bancario": "#f59e0b", "Fraude al consumidor": "#fb923c", "Extorsión": "#10b981" };
  chartDelitoInstance = new Chart(document.getElementById('chartDelito'), {
    type: 'bar',
    data: {
      labels: delitosTotales.map(d => d.delito),
      datasets: [{
        data: delitosTotales.map(d => d.estimacion),
        backgroundColor: delitosTotales.map(d => cMap[d.delito] || "#3b82f6"),
        borderRadius: 3
      }]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ' ' + fmtFull(c.raw) } } },
      scales: { x: { ticks: { callback: v => fmt(v), font: { family: "'IBM Plex Mono', monospace", size: 10 } }, grid: { color: '#e2e8f0' } }, y: { grid: { display: false }, ticks: { font: { size: 10 } } } }
    }
  });

  // Update Extorsion Chart
  const ext = groupBySum(DATA.extorsion_por_año, 'medio_etiqueta');
  if (chartExtorsionInstance) chartExtorsionInstance.destroy();
  
  chartExtorsionInstance = new Chart(document.getElementById('chartExtorsion'), {
    type: 'doughnut',
    data: {
      labels: ext.map(d => d.medio_etiqueta),
      datasets: [{
        data: ext.map(d => d.estimacion),
        backgroundColor: ext.map(d => getColor(d.medio_etiqueta)),
        borderWidth: 3, borderColor: '#ffffff'
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '65%',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => {
        const total = c.dataset.data.reduce((a,b) => a+b, 0);
        const pct = (c.raw / total * 100).toFixed(1);
        return ` ${fmtFull(c.raw)} (${pct}%)`;
      } } } }
    }
  });

  const leg = document.getElementById('legend-ext');
  leg.innerHTML = '';
  const totalExt = ext.reduce((a,b) => a + b.estimacion, 0);
  ext.forEach(d => {
    const pct = totalExt > 0 ? (d.estimacion / totalExt * 100).toFixed(1) : 0;
    leg.innerHTML += `
      <div class="legend-item">
        <div class="legend-dot" style="background:${getColor(d.medio_etiqueta)}"></div>
        <span>${d.medio_etiqueta} <strong style="color:var(--text)">${pct}%</strong></span>
      </div>`;
  });

  // Update Table
  renderTable(currentMedioFilter);
}

// ─── TABLE: BREAKDOWN ─────────────────────────────────────────────────────
let currentMedioFilter = '';
function badgeMedio(m) {
  if (m.includes('Internet'))   return `<span class="badge internet">${m}</span>`;
  if (m.includes('Teléfono'))   return `<span class="badge telefono">${m}</span>`;
  if (m.includes('Presencial')) return `<span class="badge presencial">${m}</span>`;
  if (m.includes('No aplica'))  return `<span class="badge otro">No aplica</span>`;
  return `<span class="badge otro">${m}</span>`;
}

function renderTable(filter = '') {
  const tbody = document.getElementById('tbody-breakdown');
  let rows = groupBySum(DATA.breakdown_por_año, 'delito', 'medio_etiqueta');
  const totalGeneral = rows.reduce((a,b) => a + b.estimacion, 0);

  if (filter) {
    if (filter === 'Presencial (cara a cara)') {
      rows = rows.filter(r => r.medio_etiqueta.includes('Presencial'));
    } else if (filter === 'Teléfono (sin detalle)') {
      rows = rows.filter(r => r.medio_etiqueta.includes('Teléfono'));
    } else if (filter === 'Internet / redes sociales') {
      rows = rows.filter(r => r.medio_etiqueta.includes('Internet'));
    }
  }
  
  rows.sort((a, b) => b.estimacion - a.estimacion);

  const maxVal = Math.max(...rows.map(r => r.estimacion), 1);

  tbody.innerHTML = rows.map(r => {
    const pct = totalGeneral > 0 ? (r.estimacion / totalGeneral * 100).toFixed(1) : 0;
    const barW = Math.round(r.estimacion / maxVal * 120);
    return `<tr>
      <td>${r.delito}</td>
      <td>${badgeMedio(r.medio_etiqueta)}</td>
      <td class="num">${fmtFull(r.estimacion)}</td>
      <td>
        <div class="bar-inline">
          <div class="bar-fill" style="width:${barW}px;background:${getColor(r.medio_etiqueta)}"></div>
          <span class="num" style="color:var(--muted);font-size:11px">${pct}%</span>
        </div>
      </td>
    </tr>`;
  }).join('');
}

// Filter buttons
document.getElementById('filter-medio').addEventListener('click', e => {
  const btn = e.target.closest('.filter-btn');
  if (!btn) return;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentMedioFilter = btn.dataset.medio;
  renderTable(currentMedioFilter);
});

// ─── INIT ─────────────────────────────────────────────────────────────────
renderTendencia();
updateDashboard();
