/* Full-window 3D view of the loaded terrain: rotate (left drag), move (right drag), zoom (wheel).
   Heights (uint16, every 2nd landscape vertex) and the colour texture come from the app (api.view3d, served as
   /blob/...); the topo-map texture is stitched here from the same map tiles the main map uses (their own local port).
   Close / Esc work at any time, also while loading: every load checks `gen` and is dropped once the view was closed. */
import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const FT = 3.28084;
let R = null;          // { renderer, scene, camera, controls, mesh, skirt, pin, data, heights, tex, raf }
let renderer = null;   // one WebGL context for the app's lifetime (browsers cap how many a page may create)
let gen = 0;           // bumped by every open / close
const LOAD_MS = 90000;
const TOPO_MS = 180000;

function q(s) { return encodeURIComponent(s); }

function withTimeout(p, ms, what) {
  let t;
  const late = new Promise((_, reject) => { t = setTimeout(() => reject(new Error(what + ' took too long')), ms); });
  return Promise.race([p, late]).finally(() => clearTimeout(t));
}

function getRenderer() {
  if (!renderer) {
    renderer = new THREE.WebGLRenderer({ canvas: $('v3dCanvas'), antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  }
  return renderer;
}

async function loadHeights(token, ver) {
  const r = await fetch(`/blob/heights?t=${q(token)}&v=${ver}`);
  if (!r.ok) throw new Error('heights ' + r.status);
  return new Uint16Array(await r.arrayBuffer());
}

function loadTexture(url) {
  return new Promise((resolve, reject) => new THREE.TextureLoader().load(url, resolve, undefined, reject));
}

function buildTerrain(data, heights, exag) {
  const n = data.n, size = data.size_m, half = size / 2, step = size / (n - 1);
  const range = data.hmax - data.hmin;
  const pos = new Float32Array(n * n * 3);
  const uv = new Float32Array(n * n * 2);
  for (let r = 0, k = 0; r < n; r++) {
    for (let c = 0; c < n; c++, k++) {
      pos[k * 3] = c * step - half;
      pos[k * 3 + 1] = heights[k] / 65535 * range * exag;
      pos[k * 3 + 2] = r * step - half;              // row 0 = north = -Z
      uv[k * 2] = c / (n - 1);
      uv[k * 2 + 1] = 1 - r / (n - 1);
    }
  }
  const idx = new Uint32Array((n - 1) * (n - 1) * 6);
  for (let r = 0, k = 0; r < n - 1; r++) {
    for (let c = 0; c < n - 1; c++) {
      const a = r * n + c, b = a + 1, d = a + n, e = d + 1;
      idx[k++] = a; idx[k++] = d; idx[k++] = b;
      idx[k++] = b; idx[k++] = d; idx[k++] = e;
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  return g;
}

function buildSkirt(data, heights, exag) {
  /* diorama-style walls from the terrain edge down to a base below the lowest point */
  const n = data.n, size = data.size_m, half = size / 2, step = size / (n - 1);
  const range = data.hmax - data.hmin, bottom = -Math.max(range * 0.08, size * 0.012) * exag;
  const edges = [];
  for (let c = 0; c < n; c++) edges.push([c, 0]);
  for (let r = 1; r < n; r++) edges.push([n - 1, r]);
  for (let c = n - 2; c >= 0; c--) edges.push([c, n - 1]);
  for (let r = n - 2; r > 0; r--) edges.push([0, r]);
  edges.push(edges[0]);
  const pos = new Float32Array(edges.length * 6);
  edges.forEach(([c, r], i) => {
    const x = c * step - half, z = r * step - half, y = heights[r * n + c] / 65535 * range * exag;
    pos.set([x, y, z, x, bottom, z], i * 6);
  });
  const idx = [];
  for (let i = 0; i < edges.length - 1; i++) {
    const a = i * 2, b = a + 1, c = a + 2, d = a + 3;
    idx.push(a, c, b, b, c, d);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/* ---------------------------------------------------------------- surfaces and overlays
   Surface (one at a time): Terrain or Topo map, on the terrain mesh itself.
   Overlays (any number, on top of each other and of either surface): Slope difficulty, Trails and lifts, Trees. They are drawn
   into one transparent canvas (OV_PX square, the square's own coordinates, north up) that a second mesh, sharing the terrain's
   geometry, shows just above the ground; the order is slope, trees, trails and lifts. */
const OV_PX = 2048;
const OV_ORDER = ['build', 'slope', 'trees', 'trails'];
const BUILD_MAX = 22;                                      // the game's Buildability overlay: steeper than this is "Too steep"
const TIERS = ['Beginner', 'Intermediate', 'Expert', 'Extreme'];
const TIER_RANGE = ['< 16°', '16–27°', '27–33°', '> 33°'];
/* the game's Trail rating styles (Settings > Interface). The slope limits are the same in all four (checked on the game's own
   overlay); what differs is the colours and the symbols: North American marks the tiers with a circle, square, diamond and
   double diamond, Japanese marks its double black with two red circles, the others use circles only. "auto" is the game's
   Automatic: the style of the map's region. */
const STRIPE_LIGHT = [233, 237, 240];
const RATINGS = {
  auto: { label: 'Automatic (the region of the map)' },
  na: { label: 'North American (green, blue, black, double black)', name: 'North American', colors: ['#37a046', '#4b6eb9', '#2d2d3c', '#eceff1'],
    marks: ['circle', 'square', 'diamond', 'diamond2'] },
  alpine: { label: 'Alpine (blue, red, black, orange)', name: 'Alpine', colors: ['#4b6eb9', '#b44b46', '#2d2d3c', '#be7d37'],
    marks: ['circle', 'circle', 'circle', 'circle'] },
  fr: { label: 'French & Nordic (green, blue, red, black)', name: 'French & Nordic', colors: ['#37a046', '#4b6eb9', '#b44b46', '#2d2d3c'],
    marks: ['circle', 'circle', 'circle', 'circle'] },
  jp: { label: 'Japanese (green, red, black, double black)', name: 'Japanese', colors: ['#37a046', '#b44b46', '#2d2d3c', '#eceff1'],
    marks: ['circle', 'circle', 'circle', 'circle2'] },
};
function ratingKey(o) { return o.rating === 'auto' ? (R.data && RATINGS[R.data.region] ? R.data.region : 'na') : o.rating; }
const SPECIES_COLORS = {                                  // bright, unlike the green terrain; the treeline fade is turquoise
  Spruce: '#7b3fbf', Fir: '#3f51b5', Pine: '#ff9800', WhitebarkPine: '#ffd23f', Hemlock: '#c2185b', Larch: '#c6e03a',
  Sclerophyll: '#ffa726', Aspen: '#fff176', Birch: '#f48fb1', Maple: '#ef5350', Oak: '#ff7043', MountainBirch: '#ba68c8',
  SouthernBeech: '#5c6bc0', SnowGum: '#b0bec5',
};
const SPECIES_LABELS = { WhitebarkPine: 'Whitebark pine', MountainBirch: 'Mountain birch', SouthernBeech: 'Southern beech', SnowGum: 'Snow gum' };
const DIFF_COLOR = { Beginner: '#2e9e4f', Intermediate: '#2563eb', Expert: '#151515', Pro: '#151515' };   // as on the app's map
const LAYER_ALPHA = { build: 0.62, slope: 0.85, trees: 0.85 };

function hexRgb(h) { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function slopeTier(deg) { return deg < 16 ? 0 : deg < 27 ? 1 : deg < 33 ? 2 : 3; }

/* the slope of the height grid in the game's four tiers, lightly smoothed (3 x 3 mean), one cell per grid vertex */
function slopeDeg(data, heights) {
  const n = data.n, step = data.size_m / (n - 1), k = (data.hmax - data.hmin) / 65535;
  const at = (r, c) => heights[Math.min(n - 1, Math.max(0, r)) * n + Math.min(n - 1, Math.max(0, c))] * k;
  const sl = new Float32Array(n * n), out = new Float32Array(n * n);
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const gx = (at(r, c + 1) - at(r, c - 1)) / (2 * step), gz = (at(r + 1, c) - at(r - 1, c)) / (2 * step);
      sl[r * n + c] = Math.atan(Math.hypot(gx, gz)) * 180 / Math.PI;
    }
  }
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      let sum = 0, cnt = 0;
      for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
        const rr = r + dr, cc = c + dc;
        if (rr >= 0 && rr < n && cc >= 0 && cc < n) { sum += sl[rr * n + cc]; cnt++; }
      }
      out[r * n + c] = sum / cnt;
    }
  }
  return out;
}
function slopeTiers(data, heights) { return Uint8Array.from(slopeDeg(data, heights), slopeTier); }

/* a small canvas, one pixel per cell, coloured by `colorOf(index)` (a [r, g, b] or null for transparent) */
function cellCanvas(n, cells, colorOf) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = n;
  const ctx = cv.getContext('2d'), img = ctx.createImageData(n, n), px = img.data;
  for (let i = 0; i < n * n; i++) {
    const col = colorOf(i, cells[i]);
    if (col) { px[i * 4] = col[0]; px[i * 4 + 1] = col[1]; px[i * 4 + 2] = col[2]; px[i * 4 + 3] = col.length > 3 ? col[3] : 255; }
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

function buildCanvas(o) {
  if (o.buildCv) return o.buildCv;
  const red = hexRgb('#d9253a');                                          // only the ground that is too steep is painted
  o.buildCv = cellCanvas(R.data.n, o.build, (i, d) => (d > BUILD_MAX ? red : null));
  return o.buildCv;
}

function slopeCanvas(o) {
  const key = ratingKey(o);
  if (o.slopeCv[key]) return o.slopeCv[key];
  const rt = RATINGS[key], cols = rt.colors.map(hexRgb), n = R.data.n;
  o.slopeCv[key] = cellCanvas(n, o.slope, (i, tier) => cols[tier]);
  return o.slopeCv[key];
}

/* one symbol (as the game scatters over its overlay): a ring or shape in light grey with a dark edge; the extreme ones in red */
/* double black (North American, Japanese): light diagonal stripes over the black, drawn at the overlay's own resolution so they
   stay stripes at any map size */
function stripeCanvas(o) {
  const key = ratingKey(o);
  if (o.stripeCv[key] !== undefined) return o.stripeCv[key];
  if (!RATINGS[key].stripe) return (o.stripeCv[key] = null);
  const cv = document.createElement('canvas');
  cv.width = cv.height = OV_PX;
  const ctx = cv.getContext('2d'), sw = Math.min(40, Math.max(5, 45 / (R.data.size_m / OV_PX)));
  ctx.strokeStyle = '#eceff1';
  ctx.lineWidth = sw;
  for (let k = -OV_PX; k < 2 * OV_PX; k += 2 * sw * 1.4142) { ctx.beginPath(); ctx.moveTo(k, 0); ctx.lineTo(k + OV_PX, OV_PX); ctx.stroke(); }
  const n = R.data.n, mask = cellCanvas(n, o.slope, (i, tier) => (tier === 3 ? [0, 0, 0] : null));
  ctx.globalCompositeOperation = 'destination-in';
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(mask, 0, 0, OV_PX, OV_PX);
  o.stripeCv[key] = cv;
  return cv;
}
function drawMark(ctx, kind, x, y, r) {
  const one = (cx, shape, red) => {
    ctx.beginPath();
    if (shape === 'square') ctx.rect(cx - r * 0.85, y - r * 0.85, r * 1.7, r * 1.7);
    else if (shape === 'diamond') { ctx.moveTo(cx, y - r * 1.15); ctx.lineTo(cx + r * 0.8, y); ctx.lineTo(cx, y + r * 1.15); ctx.lineTo(cx - r * 0.8, y); ctx.closePath(); }
    else ctx.ellipse(cx, y, r, r * 0.72, 0, 0, Math.PI * 2);
    ctx.fillStyle = red ? '#d9363e' : '#e9edf0';
    ctx.fill();
    ctx.lineWidth = Math.max(1.2, r * 0.28);
    ctx.strokeStyle = red ? '#f4f4f4' : '#1d2027';
    ctx.stroke();
  };
  if (kind.endsWith('2')) { const s = kind.slice(0, -1) === 'diamond' ? 'diamond' : 'circle'; one(x - r * 0.75, s, true); one(x + r * 0.75, s, true); }
  else one(x, kind, false);
}
function markCanvas(o) {
  const key = ratingKey(o);
  if (o.markCv[key]) return o.markCv[key];
  const cv = document.createElement('canvas');
  cv.width = cv.height = OV_PX;
  const ctx = cv.getContext('2d'), n = R.data.n, mpp = R.data.size_m / OV_PX, marks = RATINGS[key].marks;
  const step = Math.max(24, Math.round(120 / mpp)), r = Math.min(12, Math.max(5, 26 / mpp));
  let seed = 12345;
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);   // fixed jitter: the same symbols every time
  for (let y = step / 2; y < OV_PX; y += step) {
    for (let x = step / 2; x < OV_PX; x += step) {
      const px = x + (rnd() - 0.5) * step * 0.8, py = y + (rnd() - 0.5) * step * 0.8;
      const c = Math.min(n - 1, Math.max(0, Math.round(px / OV_PX * (n - 1)))), rw = Math.min(n - 1, Math.max(0, Math.round(py / OV_PX * (n - 1))));
      drawMark(ctx, marks[o.slope[rw * n + c]], px, py, r);
    }
  }
  o.markCv[key] = cv;
  return cv;
}

function treeCanvas(o) {
  if (o.treeCv) return o.treeCv;
  const cols = o.trees.species.map((s) => hexRgb(SPECIES_COLORS[s] || '#4f8f3a'));
  const t = o.trees, n = t.n;
  // behind the species: the treeline fade in turquoise (stronger nearer the treeline); the species show as dense as the forest is
  const back = cellCanvas(n, t.fadeCells, (i, f) => (f ? [0, 200, 190, Math.round(70 + 150 * f / 255)] : null));
  const front = cellCanvas(n, t.cells, (i, k) => (k === 255 ? null : [...cols[k], Math.max(40, t.dens[i])]));
  const cv = document.createElement('canvas');
  cv.width = cv.height = n;
  const ctx = cv.getContext('2d');
  ctx.drawImage(back, 0, 0);
  ctx.drawImage(front, 0, 0);
  o.treeCv = cv;
  return o.treeCv;
}

/* the real trails and lifts, drawn as on the app's map (difficulty colours, lifts dashed red, glades grey) */
function drawTrails(ctx, lines) {
  const W = OV_PX, mpp = R.data.size_m / W;                              // metres per pixel
  const px = (m, lo, hi) => Math.min(hi, Math.max(lo, m / mpp));
  const pts = (l) => l.pts.map((p) => [p[0] * W, p[1] * W]);
  const path = (P, closed) => { ctx.beginPath(); P.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]))); if (closed) ctx.closePath(); };
  ctx.lineJoin = ctx.lineCap = 'round';
  const order = (l) => (l.kind === 'bowl' ? 0 : l.kind === 'glade' ? 1 : l.kind === 'lift' ? 3 : 2);
  [...lines].sort((a, b) => order(a) - order(b)).forEach((l) => {
    const P = pts(l);
    if (l.kind === 'lift') {
      const w = px(14, 2.5, 8);
      path(P); ctx.setLineDash([]); ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.lineWidth = w + 2.5; ctx.stroke();
      path(P); ctx.setLineDash([w * 2.2, w * 1.4]); ctx.strokeStyle = '#c0392b'; ctx.lineWidth = w; ctx.stroke();
    } else if (l.kind === 'glade') {
      const w = px(10, 2, 6);
      path(P, l.closed); ctx.setLineDash([w * 2.5, w * 1.6]); ctx.strokeStyle = '#959ba4'; ctx.lineWidth = w; ctx.stroke();
    } else {
      const w = px(22, 3, 10), col = DIFF_COLOR[l.difficulty] || '#151515', bowl = l.kind === 'bowl';
      path(P, bowl); ctx.setLineDash([]); ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.lineWidth = w + 2.5; ctx.stroke();
      if (bowl) { ctx.fillStyle = col + '33'; ctx.fill(); }
      path(P, bowl); ctx.setLineDash(l.difficulty === 'Pro' ? [w * 0.4, w * 1.1] : []); ctx.strokeStyle = col; ctx.lineWidth = w; ctx.stroke();
    }
  });
  ctx.setLineDash([]);
}

