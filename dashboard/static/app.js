/* Vivarium frontend — a living lab world, Newt's mind, and the control console.
   The world is a hand-drawn Canvas-2D scene (no deps, no build): lab-rooms per workflow
   stage, a cinematic camera, a hand-drawn procedural creature (Newt the orchestrator), and
   one creature per worker/subagent. Everything below the Scene engine is the control surface. */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const hhmm = ts => (ts || '').slice(11, 16);
const num = v => typeof v === 'number' ? (+v).toPrecision(4) : esc(v);
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = t => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);

const LIFECYCLE = ['seed', 'triaged', 'lit-review', 'scoping', 'proposal', 'active', 'analysis', 'writing', 'internal-review', 'final'];
const lifeIdx = s => { const i = LIFECYCLE.indexOf(s); return i < 0 ? 99 : i; };
// kept for the panels (Projects / In flight): a glyph per lifecycle stage
const PLANT = ['🌰', '🌱', '🌿', '☘️', '🪴', '🪴', '🌻', '🌷', '💐', '🌳'];
function plantFor(state) {
  if (state === 'killed') return '🍂';
  if (state === 'parked') return '🌙';
  const i = lifeIdx(state); return i < 99 ? PLANT[i] : '🌱';
}

let STATE = null, MODE = 'terrarium', TARGET = 'hub';

/* ── PI preferences (persisted locally) — toggled in the ⚙ Settings panel ─────── */
const PREF_DEFAULTS = { narrate: false, ambient: true, density: 'comfortable', legend: true, status: true, keyOpen: false };
let PREFS = (() => { try { return { ...PREF_DEFAULTS, ...JSON.parse(localStorage.getItem('viv-prefs') || '{}') }; } catch (e) { return { ...PREF_DEFAULTS }; } })();
function applyPrefs() {
  document.body.dataset.density = PREFS.density;
  document.body.classList.toggle('no-status', !PREFS.status);
  document.body.classList.toggle('no-legend', !PREFS.legend);
  if (typeof Scene !== 'undefined' && Scene && Scene.setAmbient) Scene.setAmbient(PREFS.ambient);
}
function setPref(k, v) { PREFS[k] = v; try { localStorage.setItem('viv-prefs', JSON.stringify(PREFS)); } catch (e) {} applyPrefs(); if (STATE) render(); if (!$('#settings').hidden) renderSettings(); }

/* ── overlay bookkeeping ──────────────────────────────────────────────────────
   When ANY panel/modal/drawer is open, the World's HUD (Newt's gate beacon, his speech bubble, the
   listening command bar) must recede so nothing floats over a "screen". One source of truth — the DOM
   itself — drives a `body.overlay-open` class, so it can never drift out of sync with the individual
   open/close fns. Every opener/closer calls syncOverlay() as its last act; render() calls it too. */
const OVERLAY_IDS = ['#sheet', '#modal', '#drawer', '#inspector', '#detail', '#attention', '#help', '#settings', '#palette'];
let OVERLAY_OPEN = false;
function syncOverlay() {
  OVERLAY_OPEN = OVERLAY_IDS.some(id => { const n = $(id); return n && !n.hidden; });
  document.body.classList.toggle('overlay-open', OVERLAY_OPEN);
  if (OVERLAY_OPEN) { const l = $('#lantern'); if (l) l.hidden = true; const sp = $('#speech'); if (sp) sp.hidden = true; }
  else if (STATE) renderMeters(STATE);   // restore the beacon if a gate is still waiting
}
// The right-side drawers (detail · inspector · attention · command sheet · settings) are mutually
// exclusive — only one open at a time. Each opener calls this first (a no-op on itself).
function closeRightDrawers(except) {
  const drawers = [['#detail', null], ['#inspector', null], ['#attention', null], ['#sheet', '#sheetScrim'], ['#settings', '#settingsScrim']];
  drawers.forEach(([id, scrim]) => { if (id === except) return; const n = $(id); if (n && !n.hidden) { n.hidden = true; if (scrim) { const sc = $(scrim); if (sc) sc.hidden = true; } } });
}

