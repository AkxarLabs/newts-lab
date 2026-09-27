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
  NL.day = ts => (ts || '').slice(0, 10);
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

  /* ── lifecycle vocabulary (one place) ──────────────────────────────────── */
  NL.LIFECYCLE = ['seed', 'triaged', 'lit-review', 'scoping', 'proposal', 'active', 'analysis', 'writing', 'internal-review', 'final'];
  NL.STATE_LABEL = {
    seed: 'Seed', triaged: 'Triaged', 'lit-review': 'Literature review', scoping: 'Scoping', proposal: 'Proposal',
    active: 'Experiments', analysis: 'Analysis', writing: 'Writing', 'internal-review': 'Internal review',
    final: 'Final', parked: 'Parked', killed: 'Killed',
  };
  // the rooms of the building = the Studies board columns
  NL.ROOMS = [
    { key: 'incubator', label: 'Ideas', states: ['seed', 'triaged'] },
    { key: 'study', label: 'Study', states: ['lit-review', 'scoping', 'proposal'] },
    { key: 'lab', label: 'Lab', states: ['active', 'analysis'] },
    { key: 'writing', label: 'Writing', states: ['writing', 'internal-review'] },
    { key: 'archive', label: 'Done', states: ['final'] },
    { key: 'margins', label: 'Margins', states: ['parked', 'killed'] },
  ];
  NL.roomOf = st => (NL.ROOMS.find(r => r.states.includes(st)) || NL.ROOMS[0]).key;
  // the gate each step waits on (a door between rooms)
  NL.GATE_AT = { proposal: 1, active: 2, 'internal-review': 3 };

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

  // procedures in plain words (what the composer and the study page offer)
  NL.PROC = {
    'lab-status': { title: 'Check on the lab', does: 'Reads the registry, inboxes and notebook and recommends the next step.' },
    ideate: { title: 'Explore a new direction', does: 'Researches the direction, generates and critiques ideas, and files the best 1–3 as studies.', stops: 'when the ideas are filed' },
    'lit-review': { title: 'Review the literature', does: 'Searches and reads related work and gives a novelty verdict.', stops: 'with the verdict' },
    scope: { title: 'Scope the design', does: 'Writes the design decisions (and re-checks whether it is still worth doing).' },
    propose: { title: 'Write the proposal', does: 'Writes the full plan — hypothesis, staged experiments, budgets, kill criteria.', stops: 'at Gate 1, for your signature' },
    'spawn-project': { title: 'Create the project repo', does: 'Creates the project repository from the approved proposal and runs its smoke test.', stops: 'when the smoke test is green' },
    advance: { title: 'Advance one step', does: 'Runs exactly the next lifecycle stage for a study, then stops.' },
    experiment: { title: 'Run experiments', does: 'Smoke → pilot → full runs from the plan, logged and committed.', stops: 'before FULL runs outside a signed envelope' },
    improve: { title: 'Improve the method', does: 'Draft / debug / improve operators in parallel worktrees.' },
    'research-loop': { title: 'Run the research loop', does: 'Unattended experiment cycles within the signed loop brief.', stops: 'at the brief\'s stop conditions' },
    analyze: { title: 'Analyze results', does: 'Analyzes the runs and routes the study: more experiments, writing, or stop.' },
    'make-figures': { title: 'Make figures', does: 'Builds the paper figures from the run artifacts.' },
    'write-paper': { title: 'Write the paper', does: 'Drafts the paper with every claim linked to evidence.' },
    'critique-paper': { title: 'Critique the paper', does: 'A fresh-context reviewer ensemble critiques the draft.' },
    'review-paper': { title: 'Internal review', does: 'Review cycles until the paper is accepted internally.', stops: 'at Gate 3, for your signature' },
    adopt: { title: 'Bring in what I have', does: 'Enters the lifecycle mid-stream from an idea, a design, a repo or a draft.' },
    autopilot: { title: 'Run a campaign', does: 'Carries several ideas end-to-end within a signed campaign brief.' },
    discuss: { title: 'Talk it through', does: 'A one-question-at-a-time conversation with live research. Crosses no gate.' },
    compete: { title: 'Compete on a target', does: 'An interview for a fixed-target task (a benchmark, a score).' },
    'setup-lab': { title: 'Set up the lab', does: 'The first-run interview: research areas, budgets, compute, venue, models.' },
    configure: { title: 'Change lab settings', does: 'Views or edits the lab configuration with you.' },
    finalize: { title: 'Finalize', does: 'The reproducibility pass and knowledge write-back after Gate 3.' },
  };
  NL.procTitle = s => (NL.PROC[s] && NL.PROC[s].title) || ('/' + s);
  // which procedures fit a study in a given state (the study page's "work on it" list; first = the default)
  NL.PROCS_FOR_STATE = {
    seed: ['advance', 'lit-review', 'discuss'], triaged: ['lit-review', 'advance', 'discuss'],
    'lit-review': ['lit-review', 'scope', 'advance'], scoping: ['scope', 'propose', 'advance'],
    proposal: ['propose', 'spawn-project', 'advance'], active: ['experiment', 'improve', 'research-loop', 'analyze'],
    analysis: ['analyze', 'experiment', 'make-figures', 'write-paper'], writing: ['write-paper', 'make-figures', 'critique-paper'],
    'internal-review': ['review-paper', 'critique-paper', 'write-paper'], final: [], parked: [], killed: [],
  };

  /* ── the live lab store ────────────────────────────────────────────────── */
  const store = { state: window.__STATE__ || null, live: true, listeners: new Set(), conn: 'connecting' };
  NL.store = store;
  NL.getState = () => store.state;
  function emit() { for (const f of store.listeners) { try { f(store.state); } catch (e) { console.error(e); } } }
  NL.setState = s => { const prev = store.state; store.state = s; NL.onSnapshot && NL.onSnapshot(prev, s); emit(); };
  /** Subscribe a component to the lab snapshot (re-renders on every change). */
  NL.useLab = () => {
    const [, force] = H.useReducer(x => x + 1, 0);
    H.useEffect(() => { store.listeners.add(force); return () => store.listeners.delete(force); }, []);
    return store.state || {};
  };
  NL.useConn = () => {
    const [c, setC] = H.useState(store.conn);
    H.useEffect(() => { const f = () => setC(store.conn); store.listeners.add(f); return () => store.listeners.delete(f); }, []);
    return c;
  };

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
    H.useEffect(() => { const f = () => setR(NL.parseRoute()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
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
  NL.usePrefs = () => {
    const [, force] = H.useReducer(x => x + 1, 0);
    H.useEffect(() => { prefListeners.add(force); return () => prefListeners.delete(force); }, []);
    return prefs;
  };
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
  NL.useToasts = () => {
    const [, force] = H.useReducer(x => x + 1, 0);
    H.useEffect(() => { toasts.listeners.add(force); return () => toasts.listeners.delete(force); }, []);
    return toasts.list;
  };

  /* ── layers: sheets and dialogs, stacked; Escape closes the top one ──────
     NL.open(Component, props) → id · NL.close(id) · NL.confirm({...}) → Promise<boolean|string>
     A dialog opened from a sheet sits ABOVE it and never closes it. */
  const layers = { list: [], listeners: new Set(), n: 0 };
  NL.layers = layers;
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
  NL.closeKey = key => { const l = layers.list.find(x => x.key === key); if (l) NL.close(l.id); };
  NL.closeTop = () => { const top = layers.list[layers.list.length - 1]; if (top) { NL.close(top.id); return true; } return false; };
  NL.isOpen = key => layers.list.some(l => l.key === key);
  NL.useLayers = () => {
    const [, force] = H.useReducer(x => x + 1, 0);
    H.useEffect(() => { layers.listeners.add(force); return () => layers.listeners.delete(force); }, []);
    return layers.list;
  };
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
  NL.inbox = s => ((s && s.attention) || []).filter(a => a.sev !== 'info' || a.kind === 'report');
  NL.needsYou = s => ((s && s.attention) || []).filter(a => a.sev !== 'info');
  NL.backends = s => { const c = (NL.exec(s).clis) || {}; return ['claude', 'codex', 'opencode'].map(b => ({ id: b, ...(c[b] || {}) })); };
  NL.readyBackend = s => NL.backends(s).find(b => b.found && b.logged_in !== false && b.id === (NL.exec(s).backend || 'claude')) || NL.backends(s).find(b => b.found && b.logged_in);

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
