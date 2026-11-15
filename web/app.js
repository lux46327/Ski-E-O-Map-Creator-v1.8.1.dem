'use strict';
/* Ski-E-O Map Creator -- window logic. Talks to Python through window.pywebview.api (see skieo_creator/api.py);
   progress of background jobs arrives through window.app.onEvent(kind, payload). */

const $ = (id) => document.getElementById(id);
const FT = 3.28084;
const Q = new URLSearchParams(location.search);
const S = {
  token: Q.get('t') || '',
  // map tiles come from their own local port, so slow / failing tile downloads never hold up the app's requests
  tiles: /^\d+$/.test(Q.get('tp') || '') ? `http://127.0.0.1:${Q.get('tp')}` : '',
  units: 'ft', layer: 'topo', game: null, biomes: [], limits: { min_km: 3, max_km: 20 },
  sq: { lat: 45.92, lon: 6.88, km: 8, rot: 0 }, preview: null, osm: null, job: null, maps: [], overlayOn: true,
  touched: { biome: false, treeline: false, snow: false, name: false }, suggestName: '',
  dragging: false, busyPoll: null,
};

async function call(name, ...args) {
  try {
    const r = await window.pywebview.api[name](...args);
    return r || { ok: false, error: 'No answer from the app.' };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

/* ------------------------------------------------------------ formatting */

function fmtElev(m) {
  if (m == null || isNaN(m)) return '-';
  return S.units === 'ft' ? Math.round(m * FT).toLocaleString('en-US') + ' ft' : Math.round(m).toLocaleString('en-US') + ' m';
}
function fmtSize(km) {
  const mi = km * 0.621371;
  return S.units === 'ft' ? `${km.toFixed(1)} km (${mi.toFixed(1)} mi)` : `${km.toFixed(1)} km`;
}
function toUnits(m) { return S.units === 'ft' ? m * FT : m; }
function fromUnits(v) { return S.units === 'ft' ? v / FT : v; }
function unitName() { return S.units === 'ft' ? 'ft' : 'm'; }
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ------------------------------------------------------------ toast / modal */

let toastTimer = null;
function toast(msg, bad = false, ms = 4200) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast' + (bad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), ms);
}
function confirmBox(title, text, yes = 'OK', danger = true) {
  return new Promise((resolve) => {
    $('modalTitle').textContent = title;
    $('modalText').textContent = text;
    $('modalYes').textContent = yes;
    $('modalYes').className = 'gbtn ' + (danger ? 'crimson' : 'green');
    $('modalNo').classList.toggle('hidden', yes === null);
    $('modal').classList.remove('hidden');
    const done = (v) => { $('modal').classList.add('hidden'); $('modalYes').onclick = $('modalNo').onclick = null; resolve(v); };
    $('modalYes').onclick = () => done(true);
    $('modalNo').onclick = () => done(false);
  });
}
function errorBox(text) {
  $('modalNo').textContent = 'Copy diagnostics';
  return confirmBox('Something went wrong', text, 'OK', false).then((ok) => {
    $('modalNo').textContent = 'Cancel';
    if (!ok) copyDiagnostics();
  });
}

/* ------------------------------------------------------------ map + selection square */

const map = L.map('map', { zoomControl: true, worldCopyJump: true, minZoom: 3, maxZoom: 17, zoomSnap: 0.5 });
map.zoomControl.setPosition('topleft');
L.control.scale({ position: 'bottomleft', imperial: true, metric: true, maxWidth: 160 }).addTo(map);
const layers = {};
function tileLayer(id, maxNative) {
  return L.tileLayer(`${S.tiles}/tile/${id}/{z}/{x}/{y}.png?t=${encodeURIComponent(S.token)}`,
    { maxZoom: 18, maxNativeZoom: maxNative, keepBuffer: 3, updateWhenIdle: false });
}
function setLayer(id) {
  S.layer = layers[id] ? id : 'topo';
  for (const [k, l] of Object.entries(layers)) { if (k !== S.layer && map.hasLayer(l)) map.removeLayer(l); }
  if (!map.hasLayer(layers[S.layer])) layers[S.layer].addTo(map);
  document.querySelectorAll('[data-layer]').forEach((b) => b.classList.toggle('on', b.dataset.layer === S.layer));
}

function mPerDeg(lat) {
  const p = lat * Math.PI / 180;
  return { lat: 111132.954 - 559.822 * Math.cos(2 * p) + 1.175 * Math.cos(4 * p),
           lon: 111412.84 * Math.cos(p) - 93.5 * Math.cos(3 * p) };
}
/* The square can be turned about its centre: rot = degrees clockwise, the compass bearing its top edge points to (0 = north
   is up). Corners are returned top-left, top-right, bottom-right, bottom-left of the square itself. */
function corners(lat, lon, km, rot = 0) {
  const m = mPerDeg(lat), h = km * 500, t = rot * Math.PI / 180, c = Math.cos(t), s = Math.sin(t);
  return [[-h, h], [h, h], [h, -h], [-h, -h]].map(([x, y]) => [lat + (-x * s + y * c) / m.lat, lon + (x * c + y * s) / m.lon]);
}
function squareBounds(lat, lon, km, rot = 0) { return L.latLngBounds(corners(lat, lon, km, rot)); }
function toWindow(lat, lon) {           // metres right / up of the square's centre, in the square's own (turned) frame
  const p = toLocal(lat, lon), t = S.sq.rot * Math.PI / 180, c = Math.cos(t), s = Math.sin(t);
  return { x: p.x * c - p.y * s, y: p.x * s + p.y * c };
}
const normRot = (r) => ((Math.round(r) % 360) + 360) % 360;        // 0..359 degrees clockwise
const rotDiff = (a, b) => Math.abs((((a - b) % 360) + 540) % 360 - 180);
function toLocal(lat, lon) {            // metres east / north of the square's centre
  const m = mPerDeg(S.sq.lat);
  return { x: (lon - S.sq.lon) * m.lon, y: (lat - S.sq.lat) * m.lat };
}
function fromLocal(x, y) {
  const m = mPerDeg(S.sq.lat);
  return L.latLng(S.sq.lat + y / m.lat, S.sq.lon + x / m.lon);
}

const sqStyle = { color: '#b3263d', weight: 3, fillColor: '#ffffff', fillOpacity: 0.12, className: 'sq' };
const square = L.polygon(corners(S.sq.lat, S.sq.lon, S.sq.km), sqStyle).addTo(map);
const sqLabel = L.tooltip({ permanent: true, direction: 'top', className: 'sq-label', offset: [0, -2] });
const handle = L.marker([S.sq.lat, S.sq.lon], {
  draggable: true, zIndexOffset: 500, keyboard: false, title: 'Drag to move the area',
  icon: L.divIcon({ className: '', iconSize: [30, 30], iconAnchor: [15, 15],
    html: '<div class="move-handle"><svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/></svg></div>' }),
}).addTo(map);
/* A small "N" on the square: the game's north (the top of the square), which turns with it. Only a visual hint. */
const northMark = L.marker([S.sq.lat, S.sq.lon], {
  interactive: false, keyboard: false, zIndexOffset: 400,
  icon: L.divIcon({ className: '', iconSize: [20, 20], iconAnchor: [10, 10],
    html: '<div class="north-mark"><svg viewBox="0 0 24 24"><path d="M12 2l5 11h-4v9h-2v-9H7z"/></svg><b>N</b></div>' }),
}).addTo(map);
function drawNorth() {
  // the game's north: just outside the middle of the square's top edge (beyond the turn handle), turning with the square;
  // real north is ignored
  const { lat, lon, km, rot } = S.sq, t = rot * Math.PI / 180, m = mPerDeg(lat), r = km * 500;
  northMark.setLatLng([lat + r * Math.cos(t) / m.lat, lon + r * Math.sin(t) / m.lon]);
  const el = northMark.getElement();
  if (el && el.firstChild) el.firstChild.style.transform = `rotate(${rot}deg) translateY(-34px)`;   // 34 px outwards, whatever the zoom
}
/* The turn handle sits in the middle of the square's top edge: drag it round the centre. Shift snaps to 15 degrees. */
const rotHandle = L.marker([S.sq.lat, S.sq.lon], {
  draggable: true, zIndexOffset: 600, keyboard: false, title: 'Drag to turn the area (Shift: steps of 15°). Double-click the Rotation slider to turn it back north.',
  icon: L.divIcon({ className: '', iconSize: [26, 26], iconAnchor: [13, 13],
    html: '<div class="rot-handle"><svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5"/></svg></div>' }),
}).addTo(map);
rotHandle.on('dragstart', () => { S.rotating = true; });
rotHandle.on('drag', (e) => {
  if (busy()) { S.rotating = false; drawSquare(); return; }          // locked while a job runs
  const ll = rotHandle.getLatLng(), p = toLocal(ll.lat, ll.lng);
  let r = Math.atan2(p.x, p.y) * 180 / Math.PI;                       // bearing of the handle from the centre
  if (e.originalEvent && e.originalEvent.shiftKey) r = Math.round(r / 15) * 15;
  r = normRot(r);
  S.sq.rot = (r <= 2 || r >= 358) ? 0 : r;                                // a little magnet at north
  $('rot').value = S.sq.rot;
  drawSquare();
});
rotHandle.on('dragend', () => { S.rotating = false; drawSquare(); if (!busy()) areaChanged(); });
/* a map overlay turned about its centre (Leaflet's ImageOverlay is axis-aligned): the picture of the terrain loaded for a
   turned square. Its bounds are the square's own, un-turned; the turn is added to the transform Leaflet sets. */
const RotatedOverlay = L.ImageOverlay.extend({
  _reset() { L.ImageOverlay.prototype._reset.call(this); this._turn(); },
  _animateZoom(e) { L.ImageOverlay.prototype._animateZoom.call(this, e); this._turn(); },
  _turn() {
    if (!this._image || !this.options.rot) return;
    this._image.style.transformOrigin = '50% 50%';
    this._image.style.transform += ` rotate(${this.options.rot}deg)`;
  },
});
/* ------------------------------------------------------------ access keys (national elevation services)
   A job that stops with `needs` = a service id (skieo_creator/credentials.py) opens this window: how to get the key, the
   licence notice, the fields. The key only lives in the app until it is closed. */

function keyLink(name, label) {
  return `<a href="#" class="link" data-link="${esc(name)}">${esc(label || name)}</a>`;
}

async function askKey(job) {
  const r = await call('key_info', job.needs);
  if (!r.ok) return errorBox(r.error);
  $('keyTitle').textContent = `Access key for ${r.country}`;
  $('keyIntro').textContent = `${r.dataset} from ${r.name} is free, but the service asks for a personal access key. `
    + 'Without it this area uses the free worldwide terrain data, which is much less detailed.';
  $('keySteps').innerHTML = r.steps.map((s) => `<li>${esc(s.text)}${s.link ? ' ' + keyLink(s.link, s.label) : ''}</li>`).join('');
  $('keyLicense').innerHTML = `<b>Licence and terms.</b> ${esc(r.license.text)} ${keyLink(r.license.link, r.license.label)}`;
  $('keyFields').innerHTML = r.fields.map((f) => `<label class="field">${esc(f.label)}
    <input data-field="${esc(f.id)}" type="${f.secret ? 'password' : 'text'}" placeholder="${esc(f.placeholder)}"
      autocomplete="off" spellcheck="false"></label>`).join('');
  $('keyError').classList.add('hidden');
  const box = $('keyModal');
  box.querySelectorAll('[data-link]').forEach((a) => {
    a.onclick = (e) => { e.preventDefault(); call('link', a.dataset.link); };
  });
  const inputs = [...box.querySelectorAll('input[data-field]')];
  box.classList.remove('hidden');
  inputs[0] && inputs[0].focus();
  const close = () => { box.classList.add('hidden'); $('keyUse').onclick = $('keySkip').onclick = $('keyCancel').onclick = null; };
  const retry = () => { if (job.kind === 'preview') $('loadBtn').onclick(); };
  $('keyCancel').onclick = close;
  $('keySkip').onclick = async () => {
    const k = await call('key_skip', job.needs);
    close();
    if (!k.ok) return errorBox(k.error);
    toast(`Using the free worldwide terrain data for ${r.country}`);
    retry();
  };
  $('keyUse').onclick = async () => {
    const vals = {};
    inputs.forEach((i) => { vals[i.dataset.field] = i.value.trim(); });
    $('keyUse').disabled = true;
    $('keyUse').textContent = 'Checking...';
    const k = await call('key_set', job.needs, vals);
    $('keyUse').disabled = false;
    $('keyUse').textContent = 'Use key';
    if (!k.ok) {
      $('keyError').textContent = k.error;
      $('keyError').classList.remove('hidden');
      return;
    }
    close();
    toast(k.note || 'Key saved for this session');
    retry();
  };
  inputs.forEach((i) => { i.onkeydown = (e) => { if (e.key === 'Enter') $('keyUse').click(); }; });
}

let overlay = null, osmLayer = null;

function drawSquare() {
  const c = corners(S.sq.lat, S.sq.lon, S.sq.km, S.sq.rot);
  square.setLatLngs(c);
  handle.setLatLng([S.sq.lat, S.sq.lon]);
  if (!S.rotating) rotHandle.setLatLng([(c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2]);   // middle of the top edge
  sqLabel.setLatLng([Math.max(...c.map((p) => p[0])), S.sq.lon])
    .setContent(`${S.sq.km.toFixed(1)} × ${S.sq.km.toFixed(1)} km`);
  if (!map.hasLayer(sqLabel)) sqLabel.addTo(map);
  showNum('size');
  showNum('rot');
  drawNorth();
  $('areaMeta').textContent = `${S.sq.lat.toFixed(5)}, ${S.sq.lon.toFixed(5)}`;
  fitTrees();
}

// a new map size selects the game's own forest density for it (also the most); moving the square keeps a lowered count
function fitTrees() {
  const t = $('trees');
  if (!S.limits.trees_per_km2) return;
  t.max = Math.round(S.limits.trees_per_km2 * S.sq.km * S.sq.km / 1000) * 1000;
  if (S.treesKm !== S.sq.km) t.value = t.max;
  S.treesKm = S.sq.km;
  showNum('trees');
}

function moveSquare(lat, lon) {
  S.sq.lat = Math.max(-84, Math.min(84, lat));
  S.sq.lon = ((lon + 540) % 360) - 180;
  drawSquare();
  areaChanged();
}

let viewTimer = null;
function areaChanged() {
  const p = S.preview;
  const same = p && Math.abs(p.lat - S.sq.lat) < 1e-7 && Math.abs(p.lon - S.sq.lon) < 1e-7 && Math.abs(p.size_km - S.sq.km) < 1e-9 && rotDiff(p.rot || 0, S.sq.rot) < 0.05;
  if (p && !same) {
    S.preview = null;
    if (overlay) { map.removeLayer(overlay); overlay = null; }
    clearOsm();
    $('osm').checked = false;                    // switched off too: nothing is downloaded until the player asks again
    $('realTrees').checked = false; clearTrees();
    $('overlayBtn').disabled = true;
    lockTerrain(true);
    toast('The area changed. Press "Load terrain" to load it, and switch on the real trails and lifts again if you want them.');
  }
  updateButtons();
  clearTimeout(viewTimer);
  viewTimer = setTimeout(() => call('set_setting', 'view', { lat: S.sq.lat, lon: S.sq.lon, km: S.sq.km, rot: S.sq.rot, zoom: map.getZoom() }), 800);
}

handle.on('drag', () => { if (busy()) return drawSquare(); const ll = handle.getLatLng(); S.sq.lat = ll.lat; S.sq.lon = ll.lng; drawSquare(); });
handle.on('dragend', () => { if (busy()) return drawSquare(); moveSquare(S.sq.lat, S.sq.lon); });
let dragFrom = null;
square.on('mousedown', (e) => {
  if (busy()) return;
  S.dragging = true;
  dragFrom = { ll: e.latlng, lat: S.sq.lat, lon: S.sq.lon };
  map.dragging.disable();
  L.DomEvent.stop(e);
});
map.on('mousemove', (e) => {
  if (!S.dragging || !dragFrom) return;
  S.sq.lat = dragFrom.lat + (e.latlng.lat - dragFrom.ll.lat);
  S.sq.lon = dragFrom.lon + (e.latlng.lng - dragFrom.ll.lng);
  drawSquare();
});
function endDrag() {
  if (!S.dragging) return;
  S.dragging = false;
  map.dragging.enable();
  const moved = dragFrom && (Math.abs(dragFrom.lat - S.sq.lat) > 1e-9 || Math.abs(dragFrom.lon - S.sq.lon) > 1e-9);
  dragFrom = null;
  if (moved) moveSquare(S.sq.lat, S.sq.lon);
  setTimeout(() => { S.justDragged = false; }, 0);
  S.justDragged = moved;
}
map.on('mouseup', endDrag);
document.addEventListener('mouseup', endDrag);
map.on('click', (e) => {
  if (S.justDragged || busy()) return;
  const p = toWindow(e.latlng.lat, e.latlng.lng), h = S.sq.km * 500;
  if (Math.abs(p.x) <= h && Math.abs(p.y) <= h) return;       // clicks inside the square don't move it
  moveSquare(e.latlng.lat, e.latlng.lng);
  hideHint();
});

let hintHidden = false;
function hideHint() { if (!hintHidden) { hintHidden = true; $('mapHint').style.opacity = 0; } }
map.on('dragstart', hideHint);                 // user drags only (setView / fitBounds also fire zoomstart)

/* ------------------------------------------------------------ panel state */

function busy() { return !!S.starting || !!(S.job && (S.job.state === 'running' || S.job.state === 'waiting')); }     // (starting: the click is sent, the job not yet)
function lockTerrain(lock) {
  $('cardTerrain').classList.toggle('locked', lock);
  $('cardSettings').classList.toggle('locked', lock);
  if (lock) {
    $('diorama').removeAttribute('src');
    $('dioEmpty').classList.remove('hidden');
    $('photo').classList.remove('ready');
    $('photoBadge').classList.add('hidden');
    $('stats').innerHTML = '';
    $('warnings').innerHTML = '';
    $('srcTag').textContent = '';
  }
}
function updateButtons() {
  const g = S.game;
  const ready = g && g.found;
  $('loadBtn').disabled = busy();
  $('createBtn').disabled = busy() || !S.preview || !ready || !$('name').value.trim() || S.nameBad;
  // while a terrain, trails and lifts, trees or build job runs, every setting of the Create tab is locked: the download
  // works on the settings it was started with, and changing one mid-way would not apply to it
  const b = busy();
  document.querySelectorAll('#tab-create input, #tab-create select, #tab-create textarea').forEach((el) => { el.disabled = b; });
  $('qBtn').disabled = b;
  document.querySelectorAll('.mact .link').forEach((l) => { l.disabled = b; });
  for (const h of [handle, rotHandle]) { if (b) h.dragging.disable(); else h.dragging.enable(); }
  $('tab-create').classList.toggle('working', b);
  document.body.classList.toggle('working', b);          // (the handles on the map are dimmed and ignore the mouse)
}

function renderGame(g) {
  S.game = g;
  const banner = $('banner');
  banner.className = 'banner hidden';
  if (!g || !g.found) {
    setStatus('bad', 'Game not found', 'Click to show the creator where Ski-E-O is installed');
    banner.className = 'banner';
    banner.innerHTML = 'Ski-E-O! was not found on this PC. If it is installed, show the creator where.' +
      '<br><button class="gbtn green" id="locateBtn">Locate game folder</button>';
    $('locateBtn').onclick = locateGame;
  } else if (!g.ready) {
    setStatus('warn', 'Reading game files...', '');
  } else if (g.running) {
    setStatus('warn', 'Ski-E-O is running', 'Maps are built while the game runs and installed when you close it.');
  } else {
    setStatus('ok', 'Ski-E-O ready', `${g.folder}\nbuild ${g.build || '?'}`);
  }
  updateButtons();
}

function setStatus(kind, text, title) {
  const p = $('gamePill');
  p.className = 'status ' + kind;
  p.querySelector('span').textContent = text;
  p.title = title || '';
}

async function locateGame() {
  const r = await call('pick_game_folder');
  if (!r.ok) return errorBox(r.error);
  renderGame(r.game);
  if (r.game.found && !r.game.ready) prepareGame();
}
async function refreshGame() {
  if (busy()) return;
  const r = await call('game_status');
  if (r.ok) renderGame(r);
}
async function prepareGame() {
  const r = await call('prepare_game');
  if (!r.ok) return errorBox(r.error);
  startJob(r);
}

/* ------------------------------------------------------------ jobs */

const JOB_TITLES = { prepare: 'Preparing', preview: 'Loading terrain', osm: 'Loading the trails and lifts', trees: 'Loading the real tree cover', create: 'Creating map', install: 'Installing',
  uninstall: 'Removing', delete: 'Deleting', rebuild: 'Rebuilding', repair: 'Repairing the map list' };

function startJob(j) {
  S.job = j;
  renderJob();
  clearInterval(S.busyPoll);
  S.busyPoll = setInterval(async () => {
    const r = await call('job');
    if (r.ok && r.id) window.app.onEvent('job', r);
  }, 700);
}

function renderJob() {
  const j = S.job;
  const box = $('jobBox');
  const active = j && (j.state === 'running' || j.state === 'waiting');
  const anchor = j && j.kind === 'preview' ? $('loadBtn') : j && j.kind === 'osm' ? $('osmRow') : j && j.kind === 'trees' ? $('treesRow') : $('createBtn');
  if (box.previousElementSibling !== anchor) anchor.after(box);
  const inPanel = j && ['preview', 'osm', 'trees', 'create', 'install', 'rebuild', 'uninstall', 'delete', 'repair', 'prepare'].includes(j.kind);
  box.classList.toggle('hidden', !(active && inPanel));
  box.classList.toggle('waiting', !!(j && j.state === 'waiting'));
  if (active) {
    $('jobText').textContent = j.text || (JOB_TITLES[j.kind] || 'Working') + '...';
    $('jobBar').style.width = Math.round((j.fraction || 0) * 100) + '%';
    if (j.kind === 'prepare') setStatus('warn', 'Reading game files...', '');
  }
  updateButtons();
}

window.app = {
  onEvent(kind, p) {
    if (kind !== 'job' || !p) return;
    const prev = S.job;
    if (prev && prev.id === p.id && !(prev.state === 'running' || prev.state === 'waiting')) return;   // already handled
    S.job = p;
    renderJob();
    if (p.state === 'running' || p.state === 'waiting') return;
    clearInterval(S.busyPoll);
    jobFinished(p);
  },
};

function jobFinished(j) {
  if (j.kind === 'osm' && j.state !== 'done') { $('osm').checked = false; clearOsm(); }
  if (j.kind === 'trees' && j.state !== 'done') { $('realTrees').checked = false; clearTrees(); }
  if (j.state === 'cancelled') { toast('Cancelled'); return refreshGame(); }
  if (j.state === 'error' && j.needs) { refreshGame(); return askKey(j); }
  if (j.state === 'error') { refreshGame(); return errorBox(j.error); }
  const r = j.result || {};
  if (j.kind === 'prepare') { renderGame(r); toast('Game files ready'); }
  if (j.kind === 'preview') showPreview(r);
  if (j.kind === 'osm') showOsm(r);
  if (j.kind === 'trees') showTrees(r);
  if (j.kind === 'create') { showDone(r); loadMaps(); }
  if (['install', 'uninstall', 'rebuild'].includes(j.kind)) {
    toast({ install: 'Installed in Ski-E-O', uninstall: 'Removed from Ski-E-O', rebuild: 'Rebuilt and installed' }[j.kind]);
    loadMaps();
  }
  if (j.kind === 'delete') { toast('Map deleted'); loadMaps(); }
  if (j.kind === 'repair') toast('Map list rebuilt');
  refreshGame();
}

$('cancelBtn').onclick = () => call('cancel');

/* ------------------------------------------------------------ preview */

$('loadBtn').onclick = async () => {
  hideHint();
  $('doneBox').classList.add('hidden');
  S.starting = true; updateButtons();
  let r;
  try { r = await call('preview', S.sq.lat, S.sq.lon, S.sq.km, S.sq.rot); } finally { S.starting = false; }
  if (!r.ok) { updateButtons(); return errorBox(r.error); }
  startJob(r);
};

function showPreview(p) {
  S.preview = p;
  lockTerrain(false);
  $('diorama').src = p.diorama;
  $('dioEmpty').classList.add('hidden');
  $('photo').classList.add('ready');
  $('photoBadge').classList.remove('hidden');
  // every dataset the terrain was made from, under its official name, one chip each
  $('srcTag').replaceChildren(...((p.datasets && p.datasets.length) ? p.datasets : [p.source]).map(n => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = n;
    return chip;
  }));
  $('srcTag').title = p.credit;
  $('stats').innerHTML = [
    ['Peak', fmtElev(p.peak_m)], ['Base', fmtElev(p.base_m)], ['Vertical', fmtElev(p.relief_m)],
    ['Avg slope', Math.round(p.mean_slope) + '°'],
  ].map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('');
  $('warnings').innerHTML = (p.warnings || []).map((w) => `<div class="warn">${esc(w)}</div>`).join('');
  // Initialize terrain modification controls
  $('heightMod').value = 1;
  $('heightOff').value = 1;
  _dioramaMod = 1;
  _dioramaOff = 0;
  renderTerrain();
  if (overlay) map.removeLayer(overlay);
  overlay = new RotatedOverlay(p.shade, squareBounds(p.lat, p.lon, p.size_km, 0), { opacity: 0.55, interactive: false, rot: p.rot || 0 });
  if (S.overlayOn) overlay.addTo(map);
  $('overlayBtn').disabled = false;
  $('overlayBtn').classList.toggle('on', S.overlayOn);
  applyDefaults(p.defaults);
  if (!S.touched.name && S.suggestName) $('name').value = S.suggestName;
  checkName();
  updateButtons();
  $('cardTerrain').scrollIntoView({ behavior: 'smooth', block: 'start' });      // down to the terrain card: the whole picture and its numbers
  clearOsm();
  if ($('osm').checked) startOsm();
}

/* ------------------------------------------------------------ real trails and lifts (OpenStreetMap) */

const DIFF_COLOR = { Beginner: '#2e9e4f', Intermediate: '#2563eb', Expert: '#151515', Pro: '#151515' };
async function startOsm() {
  clearOsm();
  const r = await call('osm');
  if (!r.ok) { $('osm').checked = false; return errorBox(r.error); }
  startJob(r);
}
async function startTrees() {
  clearTrees();
  const r = await call('trees');
  if (!r.ok) { $('realTrees').checked = false; return errorBox(r.error); }
  startJob(r);
}
function clearTrees() { $('treesInfo').classList.add('hidden'); $('treesInfo').textContent = ''; }
function showTrees(r) {
  if (!$('realTrees').checked || !S.preview) return;     // switched off, or the area changed, while it loaded
  $('treesInfo').textContent = `Real tree cover loaded: about ${r.percent}% of the area is forest.`;
  $('treesInfo').classList.remove('hidden');
}
$('realTrees').onchange = () => { if ($('realTrees').checked) startTrees(); else clearTrees(); };
function clearOsm() {
  S.osm = S.osmSkip = null;
  if (osmLayer) { map.removeLayer(osmLayer); osmLayer = null; }
  $('osmInfo').classList.add('hidden');
  $('osmInfo').innerHTML = '';
}
function showOsm(r) {
  if (!$('osm').checked || !S.preview) return;           // switched off, or the area changed, while it loaded
  S.osm = r;
  osmLayer = L.layerGroup(r.lines.map((x) => {
    if (x.kind === 'lift') {
      return L.polyline(x.pts, { color: '#c0392b', weight: 3, dashArray: '7 4' })
        .bindTooltip(`${esc(x.name)}<br>${esc(x.game)}`, { sticky: true });
    }
    if (x.kind === 'glade') {                              // left out: shown so the satellite view can be checked
      const st = { color: '#959ba4', weight: 3, opacity: 0.95, dashArray: '9 6' };
      return (x.closed ? L.polygon(x.pts, { ...st, fillOpacity: 0.05 }) : L.polyline(x.pts, st))
        .bindTooltip(`${esc(x.name)}<br>Glade: left out`, { sticky: true });
    }
    const st = { color: DIFF_COLOR[x.difficulty], weight: 2.5, opacity: 0.9, dashArray: x.difficulty === 'Pro' ? '2 5' : null };
    return (x.kind === 'bowl' ? L.polygon(x.pts, { ...st, fillOpacity: 0.12 }) : L.polyline(x.pts, st))
      .bindTooltip(esc(x.name), { sticky: true });
  })).addTo(map);
  const s = r.summary, d = s.difficulties || {};
  const skipped = Object.entries(s.skipped || {});
  S.osmSkip = new Set();
  $('osmInfo').innerHTML = '<div class="stats">' + [['Lifts', s.lifts], ['Trails', s.trails],
    ['Green / blue', `${d.Beginner || 0} / ${d.Intermediate || 0}`], ['Black / 2×', `${d.Expert || 0} / ${d.Pro || 0}`]]
    .map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('') + '</div>' +
    (s.lift_list.length ? '<details><summary>The lifts in the game (untick to leave one out)</summary><div class="osm-list">' +
      s.lift_list.map((l) => `<label><input type="checkbox" data-id="${l.id}" checked><b>${esc(l.name)}</b>` +
        `<span>${esc(l.real)} → ${esc(l.game)} · $${l.upkeep.toLocaleString('en-US')}/night</span></label>`).join('') +
      '</div></details><div class="meta" id="osmCost"></div>' : '') +
    (skipped.length ? `<div class="meta">Left out: ${skipped.map(([k, v]) => `${esc(k)} (${v})`).join(', ')}.</div>` : '') +
    (s.notes || []).map((n) => `<div class="meta">${esc(n)}</div>`).join('');
  $('osmInfo').querySelectorAll('.osm-list input').forEach((c) => {
    c.onchange = () => { if (c.checked) S.osmSkip.delete(+c.dataset.id); else S.osmSkip.add(+c.dataset.id); osmCost(); };
  });
  osmCost();
  $('osmInfo').classList.remove('hidden');
}
// lifts cost upkeep every night, open or not; a real resort's lifts cost far more than a new game earns at first
function osmCost() {
  const box = $('osmCost'), s = S.osm && S.osm.summary;
  if (!box || !s) return;
  const kept = s.lift_list.filter((l) => !S.osmSkip.has(l.id));
  const night = kept.reduce((a, l) => a + l.upkeep, 0);
  box.textContent = `Upkeep of the ${kept.length} lifts: $${night.toLocaleString('en-US')} a night, open or not. A new game ` +
    'starts with $165,000: to run a big resort from day one, turn on Sandbox (no costs) in Advanced Options when you ' +
    'start it, or leave lifts out here and build them in the game as you grow.';
}
$('osm').onchange = () => {
  if (!$('osm').checked) return clearOsm();
  if (S.preview) startOsm();
};

$('photo').onclick = () => {
  if (!S.preview || !window.terrain3d) return;
  window.terrain3d.open({
    token: S.token, tiles: S.tiles, name: $('name').value.trim() || S.suggestName || 'Terrain', units: S.units,
    treeline: +$('treeline').value, onError: (msg) => errorBox(msg),
    heightModifier: +$('heightMod').value, heightOffset: +$('heightOff').value,
  });
};

$('overlayBtn').onclick = () => {
  S.overlayOn = !S.overlayOn;
  $('overlayBtn').classList.toggle('on', S.overlayOn);
  if (overlay) { if (S.overlayOn) overlay.addTo(map); else map.removeLayer(overlay); }
};

/* ------------------------------------------------------------ settings */

function fillBiomes(list) {
  $('biome').innerHTML = list.map((b) => `<option value="${esc(b.id)}">${esc(b.label)}</option>`).join('');
}
function applyDefaults(d) {
  if (!d) return;
  S.defaults = d;
  if (!S.touched.biome) $('biome').value = d.biome;
  $('biomeHint').textContent = `Automatic: nearest real resort in the game is ${d.near} (${d.near_km.toLocaleString('en-US')} km)`;
  if (!S.touched.treeline) $('treeline').value = autoTreeline();
  if (!S.touched.snow) $('snow').value = (d.snows || {})[$('biome').value] ?? d.snow;
  renderSettings();
}
// what the game shows for the map: the biome's average annual snowfall times the multiplier
function snowYear() {
  const b = (S.biomes || []).find((x) => x.id === $('biome').value);
  if (!b || !b.snow_in) return '';
  const inch = b.snow_in * +$('snow').value;
  return S.units === 'ft' ? ` (${Math.round(inch / 5) * 5}″/yr)` : ` (${(Math.round(inch * 2.54 / 10) * 10).toLocaleString('en-US')} cm/yr)`;
}
function renderSettings() {
  $('tlAuto').classList.toggle('hidden', !S.touched.treeline);
  ['treeline', 'fade', 'snow', 'valley', 'slope', 'trees'].forEach(showNum);
}
let _dioramaMod = 1, _dioramaOff = 0, _dioramaTimer = null, _dioramaBusy = false;
async function runDiorama() {
  if (_dioramaBusy) { _dioramaTimer = setTimeout(runDiorama, 150); return; }       // one at a time; then the latest value
  _dioramaBusy = true;
  const mod = _dioramaMod, offs = _dioramaOff;
  try {
    const result = await window.pywebview.api.diorama(mod, _dioramaOff);
    const dataUrl = result && result.ok ? (result.value !== undefined ? result.value : result) : null;
    if (dataUrl && mod === _dioramaMod && offs === _dioramaOff) $('diorama').src = dataUrl;
  } catch (e) { /* silent: preview may not be loaded yet */ }
  _dioramaBusy = false;
  if (mod !== _dioramaMod || offs !== _dioramaOff) runDiorama();
}
function renderTerrain() {
  ['heightMod', 'heightOff'].forEach(showNum);
  // Update terrain stats based on height modifier and offset
  const p = S.preview;
  if (!p || !p.mean_m) return;
  const mod = +$('heightMod').value;
  const off = +$('heightOff').value;
  const mean = p.mean_m;
  const peak = Math.max(mean + (p.peak_m - mean) * mod + off, 1);          // land below 0 m is put to 1 m
  const base = Math.max(mean + (p.base_m - mean) * mod + off, 1);
  const relief = peak - base;
  const slope = p.mean_slope * mod;
  $('stats').innerHTML = [
    ['Peak', fmtElev(peak)], ['Base', fmtElev(base)], ['Vertical', fmtElev(relief)],
    ['Avg slope', Math.round(slope) + '°'],
  ].map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('');
  // Refresh the diorama picture. The offset only changes its shape where land would go below 0 m (put to 1 m), so it only
  // counts then; the renders are held back until the slider pauses and one runs at a time, so dragging never queues up work
  const offEff = mean + (p.base_m - mean) * mod + off < 0 ? off : 0;
  if (mod !== _dioramaMod || offEff !== _dioramaOff) {
    _dioramaMod = mod;
    _dioramaOff = offEff;
    clearTimeout(_dioramaTimer);
    _dioramaTimer = setTimeout(runDiorama, 150);
  }
  // Refresh 3D view if it's open
  if (window.terrain3d && window.terrain3d.refresh) {
    window.terrain3d.refresh({ heightModifier: mod, heightOffset: off });
  }
}

/* The value next to each slider is a box you can type into: Enter (or clicking away) applies it, Esc undoes.
   Values are typed in the shown units and kept inside the slider's range. */
const clampTo = (el, v) => Math.min(+el.max, Math.max(+el.min, v));
const NUMS = {
  size: {
    box: 'sizeOut', unit: 'sizeUnit', decimal: true,
    show: () => [S.sq.km.toFixed(1), S.units === 'ft' ? `km (${(S.sq.km * 0.621371).toFixed(1)} mi)` : 'km'],
    apply: (v) => {
      S.sq.km = Math.round(clampTo($('size'), v) * 10) / 10;
      $('size').value = S.sq.km;
      moveSquare(S.sq.lat, S.sq.lon); fitSquare();
    },
  },
  rot: {
    box: 'rotOut', unit: 'rotUnit',
    show: () => [String(S.sq.rot), '°'],
    apply: (v) => { S.sq.rot = normRot(v); $('rot').value = S.sq.rot; drawSquare(); areaChanged(); },
  },
  treeline: {
    box: 'tlOut', unit: 'tlUnit', zero: 'none',
    show: () => { const m = +$('treeline').value; return m <= 0 ? ['none', '(trees everywhere)'] : [Math.round(toUnits(m)).toLocaleString('en-US'), unitName()]; },
    apply: (v) => { $('treeline').value = clampTo($('treeline'), fromUnits(v)); S.touched.treeline = true; renderSettings(); },
  },
  fade: {
    box: 'fadeOut', unit: 'fadeUnit', zero: 'sharp',
    show: () => { const m = +$('fade').value; return m <= 0 ? ['sharp', ''] : [Math.round(toUnits(m)).toLocaleString('en-US'), unitName()]; },
    apply: (v) => { $('fade').value = clampTo($('fade'), fromUnits(v)); renderSettings(); },
  },
  snow: {
    box: 'snowOut', unit: 'snowUnit', decimal: true,
    show: () => [(+$('snow').value).toFixed(2), '×' + snowYear()],
    apply: (v) => { $('snow').value = clampTo($('snow'), Math.round(v * 100) / 100); S.touched.snow = true; renderSettings(); },
  },
  valley: {
    box: 'valOut', unit: 'valUnit', zero: 'off',
    show: () => { const m = +$('valley').value; return m <= 0 ? ['off', ''] : [Math.round(toUnits(m)).toLocaleString('en-US'), unitName()]; },
    apply: (v) => { $('valley').value = clampTo($('valley'), fromUnits(v)); renderSettings(); },
  },
  slope: {
    box: 'slopeOut', unit: 'slopeUnit',
    show: () => [String(Math.round(+$('slope').value)), '°'],
    apply: (v) => { $('slope').value = clampTo($('slope'), Math.round(v)); renderSettings(); },
  },
  trees: {
    box: 'treesOut', unit: 'treesUnit',
    show: () => [(+$('trees').value).toLocaleString('en-US'), ''],
    apply: (v) => { $('trees').value = clampTo($('trees'), Math.round(v / 1000) * 1000); renderSettings(); },
  },
  heightMod: {
    box: 'heightModOut', unit: 'heightModUnit', decimal: true,
    show: () => [(+$('heightMod').value).toFixed(1), '×'],
    apply: (v) => { $('heightMod').value = clampTo($('heightMod'), Math.round(v * 10) / 10); renderTerrain(); },
  },
  heightOff: {
    box: 'heightOffOut', unit: 'heightOffUnit',
    show: () => [String(Math.round(+$('heightOff').value)), 'm'],
    apply: (v) => { $('heightOff').value = clampTo($('heightOff'), Math.round(v)); renderTerrain(); },
  },
};
function showNum(key, force) {
  const n = NUMS[key], box = $(n.box);
  if (!force && document.activeElement === box) return;      // don't overwrite what is being typed
  const [text, unit] = n.show();
  box.value = box.dataset.shown = text;
  $(n.unit).textContent = unit;
}
function parseNum(t, decimal) {
  /* "0,93" and "0.93" both work (most of Europe types a decimal comma). In whole-number boxes a , or . before exactly
     three digits groups thousands: 11,300 ft / 3.500 m. */
  let s = t.replace(/[^0-9.,\-]/g, '');
  if (!decimal) s = s.replace(/[.,](?=\d{3}(?!\d))/g, '');
  return parseFloat(s.replace(',', '.'));
}
function commitNum(key) {
  const n = NUMS[key], box = $(n.box), t = box.value.trim().toLowerCase();
  if (t !== (box.dataset.shown || '').toLowerCase()) {      // only when something was typed: tabbing through changes nothing
    const v = n.zero && (t === '' || t === n.zero || t === 'no' || t === 'none') ? 0 : parseNum(t, n.decimal);
    if (isFinite(v)) n.apply(v);
  }
  showNum(key, true);
}
Object.entries(NUMS).forEach(([key, n]) => {
  const box = $(n.box);
  box.onfocus = () => box.select();
  box.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitNum(key); box.blur(); }
    if (e.key === 'Escape') { showNum(key, true); box.blur(); }
  };
  box.onblur = () => commitNum(key);
});
function autoTreeline() {
  const d = S.defaults;
  return d ? (d.treelines || {})[$('biome').value] ?? d.treeline : 0;
}
$('biome').onchange = () => {
  S.touched.biome = true;
  const d = S.defaults;
  if (d) {                     // the chosen biome's own treeline / snowfall at this latitude
    if (!S.touched.treeline) $('treeline').value = autoTreeline();
    if (!S.touched.snow && d.snows) $('snow').value = d.snows[$('biome').value];
  }
  renderSettings();
};
$('treeline').oninput = () => { S.touched.treeline = true; renderSettings(); };
$('tlAuto').onclick = () => { S.touched.treeline = false; $('treeline').value = autoTreeline(); renderSettings(); };
$('snow').oninput = () => { S.touched.snow = true; renderSettings(); };
$('valley').oninput = renderSettings;
$('slope').oninput = renderSettings;
$('fade').oninput = renderSettings;
$('trees').oninput = renderSettings;
$('heightMod').oninput = renderTerrain;
$('heightOff').oninput = renderTerrain;
let nameTimer = null;
function checkName() {
  clearTimeout(nameTimer);
  nameTimer = setTimeout(async () => {
    const r = await call('name_ok', $('name').value);
    S.nameBad = !!(r.ok && !r.valid && r.message);
    const note = !!(r.ok && r.valid && r.replaces);          // same name as a saved map: allowed, it gets replaced
    $('nameErr').textContent = S.nameBad || note ? r.message : '';
    $('nameErr').classList.toggle('hidden', !S.nameBad && !note);
    $('createBtn').querySelector('.lbl').textContent = note ? 'Replace Map' : 'Create Map';
    $('name').classList.toggle('bad', S.nameBad || note);        // red for an existing name too (the map is still allowed)
    updateButtons();
  }, 220);
}
/* Names keep to letters A-Z, numbers, spaces and - ' . & ( ): accents become plain letters, anything else is dropped
   (the same rule as api.NAME_CHARS) */
