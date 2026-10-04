/* Newts' Lab — the world behind the dashboard, and one stable API for it.

   The tabletop lab in 3D (static/world3d/world.js), wrapped by VivScene.create(): sync, setPose, setLamp,
   setView, goRoom, focusProject, back, viewInfo, highlight, layout, setAmbient, setLens,
   followWorker/stopFollow/following, on* callbacks. Calls made while the world is still booting are
   buffered and replayed in order. Without WebGL the dashboard works the same, minus the world: a quiet
   stand-in says so. */
(function () {
'use strict';
let DEPS = {};

function hash01(str) { let h = 2166136261; for (let i = 0; i < (str || '').length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 100000) / 100000; }
// a study's stable hue (its card in the world, its dot on the board), in 30° steps
function projectHue(id) { return id ? Math.floor(hash01(id + 'hue') * 12) * 30 : 0; }

/* no WebGL: the same contract, nothing drawn but one line saying why */
function quietWorld(canvas, why) {
  const noop = () => {};
  const paint = () => {
    try {
      const c = canvas.getContext('2d'), r = canvas.getBoundingClientRect();
      canvas.width = r.width; canvas.height = r.height;
      c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--ink-faint').trim() || '#888';
      c.font = '14px ' + (getComputedStyle(document.documentElement).getPropertyValue('--sans').trim() || 'system-ui'); c.textAlign = 'center';
      c.fillText(why, r.width / 2, r.height / 2);
    } catch (e) { /* nothing to draw on */ }
  };
  paint(); window.addEventListener('resize', paint);
  return { kind: 'none', boot: noop, sync: noop, setPose: noop, setLamp: noop, setView: noop, goRoom: noop, focusProject: noop, back: noop,
    viewInfo: () => ({ level: 'WORLD', label: '' }), highlight: noop, roomRect: () => null, band: () => null,
    followWorker: noop, stopFollow: noop, following: () => null, layout: () => null, setAmbient: noop, setLens: noop, lens: () => 'work', insetsChanged: noop,
    onClick: noop, onWorker: noop, onRun: noop, onNewt: noop, onView: noop, onFollow: noop };
}

function create(opts) {
  DEPS = Object.assign(DEPS, opts || {});
  let impl = null, pendingState = null, pendingPose = 'idle', pendingLamp = null, pendingLens = null;
  const cbs = {}, queued = [];
  let booted = false;
  const later = (fn) => { if (impl) fn(impl); else queued.push(fn); };
  async function boot(canvas) {
    if (booted || !canvas) return; booted = true;
    const reduced = (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) || DEPS.motion === false;
    let made = null;
    if (window.Lab3D && window.Lab3D.createWorld) {
      try { made = await window.Lab3D.createWorld(canvas, { reduced, lamp: document.documentElement.dataset.lamp }); await made.boot(); }
      catch (e) { console.warn("Newts' Lab: the world could not start.", e); made = null; }
    }
    if (!made) {   // a WebGL canvas can't be reused for a 2D context: swap in a fresh element
      const c2 = canvas.cloneNode(false); canvas.replaceWith(c2);
      made = quietWorld(c2, 'This browser cannot draw the lab world (no WebGL) — everything else works.');
    }
    impl = made;
    window.__VIV = { kind: impl.kind, scene: impl };
    impl.onClick(cbs.item, cbs.inbox);
    for (const k of ['onWorker', 'onRun', 'onNewt', 'onView', 'onFollow']) if (cbs[k]) impl[k](cbs[k]);
    if (pendingLamp) impl.setLamp(pendingLamp);
    if (pendingLens) impl.setLens(pendingLens);
    impl.setPose(pendingPose);
    if (pendingState) await impl.sync(pendingState);
    while (queued.length) { try { queued.shift()(impl); } catch (e) { /* a stale call is harmless */ } }
  }
  const relay = name => cb => { cbs[name] = cb; if (impl) impl[name](cb); };
  return {
    boot,
    onClick(item, inbox) { cbs.item = item; cbs.inbox = inbox; if (impl) impl.onClick(item, inbox); },
    onWorker: relay('onWorker'), onRun: relay('onRun'), onNewt: relay('onNewt'), onView: relay('onView'), onFollow: relay('onFollow'),
    sync(s) { pendingState = s; if (impl) impl.sync(s); },
    setPose(p) { pendingPose = p; if (impl) impl.setPose(p); },
    setLamp(m) { pendingLamp = m; if (impl) impl.setLamp(m); },
    setLens(l) { pendingLens = l; if (impl) impl.setLens(l); },
    lens() { return impl ? impl.lens() : (pendingLens || 'work'); },
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
  if ((s.items || []).some(it => (it.inflight || []).length) || (s.runs || []).some(r => ['starting', 'running', 'resuming'].includes(r.status))) return 'running';
  if (recent.some(e => e.kind === 'paper_compiled' || (e.kind || '').includes('review'))) return 'writing';
  if (!recent.length) return 'sleep';
  return 'idle';
}

window.VivScene = { create, newtPoseFor, escList, hash01, projectHue };
})();
