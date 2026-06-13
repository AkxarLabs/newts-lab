/* Marginalia frontend — SSE client, hash router, view renderers, Pica's mind. */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (t, cls, html) => { const e = document.createElement(t); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const hhmm = ts => (ts || '').slice(11, 16);

// lifecycle order for the rail
const LIFECYCLE = ['seed', 'triaged', 'lit-review', 'scoping', 'proposal', 'active', 'analysis', 'writing', 'internal-review', 'final'];
const lifeIdx = s => { const i = LIFECYCLE.indexOf(s); return i < 0 ? 99 : i; };

let STATE = null;
let MODE = 'desk';
let TARGET = 'hub';
let lastSeenTs = '';

/* ── Pica: posture priority + speech ─────────────────────────────────────── */
const PICA_PRIORITY = ['gate', 'failure', 'success', 'running', 'writing', 'reading', 'debug', 'sleep', 'letter', 'idle'];
function picaPoseFor(state) {
  if (!state || state.cold) return 'sleep';
  if (state.gates_waiting > 0) return 'gate';
  const ev = state.events || [];
  const recent = ev.slice(-6).reverse();
  for (const e of recent) {
    const k = e.kind || '';
    if (k === 'run_finished' && ['failed', 'timeout'].includes(e.status)) return 'failure';
    if (k === 'kill') return 'failure';
    if (k === 'run_finished' && e.status === 'completed') return 'success';
  }
  if ((state.items || []).some(it => (it.inflight || []).length)) return 'running';
  if (recent.some(e => e.kind === 'paper_compiled' || (e.kind || '').includes('review'))) return 'writing';
  if (recent.some(e => (e.detail || '').toLowerCase().includes('lit') || (e.kind === 'cycle'))) return 'reading';
  if (recent.length === 0) return 'sleep';
  return 'idle';
}
function setPica(pose) {
  const p = $('#pica');
  PICA_PRIORITY.forEach(x => p.classList.remove('pose-' + x));
  p.classList.add('pose-' + pose);
}
function speak(text) {
  const s = $('#speech');
  if (!text) { s.hidden = true; return; }
  s.innerHTML = text; s.hidden = false;
  clearTimeout(speak._t); speak._t = setTimeout(() => { s.hidden = true; }, 8000);
}
// the verbatim-values rule: Pica only repeats numbers copied from the event line
function narrate(state) {
  const ev = (state.events || []);
  const last = ev[ev.length - 1];
  if (!last) return;
  if (last.ts === narrate._ts) return; narrate._ts = last.ts;
  const live = (state.items || []).reduce((n, it) => n + (it.inflight || []).length, 0);
  if (state.gates_waiting > 0) return speak(`<b>${state.gates_waiting} gate(s)</b> waiting — your move.`);
  let txt = '';
  const d = last.detail ? esc(last.detail) : '';
  const m = last.data && last.data.metrics ? Object.entries(last.data.metrics).slice(0, 2).map(([k, v]) => `<span class="mono">${k}=${typeof v === 'number' ? (+v).toPrecision(4) : esc(v)}</span>`).join(' ') : '';
  switch (last.kind) {
    case 'run_finished': txt = `<span class="mono">${esc(last.run_id || '')}</span> ${esc(last.status || '')} ${m}`; break;
    case 'run_started': txt = `tending <span class="mono">${esc(last.run_id || '')}</span> (${esc(last.stage || '')})`; break;
    case 'cycle': txt = `cycle — ${d}`; break;
    case 'kill': txt = `composted: ${d}`; break;
    case 'state_change': txt = d; break;
    default: txt = d || last.kind;
  }
  if (live > 1) txt = `${live} runs live · ${txt}`;
  speak(txt);
}

/* ── meters / masthead ───────────────────────────────────────────────────── */
function renderMeters(s) {
  const gb = $('#gateBadge'), lan = $('#lantern');
  if (s.gates_waiting > 0) { gb.hidden = false; gb.textContent = s.gates_waiting; lan.hidden = false; }
  else { gb.hidden = true; lan.hidden = true; }
  const iw = $('#inkwells'); iw.innerHTML = '';
  for (let i = 0; i < s.slots.cap; i++) iw.appendChild(el('i', i < s.slots.in_use ? 'full' : ''));
  iw.title = `${s.slots.in_use}/${s.slots.cap} compute slots in use`;
  const clk = $('#deskclock'); clk.textContent = hhmm(s.now); clk.classList.remove('stopped');
}

/* ── ticker ──────────────────────────────────────────────────────────────── */
function renderTicker(s) {
  const t = $('#ticker'); t.innerHTML = '';
  const ev = (s.events || []).slice(-40).reverse();
  for (const e of ev) {
    const num = e.data && e.data.metrics ? ' · ' + Object.entries(e.data.metrics).slice(0, 1).map(([k, v]) => `${k}=${typeof v === 'number' ? (+v).toPrecision(4) : v}`).join('') : '';
    const line = el('div', 't', `<time>${hhmm(e.ts)}</time><b>${esc(e.source || '')}</b> ${esc(e.kind || '')} ${esc(e.detail || '')}${esc(num)}`);
    t.appendChild(line);
  }
}

/* ── views ───────────────────────────────────────────────────────────────── */
function renderDesk(s) {
  const L = $('#pageLeft'), R = $('#pageRight');
  L.innerHTML = '<h2>The lab <small>lifecycle rail</small></h2>';
  if (s.cold) {
    L.innerHTML += `<div class="coldstart"><div class="big">a fresh notebook</div>
      <p>nothing planted yet. open a session and run <code>/setup-lab</code>, then <code>/ideate</code>.</p></div>`;
    R.innerHTML = '';
    return;
  }
  const rail = el('div', 'rail', '<div class="rail-line"></div>');
  [...s.items].sort((a, b) => lifeIdx(a.state) - lifeIdx(b.state)).forEach(it => {
    const live = (it.inflight || []).length > 0;
    const gate = (it.next || '').toLowerCase().includes('gate');
    const cls = ['rail-dot', live && 'live', gate && 'gate', it.state === 'killed' && 'killed', it.state === 'parked' && 'parked'].filter(Boolean).join(' ');
    const dot = el('div', cls, `<span class="pip"></span>
      <div class="meta"><div class="ttl">${esc(it.title || it.id)}</div>
      <div class="sub">${esc(it.state)} · ${esc(it.next || '')}</div></div>`);
    if (it.state === 'killed' && it.next) dot.title = it.next;
    rail.appendChild(dot);
  });
  L.appendChild(rail);

  R.innerHTML = '<h2>Today <small>the lab writes itself</small></h2>';
  const entries = el('div', 'entries');
  (s.events || []).slice(-60).reverse().forEach(e => {
    const num = e.data && e.data.metrics ? ' ' + Object.entries(e.data.metrics).slice(0, 2).map(([k, v]) => `<span class="num">${k}=${typeof v === 'number' ? (+v).toPrecision(4) : esc(v)}</span>`).join(' ') : '';
    entries.appendChild(el('div', `entry k-${e.kind} s-${e.status || ''}`,
      `<time>${hhmm(e.ts)}</time><span class="src">${esc(e.source || '')}</span>${esc(e.detail || e.kind)}${num}`));
  });
  R.appendChild(entries);
}

function sparkline(series) {
  if (!series || series.length < 2) return '';
  const vals = series.map(p => p.value), mn = Math.min(...vals), mx = Math.max(...vals), rng = mx - mn || 1;
  const w = 180, h = 26, step = w / (vals.length - 1);
  const pts = vals.map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - mn) / rng) * (h - 4) - 2).toFixed(1)}`).join(' ');
  return `<svg class="spark" width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="var(--clay)" stroke-width="1.6"/></svg>`;
}
// deterministic doodle per slug (recognizable without colour-coding)
function doodle(id) {
  let n = 0; for (const c of id) n = (n * 31 + c.charCodeAt(0)) >>> 0;
  const paths = ['M0 8 q8 -16 16 0', 'M0 0 l8 8 l-8 8 M8 0 l8 16', 'M8 0 a8 8 0 1 0 .1 0 M8 6 v6', 'M0 12 l6 -12 l6 12 z', 'M0 4 h16 M4 0 v12 M12 0 v12'];
  return `<svg class="doodle" width="18" height="18" viewBox="-1 -1 18 18"><path d="${paths[n % paths.length]}" fill="none" stroke="var(--brown)" stroke-width="1.6"/></svg>`;
}
function renderBench(s) {
  const L = $('#pageLeft'); L.innerHTML = '<h2>The bench <small>one card per project</small></h2>';
  if (s.cold || !s.items.length) { L.innerHTML += '<p class="coldstart">no projects on the bench yet.</p>'; return; }
  const grid = el('div', 'cards');
  const order = it => (it.next || '').toLowerCase().includes('gate') ? 0 : (it.inflight || []).some(r => r.state === 'stalled') ? 1 : (it.inflight || []).length ? 2 : 5;
  [...s.items].sort((a, b) => order(a) - order(b)).forEach(it => {
    const fly = it.inflight || [];
    const attn = (it.next || '').toLowerCase().includes('gate');
    const fail = fly.some(r => r.state === 'stalled');
    const card = el('div', ['card', attn && 'attn', fail && 'fail'].filter(Boolean).join(' '));
    let chips = `<span class="chip state">${esc(it.state)}</span>`;
    fly.forEach(r => { chips += `<span class="chip ${r.state}">${esc(r.run_id?.split('-').slice(-1)[0] || r.stage || 'run')} ${r.state}</span>`; });
    if (it.loop_active) chips += '<span class="chip live">loop</span>';
    let rule = '';
    if (fly.length && fly[0].budget_min) {
      const pct = Math.min(100, (fly[0].elapsed_s / (fly[0].budget_min * 60)) * 100);
      rule = `<div class="rule"><i style="width:${pct.toFixed(0)}%"></i></div>`;
    }
    const last = fly.length && Object.keys(fly[0].last).length ? `<div class="last">last: ${Object.entries(fly[0].last).slice(0, 2).map(([k, v]) => `${k}=${(+v).toPrecision(4)}`).join(' ')}</div>` : '';
    card.innerHTML = `${doodle(it.id)}<div class="slug">${esc(it.id)}</div><div class="chips">${chips}</div>${rule}${sparkline(it.best?.series)}${last}`;
    grid.appendChild(card);
  });
  L.appendChild(grid);
}

function renderGates(s) {
  const L = $('#pageLeft'); L.innerHTML = '<h2>The anteroom <small>what waits for you</small></h2>';
  const waiting = s.items.filter(it => (it.next || '').toLowerCase().includes('gate'));
  if (!waiting.length) { L.innerHTML += '<p class="coldstart">no gates waiting — nothing needs you right now.</p>'; }
  const wrap = el('div', 'letters');
  waiting.forEach(it => {
    const which = /gate ?1/i.test(it.next) ? 1 : /gate ?3/i.test(it.next) ? 3 : 2;
    const cmd = which === 1 ? `review ideas/${it.id}/proposal.md, then approve at Gate 1`
      : which === 3 ? `read papers/${it.id}/ + the meta-review, then /finalize ${it.id}`
        : `/configure ${it.id} set gate2_envelope.pi_signed=true`;
    wrap.appendChild(el('div', 'letter',
      `<div class="seal">${which}</div><h3>${esc(it.title || it.id)} — Gate ${which}</h3>
       <div class="sub">${esc(it.next)}</div><code class="cmd">${esc(cmd)}</code>
       <p class="burn">The dashboard signs nothing — run the command in a session, or leave Pica a note to nudge the agent.</p>`));
  });
  L.appendChild(wrap);
}

function renderLedger(s) {
  const L = $('#pageLeft'); L.innerHTML = '<h2>The back pages <small>every directive & event</small></h2>';
  const dir = s.directives || [];
  let html = '<h3 style="margin-top:14px">Directives</h3><table><thead><tr><th>id</th><th>target</th><th>note</th><th>state</th><th>evidence</th></tr></thead><tbody>';
  if (!dir.length) html += '<tr><td colspan="5" class="sub">none</td></tr>';
  dir.forEach(d => {
    const ev = d.ack && d.ack.evidence ? `<span class="mono">${esc(d.ack.evidence)}</span>` : (d.state === 'done' ? '<span class="unresolved">— none —</span>' : '');
    html += `<tr><td class="mono">${esc(d.id)}</td><td>hub</td><td>${esc(d.text)}</td><td><span class="dchip ${d.state}${d.state === 'done' && !(d.ack && d.ack.evidence) ? ' noevidence' : ''}">${esc(d.state)}</span></td><td>${ev}</td></tr>`;
  });
  html += '</tbody></table>';
  html += '<h3 style="margin-top:22px">Event log</h3><table><thead><tr><th>time</th><th>source</th><th>kind</th><th>detail</th></tr></thead><tbody>';
  (s.events || []).slice(-80).reverse().forEach(e => {
    html += `<tr><td class="mono">${hhmm(e.ts)}</td><td>${esc(e.source)}</td><td class="mono">${esc(e.kind)}</td><td>${esc(e.detail || '')}</td></tr>`;
  });
  html += '</tbody></table>';
  L.innerHTML += html;
}

function renderNight(s) {
  const L = $('#pageLeft'); L.innerHTML = '<h2>Night watch <small>in-flight, quietly</small></h2>';
  const night = el('div', 'night');
  const live = [];
  s.items.forEach(it => (it.inflight || []).forEach(r => live.push({ ...r, slug: it.id })));
  if (s.gates_waiting) night.appendChild(el('div', 'nrow stalled', `<span class="rid">⚑ ${s.gates_waiting} gate(s) waiting for the PI</span>`));
  if (!live.length) night.appendChild(el('div', 'quiet', 'all quiet — no runs in flight.'));
  live.forEach(r => {
    const pct = r.budget_min ? Math.min(100, (r.elapsed_s / (r.budget_min * 60)) * 100) : 0;
    const met = Object.keys(r.last).length ? Object.entries(r.last).slice(0, 1).map(([k, v]) => `${k}=${(+v).toPrecision(4)}`).join('') : '—';
    night.appendChild(el('div', `nrow ${r.state === 'stalled' ? 'stalled' : ''}`,
      `<span class="rid">${esc(r.slug)} · ${esc(r.run_id)}</span>
       <span class="barwrap"><i style="width:${pct.toFixed(0)}%"></i></span>
       <span class="met">${Math.round(r.elapsed_s / 60)}m/${r.budget_min || '∞'}m · ${esc(met)} · ${r.state}</span>`));
  });
  L.appendChild(night);
}

const VIEWS = { desk: renderDesk, bench: renderBench, gates: renderGates, ledger: renderLedger, night: renderNight };

function render() {
  if (!STATE) return;
  document.body.dataset.mode = MODE;
  $$('.ribbon').forEach(b => b.classList.toggle('is-active', b.dataset.go === MODE));
  renderMeters(STATE);
  renderTicker(STATE);
  (VIEWS[MODE] || renderDesk)(STATE);
  setPica(picaPoseFor(STATE));
  narrate(STATE);
  buildTargetChips();
}

/* ── directive composer ──────────────────────────────────────────────────── */
function buildTargetChips() {
  const wrap = $('#targetChips'); if (!wrap) return;
  wrap.innerHTML = '';
  const targets = ['hub', ...(STATE?.items || []).map(it => it.id)];
  targets.forEach(t => {
    const c = el('button', 'tchip' + (t === TARGET ? ' on' : ''), t === 'hub' ? 'The Lab' : esc(t));
    c.onclick = () => { TARGET = t; buildTargetChips(); updateLatency(); };
    wrap.appendChild(c);
  });
}
function updateLatency() {
  const it = (STATE?.items || []).find(i => i.id === TARGET);
  const liveLoop = TARGET === 'hub' ? false : it?.loop_active;
  $('#latency').textContent = liveLoop ? 'next read: ~ next loop cycle'
    : 'agents read notes at their next checkpoint — not live';
}
function openComposer() {
  $('#composer').hidden = false;
  $('#pica').classList.add('pose-letter');
  updateLatency();
  $('#directiveText').focus();
}
async function sendDirective() {
  const text = $('#directiveText').value.trim();
  if (!text) return;
  try {
    await fetch('/api/directive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: TARGET, text }) });
    $('#directiveText').value = '';
    speak('pinned to the corkboard — Pica will carry it.');
  } catch (e) { speak('could not reach the daybook server.'); }
}

/* ── lamplight (auto by clock, manual override) ──────────────────────────── */
function applyLamp() {
  const url = new URLSearchParams(location.search).get('lamp'); // override for snapshots
  const mode = url || localStorage.getItem('lamp') || 'auto';
  const hr = new Date().getHours();
  const night = mode === 'night' || (mode === 'auto' && (hr >= 19 || hr < 7));
  document.documentElement.dataset.lamp = night ? 'night' : 'day';
}
$('#lampToggle').onclick = () => {
  const cur = localStorage.getItem('lamp') || 'auto';
  const next = cur === 'auto' ? 'day' : cur === 'day' ? 'night' : 'auto';
  localStorage.setItem('lamp', next); applyLamp();
  speak(`lamplight: ${next}`);
};

/* ── wiring ──────────────────────────────────────────────────────────────── */
$$('.ribbon').forEach(b => b.onclick = () => { MODE = b.dataset.go; location.hash = MODE; render(); });
$('#buddyStage').onclick = openComposer;
$('#sendDirective').onclick = sendDirective;
window.addEventListener('hashchange', () => { const m = location.hash.slice(1); if (VIEWS[m]) { MODE = m; render(); } });

function ingest(s) {
  STATE = s;
  // diegetic staleness: if the snapshot stops changing AND nothing is live, the clock stops
  ingest._beats = (JSON.stringify(s.events) === ingest._lastEv) ? (ingest._beats || 0) + 1 : 0;
  ingest._lastEv = JSON.stringify(s.events);
  render();
}

function connect() {
  const es = new EventSource('/api/events');
  es.onmessage = ev => { try { ingest(JSON.parse(ev.data)); $('#staleVeil').hidden = true; } catch (e) {} };
  es.onerror = () => {
    $('#deskclock').classList.add('stopped');
    setPica('sleep');
    // fall back to polling if the stream dies
    if (!connect._poll) connect._poll = setInterval(() => fetch('/api/state').then(r => r.json()).then(ingest).catch(() => $('#staleVeil').hidden = false), 5000);
  };
}

applyLamp();
const startMode = location.hash.slice(1); if (VIEWS[startMode]) MODE = startMode;
const STATIC = location.search.includes('static'); // one-shot render (snapshots/embeds): no SSE
// First paint from the server-seeded snapshot (instant; no async dependency), then live.
if (window.__STATE__) ingest(window.__STATE__);
else fetch('/api/state').then(r => r.json()).then(ingest).catch(() => $('#staleVeil').hidden = false);
if (!STATIC) { connect(); setInterval(applyLamp, 60000); }