/* draw the layers that are on into the overlay canvas and show or hide the overlay mesh */
function composeOverlays() {
  const o = R && R.ov;
  if (!o) return;
  const ctx = o.ctx;
  ctx.clearRect(0, 0, OV_PX, OV_PX);
  ctx.imageSmoothingEnabled = false;                                      // clean cell borders
  if (o.on.build && o.build) { ctx.globalAlpha = LAYER_ALPHA.build; ctx.drawImage(buildCanvas(o), 0, 0, OV_PX, OV_PX); }
  if (o.on.slope && o.slope) { ctx.globalAlpha = LAYER_ALPHA.slope; ctx.drawImage(slopeCanvas(o), 0, 0, OV_PX, OV_PX); const st = stripeCanvas(o); if (st) ctx.drawImage(st, 0, 0); }
  if (o.on.trees && o.trees) { ctx.globalAlpha = LAYER_ALPHA.trees; ctx.drawImage(treeCanvas(o), 0, 0, OV_PX, OV_PX); }
  ctx.globalAlpha = 1;
  ctx.imageSmoothingEnabled = true;
  if (o.on.trails && o.lines) {                                            // what is left out in the 2D map is left out here too
    const off = new Set(R.opts.skip ? R.opts.skip() : []);
    drawTrails(ctx, o.lines.filter((l) => l.id === undefined || l.id === null || !off.has(l.id)));
  }
  o.tex.needsUpdate = true;
  R.ovMesh.visible = OV_ORDER.some((k) => o.on[k]);
  renderLegend();
}

