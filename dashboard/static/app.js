/* Vivarium frontend — the terrarium scene, Newt's mind, and the control console. */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const hhmm = ts => (ts || '').slice(11, 16);
const num = v => typeof v === 'number' ? (+v).toPrecision(4) : esc(v);

const LIFECYCLE = ['seed', 'triaged', 'lit-review', 'scoping', 'proposal', 'active', 'analysis', 'writing', 'internal-review', 'final'];
const lifeIdx = s => { const i = LIFECYCLE.indexOf(s); return i < 0 ? 99 : i; };
// a plant grows through the lifecycle; killed wilts, parked rests
const PLANT = ['🌰', '🌱', '🌿', '☘️', '🪴', '🪴', '🌻', '🌷', '💐', '🌳'];
function plantFor(state) {
  if (state === 'killed') return '🍂';
  if (state === 'parked') return '🌵';
  const i = lifeIdx(state); return i < 99 ? PLANT[i] : '🌱';
}

let STATE = null, MODE = 'terrarium', TARGET = 'hub';

/* ── Newt's mind: pose + speech ─────────────────────────────────────────── */
const POSES = ['gate', 'failure', 'success', 'regen', 'running', 'writing', 'letter', 'idle', 'sleep'];
function newtPoseFor(s) {
  if (!s || s.cold) return 'sleep';
  if (s.gates_waiting > 0) return 'gate';
  const recent = (s.events || []).slice(-6).reverse();
  for (const e of recent) {
    const k = e.kind || '';
    if (k === 'kill' || (k === 'run_finished' && ['failed', 'timeout'].includes(e.status))) return 'failure';
    if (k === 'run_finished' && e.status === 'completed') return 'success';
    if (['replan', 'decision_revisit', 'frontier_expand'].includes(k)) return 'regen';
  }
  if ((s.items || []).some(it => (it.inflight || []).length)) return 'running';
  if (recent.some(e => e.kind === 'paper_compiled' || (e.kind || '').includes('review'))) return 'writing';
  if (!recent.length) return 'sleep';
  return 'idle';
}
function setPose(p) { const n = $('#newt'); POSES.forEach(x => n.classList.remove('pose-' + x)); n.classList.add('pose-' + p); }
function speak(html) {
  const s = $('#speech'); if (!html) { s.hidden = true; return; }
  s.innerHTML = html; s.hidden = false; clearTimeout(speak._t); speak._t = setTimeout(() => s.hidden = true, 8000);
}
function narrate(s) {
  const ev = s.events || [], last = ev[ev.length - 1];
  if (!last || last.ts === narrate._ts) return; narrate._ts = last.ts;
  if (s.gates_waiting > 0) return speak(`<b>${s.gates_waiting} gate(s)</b> waiting — tap the lantern.`);
  const d = last.detail ? esc(last.detail) : '';
  const m = last.data && last.data.metrics ? Object.entries(last.data.metrics).slice(0, 2).map(([k, v]) => `<span class="mono">${k}=${num(v)}</span>`).join(' ') : '';
  let t;
  switch (last.kind) {
    case 'run_finished': t = `<span class="mono">${esc(last.run_id || '')}</span> ${esc(last.status || '')} ${m}`; break;
    case 'run_started': t = `tending <span class="mono">${esc(last.run_id || '')}</span>`; break;
    case 'decision_revisit': t = `regrowing — reopened a decision · ${d}`; break;
    case 'frontier_expand': t = `sprouting new lines · ${d}`; break;
    case 'replan': t = `re-planning · ${d}`; break;
    case 'kill': t = `composted: ${d}`; break;
    default: t = d || last.kind;
  }
  speak(t);
}

/* ── meters ─────────────────────────────────────────────────────────────── */
function renderMeters(s) {
  const gb = $('#gateBadge'), lan = $('#lantern');
  if (s.gates_waiting > 0) { gb.hidden = false; gb.textContent = s.gates_waiting; lan.hidden = false; $('#lanternN').textContent = s.gates_waiting; }
  else { gb.hidden = true; lan.hidden = true; }
  const ff = $('#fireflies'); ff.innerHTML = ''; ff.title = `${s.slots.in_use}/${s.slots.cap} compute slots in use`;
  for (let i = 0; i < s.slots.cap; i++) ff.appendChild(el('i', i < s.slots.in_use ? 'lit' : ''));
  const c = $('#clock'); c.textContent = hhmm(s.now); c.classList.remove('stopped');
}

