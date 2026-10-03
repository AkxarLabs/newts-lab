/* Newts' Lab — the world behind the dashboard, and one stable API for it.

   The diorama (PixiJS, static/world/engine.js), wrapped by VivScene.create(): sync, setPose, setLamp,
   setView, goRoom, focusProject, back, viewInfo, highlight, layout, setAmbient,
   followWorker/stopFollow/following, on* callbacks. Calls made while the world is still booting are
   buffered and replayed in order. Without WebGL the dashboard works the same, minus the world: a quiet
   stand-in says so. */
(function () {
'use strict';
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const ROLE_ORDER = ['orchestrator', 'experiment-runner', 'fresh-context-reviewer', 'overseer', 'ideation-critic', 'scoping-advocate'];
let DEPS = { toast: () => {}, runTool: () => {} };
const toast = (m) => DEPS.toast(m);
const runTool = (n, i) => DEPS.runTool(n, i);

function hash01(str) { let h = 2166136261; for (let i = 0; i < (str || '').length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 100000) / 100000; }

// role → base colour (muted HSL [h,s,l]); per-instance jitter keeps clones distinct
const ROLE_HSL = {
  'orchestrator': [45, 46, 68], 'experiment-runner': [168, 32, 56], 'fresh-context-reviewer': [262, 28, 66],
  'overseer': [214, 28, 60], 'ideation-critic': [320, 30, 66], 'scoping-advocate': [40, 44, 60], 'other': [120, 8, 62],
};
function roleHSL(role, jit) {
  const b = ROLE_HSL[role] || ROLE_HSL.other; jit = jit || 0;
  return [b[0] + (jit - 0.5) * 18, b[1], clamp(b[2] + (jit - 0.5) * 12, 30, 82)];
}

// worker role → its default station, where a room names none for that role (rooms/*.js roleStation wins)
const ROLE_STATION = { 'ideation-critic': 'reflect', 'scoping-advocate': 'decisions', 'fresh-context-reviewer': 'review', 'experiment-runner': 'experiments', 'overseer': 'quality' };
// per-project stable hue rotation (deg) for buddy colour — bucketed for tint caching; Newt = 0 (pink)
function projectHue(id) { return id ? Math.floor(hash01(id + 'hue') * 12) * 30 : 0; }

/* no WebGL: the same contract, nothing drawn but one line saying why */
function quietWorld(canvas, why) {
  const noop = () => {};
  const paint = () => {
    try {
      const c = canvas.getContext('2d'), r = canvas.getBoundingClientRect();
      canvas.width = r.width; canvas.height = r.height;
      c.fillStyle = cssVar('--muted') || '#888'; c.font = '14px ' + getRound(); c.textAlign = 'center';
      c.fillText(why, r.width / 2, r.height / 2);
    } catch (e) { /* nothing to draw on */ }
  };
  paint(); window.addEventListener('resize', paint);
  return { kind: 'none', sync: noop, setPose: noop, setLamp: noop, setView: noop, goRoom: noop, focusProject: noop, back: noop,
    viewInfo: () => ({ level: 'WORLD', label: '' }), highlight: noop, roomRect: () => null, band: () => null,
    followWorker: noop, stopFollow: noop, following: () => null, layout: () => null, setAmbient: noop, insetsChanged: noop,
    onClick: noop, onWorker: noop, onNewt: noop, onView: noop, onFollow: noop };
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
  let impl = null, pendingState = null, pendingPose = 'idle', pendingLamp = null;
  let itemCb = null, gateCb = null, workerCb = null, newtCb = null, viewCb = null, followCb = null, booted = false;
  const queued = [];
  const later = (fn) => { if (impl) fn(impl); else queued.push(fn); };
  async function boot(canvas) {
    if (booted || !canvas) return; booted = true;
    const reduced = (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) || DEPS.motion === false;
    const o = { reduced, lamp: document.documentElement.dataset.lamp };
    let made = null;
    if (window.VivWorld && window.PIXI) {
      try {
        made = await window.VivWorld.createPixiWorld(canvas, Object.assign({}, o, { deps: {
          hash01, projDeg: projectHue, roleHSL, ROLE_ORDER, POSE_PARAMS, getRound, runTool, toast, ROLE_STATION } }));
      } catch (e) { console.warn("Newts' Lab: the world could not start.", e); made = null; }
    }
    if (!made) {   // a Pixi canvas can't be reused for a 2D context: swap in a fresh element
      const c2 = canvas.cloneNode(false); canvas.replaceWith(c2);
      made = quietWorld(c2, 'This browser cannot draw the lab world (no WebGL) — everything else works.');
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

window.VivScene = { create, newtPoseFor, escList, hash01, projectHue, roleHSL, ROLE_ORDER, POSE_PARAMS };
})();
