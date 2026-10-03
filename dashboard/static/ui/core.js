/* Newts' Lab — UI core: the live lab store, the API client, the router, preferences, toasts, layers.
   No build step: Preact + hooks + htm are vendored UMD globals (static/vendor/preact/). Every UI file
   registers into window.NL. Components use `html\`...\`` (htm) instead of JSX. */
(function () {
  'use strict';
  const { h, render, Fragment } = window.preact;
  const H = window.preactHooks;
  const html = window.htm.bind(h);
  const NL = (window.NL = window.NL || {});
  Object.assign(NL, { h, render, Fragment, html, ...H });

  /* ── small helpers ─────────────────────────────────────────────────────── */
  NL.cls = (...xs) => xs.filter(Boolean).join(' ');
  NL.hhmm = ts => (ts || '').slice(11, 16);
  NL.plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;
  NL.mins = s => s == null ? '' : s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`;
  NL.ago = ts => {
    if (!ts) return '';
    const t = Date.parse(ts.length <= 19 ? ts : ts); if (isNaN(t)) return '';
    const d = (Date.now() - t) / 1000;
    if (d < 60) return 'just now';
    if (d < 3600) return `${Math.round(d / 60)} min ago`;
    if (d < 86400) return `${Math.round(d / 3600)} h ago`;
    return `${Math.round(d / 86400)} d ago`;
  };
  NL.clip = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  NL.qs = o => Object.entries(o).filter(([, v]) => v != null && v !== '').map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  const ls = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
  };
  NL.ls = ls;

  /* ── the workflow vocabulary: states, rooms, gates, procedures — all from workflow/stages.yaml ──
     (the live snapshot's `workflow`; the generated workflow-default.js serves demo/static pages).
     applyWorkflow() refills these in place whenever the lab's workflow changes. */
  NL.LIFECYCLE = []; NL.STATE_LABEL = {}; NL.ROOMS = []; NL.GATE_AT = {}; NL.PROC = {}; NL.PROCS_FOR_STATE = {};
  NL.NEXT_FOR_STATE = {}; NL.STAGES = []; NL.GATES = []; NL.WF = {};
  let wfSig = '';
  NL.applyWorkflow = wf => {
    if (!wf || wf.error || !Array.isArray(wf.states)) return false;
    const sig = JSON.stringify([wf.states, wf.side_states, wf.rooms, wf.gates, wf.stages, wf.procedures, wf.next_for_state, wf.offer_for_state]);
    NL.WF = wf;
    if (sig === wfSig) return false;
    wfSig = sig;
    const all = wf.states.concat(wf.side_states || []);
    NL.LIFECYCLE.splice(0, NL.LIFECYCLE.length, ...wf.states.map(x => x.id));
    for (const k of Object.keys(NL.STATE_LABEL)) delete NL.STATE_LABEL[k];
    all.forEach(x => { NL.STATE_LABEL[x.id] = x.label || x.id; });
    NL.ROOMS.splice(0, NL.ROOMS.length, ...(wf.rooms || []).map(r => ({ key: r.id, label: r.label, title: r.title, states: r.states || [], gate: r.gate })));
    for (const k of Object.keys(NL.GATE_AT)) delete NL.GATE_AT[k];
    (wf.gates || []).forEach(g => { if (g.at) NL.GATE_AT[g.at] = g.n; });
    NL.GATES.splice(0, NL.GATES.length, ...(wf.gates || []));
    NL.STAGES.splice(0, NL.STAGES.length, ...(wf.stages || []));
    for (const k of Object.keys(NL.PROC)) delete NL.PROC[k];
    Object.entries(wf.procedures || {}).forEach(([k, v]) => { NL.PROC[k] = v; });
    for (const k of Object.keys(NL.PROCS_FOR_STATE)) delete NL.PROCS_FOR_STATE[k];
    all.forEach(x => { NL.PROCS_FOR_STATE[x.id] = (wf.offer_for_state || {})[x.id] || []; });
    for (const k of Object.keys(NL.NEXT_FOR_STATE)) delete NL.NEXT_FOR_STATE[k];
    Object.assign(NL.NEXT_FOR_STATE, wf.next_for_state || {});
    return true;
  };
  NL.applyWorkflow(window.__WORKFLOW_DEFAULT__);
  const stateOf = st => (NL.WF.states || []).concat(NL.WF.side_states || []).find(y => y.id === st);
  NL.isTerminal = st => !!(stateOf(st) || {}).terminal;   // final, parked, killed: nothing more runs
  NL.isShelved = st => (NL.WF.side_states || []).some(y => y.id === st);   // parked or killed: revivable from here
  NL.stageOf = st => { const x = (NL.WF.states || []).find(y => y.id === st); return x ? NL.STAGES.find(g => g.id === x.stage) : null; };
  // where a state stands in the world (room + station), for the painted and the diorama worlds
  NL.wfStateRoom = () => { const o = {}; (NL.WF.states || []).concat(NL.WF.side_states || []).forEach(x => { if (x.room) o[x.id] = x.room; }); return o; };
  NL.wfStation = st => { const x = (NL.WF.states || []).concat(NL.WF.side_states || []).find(y => y.id === st); return x && x.station; };
  // the procedure a study in `state` should run next (the proposal step depends on Gate 1)
  NL.nextSkill = (state, gateSigned) => { const v = NL.NEXT_FOR_STATE[state]; return v && typeof v === 'object' ? (gateSigned ? v.signed : v.unsigned) : v; };

  // run status → what the PI reads (one vocabulary everywhere)
  NL.RUN_WORD = {
    queued: 'Queued', starting: 'Starting', running: 'Running', resuming: 'Resuming', waiting_input: 'Waiting for you',
    completed: 'Finished', failed: 'Failed', timeout: 'Timed out', killed: 'Stopped',
  };
  NL.RUN_TONE = { queued: 'muted', starting: 'live', running: 'live', resuming: 'live', waiting_input: 'ask',
    completed: 'ok', failed: 'bad', timeout: 'bad', killed: 'muted' };
  NL.RUN_ACTIVE = new Set(['starting', 'running', 'resuming']);
  NL.RUN_DONE = new Set(['completed', 'failed', 'timeout', 'killed']);
  NL.runTitle = r => r ? (r.kind === 'ask' ? (r.label || r.prompt_summary || 'Instruction') : (r.command || r.label || r.prompt_summary || r.run_id)) : '';

  NL.ROLE = {
    orchestrator: { label: 'Orchestrator', color: 'var(--r-orch)' },
    'experiment-runner': { label: 'Experiment runner', color: 'var(--r-run)' },
    'fresh-context-reviewer': { label: 'Reviewer', color: 'var(--r-rev)' },
    overseer: { label: 'Overseer', color: 'var(--r-over)' },
    'ideation-critic': { label: 'Ideation critic', color: 'var(--r-crit)' },
    'scoping-advocate': { label: 'Scoping advocate', color: 'var(--r-scope)' },
  };
  NL.roleOf = r => NL.ROLE[r] || { label: r || 'Agent', color: 'var(--ink-soft)' };

  NL.procTitle = s => (NL.PROC[s] && NL.PROC[s].title) || ('/' + s);

  /* ── the live lab store ────────────────────────────────────────────────── */
  const store = { state: window.__STATE__ || null, live: true, listeners: new Set(), conn: 'connecting' };
  NL.store = store;
  if (store.state && store.state.workflow) NL.applyWorkflow(store.state.workflow);
  NL.getState = () => store.state;
  function emit() { for (const f of store.listeners) { try { f(store.state); } catch (e) { console.error(e); } } }
  NL.setState = s => { const prev = store.state; store.state = s; if (s && s.workflow) NL.applyWorkflow(s.workflow); NL.onSnapshot && NL.onSnapshot(prev, s); emit(); };
  /** Re-render the calling component whenever a listener set fires (the one subscription pattern). */
  const useSub = set => {
    const [, force] = H.useReducer(x => x + 1, 0);
    H.useEffect(() => { set.add(force); return () => set.delete(force); }, []);
  };
  /** Subscribe a component to the lab snapshot (re-renders on every change). */
  NL.useLab = () => { useSub(store.listeners); return store.state || {}; };
  NL.useConn = () => { useSub(store.listeners); return store.conn; };

  NL.DEMO = location.search.includes('demo') && (window.__VIV_DEMO__ === true || location.protocol === 'file:');
  NL.STATIC = location.search.includes('static');

  let es = null, pollT = null, backoff = 15000;
  NL.connect = function connect() {
    if (NL.DEMO || NL.STATIC) return;
    try { es && es.close(); } catch (e) { /* closed */ }
    es = new EventSource('/api/events');
    es.onopen = () => { store.conn = 'live'; backoff = 15000; if (pollT) { clearInterval(pollT); pollT = null; } emit(); };
    es.onmessage = ev => { try { const s = JSON.parse(ev.data); if (!s.error) { store.conn = 'live'; NL.setState(s); } } catch (e) { /* partial */ } };
    es.addEventListener('tick', ev => { try { const t = JSON.parse(ev.data); if (store.state && t.now) { store.state.now = t.now; } } catch (e) { /* ignore */ } });
    es.onerror = () => {
      store.conn = 'reconnecting'; emit();
      try { es.close(); } catch (e) { /* closed */ }
      if (!pollT) pollT = setInterval(NL.refresh, 5000);
      setTimeout(connect, backoff); backoff = Math.min(90000, backoff * 1.5);
    };
  };
  NL.refresh = async () => {
    try { const r = await fetch('/api/state', { credentials: 'same-origin' }); if (r.ok) { NL.setState(await r.json()); store.conn = 'live'; } }
    catch (e) { store.conn = 'offline'; emit(); }
  };

  /* ── API ───────────────────────────────────────────────────────────────── */
  NL.api = async function api(path, body) {
    if (NL.DEMO) return { error: 'demo mode — nothing is written', demo: true };
    try {
      const r = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
      const j = await r.json().catch(() => ({ error: `server said ${r.status}` }));
      if (r.status === 403 && /session/.test(j.error || '')) NL.toast('This page lost its session with the lab — reloading…', 'warn'), setTimeout(() => location.reload(), 1200);
      return j;
    } catch (e) { return { error: 'could not reach the lab server — is it still running?' }; }
  };
  NL.get = async function get(path) {
    try {
      const r = await fetch(path, { credentials: 'same-origin' });
      return await r.json().catch(() => ({ error: `server said ${r.status}` }));
    } catch (e) { return { error: 'could not reach the lab server' }; }
  };
  /** Run an API call with a toast for the outcome; returns the result. */
  NL.act = async (path, body, okMsg) => {
    const r = await NL.api(path, body);
    if (r && r.ok) { NL.toast(okMsg || r.note || 'done', 'ok'); (r.warnings || []).forEach(w => NL.toast(w, 'warn')); setTimeout(NL.refresh, 300); }
    else NL.toast((r && r.error) || 'that did not work', 'bad');
    return r || {};
  };

  /* ── router: #/page/arg/arg ────────────────────────────────────────────── */
  NL.parseRoute = () => {
    const raw = (location.hash || '').replace(/^#\/?/, '');
    const [path, q] = raw.split('?');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    const legacy = { terrarium: '', shelf: 'studies', gates: '', night: '', agents: 'runs', ledger: 'history' };
    if (parts.length === 1 && parts[0] in legacy) return { page: legacy[parts[0]] || 'home', args: [], query: {} };
    const query = Object.fromEntries(new URLSearchParams(q || ''));
    return { page: parts[0] || 'home', args: parts.slice(1), query };
  };
  NL.go = (path) => { const target = '#/' + String(path || '').replace(/^#?\/?/, ''); if (location.hash !== target) location.hash = target; else window.dispatchEvent(new HashChangeEvent('hashchange')); };
  NL.useRoute = () => {
    const [r, setR] = H.useState(NL.parseRoute());
    // resync once listening: a redirect that fired before this effect ran (the first-run wizard) must not be missed
    H.useEffect(() => { const f = () => setR(NL.parseRoute()); window.addEventListener('hashchange', f); f(); return () => window.removeEventListener('hashchange', f); }, []);
    return r;
  };

  /* ── preferences ───────────────────────────────────────────────────────── */
  const PREF_DEFAULTS = { theme: 'auto', world: 'diorama', motion: true, rail: true, notify: false, density: 'comfortable', narrate: false };
  const prefs = Object.assign({}, PREF_DEFAULTS, ls.get('nl-prefs', {}));
  // carry over the old dashboard's choices once
  (() => { const old = ls.get('viv-prefs', null); if (old && !ls.get('nl-prefs', null)) { if (old.world) prefs.world = old.world; if (old.ambient === false) prefs.motion = false; }
    try { const lamp = localStorage.getItem('lamp'); if (lamp && !ls.get('nl-prefs', null)) prefs.theme = lamp === 'light' ? 'day' : lamp === 'dark' ? 'night' : 'auto'; } catch (e) { /* ignore */ } })();
  NL.prefs = prefs;
  const prefListeners = new Set();
  NL.setPref = (k, v) => { prefs[k] = v; ls.set('nl-prefs', prefs); NL.applyTheme(); for (const f of prefListeners) f(prefs); };
  NL.usePrefs = () => { useSub(prefListeners); return prefs; };
  NL.themeNow = () => {
    const q = new URLSearchParams(location.search).get('lamp');
    if (q === 'day' || q === 'light') return 'day';
    if (q === 'night' || q === 'dark') return 'night';
    if (prefs.theme === 'day' || prefs.theme === 'night') return prefs.theme;
    return window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'day' : 'night';
  };
  NL.applyTheme = () => {
    const t = NL.themeNow();
    document.documentElement.dataset.lamp = t;
    document.documentElement.dataset.density = prefs.density;
    if (NL.Scene) NL.Scene.setLamp(t);
  };
  if (window.matchMedia) matchMedia('(prefers-color-scheme: light)').addEventListener?.('change', () => prefs.theme === 'auto' && NL.applyTheme());

  /* ── toasts ────────────────────────────────────────────────────────────── */
  const toasts = { list: [], listeners: new Set(), n: 0 };
  NL.toast = (msg, tone) => {
    if (!msg) return;
    const t = { id: ++toasts.n, msg: String(msg), tone: tone || 'info' };
    toasts.list = [...toasts.list.slice(-3), t];
    toasts.listeners.forEach(f => f());
    setTimeout(() => { toasts.list = toasts.list.filter(x => x !== t); toasts.listeners.forEach(f => f()); }, tone === 'bad' ? 7000 : 4200);
  };
  NL.useToasts = () => { useSub(toasts.listeners); return toasts.list; };

  /* ── layers: sheets and dialogs, stacked; Escape closes the top one ──────
     NL.open(Component, props) → id · NL.close(id) · NL.confirm({...}) → Promise<boolean|string>
     A dialog opened from a sheet sits ABOVE it and never closes it. */
  const layers = { list: [], listeners: new Set(), n: 0 };
  const bump = () => layers.listeners.forEach(f => f());
  NL.open = (Comp, props, opts) => {
    const key = opts && opts.key;
    if (key) { const hit = layers.list.find(l => l.key === key); if (hit) { hit.props = props || {}; bump(); return hit.id; } }
    const id = ++layers.n;
    layers.list = [...layers.list, { id, Comp, props: props || {}, key, kind: (opts && opts.kind) || 'sheet' }];
    bump();
    return id;
  };
  NL.close = id => { const l = layers.list.find(x => x.id === id); layers.list = layers.list.filter(x => x.id !== id); if (l && l.props && l.props.onClose) l.props.onClose(); bump(); };
  NL.closeTop = () => { const top = layers.list[layers.list.length - 1]; if (top) { NL.close(top.id); return true; } return false; };
  NL.isOpen = key => layers.list.some(l => l.key === key);
  // going to another page closes its side sheets (a dialog waiting for an answer stays)
  NL.closeSheets = () => { layers.list.filter(l => l.kind === 'sheet').forEach(l => NL.close(l.id)); };
  NL.useLayers = () => { useSub(layers.listeners); return layers.list; };
  NL.confirm = (o) => new Promise(resolve => {
    let done = false;
    const id = NL.open(NL.ConfirmDialog, { ...o, resolve: v => { if (done) return; done = true; NL.close(id); resolve(v); }, onClose: () => { if (!done) { done = true; resolve(false); } } }, { kind: 'dialog' });
  });
  window.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const t = e.target && e.target.tagName;
    if ((t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT') && e.target.value && !e.target.dataset.escClose) { e.target.blur(); return; }
    if (NL.closeTop()) e.preventDefault();
  });

  /* ── lab accessors ─────────────────────────────────────────────────────── */
  NL.item = (s, id) => ((s && s.items) || []).find(i => i.id === id);
  NL.exec = s => (s && s.executor) || {};
  NL.execOn = s => { const x = NL.exec(s); return !!(x.available !== false && x.enabled); };
  NL.runs = (s, pred) => ((s && s.runs) || []).filter(pred || (() => true));
  NL.run = (s, id) => ((s && s.runs) || []).find(r => r.run_id === id);
  NL.runsOf = (s, slug) => NL.runs(s, r => r.target === slug || r.subject === slug);
  NL.workersOf = (s, slug) => ((s && s.workers) || []).filter(w => w.project === slug || w.idea === slug);
  NL.needsYou = s => ((s && s.attention) || []).filter(a => a.sev !== 'info');
  NL.backends = s => { const c = (NL.exec(s).clis) || {}; return ['claude', 'codex', 'opencode'].map(b => ({ id: b, ...(c[b] || {}) })); };

  /* ── launching (every "start" button ends here) ────────────────────────── */
  NL.launch = async (body, opts) => {
    const s = NL.getState();
    if (!NL.execOn(s)) {
      const on = await NL.confirm({ title: 'Let the dashboard start agents?', ok: 'Turn it on',
        body: 'Starting work from here runs the agent CLI on this machine, as you, with your own login. You can turn this off any time in Settings → Autonomy.' });
      if (!on) return null;
      const r = await NL.api('/api/executor/enable', { enabled: true, confirm: true });
      if (!r.ok) { NL.toast(r.error || 'could not turn launching on', 'bad'); return null; }
    }
    const r = await NL.api('/api/run', { confirm: true, ...body });
    if (r && r.ok) {
      NL.toast(`${r.label ? NL.clip(r.label, 50) : 'Run'} queued — it starts in a moment`, 'ok');
      setTimeout(NL.refresh, 300);
      if (!opts || opts.open !== false) NL.openRun(r.run_id);
      return r;
    }
    NL.toast((r && r.error) || 'could not start it', 'bad');
    return null;
  };
  NL.launchCommand = (cmd, fallbackTarget) => {
    const toks = String(cmd || '').trim().split(/\s+/);
    const skill = (toks[0] || '').replace(/^\//, '');
    const s = NL.getState();
    const cfg = ((s && s.skills) || {})[skill];
    if (!cfg) { NL.toast(`"${cmd}" isn't something the dashboard can start`, 'warn'); return; }
    const rest = toks.slice(1);
    if (skill === 'autopilot') return NL.launch({ skill, args: rest[rest[0] === 'continue' ? 1 : 0] || '' });
    if (cfg.args.startsWith('slug') && rest.length) return NL.launch({ skill, target: rest[0], args: rest.slice(1).join(' ') });
    return NL.launch({ skill, target: cfg.level === 'project' ? (fallbackTarget || 'hub') : 'hub', args: rest.join(' ') });
  };
})();