/* ── the terrarium scene ────────────────────────────────────────────────── */
function sparkline(series) {
  if (!series || series.length < 2) return '';
  const v = series.map(p => p.value), mn = Math.min(...v), mx = Math.max(...v), rng = mx - mn || 1, w = 150, h = 22;
  const pts = v.map((x, i) => `${(i * w / (v.length - 1)).toFixed(1)},${(h - ((x - mn) / rng) * (h - 4) - 2).toFixed(1)}`).join(' ');
  return `<svg class="spark" width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="var(--leaf-d)" stroke-width="1.6"/></svg>`;
}
function jarHTML(it) {
  const fly = it.inflight || [], live = fly.length > 0, stalled = fly.some(r => r.state === 'stalled');
  let chips = `<span class="chip state">${esc(it.state)}</span>`;
  fly.forEach(r => chips += `<span class="chip ${r.state === 'stalled' ? 'stalled' : 'live'}">${esc((r.run_id || '').split('-').slice(-1)[0] || 'run')} ${r.state}</span>`);
  if (it.loop_active) chips += '<span class="chip live">loop</span>';
  const pend = (it.directives || []).filter(d => d.state === 'pending' || d.state === 'seen').length;
  if (pend) chips += `<span class="chip note" title="commands awaiting the agent">✎ ${pend}</span>`;
  let fill = '';
  if (live && fly[0].budget_min) fill = `<div class="fill"><i style="width:${Math.min(100, fly[0].elapsed_s / (fly[0].budget_min * 60) * 100).toFixed(0)}%"></i></div>`;
  const lastm = live && Object.keys(fly[0].last).length ? `<div class="last">${Object.entries(fly[0].last).slice(0, 2).map(([k, v]) => `${k}=${num(v)}`).join(' · ')}</div>` : '';
  return `<div class="plant">${plantFor(it.state)}</div><div class="nm">${esc(it.title || it.id)}</div>
    <div class="chips">${chips}</div>${fill}${sparkline(it.best && it.best.series)}${lastm}
    <div class="tap">tap to command ▸</div>`;
}
function renderScene(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const scene = el('section', 'scene');
  scene.appendChild(el('div', 'scene-sun'));
  if (s.cold) {
    scene.innerHTML += `<div class="coldstart"><div class="big">an empty terrarium</div>
      <p>nothing planted yet. open a session and run <code>/setup-lab</code>, then <code>/ideate</code>.<br>
      Newt's napping until something sprouts.</p></div>`;
    stage.appendChild(scene); return;
  }
  scene.innerHTML += `<h2>The terrarium</h2><p class="lede">every idea a plant, every project a jar on the shelf — tap any to steer it.</p>`;
  const sprouts = el('div', 'sprouts');
  const seedlings = s.items.filter(it => !it.has_project).sort((a, b) => lifeIdx(a.state) - lifeIdx(b.state));
  seedlings.forEach(it => {
    const sp = el('div', 'sprout' + (it.gate ? ' gate' : ''));
    sp.style.opacity = (it.state === 'killed' || it.state === 'parked') ? .5 : 1;
    sp.innerHTML = `<div class="pot">${plantFor(it.state)}</div><div class="nm">${esc(it.id)}</div><div class="st">${esc(it.state)}</div>`;
    sp.onclick = () => openSheet(it.id);
    sprouts.appendChild(sp);
  });
  if (!seedlings.length) sprouts.appendChild(el('div', 'empty-note', 'no seedlings — run /ideate to plant one'));
  scene.appendChild(sprouts);

  const shelf = el('div', 'shelf'), jars = el('div', 'jars');
  const projects = s.items.filter(it => it.has_project)
    .sort((a, b) => (a.gate ? 0 : (a.inflight || []).length ? 1 : 5) - (b.gate ? 0 : (b.inflight || []).length ? 1 : 5));
  projects.forEach(it => {
    const j = el('div', 'jar' + (it.gate ? ' gate' : '') + ((it.inflight || []).some(r => r.state === 'stalled') ? ' fail' : ''), jarHTML(it));
    j.onclick = () => openSheet(it.id); jars.appendChild(j);
  });
  if (!projects.length) jars.appendChild(el('div', 'empty-note', 'the shelf is bare — approved proposals spawn jars here'));
  shelf.appendChild(jars); scene.appendChild(shelf);
  stage.appendChild(scene);
}

