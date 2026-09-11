/* Tableau de bord météo chambre — vanilla JS, sans dépendance externe. */

function getColor(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
}

function parseTs(ts) {
  return new Date(ts);
}

class LineChart {
  constructor(canvas, tooltipEl, unit) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.tooltipEl = tooltipEl;
    this.unit = unit;
    this.series = [];
    this._scalesCache = null;
    this._domainCache = null;

    window.addEventListener('resize', () => this.draw());
    canvas.addEventListener('mousemove', (e) => this._onHover(e));
    canvas.addEventListener('mouseleave', () => {
      this.tooltipEl.style.opacity = 0;
      this.draw();
    });
  }

  setSeries(series) {
    this.series = series.filter((s) => s.points.length > 0);
    this.draw();
  }

  _chromeColors() {
    return {
      grid: getColor('--grid'),
      axis: getColor('--axis'),
      textMuted: getColor('--text-muted'),
    };
  }

  _setupCanvasSize() {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(rect.width * dpr));
    this.canvas.height = Math.max(1, Math.round(rect.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.width = rect.width;
    this.height = rect.height;
  }

  _domain() {
    const allX = [];
    const allY = [];
    for (const s of this.series) {
      for (const p of s.points) {
        allX.push(p.x.getTime());
        allY.push(p.y);
      }
    }
    if (!allX.length) return null;
    const xMin = Math.min(...allX);
    const xMax = Math.max(...allX);
    let yMin = Math.min(...allY);
    let yMax = Math.max(...allY);
    if (yMin === yMax) {
      yMin -= 1;
      yMax += 1;
    }
    const pad = (yMax - yMin) * 0.15;
    return { xMin, xMax, yMin: yMin - pad, yMax: yMax + pad };
  }

  draw(hoverX = null) {
    if (!this.canvas.isConnected) return;
    this._setupCanvasSize();
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    if (!this.series.length) return;

    const domain = this._domain();
    if (!domain) return;
    const chrome = this._chromeColors();

    const marginLeft = 40;
    const marginRight = 8;
    const marginTop = 10;
    const marginBottom = 20;
    const plotW = Math.max(1, this.width - marginLeft - marginRight);
    const plotH = Math.max(1, this.height - marginTop - marginBottom);

    const xScale = (t) => marginLeft + ((t - domain.xMin) / (domain.xMax - domain.xMin || 1)) * plotW;
    const yScale = (v) => marginTop + plotH - ((v - domain.yMin) / (domain.yMax - domain.yMin || 1)) * plotH;

    ctx.font = '11px system-ui, -apple-system, sans-serif';
    ctx.strokeStyle = chrome.grid;
    ctx.lineWidth = 1;
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {
      const v = domain.yMin + (i / yTicks) * (domain.yMax - domain.yMin);
      const y = yScale(v);
      ctx.beginPath();
      ctx.moveTo(marginLeft, y);
      ctx.lineTo(this.width - marginRight, y);
      ctx.stroke();
      ctx.fillStyle = chrome.textMuted;
      ctx.fillText(v.toFixed(1), 2, y + 3);
    }

    const xTicks = Math.min(5, Math.max(2, Math.floor(plotW / 110)));
    for (let i = 0; i <= xTicks; i++) {
      const t = domain.xMin + (i / xTicks) * (domain.xMax - domain.xMin);
      const x = xScale(t);
      const label = new Date(t).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit' });
      ctx.fillStyle = chrome.textMuted;
      ctx.fillText(label, Math.min(Math.max(x - 22, marginLeft), this.width - marginRight - 44), this.height - 5);
    }

    const now = Date.now();
    if (now >= domain.xMin && now <= domain.xMax) {
      const x = xScale(now);
      ctx.save();
      ctx.strokeStyle = chrome.axis;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, marginTop);
      ctx.lineTo(x, marginTop + plotH);
      ctx.stroke();
      ctx.restore();
    }

    for (const s of this.series) {
      ctx.save();
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      if (s.dashed) ctx.setLineDash([5, 4]);
      ctx.beginPath();
      s.points.forEach((p, i) => {
        const x = xScale(p.x.getTime());
        const y = yScale(p.y);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.restore();
    }

    if (hoverX !== null) {
      ctx.save();
      ctx.strokeStyle = chrome.axis;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(hoverX, marginTop);
      ctx.lineTo(hoverX, marginTop + plotH);
      ctx.stroke();
      ctx.restore();
    }

    this._domainCache = domain;
    this._scalesCache = { marginLeft, plotW };
  }

  _nearestPoint(series, t) {
    let closest = series.points[0];
    let closestDiff = Infinity;
    for (const p of series.points) {
      const diff = Math.abs(p.x.getTime() - t);
      if (diff < closestDiff) {
        closestDiff = diff;
        closest = p;
      }
    }
    return closest;
  }

  _onHover(e) {
    if (!this.series.length || !this._scalesCache) return;
    const rect = this.canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const { marginLeft, plotW } = this._scalesCache;
    const domain = this._domainCache;

    if (mouseX < marginLeft || mouseX > marginLeft + plotW) {
      this.tooltipEl.style.opacity = 0;
      this.draw();
      return;
    }

    const t = domain.xMin + ((mouseX - marginLeft) / plotW) * (domain.xMax - domain.xMin);
    this.draw(mouseX);

    let refTime = null;
    const rows = this.series.map((s) => {
      const p = this._nearestPoint(s, t);
      if (refTime === null) refTime = p.x;
      return { label: s.label, color: s.color, value: p.y };
    });

    const timeLabel = refTime.toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
    let html = `<div class="t-time">${timeLabel}</div>`;
    for (const r of rows) {
      html += `<div class="t-row"><span class="legend-swatch" style="background:${r.color}"></span>${r.label} : <strong>${r.value.toFixed(1)}${this.unit}</strong></div>`;
    }
    this.tooltipEl.innerHTML = html;
    this.tooltipEl.style.opacity = 1;

    let left = mouseX + 12;
    if (left + 170 > this.width) left = mouseX - 182;
    this.tooltipEl.style.left = `${Math.max(0, left)}px`;
    this.tooltipEl.style.top = '6px';
  }
}

function buildLegend(el, items) {
  el.innerHTML = items
    .map(
      (it) => `<span class="legend-item" style="color:${it.color}">
        <span class="legend-swatch${it.dashed ? ' dashed' : ''}" style="background:${it.dashed ? 'none' : it.color}"></span>
        <span style="color:var(--text-secondary)">${it.label}</span>
      </span>`
    )
    .join('');
}

// Relie une série "observée" à sa continuation "prédite" en dupliquant le
// dernier point observé en tête de la série prédite, pour que le trait en
// pointillés reparte visuellement du dernier point plein.
function joinForContinuity(observedPoints, predictedPoints) {
  if (!observedPoints.length || !predictedPoints.length) return predictedPoints;
  const last = observedPoints[observedPoints.length - 1];
  return [last, ...predictedPoints];
}

// Les deux pages (indicateurs / prévisions) partagent ce script : on ne
// construit les graphiques que si leurs <canvas> sont présents sur la page.
const hasCharts = !!document.getElementById('chart-temp');
const hasTiles = !!document.getElementById('tiles');

const charts = hasCharts ? {
  temperature: new LineChart(document.getElementById('chart-temp'), document.getElementById('tooltip-temp'), ' °C'),
  humidity: new LineChart(document.getElementById('chart-humidity'), document.getElementById('tooltip-humidity'), ' %'),
  pressure: new LineChart(document.getElementById('chart-pressure'), document.getElementById('tooltip-pressure'), ' hPa'),
} : {};

function renderAll(data) {
  const colorRoom = getColor('--series-room');
  const colorOutdoor = getColor('--series-outdoor');

  const roomPoints = (v) => data.history.room.map((r) => ({ x: parseTs(r.ts), y: r[v] })).filter((p) => p.y !== null);
  const weatherPoints = (v) => data.history.weather.map((r) => ({ x: parseTs(r.ts), y: r[v] })).filter((p) => p.y !== null);
  const forecastPoints = (v) => data.forecast.map((r) => ({ x: parseTs(r.target_ts), y: r[v] })).filter((p) => p.y !== null);
  const predPoints = (v) => data.predictions.map((r) => ({ x: parseTs(r.target_ts), y: r[`predicted_${v}`] })).filter((p) => p.y !== null);

  const configs = [
    { key: 'temperature', chart: charts.temperature, legend: 'legend-temp' },
    { key: 'humidity', chart: charts.humidity, legend: 'legend-humidity' },
    { key: 'pressure', chart: charts.pressure, legend: 'legend-pressure' },
  ];

  for (const cfg of configs) {
    const room = roomPoints(cfg.key);
    const weather = weatherPoints(cfg.key);
    const roomPred = joinForContinuity(room, predPoints(cfg.key));
    const weatherFcst = joinForContinuity(weather, forecastPoints(cfg.key));

    cfg.chart.setSeries([
      { label: 'Chambre (mesuré)', color: colorRoom, dashed: false, points: room },
      { label: 'Chambre (prédit)', color: colorRoom, dashed: true, points: roomPred },
      { label: 'Extérieur (observé)', color: colorOutdoor, dashed: false, points: weather },
      { label: 'Extérieur (prévu)', color: colorOutdoor, dashed: true, points: weatherFcst },
    ]);

    buildLegend(document.getElementById(cfg.legend), [
      { label: 'Chambre — mesuré', color: colorRoom, dashed: false },
      { label: 'Chambre — prédit', color: colorRoom, dashed: true },
      { label: 'Extérieur — observé', color: colorOutdoor, dashed: false },
      { label: 'Extérieur — prévu', color: colorOutdoor, dashed: true },
    ]);
  }
}

function renderTiles(latest) {
  const tiles = document.getElementById('tiles');
  const lastUpdate = latest ? new Date(latest.ts).toLocaleTimeString('fr-FR') : '';

  const tileHtml = (icon, color, colorDeep, label, value, unit, sub) => `
    <div class="tile" style="--tile-color:${color}; --tile-color-deep:${colorDeep}">
      <div class="tile-icon">${icon}</div>
      <div class="label">${label}</div>
      <div class="value">${value !== null && value !== undefined ? value.toFixed(1) + unit : '—'}</div>
      ${sub ? `<div class="sub">${sub}</div>` : ''}
    </div>`;

  const colorRoom = getColor('--series-room');
  const colorHumidity = getColor('--series-humidity');
  const colorOutdoor = getColor('--series-outdoor');

  tiles.innerHTML = [
    tileHtml('🌡️', colorRoom, colorRoom, 'Température relevée', latest?.temperature, ' °C', lastUpdate ? `Relevé à ${lastUpdate}` : ''),
    tileHtml('💧', colorHumidity, colorHumidity, 'Humidité relevée', latest?.humidity, ' %', lastUpdate ? `Relevé à ${lastUpdate}` : ''),
    tileHtml('🌀', colorOutdoor, colorOutdoor, 'Pression relevée', latest?.pressure, ' hPa', lastUpdate ? `Relevé à ${lastUpdate}` : ''),
  ].join('');
}

function renderMeta(metadata) {
  const el = document.getElementById('model-meta');
  if (!metadata) {
    el.innerHTML = '<em>Aucun modèle entraîné pour le moment — en attente de suffisamment de données.</em>';
    return;
  }
  const rows = Object.entries(metadata.metrics || {})
    .map(
      ([variable, m]) => `<tr>
        <td>${variable}</td>
        <td>${m.baseline.mae.toFixed(3)}</td>
        <td>${m.gbm.mae.toFixed(3)}</td>
      </tr>`
    )
    .join('');
  el.innerHTML = `
    Modèle version <strong>${metadata.version}</strong>, entraîné le
    ${new Date(metadata.trained_at).toLocaleString('fr-FR')} sur ${metadata.n_rows_total} lignes.
    <table>
      <thead><tr><th>Variable</th><th>MAE baseline</th><th>MAE gradient boosting</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function fetchJson(url, fallback) {
  try {
    const res = await fetch(url);
    if (!res.ok) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

async function refresh() {
  const statusEl = document.getElementById('status');
  try {
    const latest = await fetchJson('/api/latest', null);

    if (!latest) {
      statusEl.textContent = "En attente de la première mesure du capteur…";
      statusEl.classList.add('error');
      return;
    }

    statusEl.textContent = `Mis à jour à ${new Date().toLocaleTimeString('fr-FR')}`;
    statusEl.classList.remove('error');

    if (hasTiles) renderTiles(latest);

    if (hasCharts) {
      const [history, forecast, predictions, metadata] = await Promise.all([
        fetchJson('/api/history?hours=72', { room: [], weather: [] }),
        fetchJson('/api/forecast', []),
        fetchJson('/api/predictions', []),
        fetchJson('/api/metadata', null),
      ]);
      renderAll({ history, forecast, predictions });
      renderMeta(metadata);
    }
  } catch (err) {
    statusEl.textContent = 'Erreur de connexion à l\'API.';
    statusEl.classList.add('error');
    console.error(err);
  }
}

refresh();
