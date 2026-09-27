/* Newts' Lab — the app shell: the top bar, the pages over the living world, the command palette, the
   world's click wiring, notifications, and boot. Pages: Home (the world + Today) · Studies · Runs ·
   Library, plus Settings, History, Labs and the setup wizard. Sheets and dialogs stack over any page. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, render, useState, useEffect, useRef, cls } = NL;

  /* ── the world ─────────────────────────────────────────────────────────── */
  NL.viewListeners = new Set();
  NL.Scene = window.VivScene ? window.VivScene.create({
    world: NL.prefs.world, motion: NL.prefs.motion, toast: m => NL.toast(m),
    runTool: async (name, idea) => { const r = await NL.api('/api/tool', { name, idea }); NL.open(NL.TextSheet, { title: name, text: r.output || r.error || '(no output)' }); },
  }) : null;
  if (NL.Scene) {
    NL.Scene.onClick(id => NL.open(StudyPeek, { id }, { key: 'peek' }), () => NL.open(NL.InboxSheet, {}, { key: 'inbox' }));
    NL.Scene.onWorker(id => NL.openWorker(id));
    NL.Scene.onNewt(() => NL.openStart());
    NL.Scene.onView(info => { NL.viewInfo = info; NL.viewListeners.forEach(f => f(info)); });
  }

  /* a study, peeked at from the world without leaving it */
  const StudyPeek = ({ id, onClose }) => {
    const s = NL.useLab();
    const it = NL.item(s, id);
    if (!it) return html`<${NL.Sheet} title="Study" onClose=${onClose}><${NL.Empty}>Not in the registry.</${NL.Empty}></${NL.Sheet}>`;
    const nx = NL.nextFor(s, it);
    const runs = NL.runsOf(s, id).sort((a, b) => (b.created || '').localeCompare(a.created || '')).slice(0, 4);
    return html`<${NL.Sheet} title=${it.title || it.id} sub=${html`<span class="row-wrap"><${NL.StatePill} state=${it.state} />${it.next && it.next !== '-' ? html`<span class="muted">${it.next}</span>` : null}</span>`} onClose=${onClose}>
      <div class="stack">${nx ? html`<${NL.Btn} kind="primary" icon=${nx.icon} onClick=${() => { onClose(); nx.run(); }}>${nx.label}</${NL.Btn}>` : null}
        <${NL.Btn} onClick=${() => { onClose(); NL.go('study/' + it.id); }}>Open the study</${NL.Btn}>
        ${it.has_project ? html`<${NL.Btn} onClick=${() => { onClose(); NL.Scene.focusProject(it.id); }}>Enter its lab</${NL.Btn}>` : null}
        <${NL.Btn} onClick=${() => { onClose(); NL.openStart({ intent: 'study', target: it.id }); }}>Work on it…</${NL.Btn}></div>
      ${runs.length ? html`<${NL.Section} title="Runs">${runs.map(r => html`<${NL.RunRow} key=${r.run_id} r=${r} compact />`)}</${NL.Section}>` : null}
    </${NL.Sheet}>`;
  };

  /* ── command palette (/ or Ctrl+K) ─────────────────────────────────────── */
  function paletteActions(s) {
    const A = [];
    const add = (label, hint, run, kw) => A.push({ label, hint, run, kw: (label + ' ' + (hint || '') + ' ' + (kw || '')).toLowerCase() });
    add('Start something', 'a procedure or an instruction', () => NL.openStart(), 'new launch run');
    add('Ask Newt…', 'a free-form instruction', () => NL.openStart(), 'prompt chat');
    add('Plan a campaign', 'several ideas end-to-end, unattended', () => NL.openStart({ intent: 'campaign' }), 'autopilot');
    add('Explore a new direction', '/ideate', () => NL.openStart({ intent: 'ideate' }));
    [['', 'Home'], ['studies', 'Studies'], ['runs', 'Runs'], ['library', 'Library'], ['history', 'History'], ['labs', 'Labs & machines — switch, create, connect'], ['setup', 'Setup wizard']]
      .forEach(([p, l]) => add(l, 'go', () => NL.go(p)));
    ['agents', 'autonomy', 'lab', 'keys', 'appearance', 'notifications', 'about'].forEach(x => add('Settings: ' + x, 'go', () => NL.go('settings/' + x)));
    (s.items || []).forEach(i => {
      add(i.title || i.id, NL.STATE_LABEL[i.state] + ' · study', () => NL.go('study/' + i.id), i.id);
      if (i.gate && !i.gate_signed) add(`Sign Gate ${i.gate} — ${i.title || i.id}`, 'review and sign', () => NL.openGate(i.id, i.gate), 'approve');
    });
    (s.runs || []).filter(r => r.status === 'waiting_input' || NL.RUN_ACTIVE.has(r.status)).forEach(r => add(NL.runTitle(r), NL.RUN_WORD[r.status], () => NL.openRun(r.run_id), r.run_id));
    NL.needsYou(s).forEach(a => add(a.title, 'needs you', () => a.run_id ? NL.openRun(a.run_id) : a.kind === 'gate' ? NL.openGate(a.idea, (a.detail || {}).gate) : NL.open(NL.InboxSheet, {}, { key: 'inbox' }), 'sign answer ' + (a.kind || '')));
    add('Toggle day / night', 'theme', () => NL.setPref('theme', NL.themeNow() === 'day' ? 'night' : 'day'), 'dark light');
    return A;
  }
  const Palette = ({ onClose }) => {
    const s = NL.useLab();
    const [q, setQ] = useState('');
    const [sel, setSel] = useState(0);
    const list = paletteActions(s).filter(a => !q || q.toLowerCase().split(/\s+/).every(t => a.kw.includes(t))).slice(0, 14);
    const pick = a => { onClose(); setTimeout(a.run, 0); };
    return html`<div class="palette" role="dialog" aria-label="command palette">
      <input class="palette-in" autofocus value=${q} data-esc-close="1" placeholder="Jump to a study, a run, a page — or start something…"
        onInput=${e => { setQ(e.target.value); setSel(0); }}
        onKeyDown=${e => { if (e.key === 'ArrowDown') { e.preventDefault(); setSel(x => Math.min(list.length - 1, x + 1)); } else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(x => Math.max(0, x - 1)); } else if (e.key === 'Enter' && list[sel]) { e.preventDefault(); pick(list[sel]); } else if (e.key === 'Escape') onClose(); }}
        ref=${el => el && setTimeout(() => el.focus(), 0)} />
      <div class="palette-list">${list.map((a, i) => html`<button type="button" class=${cls('pal-row', i === sel && 'on')} onMouseEnter=${() => setSel(i)} onClick=${() => pick(a)}><span>${a.label}</span><small>${a.hint || ''}</small></button>`)}
        ${!list.length ? html`<div class="muted pad">Nothing matches.</div>` : null}</div>
      <div class="palette-hint">↑↓ move · ↵ go · esc close</div></div>`;
  };
  NL.openPalette = () => NL.open(Palette, {}, { key: 'palette', kind: 'dialog' });

  /* ── the top bar ───────────────────────────────────────────────────────── */
  const TopBar = ({ page }) => {
    const s = NL.useLab();
    const conn = NL.useConn();
    const { needs } = NL.inboxItems(s);
    const li = s.lab_info || {};
    const x = NL.exec(s);
    const slots = s.slots || {};
    const nav = [['home', '', 'Home'], ['studies', 'studies', 'Studies'], ['runs', 'runs', 'Runs'], ['library', 'library', 'Library']];
    const running = x.active || 0;
    return html`<header class="topbar">
      <a class="brand" href="#/labs" title="labs & machines — switch, create, or connect"><span class="brand-mark" aria-hidden="true">🦎</span><span class="brand-name">${li.name || "Newts' Lab"}</span>
        ${s.remote ? html`<span class=${cls('brand-machine', s.remote.state !== 'connected' && 'off')} title=${s.remote.host}>on ${s.remote.name}</span>` : null}<span class="brand-caret">▾</span></a>
      <nav class="mainnav">${nav.map(([id, to, label]) => html`<a class=${cls('navlink', (page === id || (id === 'studies' && page === 'study')) && 'on')} href=${'#/' + to}>${label}${id === 'runs' && running ? html` <span class="navcount live">${running}</span>` : null}</a>`)}</nav>
      <div class="topright">
        <span class=${cls('conn', 'conn-' + conn)} title=${conn === 'live' ? 'live' : conn}><i></i>${NL.hhmm(s.now)}</span>
        ${slots.cap ? html`<span class="slots" title=${`compute slots: ${slots.in_use || 0} of ${slots.cap} in use`}>${Array.from({ length: Math.min(slots.cap, 8) }, (_, i) => html`<i class=${i < (slots.in_use || 0) ? 'on' : ''}></i>`)}</span>` : null}
        <button class="iconbtn" title="search and jump (/ or Ctrl+K)" onClick=${NL.openPalette}>⌕</button>
        <button class=${cls('iconbtn', needs.length && 'has')} title="what needs you" onClick=${() => NL.open(NL.InboxSheet, {}, { key: 'inbox' })}>🔔${needs.length ? html`<span class="bell-n">${needs.length}</span>` : null}</button>
        <a class=${cls('iconbtn', page === 'settings' && 'on')} title="settings" href="#/settings">⚙</a>
      </div></header>`;
  };

  /* ── routing ───────────────────────────────────────────────────────────── */
  const PAGES = {
    home: () => null, studies: () => NL.StudiesPage, study: () => NL.StudyPage, runs: () => NL.RunsPage, run: () => NL.RunsPage,
    library: () => NL.LibraryPage, settings: () => NL.SettingsPage, history: () => NL.HistoryPage, labs: () => NL.LabsPage, setup: () => NL.SetupPage,
  };
  const App = () => {
    const route = NL.useRoute();
    NL.useLab();
    const page = PAGES[route.page] ? route.page : 'home';
    const P = PAGES[page]();
    useEffect(() => {
      document.body.dataset.page = page;
      if (page === 'run' && route.args[0]) NL.openRun(route.args[0]);
      // shareable deep links into a sheet: #/study/<slug>?gate=3 · #/?start=<intent> · #/runs?run=<id>
      const q = route.query || {};
      if (page === 'study' && q.gate) NL.openGate(route.args[0], +q.gate);
      if ('start' in q) NL.openStart(q.start ? { intent: q.start } : {});
      if (q.run) NL.openRun(q.run);
    }, [page, route.args.join('/'), JSON.stringify(route.query || {})]);
    return html`<${TopBar} page=${page} />
      ${page === 'home' ? html`<${NL.Home} />` : html`<main class="stage" key=${page}><${P} args=${route.args} query=${route.query} /></main>`}
      <${NL.OverlayHost} /><${NL.Toasts} />`;
  };

  /* ── notifications: toasts, desktop notifications, the tab title ────────── */
  let seenAtt = null;
  NL.onSnapshot = (prev, next) => {
    if (NL.Scene) { NL.Scene.sync(next); NL.Scene.setPose(window.VivScene.newtPoseFor(next)); }
    const needs = ((next && next.attention) || []).filter(a => a.sev !== 'info');
    document.title = (needs.length ? `(${needs.length}) ` : '') + ((next && next.lab_info && next.lab_info.name) || "Newts' Lab");
    const ids = new Set(((next && next.attention) || []).map(a => a.id));
    if (seenAtt === null) { seenAtt = ids; return; }
    const fresh = ((next && next.attention) || []).filter(a => !seenAtt.has(a.id));
    seenAtt = ids;
    for (const a of fresh.slice(0, 3)) {
      const tone = a.sev === 'block' ? 'warn' : a.kind === 'report' ? 'ok' : a.kind === 'crashed' ? 'bad' : 'info';
      NL.toast(a.title, tone);
      if (NL.prefs.notify && window.Notification && Notification.permission === 'granted' && (document.hidden || !document.hasFocus())) {
        try { const n = new Notification(a.title, { body: a.body || '', tag: a.id }); n.onclick = () => { window.focus(); if (a.run_id) NL.openRun(a.run_id); else if (a.kind === 'gate') NL.openGate(a.idea, (a.detail || {}).gate); }; } catch (e) { /* unsupported */ }
      }
    }
  };

  /* ── keys ──────────────────────────────────────────────────────────────── */
  window.addEventListener('keydown', e => {
    const t = e.target && e.target.tagName;
    const typing = t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT';
    if ((e.key === 'k' && (e.ctrlKey || e.metaKey)) || (e.key === '/' && !typing)) { e.preventDefault(); if (!NL.isOpen('palette')) NL.openPalette(); }
  });

  /* ── boot ──────────────────────────────────────────────────────────────── */
  NL.boot = () => {
    NL.applyTheme();
    const root = document.getElementById('app');
    render(html`<${App} />`, root);
    if (NL.Scene) NL.Scene.boot(document.getElementById('scene')).then(() => { if (!NL.prefs.motion) NL.Scene.setAmbient(false); });
    if (NL.DEMO && NL.startDemo) { NL.startDemo(); return; }
    if (NL.store.state) NL.onSnapshot(null, NL.store.state); else NL.refresh();
    NL.connect();
    // first run: a fresh lab that hasn't been set up opens the wizard (once; skippable)
    const s = NL.store.state, setup = s && s.lab_info && s.lab_info.setup;
    if (setup && !setup.completed && setup.fresh && !NL.ls.get('nl-setup-skip', false) && NL.parseRoute().page === 'home') NL.go('setup');
    // old links: ?open=<target> / ?read=scope:slug:rel
    const q = new URLSearchParams(location.search);
    if (q.get('open')) NL.go('study/' + q.get('open'));
    if (q.get('read')) { const [sc, sl, ...rel] = q.get('read').split(':'); NL.openDoc(sc, sl === '' ? null : sl, rel.join(':')); }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', NL.boot); else NL.boot();
})();