function swatch(c) {
  return Array.isArray(c) ? `<i style="background:repeating-linear-gradient(45deg,${c[0]} 0 3px,${c[1]} 3px 6px);border-color:#9aa3ad"></i>`
    : `<i style="background:${c};${c === '#1d2027' ? 'border-color:#9aa3ad' : ''}"></i>`;
}
/* a legend symbol of a tier: its colour with its mark (as in the game's legend) */
function markSwatch(rt, i) {
  const k = rt.marks[i], col = rt.colors[i], dark = col === '#2d2d3c';
  const edge = dark ? '#e9edf0' : '#1d2027';
  const sh = (cx, shape, fill, st) => shape === 'square' ? `<rect x="${cx - 5}" y="2" width="10" height="10" fill="${fill}" stroke="${st}" stroke-width="1.2"/>`
    : shape === 'diamond' ? `<path d="M${cx} 0.5 L${cx + 4} 7 L${cx} 13.5 L${cx - 4} 7Z" fill="${fill}" stroke="${st}" stroke-width="1.2"/>`
    : `<circle cx="${cx}" cy="7" r="5.5" fill="${fill}" stroke="${st}" stroke-width="1.2"/>`;
  let inner;
  if (k.endsWith('2')) { const s = k === 'diamond2' ? 'diamond' : 'circle'; inner = sh(4.5, s, '#d9363e', '#f4f4f4') + sh(10.5, s, '#d9363e', '#f4f4f4'); }
  else if (k === 'diamond') inner = sh(7, 'diamond', '#e9edf0', '#1d2027');
  else inner = sh(7, k, col, dark ? '#e9edf0' : 'rgba(255,255,255,.4)');
  return `<svg class="mk" width="16" height="14" viewBox="0 0 16 14">${inner}</svg>`;
}
function colorSwatch(rt, i) {                                     // a thin colour bar, not a dot
  const c = rt.colors[i];
  const bg = i === 3 && rt.stripe ? `repeating-linear-gradient(45deg,${c} 0 3px,#e9edf0 3px 6px)` : c;
  return `<i class="bar" style="background:${bg}"></i>`;
}
function syncAutoLabel() {
  const o = document.querySelector('#v3dRating option[value="auto"]');
  if (o && R && R.data) o.textContent = 'Automatic (' + (RATINGS[R.data.region] || RATINGS.na).name + ', like the game)';
}
function renderLegend() {
  syncAutoLabel();
  const o = R && R.ov, box = $('v3dLegend');
  if (!o || !OV_ORDER.some((k) => o.on[k])) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  const parts = [];
  if (o.on.build) parts.push(`<div class="lg"><b>Buildability</b><span>${swatch('#d9253a')}Too steep (&gt; ${BUILD_MAX}°)</span><span class="dim">Buildable ground is left unpainted</span></div>`);
  if (o.on.slope) {
    const key = ratingKey(o), rt = RATINGS[key];
    parts.push('<div class="lg"><b>Slope difficulty' + (o.rating === 'auto' ? ` (${rt.name})` : '') + '</b>' +
      TIERS.map((n, i) => `<span>${colorSwatch(rt, i)}${n} (${TIER_RANGE[i]})</span>`).join('') + '</div>');
  }
  if (o.on.trails) {
    parts.push('<div class="lg"><b>Trails and lifts</b>' +
      ['Beginner', 'Intermediate', 'Expert'].map((d) => `<span><i class="ln" style="background:${DIFF_COLOR[d]}"></i>${d}</span>`).join('') +
      '<span><i class="ln dots"></i>Pro</span><span><i class="ln dash"></i>Lift</span></div>');
  }
  if (o.on.trees && o.trees) {
    parts.push('<div class="lg"><b>Trees' + (o.trees.real ? ' (real tree cover)' : ' (simplified)') + '</b>' + (o.trees.real ? '<span class="dim">Fainter where there are fewer real trees</span>' : '') +
      (o.trees.fade ? '<span><i style="background:#00c8be"></i>Treeline fade</span>' : '') + o.trees.species.map((s, i) => [s, o.trees.share[i]])
      .filter(([, sh]) => sh > 0.005).sort((a, b) => b[1] - a[1])
      .map(([s, sh]) => `<span>${swatch(SPECIES_COLORS[s] || '#4f8f3a')}${SPECIES_LABELS[s] || s} ${Math.round(sh * 100)}%</span>`).join('') + '</div>');
  }
  box.innerHTML = parts.join('');
  box.classList.remove('hidden');
}

