/* Newts' Lab — Settings (#/settings/<section>). Human words first; the config key it writes is shown
   small underneath. Every save shows what changes and asks before writing; each change is logged. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, cls } = NL;

  const LOGIN = { claude: 'Opens a window running `claude auth login` — sign in with your Anthropic account in the browser it opens.',
    codex: 'Opens a window running `codex login` — sign in with ChatGPT or an API key there.',
    opencode: 'Opens a window running `opencode auth login` — pick a provider and add its key there.' };
  const WHAT = { claude: 'Claude Code — the default agent', codex: 'OpenAI Codex CLI', opencode: 'opencode — any provider' };

  /** One card per agent CLI: installed? version? signed in? — with Install / Sign in / Check again. */
  NL.AgentsSignIn = ({ compact }) => {
    const s = NL.useLab();
    const [fresh, setFresh] = useState(null);
    const [busy, setBusy] = useState(false);
    const check = async () => { setBusy(true); const h = await NL.get('/api/executor/health?fresh=1'); setFresh(h); setBusy(false); NL.refresh(); };
    const clis = (fresh && fresh.clis) || NL.exec(s).clis || {};
    // after "Sign in", poll for a few minutes until the CLI reports signed in
    const [watch, setWatch] = useState(null);
    useEffect(() => {
      if (!watch) return undefined;
      let n = 0; const t = setInterval(async () => { n++; const h = await NL.get('/api/executor/health?fresh=1'); setFresh(h);
        if ((h.clis || {})[watch] && h.clis[watch].logged_in) { clearInterval(t); setWatch(null); NL.toast(`${watch} is signed in`, 'ok'); NL.refresh(); }
        if (n > 40) { clearInterval(t); setWatch(null); } }, 6000);
      return () => clearInterval(t);
    }, [watch]);
    const term = async (purpose, backend) => { const how = await NL.runOnLabMachine(purpose, backend); if (how) setWatch(purpose === 'login' ? backend : null); };
    return html`<div class=${cls('clis', compact && 'compact')}>${['claude', 'codex', 'opencode'].map(b => {
      const c = clis[b] || {};
      if (NL.DEMO) return html`<div class="cli cli-unknown"><div class="cli-top"><b>${b}</b><${NL.Pill} tone="muted">demo — not checked</${NL.Pill}></div>
        <div class="muted small">${WHAT[b]}</div><div class="muted small">The demo doesn't look at this computer's agents.</div></div>`;
      const st = !c.found ? 'missing' : c.logged_in === true ? 'ok' : c.logged_in === false ? 'out' : 'unknown';
      return html`<div class=${cls('cli', 'cli-' + st)}>
        <div class="cli-top"><b>${b}</b><${NL.Pill} tone=${st === 'ok' ? 'ok' : st === 'missing' ? 'muted' : 'warn'}>${st === 'ok' ? 'signed in' : st === 'missing' ? 'not installed' : st === 'out' ? 'not signed in' : 'sign-in unknown'}</${NL.Pill}></div>
        <div class="muted small">${WHAT[b]}${c.version ? ' · v' + c.version : ''}</div>
        ${watch === b ? html`<div class="note small"><${NL.Spinner} /> Finish signing in in the terminal that opened — this updates by itself.</div>` : null}
        <div class="row">${!c.found ? html`<${NL.Btn} small onClick=${() => term('install', b)}>Install…</${NL.Btn}>`
          : st !== 'ok' ? html`<${NL.Btn} small kind="primary" onClick=${() => term('login', b)} title=${LOGIN[b]}>Sign in…</${NL.Btn}>` : null}
          <button class="link small" onClick=${check} disabled=${busy}>${busy ? 'checking…' : 'check again'}</button></div>
        ${!compact && st !== 'ok' ? html`<div class="muted small">${!c.found ? 'Opens a terminal window that installs it (you watch it run).' : LOGIN[b]} Your credentials go to the CLI, never to this page.</div>` : null}
      </div>`;
    })}</div>`;
  };

  /* every settings form saves the same way: the changed keys, shown old → new, confirmed, then written */
  const changed = (keys, v, orig) => keys.filter(k => String(v[k] ?? '') !== String(orig[k] ?? ''));
  const saveChanges = async (title, path, keys, v, orig) => {
    if (!keys.length || !await NL.confirm({ title, ok: 'Save', body: html`<ul class="diff">${keys.map(k => html`<li><span class="mono">${k}</span>: ${String(orig[k] ?? '—')} → <b>${String(v[k])}</b></li>`)}</ul>` })) return {};
    return NL.act(path, { confirm: true, changes: Object.fromEntries(keys.map(k => [k, v[k]])) }, 'Saved');
  };

  // [key, label, hint, min, default — shown as the placeholder while the field is blank (tools/executor)]
  const EXEC = [
    ['max_minutes', 'Time limit per run', 'minutes', 5, 240],
    ['max_concurrent_total', 'Agents running at once (whole lab)', 'Subagents an agent starts don’t count. Campaign limits apply on top; the lower one wins.', 1, 3],
    ['hub_max_concurrent', 'Lab-wide jobs at once (ideation, registry edits — keep 1)', 'keep 1 so two jobs never edit the registry together', 1, 1],
    ['max_concurrent', 'Agents at once per project (each project can have its own main agent)', '', 1, 3],
    ['daily_max_runs', 'Daily run limit', '0 = no limit', 0, 0], ['daily_max_minutes', 'Daily agent-minutes limit', '0 = no limit', 0, 0],
    ['chain_max_steps', 'Max steps when an agent runs on to the next gate', '', 1, 6],
    ['park_minutes', 'Keep an agent waiting for your answer', 'minutes; then it pauses and your answer resumes it', 1, 60],
    ['permission_minutes', 'Wait for your allow/deny on a risky action', 'minutes; then it is denied (campaigns: at once)', 1, 30],
    ['campaign_question_minutes', 'In a campaign, wait for an answer', 'minutes; then the agent takes its recommended option and tells you', 1, 30],
    ['linger_minutes', 'Keep Ask Newt (the chat box on Home) open after it answers', 'minutes, for your next message', 0, 10],
  ];
  const ExecForm = () => {
    const s = NL.useLab();
    const x = NL.exec(s), cfg = x.config || {};
    const init = () => Object.fromEntries([...EXEC.map(([k]) => [k, cfg[k] ?? '']), ['backend', x.backend || 'claude'], ['model', cfg.model || ''], ['permission_mode', x.permission_mode || 'auto'], ['auto_spawn_on_gate1', !!x.auto_spawn_on_gate1], ['live', cfg.live !== false]]);
    const [v, setV] = useState(init);
    const orig = init();
    const diff = changed(Object.keys(v), v, orig);
    const save = () => saveChanges('Save these settings?', '/api/executor/config', diff, v, orig);
    const set = (k, val) => setV(o => ({ ...o, [k]: val }));
    return html`<div class="form">
      <div class="grid2">
        <${NL.Field} label="Default agent"><${NL.Select} value=${v.backend} onChange=${x2 => set('backend', x2)} options=${['claude', 'codex', 'opencode']} /></${NL.Field}>
        <${NL.Field} label="Default model" hint="blank or “inherit” = the agent's own default"><${NL.Input} value=${v.model} onInput=${x2 => set('model', x2)} mono /></${NL.Field}>
        <${NL.Field} label="What claude may do without asking" hint="auto = its safety classifier decides; plan = read-only"><${NL.Select} value=${v.permission_mode} onChange=${x2 => set('permission_mode', x2)}
          options=${[{ value: 'auto', label: 'auto (recommended)' }, { value: 'acceptEdits', label: 'accept file edits' }, { value: 'default', label: 'ask for everything' }, { value: 'plan', label: 'plan only (read-only)' }, { value: 'dontAsk', label: 'deny anything that would ask' }]} /></${NL.Field}>
        ${EXEC.map(([k, label, hint, min, def]) => html`<${NL.Field} label=${label} hint=${hint}><${NL.Input} type="number" min=${min} value=${v[k]} onInput=${x2 => set(k, x2)} placeholder=${def != null ? String(def) + ' (default)' : ''} /></${NL.Field}>`)}
      </div>
      <${NL.Toggle} on=${v.live} onChange=${x2 => set('live', x2)} label="Talk to agents while they run" sub="live sessions: questions, approvals and your messages reach the running agent; off = each answer restarts it" />
      <${NL.Toggle} on=${v.auto_spawn_on_gate1} onChange=${x2 => set('auto_spawn_on_gate1', x2)} label="Create the project as soon as I sign Gate 1" sub="queues creating the project repo right after your signature" />
      <div class="row end">${diff.length ? html`<span class="muted small">${NL.plural(diff.length, 'change')}</span><${NL.Btn} onClick=${() => setV(init())}>Reset</${NL.Btn}>` : null}<${NL.Btn} kind="primary" disabled=${!diff.length} onClick=${save}>Save…</${NL.Btn}></div></div>`;
  };

  NL.LaunchSwitch = () => {
    const s = NL.useLab();
    const on = NL.execOn(s);
    return html`<${NL.Toggle} on=${on} label="Let the dashboard start agents for you" sub=${on ? 'On — buttons here start headless Claude/Codex/opencode sessions on this machine, as you.' : 'Off — it only records what you ask, and you run it in your own terminal.'}
      onChange=${async val => { if (await NL.confirm({ title: val ? 'Let the dashboard start agents?' : 'Stop starting agents from here?', ok: val ? 'Turn on' : 'Turn off',
        body: val ? 'It runs the agent CLI on this machine, as you, with your login, within the limits below. Gates still wait for your signature.' : 'Nothing new starts from here. Runs already going finish on their own.' }))
        NL.act('/api/executor/enable', { enabled: val, confirm: true }, val ? 'Launching is on' : 'Launching is off'); }} />`;
  };

  const LabForm = () => {
    const [c, setC] = useState(null);
    const [v, setV] = useState({});
    const load = () => NL.get('/api/lab/config').then(x => { setC(x.config || {}); setV({ ...(x.config || {}) }); });
    useEffect(() => { load(); }, []);
    if (!c) return html`<${NL.Spinner} />`;
    const keys = ['name', 'projects_root', 'max_concurrent_runs', 'oversight', 'venue', 'page_limit', 'max_concurrent_projects',
      'loop_mode', 'explore_rounds', 'in_project_approval', 'keep_awake'];
    const diff = changed(keys, v, c);
    const set = (k, x) => setV(o => ({ ...o, [k]: x }));
    const save = async () => { if ((await saveChanges('Save lab settings?', '/api/lab/config', diff, v, c)).ok) load(); };
    const tier = async t => { if (await NL.confirm({ title: `Apply the ${t} budget tier?`, ok: 'Apply', body: 'Sets how many ideas, critics and parallel agents each procedure uses (lab/profiles/' + t + '.yaml). Integrity floors are never lowered.' }))
      NL.act('/api/lab/config', { confirm: true, changes: { budget_tier: t } }, `Applied the ${t} tier`); };
    return html`<div class="form"><div class="grid2">
      <${NL.Field} label="Lab name"><${NL.Input} value=${v.name} onInput=${x => set('name', x)} /></${NL.Field}>
      <${NL.Field} label="Where project repos go" hint="relative to the lab folder"><${NL.Input} value=${v.projects_root} onInput=${x => set('projects_root', x)} mono /></${NL.Field}>
      <${NL.Field} label="Training runs at once (all projects)" hint="compute slots — the number of GPUs you can use in parallel"><${NL.Input} type="number" min="1" value=${v.max_concurrent_runs} onInput=${x => set('max_concurrent_runs', x)} /></${NL.Field}>
      <${NL.Field} label="Projects a campaign carries at once"><${NL.Input} type="number" min="1" value=${v.max_concurrent_projects ?? 1} onInput=${x => set('max_concurrent_projects', x)} /></${NL.Field}>
      <${NL.Field} label="Oversight"><${NL.Seg} value=${v.oversight || 'standard'} onChange=${x => set('oversight', x)} options=${[{ value: 'standard', label: 'Standard' }, { value: 'strict', label: 'Strict' }]} /></${NL.Field}>
      <${NL.Field} label="Target venue"><${NL.Input} value=${v.venue} onInput=${x => set('venue', x)} placeholder="neurips, icml, …" /></${NL.Field}>
      <${NL.Field} label="Page limit"><${NL.Input} type="number" min="1" value=${v.page_limit} onInput=${x => set('page_limit', x)} /></${NL.Field}>
      <${NL.Field} label="Research loops" hint="explore: a project's loop may widen its plan and reopen supporting decisions within its signed envelope"><${NL.Seg} value=${v.loop_mode || 'execute'} onChange=${x => set('loop_mode', x)} options=${[{ value: 'execute', label: 'Follow the plan' }, { value: 'explore', label: 'Explore' }]} /></${NL.Field}>
      <${NL.Field} label="Plan-widening rounds per loop" hint="explore mode only"><${NL.Input} type="number" min="0" value=${v.explore_rounds ?? 0} onInput=${x => set('explore_rounds', x)} /></${NL.Field}>
      <${NL.Field} label="New approaches inside a campaign" hint="a headline-changing idea found mid-project"><${NL.Seg} value=${v.in_project_approval || 'pi'} onChange=${x => set('in_project_approval', x)} options=${[{ value: 'pi', label: 'Ask me' }, { value: 'campaign_auto', label: 'Within the campaign bounds' }]} /></${NL.Field}>
      <${NL.Field} label="Keep the computer awake" hint="while agents work or a campaign runs (the screen may still turn off)"><${NL.Seg} value=${v.keep_awake || 'auto'} onChange=${x => set('keep_awake', x)} options=${[{ value: 'auto', label: 'While working' }, { value: 'off', label: 'Never' }]} /></${NL.Field}>
      <${NL.Field} label="Budget tier" hint="how much exploration each procedure does"><div class="row">${['low', 'medium', 'high'].map(t => html`<${NL.Btn} small onClick=${() => tier(t)}>${t}</${NL.Btn}>`)}</div></${NL.Field}>
    </div><div class="row end">${diff.length ? html`<${NL.Btn} onClick=${() => setV({ ...c })}>Reset</${NL.Btn}>` : null}<${NL.Btn} kind="primary" disabled=${!diff.length} onClick=${save}>Save…</${NL.Btn}></div>
    <div class="stack"><button class="link" onClick=${() => NL.open(NL.DocEditSheet, { which: 'system' })}>Describe this machine for the agents (SYSTEM.md) →</button>
      <button class="link" onClick=${() => NL.openStart({ intent: 'configure' })}>Change anything else with an agent (/configure) →</button></div></div>`;
  };

  const Keys = () => {
    const [k, setK] = useState(null);
    const load = () => NL.get('/api/keys').then(setK);
    useEffect(() => { load(); }, []);
    const edit = async (key, label) => {
      const val = await NL.confirm({ title: `${label} key`, input: 'Paste the key (stored in lab/.env.local, never shown again)', ok: 'Save' });
      if (val) { await NL.act('/api/keys', { key, value: val }, 'Saved'); load(); }
    };
    const [custom, setCustom] = useState('');
    if (!k) return html`<${NL.Spinner} />`;
    return html`<div class="form"><p class="muted">Literature search works without keys, but rate-limited. Keys are kept in <span class="mono">${k.file}</span> in this lab and handed to every run. They are never shown or sent anywhere else.</p>
      ${(k.keys || []).map(x => html`<div class="keyrow"><b>${x.label}</b><span class="mono small muted">${x.key}</span><span class="grow"></span>
        <${NL.Pill} tone=${x.set ? 'ok' : 'muted'}>${x.set ? (x.where === 'environment' ? 'set in your environment' : 'saved') : 'not set'}</${NL.Pill}>
        <${NL.Btn} small onClick=${() => edit(x.key, x.label)}>${x.where === 'lab' ? 'Replace' : 'Add'}</${NL.Btn}>
        ${x.where === 'lab' ? html`<${NL.Btn} small onClick=${async () => { await NL.act('/api/keys', { key: x.key, value: '' }, 'Removed'); load(); }}>Remove</${NL.Btn}>` : null}</div>`)}
      <div class="row"><${NL.Input} value=${custom} onInput=${v => setCustom(v.toUpperCase())} placeholder="OTHER_API_KEY" mono /><${NL.Btn} disabled=${!/^[A-Z][A-Z0-9_]{1,40}$/.test(custom)} onClick=${() => edit(custom, custom)}>Add another</${NL.Btn}></div></div>`;
  };

  const Appearance = () => {
    const p = NL.usePrefs();
    return html`<div class="form">
      <${NL.Field} label="Theme"><${NL.Seg} value=${p.theme} onChange=${v => NL.setPref('theme', v)} options=${[{ value: 'auto', label: 'Match my system' }, { value: 'day', label: 'Day — the atelier' }, { value: 'night', label: 'Night — the cave' }]} /></${NL.Field}>
      <${NL.Field} label="Density"><${NL.Seg} value=${p.density} onChange=${v => NL.setPref('density', v)} options=${[{ value: 'comfortable', label: 'Comfortable' }, { value: 'compact', label: 'Compact' }]} /></${NL.Field}>
      <${NL.Toggle} on=${p.motion} onChange=${v => { NL.setPref('motion', v); NL.Scene && NL.Scene.setAmbient(v); }} label="Ambient motion" sub="drifting motes, swaying plants (off also when your system asks for reduced motion)" />
      <${NL.Toggle} on=${p.rail} onChange=${v => NL.setPref('rail', v)} label="Show the Today rail on Home" />
      <${NL.Toggle} on=${p.narrate} onChange=${v => NL.setPref('narrate', v)} label="Newt narrates" sub="short speech bubbles quoting what just happened" />
      <${Cast} /></div>`;
  };

  /* who plays the agents in the world: one character for all, or one per tool so you can tell them apart */
  const Cast = () => {
    const p = NL.usePrefs(), c = p.cast || {};
    const chars = (window.Lab3D && Lab3D.CHARACTERS) || [{ id: 'newt', label: 'Newt' }];
    const opts = chars.map(x => ({ value: x.id, label: x.label }));
    const set = patch => { const next = { ...c, ...patch }; NL.setPref('cast', next); NL.Scene && NL.Scene.setCast(next); };
    return html`<${NL.Section} title="The cast">
      <p class="muted small">Who plays the agents on Home. A main agent's subagents are smaller copies of it, in the same colours.</p>
      <${NL.Seg} value=${c.mode || 'backend'} onChange=${v => set({ mode: v })} options=${[{ value: 'backend', label: 'One per tool' }, { value: 'one', label: 'One for everyone' }]} />
      ${c.mode === 'one' ? html`<${NL.Field} label="Every agent is a"><${NL.Select} value=${c.one || 'newt'} onChange=${v => set({ one: v })} options=${opts} /></${NL.Field}>`
        : html`<div class="grid3">${[['claude', 'Claude'], ['codex', 'Codex'], ['opencode', 'opencode']].map(([k, l]) => html`<${NL.Field} label=${l}><${NL.Select} value=${c[k] || 'newt'} onChange=${v => set({ [k]: v })} options=${opts} /></${NL.Field}>`)}</div>`}
      <a class="link small" href="/static/world3d/newt.html" target="_blank" rel="noopener">Meet the cast ↗</a></${NL.Section}>`;
  };

  const Notifications = () => {
    const p = NL.usePrefs();
    const perm = window.Notification ? Notification.permission : 'unsupported';
    return html`<div class="form">
      <${NL.Toggle} on=${p.notify && perm === 'granted'} onChange=${async v => { if (v && window.Notification && Notification.permission !== 'granted') { const r = await Notification.requestPermission(); if (r !== 'granted') return NL.toast('The browser blocked notifications', 'warn'); } NL.setPref('notify', v); }}
        label="Desktop notifications" sub="when an agent asks you something, a gate opens, or a run finishes or fails — even with this tab in the background" />
      ${perm === 'denied' ? html`<div class="note note-warn">Notifications are blocked for this page in your browser's site settings.</div>` : null}
      <p class="muted small">The tab title always shows how many things are waiting on you.</p>
      <${NL.Section} title="Sound"><${NL.SoundControls} /></${NL.Section}>
      <${NL.Section} title="On your phone"><${PhoneNotify} /></${NL.Section}></div>`;
  };

  /* questions, approvals and gates → ntfy / a webhook, sent by the lab's scheduler (works with this page closed) */
  const PhoneNotify = () => {
    const [c, setC] = useState(null);
    const [v, setV] = useState({ ntfy: '', webhook: '', link: '' });
    const load = () => NL.get('/api/notify').then(x => { setC(x); setV({ ntfy: '', webhook: '', link: x.link || '' }); });
    useEffect(() => { load(); }, []);
    if (!c) return html`<${NL.Spinner} />`;
    const changes = Object.fromEntries(Object.entries(v).filter(([k, x]) => k === 'link' ? x !== (c.link || '') : x.trim()));
    const save = async () => { const r = await NL.act('/api/notify', { confirm: true, ...changes }); if (r.ok) load(); };
    const clear = async k => { if (await NL.confirm({ title: `Stop sending to ${k}?`, ok: 'Stop' })) { const r = await NL.act('/api/notify', { confirm: true, [k]: '' }); if (r.ok) load(); } };
    const row = (k, label, hint, ph) => html`<${NL.Field} label=${label} hint=${hint}>
      ${c[k] && k !== 'link' ? html`<div class="row"><span class="mono small">${c[k]}</span><button class="link small" onClick=${() => clear(k)}>remove</button></div>` : null}
      <${NL.Input} value=${v[k]} onInput=${x => setV(o => ({ ...o, [k]: x }))} placeholder=${c[k] && k !== 'link' ? 'replace with…' : ph} mono /></${NL.Field}>`;
    return html`<div class="form">
      <p class="muted small">The lab sends what needs you — a question, an approval, a gate, a stalled campaign — once each, even when this page is closed. Only the title and one line are sent, never files or transcripts. These addresses are kept in the lab's <span class="mono">.env.local</span> (not committed, not given to agents): anyone who knows an ntfy topic can read it, so pick a long random one.</p>
      ${row('ntfy', 'ntfy topic', 'install the ntfy app and subscribe to the same topic', 'https://ntfy.sh/your-long-random-topic')}
      ${row('webhook', 'Webhook', 'Slack, Discord, Teams — any incoming webhook', 'https://hooks.slack.com/services/…')}
      ${row('link', 'Dashboard address from your phone', 'each notification opens the item here — e.g. your Tailscale address; leave empty for no link', 'http://my-computer:8787')}
      <div class="row end"><${NL.Btn} onClick=${() => NL.act('/api/notify/test', {})} disabled=${!(c.ntfy || c.webhook)}>Send a test</${NL.Btn}>
        <${NL.Btn} kind="primary" disabled=${!Object.keys(changes).length} onClick=${save}>Save</${NL.Btn}></div></div>`;
  };

  const About = () => {
    const s = NL.useLab();
    const li = s.lab_info || {};
    return html`<div class="form">
      <div class="facts"><div><span>Lab</span><b>${li.name || '—'}</b></div><div><span>Folder</span><b class="mono small">${li.path || ''}</b></div><div><span>Dashboard</span><b>v${window.__NL_VERSION__ || '2'}</b></div></div>
      <div class="row"><${NL.Btn} onClick=${() => NL.go('labs')}>Switch or create a lab</${NL.Btn}><${NL.Btn} onClick=${async () => { if (await NL.confirm({ title: 'Open a terminal in the lab folder?', ok: 'Open', body: 'A shell on the machine the lab runs on, as you. Anything you type runs there.' })) NL.runOnLabMachine('shell'); }}>Open a terminal here</${NL.Btn}>
        <${NL.Btn} onClick=${() => NL.go('setup')}>Run the setup again</${NL.Btn}><${NL.Btn} onClick=${() => NL.go('history')}>History</${NL.Btn}></div>
      <${NL.Section} title="Server"><p class="muted small">Stopping the server closes this dashboard. Agents already running keep going; start it again with <span class="mono">Start Newts Lab</span>.</p>
        <${NL.Btn} kind="danger" onClick=${async () => { if (await NL.confirm({ title: 'Stop the dashboard server?', ok: 'Stop it', danger: true, body: 'Running agents keep going. You can start it again any time.' })) { const r = await NL.api('/api/server/stop', { confirm: true }); NL.toast(r.note || r.error, r.ok ? 'ok' : 'bad'); } }}>Stop the server</${NL.Btn}></${NL.Section}></div>`;
  };

  /* this machine: what it offers, and how training runs on it (compute.scheduler) */
  const System = () => {
    const [d, setD] = useState(null);
    const [sc, setSc] = useState(null);
    const load = fresh => NL.get('/api/system' + (fresh ? '?fresh=1' : '')).then(x => { setD(x); if (x.ok) setSc(JSON.parse(JSON.stringify(x.scheduler || { kind: 'local' }))); });
    useEffect(() => { load(false); }, []);
    if (!d) return html`<${NL.Spinner} />`;
    if (!d.ok) return html`<div class="note note-warn">${d.error}</div>`;
    const f = d.facts || {};
    const s2 = NL.getState() || {};
    const where = s2.remote ? s2.remote.name : 'this computer';
    const set = (path, v) => setSc(o => { const n = JSON.parse(JSON.stringify(o)); let t = n; const ks = path.split('.'); ks.slice(0, -1).forEach(k => { t[k] = t[k] || {}; t = t[k]; }); t[ks[ks.length - 1]] = v; return n; });
    const slurm = (sc && sc.slurm) || {}, custom = (sc && sc.custom) || {};
    const stages = (sc && sc.stages) || ['PILOT', 'FULL'];
    const lines = v => (Array.isArray(v) ? v : []).join('\n');
    const toLines = v => v.split('\n').map(x => x.trim()).filter(Boolean);
    const sug = f.suggested_scheduler || { kind: 'local' };
    const suggest = () => setSc(o => ({ ...o, kind: sug.kind, stages: sug.stages || o.stages, slurm: { ...(o.slurm || {}), ...(sug.slurm || {}) } }));
    const save = async () => {
      if (!await NL.confirm({ title: 'Save how training runs here?', ok: 'Save',
        body: sc.kind === 'local' ? 'PILOT and FULL runs will run directly on this machine.' : html`<p>PILOT/FULL runs will be <b>submitted to ${sc.kind}</b> and waited on — the setup lines run on the compute node before each run. Written to <span class="mono">lab/config.yaml</span> (compute.scheduler), logged.</p>` })) return;
      const r = await NL.act('/api/system/scheduler', { scheduler: sc, confirm: true }, 'Saved');
      if (r.ok) load(false);
    };
    const gpus = f.gpus || [];
    const scheds = Object.entries(f.schedulers || {}).filter(([, v]) => v).map(([k]) => k.toUpperCase()).join(', ');
    const parts = (f.slurm && f.slurm.partitions) || [];
    return html`<div class="form">
      <p class="muted">The machine the lab lives on — <b>${where}</b>. Agents read this, and every PILOT/FULL training run follows the choice below. Site rules that aren't settings (data paths, quotas, what not to touch) go in <button class="link" onClick=${() => NL.open(NL.DocEditSheet, { which: 'system' })}>SYSTEM.md</button>.</p>
      <div class="sysfacts">
        <div><span>Machine</span><b>${f.hostname || '?'} · ${f.os} ${f.arch}</b></div>
        <div><span>CPUs · memory</span><b>${f.cpus || '?'} · ${f.memory_gb ? f.memory_gb + ' GB' : '?'}</b></div>
        <div><span>GPUs</span><b>${gpus.length ? gpus.map(g => g.name + (g.memory_gb ? ' (' + g.memory_gb + ' GB)' : '')).join(', ') : 'none found'}</b></div>
        <div><span>Disk free</span><b>${f.disk ? f.disk.free_gb + ' GB of ' + f.disk.total_gb : '?'}</b></div>
        <div><span>Schedulers</span><b>${scheds || 'none'}${f.modules ? ' · environment modules' : ''}</b></div>
        ${parts.length ? html`<div><span>Partitions</span><b>${parts.map(p => p.name + (p.default ? '*' : '') + (p.gres && p.gres !== '(null)' ? ' (' + p.gres + ')' : '')).join(' · ')}</b></div>` : null}
      </div>
      ${f.login_node_hint ? html`<div class="note">This looks like a cluster login node: the dashboard and agents run here, and training should go through SLURM.</div>` : null}
      <div class="row"><button class="link small" onClick=${() => load(true)}>check again</button>${sug.kind !== (sc && sc.kind) ? html`<${NL.Btn} small onClick=${suggest}>Use the detected setup (${sug.kind})</${NL.Btn}>` : null}</div>
      ${sc ? html`<${NL.Section} title="Where training runs">
        <${NL.Seg} value=${sc.kind} onChange=${v => set('kind', v)} options=${[{ value: 'local', label: 'Right here' }, { value: 'slurm', label: 'Through SLURM' }, { value: 'custom', label: 'Another scheduler' }]} />
        ${sc.kind !== 'local' ? html`<div class="row-wrap small">Send these stages: ${['SMOKE', 'PILOT', 'FULL'].map(st => html`<label class="check inline"><input type="checkbox" checked=${stages.includes(st)} onChange=${e => set('stages', e.target.checked ? [...stages, st] : stages.filter(x => x !== st))} /> ${st}</label>`)}</div>` : null}
        ${sc.kind === 'slurm' ? html`<div class="grid3">
          ${[['partition', 'Partition'], ['account', 'Account'], ['qos', 'QOS'], ['mem', 'Memory (e.g. 32G)'], ['constraint', 'Constraint'], ['gres', 'GRES (overrides GPUs)']].map(([k, l]) => html`<${NL.Field} label=${l}><${NL.Input} value=${slurm[k] || ''} onInput=${v => set('slurm.' + k, v)} mono /></${NL.Field}>`)}
          ${[['gpus_per_run', 'GPUs per run'], ['cpus_per_task', 'CPUs per run'], ['time_grace_minutes', 'Extra minutes on --time']].map(([k, l]) => html`<${NL.Field} label=${l}><${NL.Input} type="number" min="0" value=${slurm[k] ?? ''} onInput=${v => set('slurm.' + k, v === '' ? null : +v)} /></${NL.Field}>`)}
        </div>
        <div class="grid2"><${NL.Field} label="Setup lines (run first in each job)" hint="module load …, source …/activate"><textarea class="input textarea mono" rows="3" value=${lines(slurm.setup)} onInput=${e => set('slurm.setup', toLines(e.target.value))}></textarea></${NL.Field}>
          <${NL.Field} label="More sbatch flags" hint="one per line, e.g. --exclusive"><textarea class="input textarea mono" rows="3" value=${lines(slurm.extra_args)} onInput=${e => set('slurm.extra_args', toLines(e.target.value))}></textarea></${NL.Field}></div>` : null}
        ${sc.kind === 'custom' ? html`<div class="grid3">${[['submit', 'Submit — contains {script}, prints the job id', 'qsub {script}'], ['state', 'State — {job}', 'qstat {job}'], ['cancel', 'Cancel — {job}', 'qdel {job}']].map(([k, l, ph]) => html`<${NL.Field} label=${l}><${NL.Input} value=${custom[k] || ''} onInput=${v => set('custom.' + k, v)} placeholder=${ph} mono /></${NL.Field}>`)}</div>
          <div class="grid2"><${NL.Field} label="Job script header lines"><textarea class="input textarea mono" rows="3" value=${lines(custom.header)} onInput=${e => set('custom.header', toLines(e.target.value))}></textarea></${NL.Field}>
            <${NL.Field} label="Setup lines"><textarea class="input textarea mono" rows="3" value=${lines(custom.setup)} onInput=${e => set('custom.setup', toLines(e.target.value))}></textarea></${NL.Field}></div>` : null}
        <p class="muted small">${sc.kind === 'local' ? 'Runs execute on this machine, one per compute slot.' : 'run.py submits each run and waits for it — same artifacts, same logs, budgets enforced on the node; queue time never counts. Agents are told never to submit jobs themselves.'}</p>
        <div class="row end"><${NL.Btn} kind="primary" onClick=${save}>Save…</${NL.Btn}></div></${NL.Section}>` : null}
    </div>`;
  };

  const SECTIONS = [
    { id: 'agents', label: 'Agents & sign-in', C: () => html`<p class="muted">The lab runs these command-line agents on this machine, as you. At least one needs to be installed and signed in.</p><${NL.AgentsSignIn} />` },
    { id: 'autonomy', label: 'Autonomy & limits', C: () => html`<${NL.LaunchSwitch} /><${ExecForm} />` },
    { id: 'lab', label: 'Lab', C: LabForm },
    { id: 'system', label: 'System & compute', C: System },
    { id: 'keys', label: 'Research keys', C: Keys },
    { id: 'appearance', label: 'Appearance', C: Appearance },
    { id: 'notifications', label: 'Notifications', C: Notifications },
    { id: 'about', label: 'About & server', C: About },
  ];
  NL.SETTINGS_SECTIONS = SECTIONS;
  NL.SettingsPage = ({ args }) => {
    const cur = SECTIONS.find(x => x.id === args[0]) || SECTIONS[0];
    return html`<div class="page page-split">
      <aside class="split-left"><div class="split-head"><h1>Settings</h1></div><nav class="side-nav">${SECTIONS.map(x => html`<a class=${cls('side-link', x.id === cur.id && 'on')} href=${'#/settings/' + x.id}>${x.label}</a>`)}</nav></aside>
      <main class="split-right"><h2>${cur.label}</h2><${cur.C} /></main></div>`;
  };
})();