/* ── Newt's mind: pose + speech ─────────────────────────────────────────── */
const POSES = ['gate', 'failure', 'success', 'regen', 'running', 'writing', 'letter', 'idle', 'sleep'];
function newtPoseFor(s) {
  if (!s || s.cold) return 'sleep';
  if (s.gates_waiting > 0) return 'gate';
  if ((s.events || []).slice(-6).some(e => e.kind === 'escalation')) return 'gate';
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
function setPose(p) {
  const n = $('#newt');
  if (n) { POSES.forEach(x => n.classList.remove('pose-' + x)); n.classList.add('pose-' + p); }
  const cb = $('#commandBar');
  if (cb) { POSES.forEach(x => cb.classList.remove('pose-' + x)); cb.classList.add('pose-' + p); }
  Scene.setPose(p);
}
function speak(html) {
  const s = $('#speech'); if (!html) { s.hidden = true; return; }
  s.innerHTML = html; s.hidden = false; clearTimeout(speak._t); speak._t = setTimeout(() => s.hidden = true, 8000);
}
function narrate(s) {
  if (!PREFS.narrate) { $('#speech').hidden = true; return; }   // Newt's chatter is opt-in (⚙ Settings)
  const ev = s.events || [], last = ev[ev.length - 1];
  if (!last || last.ts === narrate._ts) return; narrate._ts = last.ts;
  if (s.gates_waiting > 0) return speak(`<b>${s.gates_waiting} gate(s)</b> waiting — tap the beacon.`);
  const d = last.detail ? esc(last.detail) : '';
  const m = last.data && last.data.metrics ? Object.entries(last.data.metrics).slice(0, 2).map(([k, v]) => `<span class="mono">${k}=${num(v)}</span>`).join(' ') : '';
  let t;
  switch (last.kind) {
    case 'run_finished': t = `<span class="mono">${esc(last.run_id || '')}</span> ${esc(last.status || '')} ${m}`; break;
    case 'run_started': t = `tending <span class="mono">${esc(last.run_id || '')}</span>`; break;
    case 'escalation': t = `⚠ <b>${esc(last.source || 'a project')}</b> needs you · ${d}`; break;
    case 'approach_ideate': t = `dreaming up new approaches · ${d}`; break;
    case 'decision_revisit': t = `regrowing — reopened a decision · ${d}`; break;
    case 'frontier_expand': t = `branching new lines · ${d}`; break;
    case 'replan': t = `re-planning · ${d}`; break;
    case 'kill': t = `released: ${d}`; break;
    default: t = d || last.kind;
  }
  speak(t);
}

/* ── meters ─────────────────────────────────────────────────────────────── */
function renderMeters(s) {
  const gb = $('#gateBadge'), lan = $('#lantern');
  if (s.gates_waiting > 0) { gb.hidden = false; gb.textContent = s.gates_waiting; } else gb.hidden = true;
  // the beacon lives in the World HUD: only when we're in the World and no overlay is up (it must
  // never float over a panel/modal). The topbar gate badge above stays visible in every view.
  if (s.gates_waiting > 0 && MODE === 'terrarium' && !OVERLAY_OPEN) { lan.hidden = false; $('#lanternN').textContent = s.gates_waiting; }
  else lan.hidden = true;
  const ff = $('#fireflies'); ff.innerHTML = ''; ff.title = `${s.slots.in_use}/${s.slots.cap} compute slots in use`;
  for (let i = 0; i < s.slots.cap; i++) ff.appendChild(el('i', i < s.slots.in_use ? 'lit' : ''));
  const c = $('#clock'); c.textContent = hhmm(s.now); c.classList.remove('stopped');
}

/* ── the World view: the canvas IS the scene; the DOM only holds a cold note */
function sparkline(series) {
  if (!series || series.length < 2) return '';
  const v = series.map(p => p.value), mn = Math.min(...v), mx = Math.max(...v), rng = mx - mn || 1, w = 150, h = 22;
  const pts = v.map((x, i) => `${(i * w / (v.length - 1)).toFixed(1)},${(h - ((x - mn) / rng) * (h - 4) - 2).toFixed(1)}`).join(' ');
  return `<svg class="spark" width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="var(--leaf-d)" stroke-width="1.6"/></svg>`;
}
function renderScene(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  if (s.cold) {
    stage.appendChild(el('div', 'coldstart', `<div class="big">the lab is quiet</div>
      <p>nothing stirring yet. open a session and run <code>/setup-lab</code>, then <code>/ideate</code>.<br>
      Newt is curled up in the dark until the first idea arrives.</p>`));
  }
  // when populated, the World view is the bare canvas — rooms, creatures, and Newt live there.
}

/* ── panels ─────────────────────────────────────────────────────────────── */
// a /autopilot campaign — nests the projects it delegates (status · budget · members → drill in)
function campaignBudget(c) {
  const b = c.budget; if (!b || typeof b !== 'object') return '';
  const cap = b.total_max_minutes || b.per_run_max_minutes || b.full_runs;
  const bits = [];
  if (b.full_runs != null) bits.push(`${b.full_runs} FULL runs`);
  if (b.total_max_minutes != null) bits.push(`${b.total_max_minutes}m total`);
  if (b.expires) bits.push(`expires ${esc(String(b.expires))}`);
  if (b.pi_signed != null) bits.push(b.pi_signed ? 'PI-signed' : 'unsigned');
  return bits.length ? `<div class="camp-budget">${bits.join(' · ')}</div>` : '';
}
function renderCampaigns(s, host) {
  const camps = s.campaigns || []; if (!camps.length) return;
  host.appendChild(el('div', 'd-sec', 'Campaigns'));
  const wrap = el('div', 'camp-list');
  camps.forEach(c => {
    const members = (c.projects || []).map(pid => (s.items || []).find(it => it.id === pid)).filter(Boolean);
    const nWork = members.reduce((n, it) => n + (it.n_workers || 0), 0);
    const fly = members.reduce((n, it) => n + (it.inflight || []).length, 0);
    const card = el('div', 'camp-card');
    card.innerHTML = `<div class="camp-head"><span class="camp-name">${esc(c.title || c.name)}</span>
      <span class="camp-status st-${esc(c.status || 'active')}">${esc(c.status || 'active')}</span></div>
      <div class="camp-meta">${members.length} project${members.length === 1 ? '' : 's'} · <b>${nWork}</b> agents${fly ? ` · ${fly} in flight` : ''}${c.signed ? ` · signed ${esc(String(c.signed))}` : ''}</div>
      ${campaignBudget(c)}`;
    const chips = el('div', 'camp-members');
    (members.length ? members : []).forEach(it => {
      const ch = el('button', 'camp-chip', `${plantFor(it.state)} ${esc(it.title || it.id)}${it.n_workers ? ` · ${it.n_workers}` : ''}`);
      ch.title = 'open ' + (it.title || it.id);
      ch.onclick = () => (it.has_project ? (enterTerrarium(), Scene.focusProject(it.id)) : openDetail(it.id));
      chips.appendChild(ch);
    });
    (c.projects || []).filter(pid => !members.find(m => m.id === pid)).forEach(pid => chips.appendChild(el('span', 'camp-chip ghost', esc(pid))));
    card.appendChild(chips);
    wrap.appendChild(card);
  });
  host.appendChild(wrap);
}
function renderShelf(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>Projects</h2><p class="lede">every project up close — steer it, or run a read-only check.</p>');
  renderCampaigns(s, p);
  if (!s.items.length) { p.innerHTML += '<div class="empty-note"><span class="en-ico">🌱</span>nothing under way yet — run <code>/ideate</code> to plant the first idea.</div>'; stage.appendChild(p); return; }
  if ((s.campaigns || []).length) p.appendChild(el('div', 'd-sec', 'All projects'));
  const grid = el('div', 'cardgrid');
  s.items.forEach(it => {
    const fly = it.inflight || [];
    const c = el('div', 'pcard');
    let chips = `<span class="chip state">${esc(it.state)}</span>` + (it.loop_active ? '<span class="chip live">loop</span>' : '');
    if (it.n_workers) chips += `<span class="chip work">${it.n_workers} working</span>`;
    fly.forEach(r => chips += `<span class="chip ${r.state === 'stalled' ? 'stalled' : 'live'}">${esc(r.run_id)} ${r.state}</span>`);
    c.innerHTML = `<h3>${plantFor(it.state)} ${esc(it.title || it.id)}</h3><div class="row">${chips}</div>
      <div class="mono" style="font-size:.78rem;color:var(--ink-soft)">${esc(it.next || '')}</div>
      ${sparkline(it.best && it.best.series)}`;
    const br = el('div', 'btnrow');
    br.appendChild(btn('details', '', () => openDetail(it.id)));
    br.appendChild(btn('command ▸', 'go', () => openSheet(it.id)));
    if (it.has_project) {
      br.appendChild(btn('enter lab', '', () => { enterTerrarium(); Scene.focusProject(it.id); }));
      br.appendChild(btn('status', 'tool', () => runTool('status', it.id)));
      br.appendChild(btn('compare', 'tool', () => runTool('compare', it.id)));
      br.appendChild(btn('inbox', 'tool', () => runTool('inbox', it.id)));
    }
    c.appendChild(br); grid.appendChild(c);
  });
  p.appendChild(grid); stage.appendChild(p);
}
function btn(label, cls, fn) { const b = el('button', 'btn ' + (cls || ''), label); b.onclick = fn; return b; }

// Activity = the two live-state views the PI checks together: "Needs you" (the gates) + "In flight"
// (running runs). Merged from the old Gates + In flight tabs. The route key stays `gates` so the
// gate badge, #gates deep-links, and the beacon's click target are all preserved.
function renderGates(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>Activity</h2><p class="lede">what needs you, and what’s running right now. Gate 1 & 2 you can approve here; Gate 3 is always done in a session.</p>');
  const cols = el('div', 'activity-cols');

  // ── Needs you (left): the gates ──
  const need = el('div', 'act-col');
  need.appendChild(el('div', 'd-sec', 'Needs you'));
  const waiting = s.items.filter(it => it.gate);
  if (!waiting.length) need.appendChild(el('div', 'empty-note sm', '<span class="en-ico">✓</span>nothing needs your sign-off.'));
  else {
    const wrap = el('div', 'letters');
    waiting.forEach(it => {
      const g = it.gate;
      const what = g === 1 ? `review the proposal` : g === 3 ? `read the paper + meta-review` : `pre-authorize the FULL runs (Gate-2 envelope)`;
      const card = el('div', 'letter' + (g === 3 ? ' g3' : ''));
      card.innerHTML = `<div class="seal">${g}</div><h3>${esc(it.title || it.id)} — Gate ${g}</h3><div class="sub">${esc(it.next || what)}</div>`;
      const row = el('div', 'btnrow');
      const previewLabel = g === 1 ? 'read the proposal ▸' : g === 3 ? 'read claims + review ▸' : 'review the envelope ▸';
      row.appendChild(btn(previewLabel, 'tool', () => openDoc('gate', it.id, g, `Gate ${g} · ${it.title || it.id}`)));   // read-only preview, in-dashboard
      if (g !== 3) row.appendChild(btn(`✓ Approve Gate ${g} (PI)`, 'go', () => openGate(it.id, g)));
      card.appendChild(row);
      if (g === 3) card.appendChild(el('div', 'sub', 'Gate 3 (anything leaving the lab) is never one-click — open a session and run /finalize.'));
      wrap.appendChild(card);
    });
    need.appendChild(wrap);
  }
  cols.appendChild(need);

  // ── In flight (right): each running run reads as project · STAGE (smoke/pilot/full) · how much of its
  //    time budget is used (the watchdog-enforced budget — the one thing we can honestly track over time)
  //    · alive/stalled. When nothing is executing, show the active projects and the lifecycle stage they sit in. ──
  const fly = el('div', 'act-col');
  fly.appendChild(el('div', 'd-sec', 'In flight'));
  const live = [];
  s.items.forEach(it => (it.inflight || []).forEach(r => live.push({ ...r, slug: it.id, title: it.title || it.id })));
  if (live.length) {
    const wrap = el('div', 'flights');
    live.forEach(r => {
      const pct = r.budget_min ? Math.min(100, r.elapsed_s / (r.budget_min * 60) * 100) : 0;
      const stg = (r.stage || '').toString();
      const metric = Object.keys(r.last || {}).length ? Object.entries(r.last).slice(0, 1).map(([k, v]) => `${esc(k)} ${num(v)}`).join('') : '';
      const card = el('div', 'flight' + (r.state === 'stalled' ? ' stalled' : ''));
      card.innerHTML =
        `<div class="fl-top"><span class="fl-proj">${esc(r.title)}</span>${stg ? `<span class="stage-chip s-${esc(stg.toLowerCase())}">${esc(stg)}</span>` : ''}<span class="fl-state ${r.state === 'stalled' ? 'stalled' : 'live'}">${r.state === 'stalled' ? '◴ stalled' : '● running'}</span></div>
         <div class="fl-mid"><span class="barwrap"><i style="width:${pct.toFixed(0)}%"></i></span></div>
         <div class="fl-bot"><span class="mono">${esc(r.run_id)}</span><span>${Math.round(r.elapsed_s / 60)}m / ${r.budget_min || '∞'}m budget${metric ? ` · ${metric}` : ''}</span></div>`;
      card.title = 'open ' + r.title;
      card.onclick = () => { enterTerrarium(); Scene.focusProject(r.slug); };
      wrap.appendChild(card);
    });
    fly.appendChild(wrap);
  } else {
    fly.appendChild(el('div', 'quiet sm', '🌙 nothing executing right now.'));
    const active = (s.items || []).filter(it => it.has_project && it.state !== 'parked' && it.state !== 'killed');
    if (active.length) {
      fly.appendChild(el('div', 'leg-sec', 'Active projects · stage'));
      const wrap = el('div', 'flights');
      active.forEach(it => {
        const card = el('div', 'flight idle');
        card.innerHTML = `<div class="fl-top"><span class="fl-proj">${esc(it.title || it.id)}</span><span class="stage-chip s-state">${esc(it.state)}</span>${it.loop_active ? '<span class="fl-state live">● loop</span>' : ''}</div>`;
        card.title = 'open ' + (it.title || it.id);
        card.onclick = () => { enterTerrarium(); Scene.focusProject(it.id); };
        wrap.appendChild(card);
      });
      fly.appendChild(wrap);
    }
  }
  cols.appendChild(fly);

  p.appendChild(cols); stage.appendChild(p);
}

let LEDGER_Q = '', LEDGER_HIDE = false, LEDGER_SHOWHIDDEN = false;
// withdraw a directive — appends an append-only "withdraw" marker (never erases the audit trail)
async function withdrawDirective(target, id) {
  try { await fetch('/api/withdraw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target, id }) }); toast(`withdrew ${id}`); }
  catch (e) { toast('could not reach the vivarium server'); }
}
// ── ledger decluttering. The lab's event bus on disk is APPEND-ONLY audit (hard rule) — we never
// erase it. Instead the PI can HIDE rows from THIS view (stored locally in the browser); "restore"
// brings them all back. So you get a tidy ledger without ever touching the integrity of the record.
const _ls = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }, del(k) { try { localStorage.removeItem(k); } catch (e) {} } };
function evKey(e) { return `${e.ts || ''}|${e.source || ''}|${e.kind || ''}|${e.detail || ''}`; }
function ledgerDismissed() { try { return new Set(JSON.parse(_ls.get('viv-ledger-dismissed', '[]'))); } catch (e) { return new Set(); } }
function dismissEvent(e) { const set = ledgerDismissed(); set.add(evKey(e)); _ls.set('viv-ledger-dismissed', JSON.stringify([...set].slice(-3000))); renderLedger(STATE); }
function restoreEvent(e) { const set = ledgerDismissed(); set.delete(evKey(e)); _ls.set('viv-ledger-dismissed', JSON.stringify([...set])); renderLedger(STATE); }
function clearLedgerView() { const evs = (STATE && STATE.events) || []; if (!evs.length) return; _ls.set('viv-ledger-clearedAt', evs[evs.length - 1].ts || ''); toast('ledger view cleared — the on-disk audit log is untouched'); renderLedger(STATE); }
function restoreLedgerView() { _ls.del('viv-ledger-dismissed'); _ls.del('viv-ledger-clearedAt'); LEDGER_SHOWHIDDEN = false; toast('restored every hidden row'); renderLedger(STATE); }
function renderLedger(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>The ledger</h2><p class="lede">commands you’ve issued (withdrawable) and every signal the lab has emitted. Tidy your view freely — the lab’s on-disk audit log is append-only and never erased.</p>');
  const Q = LEDGER_Q.trim().toLowerCase();
  const match = (...parts) => !Q || parts.join(' ').toLowerCase().includes(Q);
  const dismissed = ledgerDismissed(), clearedAt = _ls.get('viv-ledger-clearedAt', '');
  const hiddenOf = e => dismissed.has(evKey(e)) || (clearedAt && (e.ts || '') <= clearedAt);
  const allEv = (s.events || []).slice().reverse().filter(e => match(e.source, e.kind, e.detail));
  const hiddenCount = allEv.filter(hiddenOf).length;

  // toolbar: search · hide-resolved (directives) · clear view · show hidden · restore
  const bar = el('div', 'ledger-bar');
  const q = el('input', 'ledger-q'); q.type = 'search'; q.placeholder = 'filter the ledger…'; q.value = LEDGER_Q;
  q.oninput = () => { LEDGER_Q = q.value; renderLedger(STATE); setTimeout(() => { const n = $('.ledger-q'); if (n) { n.focus(); n.selectionStart = n.selectionEnd = n.value.length; } }, 0); };
  bar.appendChild(q);
  const tg = el('button', 'btn' + (LEDGER_HIDE ? ' go' : ''), LEDGER_HIDE ? 'showing open only' : 'hide resolved'); tg.onclick = () => { LEDGER_HIDE = !LEDGER_HIDE; renderLedger(STATE); };
  bar.appendChild(tg);
  bar.appendChild(btn('clear event view', '', clearLedgerView));
  if (hiddenCount) { const sh = el('button', 'btn' + (LEDGER_SHOWHIDDEN ? ' go' : ''), (LEDGER_SHOWHIDDEN ? 'hiding ' : 'show ') + hiddenCount + ' hidden'); sh.onclick = () => { LEDGER_SHOWHIDDEN = !LEDGER_SHOWHIDDEN; renderLedger(STATE); }; bar.appendChild(sh); bar.appendChild(btn('restore all', 'warn', restoreLedgerView)); }
  p.appendChild(bar);

  let dir = [...(s.directives || []).map(d => ({ ...d, target: 'hub' })), ...(s.items || []).flatMap(it => (it.directives || []).map(d => ({ ...d, target: it.id })))];
  if (LEDGER_HIDE) dir = dir.filter(d => d.state === 'pending' || d.state === 'seen');
  dir = dir.filter(d => match(d.id, d.target, d.text, d.action, d.state));
  let h = '<h3 style="font-family:var(--display)">Commands & notes</h3><table><thead><tr><th>id</th><th>target</th><th>what</th><th>state</th><th>evidence</th><th></th></tr></thead><tbody>';
  if (!dir.length) h += '<tr><td colspan="6" class="sub">nothing here</td></tr>';
  dir.forEach(d => {
    const what = d.kind === 'command' ? `<span class="mono">${esc(d.action)}</span> ${esc(JSON.stringify(d.args || {}) === '{}' ? '' : JSON.stringify(d.args))} ${esc(d.text || '')}` : esc(d.text || '');
    const ev = d.ack && d.ack.evidence ? `<span class="mono">${esc(d.ack.evidence)}</span>` : (d.state === 'done' ? '<span class="unresolved">— none —</span>' : '');
    const canWithdraw = d.state === 'pending' || d.state === 'seen';
    const wd = canWithdraw ? `<button class="x-row" data-wd="${esc(d.target)}|${esc(d.id)}" title="withdraw this directive">✕</button>` : '';
    h += `<tr><td class="mono">${esc(d.id)}</td><td>${esc(d.target)}</td><td>${what}</td><td><span class="dchip ${d.state}${d.state === 'done' && !(d.ack && d.ack.evidence) ? ' noevidence' : ''}">${esc(d.state)}</span></td><td>${ev}</td><td>${wd}</td></tr>`;
  });
  h += `</tbody></table><h3 style="font-family:var(--display)">Event log <span class="sub" style="font-weight:400">· append-only audit${clearedAt || dismissed.size ? ` · ${hiddenCount} hidden from view` : ''}</span></h3><table><thead><tr><th>time</th><th>source</th><th>kind</th><th>detail</th><th></th></tr></thead><tbody>`;
  const evs = (LEDGER_SHOWHIDDEN ? allEv : allEv.filter(e => !hiddenOf(e))).slice(0, 200);
  if (!evs.length) h += `<tr><td colspan="5" class="sub">${allEv.length ? 'all caught up — nothing to show' : 'no matching events'}</td></tr>`;
  evs.forEach((e, i) => {
    const hidden = hiddenOf(e);
    const n = e.data && e.data.metrics ? ' · ' + Object.entries(e.data.metrics).slice(0, 1).map(([k, v]) => `${k}=${num(v)}`).join('') : '';
    const act = hidden ? `<button class="x-row ev-act" data-evi="${i}" data-evact="restore" title="restore to view">↩</button>` : `<button class="x-row ev-act" data-evi="${i}" data-evact="dismiss" title="hide from view (audit log untouched)">✕</button>`;
    h += `<tr${hidden ? ' class="ev-hidden"' : ''}><td class="mono">${hhmm(e.ts)}</td><td>${esc(e.source)}</td><td class="mono">${esc(e.kind)}</td><td>${esc(e.detail || '')}${esc(n)}</td><td>${act}</td></tr>`;
  });
  h += '</tbody></table>';
  const body = el('div', '', h);
  body.querySelectorAll('[data-wd]').forEach(b => b.onclick = () => { const [tg2, id] = b.dataset.wd.split('|'); withdrawDirective(tg2, id); b.closest('tr').style.opacity = '.4'; });
  body.querySelectorAll('[data-evi]').forEach(b => b.onclick = () => { const e = evs[+b.dataset.evi]; if (!e) return; b.dataset.evact === 'restore' ? restoreEvent(e) : dismissEvent(e); });
  p.appendChild(body); stage.appendChild(p);
}

/* ── the Agents roster: every live agent/subagent, grouped by where it works ── */
function renderRoster(s) {
  const stage = $('#stage'); stage.innerHTML = '';
  const p = el('section', 'panel', '<h2>Agents</h2><p class="lede">every agent &amp; subagent at work right now — grouped by where it works. Click one to read its own action log.</p>');
  const wk = (s.workers || []).filter(w => w.status !== 'done');
  if (!wk.length) { p.innerHTML += '<div class="empty-note"><span class="en-ico">😴</span>no agents at work right now — the lab is quiet.</div>'; stage.appendChild(p); return; }
  const groups = {};
  wk.forEach(w => { const key = w.project ? 'project:' + w.project : (w.idea ? 'idea:' + w.idea : 'hub'); (groups[key] = groups[key] || []).push(w); });
  const titleFor = it => { const o = (s.items || []).find(x => x.id === it); return o && (o.title || o.id) || it; };
  const label = k => k === 'hub' ? 'The Lab (hub)' : k.startsWith('project:') ? 'project · ' + titleFor(k.slice(8)) : 'idea · ' + titleFor(k.slice(5));
  Object.keys(groups).sort((a, b) => (a === 'hub' ? -1 : b === 'hub' ? 1 : a.localeCompare(b))).forEach(k => {
    p.appendChild(el('div', 'roster-grouphead', esc(label(k)) + ` · ${groups[k].length}`));
    const grid = el('div', 'roster-grid');
    groups[k].forEach(w => {
      const role = ROLE_ORDER.includes(w.role) ? w.role : 'other';
      const last = (w.recent_actions || []).slice(-1)[0];
      const c = el('button', 'wcard ' + (w.status === 'working' ? 'on' : 'idle'),
        `<div class="wc-top"><span class="sw role-${role}"></span><span class="wc-id">${esc(w.worker_id)}</span><span class="wc-st">${esc(w.status)}</span></div>
         <div class="wc-role">${esc(ROLE_LABEL[role] || w.role)}</div>
         <div class="wc-last">${last ? esc(last.text) : '— no actions logged —'}</div>
         <div class="wc-n">${w.n_actions || 0} action${w.n_actions === 1 ? '' : 's'}</div>`);
      c.onclick = () => openWorkerInspector(w.worker_id);
      grid.appendChild(c);
    });
    p.appendChild(grid);
  });
  stage.appendChild(p);
}

/* ── command palette (press / or the ⌕ button): jump to tabs · rooms · projects · actions ── */
function paletteActions() {
  const out = [];
  [['terrarium', 'World'], ['shelf', 'Projects'], ['agents', 'Agents'], ['gates', 'Activity'], ['ledger', 'Ledger']]
    .forEach(([m, l]) => out.push({ label: 'Go to ' + l, hint: 'tab', run: () => { MODE = m; location.hash = m; render(); Scene.setView(m); } }));
  ROOM_KEYS.forEach(k => out.push({ label: 'Zoom to ' + ROOM_LABEL[k], hint: 'room', run: () => { enterTerrarium(); Scene.goRoom(k); } }));
  (STATE && STATE.items || []).forEach(it => {
    const nm = it.title || it.id;
    if (it.has_project) out.push({ label: 'Enter lab · ' + nm, hint: 'project', run: () => { enterTerrarium(); Scene.focusProject(it.id); } });
    out.push({ label: 'Details · ' + nm, hint: 'info', run: () => openDetail(it.id) });
    out.push({ label: 'Command · ' + nm, hint: 'steer', run: () => openSheet(it.id) });
    if (it.gate && it.gate !== 3) out.push({ label: `Approve Gate ${it.gate} · ${nm}`, hint: 'gate', run: () => openGate(it.id, it.gate) });
  });
  out.push({ label: 'Command the lab (Newt)', hint: 'hub', run: () => openSheet('hub') });
  out.push({ label: 'Open · Lab knowledge (findings / failures / open questions)', hint: 'read', run: () => openDoc('knowledge', null, null, 'Lab knowledge') });
  out.push({ label: 'Open · Settings', hint: 'prefs', run: openSettings });
  out.push({ label: 'Open · History timeline (replay this session)', hint: 'time', run: () => { if ($('#scrubber').hidden) toggleScrubber(); } });
  out.push({ label: 'Toggle light / dark', hint: 'theme', run: cycleLamp });
  return out;
}
let PAL_SEL = 0;
function openPalette() { $('#paletteScrim').hidden = false; $('#palette').hidden = false; const i = $('#paletteInput'); i.value = ''; PAL_SEL = 0; renderPalette(); i.focus(); syncOverlay(); }
function closePalette() { $('#paletteScrim').hidden = true; $('#palette').hidden = true; syncOverlay(); }
function paletteMatches() { const q = $('#paletteInput').value.trim().toLowerCase(); const all = paletteActions(); return q ? all.filter(a => (a.label + ' ' + a.hint).toLowerCase().includes(q)) : all; }
function renderPalette() {
  const list = $('#paletteList'); list.innerHTML = ''; const m = paletteMatches();
  PAL_SEL = clamp(PAL_SEL, 0, Math.max(0, m.length - 1));
  m.slice(0, 40).forEach((a, i) => {
    const row = el('div', 'pal-row' + (i === PAL_SEL ? ' on' : ''), `<span class="pal-l">${esc(a.label)}</span><span class="pal-h">${esc(a.hint)}</span>`);
    row.onmouseenter = () => { PAL_SEL = i; [...list.children].forEach((c, j) => c.classList.toggle('on', j === i)); };
    row.onclick = () => { closePalette(); a.run(); };
    list.appendChild(row);
  });
  if (!m.length) list.appendChild(el('div', 'pal-row sub', 'no matches'));
}
function paletteKey(e) {
  if (e.key === 'Escape') return closePalette();
  const m = paletteMatches();
  if (e.key === 'ArrowDown') { PAL_SEL = Math.min(m.length - 1, PAL_SEL + 1); renderPalette(); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { PAL_SEL = Math.max(0, PAL_SEL - 1); renderPalette(); e.preventDefault(); }
  else if (e.key === 'Enter') { const a = m[PAL_SEL]; if (a) { closePalette(); a.run(); } }
}

/* ── onboarding / help overlay (the ? button; auto-shown on first visit) ────── */
function openHelp() {
  const demo = location.search.includes('demo'), b = $('#helpDemo');
  if (b) b.textContent = demo ? '⤺ exit demo mode' : '▶ open demo mode';
  $('#helpScrim').hidden = false; $('#help').hidden = false; syncOverlay();
}
function toggleDemo() { const demo = location.search.includes('demo'); location.href = location.pathname + (demo ? '' : '?demo'); }
function closeHelp() { $('#helpScrim').hidden = true; $('#help').hidden = true; try { localStorage.setItem('viv-seen-help', '1'); } catch (e) {} syncOverlay(); }
function maybeAutoHelp() { if (location.search.includes('static')) return; let seen = '1'; try { seen = localStorage.getItem('viv-seen-help'); } catch (e) {} if (!seen) setTimeout(openHelp, 900); }

/* ── settings drawer (⚙): preferences · theme · knowledge · guide ────────────── */
// Theme is a simple, persisted Light / Dark toggle (default Dark — the scene is dark-first). Stored as
// 'light'|'dark'; legacy 'day'/'night'/'auto' values normalize (light|day → light; everything else → dark).
function lampMode() { let m = null; try { m = localStorage.getItem('lamp'); } catch (e) {} return (m === 'light' || m === 'day') ? 'light' : 'dark'; }
function setLampMode(m) { try { localStorage.setItem('lamp', m); } catch (e) {} applyLamp(); if (!$('#settings').hidden) renderSettings(); }
function cycleLamp() { const n = lampMode() === 'dark' ? 'light' : 'dark'; setLampMode(n); toast(`theme: ${n}`); }
function segRow(label, val, opts, fn) {
  const row = el('div', 'set-row'); row.appendChild(el('span', 'set-label', esc(label)));
  const seg = el('div', 'seg');
  opts.forEach(([v, l]) => { const b = el('button', 'seg-b' + (v === val ? ' on' : ''), esc(l)); b.onclick = () => fn(v); seg.appendChild(b); });
  row.appendChild(seg); return row;
}
function toggleRow(label, on, fn, sub) {
  const row = el('div', 'set-row');
  row.appendChild(el('span', 'set-label', `${esc(label)}${sub ? `<small>${esc(sub)}</small>` : ''}`));
  const sw = el('button', 'switch' + (on ? ' on' : '')); sw.setAttribute('role', 'switch'); sw.setAttribute('aria-checked', String(on));
  sw.onclick = () => fn(!on); row.appendChild(sw); return row;
}
function renderSettings() {
  const body = $('#settingsBody'); body.innerHTML = '';
  body.appendChild(el('div', 'd-sec', 'Appearance'));
  body.appendChild(segRow('Theme', lampMode(), [['light', 'Light'], ['dark', 'Dark']], setLampMode));
  body.appendChild(segRow('Density', PREFS.density, [['comfortable', 'Cozy'], ['compact', 'Compact']], v => setPref('density', v)));
  body.appendChild(el('div', 'd-sec', 'On screen'));
  body.appendChild(toggleRow('Status line', PREFS.status, v => setPref('status', v), 'the live pulse strip'));
  body.appendChild(toggleRow('The Key', PREFS.legend, v => setPref('legend', v), 'colour & role legend'));
  body.appendChild(toggleRow('Newt narration', PREFS.narrate, v => setPref('narrate', v), 'speech-bubble commentary'));
  body.appendChild(toggleRow('Ambient motion', PREFS.ambient, v => setPref('ambient', v), 'drifting motes & footstep dust'));
  body.appendChild(el('div', 'd-sec', 'More'));
  const more = el('div', 'set-more');
  more.appendChild(btn('Lab knowledge', '', () => { closeSettings(); openDoc('knowledge', null, null, 'Lab knowledge'); }));
  more.appendChild(btn('Show the guide', '', () => { closeSettings(); openHelp(); }));
  body.appendChild(more);
}
function openSettings() { closeRightDrawers('#settings'); renderSettings(); $('#settingsScrim').hidden = false; $('#settings').hidden = false; syncOverlay(); }
function closeSettings() { $('#settingsScrim').hidden = true; $('#settings').hidden = true; syncOverlay(); }

/* ── attention inbox (the bell): everything that wants the PI, prioritised ── */
function attentionItems(s) {
  const out = [];
  (s.items || []).filter(it => it.gate).forEach(it => out.push({ sev: it.gate === 3 ? 'g3' : 'gate', icon: '⛓', title: `Gate ${it.gate} · ${it.title || it.id}`, sub: it.next || '', act: it.gate !== 3 ? { label: 'approve', fn: () => openGate(it.id, it.gate) } : null, go: () => openDetail(it.id) }));
  (s.events || []).filter(e => e.kind === 'escalation').slice(-8).reverse().forEach(e => out.push({ sev: 'warn', icon: '⚠', title: `${e.source || 'a project'} needs you`, sub: e.detail || '' }));
  const dirs = [...(s.directives || []).map(d => ({ ...d, target: 'hub' })), ...(s.items || []).flatMap(it => (it.directives || []).map(d => ({ ...d, target: it.id })))];
  dirs.filter(d => d.state === 'pending' || d.state === 'seen').forEach(d => out.push({ sev: 'pending', icon: '✎', title: `pending → ${d.target}`, sub: d.text || d.action || '', act: { label: 'withdraw', fn: () => { withdrawDirective(d.target, d.id); setTimeout(renderAttention, 300); } } }));
  (s.items || []).forEach(it => (it.inflight || []).filter(r => r.state === 'stalled').forEach(r => out.push({ sev: 'warn', icon: '◴', title: `stalled run · ${it.id}`, sub: r.run_id, go: () => openDetail(it.id) })));
  return out;
}
function renderAttention() {
  const s = STATE; if (!s) return;
  const items = attentionItems(s);
  const badge = $('#bellN'); if (items.length) { badge.hidden = false; badge.textContent = items.length; } else badge.hidden = true;
  if ($('#attention').hidden) return;
  const body = $('#attentionBody'); body.innerHTML = '';
  if (!items.length) { body.appendChild(el('div', 'empty-note', 'all clear — nothing needs you.')); return; }
  items.forEach(it => {
    const row = el('div', 'att-row sev-' + it.sev);
    row.innerHTML = `<span class="att-i">${it.icon}</span><span class="att-t"><b>${esc(it.title)}</b><small>${esc(it.sub)}</small></span>`;
    if (it.act) { const b = el('button', 'btn go att-b', it.act.label); b.onclick = it.act.fn; row.appendChild(b); }
    if (it.go) { const t = row.querySelector('.att-t'); t.style.cursor = 'pointer'; t.onclick = it.go; }
    body.appendChild(row);
  });
}
function toggleAttention() { const a = $('#attention'); const opening = a.hidden; if (opening) closeRightDrawers('#attention'); a.hidden = !opening; if (opening) renderAttention(); syncOverlay(); }

/* ── project detail drawer (rich, read-only view + quick controls) ── */
function openDetail(id) {
  const it = (STATE.items || []).find(x => x.id === id); if (!it) return;
  $('#detailTitle').textContent = it.title || it.id;
  let chips = `<span class="chip state">${esc(it.state)}</span>` + (it.loop_active ? '<span class="chip live">loop</span>' : '') + (it.gate ? `<span class="chip note">Gate ${it.gate}</span>` : '') + (it.n_workers ? `<span class="chip work">${it.n_workers} working</span>` : '');
  let h = `<div class="row">${chips}</div><div class="mono" style="font-size:.8rem;color:var(--ink-soft);margin:6px 0">next: ${esc(it.next || '—')}</div>`;
  if (it.best && it.best.series) h += sparkline(it.best.series);
  const fly = it.inflight || [];
  if (fly.length) { h += '<div class="d-sec">In flight</div>'; fly.forEach(r => { const pct = r.budget_min ? Math.min(100, r.elapsed_s / (r.budget_min * 60) * 100) : 0; h += `<div class="nrow ${r.state === 'stalled' ? 'stalled' : ''}"><span class="rid">${esc(r.run_id)}</span><span class="barwrap"><i style="width:${pct.toFixed(0)}%"></i></span><span class="met">${Math.round(r.elapsed_s / 60)}m/${r.budget_min || '∞'}m · ${esc(r.state)}</span><button class="x-row peek" data-peek="${esc(it.id)}|${esc(r.run_id)}" title="peek at this run's metrics">⤢</button></div>`; }); }
  const dirs = (it.directives || []).filter(d => d.state === 'pending' || d.state === 'seen');
  if (dirs.length) { h += '<div class="d-sec">Pending directives</div>'; dirs.forEach(d => h += `<div class="iact"><span class="ix">${esc(d.text || d.action)}</span><span class="ik">${esc(d.state)}</span></div>`); }
  const evs = (it.events || []).slice(-8).reverse();
  if (evs.length) { h += '<div class="d-sec">Recent events</div>'; evs.forEach(e => h += `<div class="iact"><span class="it">${hhmm(e.ts)}</span><span class="ix">${esc(e.kind)} ${esc(e.detail || '')}</span></div>`); }
  const body = $('#detailBody'); body.innerHTML = h;
  body.querySelectorAll('[data-peek]').forEach(b => b.onclick = () => { const [pid, rid] = b.dataset.peek.split('|'); openDoc('run', pid, null, `${pid} · ${rid}`, rid); });
  const br = el('div', 'btnrow');
  br.appendChild(btn('command ▸', 'go', () => { closeDetail(); openSheet(it.id); }));
  if (it.has_project) { br.appendChild(btn('enter lab', '', () => { closeDetail(); enterTerrarium(); Scene.focusProject(it.id); })); br.appendChild(btn('status', 'tool', () => runTool('status', it.id))); br.appendChild(btn('compare', 'tool', () => runTool('compare', it.id))); }
  if (it.gate && it.gate !== 3) br.appendChild(btn(`✓ Gate ${it.gate}`, 'go', () => { closeDetail(); openGate(it.id, it.gate); }));
  body.appendChild(br);
  closeRightDrawers('#detail');   // one right-drawer at a time
  $('#detail').hidden = false; syncOverlay();
}
function closeDetail() { $('#detail').hidden = true; syncOverlay(); }

/* ── legend: who's working (role → colour, with live counts) ──────────────── */
const ROLE_ORDER = ['orchestrator', 'experiment-runner', 'fresh-context-reviewer', 'overseer', 'ideation-critic', 'scoping-advocate'];
const ROLE_LABEL = {
  'orchestrator': 'Orchestrator (Newt)', 'experiment-runner': 'Experiment runner',
  'fresh-context-reviewer': 'Reviewer', 'overseer': 'Overseer',
  'ideation-critic': 'Ideation critic', 'scoping-advocate': 'Scoping advocate', 'other': 'Other agents',
};
let LEGEND_HL = null;
const STATUS_KEYS = [
  ['active',   'Active',           150, it => (it.inflight || []).some(r => r.state !== 'stalled')],
  ['progress', 'Work in progress', 184, it => !(it.inflight || []).length && (it.n_workers > 0 || it.loop_active)],
  ['gate',     'Waiting on PI',     45, it => !!it.gate],
  ['margin',   'Parked / killed',   12, it => it.state === 'parked' || it.state === 'killed'],
  ['dormant',  'Dormant',          214, it => !it.gate && !(it.inflight || []).length && !it.n_workers && !it.loop_active && it.state !== 'parked' && it.state !== 'killed'],
];
// ONE merged "Key" panel (bottom-left): status colours + active projects + role pips. Replaces the
// two separate legends. Buddies are coloured by PROJECT (role is implied by the room + the pip).
function toggleKey() { setPref('keyOpen', !PREFS.keyOpen); }
function renderKey(s) {
  $('#legend').hidden = true;   // the old bottom-right roles legend is folded into this single panel
  const box = $('#statusLegend'), show = MODE === 'terrarium' && !s.cold && PREFS.legend;
  box.hidden = !show; if (!show) return;
  box.classList.toggle('collapsed', !PREFS.keyOpen);   // collapsed → a small "Key" pill; click to expand
  const head = box.querySelector('.legend-head');
  if (head) { head.innerHTML = `Key <span class="leg-chev">${PREFS.keyOpen ? '▾' : '▸'}</span>`; head.title = PREFS.keyOpen ? 'collapse' : 'expand'; head.onclick = toggleKey; }
  const body = $('#statusLegendBody'); body.innerHTML = '';
  body.appendChild(el('div', 'leg-sec', 'Status'));
  STATUS_KEYS.forEach(([key, label, hue, test]) => {
    const n = (s.items || []).filter(test).length;
    const row = el('div', 'legrow' + (n ? ' on' : ' idle'));
    row.innerHTML = `<span class="sw" style="color:hsl(${hue},58%,62%)"></span><span class="nm">${esc(label)}</span><span class="ct">${n}</span>`;
    body.appendChild(row);
  });
  const projs = (s.items || []).filter(it => it.has_project);
  if (projs.length) {
    body.appendChild(el('div', 'leg-sec', 'Projects'));
    projs.forEach(it => {
      const sw = `hsl(${(325 + projectHue(it.id)) % 360},72%,62%)`, n = it.n_workers || 0;
      const row = el('div', 'legrow' + (n ? ' on' : ' idle'));
      row.innerHTML = `<span class="sw" style="color:${sw}"></span><span class="nm">${esc(it.title || it.id)}</span><span class="ct">${n || ''}</span>`;
      row.title = 'open ' + (it.title || it.id);
      row.onclick = () => { enterTerrarium(); Scene.focusProject(it.id); };
      body.appendChild(row);
    });
  }
  const roles = [...new Set((s.workers || []).filter(w => w.status !== 'done' && w.role !== 'orchestrator').map(w => ROLE_ORDER.includes(w.role) ? w.role : 'other'))];
  if (roles.length) {
    body.appendChild(el('div', 'leg-sec', 'Roles · pip'));
    roles.forEach(r => {
      const row = el('div', 'legrow small' + (LEGEND_HL === r ? ' hl' : ''));
      row.innerHTML = `<span class="sw role-${r}"></span><span class="nm">${esc(ROLE_LABEL[r] || r)}</span>`;
      row.onclick = () => { LEGEND_HL = (LEGEND_HL === r ? null : r); Scene.highlight(LEGEND_HL); renderKey(STATE); };
      body.appendChild(row);
    });
  }
}
function renderProjectLegend(s) { renderKey(s); }   // back-compat shims (callers unchanged)
function renderStatusLegend(s) {}

/* ── "now happening": a one-line workflow pulse for at-a-glance tracking ───── */
function renderPulse(s) {
  const p = $('#pulse');
  if (s.cold || MODE !== 'terrarium' || !PREFS.status) { p.hidden = true; return; }
  const loops = (s.items || []).filter(it => it.loop_active).length;
  const fly = (s.items || []).reduce((n, it) => n + (it.inflight || []).length, 0);
  const wk = (s.workers || []).filter(w => w.status !== 'done').length;
  const escN = (s.events || []).slice(-50).filter(e => e.kind === 'escalation').length;
  const bits = [];
  if (loops) bits.push(`<b>${loops}</b> loop${loops > 1 ? 's' : ''}`);
  if (s.gates_waiting) bits.push(`<b>${s.gates_waiting}</b> gate${s.gates_waiting > 1 ? 's' : ''} waiting`);
  if (fly) bits.push(`<b>${fly}</b> in flight`);
  bits.push(`<b>${wk}</b> agent${wk === 1 ? '' : 's'} working`);
  if (s.slots && s.slots.cap) bits.push(`<b>${s.slots.in_use}/${s.slots.cap}</b> compute`);
  if (escN) bits.unshift(`<b>⚠ ${escN}</b> escalation${escN > 1 ? 's' : ''}`);
  p.hidden = false; p.innerHTML = bits.join('<span class="dot">·</span>');
}

const VIEWS = { terrarium: renderScene, shelf: renderShelf, agents: renderRoster, gates: renderGates, ledger: renderLedger };
function render() {
  if (!STATE) return;
  document.body.dataset.mode = MODE;
  $$('.tab').forEach(b => b.classList.toggle('is-active', b.dataset.go === MODE));
  renderMeters(STATE);
  Scene.sync(STATE);                 // the canvas always reflects the lab, behind any panel
  (VIEWS[MODE] || renderScene)(STATE);
  renderProjectLegend(STATE); renderStatusLegend(STATE); renderPulse(STATE); renderAttention(); renderMinimap(Scene.viewInfo()); renderScrubber();
  // keep an open worker inspector live (refresh its actions; close it if the worker has despawned)
  if (INSPECT_ID && !$('#inspector').hidden) {
    if (!workerById(INSPECT_ID)) closeInspector();
    else { const sc = $('#inspectorBody').scrollTop; openWorkerInspector(INSPECT_ID); $('#inspectorBody').scrollTop = sc; }
  }
  const terr = MODE === 'terrarium' && !STATE.cold;
  $('#commandBar').hidden = !terr; if (!terr) $('#speech').hidden = true;
  setPose(newtPoseFor(STATE)); narrate(STATE);
  syncOverlay();   // safety net: palette/help/settings open without a render(); keep the HUD recede in sync
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
    ['ideate', 'Ideate approaches', 'divergent new approaches, in-project', ''],
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
  closeRightDrawers('#sheet');
  $('#sheetScrim').hidden = false; $('#sheet').hidden = false;
  setPose('letter');
  buildTargets(); buildActions(); updateLatency(); syncOverlay();
}
function closeSheet() { $('#sheetScrim').hidden = true; $('#sheet').hidden = true; setPose(newtPoseFor(STATE)); syncOverlay(); }
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
  const m = $('#modal'); m.classList.toggle('g3', gate === 3);
  $('#modalSeal').textContent = gate;
  $('#modalTitle').textContent = `Gate ${gate} — ${idea}`;
  $('#modalBody').innerHTML = gate === 1
    ? `Records your PI signature on <span class="mono">ideas/${esc(idea)}/proposal.md</span> and lets the agent spawn the project.`
    : `Sets <span class="mono">gate2_envelope.pi_signed: true</span> in the project's control.yaml, authorizing the pre-agreed FULL runs.`;
  const read = $('#modalRead'); read.hidden = false;
  read.textContent = gate === 1 ? 'read the proposal ▸' : 'review the envelope ▸';
  read.onclick = () => openDoc('gate', idea, gate, `Gate ${gate} · ${idea}`);
  $('#modalScrim').hidden = false; m.hidden = false; syncOverlay();
}
function closeModal() { $('#modalScrim').hidden = true; $('#modal').hidden = true; $('#modal').classList.remove('g3'); pendingGate = null; syncOverlay(); }
async function confirmGate() {
  if (!pendingGate) return;
  try {
    const r = await fetch('/api/gate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...pendingGate, confirm: true }) }).then(r => r.json());
    toast(r.ok ? `Gate ${pendingGate.gate} approved ✓` : (r.error || 'failed'));
  } catch (e) { toast('could not reach the server'); }
  closeModal();
}

/* ── tool runner (read-only) ────────────────────────────────────────────── */
function closeDrawer() { $('#drawer').hidden = true; syncOverlay(); }
async function runTool(name, idea) {
  $('#drawer').hidden = false; syncOverlay(); $('#drawerTitle').textContent = `${name}${idea ? ' · ' + idea : ''} — running…`; $('#drawerBody').textContent = '';
  try {
    const r = await fetch('/api/tool', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, idea }) }).then(r => r.json());
    $('#drawerTitle').textContent = `${name}${idea ? ' · ' + idea : ''}${r.exit != null ? ' · exit ' + r.exit : ''}`;
    $('#drawerBody').textContent = r.output || r.error || '(no output)';
  } catch (e) { $('#drawerBody').textContent = 'could not reach the server'; }
}