/* fetch what a layer needs (first time, and again when the terrain changed), then draw */
async function updateOverlays() {
  if (!R || !R.ov) return;
  const my = gen, o = R.ov, a = window.pywebview.api;
  let failed = false;
  const fail = (k, e) => {
    failed = true;
    o.on[k] = false;
    document.querySelectorAll(`[data-ovl="${k}"]`).forEach((b) => b.classList.remove('on'));
    setStatus((e && e.message || e || 'Failed') + '', 'note');
  };
  if (o.on.build && !o.build) o.build = slopeDeg(R.data, R.heights);
  if (o.on.slope && !o.slope) o.slope = slopeTiers(R.data, R.heights);
  if (o.on.trees && !o.trees) {
    setStatus('Working out the tree species...');
    try {
      const res = await withTimeout(a.overlay_trees(R.opts.biome, R.opts.treeline, R.opts.valley, R.opts.treeSlope, R.hm, R.ho, R.opts.fade), LOAD_MS, 'The tree species');
      if (!res || !res.ok) throw new Error(res && res.error || 'No answer from the app.');
      const r = await fetch(`/blob/trees?t=${q(R.opts.token)}&v=${res.version}`);
      if (!r.ok) throw new Error('trees ' + r.status);
      const all = new Uint8Array(await r.arrayBuffer()), nn = res.n * res.n;
      const cells = all.subarray(0, nn), dens = all.subarray(nn, 2 * nn), fadeCells = all.subarray(2 * nn, 3 * nn);
      if (my === gen && R) { o.trees = { n: res.n, real: !!res.real, fade: !!res.fade, species: res.species, share: res.share, cells, dens, fadeCells }; o.treeCv = null; }
    } catch (e) { if (my === gen) fail('trees', e); }
  }
  if (o.on.trails && !o.lines) {
    setStatus('Loading the trails and lifts...');
    try {
      const res = await withTimeout(a.overlay_trails(), TOPO_MS, 'The trails and lifts');
      if (!res || !res.ok) throw new Error(res && res.error || 'No answer from the app.');
      if (my === gen && R) {
        o.lines = res.lines;
        if (!o.lines.length) { fail('trails', 'OpenStreetMap has no ski trails or lifts inside this square.'); o.lines = null; }
      }
    } catch (e) { if (my === gen) fail('trails', e); }
  }
  if (my !== gen || !R) return;
  if (!failed) setStatus('');
  composeOverlays();
}

