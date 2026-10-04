/* Newts' Lab — the app shell: the top bar, the pages over the living world, the command palette, the
   world's click wiring, notifications, and boot. Pages: Home (the world + Today) · Studies · Runs ·
   Library, plus Settings, History, Labs and the setup wizard. Sheets and dialogs stack over any page. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, render, useState, useEffect, useRef, cls } = NL;

  /* ── the world ─────────────────────────────────────────────────────────── */
  NL.viewListeners = new Set();
  NL.Scene = window.VivScene ? window.VivScene.create({ motion: NL.prefs.motion }) : null;
  if (NL.Scene) NL.Scene.setCast(NL.prefs.cast);
  if (NL.Scene) {
    NL.Scene.onClick(id => NL.open(StudyPeek, { id }, { key: 'peek' }), () => NL.open(NL.InboxSheet, {}, { key: 'inbox' }));
    NL.Scene.onWorker(id => NL.openWorker(id));
    NL.Scene.onRun((id, sub) => NL.openRun(id, sub));
    NL.Scene.onArtifact(id => NL.openArtifact(id));
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
        <${NL.Btn} onClick=${() => { onClose(); NL.go('study/' + it.id); }}>Open the study page<small class="btn-sub">its documents, runs and decisions</small></${NL.Btn}>
        ${it.has_project ? html`<${NL.Btn} onClick=${() => { onClose(); NL.Scene.focusProject(it.id); }}>Zoom to its lab<small class="btn-sub">see its agents at work on the table</small></${NL.Btn}>` : null}
        <${NL.Btn} onClick=${() => { onClose(); NL.openStart({ intent: 'study', target: it.id }); }}>Start new work on it…<small class="btn-sub">pick a step, or tell an agent what to do</small></${NL.Btn}></div>
      ${runs.length ? html`<${NL.Section} title="Runs">${runs.map(r => html`<${NL.RunRow} key=${r.run_id} r=${r} compact />`)}</${NL.Section}>` : null}
    </${NL.Sheet}>`;
  };

  /* ── command palette (/ or Ctrl+K) ─────────────────────────────────────── */
  /* the pages you can go to: [route, label, in the top bar] — the top bar and the palette both read this */
  const NAV = [['', 'Home', 1], ['studies', 'Studies', 1], ['runs', 'Runs', 1], ['library', 'Library', 1], ['artifacts', 'For you', 1], ['compose', 'Compose', 1],
    ['history', 'History'], ['labs', 'Labs & machines — switch, create, connect'], ['setup', 'Setup wizard']];
  function paletteActions(s) {
    const A = [];
    const add = (label, hint, run, kw) => A.push({ label, hint, run, kw: (label + ' ' + (hint || '') + ' ' + (kw || '')).toLowerCase() });
    if (s.lab_paused) add('Resume the lab', 'agents may start again; paused runs can be resumed', () => NL.pauseLab(false), 'unpause start');
    else add('Pause the lab…', 'stop every agent now (resumable); nothing new starts until you resume', () => NL.pauseLab(true), 'stop everything halt all kill');
    add('Start something', 'a procedure or an instruction', () => NL.openStart(), 'new launch run');
    add('History', 'what happened in the lab, and what you sent', () => NL.go('history'), 'log events overnight');
    add('Ask Newt…', 'a free-form instruction', () => NL.openStart(), 'prompt chat');
    add('Plan a campaign', 'several ideas end-to-end, unattended', () => NL.openStart({ intent: 'campaign' }), 'autopilot');
    (NL.liveCampaigns ? NL.liveCampaigns(s) : []).forEach(c => {
      const nm = c.name.replace(/^\d{4}-\d{2}-\d{2}-/, '');
      if (c.status === 'active' || c.status === 'finishing') add(`Pause campaign ${nm}`, 'no new pass starts; what is running finishes', () => NL.campaignAct(c, 'pause'), 'campaign autopilot pause');
      if (c.status === 'paused' || c.status === 'stalled') add(`Resume campaign ${nm}`, 'carry on from where it paused', () => NL.campaignAct(c, 'resume'), 'campaign autopilot resume');
      if (!['done', 'stopped', 'stopping'].includes(c.status)) add(`Stop campaign ${nm}…`, 'stops its runs and writes a final report', () => NL.campaignAct(c, 'stop'), 'campaign autopilot stop end');
    });
    add('Explore a new direction', '/ideate', () => NL.openStart({ intent: 'ideate' }));
    add('New procedure…', 'Compose — start from a copy', () => { NL.go('compose'); setTimeout(() => NL.composeNew('procedure'), 50); }, 'skill add create workflow');
    add('Tour of Compose', 'how to make the lab yours, in a minute', () => NL.composeTour(), 'customise customize workflow help');
    NAV.forEach(([p, l]) => add(l, 'go', () => NL.go(p)));
    (NL.SETTINGS_SECTIONS || []).forEach(x => add('Settings: ' + x.label, 'go', () => NL.go('settings/' + x.id), x.id));
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
    const nav = NAV.filter(x => x[2]).map(([to, label]) => [to || 'home', to, label]);
    const running = x.active || 0;
    const fl = NL.useFleet ? NL.useFleet() : null;
    useEffect(() => { const el = document.querySelector('.mainnav .navlink.on'); if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }, [page]);
    const elsewhere = (fl && fl.needs_elsewhere) || 0;
    return html`<header class="topbar">
      <a class="brand" href="#/labs" title="labs & machines — switch, create, or connect"><span class="brand-mark" aria-hidden="true">N</span><span class="brand-name">${li.name || "Newts' Lab"}</span>
        ${s.remote ? html`<span class=${cls('brand-machine', s.remote.state !== 'connected' && 'off')} title=${s.remote.host}>on ${s.remote.name}</span>` : null}<span class="brand-caret"><${NL.Icon} name="caret" /></span>${elsewhere ? html`<span class="brand-else" title=${`${NL.plural(elsewhere, 'thing')} in your other labs ${elsewhere === 1 ? 'needs' : 'need'} you — open Labs & machines`}>+${elsewhere} in other labs</span>` : null}</a>
      <nav class="mainnav">${nav.map(([id, to, label]) => html`<a class=${cls('navlink', (page === id || (id === 'studies' && page === 'study')) && 'on')} href=${'#/' + to}>${label}${id === 'runs' && running ? html` <span class="navcount live">${running}</span>` : null}${id === 'artifacts' && (NL.artifactsAsking(s).length + NL.artifactsUnseen(s).filter(a => !a.question).length) ? html` <span class=${cls('navcount', NL.artifactsAsking(s).length && 'warm')} title="questions for you, and new things to look at">${NL.artifactsAsking(s).length + NL.artifactsUnseen(s).filter(a => !a.question).length}</span>` : null}</a>`)}</nav>
      <div class="topright">
        <span class=${cls('conn', 'conn-' + conn)} title=${conn === 'live' ? 'live' : conn}><i></i>${NL.hhmm(s.now)}</span>
        <${SoundBtn} />
        <button class="iconbtn" title="search and jump (/ or Ctrl+K)" onClick=${NL.openPalette}><${NL.Icon} name="search" /></button>
        <button class=${cls('iconbtn', needs.length && 'has')} title="what needs you" onClick=${() => NL.open(NL.InboxSheet, {}, { key: 'inbox' })}><${NL.Icon} name="bell" />${needs.length ? html`<span class="bell-n">${needs.length}</span>` : null}</button>
        <a class=${cls('iconbtn', 'labelled', page === 'settings' && 'on')} title="Settings — agents, limits, notifications" href="#/settings"><${NL.Icon} name="sliders" /><span class="iconbtn-label">Settings</span></a>
      </div></header>`;
  };

  /* ── pause the lab: every agent stops now (resumable), nothing new starts until you resume ───────────── */
  NL.pauseLab = async on => {
    if (on && !await NL.confirm({ title: 'Pause the lab?', ok: 'Pause everything', danger: true,
      body: 'Every running agent stops now — each stays resumable. Queued runs and campaign passes wait, and nothing new starts until you resume.' })) return;
    return NL.act('/api/lab/pause', { paused: !!on, confirm: true }, on ? 'The lab is paused' : 'The lab is running again');
  };
  NL.PausedBar = () => {
    const s = NL.useLab();
    if (!s.lab_paused) return null;
    return html`<div class="paused-bar" role="status"><b>The lab is paused</b><span class="muted small">since ${NL.when ? NL.when(s.lab_paused.since) : s.lab_paused.since} — agents are stopped; anything you start waits until you resume</span>
      <${NL.Btn} small kind="primary" onClick=${() => NL.pauseLab(false)}>Resume</${NL.Btn}></div>`;
  };

  /* ── sound: gentle chimes when something needs you, and soft music — both off until you turn them on ── */
  const useSound = () => { const [, f] = NL.useReducer(x => x + 1, 0); useEffect(() => NL.Sound ? NL.Sound.subscribe(() => f()) : undefined, []); return NL.Sound ? NL.Sound.prefs() : {}; };
  NL.SoundControls = ({ compact }) => {
    const p = useSound();
    if (!NL.Sound) return null;
    const set = x => NL.Sound.set(x);
    return html`<div class=${cls('sound', compact && 'compact')}>
      <${NL.Toggle} on=${!!p.chimes} onChange=${v => { set({ chimes: v }); if (v) NL.Sound.test('ask'); }} label="Chimes" sub="a soft bell when an agent asks you something or a gate opens; a lighter note when a run finishes, a low one when it fails" />
      <label class="sound-vol"><span class="muted small">chime volume</span><input type="range" min="0" max="1" step="0.05" value=${p.volume} onInput=${e => set({ volume: +e.target.value })} /></label>
      <div class="row-wrap">${(NL.Sound.KINDS || []).map(k => html`<button type="button" class="link small" onClick=${() => NL.Sound.test(k)}>▸ ${k}</button>`)}</div>
      <${NL.Toggle} on=${!!p.music} onChange=${v => set({ music: v })} label="Music" sub="calm, generated as you listen — it breathes with the lab: sparser when it is quiet, a little brighter when agents are at work" />
      <label class="sound-vol"><span class="muted small">music volume</span><input type="range" min="0" max="1" step="0.05" value=${p.musicVolume} onInput=${e => set({ musicVolume: +e.target.value })} /></label></div>`;
  };
  const SoundBtn = () => {
    const p = useSound();
    const [open, setOpen] = useState(false);
    if (!NL.Sound) return null;
    const on = p.chimes || p.music;
    return html`<span class="sound-wrap"><button class=${cls('iconbtn', on && 'on')} title="sound — chimes and music" aria-expanded=${open} onClick=${() => setOpen(!open)}><${NL.Icon} name=${on ? 'sound' : 'mute'} /></button>
      ${open ? html`<div class="sound-pop" onMouseLeave=${() => setOpen(false)}><${NL.SoundControls} compact /><a class="link small" href="#/settings/notifications" onClick=${() => setOpen(false)}>More in Settings → Notifications</a></div>` : null}</span>`;
  };

  /* ── routing ───────────────────────────────────────────────────────────── */
  const PAGES = {
    home: () => null, studies: () => NL.StudiesPage, study: () => NL.StudyPage, runs: () => NL.RunsPage, run: () => NL.RunsPage,
    library: () => NL.LibraryPage, artifacts: () => NL.ArtifactsPage, compose: () => NL.ComposePage, settings: () => NL.SettingsPage, history: () => NL.HistoryPage, labs: () => NL.LabsPage, setup: () => NL.SetupPage,
  };
  const App = () => {
    const route = NL.useRoute();
    NL.useLab();
    const page = PAGES[route.page] ? route.page : 'home';
    const P = PAGES[page]();
    const prevPage = useRef(page);
    useEffect(() => {
      if (prevPage.current !== page) { NL.closeSheets(); prevPage.current = page; }
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
      ${page === 'compose' ? html`<${NL.ComposeTourCard} />` : null}
      <${NL.OverlayHost} /><${NL.Toasts} />`;
  };

  /* ── notifications: toasts, desktop notifications, the tab title ────────── */
  let seenAtt = null;
  NL.onSnapshot = (prev, next) => {
    if (NL.Sound && next) NL.Sound.observe(next);    // gentle chimes (off unless you turn them on), and the music's mood
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
    // the world paints its signs once: wait (briefly) for the bundled fonts first
    const fonts = document.fonts ? Promise.race([Promise.all(['600 14px Newsreader', '600 13px "Instrument Sans"'].map(f => document.fonts.load(f))), new Promise(r => setTimeout(r, 1200))]) : Promise.resolve();
    if (NL.Scene) fonts.catch(() => null).then(() => NL.Scene.boot(document.getElementById('scene'))).then(() => { if (!NL.prefs.motion) NL.Scene.setAmbient(false); });
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
