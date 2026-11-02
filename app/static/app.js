/* Tableau de bord météo chambre — vanilla JS, sans dépendance externe. */

function getColor(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
}

function tileHtml(icon, color, label, value, unit, sub) {
  return `
    <div class="tile" style="--tile-color:${color}; --tile-color-deep:${color}">
      <div class="tile-icon">${icon}</div>
      <div class="label">${label}</div>
      <div class="value">${value !== null && value !== undefined ? value.toFixed(1) + unit : '—'}</div>
      ${sub ? `<div class="sub">${sub}</div>` : ''}
    </div>`;
}

function renderTiles(elId, data, suffix, verb) {
  const el = document.getElementById(elId);
  const when = data ? new Date(data.ts).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '';
  const sub = when ? `${verb} à ${when}` : '';

  const colorRoom = getColor('--series-room');
  const colorHumidity = getColor('--series-humidity');
  const colorOutdoor = getColor('--series-outdoor');

  el.innerHTML = [
    tileHtml('🌡️', colorRoom, `Température${suffix}`, data?.temperature, ' °C', sub),
    tileHtml('💧', colorHumidity, `Humidité${suffix}`, data?.humidity, ' %', sub),
    tileHtml('🌀', colorOutdoor, `Pression${suffix}`, data?.pressure, ' hPa', sub),
  ].join('');
}

function renderWindowAdvice(advice) {
  const el = document.getElementById('window-advice');
  if (!el) return;

  if (!advice || !advice.available) {
    el.classList.remove('close-now', 'keep-open');
    el.innerHTML = `<div class="advice-icon">🪟</div><div class="advice-text">${advice ? advice.reason : "Conseil fenêtres indisponible."}</div>`;
    return;
  }

  el.classList.toggle('close-now', advice.should_close === true);
  el.classList.toggle('keep-open', advice.should_close === false);

  if (advice.cold_outside) {
    el.classList.remove('close-now', 'keep-open');
    el.innerHTML = `
      <div class="advice-icon">🥶</div>
      <div class="advice-text">
        <div class="advice-message">${advice.message}</div>
        <div class="advice-sub">Intérieur actuel : ${advice.current_indoor_temperature.toFixed(1)} °C</div>
      </div>`;
    return;
  }

  const sub = `Intérieur actuel : ${advice.current_indoor_temperature.toFixed(1)} °C`;
  el.innerHTML = `
    <div class="advice-icon">${advice.should_close ? '🪟' : '🌬️'}</div>
    <div class="advice-text">
      <div class="advice-message">${advice.message}</div>
      <div class="advice-sub">${sub}</div>
    </div>`;
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

    renderTiles('tiles', latest, ' relevée', 'Relevé');
    fetchJson('/api/outdoor', null).then((o) => renderTiles('tiles-outdoor', o, ' extérieure', 'Donnée'));
    fetchJson('/api/window-advice', null).then(renderWindowAdvice);
  } catch (err) {
    statusEl.textContent = 'Erreur de connexion à l\'API.';
    statusEl.classList.add('error');
    console.error(err);
  }
}

refresh();