/* show one surface on the terrain: 'terrain' or 'topo' */
function setSurface(want) {
  if (!R || !R.tex[want]) want = 'terrain';
  R.mesh.material.map = R.tex[want];
  R.mesh.material.needsUpdate = true;
  R.surface = want;
  document.querySelectorAll('[data-tex]').forEach((x) => x.classList.toggle('on', x.dataset.tex === want));
}

/* the transparent overlay mesh and its canvas (made once per open) */
function makeOverlay(scene) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = OV_PX;
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = R.renderer.capabilities.getMaxAnisotropy();
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  R.ovMesh = new THREE.Mesh(R.mesh.geometry, mat);                         // the terrain's own geometry
  R.ovMesh.visible = false;
  R.ovMesh.renderOrder = 1;
  scene.add(R.ovMesh);
  let rating = 'auto';
  try { rating = localStorage.getItem('skieo.v3d.rating') || 'auto'; } catch (e) { /* no storage: the default */ }
  if (!RATINGS[rating]) rating = 'auto';
  R.ov = { cv, ctx: cv.getContext('2d'), tex, on: { build: false, slope: false, trees: false, trails: false }, rating,
    build: null, buildCv: null, slope: null, slopeCv: {}, markCv: {}, stripeCv: {}, trees: null, treeCv: null, lines: null };
  $('v3dRating').value = rating;
  $('v3dRating').classList.add('hidden');
  document.querySelectorAll('[data-ovl]').forEach((b) => b.classList.remove('on'));
}

function heightAt(x, z) {
  const d = R.data, n = d.n, half = d.size_m / 2, step = d.size_m / (n - 1);
  const c = Math.max(0, Math.min(n - 1.001, (x + half) / step)), r = Math.max(0, Math.min(n - 1.001, (z + half) / step));
  const c0 = Math.floor(c), r0 = Math.floor(r), fc = c - c0, fr = r - r0, H = R.heights;
  const h = H[r0 * n + c0] * (1 - fc) * (1 - fr) + H[r0 * n + c0 + 1] * fc * (1 - fr)
    + H[(r0 + 1) * n + c0] * (1 - fc) * fr + H[(r0 + 1) * n + c0 + 1] * fc * fr;
  return h / 65535 * (d.hmax - d.hmin);
}

function makePin(size) {
  const grp = new THREE.Group();
  const s = size / 130;
  const red = new THREE.MeshStandardMaterial({ color: 0xb3263d, roughness: 0.5 });
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(s * 0.12, s * 0.12, s * 3.2, 12), new THREE.MeshStandardMaterial({ color: 0x3a2a1c }));
  pole.position.y = s * 1.6;
  const head = new THREE.Mesh(new THREE.SphereGeometry(s * 0.7, 20, 14), red);
  head.position.y = s * 3.4;
  grp.add(pole, head);
  return grp;
}

function setExaggeration(exag) {
  // Kept for backward compatibility but no longer used by the UI slider
  const g = R.mesh.geometry, pos = g.attributes.position.array, H = R.heights, range = R.data.hmax - R.data.hmin;
  for (let k = 0; k < H.length; k++) pos[k * 3 + 1] = H[k] / 65535 * range * exag;
  g.attributes.position.needsUpdate = true;
  g.computeVertexNormals();
  g.computeBoundingSphere();
  R.scene.remove(R.skirt);
  R.skirt.geometry.dispose();
  R.skirt.geometry = buildSkirt(R.data, H, exag);
  R.scene.add(R.skirt);
  if (R.pin && R.data.base) R.pin.position.y = heightAt(R.data.base[0], -R.data.base[1]) * exag;
  R.exag = exag;
}