/* ── panels ─────────────────────────────────────────────────────────────── */
function renderShelf(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>The shelf</h2><p class="lede">every project up close — steer it, or run a read-only check.</p>');
  if (!s.items.length) { p.innerHTML += '<div class="empty-note">nothing growing yet.</div>'; stage.appendChild(p); return; }
  const grid = el('div', 'cardgrid');
  s.items.forEach(it => {
    const fly = it.inflight || [];
    const c = el('div', 'pcard');
    let chips = `<span class="chip state">${esc(it.state)}</span>` + (it.loop_active ? '<span class="chip live">loop</span>' : '');
    fly.forEach(r => chips += `<span class="chip ${r.state === 'stalled' ? 'stalled' : 'live'}">${esc(r.run_id)} ${r.state}</span>`);
    c.innerHTML = `<h3>${plantFor(it.state)} ${esc(it.title || it.id)}</h3><div class="row">${chips}</div>
      <div class="mono" style="font-size:.78rem;color:var(--ink-soft)">${esc(it.next || '')}</div>
      ${sparkline(it.best && it.best.series)}`;
    const br = el('div', 'btnrow');
    br.appendChild(btn('command ▸', 'go', () => openSheet(it.id)));
    if (it.has_project) {
      br.appendChild(btn('status', 'tool', () => runTool('status', it.id)));
      br.appendChild(btn('compare', 'tool', () => runTool('compare', it.id)));
      br.appendChild(btn('config', 'tool', () => runTool('show_config', it.id)));
      br.appendChild(btn('inbox', 'tool', () => runTool('inbox', it.id)));
    }
    c.appendChild(br); grid.appendChild(c);
  });
  p.appendChild(grid); stage.appendChild(p);
}
function btn(label, cls, fn) { const b = el('button', 'btn ' + (cls || ''), label); b.onclick = fn; return b; }

function renderGates(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>The gates</h2><p class="lede">your sign-off. Gate 1 & 2 you can approve right here; Gate 3 is always done in a session.</p>');
  const waiting = s.items.filter(it => it.gate);
  if (!waiting.length) p.innerHTML += '<div class="empty-note">no gates waiting — nothing needs you.</div>';
  const wrap = el('div', 'letters');
  waiting.forEach(it => {
    const g = it.gate;
    const what = g === 1 ? `review <code>ideas/${esc(it.id)}/proposal.md</code>` : g === 3 ? `read <code>papers/${esc(it.id)}/</code> + the meta-review` : `pre-authorize FULL runs (Gate-2 envelope)`;
    const card = el('div', 'letter' + (g === 3 ? ' g3' : ''));
    card.innerHTML = `<div class="seal">${g}</div><h3>${esc(it.title || it.id)} — Gate ${g}</h3><div class="sub">${esc(it.next)}</div><p class="sub">${what}, then:</p>`;
    if (g === 3) card.innerHTML += `<code>read the draft, then /finalize ${esc(it.id)}</code><p class="sub">Gate 3 (sending anything outside the lab) is never one-click — open a session.</p>`;
    else { const b = btn(`✓ Approve Gate ${g} (PI)`, 'go', () => openGate(it.id, g)); card.appendChild(b); card.appendChild(el('p', 'sub', 'records your signature locally (logged); the agent does the mechanics next checkpoint.')); }
    wrap.appendChild(card);
  });
  p.appendChild(wrap); stage.appendChild(p);
}