// toasts STACK (newest at the bottom); each fades itself out, so rapid events never overwrite.
function toast(msg) {
  const host = $('#toast'); host.hidden = false;
  const pill = el('div', 'toast-pill', esc(msg)); host.appendChild(pill);
  while (host.children.length > 4) host.removeChild(host.firstChild);
  requestAnimationFrame(() => pill.classList.add('in'));
  setTimeout(() => { pill.classList.add('out'); setTimeout(() => { pill.remove(); if (!host.children.length) host.hidden = true; }, 300); }, 3400);
}

/* ── read-only document viewer (lab knowledge · a gate's proposal/claims) ───── */
async function openDoc(what, idea, gate, label, run) {
  $('#drawer').hidden = false; syncOverlay(); $('#drawerTitle').textContent = `${label || what} — reading…`; $('#drawerBody').textContent = '';
  try {
    const r = await fetch('/api/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ what, idea, gate, run }) }).then(r => r.json());
    if (r.error) { $('#drawerTitle').textContent = label || what; $('#drawerBody').textContent = r.error; return; }
    $('#drawerTitle').textContent = r.title || label || what;
    $('#drawerBody').textContent = (r.sections || []).map(s => `══ ${s.title} ${'═'.repeat(Math.max(0, 60 - s.title.length))}\n\n${(s.text || '').trim() || '(empty)'}`).join('\n\n\n');
  } catch (e) { $('#drawerBody').textContent = 'could not reach the vivarium server'; }
}

/* ── worker inspector: a worker's own activity — what it's doing now + its full action timeline ── */
function workerById(id) { return (STATE && STATE.workers || []).find(w => w.worker_id === id); }
let INSPECT_ID = null;
function titleOfAnchor(w) { const o = (STATE.items || []).find(x => x.id === (w.project || w.idea)); return o ? (o.title || o.id) : (w.project || w.idea); }
function openWorkerInspector(id) {
  const w = workerById(id); if (!w) return;
  INSPECT_ID = id;
  const role = ROLE_ORDER.includes(w.role) ? w.role : 'other';
  const where = w.project ? `project · ${esc(titleOfAnchor(w))}` : (w.idea ? `idea · ${esc(titleOfAnchor(w))}` : 'the hub');
  const live = w.status === 'working';
  $('#inspectorTitle').innerHTML = `<span class="who"><span class="nm">${esc(w.worker_id)}</span>
     <span class="rl"><span class="sw role-${role}"></span>${esc(ROLE_LABEL[role] || w.role)}<span class="wsep">·</span><span class="wst ${live ? 'live' : ''}">${live ? '● ' : ''}${esc(w.status)}</span><span class="wsep">·</span>${where}</span></span>`;
  const body = $('#inspectorBody'); body.innerHTML = '';
  // follow toggle + at-a-glance meta
  const ctl = el('div', 'insp-ctl');
  const followBtn = el('button', 'btn go insp-follow' + (Scene.following() === id ? ' on' : ''), Scene.following() === id ? '◉ following' : '⊙ follow this agent');
  followBtn.onclick = () => { if (Scene.following() === id) Scene.stopFollow(); else { enterTerrarium(); Scene.followWorker(id); } };
  ctl.appendChild(followBtn);
  body.appendChild(ctl);
  const meta = el('div', 'insp-meta', `<span><b>${w.n_actions || 0}</b> actions</span>${w.started ? `<span>started <span class="mono">${hhmm(w.started)}</span></span>` : ''}${w.last_ts ? `<span>last <span class="mono">${hhmm(w.last_ts)}</span></span>` : ''}`);
  body.appendChild(meta);
  const acts = (w.recent_actions || []).slice();
  // current action (the latest) gets its own highlighted callout
  const cur = acts[acts.length - 1];
  if (cur && live) {
    const k = esc(cur.kind || '');
    body.appendChild(el('div', 'insp-now', `<div class="now-h">▸ doing now</div><div class="now-row"><span class="ik ${k}">${k}</span><span class="now-x">${esc(cur.text || '')}</span></div>`));
  }
  body.appendChild(el('div', 'd-sec', live && cur ? 'Earlier actions' : 'Action timeline'));
  const past = (live && cur ? acts.slice(0, -1) : acts).reverse();
  if (!past.length) { body.appendChild(el('div', 'empty-note', cur ? 'no earlier actions logged.' : 'no actions logged yet.')); }
  past.forEach(a => {
    const row = el('div', 'iact');
    row.innerHTML = `<span class="it">${hhmm(a.ts)}</span><span class="ix">${esc(a.text || '')}</span><span class="ik ${esc(a.kind || '')}">${esc(a.kind || '')}</span>`;
    body.appendChild(row);
  });
  closeRightDrawers('#inspector');   // one right-drawer at a time
  $('#inspector').hidden = false;
  $('#legend').hidden = true;   // the inspector (right side) would otherwise crowd the Projects legend
  syncOverlay();
}
function closeInspector() { $('#inspector').hidden = true; INSPECT_ID = null; Scene.stopFollow(); if (STATE) renderProjectLegend(STATE); syncOverlay(); }

/* ── lamplight (dusk / night) ───────────────────────────────────────────── */
function applyLamp() {
  // a ?lamp= override is honoured (deep-links / test harnesses; day|night aliases tolerated); otherwise
  // the persisted light|dark choice. data-lamp stays day|night internally so all theme CSS is unchanged.
  const url = new URLSearchParams(location.search).get('lamp');
  const dark = url ? (url === 'dark' || url === 'night') : (lampMode() === 'dark');
  document.documentElement.dataset.lamp = dark ? 'night' : 'day';
  Scene.setLamp(dark ? 'night' : 'day');
}

/* ═══════════════════════════════════════════════════════════════════════════
   Scene engine — a hand-drawn Canvas-2D lab world (Rain World design language)
   A dense, non-linear region of rooms · cinematic camera · a hand-drawn salamander
   creature (Newt the orchestrator, clickable) · one creature per worker. Public API:
   boot · onClick(item,gate) · onWorker(cb) · onNewt(cb) · onView(cb) · sync(state)
   · setPose(p) · setLamp(m) · setView(mode) · focusProject(id) · back() · viewInfo() · highlight(role)
   ═══════════════════════════════════════════════════════════════════════════ */

// deterministic 0..1 from a string (stable layout/hue per id)
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
    workforce.forEach(w => { if (w.role === 'orchestrator') return; const k = 'wk:' + w.worker_id; seen.add(k); let e = ents.get(k); if (!e) { e = Object.assign(newEnt(), { kind: 'worker', w, jx: hash01(w.worker_id + 'a') - 0.5, jy: hash01(w.worker_id + 'b') - 0.5 }); ents.set(k, e); } e.w = w; if (w.status === 'done' && !e.dying) { e.dying = true; e.dieT = 0; } });
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
      const Hw = s * C.K, fw = Hw * (cw / ch);
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
      e.blinkT -= dt; if (e.blinkT < 0) { e.blinkT = 2.6 + Math.random() * 3.6; e.blinkOn = 0.13; } if (e.blinkOn > 0) e.blinkOn -= dt; e.blink = e.blinkOn > 0;
      if (e.dying) { e.dieT += dt; if (e.dieT >= 1.0 && e.w) ents.delete('wk:' + e.w.worker_id); }
      e.fade = lerp(e.fade, 1, dt * 3); if (!e.init) { e.fade = 1; e.init = true; }
    }
    newt.idle += dt; newt.bounce = lerp(newt.bounce, 0, dt * 2.4);
    newt.look = Math.sin(newt.idle * 0.5) * 0.5;
    newt.blinkT -= dt; if (newt.blinkT < 0) { newt.blinkT = 2 + Math.random() * 3; newt.blinkOn = 0.13; } if (newt.blinkOn > 0) newt.blinkOn -= dt; newt.blink = newt.blinkOn > 0;
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
  function pick(p) { let best = null, bd = 1e9; for (const h of hits) { const d = Math.hypot(p.x - h.sx, p.y - h.sy); if (d < h.r && d < bd) { bd = d; best = h; } } return best; }
  function boxAt(p) { const wpt = s2w(p.x, p.y); for (const k of ROOM_KEYS) { const b = ROOM_BOX[k]; if (wpt.x >= b.x && wpt.x <= b.x + b.w && wpt.y >= b.y && wpt.y <= b.y + b.h) return k; } return null; }
  function clampCam() { const b = boxesBBox(); cam.x = clamp(cam.x, b.x - 400, b.x + b.w + 400); cam.y = clamp(cam.y, b.y - 400, b.y + b.h + 400); }
  let down = null, panned = false;
  canvas.addEventListener('pointerdown', ev => { down = toCanvas(ev); panned = false; try { canvas.setPointerCapture(ev.pointerId); } catch (e) {} });
  canvas.addEventListener('pointermove', ev => { const p = toCanvas(ev); if (down) { const dx = p.x - down.x, dy = p.y - down.y; if (panned || Math.hypot(dx, dy) > 6) { panned = true; if (followId !== null) { followId = null; fireFollow(); } cam.q = []; camFrom = null; cam.x -= dx / cam.zoom; cam.y -= dy / cam.zoom; clampCam(); down = p; userT = t; if (reduced) drawOnce(); } } else { hot = pick(p); if (reduced) drawOnce(); } });
  canvas.addEventListener('pointerup', ev => { const p = toCanvas(ev); if (down && !panned) { const h = pick(p); if (h) { if (h.kind === 'item') { const o = items.find(x => x.id === h.id); if (o && o.has_project) { userT = t; focusProject(h.id); } else if (onItem) onItem(h.id); } else if (h.kind === 'worker' && onWorker) onWorker(h.id); else if (h.kind === 'newt' && onNewt) onNewt(); } else { const rk = boxAt(p); if (rk && !(view.level !== 'WORLD' && view.room === rk)) { userT = t; goRegion(rk); } } } down = null; panned = false; });
  canvas.addEventListener('wheel', ev => { ev.preventDefault(); if (followId !== null) { followId = null; fireFollow(); } const cp = toCanvas(ev), before = s2w(cp.x, cp.y); cam.q = []; camFrom = null; cam.zoom = clamp(cam.zoom * (1 + (ev.deltaY < 0 ? 0.14 : -0.14)), 0.06, 2.6); const after = w2s(before.x, before.y); cam.x += (after.x - cp.x) / cam.zoom; cam.y += (after.y - cp.y) / cam.zoom; clampCam(); userT = t; if (reduced) drawOnce(); }, { passive: false });

  if (reduced) drawOnce(); else startLoop();

  return {
    kind: 'canvas2d',
    sync(s) {
      items = (s.items || []).map(it => ({ id: it.id, title: it.title || it.id, state: it.state, has_project: !!it.has_project, hasProject: !!it.has_project, hasPaper: !!it.has_paper, gate: it.gate || 0, nWorkers: it.n_workers || 0, n_workers: it.n_workers || 0, loop_active: !!it.loop_active, inflight: it.inflight || [], live: (it.inflight || []).some(r => r.state !== 'stalled') && (it.inflight || []).length > 0, dead: it.state === 'killed', parked: it.state === 'parked' }));
      workforce = (s.workers || []); slots = s.slots || slots; gates = s.gates_waiting || 0; cold = !!s.cold;
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

/* ── Scene controller: build the Canvas world, expose a stable API ────────── */
const Scene = (() => {
  let impl = null, pendingState = null, pendingPose = 'idle', pendingLamp = null;
  let itemCb = null, gateCb = null, workerCb = null, newtCb = null, viewCb = null, followCb = null, booted = false;
  async function boot() {
    if (booted) return; booted = true;
    const canvas = $('#scene'); if (!canvas) return;
    const reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    const opts = { reduced, lamp: document.documentElement.dataset.lamp };
    try { impl = createWorld(canvas, opts); }
    catch (e) { console.warn('Vivarium: world scene failed.', e); return; }
    window.__VIV = { kind: impl.kind, scene: impl };   // kind + a diagnostic handle (for tests)
    impl.onClick(itemCb, gateCb); if (workerCb) impl.onWorker(workerCb); if (newtCb) impl.onNewt(newtCb); if (viewCb) impl.onView(viewCb); if (followCb) impl.onFollow(followCb);
    if (pendingLamp) impl.setLamp(pendingLamp);
    if (pendingState) impl.sync(pendingState);
    impl.setPose(pendingPose);
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
    setView(m) { if (impl) impl.setView(m); },
    goRoom(k) { if (impl) impl.goRoom(k); },
    focusProject(id) { if (impl) impl.focusProject(id); },
    back() { if (impl) impl.back(); },
    viewInfo() { return impl ? impl.viewInfo() : { level: 'WORLD', label: '' }; },
    highlight(r) { if (impl) impl.highlight(r); },
    roomRect(k) { return impl ? impl.roomRect(k) : null; },
    band() { return impl ? impl.band() : null; },
    followWorker(id) { if (impl) impl.followWorker(id); },
    stopFollow() { if (impl) impl.stopFollow(); },
    following() { return impl ? impl.following() : null; },
    onFollow(cb) { followCb = cb; if (impl) impl.onFollow(cb); },
    layout() { return impl ? impl.layout() : null; },
    setAmbient(on) { if (impl) impl.setAmbient(on); },
  };
})();

/* ── breadcrumb (camera level) ──────────────────────────────────────────── */
function updateBreadcrumb(info) {
  const bc = $('#breadcrumb');
  if (!info || info.level === 'WORLD') { bc.hidden = true; } else { bc.hidden = false; $('#crumbText').textContent = info.label || ''; }
  renderMinimap(info);
}
/* ── mini-map: the whole lab in miniature, current room lit; click a room to jump ──── */
function renderMinimap(info) {
  const mm = $('#minimap');
  const show = info && info.level !== 'WORLD' && MODE === 'terrarium' && STATE && !STATE.cold;
  if (!show) { mm.hidden = true; return; }
  const lay = Scene.layout(); if (!lay || !lay.bbox) { mm.hidden = true; return; }
  mm.hidden = false; mm.innerHTML = '';
  const bb = lay.bbox, W = 170, H = 104, pad = 7, sc = Math.min((W - pad * 2) / bb.w, (H - pad * 2) / bb.h);
  const offx = (W - bb.w * sc) / 2, offy = (H - bb.h * sc) / 2;
  lay.boxes.forEach(b => {
    const cell = el('button', 'mm-room' + (b.key === lay.room ? ' on' : ''), String(ROOM_N[b.key]));
    cell.style.cssText = `left:${(offx + (b.x - bb.x) * sc).toFixed(1)}px;top:${(offy + (b.y - bb.y) * sc).toFixed(1)}px;width:${(b.w * sc).toFixed(1)}px;height:${(b.h * sc).toFixed(1)}px`;
    cell.title = ROOM_LABEL[b.key];
    cell.onclick = () => { enterTerrarium(); Scene.goRoom(b.key); };
    mm.appendChild(cell);
  });
}

/* ── wiring ─────────────────────────────────────────────────────────────── */
function goTab(m) { MODE = m; location.hash = m; try { localStorage.setItem('viv-tab', m); } catch (e) {} render(); Scene.setView(m); }
$$('.tab').forEach(b => b.onclick = () => goTab(b.dataset.go));
// switch to the World view WITHOUT forcing the camera to the overview — used before a programmatic
// camera move (focusProject / goRoom / followWorker). NB: we deliberately don't touch location.hash
// here, because a hashchange to "terrarium" routes through Scene.setView → goWorld and would snap the
// camera back to the overview, undoing the move we're about to make.
function enterTerrarium() { MODE = 'terrarium'; try { localStorage.setItem('viv-tab', 'terrarium'); } catch (e) {} render(); }
$('#newtStage').onclick = () => openSheet(TARGET || 'hub');
$('#lantern').onclick = () => { MODE = 'gates'; location.hash = 'gates'; render(); Scene.setView('gates'); };
$('#sheetClose').onclick = closeSheet; $('#sheetScrim').onclick = closeSheet;
$('#sendNote').onclick = sendNote;
$('#modalCancel').onclick = closeModal; $('#modalScrim').onclick = closeModal; $('#modalOk').onclick = confirmGate;
$('#drawerClose').onclick = closeDrawer;
$('#inspectorClose').onclick = closeInspector;
$('#cameraBack').onclick = () => Scene.back();
$('#settingsBtn').onclick = openSettings;
$('#settingsClose').onclick = closeSettings; $('#settingsScrim').onclick = closeSettings;
// history scrubber — click the clock to open; scrub/play/return-to-live
$('#clock').onclick = toggleScrubber;
$('#scrubPlay').onclick = playScrub; $('#scrubLive').onclick = goLive; $('#scrubClose').onclick = closeScrubber;
$('#scrubRange').addEventListener('input', e => showHistory(+e.target.value));
// the listening command bar: free-text note to Newt (Enter or ➤); ⋯ opens the full console
function sendCmd() { const inp = $('#cmdInput'); const v = (inp.value || '').trim(); if (!v) return; fetch('/api/directive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: TARGET || 'hub', text: v }) }).then(() => { inp.value = ''; toast(`note pinned → ${TARGET && TARGET !== 'hub' ? TARGET : 'the lab'}`); }).catch(() => toast('could not reach the vivarium server')); }
$('#cmdSend').onclick = sendCmd;
$('#cmdMore').onclick = () => openSheet(TARGET || 'hub');
$('#cmdInput').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); sendCmd(); } });
// command palette + attention inbox + detail drawer
$('#paletteBtn').onclick = openPalette;
$('#paletteScrim').onclick = closePalette;
$('#paletteInput').addEventListener('input', renderPalette);
$('#paletteInput').addEventListener('keydown', paletteKey);
$('#bell').onclick = toggleAttention;
$('#helpClose').onclick = closeHelp; $('#helpScrim').onclick = closeHelp;
$('#helpDemo').onclick = toggleDemo;
$('#attentionClose').onclick = () => { $('#attention').hidden = true; syncOverlay(); };
$('#detailClose').onclick = closeDetail;
// global keys: "/" opens the palette (when not typing in a field); Esc closes overlays
window.addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || '');
  if (e.key === '/' && !typing && $('#palette').hidden) { e.preventDefault(); openPalette(); }
  else if (e.key === 'Escape') { if (!$('#help').hidden) closeHelp(); else if (!$('#settings').hidden) closeSettings(); else if (!$('#palette').hidden) closePalette(); else if (!$('#detail').hidden) closeDetail(); else if (!$('#attention').hidden) { $('#attention').hidden = true; syncOverlay(); } else if (!$('#scrubber').hidden) closeScrubber(); }
});
window.addEventListener('hashchange', () => { let m = location.hash.slice(1); if (m === 'night') m = 'gates'; if (VIEWS[m]) { MODE = m; render(); Scene.setView(m); } });
// canvas clicks → the same console / gates / inspector the rest of the UI uses
Scene.onClick(id => openSheet(id), () => { MODE = 'gates'; location.hash = 'gates'; render(); Scene.setView('gates'); });
Scene.onWorker(id => openWorkerInspector(id));
Scene.onNewt(() => openSheet(TARGET || 'hub'));     // click the orchestrator creature to command the lab
Scene.onView(info => updateBreadcrumb(info));
// keep the inspector's follow toggle in sync when the camera stops following (e.g. on a manual pan)
Scene.onFollow(fid => { const b = $('.insp-follow'); if (b && INSPECT_ID) { const on = fid === INSPECT_ID; b.classList.toggle('on', on); b.textContent = on ? '◉ following' : '⊙ follow this agent'; } });