export async function refresh(opts) {
  /* Reload terrain data when height modifier/offset changes while the 3D view is open */
  if (!R || !R.mesh) return;
  const my = gen;
  // Save camera state
  const camPos = R.camera.position.clone();
  const camTarget = R.controls.target.clone();
  
  // Dispose old geometry and textures
  R.mesh.geometry.dispose();
  R.skirt.geometry.dispose();
  if (R.tex.terrain) R.tex.terrain.dispose();
  
  setStatus('Updating the 3D view...');
  let res;
  try {
    const hm = opts && opts.heightModifier != null ? opts.heightModifier : 1.0;
    const ho = opts && opts.heightOffset != null ? opts.heightOffset : 0;
    res = await withTimeout(window.pywebview.api.view3d(R.opts.treeline, hm, ho), LOAD_MS, 'Updating the 3D view');
  } catch (e) {
    setStatus('Failed to update 3D view: ' + (e && e.message || e), 'note');
    return;
  }
  if (my !== gen) return;
  
  try {
    const [heights, tex] = await withTimeout(Promise.all([loadHeights(R.opts.token, res.version),
      loadTexture(`/blob/albedo?t=${q(R.opts.token)}&v=${res.version}`)]), LOAD_MS, 'Loading the terrain');
    if (my !== gen) { tex.dispose(); return; }
    
    R.data = res;
    { const o = document.querySelector('#v3dRating option[value="auto"]'); if (o) o.textContent = 'Automatic (' + (RATINGS[res.region] || RATINGS.na).name + ', like the game)'; }
    R.heights = heights;
    R.tex.terrain = tex;
    
    // Rebuild mesh with default exag 1.0 (heights already include modifier/offset)
    R.mesh.geometry = buildTerrain(res, heights, 1.0);
    setSurface(R.surface || 'terrain');
    R.skirt.geometry = buildSkirt(res, heights, 1.0);
    R.hm = hm; R.ho = ho;
    if (R.ov) {                                       // new heights: new slopes and tree zones (the trails stay)
      R.ovMesh.geometry = R.mesh.geometry;
      R.ov.build = null; R.ov.buildCv = null; R.ov.slope = null; R.ov.slopeCv = {}; R.ov.markCv = {}; R.ov.stripeCv = {}; R.ov.trees = null; R.ov.treeCv = null;
    }
    R.exag = 1.0;
    
    // Restore camera state
    R.camera.position.copy(camPos);
    R.controls.target.copy(camTarget);
    R.controls.update();
    
    // Update peak label
    $('v3dPeakLbl').textContent = 'Peak ' + (R.opts.units === 'm' ? Math.round(res.hmax) + ' m' : Math.round(res.hmax * FT).toLocaleString('en-US') + ' ft');
    $('v3dInfo').textContent = `${(res.size_m / 1000).toFixed(1)} km × ${(res.size_m / 1000).toFixed(1)} km · ` +
      (R.opts.units === 'm' ? `${Math.round(res.hmin)}–${Math.round(res.hmax)} m` :
        `${Math.round(res.hmin * FT).toLocaleString('en-US')}–${Math.round(res.hmax * FT).toLocaleString('en-US')} ft`);
    
    setStatus('');
    if (R.ov && OV_ORDER.some((k) => R.ov.on[k])) updateOverlays();
  } catch (e) {
    setStatus('Failed to update 3D view (' + (e && e.message || e) + ').', 'note');
  }
}

async function topoTexture(bbox, opts, onProgress, view) {
  /* stitch OpenTopoMap tiles over the square (lat/lon box; mercator is ~linear over a few km).
     -> { tex, missing, total }; tex is null when no tile could be loaded (offline) */
  const lon2x = (lon, z) => (lon + 180) / 360 * 256 * 2 ** z;
  const lat2y = (lat, z) => { const s = Math.sin(lat * Math.PI / 180); return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * 256 * 2 ** z; };
  let z = 17;
  while (z > 9 && (lon2x(bbox.e, z) - lon2x(bbox.w, z)) > 1700) z--;
  const x0 = lon2x(bbox.w, z), x1 = lon2x(bbox.e, z), y0 = lat2y(bbox.n, z), y1 = lat2y(bbox.s, z);
  const tx0 = Math.floor(x0 / 256), tx1 = Math.floor(x1 / 256), ty0 = Math.floor(y0 / 256), ty1 = Math.floor(y1 / 256);
  const src = document.createElement('canvas');
  src.width = (tx1 - tx0 + 1) * 256; src.height = (ty1 - ty0 + 1) * 256;
  const ctx = src.getContext('2d');
  ctx.fillStyle = '#d8d2c4'; ctx.fillRect(0, 0, src.width, src.height);
  const jobs = [];
  let done = 0, drawn = 0;
  const total = (tx1 - tx0 + 1) * (ty1 - ty0 + 1);
  for (let ty = ty0; ty <= ty1; ty++) {
    for (let tx = tx0; tx <= tx1; tx++) {
      jobs.push(new Promise((res) => {
        const im = new Image();
        im.crossOrigin = 'anonymous';                    // other port: without CORS the canvas can't become a texture
        im.onload = () => {
          if (im.naturalWidth >= 256) { ctx.drawImage(im, (tx - tx0) * 256, (ty - ty0) * 256); drawn++; }  // 1 px = no tile
          onProgress(++done, total); res();
        };
        im.onerror = () => { onProgress(++done, total); res(); };
        im.src = `${opts.tiles || ''}/tile/topo/${z}/${tx}/${ty}.png?t=${q(opts.token)}`;
      }));
    }
  }
  await Promise.race([Promise.all(jobs), new Promise((res) => setTimeout(res, TOPO_MS))]);
  if (!drawn) return { tex: null, missing: total, total };
  const out = document.createElement('canvas');
  out.width = out.height = 2048;
  const octx = out.getContext('2d');
  if (view && view.rot) {
    // a turned area: the tiles are north-up, so turn the mosaic back by the area's rotation about the area's centre
    const cx = lon2x(view.lon, z) - tx0 * 256, cy = lat2y(view.lat, z) - ty0 * 256;
    const sizePx = view.size_m / (40075016.686 * Math.cos(view.lat * Math.PI / 180) / (256 * 2 ** z));
    octx.fillStyle = '#d8d2c4'; octx.fillRect(0, 0, 2048, 2048);
    octx.translate(1024, 1024); octx.rotate(-view.rot * Math.PI / 180); octx.scale(2048 / sizePx, 2048 / sizePx);
    octx.drawImage(src, -cx, -cy);
  } else {
    octx.drawImage(src, x0 - tx0 * 256, y0 - ty0 * 256, x1 - x0, y1 - y0, 0, 0, 2048, 2048);
  }
  const t = new THREE.CanvasTexture(out);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = getRenderer().capabilities.getMaxAnisotropy();
  return { tex: t, missing: total - drawn, total };
}