function renderLedger(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>The ledger</h2><p class="lede">commands you’ve issued and every signal the lab has emitted.</p>');
  const dir = [...(s.directives || []).map(d => ({ ...d, target: 'hub' })), ...(s.items || []).flatMap(it => (it.directives || []).map(d => ({ ...d, target: it.id })))];
  let h = '<h3 style="font-family:var(--serif)">Commands & notes</h3><table><thead><tr><th>id</th><th>target</th><th>what</th><th>state</th><th>evidence</th></tr></thead><tbody>';
  if (!dir.length) h += '<tr><td colspan="5" class="sub">none yet</td></tr>';
  dir.forEach(d => {
    const what = d.kind === 'command' ? `<span class="mono">${esc(d.action)}</span> ${esc(JSON.stringify(d.args || {}) === '{}' ? '' : JSON.stringify(d.args))} ${esc(d.text || '')}` : esc(d.text || '');
    const ev = d.ack && d.ack.evidence ? `<span class="mono">${esc(d.ack.evidence)}</span>` : (d.state === 'done' ? '<span class="unresolved">— none —</span>' : '');
    h += `<tr><td class="mono">${esc(d.id)}</td><td>${esc(d.target)}</td><td>${what}</td><td><span class="dchip ${d.state}${d.state === 'done' && !(d.ack && d.ack.evidence) ? ' noevidence' : ''}">${esc(d.state)}</span></td><td>${ev}</td></tr>`;
  });
  h += '</tbody></table><h3 style="font-family:var(--serif)">Event log</h3><table><thead><tr><th>time</th><th>source</th><th>kind</th><th>detail</th></tr></thead><tbody>';
  (s.events || []).slice(-90).reverse().forEach(e => {
    const n = e.data && e.data.metrics ? ' · ' + Object.entries(e.data.metrics).slice(0, 1).map(([k, v]) => `${k}=${num(v)}`).join('') : '';
    h += `<tr><td class="mono">${hhmm(e.ts)}</td><td>${esc(e.source)}</td><td class="mono">${esc(e.kind)}</td><td>${esc(e.detail || '')}${esc(n)}</td></tr>`;
  });
  h += '</tbody></table>'; p.innerHTML += h; stage.appendChild(p);
}

function renderNight(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>Night watch</h2><p class="lede">what’s in flight, quietly.</p>');
  const night = el('div', 'night'); const live = [];
  s.items.forEach(it => (it.inflight || []).forEach(r => live.push({ ...r, slug: it.id })));
  if (s.gates_waiting) night.appendChild(el('div', 'nrow stalled', `<span class="rid">🔔 ${s.gates_waiting} gate(s) waiting for you</span>`));
  if (!live.length) night.appendChild(el('div', 'quiet', 'all quiet — no runs in flight.'));
  live.forEach(r => {
    const pct = r.budget_min ? Math.min(100, r.elapsed_s / (r.budget_min * 60) * 100) : 0;
    const met = Object.keys(r.last).length ? Object.entries(r.last).slice(0, 1).map(([k, v]) => `${k}=${num(v)}`).join('') : '—';
    night.appendChild(el('div', 'nrow ' + (r.state === 'stalled' ? 'stalled' : ''),
      `<span class="rid">${esc(r.slug)} · ${esc(r.run_id)}</span><span class="barwrap"><i style="width:${pct.toFixed(0)}%"></i></span>
       <span class="met">${Math.round(r.elapsed_s / 60)}m/${r.budget_min || '∞'}m · ${esc(met)} · ${r.state}</span>`));
  });
  p.appendChild(night); stage.appendChild(p);
}

const VIEWS = { terrarium: renderScene, shelf: renderShelf, gates: renderGates, ledger: renderLedger, night: renderNight };
function render() {
  if (!STATE) return;
  document.body.dataset.mode = MODE;
  $$('.tab').forEach(b => b.classList.toggle('is-active', b.dataset.go === MODE));
  renderMeters(STATE); (VIEWS[MODE] || renderScene)(STATE);
  setPose(newtPoseFor(STATE)); narrate(STATE);
}

