/* Newts' Lab — the world behind the dashboard: which renderer draws it, and one stable API for it.

   The diorama (PixiJS, static/world/engine.js) unless the PI chose the classic painted world, the URL
   says ?world=classic, or the browser can't do WebGL — then the painted Canvas-2D world below
   (createWorld: painted backdrops + layered buddy sprites). Both implement the same contract, wrapped
   by VivScene.create(): sync, setPose, setLamp, setView, goRoom, focusProject, back, viewInfo,
   highlight, layout, setAmbient, followWorker/stopFollow/following, on* callbacks. Calls made while
   the world is still booting are buffered and replayed in order. */
(function () {
'use strict';
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = t => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);
const ROLE_ORDER = ['orchestrator', 'experiment-runner', 'fresh-context-reviewer', 'overseer', 'ideation-critic', 'scoping-advocate'];
let DEPS = { toast: () => {}, runTool: () => {} };
const toast = (m) => DEPS.toast(m);
const runTool = (n, i) => DEPS.runTool(n, i);

function hash01(str) { let h = 2166136261; for (let i = 0; i < (str || '').length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 100000) / 100000; }
function hueFor(id) { return 150 + hash01(id) * 130; }

// role → base colour (muted HSL [h,s,l]); per-instance jitter keeps clones distinct
const ROLE_HSL = {
  'orchestrator': [45, 46, 68], 'experiment-runner': [168, 32, 56], 'fresh-context-reviewer': [262, 28, 66],
  'overseer': [214, 28, 60], 'ideation-critic': [320, 30, 66], 'scoping-advocate': [40, 44, 60], 'other': [120, 8, 62],
};
function roleHSL(role, jit) {
  const b = ROLE_HSL[role] || ROLE_HSL.other; jit = jit || 0;
  return [b[0] + (jit - 0.5) * 18, b[1], clamp(b[2] + (jit - 0.5) * 12, 30, 82)];
}
const hsl = (h, s, l, a) => `hsla(${h.toFixed(0)},${s.toFixed(0)}%,${l.toFixed(0)}%,${a == null ? 1 : a})`;

/* ── the world is painted backdrops (dash_assets) + layered buddy sprites (buddy/).
   A "board" overview shows the six rooms; each room has its own close-up backdrop. All
   positions are NORMALISED (0..1) over whichever backdrop is on screen. Coords were
   calibrated to the art and are refined visually. ─────────────────────────────────── */
const ROOM_KEYS = ['incubator', 'study', 'lab', 'writing', 'archive', 'margins'];
const ROOM_LABEL = { incubator: 'Incubator', study: 'The Study', lab: 'The Lab', writing: 'The Writing Room', archive: 'The Archive', margins: 'The Margins' };
const ROOM_N = { incubator: 1, study: 2, lab: 3, writing: 4, archive: 5, margins: 6 };
const ROOM_GATE = { study: 1, lab: 2, writing: 3 };
const STATE_ROOM = {
  seed: 'incubator', triaged: 'incubator',
  'lit-review': 'study', scoping: 'study', proposal: 'study',
  active: 'lab', analysis: 'lab',
  writing: 'writing', 'internal-review': 'writing',
  final: 'archive', parked: 'margins', killed: 'margins',
};
// each room is a framed BOX in world space; the camera zooms smoothly into one. The lab follows a
// roughly LEFT→RIGHT process order but is scattered above/below the line (asymmetric, organic — not
// a tidy grid), with the busy Lab larger and the Margins parked off below near the tail of the flow.
const ROOM_BOX = {
  incubator: { x: 0,    y: 120,  w: 1440, h: 800 },
  study:     { x: 1500, y: 0,    w: 1440, h: 800 },
  lab:       { x: 3000, y: 230,  w: 1590, h: 900 },
  writing:   { x: 380,  y: 1140, w: 1440, h: 800 },
  archive:   { x: 1900, y: 1230, w: 1440, h: 800 },
  margins:   { x: 3460, y: 1160, w: 1280, h: 720 },
};
const ROOM_ORDER = ['incubator', 'study', 'lab', 'writing', 'archive'];  // process flow, for connectors
// stations inside each ROOM close-up image (normalised) — the buddy's FEET land here (on the
// platform floor, not on the painted furniture). Calibrated to the art + adversarial review.
const STATIONS = {
  incubator: { seed: { x: 0.18, y: 0.52 }, reflect: { x: 0.50, y: 0.45 }, evolve: { x: 0.82, y: 0.52 }, ranking: { x: 0.27, y: 0.80 }, triage: { x: 0.58, y: 0.80 } },
  study:     { stacks: { x: 0.17, y: 0.40 }, scoping: { x: 0.80, y: 0.38 }, novelty: { x: 0.16, y: 0.70 }, decisions: { x: 0.82, y: 0.70 }, proposal: { x: 0.50, y: 0.82 }, gate: { x: 0.50, y: 0.24 } },
  lab:       { experiments: { x: 0.47, y: 0.37 }, improve: { x: 0.78, y: 0.40 }, ideate: { x: 0.17, y: 0.78 }, quality: { x: 0.50, y: 0.70 }, analysis: { x: 0.78, y: 0.80 } },
  writing:   { figures: { x: 0.17, y: 0.42 }, drafting: { x: 0.45, y: 0.38 }, review: { x: 0.70, y: 0.40 }, audit: { x: 0.20, y: 0.78 }, notes: { x: 0.62, y: 0.80 }, gate: { x: 0.90, y: 0.34 } },
  archive:   { reproduce: { x: 0.30, y: 0.42 }, writeback: { x: 0.50, y: 0.56 }, secure: { x: 0.72, y: 0.42 }, finalize: { x: 0.16, y: 0.70 }, rest: { x: 0.82, y: 0.74 } },
  margins:   { parked: { x: 0.20, y: 0.40 }, recorded: { x: 0.50, y: 0.40 }, killed: { x: 0.78, y: 0.46 }, revive: { x: 0.50, y: 0.78 } },
};
// lifecycle state → the station an idea/project stands at (within its room close-up)
const STATE_STATION = {
  seed: 'seed', triaged: 'triage', 'lit-review': 'stacks', scoping: 'scoping', proposal: 'proposal',
  active: 'experiments', analysis: 'analysis', writing: 'drafting', 'internal-review': 'review',
  final: 'rest', parked: 'parked', killed: 'killed',
};
// worker role → station (within its anchor's room; room-specific overrides below)
const ROLE_STATION = { 'ideation-critic': 'reflect', 'scoping-advocate': 'decisions', 'fresh-context-reviewer': 'review', 'experiment-runner': 'experiments', 'overseer': 'quality' };
const ROOM_ROLE_STATION = { study: { 'fresh-context-reviewer': 'stacks', 'overseer': 'novelty' }, writing: { 'overseer': 'audit' }, incubator: { 'ideation-critic': 'reflect' } };
function roomOfState(st) { return STATE_ROOM[st] || 'incubator'; }
function stationOf(room, key) { const s = STATIONS[room]; return (s && s[key]) || (s && s[Object.keys(s)[0]]) || { x: 0.5, y: 0.6 }; }
// the painted trail through each room (normalised, ordered) — creatures stroll ALONG these paths
const PATHS = {
  incubator: [[0.18, 0.56], [0.30, 0.66], [0.27, 0.80], [0.45, 0.77], [0.58, 0.80], [0.63, 0.64], [0.50, 0.55], [0.50, 0.46], [0.66, 0.55], [0.82, 0.56]],
  study:     [[0.17, 0.42], [0.16, 0.70], [0.34, 0.76], [0.50, 0.82], [0.66, 0.76], [0.82, 0.70], [0.80, 0.40], [0.62, 0.46], [0.50, 0.30], [0.36, 0.44]],
  lab:       [[0.17, 0.78], [0.34, 0.72], [0.50, 0.70], [0.50, 0.55], [0.47, 0.40], [0.62, 0.44], [0.78, 0.40], [0.78, 0.60], [0.78, 0.80], [0.60, 0.74]],
  writing:   [[0.20, 0.78], [0.18, 0.50], [0.17, 0.42], [0.34, 0.40], [0.45, 0.38], [0.58, 0.42], [0.70, 0.40], [0.66, 0.62], [0.62, 0.80], [0.84, 0.36]],
  archive:   [[0.16, 0.70], [0.28, 0.50], [0.30, 0.42], [0.42, 0.54], [0.50, 0.56], [0.60, 0.54], [0.72, 0.42], [0.78, 0.60], [0.82, 0.74]],
  margins:   [[0.20, 0.42], [0.36, 0.50], [0.50, 0.40], [0.64, 0.50], [0.78, 0.46], [0.62, 0.64], [0.50, 0.78], [0.38, 0.64]],
};
function samplePath(P, t) { const n = P.length; t = clamp(t, 0, n - 1); const i = Math.min(n - 2, Math.floor(t)), f = t - i; return { x: P[i][0] + (P[i + 1][0] - P[i][0]) * f, y: P[i][1] + (P[i + 1][1] - P[i][1]) * f }; }
function nearestT(P, x, y) { let bi = 0, bd = 1e9; for (let i = 0; i < P.length; i++) { const d = (P[i][0] - x) ** 2 + (P[i][1] - y) ** 2; if (d < bd) { bd = d; bi = i; } } return bi; }
// per-project stable hue rotation (deg) for buddy colour — bucketed for tint caching; Newt = 0 (pink)
function projectHue(id) { return id ? Math.floor(hash01(id + 'hue') * 12) * 30 : 0; }

function createWorld(canvas, opts) {
  const ctx = canvas.getContext('2d');
  const reduced = opts.reduced;
  let W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
  let theme = (opts.lamp === 'day') ? 'day' : 'night', t = 0;
  let onItem = null, onGate = null, onWorker = null, onNewt = null, onView = null, onFollow = null;
  let items = [], workforce = [], slots = { cap: 0, in_use: 0 }, gates = 0, cold = true, hot = null;
  let pose = 'idle', highlightRole = null, followId = null, ambient = true;

  function softGlow(x, y, r, color, a) { if (r <= 0) return; ctx.save(); ctx.globalCompositeOperation = 'lighter'; const g = ctx.createRadialGradient(x, y, 0, x, y, r); g.addColorStop(0, color.replace('§', a)); g.addColorStop(0.5, color.replace('§', a * 0.5)); g.addColorStop(1, color.replace('§', '0')); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill(); ctx.restore(); }
  const gl = (h, s, l) => `hsla(${h},${s}%,${l}%,§)`;
  function rrect(x, y, w, h, r) { r = Math.min(r, w / 2, h / 2); ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

  // ── assets: room close-ups (per theme) + buddy layers + walk spritesheet ──
  const imgs = {};
  function srcFor(th, name) { return `/static/assets/${th === 'day' ? 'light' : 'dark'}/${name}.jpg`; }
  function loadImg(key, src) { const im = new Image(); im.onload = () => { im._ok = true; if (reduced) drawOnce(); }; im.onerror = () => { im._err = true; }; im.src = src; imgs[key] = im; }
  function ensureTheme(th) { ROOM_KEYS.forEach(n => { const k = th + ':' + n; if (!imgs[k]) loadImg(k, srcFor(th, n)); }); }
  const buddy = {}, sheets = {};
  [['body', 'body'], ['body_closed', 'body_closed'], ['gills', 'gills'], ['tail', 'tail']].forEach(([k, f]) => { const im = new Image(); im.onload = () => { im._ok = true; if (reduced) drawOnce(); }; im.src = `/static/assets/buddy/${f}.png`; buddy[k] = im; });
  ['walk'].forEach(n => { const im = new Image(); im.onload = () => { im._ok = true; if (reduced) drawOnce(); }; im.src = `/static/assets/buddy/${n}.png`; sheets[n] = im; });
  ensureTheme('night'); ensureTheme('day');
  function backImg(name) { const a = imgs[theme + ':' + name]; if (a && a._ok) return a; const b = imgs['night:' + name]; return (b && b._ok) ? b : null; }

  // ── per-project tint caches (gills/tail hue-rotate; body washed darker; walk sheet both) ──
  const tintCache = {};
  function projDeg(id) { return id ? Math.floor(hash01(id + 'hue') * 12) * 30 : 0; }
  function washCss(deg, a) { return `hsla(${(305 + deg) % 360},62%,50%,${a})`; }
  function tintLayer(layer, deg) { const im = buddy[layer]; if (!im || !im._ok) return null; if (!deg) return im; const k = 'L' + layer + deg; if (tintCache[k]) return tintCache[k]; const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; const x = c.getContext('2d'); x.filter = `hue-rotate(${deg}deg) saturate(1.18)`; x.drawImage(im, 0, 0); tintCache[k] = c; return c; }
  // body colour is THEME-based (natural white on the dark scene; dark-brown so it pops on parchment);
  // the per-project colour lives only in the gills + tail (tintLayer). Newt is the pink one.
  // body stays the natural pale white in BOTH themes; on the light scene a thicker outline (added in
  // drawBuddy) keeps it legible. Per-project colour lives only in the gills + tail.
  function tintBody(closed) { return buddy[closed ? 'body_closed' : 'body'] || null; }
  function tintSheet(name, deg) { const im = sheets[name]; if (!im || !im._ok) return null; const k = 'S' + name + deg; if (tintCache[k]) return tintCache[k]; if (!deg) { tintCache[k] = im; return im; } const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; const x = c.getContext('2d'); x.filter = `hue-rotate(${deg}deg) saturate(1.12)`; x.drawImage(im, 0, 0); tintCache[k] = c; return c; }
  // a solid-colour silhouette of the body's alpha (cached). Stamped in a ring around the body it
  // makes a crisp, uniform LINE-ART outline (used in the light theme instead of a soft drop-shadow).
  const silCache = {};
  function bodySilhouette(closed, col) { const im = buddy[closed ? 'body_closed' : 'body']; if (!im || !im._ok) return null; const k = 'sil' + (closed ? 'c' : 'o') + col; if (silCache[k]) return silCache[k]; const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; const x = c.getContext('2d'); x.drawImage(im, 0, 0); x.globalCompositeOperation = 'source-in'; x.fillStyle = col; x.fillRect(0, 0, c.width, c.height); silCache[k] = c; return c; }
  // a layer's alpha shape is the same under any hue-tint, so silhouettes cache by layer/cell only.
  function layerSil(name) { const im = buddy[name]; if (!im || !im._ok) return null; const k = 'lsil' + name; if (silCache[k]) return silCache[k]; const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; const x = c.getContext('2d'); x.drawImage(im, 0, 0); x.globalCompositeOperation = 'source-in'; x.fillStyle = OUTLINE; x.fillRect(0, 0, c.width, c.height); silCache[k] = c; return c; }
  function walkCellSil(idx) { const sh0 = sheets.walk; if (!sh0 || !sh0._ok) return null; const k = 'wsil' + idx; if (silCache[k]) return silCache[k]; const cw = sh0.width / 4, ch = sh0.height / 2, col = idx % 4, row = (idx / 4) | 0; const c = document.createElement('canvas'); c.width = cw; c.height = ch; const x = c.getContext('2d'); x.drawImage(sh0, col * cw, row * ch, cw, ch, 0, 0, cw, ch); x.globalCompositeOperation = 'source-in'; x.fillStyle = OUTLINE; x.fillRect(0, 0, cw, ch); silCache[k] = c; return c; }
  const OUTLINE = '#2b313c';   // line-art ink (light theme)
  const RING = (cnt, draw) => { for (let i = 0; i < cnt; i++) { const aa = i / cnt * 6.2832; draw(Math.cos(aa), Math.sin(aa)); } };  // stamp a layer around a ring → uniform line-art outline

  // ── one-time sprite calibration ──────────────────────────────────────────────
  // The walk spritesheet has MORE transparent padding than the idle body image, so a walk cell drawn
  // at the idle size renders a SMALLER creature ("shrinks when moving"). Fix it deterministically:
  // measure the opaque-alpha bounding boxes and scale the walk cell up by K = (idle creature height) /
  // (walk creature height), and lock the feet using each frame's measured opaque-bottom fraction.
  function alphaBBox(img, sx, sy, sw, sh) {
    try {
      const c = document.createElement('canvas'); c.width = sw; c.height = sh; const x = c.getContext('2d');
      x.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
      const d = x.getImageData(0, 0, sw, sh).data;
      let minY = sh, maxY = -1;
      for (let py = 0; py < sh; py += 2) for (let px = 0; px < sw; px += 2) { if (d[(py * sw + px) * 4 + 3] > 24) { if (py < minY) minY = py; if (py > maxY) maxY = py; } }
      if (maxY < 0) return null;
      return { botFrac: (maxY + 1) / sh, hFrac: (maxY - minY + 1) / sh };
    } catch (e) { return null; }
  }
  let CAL = null;
  const CAL_FALLBACK = { K: 1.264, botFrac_idle: 0.854, botFrac_walk: [0.896, 0.896, 0.896, 0.896, 0.896, 0.896, 0.896, 0.896] };
  function calib() {
    if (CAL) return CAL;
    const body = buddy.body, sh = sheets.walk;
    if (!body || !body._ok || !sh || !sh._ok) return CAL_FALLBACK;   // assets not decoded yet → safe literals
    const ib = alphaBBox(body, 0, 0, body.width, body.height);
    const cw = sh.width / 4, ch = sh.height / 2, cells = [];
    for (let idx = 0; idx < 8; idx++) cells.push(alphaBBox(sh, (idx % 4) * cw, ((idx / 4) | 0) * ch, cw, ch));
    if (!ib || cells.some(c => !c)) return CAL_FALLBACK;
    // calibrate the walk scale on the MEDIAN frame height — the walking creature's typical size then
    // equals the idle creature, instead of being consistently smaller (the reported bug). Per-frame
    // feet offsets keep every frame grounded, so natural leg extension still reads without floating.
    const hsorted = cells.map(c => c.hFrac).slice().sort((a, b) => a - b);
    const medH = (hsorted[3] + hsorted[4]) / 2;
    CAL = { K: ib.hFrac / medH, botFrac_idle: ib.botFrac, botFrac_walk: cells.map(b => b.botFrac), hFrac_idle: ib.hFrac, hFrac_walk: cells.map(b => b.hFrac) };
    return CAL;
  }

  // ── world-space camera (boxes live in world units; the camera flies/zooms smoothly) ──
  const cam = { x: 0, y: 0, zoom: 0.3, q: [] };
  let camFrom = null, camT = 0, userT = -999;
  const view = { level: 'WORLD', room: null, proj: null, label: '' };
  const stack = [];
  function w2s(wx, wy) { return { x: W / 2 + (wx - cam.x) * cam.zoom, y: H / 2 + (wy - cam.y) * cam.zoom }; }
  function s2w(sx, sy) { return { x: cam.x + (sx - W / 2) / cam.zoom, y: cam.y + (sy - H / 2) / cam.zoom }; }
  function flyTo(steps) { if (reduced) { const s = steps[steps.length - 1]; cam.x = s.x; cam.y = s.y; cam.zoom = s.zoom; cam.q = []; return; } cam.q = steps.slice(); camFrom = null; camT = 0; }
  function focusOn(x, y, zoom, cinematic) { if (cinematic && !reduced) { const mid = { x: (cam.x + x) / 2, y: (cam.y + y) / 2, zoom: Math.min(cam.zoom, zoom) * 0.7, dur: 0.34 }; flyTo([mid, { x, y, zoom, dur: 0.55 }]); } else flyTo([{ x, y, zoom, dur: 0.5 }]); }
  function camUpdate(dt) { if (!cam.q.length) return; const step = cam.q[0]; if (!camFrom) { camFrom = { x: cam.x, y: cam.y, zoom: cam.zoom }; camT = 0; } camT += dt / Math.max(0.0001, step.dur); const e = smooth(camT); cam.x = lerp(camFrom.x, step.x, e); cam.y = lerp(camFrom.y, step.y, e); cam.zoom = camFrom.zoom * Math.pow(step.zoom / camFrom.zoom, e); if (camT >= 1) { cam.x = step.x; cam.y = step.y; cam.zoom = step.zoom; cam.q.shift(); camFrom = null; camT = 0; } }
  function boxesBBox() { let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const k of ROOM_KEYS) { const b = ROOM_BOX[k]; x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h); } return { x: x0, y: y0, w: x1 - x0, h: y1 - y0, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 }; }
  // The VISIBLE band = the canvas minus the top bar and the bottom HUD (command bar / legends). We
  // frame everything CENTRED in this band — not the raw canvas centre — so a zoomed room lands cleanly
  // every time (no manual panning needed). `fill` > 1 fills a touch more of the band (a slightly bigger
  // room); `maxZoom` caps the world overview so it never over-zooms on a large display.
  const VIEW = { top: 64, bot: 92, side: 20 };
  // The header + bottom command bar float OVER the canvas and are opaque — anything behind them is
  // invisible. Measure their real heights from the DOM so we frame rooms in the TRULY-visible band
  // (not the raw canvas), regardless of screen size or chrome changes. Cheap; called on nav/resize.
  function measureInsets() {
    try {
      const tb = document.querySelector('.topbar'); if (tb) { const h = tb.getBoundingClientRect().height; if (h > 4) VIEW.top = Math.round(h) + 12; }
      const cb = document.querySelector('#commandBar'); if (cb) { const r = cb.getBoundingClientRect(); if (r.height > 4) VIEW.bot = clamp(Math.round((H || window.innerHeight) - r.top) + 14, 70, 260); }
    } catch (e) {}
  }
  function bandCenterY() { return (VIEW.top + ((H || 820) - VIEW.bot)) / 2; }
  function frameBox(box, fill, maxZoom) {
    const bw = Math.max(160, (W || 1280) - VIEW.side * 2), bh = Math.max(180, (H || 820) - VIEW.top - VIEW.bot);
    const zoom = clamp(Math.min(bw / box.w, bh / box.h) * (fill || 1), 0.06, maxZoom || 2.4);
    return { x: box.x + box.w / 2, y: box.y + box.h / 2 + ((H || 820) / 2 - bandCenterY()) / zoom, zoom };
  }
  function worldFit() { return frameBox(boxesBBox(), 1.0, 0.66); }
  function fireView() { if (onView) onView(viewInfo()); }
  function fireFollow() { if (onFollow) onFollow(followId); }
  function viewInfo() { return { level: view.level, label: view.label }; }
  // follow a worker: zoom into its room (its project's lab if it has one), then keep it framed until
  // the PI pans/zooms or it despawns. Lets you watch one agent work + move around.
  function followWorker(id) {
    const w = workforce.find(x => x.worker_id === id); if (!w) return;
    const anchor = w.project ? items.find(x => x.id === w.project) : (w.idea ? items.find(x => x.id === w.idea) : null);
    if (w.project && anchor) focusProject(w.project);
    else if (anchor) goRegion(roomOfState(anchor.state));
    else if (view.level === 'WORLD') goRegion('incubator');
    followId = id; fireFollow();
  }
  function stopFollow() { if (followId !== null) { followId = null; fireFollow(); } }
  function goWorld() { followId = null; fireFollow(); view.level = 'WORLD'; view.room = null; view.proj = null; view.label = ''; stack.length = 0; userT = -999; measureInsets(); const f = worldFit(); focusOn(f.x, f.y, f.zoom, false); fireView(); }
  function goRegion(room, fromTab) { if (view.level === 'REGION' && view.room === room) return; if (!fromTab && view.level !== 'WORLD') stack.push({ ...view }); view.level = 'REGION'; view.room = room; view.proj = null; view.label = ROOM_LABEL[room]; measureInsets(); const f = frameBox(ROOM_BOX[room], 1.0); focusOn(f.x, f.y, f.zoom, true); fireView(); }
  function focusProject(id) { const o = items.find(x => x.id === id); if (!o) return; const room = roomOfState(o.state); if (view.level !== 'WORLD') stack.push({ ...view }); view.level = 'PROJECT'; view.room = room; view.proj = id; view.label = `${o.title || id} · its lab`; measureInsets(); const f = frameBox(ROOM_BOX[room], 1.0); focusOn(f.x, f.y, f.zoom, true); fireView(); }
  function back() { followId = null; fireFollow(); if (stack.length) { const v = stack.pop(); view.level = v.level; view.room = v.room; view.proj = v.proj; view.label = v.label; measureInsets(); if (v.level === 'WORLD') { const f = worldFit(); focusOn(f.x, f.y, f.zoom, true); } else { const f = frameBox(ROOM_BOX[v.room], 1.0); focusOn(f.x, f.y, f.zoom, true); } fireView(); } else goWorld(); }
  function setView(mode) { if (mode === 'gates') { const g = items.find(o => o.gate); if (g) { goRegion(roomOfState(g.state), true); return; } } goWorld(); }

  // ── entities ──
  const ents = new Map();
  function newEnt() { return { jx: 0, jy: 0, wx: 0, wy: 0, wtx: 0, wty: 0, wtimer: Math.random() * 4, moving: false, facing: 1, faceVis: 1, walkAnim: 0, blinkT: Math.random() * 4, blinkOn: 0, blink: false, phase: Math.random() * 6.28, fade: 0, init: false, dying: false, dieT: 0 }; }
  function reconcile() {
    const seen = new Set();
    items.forEach(o => { const k = 'it:' + o.id; seen.add(k); let e = ents.get(k); if (!e) { e = Object.assign(newEnt(), { kind: 'item', o, jx: hash01(o.id + 'a') - 0.5, jy: hash01(o.id + 'b') - 0.5 }); ents.set(k, e); } e.o = o; });
    workforce.forEach(w => { if (w.role === 'orchestrator' && !w.run_id) return; const k = 'wk:' + w.worker_id; seen.add(k); let e = ents.get(k); if (!e) { e = Object.assign(newEnt(), { kind: 'worker', w, jx: hash01(w.worker_id + 'a') - 0.5, jy: hash01(w.worker_id + 'b') - 0.5 }); ents.set(k, e); } e.w = w; });   // despawn is handled below (a worker that left the live set), so done workers never reach here
    for (const [k, e] of ents) { if (!seen.has(k)) { if (e.kind === 'worker' && !e.dying) { e.dying = true; e.dieT = 0; } else if (e.kind === 'item') ents.delete(k); } }
  }
  // which room + station an entity belongs to, and whether it's visible in this view
  function placeOf(e) {
    if (e.kind === 'item') {
      const o = e.o, room = roomOfState(o.state);
      const dim = view.level === 'PROJECT' && view.proj && o.id !== view.proj;
      const st = stationOf(room, STATE_STATION[o.state]); return { vis: true, dim, room, sx: st.x, sy: st.y };
    }
    const w = e.w;
    const anchor = w.project ? items.find(x => x.id === w.project) : (w.idea ? items.find(x => x.id === w.idea) : null);
    const room = anchor ? roomOfState(anchor.state) : (view.level !== 'WORLD' ? view.room : 'incubator');
    // PROJECT: only this project's crew · REGION (zoomed room): EVERY worker whose anchor lives in this
    // room, so the room is busy + alive · WORLD: hide project-crews (keep the overview uncluttered).
    if (view.level === 'PROJECT') { if (w.project !== view.proj) return { vis: false }; }
    else if (view.level === 'REGION') { if (room !== view.room) return { vis: false }; }
    else if (w.project) return { vis: false };
    let key = (ROOM_ROLE_STATION[room] && ROOM_ROLE_STATION[room][w.role]) || ROLE_STATION[w.role];
    if (!STATIONS[room] || !STATIONS[room][key]) key = Object.keys(STATIONS[room])[0];
    const st = STATIONS[room][key]; return { vis: true, room, sx: st.x, sy: st.y, worker: true };
  }

  // ── buddy renderer: layered when still, walk-spritesheet when moving ──
  function drawBuddy(cx, baseY, s, o) {
    const a = o.alpha == null ? 1 : o.alpha; if (a <= 0.02) return null;
    // constant SIZE (no size-pulsing); a tiny vertical bob carries the "breathing" instead
    const w = s, h = s, idleBob = Math.sin(t * 1.6 + (o.phase || 0)) * s * 0.012;
    const sway = reduced ? 0 : Math.sin(t * 0.8 + (o.phase || 0)) * s * 0.012;   // a slow weight-shift so a standing buddy is never frozen
    const left = cx - w / 2 + sway, top = baseY - h - (o.bob || 0) - idleBob;
    const day = theme === 'day', glowK = day ? 1 : 0.66, orad = Math.max(1.3, s * 0.017);
    ctx.save(); ctx.globalAlpha = a;
    if (o.glow) { ctx.save(); ctx.globalCompositeOperation = 'lighter'; const hh = (305 + (o.deg || 0)) % 360; const rg = ctx.createRadialGradient(cx, top + h * 0.5, 0, cx, top + h * 0.5, w * 0.62); rg.addColorStop(0, `hsla(${hh},80%,62%,${0.24 * o.glow * glowK})`); rg.addColorStop(1, 'rgba(0,0,0,0)'); ctx.fillStyle = rg; ctx.fillRect(left - w * 0.5, top - h * 0.4, w * 2, h * 1.8); ctx.restore(); }
    ctx.save(); ctx.globalAlpha = a * 0.3; ctx.fillStyle = '#000'; ctx.beginPath(); ctx.ellipse(cx, baseY, s * 0.24, s * 0.055, 0, 0, 6.28); ctx.fill(); ctx.restore();
    if (!day) ctx.filter = 'brightness(0.88)';   // the white body glares on the dark scene — ease it down (reset by the outer restore)
    if (o.moving && sheets.walk && sheets.walk._ok) {
      // walk cell calibrated to the idle creature size (K≈1.26) + feet aligned, so moving never shrinks
      const sh = tintSheet('walk', o.deg) || sheets.walk, cw = sh.width / 4, ch = sh.height / 2, idx = ((o.walkAnim | 0) % 8 + 8) % 8, col = idx % 4, row = (idx / 4) | 0;
      const C = calib();                       // K + per-frame feet offsets, measured from the assets (size-matched to idle)
      const wc = o.walkAnim * Math.PI / 2;     // walk-cycle phase: ~2 footfalls per 8-frame stride
      const stride = reduced ? 0 : 1;          // master switch for walk-coupled motion (off under reduced-motion)
      const WALK_GAIN = 1.04;                  // K matches idle only at the median stride frame, so most of the cycle reads a hair short — a slight uniform bump evens it out
      const Hw = s * C.K * WALK_GAIN, fw = Hw * (cw / ch);
      const bounce = stride * Hw * 0.035 * Math.abs(Math.sin(wc));   // a little spring: lift at apex, zero at footfall (feet stay glued)
      const topw = baseY - (o.bob || 0) - idleBob - s * (1 - C.botFrac_idle) - C.botFrac_walk[idx] * Hw - bounce;
      // a little dust kicked up behind the trailing foot (procedural; subtle)
      if (!reduced && ambient) { ctx.save(); ctx.filter = 'none'; const da = a * (0.15 + 0.12 * Math.abs(Math.sin(o.walkAnim * 0.9))), ddx = -(o.facing || 1) * s * 0.17; ctx.fillStyle = day ? '#8a7250' : '#9fcfd6'; ctx.globalAlpha = da; ctx.beginPath(); ctx.ellipse(cx + ddx, baseY - s * 0.005, s * 0.07, s * 0.024, 0, 0, 6.28); ctx.fill(); ctx.globalAlpha = da * 0.6; ctx.beginPath(); ctx.ellipse(cx + ddx * 1.7, baseY - s * 0.02, s * 0.045, s * 0.017, 0, 0, 6.28); ctx.fill(); ctx.restore(); }
      // smooth turn: scale X by faceVis (∈[-1,1]); the squash through 0 reads as a turn, never an instant flip
      const fs = (o.faceScale == null ? (o.facing || 1) : o.faceScale), m = fs < 0 ? Math.min(fs, -0.16) : Math.max(fs, 0.16);
      // squash & stretch, anchored at the on-ground line so the feet never move: stretch at apex, squash at contact.
      const squish = stride * 0.06 * Math.sin(wc), sy = 1 + squish, sx = m * (1 - 0.045 * Math.sin(wc) * stride);
      const footY = baseY - (o.bob || 0) - idleBob - s * (1 - C.botFrac_idle);
      ctx.save(); ctx.translate(cx, footY); ctx.scale(sx, sy); ctx.translate(-cx, -footY);
      if (day) { const sil = walkCellSil(idx); if (sil) RING(10, (dx, dy) => ctx.drawImage(sil, cx - fw / 2 + dx * orad, topw + dy * orad, fw, Hw)); }   // crisp line-art edge
      ctx.drawImage(sh, col * cw, row * ch, cw, ch, cx - fw / 2, topw, fw, Hw); ctx.restore();
    } else {
      // the standalone gills/tail layers are each centred in their frame — re-register them to the
      // body (match full.png): scale + reposition about a pivot, with the sway baked on top. In the
      // light theme each layer is given a uniform line-art outline (a ring of dark silhouette stamps).
      const tail = tintLayer('tail', o.deg), gills = tintLayer('gills', o.deg), body = tintBody(o.closed);
      const place = (img, sil, k, pxf, pyf, dxf, dyf, ang) => { if (!img) return; const px = left + pxf * w, py = top + pyf * h; ctx.save(); ctx.translate(dxf * w, dyf * h); ctx.translate(px, py); ctx.rotate(ang || 0); ctx.scale(k, k); ctx.translate(-px, -py); if (day && sil) RING(10, (dx, dy) => ctx.drawImage(sil, left + dx * orad, top + dy * orad, w, h)); ctx.drawImage(img, left, top, w, h); ctx.restore(); };
      place(tail, layerSil('tail'), 0.60, 0.42, 0.66, -0.06, 0.16, Math.sin(t * 1.7 + (o.phase || 0)) * 0.065);   // tucked at the lower-left hip
      place(gills, layerSil('gills'), 0.84, 0.50, 0.32, 0.0, -0.15, Math.sin(t * 2.3 + (o.phase || 0)) * 0.05);    // fanned beside the head (drawn under the body, so scale up to clear it; nudged up to sit at the head, not the neck)
      if (body) { if (day) { const sil = bodySilhouette(o.closed, OUTLINE); if (sil) RING(12, (dx, dy) => ctx.drawImage(sil, left + dx * orad, top + dy * orad, w, h)); } ctx.drawImage(body, left, top, w, h); }
      else { const hh = (305 + (o.deg || 0)) % 360; ctx.fillStyle = `hsl(${hh},55%,66%)`; ctx.beginPath(); ctx.arc(cx, top + h * 0.5, s * 0.32, 0, 6.28); ctx.fill(); }
    }
    ctx.restore();
    return { bx: cx, by: top + h * 0.5, r: s * 0.5 };
  }

  // ── ambient motes ──
  const SPORES = reduced ? 0 : 40, spores = [];
  for (let i = 0; i < SPORES; i++) spores.push({ x: Math.random(), y: Math.random(), d: 0.3 + Math.random() * 0.7, ph: Math.random() * 6.28, sp: 0.003 + Math.random() * 0.008 });

  const newt = { idle: 0, blink: false, blinkT: 0, blinkOn: 0, glowP: 0.5, bounce: 0, look: 0 };
  let regenT = 0, hits = [];
  function setPoseW(p) { if (p === pose) return; if (p === 'regen') regenT = 1.2; if (p === 'success') newt.bounce = 1; pose = p; }

  const BUDDY_WH = 150;
  function update(dt) {
    t += dt; camUpdate(dt); reconcile();
    for (const [, e] of ents) {
      const pl = placeOf(e); e._vis = !!pl.vis; e._dim = !!pl.dim; e._room = pl.room; e._worker = !!pl.worker;
      if (!pl.vis) continue;
      // stroll ALONG the painted trail: each buddy keeps a home spot on the path and wanders a window
      const P = PATHS[pl.room];
      if (P) {
        if (!e.pathInit || e._proom !== pl.room) { e.homeT = clamp(nearestT(P, pl.sx, pl.sy) + e.jx * 1.4, 0, P.length - 1); e.pt = e.homeT; e.targetT = e.homeT; e.pathInit = true; e._proom = pl.room; }
        const restless = (e.w && e.w.status === 'working') || (e.o && e.o.live);   // busy buddies roam more
        e.wtimer -= dt; if (e.wtimer < 0) { e.wtimer = (restless ? 1.4 : 2.4) + Math.random() * (restless ? 3.0 : 4.2); e.targetT = clamp(e.homeT + (Math.random() - 0.5) * (restless ? 4.2 : 3.2), 0, P.length - 1); }
        const dpt = e.targetT - e.pt; e.moving = Math.abs(dpt) > 0.05;
        if (e.moving) { const step = Math.sign(dpt) * Math.min(Math.abs(dpt), dt * 1.25); e.pt += step; e.walkAnim += dt * 9; const p0 = samplePath(P, e.pt), p1 = samplePath(P, e.pt + 0.05 * Math.sign(step || 1)); e.facing = (p1.x - p0.x) < 0 ? -1 : 1; }
        e.faceVis = lerp(e.faceVis == null ? e.facing : e.faceVis, e.facing, Math.min(1, dt * 9));   // smooth turn (no instant flip)
        const pos = samplePath(P, e.pt); e._nx = pos.x; e._ny = pos.y;
      } else { e._nx = pl.sx; e._ny = pl.sy; e.moving = false; }
      e.blinkT -= dt; if (e.blinkT < 0) { e.blinkT = 2.6 + Math.random() * 3.6; e.blinkOn = 0.13; } if (e.blinkOn > 0) e.blinkOn -= dt; e.blink = !reduced && e.blinkOn > 0;
      // reduced-motion has no rAF loop (one drawOnce per ~1.5s sync), so advance the dissolve in a
      // single step — else a finished worker lingers half-faded for ~90s. Blink is disabled above too.
      if (e.dying) { e.dieT += reduced ? 1.0 : dt; if (e.dieT >= 1.0 && e.w) ents.delete('wk:' + e.w.worker_id); }
      e.fade = lerp(e.fade, 1, dt * 3); if (!e.init) { e.fade = 1; e.init = true; }
    }
    newt.idle += dt; newt.bounce = lerp(newt.bounce, 0, dt * 2.4);
    newt.look = Math.sin(newt.idle * 0.5) * 0.5;
    newt.blinkT -= dt; if (newt.blinkT < 0) { newt.blinkT = 2 + Math.random() * 3; newt.blinkOn = 0.13; } if (newt.blinkOn > 0) newt.blinkOn -= dt; newt.blink = !reduced && newt.blinkOn > 0;
    newt.glowP = lerp(newt.glowP, (POSE_PARAMS[pose] || POSE_PARAMS.idle).glow, dt * 2);
    if (regenT > 0) regenT -= dt;
    for (const sp of spores) { sp.y += sp.sp * dt * 8; sp.x += Math.sin(t * 0.2 + sp.ph) * 0.0003; if (sp.y > 1.05) { sp.y = -0.05; sp.x = Math.random(); } }
    // follow camera: gently keep the followed worker framed in the visible band
    if (followId && !cam.q.length) {
      const fe = ents.get('wk:' + followId);
      if (fe && fe._vis && ROOM_BOX[fe._room]) {
        const box = ROOM_BOX[fe._room], wx = box.x + (fe._nx == null ? 0.5 : fe._nx) * box.w, wy = box.y + (fe._ny == null ? 0.6 : fe._ny) * box.h;
        const ty = wy + ((H || 820) / 2 - bandCenterY()) / cam.zoom, k = Math.min(1, dt * 2.6);
        cam.x = lerp(cam.x, wx, k); cam.y = lerp(cam.y, ty, k);
      } else { followId = null; fireFollow(); }
    }
    if (view.level === 'WORLD' && !cam.q.length && (t - userT) > 4) { const f = worldFit(); if (Math.abs(f.zoom - cam.zoom) > 0.001 || Math.abs(f.x - cam.x) > 1 || Math.abs(f.y - cam.y) > 1) focusOn(f.x, f.y, f.zoom, false); }
  }

  // (the code-drawn Canvas2D rooms are gone: the diorama world lives in static/world/)
  function drawBox(key) {
    const b = ROOM_BOX[key], tl = w2s(b.x, b.y), brc = w2s(b.x + b.w, b.y + b.h);
    const x = tl.x, y = tl.y, w = brc.x - tl.x, h = brc.y - tl.y;
    if (x > W + 60 || brc.x < -60 || y > H + 60 || brc.y < -60) return;
    const im = backImg(key), rad = Math.max(7, 20 * cam.zoom);
    // outer glow for a gate-waiting room
    if (ROOM_GATE[key] && items.some(o => o.gate && roomOfState(o.state) === key)) { const g = ROOM_GATE[key]; softGlow(x + w / 2, y + h / 2, Math.max(w, h) * 0.6, gl(g === 3 ? 12 : 45, 80, 60), 0.16 + 0.06 * Math.sin(t * 3)); }
    ctx.save(); rrect(x, y, w, h, rad); ctx.clip();
    if (im) { const s = Math.max(w / im.width, h / im.height), iw = im.width * s, ih = im.height * s; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(im, x + (w - iw) / 2, y + (h - ih) / 2, iw, ih); }
    else { ctx.fillStyle = theme === 'day' ? '#e9e0ca' : '#0a121a'; ctx.fillRect(x, y, w, h); }
    ctx.restore();
    rrect(x, y, w, h, rad); ctx.lineWidth = Math.max(1, 2 * cam.zoom); ctx.strokeStyle = theme === 'day' ? 'rgba(96,74,42,0.5)' : 'rgba(150,190,200,0.32)'; ctx.stroke();
    // number + name plate (top-left)
    const bs = Math.max(10, 15 * cam.zoom), bx0 = x + bs + 12, by0 = y + bs + 12;
    ctx.save(); ctx.globalAlpha = 0.95; ctx.beginPath(); ctx.arc(bx0, by0, bs, 0, 6.28); ctx.fillStyle = theme === 'day' ? 'rgba(60,44,22,0.82)' : 'rgba(10,16,22,0.7)'; ctx.fill(); ctx.strokeStyle = theme === 'day' ? 'rgba(120,90,50,0.8)' : 'rgba(160,200,210,0.55)'; ctx.lineWidth = 1.2; ctx.stroke();
    ctx.fillStyle = theme === 'day' ? '#f4ecda' : '#dff0f2'; ctx.font = `${bs * 1.1}px ${getSerif()}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(ROOM_N[key], bx0, by0 + 1);
    // the parchment room art already carries a hand-lettered title, so only label in the dark theme
    if (theme !== 'day' && cam.zoom > 0.16) { ctx.textAlign = 'left'; ctx.font = `600 ${Math.max(10, 14 * cam.zoom)}px ${getRound()}`; ctx.fillStyle = 'rgba(223,240,242,0.9)'; ctx.shadowColor = 'rgba(0,0,0,0.6)'; ctx.shadowBlur = 3; ctx.fillText(ROOM_LABEL[key].toUpperCase(), bx0 + bs + 8, by0 + 1); ctx.shadowBlur = 0; }
    ctx.restore();
  }

  // faint glowing links between consecutive rooms — reads the lab as one (non-linear) process flow.
  // Small motes drift ALONG each link (incubator → … → archive), so the whole pipeline feels alive.
  const qbez = (a, c, b, u) => ({ x: (1 - u) * (1 - u) * a.x + 2 * (1 - u) * u * c.x + u * u * b.x, y: (1 - u) * (1 - u) * a.y + 2 * (1 - u) * u * c.y + u * u * b.y });
  function drawConnectors() {
    // 'lighter' compositing glows beautifully on the dark scene but ADDS to the near-white day
    // background → invisible. In the light theme we paint the corridors normally (source-over) with a
    // darker, earthy ink, and draw the drifting motes as small solid dots instead of additive glows.
    const day = theme === 'day';
    ctx.save(); ctx.lineCap = 'round'; ctx.globalCompositeOperation = day ? 'source-over' : 'lighter';
    const col = day ? 'rgba(86,62,32,0.82)' : 'rgba(120,185,195,0.42)';
    const moteCol = day ? 'rgba(132,96,44,§)' : 'rgba(150,225,235,§)';
    for (let i = 0; i < ROOM_ORDER.length - 1; i++) {
      const a = ROOM_BOX[ROOM_ORDER[i]], b = ROOM_BOX[ROOM_ORDER[i + 1]];
      const p1 = w2s(a.x + a.w * 0.92, a.y + a.h * 0.66), p2 = w2s(b.x + b.w * 0.08, b.y + b.h * 0.66);
      const mid = { x: (p1.x + p2.x) / 2, y: Math.max(p1.y, p2.y) + 46 * cam.zoom };
      // a soft parchment-coloured "underlay" in the light theme makes the ink path read as a worn trail
      if (day) { ctx.save(); ctx.strokeStyle = 'rgba(244,238,225,0.85)'; ctx.lineWidth = Math.max(4, 15 * cam.zoom); ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.quadraticCurveTo(mid.x, mid.y, p2.x, p2.y); ctx.stroke(); ctx.restore(); }
      ctx.strokeStyle = col; ctx.lineWidth = Math.max(day ? 2 : 1.5, (day ? 6 : 9) * cam.zoom);
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.quadraticCurveTo(mid.x, mid.y, p2.x, p2.y); ctx.stroke();
      if (!reduced) for (let m = 0; m < 2; m++) {                                  // two motes per link, offset in phase
        const u = ((t * 0.16 + i * 0.27 + m * 0.5) % 1), pt = qbez(p1, mid, p2, u), fade = Math.sin(u * Math.PI);
        if (day) { ctx.save(); ctx.globalAlpha = 0.7 * fade; ctx.fillStyle = moteCol.replace('§', '1'); ctx.beginPath(); ctx.arc(pt.x, pt.y, Math.max(2, 5 * cam.zoom), 0, 6.2832); ctx.fill(); ctx.restore(); }
        else softGlow(pt.x, pt.y, Math.max(3, 9 * cam.zoom), moteCol, 0.5 * fade);
      }
    }
    ctx.restore();
  }

  // hover feedback: a soft ring + a floating name pill, so a buddy is identifiable at ANY zoom
  function drawHoverRing(d) {
    ctx.save();
    ctx.strokeStyle = theme === 'day' ? 'rgba(40,52,72,0.55)' : 'rgba(185,225,230,0.7)'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(d.x, d.y, Math.max(14, d.r * 1.04), 0, 6.2832); ctx.stroke();
    const label = String(d.name || ''); ctx.font = `600 13px ${getRound()}`;
    const tw = ctx.measureText(label).width, pad = 9, pw = tw + pad * 2, ph = 21, px = d.x - pw / 2, py = d.y - Math.max(14, d.r) - 28;
    ctx.fillStyle = theme === 'day' ? 'rgba(255,255,255,0.94)' : 'rgba(9,14,20,0.88)'; rrect(px, py, pw, ph, 7); ctx.fill();
    ctx.strokeStyle = theme === 'day' ? 'rgba(40,52,72,0.18)' : 'rgba(185,225,230,0.28)'; ctx.lineWidth = 1; rrect(px, py, pw, ph, 7); ctx.stroke();
    ctx.fillStyle = theme === 'day' ? '#21242b' : '#e8f3f4'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label, d.x, py + ph / 2 + 0.5);
    ctx.restore();
  }

  function drawNewt() {
    const tp = POSE_PARAMS[pose] || POSE_PARAMS.idle, base = clamp(Math.min(W, H) * 0.2, 92, 168);
    const nx = W * 0.5, ny = H - 44 - newt.bounce * base * 0.12;
    ctx.save(); ctx.globalCompositeOperation = 'lighter'; softGlow(nx, ny - base * 0.5, base * 1.95, gl(tp.hue, 48, 60), 0.10 + 0.13 * newt.glowP); ctx.restore();
    const pool = ctx.createRadialGradient(nx, ny - base * 0.02, 0, nx, ny - base * 0.02, base * 0.9);
    pool.addColorStop(0, hsl(tp.hue, 42, theme === 'day' ? 56 : 24, 0.5)); pool.addColorStop(1, hsl(tp.hue, 42, 10, 0));
    ctx.fillStyle = pool; ctx.beginPath(); ctx.ellipse(nx, ny - base * 0.02, base * 0.8, base * 0.16, 0, 0, 6.28); ctx.fill();
    const hb = drawBuddy(nx, ny, base, { deg: 0, glow: 0.75 + newt.glowP * 0.5, alpha: 1, blink: newt.blink, closed: pose === 'sleep' || newt.blink, phase: 0.5, bob: 0, moving: false });
    if (hb) { hits.push({ sx: hb.bx, sy: hb.by, r: Math.max(44, base * 0.55), kind: 'newt' }); if (hot && hot.kind === 'newt') drawHoverRing({ x: hb.bx, y: hb.by, r: base * 0.5, name: 'Newt · orchestrator' }); }
    // (no canvas name label — the command bar names Newt; avoids colliding with the speech bubble)
  }

  function paint() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    if (theme === 'day') { bg.addColorStop(0, '#f7f7f4'); bg.addColorStop(1, '#edece7'); } else { bg.addColorStop(0, '#070b11'); bg.addColorStop(1, '#04070c'); }
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
    drawConnectors();
    for (const k of ROOM_KEYS) drawBox(k);
    hits = []; let hoverDraw = null;
    const zoomedIn = cam.zoom > 0.5;
    const list = [...ents.values()].filter(e => e.init && (e._vis || e.dying));
    // world-y sort (uses the path position)
    list.forEach(e => { const b = ROOM_BOX[e._room || roomOfState(e.o ? e.o.state : 'lab')]; e._wy = (b ? b.y + (e._ny == null ? 0.6 : e._ny) * b.h : 0); });
    list.sort((a, b) => a._wy - b._wy);
    list.forEach(e => {
      if (!e._vis && !e.dying) return;
      const b = ROOM_BOX[e._room]; if (!b) return;
      const wx = b.x + (e._nx == null ? 0.5 : e._nx) * b.w, wy = b.y + (e._ny == null ? 0.6 : e._ny) * b.h;
      const p = w2s(wx, wy); const dieK = e.dying ? clamp(1 - e.dieT, 0, 1) : 1;
      if (p.x < -120 || p.x > W + 120 || p.y < -120 || p.y > H + 140) return;
      if (e.kind === 'item') {
        const o = e.o, deg = projDeg(o.id), s = BUDDY_WH * cam.zoom * (o.hasProject ? 1.05 : 0.9);
        const bob = (o.live && !e.moving) ? Math.abs(Math.sin(t * 3 + e.phase)) * s * 0.03 : 0;
        const hb = drawBuddy(p.x, p.y, s, { deg: o.dead ? 0 : deg, glow: o.dead ? 0.12 : (o.live ? 1 : 0.55), alpha: (e._dim ? 0.55 : 1) * dieK * (o.dead ? 0.68 : 1), blink: e.blink || o.parked, closed: (e.blink || o.parked) && !e.moving, phase: e.phase, bob, moving: e.moving, walkAnim: e.walkAnim, facing: e.facing, faceScale: e.faceVis });
        if (o.gate && hb) softGlow(hb.bx, hb.by - s * 0.3, s * 0.7, gl(o.gate === 3 ? 12 : 45, 82, 64), 0.5);
        if (zoomedIn) {
          ctx.save(); ctx.shadowColor = 'rgba(0,0,0,0.7)'; ctx.shadowBlur = 4; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
          ctx.fillStyle = (theme === 'day' ? `hsla(28,32%,16%,${e._dim ? 0.66 : 0.97})` : `hsla(44,40%,94%,${e._dim ? 0.6 : 0.97})`); ctx.font = `${Math.max(10, s * 0.13)}px ${getRound()}`; ctx.fillText(o.title || o.id, p.x, p.y + s * 0.1);
          if (o.hasProject && o.nWorkers && !(view.level === 'PROJECT' && view.proj === o.id)) { ctx.fillStyle = `hsla(185,60%,80%,${e._dim ? 0.62 : 0.96})`; ctx.font = `${Math.max(8, s * 0.11)}px ${getRound()}`; ctx.fillText('▸ ' + o.nWorkers + ' inside', p.x, p.y + s * 0.26); }
          ctx.restore();
        }
        if (hb && !e._dim) { hits.push({ sx: hb.bx, sy: hb.by, r: Math.max(18, s * 0.5), kind: 'item', id: o.id }); if (hot && hot.kind === 'item' && hot.id === o.id) hoverDraw = { x: hb.bx, y: hb.by, r: s * 0.5, name: o.title || o.id }; }
      } else {
        const w = e.w, role = ROLE_ORDER.includes(w.role) ? w.role : 'other';
        const anchor = w.project ? items.find(x => x.id === w.project) : (w.idea ? items.find(x => x.id === w.idea) : null);
        const deg = projDeg(anchor ? anchor.id : (w.project || w.idea || w.worker_id));
        const dimHL = (highlightRole && highlightRole !== role) ? 0.5 : 1, s = BUDDY_WH * cam.zoom * 0.8 * dieK;
        const hb = drawBuddy(p.x, p.y, s, { deg, glow: w.status === 'working' ? 0.85 : 0.4, alpha: dimHL * (e.dying ? dieK : e.fade), blink: e.blink, closed: e.blink && !e.moving, phase: e.phase, bob: (w.status === 'working' && !e.moving) ? Math.abs(Math.sin(t * 2.5 + e.phase)) * s * 0.025 : 0, moving: e.moving, walkAnim: e.walkAnim, facing: e.facing, faceScale: e.faceVis });
        if (hb) { const rc = roleHSL(role, 0); ctx.fillStyle = hsl(rc[0], rc[1] + 16, rc[2] + 8, dimHL); ctx.beginPath(); ctx.arc(hb.bx + s * 0.3, hb.by - s * 0.36, Math.max(1.6, s * 0.045), 0, 6.28); ctx.fill(); }
        if (hb && !e.dying) { hits.push({ sx: hb.bx, sy: hb.by, r: Math.max(16, s * 0.5), kind: 'worker', id: w.worker_id }); if (hot && hot.kind === 'worker' && hot.id === w.worker_id) hoverDraw = { x: hb.bx, y: hb.by, r: s * 0.5, name: w.worker_id }; }
      }
    });
    if (hoverDraw) drawHoverRing(hoverDraw);
    if (spores.length && ambient) { ctx.save(); ctx.globalCompositeOperation = 'lighter'; for (const sp of spores) softGlow(sp.x * W, sp.y * H, 2 + sp.d * 5, gl(theme === 'day' ? 45 : 190, 30, theme === 'day' ? 60 : 80), 0.08 * sp.d); ctx.restore(); }
    drawNewt();
    const v = ctx.createRadialGradient(W / 2, H * 0.46, Math.min(W, H) * 0.42, W / 2, H * 0.5, Math.max(W, H) * 0.85);
    v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, theme === 'day' ? 'rgba(70,52,18,0.14)' : 'rgba(0,0,0,0.36)');
    ctx.fillStyle = v; ctx.fillRect(0, 0, W, H);
    canvas.classList.toggle('is-hit', !!hot);
  }

  function resize() { W = canvas.clientWidth || window.innerWidth; H = canvas.clientHeight || window.innerHeight; canvas.width = W * dpr; canvas.height = H * dpr; measureInsets(); if (!cam.q.length && view.level === 'WORLD') { const f = worldFit(); cam.x = f.x; cam.y = f.y; cam.zoom = f.zoom; } }
  resize(); window.addEventListener('resize', () => { resize(); if (reduced) drawOnce(); });
  let raf = 0, paused = false, last = performance.now();
  function frame(now) { if (paused) return; const dt = Math.min((now - last) / 1000, 0.05); last = now; update(dt); paint(); raf = requestAnimationFrame(frame); }
  function drawOnce() { update(0.016); paint(); }
  function startLoop() { if (reduced) { drawOnce(); return; } paused = false; last = performance.now(); raf = requestAnimationFrame(frame); }
  function stopLoop() { paused = true; cancelAnimationFrame(raf); }
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopLoop(); else startLoop(); });

  // ── interaction ──
  function toCanvas(ev) { const r = canvas.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; }
  function pick(p) {
    let best = null, bd = 1e9;
    for (const h of hits) { if (h.rect) continue; const d = Math.hypot(p.x - h.sx, p.y - h.sy); if (d < h.r && d < bd) { bd = d; best = h; } }
    if (best) return best;   // creatures win over the furniture behind them
    return null;
  }
  function boxAt(p) { const wpt = s2w(p.x, p.y); for (const k of ROOM_KEYS) { const b = ROOM_BOX[k]; if (wpt.x >= b.x && wpt.x <= b.x + b.w && wpt.y >= b.y && wpt.y <= b.y + b.h) return k; } return null; }
  function clampCam() { const b = boxesBBox(); cam.x = clamp(cam.x, b.x - 400, b.x + b.w + 400); cam.y = clamp(cam.y, b.y - 400, b.y + b.h + 400); }
  let down = null, panned = false;
  canvas.addEventListener('pointerdown', ev => { down = toCanvas(ev); panned = false; try { canvas.setPointerCapture(ev.pointerId); } catch (e) {} });
  canvas.addEventListener('pointerleave', () => { if (hot) { hot = null; if (reduced) drawOnce(); } });   // clear a stuck hover ring/cursor when the cursor leaves the canvas
  canvas.addEventListener('pointermove', ev => { const p = toCanvas(ev); if (down) { const dx = p.x - down.x, dy = p.y - down.y; if (panned || Math.hypot(dx, dy) > 6) { panned = true; if (followId !== null) { followId = null; fireFollow(); } cam.q = []; camFrom = null; cam.x -= dx / cam.zoom; cam.y -= dy / cam.zoom; clampCam(); down = p; userT = t; if (reduced) drawOnce(); } } else { hot = pick(p); if (reduced) drawOnce(); } });
  canvas.addEventListener('pointerup', ev => { const p = toCanvas(ev); if (down && !panned) { const h = pick(p); if (h) { if (h.kind === 'item') { const o = items.find(x => x.id === h.id); if (o && o.has_project) { userT = t; focusProject(h.id); } else if (onItem) onItem(h.id); } else if (h.kind === 'worker' && onWorker) onWorker(h.id); else if (h.kind === 'newt' && onNewt) onNewt(); } else { const rk = boxAt(p); if (rk && !(view.level !== 'WORLD' && view.room === rk)) { userT = t; goRegion(rk); } } } down = null; panned = false; });
  canvas.addEventListener('wheel', ev => { ev.preventDefault(); if (followId !== null) { followId = null; fireFollow(); } const cp = toCanvas(ev), before = s2w(cp.x, cp.y); cam.q = []; camFrom = null; cam.zoom = clamp(cam.zoom * (1 + (ev.deltaY < 0 ? 0.14 : -0.14)), 0.06, 2.6); const after = w2s(before.x, before.y); cam.x += (after.x - cp.x) / cam.zoom; cam.y += (after.y - cp.y) / cam.zoom; clampCam(); userT = t; if (reduced) drawOnce(); }, { passive: false });

  if (reduced) drawOnce(); else startLoop();

  return {
    kind: 'canvas2d',
    sync(s) {
      items = (s.items || []).map(it => ({ id: it.id, title: it.title || it.id, state: it.state, has_project: !!it.has_project, hasProject: !!it.has_project, hasPaper: !!it.has_paper, gate: it.gate || 0, nWorkers: it.n_workers || 0, n_workers: it.n_workers || 0, loop_active: !!it.loop_active, inflight: it.inflight || [], live: (it.inflight || []).some(r => r.state !== 'stalled') && (it.inflight || []).length > 0, dead: it.state === 'killed', parked: it.state === 'parked' }));
      // Exclude DONE workers. The despawn (shrink-out) animation is driven by a worker LEAVING this
      // live set (see reconcile's "not in seen" branch). 'done' workers linger in the snapshot for a
      // while (sources._WORKER_LINGER_S), so keeping them here re-created + re-killed their sprite every
      // tick → an endless "minimizing" loop. The roster/legend/pulse already filter status !== 'done'.
      workforce = (s.workers || []).filter(w => w.status !== 'done'); slots = s.slots || slots; gates = s.gates_waiting || 0; cold = !!s.cold;
      if (reduced) drawOnce();
    },
    setPose(p) { setPoseW(p); if (reduced) drawOnce(); },
    setLamp(m) { const th = m === 'night' ? 'night' : 'day'; if (th !== theme) { theme = th; ensureTheme(theme); } if (reduced) drawOnce(); },
    setView(m) { setView(m); },
    goRoom(k) { if (ROOM_BOX[k]) goRegion(k); },
    focusProject(id) { focusProject(id); },
    back() { back(); },
    viewInfo, highlight(r) { highlightRole = r; if (reduced) drawOnce(); },
    roomRect(k) { if (!ROOM_BOX[k]) return null; const b = ROOM_BOX[k], tl = w2s(b.x, b.y), br = w2s(b.x + b.w, b.y + b.h); return { x: tl.x, y: tl.y, w: br.x - tl.x, h: br.y - tl.y }; },
    band() { return { top: VIEW.top, bot: VIEW.bot, W, H }; },
    calInfo() { return calib(); },   // diagnostic handle: the measured walk-scale K + per-frame feet offsets
    layout() { return { boxes: ROOM_KEYS.map(k => ({ key: k, x: ROOM_BOX[k].x, y: ROOM_BOX[k].y, w: ROOM_BOX[k].w, h: ROOM_BOX[k].h })), bbox: boxesBBox(), room: view.room, level: view.level }; },
    setAmbient(on) { ambient = !!on; if (reduced) drawOnce(); },
    followWorker(id) { followWorker(id); },
    stopFollow() { stopFollow(); },
    following() { return followId; },
    onClick(item, gate) { onItem = item; onGate = gate; },
    onWorker(cb) { onWorker = cb; },
    onNewt(cb) { onNewt = cb; },
    onView(cb) { onView = cb; },
    onFollow(cb) { onFollow = cb; },
  };
}

/* font helpers (read the CSS vars so the canvas matches the UI) */
function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function getSerif() { return cssVar('--serif') || 'Georgia, serif'; }
function getRound() { return cssVar('--round') || 'system-ui, sans-serif'; }
function getMono() { return cssVar('--mono') || 'monospace'; }

/* pose parameter sets — Newt's glow/hue per pose (eased toward) */
const POSE_PARAMS = {
  sleep: { glow: 0.3, hue: 210 }, idle: { glow: 0.55, hue: 48 }, running: { glow: 0.95, hue: 168 },
  success: { glow: 1.1, hue: 150 }, failure: { glow: 0.3, hue: 18 }, writing: { glow: 0.7, hue: 36 },
  regen: { glow: 1.0, hue: 285 }, gate: { glow: 0.9, hue: 44 }, letter: { glow: 0.8, hue: 48 },
};

function create(opts) {
  DEPS = Object.assign(DEPS, opts || {});
  const worldMode = () => {
    const q = new URLSearchParams(location.search).get('world');
    return q === 'classic' || q === 'diorama' ? q : (DEPS.world === 'classic' ? 'classic' : 'diorama');
  };
  let impl = null, pendingState = null, pendingPose = 'idle', pendingLamp = null;
  let itemCb = null, gateCb = null, workerCb = null, newtCb = null, viewCb = null, followCb = null, booted = false;
  const queued = [];
  const later = (fn) => { if (impl) fn(impl); else queued.push(fn); };
  async function boot(canvas) {
    if (booted || !canvas) return; booted = true;
    const reduced = (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) || DEPS.motion === false;
    const o = { reduced, lamp: document.documentElement.dataset.lamp };
    let made = null;
    if (worldMode() === 'diorama' && window.VivWorld && window.PIXI) {
      try {
        made = await window.VivWorld.createPixiWorld(canvas, Object.assign({}, o, { deps: {
          hash01, projDeg: projectHue, roleHSL, ROLE_ORDER, POSE_PARAMS, getRound, runTool, toast,
          STATE_ROOM, STATE_STATION, ROLE_STATION } }));
      } catch (e) { console.warn("Newts' Lab: the diorama world could not start — using the classic painted world.", e); made = null; }
    }
    if (!made) {
      let c2 = canvas;   // a Pixi canvas can't be reused for a 2D context: swap in a fresh element
      if (worldMode() === 'diorama') { c2 = canvas.cloneNode(false); canvas.replaceWith(c2); }
      try { made = createWorld(c2, o); } catch (e) { console.warn("Newts' Lab: the world could not start.", e); return; }
    }
    impl = made;
    window.__VIV = { kind: impl.kind, scene: impl };
    impl.onClick(itemCb, gateCb); if (workerCb) impl.onWorker(workerCb); if (newtCb) impl.onNewt(newtCb); if (viewCb) impl.onView(viewCb); if (followCb) impl.onFollow(followCb);
    if (pendingLamp) impl.setLamp(pendingLamp);
    if (pendingState) impl.sync(pendingState);
    impl.setPose(pendingPose);
    while (queued.length) { try { queued.shift()(impl); } catch (e) { /* a stale call is harmless */ } }
  }
  return {
    boot,
    onClick(item, gate) { itemCb = item; gateCb = gate; if (impl) impl.onClick(item, gate); },
    onWorker(cb) { workerCb = cb; if (impl) impl.onWorker(cb); },
    onNewt(cb) { newtCb = cb; if (impl) impl.onNewt(cb); },
    onView(cb) { viewCb = cb; if (impl) impl.onView(cb); },
    sync(s) { pendingState = s; if (impl) impl.sync(s); },
    setPose(p) { pendingPose = p; if (impl) impl.setPose(p); },
    setLamp(m) { pendingLamp = m; if (impl) impl.setLamp(m); },
    setView(m) { later(w => w.setView(m)); },
    goRoom(k) { later(w => w.goRoom(k)); },
    focusProject(id) { later(w => w.focusProject(id)); },
    back() { later(w => w.back()); },
    viewInfo() { return impl ? impl.viewInfo() : { level: 'WORLD', label: '' }; },
    highlight(r) { later(w => w.highlight(r)); },
    roomRect(k) { return impl ? impl.roomRect(k) : null; },
    band() { return impl ? impl.band() : null; },
    followWorker(id) { later(w => w.followWorker(id)); },
    stopFollow() { if (impl) impl.stopFollow(); },
    following() { return impl ? impl.following() : null; },
    onFollow(cb) { followCb = cb; if (impl) impl.onFollow(cb); },
    layout() { return impl ? impl.layout() : null; },
    setAmbient(on) { later(w => w.setAmbient(on)); },
    insetsChanged() { later(w => w.insetsChanged && w.insetsChanged()); },
    kind() { return impl ? impl.kind : null; },
  };
}

/* Newt's pose from the lab state, by priority (gate-waiting > fresh failure > success > regen > running >
   writing > idle > asleep) — only UNRESOLVED escalations count */
function escList(s) {
  if (Array.isArray(s.escalations)) return s.escalations;
  const evs = s.events || [];
  const resolved = new Set(evs.filter(e => e.kind === 'escalation_resolved').map(e => (e.data && e.data.ref) || ''));
  return evs.filter(e => e.kind === 'escalation' && !resolved.has((e.data && e.data.id) || ''));
}
function newtPoseFor(s) {
  if (!s || s.cold) return 'sleep';
  if (s.gates_waiting > 0) return 'gate';
  if (escList(s).length) return 'gate';
  const recent = (s.events || []).slice(-6).reverse();
  for (const e of recent) {
    const k = e.kind || '';
    if (k === 'kill' || (k === 'run_finished' && ['failed', 'timeout'].includes(e.status))) return 'failure';
    if (k === 'run_finished' && e.status === 'completed') return 'success';
    if (['replan', 'decision_revisit', 'frontier_expand', 'approach_ideate'].includes(k)) return 'regen';
  }
  if ((s.items || []).some(it => (it.inflight || []).length)) return 'running';
  if (recent.some(e => e.kind === 'paper_compiled' || (e.kind || '').includes('review'))) return 'writing';
  if (!recent.length) return 'sleep';
  return 'idle';
}

window.VivScene = { create, newtPoseFor, escList, hash01, projectHue, roleHSL, ROLE_ORDER, ROOM_KEYS, ROOM_LABEL, ROOM_N, STATE_ROOM, POSE_PARAMS };
})();