function resetView() {
  const s = R.data.size_m, range = (R.data.hmax - R.data.hmin) * R.exag;
  R.controls.target.set(0, range * 0.35, 0);
  R.camera.position.set(-s * 0.62, range * 0.35 + s * 0.62, s * 0.78);
  R.controls.update();
}

function placeLabel(el, x, y, z) {
  const v = new THREE.Vector3(x, y, z).project(R.camera);
  const on = v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05;
  el.classList.toggle('hidden', !on);
  if (on) {
    el.style.left = ((v.x + 1) / 2 * window.innerWidth) + 'px';
    el.style.top = ((1 - v.y) / 2 * window.innerHeight) + 'px';
  }
}

function loop() {
  R.raf = requestAnimationFrame(loop);
  R.controls.update();
  const s = R.data.size_m;
  if (R.data.base) placeLabel($('v3dBaseLbl'), R.data.base[0], heightAt(R.data.base[0], -R.data.base[1]) + s / 130 * 4.4, -R.data.base[1]);
  placeLabel($('v3dPeakLbl'), R.data.peak[0], heightAt(R.data.peak[0], -R.data.peak[1]) + s / 250, -R.data.peak[1]);
  const v = new THREE.Vector3().subVectors(R.camera.position, R.controls.target);
  $('v3dCompass').style.transform = `rotate(${Math.atan2(v.x, v.z) * 180 / Math.PI}deg)`;
  R.renderer.render(R.scene, R.camera);
}

function onResize() {
  if (!R) return;
  const w = window.innerWidth, h = window.innerHeight;
  R.renderer.setSize(w, h);
  R.camera.aspect = w / h;
  R.camera.updateProjectionMatrix();
}

function onKey(e) { if (e.key === 'Escape') close(); }

let noteTimer = 0;
function setStatus(text, kind = 'busy') {
  /* kind: 'busy' (spinner; the scene is tinted while nothing is drawn yet) or 'note' (a message that goes away) */
  clearTimeout(noteTimer);
  const el = $('v3dLoading');
  el.classList.toggle('hidden', !text);
  el.classList.toggle('dim', !!text && kind === 'busy' && !R);
  el.classList.toggle('note', !!text && kind === 'note');
  $('v3d').classList.toggle('busy', !!text && kind === 'busy' && !R);
  $('v3dLoadingText').textContent = text || '';
  if (text && kind === 'note') noteTimer = setTimeout(() => setStatus(''), 5000);
}

export async function open(opts) {
  close();
  const my = gen;
  const fail = (msg) => { if (my !== gen) return; close(); if (opts.onError) opts.onError(msg); };
  $('v3d').classList.remove('hidden');
  $('v3dCanvas').style.visibility = 'hidden';       // no last frame of a previous terrain while loading
  $('v3dTitle').textContent = opts.name || 'Terrain';
  $('v3dInfo').textContent = '';
  $('v3dBaseLbl').classList.add('hidden');
  $('v3dPeakLbl').classList.add('hidden');
  window.addEventListener('resize', onResize);
  window.addEventListener('keydown', onKey);
  await _loadTerrain(opts);
}