/* ── command console ────────────────────────────────────────────────────── */
const ACTIONS = {
  // action, label, hint, css; avail: 'project'|'idea'|'both'|'hub'
  project: [
    ['start_loop', 'Start loop ▸ execute', 'run the approved plan unattended', '', { mode: 'execute' }],
    ['start_loop', 'Start loop ▸ explore', 'autonomous in-project re-planning', '', { mode: 'explore' }],
    ['stop_loop', 'Stop loop', 'wind down after the current run', ''],
    ['run_smoke', 'Run smoke', 'quick end-to-end pipeline check', ''],
    ['request_run', 'Request a run', 'queue the next planned experiment', ''],
    ['analyze', 'Analyze results', 'artifact-only read + routing', ''],
    ['prioritize', 'Prioritize', 'work this project first', ''],
    ['park', 'Park', 'set aside for now', 'warn'],
    ['kill', 'Kill', 'stop with a recorded reason', 'warn'],
  ],
  idea: [
    ['ideate', 'Ideate around this', 'generate sibling ideas', ''],
    ['prioritize', 'Prioritize', 'advance this idea first', ''],
    ['park', 'Park', 'set aside for now', 'warn'],
    ['kill', 'Kill', 'stop with a recorded reason', 'warn'],
  ],
  hub: [
    ['ideate', 'Ideate', 'start a new idea from a direction', ''],
    ['prioritize', 'Set a priority', 'tell the lab what matters now', ''],
  ],
};
function targetItem(id) { return (STATE.items || []).find(i => i.id === id); }
function openSheet(target) {
  TARGET = target || 'hub';
  $('#sheetScrim').hidden = false; $('#sheet').hidden = false;
  setPose('letter');
  buildTargets(); buildActions(); updateLatency();
}
function closeSheet() { $('#sheetScrim').hidden = true; $('#sheet').hidden = true; setPose(newtPoseFor(STATE)); }
function buildTargets() {
  const w = $('#targetChips'); w.innerHTML = '';
  ['hub', ...(STATE.items || []).map(i => i.id)].forEach(t => {
    const c = el('button', 'tchip' + (t === TARGET ? ' on' : ''), t === 'hub' ? 'The Lab' : esc(t));
    c.onclick = () => { TARGET = t; buildTargets(); buildActions(); updateLatency(); };
    w.appendChild(c);
  });
}
function buildActions() {
  const it = targetItem(TARGET);
  $('#sheetTitle').textContent = TARGET === 'hub' ? 'Command the lab' : `Steer ${TARGET}`;
  const set = TARGET === 'hub' ? ACTIONS.hub : (it && it.has_project ? ACTIONS.project : ACTIONS.idea);
  const grid = $('#actionGrid'); grid.innerHTML = '';
  if (it && it.gate && it.gate !== 3) {
    const g = el('button', 'act gate', `<b>✓ Approve Gate ${it.gate}</b><small>record your PI signature (logged)</small>`);
    g.onclick = () => { closeSheet(); openGate(it.id, it.gate); }; grid.appendChild(g);
  }
  set.forEach(([action, label, hint, cls, args]) => {
    const a = el('button', 'act ' + (cls || ''), `<b>${esc(label)}</b><small>${esc(hint)}</small>`);
    a.onclick = () => doCommand(action, args || {}, label);
    grid.appendChild(a);
  });
}
function updateLatency() {
  const it = targetItem(TARGET);
  $('#latency').textContent = (it && it.loop_active)
    ? 'a loop is live here — it reads this at its next cycle.'
    : 'commands reach the agent at its next checkpoint (a loop cycle / session start) — not instant.';
}
async function doCommand(action, args, label) {
  try {
    await fetch('/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: TARGET, action, args, text: label }) });
    toast(`queued: ${label} → ${TARGET === 'hub' ? 'the lab' : TARGET}`); closeSheet();
  } catch (e) { toast('could not reach the vivarium server'); }
}
async function sendNote() {
  const t = $('#noteText').value.trim(); if (!t) return;
  try { await fetch('/api/directive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: TARGET, text: t }) }); $('#noteText').value = ''; toast('note pinned — Newt will carry it'); closeSheet(); }
  catch (e) { toast('could not reach the vivarium server'); }
}

/* ── gate approval ──────────────────────────────────────────────────────── */
let pendingGate = null;
function openGate(idea, gate) {
  pendingGate = { idea, gate };
  $('#modalTitle').textContent = `Approve Gate ${gate} — ${idea}?`;
  $('#modalBody').innerHTML = gate === 1
    ? `Records your PI signature on <span class="mono">ideas/${esc(idea)}/proposal.md</span> and lets the agent spawn the project. <b>Read the proposal first.</b>`
    : `Sets <span class="mono">gate2_envelope.pi_signed: true</span> in the project's control.yaml, authorizing the pre-agreed FULL runs. <b>Make sure the envelope is what you intend.</b>`;
  $('#modalScrim').hidden = false; $('#modal').hidden = false;
}
function closeModal() { $('#modalScrim').hidden = true; $('#modal').hidden = true; pendingGate = null; }
async function confirmGate() {
  if (!pendingGate) return;
  try {
    const r = await fetch('/api/gate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...pendingGate, confirm: true }) }).then(r => r.json());
    toast(r.ok ? `Gate ${pendingGate.gate} approved ✓` : (r.error || 'failed'));
  } catch (e) { toast('could not reach the server'); }
  closeModal();
}

/* ── tool runner (read-only) ────────────────────────────────────────────── */
async function runTool(name, idea) {
  $('#drawer').hidden = false; $('#drawerTitle').textContent = `${name}${idea ? ' · ' + idea : ''} — running…`; $('#drawerBody').textContent = '';
  try {
    const r = await fetch('/api/tool', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, idea }) }).then(r => r.json());
    $('#drawerTitle').textContent = `${name}${idea ? ' · ' + idea : ''}${r.exit != null ? ' · exit ' + r.exit : ''}`;
    $('#drawerBody').textContent = r.output || r.error || '(no output)';
  } catch (e) { $('#drawerBody').textContent = 'could not reach the server'; }
}

function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => t.hidden = true, 3200); }