/* ── live notifications: toast the important changes between snapshots ──────── */
let _seenEventTs = null;
function notifyChanges(prev, next) {
  const ev = next.events || [], lastTs = ev.length ? ev[ev.length - 1].ts : null;
  if (!prev) { _seenEventTs = lastTs; return; }                 // don't toast the initial load
  const fresh = _seenEventTs ? ev.filter(e => (e.ts || '') > _seenEventTs) : [];
  _seenEventTs = lastTs;
  const esc1 = fresh.filter(e => e.kind === 'escalation').slice(-1)[0];
  if (esc1) return toast(`⚠ ${esc1.source || 'a project'} needs you${esc1.detail ? ' · ' + esc1.detail : ''}`);
  if ((next.gates_waiting || 0) > (prev.gates_waiting || 0)) return toast('🔔 a new gate is waiting for you');
  const fin = fresh.filter(e => e.kind === 'run_finished').slice(-1)[0];
  if (fin) return toast(`${fin.source ? fin.source + ' · ' : ''}${fin.run_id || 'run'} ${fin.status || 'finished'}`);
  const kill = fresh.filter(e => e.kind === 'kill').slice(-1)[0];
  if (kill) return toast(`released: ${kill.detail || kill.source || 'an idea'}`);
}
/* ── history scrubber (this session): record snapshots, scrub/replay them ─────── */
let LIVE_STATE = null, HISTORY = [], SCRUB = null, scrubPlay = null, _lastRec = 0;
const NOTABLE = new Set(['run_finished', 'escalation', 'kill', 'gate_resolved', 'replan', 'decision_revisit']);
function recordHistory(s) {
  let now = 0; try { now = Date.now(); } catch (e) { now = (_lastRec + 4000); }   // client clock is fine here
  if (HISTORY.length && now - _lastRec < 3500) { HISTORY[HISTORY.length - 1] = { ts: s.now, snap: s }; return; }
  _lastRec = now; HISTORY.push({ ts: s.now, snap: s });
  if (HISTORY.length > 300) HISTORY.shift();
}
function ingest(s) {
  const prev = LIVE_STATE; LIVE_STATE = s; recordHistory(s);
  if (SCRUB == null) { STATE = s; render(); notifyChanges(prev, s); }
  else renderScrubber();   // keep the timeline length live while viewing the past
}
function showHistory(i) { if (!HISTORY.length) return; SCRUB = clamp(i, 0, HISTORY.length - 1); STATE = HISTORY[SCRUB].snap; render(); }
function goLive() { pauseScrub(); SCRUB = null; STATE = LIVE_STATE || STATE; if (STATE) render(); else renderScrubber(); }
function playScrub() {
  if (scrubPlay) return pauseScrub();
  if (SCRUB == null) SCRUB = 0;
  scrubPlay = setInterval(() => { if (SCRUB >= HISTORY.length - 1) return goLive(); showHistory(SCRUB + 1); }, 650);
  renderScrubber();
}
function pauseScrub() { if (scrubPlay) { clearInterval(scrubPlay); scrubPlay = null; } renderScrubber(); }
function toggleScrubber() { const bar = $('#scrubber'); if (bar.hidden) { bar.hidden = false; goLive(); } else closeScrubber(); }
function closeScrubber() { goLive(); $('#scrubber').hidden = true; document.body.classList.remove('scrubbing'); }
function renderScrubber() {
  const bar = $('#scrubber'); if (bar.hidden) return;
  const n = HISTORY.length, range = $('#scrubRange'), live = SCRUB == null, idx = live ? n - 1 : SCRUB;
  range.max = Math.max(0, n - 1); range.value = idx < 0 ? 0 : idx;
  $('#scrubLive').classList.toggle('on', live);
  $('#scrubPlay').textContent = scrubPlay ? '❚❚' : '▶';
  const samp = HISTORY[idx];
  $('#scrubTime').textContent = live ? `live · ${n} pt${n === 1 ? '' : 's'}` : (samp ? `${hhmm(samp.ts)} · ${idx + 1}/${n}` : 'live');
  document.body.classList.toggle('scrubbing', !live);
  // event ticks along the track
  const ticks = $('#scrubTicks'); ticks.innerHTML = '';
  if (n > 1) HISTORY.forEach((h, i) => {
    const ev = (h.snap.events || []); const last = ev[ev.length - 1];
    const prevLast = i > 0 ? ((HISTORY[i - 1].snap.events || []).slice(-1)[0]) : null;
    if (last && NOTABLE.has(last.kind) && (!prevLast || prevLast.ts !== last.ts)) {
      const m = el('i', 'scrub-tick' + (last.kind === 'escalation' || last.kind === 'kill' ? ' warn' : ''));
      m.style.left = (i / (n - 1) * 100) + '%'; m.title = `${hhmm(last.ts)} · ${last.kind}`;
      m.onclick = () => showHistory(i); ticks.appendChild(m);
    }
  });
}
function connect() {
  const es = new EventSource('/api/events');
  es.onmessage = ev => { try { ingest(JSON.parse(ev.data)); $('#staleVeil').hidden = true; } catch (e) {} };
  es.onerror = () => { $('#clock').classList.add('stopped'); if (!connect._p) connect._p = setInterval(() => fetch('/api/state').then(r => r.json()).then(ingest).catch(() => $('#staleVeil').hidden = false), 5000); };
}