async function _loadTerrain(opts) {
  const my = gen;
  const fail = (msg) => { if (my !== gen) return; close(); if (opts.onError) opts.onError(msg); };
  setStatus('Building the 3D view...');
  let res;
  try {
    const hm = opts.heightModifier != null ? opts.heightModifier : 1.0;
    const ho = opts.heightOffset != null ? opts.heightOffset : 0;
    res = await withTimeout(window.pywebview.api.view3d(opts.treeline, hm, ho), LOAD_MS, 'Building the 3D view');
  } catch (e) {
    return fail('The 3D view could not be built (' + (e && e.message || e) + '). Please try again.');
  }
  if (my !== gen) return;
  if (!res || !res.ok) return fail(res && res.error || 'No answer from the app.');
  try {
    setStatus('Loading the terrain...');
    const [heights, tex] = await withTimeout(Promise.all([loadHeights(opts.token, res.version),
      loadTexture(`/blob/albedo?t=${q(opts.token)}&v=${res.version}`)]), LOAD_MS, 'Loading the terrain');
    if (my !== gen) { tex.dispose(); return; }
    const renderer = getRenderer();
    const s = res.size_m, range = res.hmax - res.hmin;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xb6cfe2);
    scene.fog = new THREE.Fog(0xb6cfe2, s * 1.6, s * 4.5);
    const camera = new THREE.PerspectiveCamera(42, 1, s / 2000, s * 8);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    R = { renderer, scene, camera, data: res, heights, tex: { terrain: tex, topo: null }, exag: 1.0 };
    const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95, metalness: 0 });
    R.mesh = new THREE.Mesh(buildTerrain(res, heights, 1.0), mat);
    R.mesh.castShadow = R.mesh.receiveShadow = true;
    R.skirt = new THREE.Mesh(buildSkirt(res, heights, 1.0),
      new THREE.MeshStandardMaterial({ color: 0x6b4a34, roughness: 1, side: THREE.DoubleSide }));
    scene.add(R.mesh, R.skirt);
    R.hm = opts.heightModifier != null ? opts.heightModifier : 1.0;
    R.ho = opts.heightOffset != null ? opts.heightOffset : 0;
    makeOverlay(scene);
    scene.add(new THREE.HemisphereLight(0xe3eef7, 0x6a5a4c, 1.05));
    const sun = new THREE.DirectionalLight(0xfff3e0, 2.1);
    sun.position.set(-s * 0.8, range * 2 + s * 0.7, -s * 0.35);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    const sc = sun.shadow.camera;
    sc.left = sc.bottom = -s * 0.75; sc.right = sc.top = s * 0.75; sc.near = s * 0.05; sc.far = s * 4;
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = s / 3000;
    scene.add(sun, sun.target);
    if (res.base) {
      R.pin = makePin(s);
      R.pin.position.set(res.base[0], heightAt(res.base[0], -res.base[1]), -res.base[1]);
      R.pin.traverse((o) => { o.castShadow = true; });
      scene.add(R.pin);
    }
    R.controls = new OrbitControls(camera, renderer.domElement);
    R.controls.enableDamping = true;
    R.controls.dampingFactor = 0.08;
    R.controls.screenSpacePanning = false;
    R.controls.maxPolarAngle = Math.PI * 0.48;
    R.controls.minDistance = s * 0.01;
    R.controls.maxDistance = s * 3;
    R.controls.zoomSpeed = 1.2;
    onResize();
    resetView();
    document.querySelectorAll('[data-tex]').forEach((b) => b.classList.toggle('on', b.dataset.tex === 'terrain'));
    renderLegend();
    $('v3dPeakLbl').textContent = 'Peak ' + (opts.units === 'm' ? Math.round(res.hmax) + ' m' : Math.round(res.hmax * FT).toLocaleString('en-US') + ' ft');
    $('v3dBaseLbl').classList.toggle('hidden', !res.base);
    $('v3dInfo').textContent = `${(s / 1000).toFixed(1)} km × ${(s / 1000).toFixed(1)} km · ` +
      (opts.units === 'm' ? `${Math.round(res.hmin)}–${Math.round(res.hmax)} m` :
        `${Math.round(res.hmin * FT).toLocaleString('en-US')}–${Math.round(res.hmax * FT).toLocaleString('en-US')} ft`);
    R.opts = opts;
    setStatus('');
    $('v3dPeakLbl').classList.remove('hidden');
    $('v3dCanvas').style.visibility = '';
    loop();
  } catch (e) {
    fail('The 3D view could not be shown (' + (e && e.message || e) + '). Please try again.');
  }
}

export function close() {
  gen++;                                            // drops any load still under way
  setStatus('');
  $('v3d').classList.add('hidden');
  window.removeEventListener('resize', onResize);
  window.removeEventListener('keydown', onKey);
  $('v3dLegend').classList.add('hidden');
  if (!R) return;
  cancelAnimationFrame(R.raf);
  R.controls && R.controls.dispose();
  R.scene.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  });
  Object.values(R.tex).forEach((t) => t && t.dispose());
  R.renderer.renderLists.dispose();
  R = null;
}

$('v3dClose').onclick = close;
$('v3dReset').onclick = () => R && resetView();
document.querySelectorAll('[data-tex]').forEach((b) => {
  b.onclick = async () => {
    if (!R || R.topoLoading) return;
    const want = b.dataset.tex, my = gen;
    if (want === 'topo' && !R.tex.topo) {
      R.topoLoading = true;
      setStatus('Loading the topo map...');
      let got;
      try {
        got = await topoTexture(R.data.bbox, R.opts, (k, n) => { if (my === gen) setStatus(`Loading the topo map (${k} of ${n})...`); },
          { rot: R.data.rot || 0, lat: R.data.center && R.data.center[0], lon: R.data.center && R.data.center[1], size_m: R.data.size_m });
      } catch (e) {
        got = { tex: null };
      }
      if (my !== gen) { if (got.tex) got.tex.dispose(); return; }
      R.topoLoading = false;
      if (!got.tex) return setStatus('The topo map could not be loaded. Check the internet connection and try again.', 'note');
      R.tex.topo = got.tex;
      setStatus(got.missing ? 'Part of the topo map could not be loaded (no connection?).' : '', 'note');
    }
    if (!R) return;
    setSurface(want);
  };
});
document.querySelectorAll('[data-ovl]').forEach((b) => {
  b.onclick = () => {
    if (!R || !R.ov) return;
    const k = b.dataset.ovl;
    R.ov.on[k] = !R.ov.on[k];
    b.classList.toggle('on', R.ov.on[k]);
    if (k === 'slope') $('v3dRating').classList.toggle('hidden', !R.ov.on.slope);
    updateOverlays();
  };
});
$('v3dRating').onchange = () => {
  if (!R || !R.ov) return;
  R.ov.rating = $('v3dRating').value;
  try { localStorage.setItem('skieo.v3d.rating', R.ov.rating); } catch (e) { /* not saved */ }
  composeOverlays();
};
(() => {
  $('v3dRating').innerHTML = Object.entries(RATINGS).map(([k, r]) => `<option value="${k}">${r.label}</option>`).join('');
})();

window.terrain3d = { open, close, refresh };