/* ── lamplight ──────────────────────────────────────────────────────────── */
function applyLamp() {
  const url = new URLSearchParams(location.search).get('lamp');
  const mode = url || localStorage.getItem('lamp') || 'auto', hr = new Date().getHours();
  const night = mode === 'night' || (mode === 'auto' && (hr >= 19 || hr < 7));
  document.documentElement.dataset.lamp = night ? 'night' : 'day';
}

/* ── wiring ─────────────────────────────────────────────────────────────── */
$$('.tab').forEach(b => b.onclick = () => { MODE = b.dataset.go; location.hash = MODE; render(); });
$('#newtStage').onclick = () => openSheet(TARGET || 'hub');
$('#lantern').onclick = () => { MODE = 'gates'; location.hash = 'gates'; render(); };
$('#sheetClose').onclick = closeSheet; $('#sheetScrim').onclick = closeSheet;
$('#sendNote').onclick = sendNote;
$('#modalCancel').onclick = closeModal; $('#modalScrim').onclick = closeModal; $('#modalOk').onclick = confirmGate;
$('#drawerClose').onclick = () => $('#drawer').hidden = true;
$('#lampToggle').onclick = () => { const c = localStorage.getItem('lamp') || 'auto'; const n = c === 'auto' ? 'day' : c === 'day' ? 'night' : 'auto'; localStorage.setItem('lamp', n); applyLamp(); toast(`lamplight: ${n}`); };
window.addEventListener('hashchange', () => { const m = location.hash.slice(1); if (VIEWS[m]) { MODE = m; render(); } });

function ingest(s) { STATE = s; render(); }
function connect() {
  const es = new EventSource('/api/events');
  es.onmessage = ev => { try { ingest(JSON.parse(ev.data)); $('#staleVeil').hidden = true; } catch (e) {} };
  es.onerror = () => { $('#clock').classList.add('stopped'); if (!connect._p) connect._p = setInterval(() => fetch('/api/state').then(r => r.json()).then(ingest).catch(() => $('#staleVeil').hidden = false), 5000); };
}
applyLamp();
const startMode = location.hash.slice(1); if (VIEWS[startMode]) MODE = startMode;
const STATIC = location.search.includes('static');
if (window.__STATE__) ingest(window.__STATE__);
else fetch('/api/state').then(r => r.json()).then(ingest).catch(() => $('#staleVeil').hidden = false);
// deep-link: ?open=<idea|hub> opens the command console straight away
const openTo = new URLSearchParams(location.search).get('open');
if (openTo) setTimeout(() => openSheet(openTo), 60);
if (!STATIC) { connect(); setInterval(applyLamp, 60000); }