const NAME_SWAPS = { 'ß': 'ss', 'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'Œ': 'OE', 'ø': 'o', 'Ø': 'O', 'ł': 'l', 'Ł': 'L', 'đ': 'd', 'Đ': 'D', 'þ': 'th' };
function cleanName(s) {
  return s.replace(/[ßæÆœŒøØłŁđĐþ]/g, (c) => NAME_SWAPS[c]).normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^A-Za-z0-9 '.&()\-]/g, '');
}
let nameHintTimer = 0;
$('name').oninput = () => {
  const box = $('name'), v = box.value, c = cleanName(v);
  if (c !== v) {
    const caret = Math.max(0, (box.selectionStart || 0) - (v.length - c.length));
    box.value = c;
    box.setSelectionRange(caret, caret);
    $('nameHint').classList.remove('hidden');
    clearTimeout(nameHintTimer);
    nameHintTimer = setTimeout(() => $('nameHint').classList.add('hidden'), 5000);
  }
  S.touched.name = true; updateButtons(); checkName();
};
$('size').oninput = () => { S.sq.km = +$('size').value; drawSquare(); };
$('size').onchange = () => { S.sq.km = +$('size').value; moveSquare(S.sq.lat, S.sq.lon); fitSquare(); };
$('rot').oninput = () => { S.sq.rot = normRot(+$('rot').value); drawSquare(); };
$('rot').onchange = () => { S.sq.rot = normRot(+$('rot').value); drawSquare(); areaChanged(); };
$('rot').ondblclick = () => { S.sq.rot = 0; $('rot').value = 0; drawSquare(); areaChanged(); };     // double-click: north up again

function fitSquare() {
  map.fitBounds(squareBounds(S.sq.lat, S.sq.lon, S.sq.km, S.sq.rot), { padding: [60, 60], maxZoom: 14 });
}

/* ------------------------------------------------------------ create */

$('createBtn').onclick = async () => {
  const name = $('name').value.trim();
  if (!name) { $('name').focus(); return toast('Give the map a name first', true); }
  S.starting = true; updateButtons();
  let r;
  try { r = await call('create', {
    name, lat: S.preview.lat, lon: S.preview.lon, rot: S.preview.rot || 0, size_km: S.preview.size_km, biome: $('biome').value,
    treeline_m: +$('treeline').value, snow: +$('snow').value, valley_m: +$('valley').value, max_trees: +$('trees').value,
    tree_slope: +$('slope').value, treeline_fade: +$('fade').value,
    height_modifier: +$('heightMod').value, height_offset: +$('heightOff').value,
    base: S.preview.base,             // flattest low ground, picked when the terrain loaded (with real lifts: their base)
    osm: $('osm').checked && !!S.osm, osm_skip: S.osmSkip ? [...S.osmSkip] : [],
    real_trees: $('realTrees').checked,
  }); } finally { S.starting = false; }
  if (!r.ok) { updateButtons(); return errorBox(r.error); }
  $('doneBox').classList.add('hidden');
  startJob(r);
};

function showDone(m) {
  $('doneImg').src = m.thumb || '';
  $('doneTitle').textContent = m.name;
  $('doneText').textContent = `Start Ski-E-O, choose New Resort and pick ${m.name} on the map list ` +
    `(with the ${m.biome_label} maps).` + (m.stats && m.stats.trees != null ? ` ${m.stats.trees.toLocaleString('en-US')} trees planted.` : '') +
    (m.stats && m.stats.lifts ? ` ${m.stats.lifts} lifts and ${m.stats.trails} trails are built in.` : '');
  $('doneBox').classList.remove('hidden');
  $('doneBox').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
$('playBtn').onclick = async () => { await call('play'); setTimeout(refreshGame, 6000); };      // once the game has had time to start
$('againBtn').onclick = () => {
  $('doneBox').classList.add('hidden');
  $('name').value = '';
  S.touched = { biome: false, treeline: false, snow: false, name: false };
  S.preview = null;
  if (overlay) { map.removeLayer(overlay); overlay = null; }
  clearOsm();
  $('overlayBtn').disabled = true;
  lockTerrain(true);
  updateButtons();
  $('q').focus();
};

/* ------------------------------------------------------------ search */

let results = [], resSel = -1;
async function doSearch() {
  const q = $('q').value.trim();
  if (!q) return;
  const box = $('results');
  box.innerHTML = '<div class="row none">Searching...</div>';
  box.classList.remove('hidden');
  const r = await call('search', q);
  if (!r.ok) { box.innerHTML = `<div class="row none">${esc(r.error)}</div>`; return; }
  results = r.results || [];
  resSel = -1;
  box.innerHTML = results.length ? results.map((x, i) =>
    `<button class="row" data-i="${i}"><div>${esc(x.label)}</div><div class="k">${esc(x.kind || '')}</div></button>`).join('')
    : '<div class="row none">Nothing found. Try another name, or type coordinates like 46.02, 7.75</div>';
  box.querySelectorAll('.row[data-i]').forEach((el) => { el.onclick = () => pickResult(+el.dataset.i); });
}
function pickResult(i) {
  const x = results[i];
  if (!x) return;
  $('results').classList.add('hidden');
  S.suggestName = cleanName((x.name || (x.label || '').split(',')[0]).trim()
    .replace(/\s+(ski\s+(resort|area|hill|cent(re|er))|resort|mountain\s+resort)$/i, '')).replace(/\s+/g, ' ').trim().slice(0, 40);
  if (!S.touched.name && S.preview) { $('name').value = S.suggestName; checkName(); }
  if (x.size_km) { S.sq.km = x.size_km; $('size').value = x.size_km; }
  moveSquare(x.lat, x.lon);
  fitSquare();
  hideHint();
}
$('qBtn').onclick = doSearch;
$('q').addEventListener('keydown', (e) => {
  const items = [...$('results').querySelectorAll('.row[data-i]')];
  if (e.key === 'Enter') { e.preventDefault(); if (resSel >= 0) pickResult(resSel); else doSearch(); }
  else if (e.key === 'Escape') $('results').classList.add('hidden');
  else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && items.length) {
    e.preventDefault();
    resSel = (resSel + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
    items.forEach((el, k) => el.classList.toggle('sel', k === resSel));
  }
});
document.addEventListener('click', (e) => { if (!e.target.closest('.search')) $('results').classList.add('hidden'); });

/* ------------------------------------------------------------ my maps */

async function loadMaps() {
  const r = await call('maps');
  if (!r.ok) return;
  S.maps = r.maps || [];
  renderMaps();
}
function renderMaps() {
  $('mapCount').textContent = S.maps.length || '';
  $('mapsEmpty').classList.toggle('hidden', S.maps.length > 0);
  $('mapsList').innerHTML = S.maps.map((m) => {
    const badge = m.stale ? '<span class="badge stale">Rebuild recommended</span>'
      : m.installed ? '<span class="badge">Installed</span>' : '<span class="badge off">Not installed</span>';
    const st = m.stats || {};
    return `<div class="mrow" data-slug="${esc(m.slug)}">
      <img src="${m.thumb || ''}" alt="">
      <div class="mi"><h4 title="${esc(m.name)}">${esc(m.name)}</h4>
        <div class="sub">${esc(m.biome_label)} · ${m.size_km.toFixed(1)} km · vertical ${fmtElev((st.vert_ft || 0) / FT)}</div>
        ${badge}
        <div class="mact">
          <button class="link" data-a="show">Show</button>
          ${m.installed ? '<button class="link" data-a="uninstall">Uninstall</button>' : '<button class="link" data-a="install">Install</button>'}
          <button class="link" data-a="rebuild">Rebuild</button>
          <button class="link danger" data-a="delete">Delete</button>
        </div></div></div>`;
  }).join('');
  $('mapsList').querySelectorAll('.mact .link').forEach((b) => {
    b.onclick = () => mapAction(b.closest('.mrow').dataset.slug, b.dataset.a);
  });
  updateButtons();
}
async function mapAction(slug, a) {
  const m = S.maps.find((x) => x.slug === slug);
  if (!m || busy()) return;
  if (a === 'show') {
    S.sq.km = m.size_km; $('size').value = m.size_km;
    S.sq.rot = normRot(m.rot || 0); $('rot').value = S.sq.rot;
    moveSquare(m.lat, m.lon); fitSquare();
    return;
  }
  if (a === 'delete' && !await confirmBox('Delete ' + m.name + '?',
    'The map is removed from Ski-E-O and from this app. Resorts you started on it will not load any more.', 'Delete')) return;
  if (a === 'uninstall' && !await confirmBox('Uninstall ' + m.name + '?',
    'Resorts you started on this map will not load until you install it again. The map stays in this app.', 'Uninstall')) return;
  if (a === 'rebuild' && !await confirmBox('Rebuild ' + m.name + '?',
    'Builds the map again for the current game version (same terrain and trees, so your resorts keep working) and installs it.', 'Rebuild', false)) return;
  const fn = { install: 'install_map', uninstall: 'uninstall_map', rebuild: 'rebuild_map', delete: 'delete_map' }[a];
  const r = await call(fn, slug);
  if (!r.ok) return errorBox(r.error);
  startJob(r);
}
/* ------------------------------------------------------------ mod library */
function renderMods(r) {
  if (!r.found) { $('modsList').innerHTML = '<div class="empty">Ski-E-O was not found.</div>'; return; }
  $('modsList').innerHTML = r.mods.map((m) => {
    const note = m.included ? 'Already in your own lift mod'
      : m.on ? (m.key ? `Installed: press ${esc(m.key)} in game` : 'Installed: in the build menu') : 'Not installed';
    return `<div class="mrow" data-mod="${esc(m.id)}">
      <div class="mi"><h4>${esc(m.name)}</h4>
        ${m.about ? `<div class="sub">${esc(m.about)}</div>` : ''}
        <span class="badge${m.on ? '' : ' off'}">${note}</span></div>
      <div class="mbtns">
        <button class="gbtn green" data-on="1" ${m.on || m.included ? 'disabled' : ''} aria-label="Install ${esc(m.name)}">Install</button>
        <button class="gbtn crimson" data-on="0" ${!m.on || m.included ? 'disabled' : ''} aria-label="Uninstall ${esc(m.name)}">Uninstall</button>
      </div></div>`;
  }).join('');
  $('modsList').querySelectorAll('.mbtns button').forEach((btn) => {
    btn.onclick = async () => {
      const row = btn.closest('.mrow');
      const on = btn.dataset.on === '1';
      if (!on && !await confirmBox('Uninstall ' + row.querySelector('h4').textContent + '?',
        'It is removed from the game. Resorts that use it may not load until you install it again.', 'Uninstall')) return;
      document.querySelectorAll('#modsList .mbtns button').forEach((x) => { x.disabled = true; });
      row.querySelector('.badge').textContent = on ? 'Installing...' : 'Removing...';
      const res = await call('set_mod', row.dataset.mod, on);
      if (!res.ok) { errorBox(res.error); return loadMods(); }
      renderMods(res);
      refreshGame();                                  // a mod was added or removed
    };
  });
}
async function loadMods() {
  const r = await call('mod_library');
  if (!r.ok) return errorBox(r.error);
  renderMods(r);
}
/* ------------------------------------------------------------ tabs, footer */

let lastTab = 'create';
function showTab(name) {
  if (name !== 'mods') lastTab = name;
  document.querySelectorAll('.tag-tab').forEach((x) => x.classList.toggle('active', x.dataset.tab === name));
  ['create', 'maps', 'mods'].forEach((n) => $('tab-' + n).classList.toggle('hidden', n !== name));
  $('modsBtn').classList.toggle('hidden', name === 'mods');
  if (name === 'maps') loadMaps();
  if (name === 'mods') loadMods();
}
document.querySelectorAll('.tag-tab').forEach((t) => { t.onclick = () => showTab(t.dataset.tab); });
$('modsBtn').onclick = () => showTab('mods');
$('modsBack').onclick = () => showTab(lastTab);
document.querySelectorAll('[data-layer]').forEach((b) => {
  b.onclick = () => { setLayer(b.dataset.layer); call('set_setting', 'layer', S.layer); };
});
document.querySelectorAll('[data-link]').forEach((b) => { b.onclick = () => call('link', b.dataset.link); });
/* every data source of the app, its provider and licence (the same list as packaging/THIRD-PARTY.txt) */
const LICENSES = [
  ['Maps, imagery and search', [
    ['OpenStreetMap', 'OpenStreetMap contributors (trails, lifts, borders, tree-less areas)', 'ODbL 1.0'],
    ['OpenTopoMap', 'OpenTopoMap (map style)', 'CC-BY-SA'],
    ['Esri World Imagery', 'Esri, Maxar, Earthstar Geographics, GIS User Community', 'Esri terms'],
    ['Photon, Nominatim', 'komoot, OpenStreetMap Foundation (place search, OSM data)', 'ODbL 1.0'],
  ]],
  ['Elevation, national surveys', [
    ['USGS S1M, USGS 3DEP', 'USA: U.S. Geological Survey', 'Public domain'],
    ['swissALTI3D, swissALTIRegio', 'Switzerland, Liechtenstein: swisstopo', 'Free geodata (OGD)'],
    ['IGN LIDAR HD, IGN RGE ALTI', 'France: IGN', 'Licence Ouverte 2.0'],
    ['INGV TINITALY', 'Italy: INGV (Tarquini et al.)', 'CC BY 4.0'],
    ['Bolzano DTM', 'South Tyrol: Provincia autonoma di Bolzano', 'CC0'],
    ['Kartverket', 'Norway: Kartverket', 'CC BY 4.0'],
    ['Korkeusmalli', 'Finland: National Land Survey (Maanmittauslaitos)', 'CC BY 4.0'],
    ['Markhöjdmodell', 'Sweden: Lantmäteriet', 'CC0'],
    ['IGN MDT05', 'Spain: Instituto Geográfico Nacional (CNIG)', 'CC BY 4.0'],
    ['GSI DEM1A, DEM5, DEM10B', 'Japan: Geospatial Information Authority of Japan', 'GSI terms of use'],
    ['BEV Austria ALS DTM', 'Austria: BEV', 'CC BY 4.0'],
    ['Bavaria DGM1', 'Bavaria: Bayerische Vermessungsverwaltung', 'CC BY 4.0'],
    ['GUGiK Poland NMT', 'Poland: GUGiK', 'Open data'],
    ['UGKK SR DMR 5.0', 'Slovakia: UGKK SR', 'CC BY 4.0'],
    ['CUZK DMR 5G', 'Czechia: ČÚZK', 'CC BY 4.0'],
    ['England LIDAR DTM', 'England: Environment Agency', 'OGL v3'],
    ['Scottish LIDAR DTM', 'Scotland: Scottish Government and partners', 'OGL v3'],
    ['Natturufraedistofnun IslandsDEM', 'Iceland: Icelandic Institute of Natural History', 'CC BY 4.0'],
    ['LINZ NZ Lidar DEM, LINZ NZ DEM', 'New Zealand: Toitū Te Whenua LINZ', 'CC BY 4.0'],
    ['Geoscience Australia DEM', 'Australia: Geoscience Australia', 'CC BY 4.0'],
    ['NRCan HRDEM, NRCan ArcticDEM', 'Canada: Natural Resources Canada; ArcticDEM: Polar Geospatial Center', 'OGL Canada'],
  ]],
  ['Elevation elsewhere, gaps and trees', [
    ['Terrain Tiles', 'AWS Open Data (Mapzen; SRTM, GMTED2010, ETOPO1, 3DEP and others)', 'Open data'],
    ['Canopy height', 'Meta and World Resources Institute (Global Canopy Height Map v2)', 'CC BY 4.0'],
  ]],
];
function showLicenses() {
  const list = $('licList');
  list.replaceChildren();
  for (const [title, rows] of LICENSES) {
    const h = document.createElement('h3'); h.textContent = title; list.append(h);
    for (const cells of rows) {
      const r = document.createElement('div'); r.className = 'lic-row';
      cells.forEach((t, i) => { const e = document.createElement(i === 0 ? 'b' : i === 2 ? 'i' : 'span'); e.textContent = t; r.append(e); });
      list.append(r);
    }
  }
  $('licModal').classList.remove('hidden');
}
$('licBtn').onclick = showLicenses;
$('licClose').onclick = () => $('licModal').classList.add('hidden');
$('licModal').addEventListener('mousedown', (e) => { if (e.target === $('licModal')) $('licModal').classList.add('hidden'); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('licModal').classList.add('hidden'); });
function renderUnits() {
  $('unitsBtn').textContent = S.units === 'ft' ? 'Units: feet' : 'Units: metres';
  document.querySelectorAll('#unitsTop span').forEach((s) => s.classList.toggle('on', s.dataset.u === S.units));
  drawSquare(); renderSettings();
  if (S.preview) showStatsOnly();
  renderMaps();
}
function showStatsOnly() {
  const p = S.preview;
  if (!p || !p.mean_m) return;
  const mod = +$('heightMod').value;
  const off = +$('heightOff').value;
  const mean = p.mean_m;
  const peak = Math.max(mean + (p.peak_m - mean) * mod + off, 1);          // land below 0 m is put to 1 m
  const base = Math.max(mean + (p.base_m - mean) * mod + off, 1);
  const relief = peak - base;
  const slope = p.mean_slope * mod;
  $('stats').innerHTML = [['Peak', fmtElev(peak)], ['Base', fmtElev(base)], ['Vertical', fmtElev(relief)],
    ['Avg slope', Math.round(slope) + '°']].map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('');
}
$('unitsBtn').onclick = $('unitsTop').onclick = () => { S.units = S.units === 'ft' ? 'm' : 'ft'; call('set_setting', 'units', S.units); renderUnits(); };
$('gamePill').onclick = () => {
  const g = S.game;
  if (!g || !g.found) return locateGame();
  toast(g.running ? 'Ski-E-O is running. New maps install as soon as you close it.' : `Game folder: ${g.folder}`);
};
$('repairBtn').onclick = async () => {
  if (!await confirmBox('Repair the map list?', 'Rebuilds the game\'s map list from the maps that are installed. Use it if a map is missing from the game\'s list.', 'Repair', false)) return;
  const r = await call('repair');
  if (!r.ok) return errorBox(r.error);
  startJob(r);
};
async function copyDiagnostics() {
  const r = await call('diagnostics');
  if (!r.ok) return toast(r.error, true);
  try { await navigator.clipboard.writeText(r.text); }
  catch (e) {
    const ta = document.createElement('textarea');
    ta.value = r.text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
  }
  toast('Diagnostics copied. Paste them where you ask for help.');
}
$('diagBtn').onclick = copyDiagnostics;

/* ------------------------------------------------------------ start */

async function start() {
  const r = await call('init');
  if (!r.ok) return errorBox(r.error);
  $('ver').textContent = 'v' + r.version;
  S.biomes = r.biomes;
  S.limits = r.limits;
  fillBiomes(r.biomes);
  const st = r.settings || {};
  $('slope').min = S.limits.min_slope; $('slope').max = S.limits.max_slope; $('slope').value = S.limits.default_slope;
  $('fade').max = S.limits.max_fade; $('fade').value = S.limits.default_fade;
  $('trees').min = S.limits.min_trees; $('trees').max = S.limits.max_trees;
  S.units = st.units === 'm' ? 'm' : 'ft';
  layers.topo = tileLayer('topo', 17);
  layers.osm = tileLayer('osm', 19);
  layers.sat = tileLayer('sat', 19);
  setLayer(st.layer || 'topo');
  const v = st.view;
  if (v && isFinite(v.lat) && isFinite(v.lon)) {
    S.sq = { lat: v.lat, lon: v.lon, km: Math.max(S.limits.min_km, Math.min(S.limits.max_km, v.km || 8)), rot: normRot(+v.rot || 0) };
    map.setView([v.lat, v.lon], v.zoom || 12);
  } else {
    map.setView([S.sq.lat, S.sq.lon], 11);
  }
  $('size').min = S.limits.min_km; $('size').max = S.limits.max_km; $('size').value = S.sq.km; $('rot').value = S.sq.rot;
  drawSquare();
  renderUnits();
  renderGame(r.game);
  S.maps = r.maps || [];
  renderMaps();
  if (r.game.found && !r.game.ready) prepareGame();
  // (the game status is checked on start, when a job finishes, after the game is started and when a mod changes; no timer)
}

if (window.pywebview && window.pywebview.api) start();
else window.addEventListener('pywebviewready', start, { once: true });