/* ── demo mode (?demo): a synthetic, living lab — agents in every room that come, go, and
   stroll around — so you can see how the world behaves with no real session running. Pure
   client-side; touches no lab files. Open http://127.0.0.1:<port>/?demo (add &lamp=day too). */
function demoState(tick) {
  const T = tick;
  const items = [
    { id: 'spark-1', title: 'Sparse attention', state: 'seed' },
    { id: 'spark-2', title: 'Token routing', state: 'triaged' },
    { id: 'lit-1', title: 'Distillation curricula', state: 'lit-review', n_workers: 1 },
    { id: 'scope-1', title: 'Adaptive optimizers', state: 'scoping', n_workers: 2 },
    { id: 'prop-1', title: 'Curriculum distillation', state: 'proposal', gate: 1, next: 'Gate 1' },
    { id: 'moe', title: 'Sparse MoE routing', state: 'active', has_project: true, loop_active: true, n_workers: 3, next: 'experiment',
      inflight: [{ run_id: 'exp-' + (7 + (T % 3)), stage: (T % 6 < 3 ? 'pilot' : 'full'), state: 'alive', budget_min: 30, elapsed_s: 120 + (T * 47) % 1650, last: { val_loss: +(1.62 - (T % 14) * 0.025).toFixed(3) } }],
      best: { series: [{ value: 2.0 }, { value: 1.74 }, { value: 1.55 }, { value: 1.4 }, { value: 1.31 }] } },
    { id: 'rl', title: 'RL fine-tuning', state: 'active', has_project: true, n_workers: 2, gate: 2, next: 'Gate 2' },
    { id: 'ana-1', title: 'Scaling probes', state: 'analysis', has_project: true, n_workers: 1, next: 'analyze' },
    { id: 'paper-1', title: 'Scaling laws note', state: 'writing', has_project: true, has_paper: true, next: 'write-paper' },
    { id: 'rev-1', title: 'Long-context eval', state: 'internal-review', has_paper: true, n_workers: 2, gate: 3, next: 'Gate 3' },
    { id: 'final-1', title: 'Quantization study', state: 'final', has_paper: true },
    { id: 'final-2', title: 'Pruning at scale', state: 'final', has_paper: true },
    { id: 'park-1', title: 'Old idea (parked)', state: 'parked' },
    { id: 'kill-1', title: 'Abandoned approach', state: 'killed' },
  ].map(it => ({ inflight: [], events: [], directives: [], ...it }));
  // worker pool — idea-anchored ones show in the world overview; project ones live inside their room.
  // A few are `transient` (come and go each cycle, to show spawn/despawn); the rest are a stable crew.
  const pool = [
    { worker_id: 'crit-1', role: 'ideation-critic', idea: 'spark-1' },
    { worker_id: 'crit-2', role: 'ideation-critic', idea: 'spark-2', transient: true },
    { worker_id: 'rev-lit', role: 'fresh-context-reviewer', idea: 'lit-1' },
    { worker_id: 'adv-1', role: 'scoping-advocate', idea: 'scope-1' },
    { worker_id: 'adv-2', role: 'scoping-advocate', idea: 'scope-1', transient: true },
    { worker_id: 'er-moe-1', role: 'experiment-runner', project: 'moe' },
    { worker_id: 'er-moe-2', role: 'experiment-runner', project: 'moe' },
    { worker_id: 'over-moe', role: 'overseer', project: 'moe' },
    { worker_id: 'er-rl-1', role: 'experiment-runner', project: 'rl' },
    { worker_id: 'over-ana', role: 'overseer', project: 'ana-1' },
    { worker_id: 'rev-lc-1', role: 'fresh-context-reviewer', idea: 'rev-1' },
    { worker_id: 'rev-lc-2', role: 'fresh-context-reviewer', idea: 'rev-1', transient: true },
  ];
  // a small role-flavoured action vocabulary → believable, evolving per-agent timelines for the inspector
  const VERB = {
    'experiment-runner': [['Bash: python scripts/run.py --seed 0', 'run'], ['Read: configs/base.yaml', 'read'], ['Edit: src/model.py', 'edit'], ['Bash: git commit -m "exp"', 'git'], ['Grep: val_loss in runs/', 'read']],
    'overseer': [['Read: runs/exp-007/metrics.json', 'read'], ['Grep: claim vs artifact', 'read'], ['Read: analysis.md', 'read']],
    'fresh-context-reviewer': [['Read: papers/draft.md', 'read'], ['Grep: unsupported claims', 'read'], ['Write: review-notes.md', 'edit']],
    'ideation-critic': [['Read: IDEA.md', 'read'], ['Write: critique.md', 'edit'], ['Grep: prior work', 'read']],
    'scoping-advocate': [['Read: decisions.md', 'read'], ['Write: scoping/option-a.md', 'edit'], ['Grep: baselines', 'read']],
  };
  const tstamp = k => { const sec = k * 7; const p = n => String(n).padStart(2, '0'); return `2026-06-19T${p((8 + ((sec / 3600) | 0)) % 24)}:${p(((sec / 60) | 0) % 60)}:${p(sec % 60)}`; };
  const present = pool.filter((w, i) => !w.transient || ((T + i) % 4) !== 0);   // transient ones blink in/out
  const workers = present.map((w, i) => {
    const vocab = VERB[w.role] || VERB['experiment-runner'], n = 3 + ((T + i) % 5);
    const recent = Array.from({ length: n }, (_, j) => { const v = vocab[(T + i + j) % vocab.length]; return { ts: tstamp(Math.max(0, T - (n - 1 - j))), text: v[0], kind: v[1] }; });
    return { ...w, status: 'working', n_actions: 6 + ((T * (i + 2)) % 60), started: tstamp(Math.max(0, T - 9)), last_ts: tstamp(T), recent_actions: recent };
  });
  return { now: '', items, events: [], slots: { cap: 3, in_use: 1 + (T % 3), held: [] },
    directives: [{ id: 'd-1', ts: '', text: 'prioritise the MoE routing work', state: 'pending', kind: 'note' }],
    campaigns: [{ name: 'scaling-laws', title: 'Scaling-laws sweep', status: 'active', signed: 'PI · 2026-06-12',
      budget: { full_runs: 12, total_max_minutes: 480, pi_signed: true, expires: '2026-06-30' }, projects: ['moe', 'rl', 'ana-1'] }],
    workers, gates_waiting: items.filter(it => it.gate).length, cold: false };
}
function startDemo() {
  document.title = 'Vivarium — demo';
  setTimeout(() => toast('demo mode — click a room (or a buddy) to zoom in and watch the agents move'), 700);
  let T = 0; const evs = [];
  const stamp = k => { const sec = k * 7; const p = n => String(n).padStart(2, '0'); return `2026-06-19T${p((8 + ((sec / 3600) | 0)) % 24)}:${p(((sec / 60) | 0) % 60)}:${p(sec % 60)}`; };
  function step() {
    const s = demoState(T), ph = T % 9;
    if (ph === 3) evs.push({ ts: stamp(T), source: 'moe', kind: 'run_finished', status: 'completed', run_id: 'exp-' + (7 + (T % 3)) });
    else if (ph === 6) evs.push({ ts: stamp(T), source: 'rl', kind: 'escalation', detail: 'requesting a FULL-run envelope bump' });
    else if (ph === 0 && T > 0) evs.push({ ts: stamp(T), source: 'moe', kind: 'run_started', run_id: 'exp-' + (7 + (T % 3)) });
    s.now = stamp(T); s.events = evs.slice(-40);
    ingest(s); T++;
  }
  step(); setInterval(step, 2600);
}
Scene.boot();
applyLamp();
applyPrefs();   // theme/density/legend/status/ambient prefs from the ⚙ Settings panel
let startMode = location.hash.slice(1) || (() => { try { return localStorage.getItem('viv-tab') || ''; } catch (e) { return ''; } })();
if (startMode === 'night') startMode = 'gates';   // the old In-flight tab folded into Activity
if (VIEWS[startMode]) MODE = startMode;
const STATIC = location.search.includes('static');
const DEMO = location.search.includes('demo');
if (DEMO) MODE = 'terrarium';   // the demo is about the living world — always open there
if (DEMO) startDemo();
else if (window.__STATE__) ingest(window.__STATE__);
else fetch('/api/state').then(r => r.json()).then(ingest).catch(() => $('#staleVeil').hidden = false);
// deep-link: ?open=<idea|hub> opens the command console straight away
const openTo = new URLSearchParams(location.search).get('open');
if (openTo) setTimeout(() => openSheet(openTo), 60);
if (!STATIC && !DEMO) connect();   // (theme is a manual light/dark toggle now — no time-based re-check)
maybeAutoHelp();   // first-time visitors get the guide once
