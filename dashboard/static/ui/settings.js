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

  const EXEC = [
    ['max_minutes', 'Time limit per run', 'minutes', 5],
    ['max_concurrent_total', 'Runs at once, lab-wide', '', 1], ['hub_max_concurrent', 'Lab-level runs at once', 'keep 1 so two runs never edit the registry together', 1],
    ['max_concurrent', 'Runs at once per project', '', 1],
    ['daily_max_runs', 'Daily run limit', '0 = no limit', 0], ['daily_max_minutes', 'Daily agent-minutes limit', '0 = no limit', 0],
    ['chain_max_steps', '“Keep going until a gate” step limit', '', 1],
    ['permission_wait_seconds', 'Wait for your allow/deny on a blocked action', 'seconds; 0 = deny it and tell you', 0],
  ];
  const ExecForm = () => {
    const s = NL.useLab();
    const x = NL.exec(s), cfg = x.config || {};
    const init = () => Object.fromEntries([...EXEC.map(([k]) => [k, cfg[k] ?? '']), ['backend', x.backend || 'claude'], ['model', cfg.model || ''], ['permission_mode', x.permission_mode || 'auto'], ['auto_spawn_on_gate1', !!x.auto_spawn_on_gate1]]);
    const [v, setV] = useState(init);
    const orig = init();
    const diff = Object.keys(v).filter(k => String(v[k]) !== String(orig[k]));
    const save = async () => {
      if (!diff.length) return;
      const ok = await NL.confirm({ title: 'Save these settings?', ok: 'Save', body: html`<ul class="diff">${diff.map(k => html`<li><span class="mono">${k}</span>: ${String(orig[k] || '—')} → <b>${String(v[k])}</b></li>`)}</ul>` });
      if (ok) NL.act('/api/executor/config', { confirm: true, changes: Object.fromEntries(diff.map(k => [k, v[k]])) }, 'Saved');
    };
    const set = (k, val) => setV(o => ({ ...o, [k]: val }));
    return html`<div class="form">
      <div class="grid2">
        <${NL.Field} label="Default agent"><${NL.Select} value=${v.backend} onChange=${x2 => set('backend', x2)} options=${['claude', 'codex', 'opencode']} /></${NL.Field}>
        <${NL.Field} label="Default model" hint="blank or “inherit” = the agent's own default"><${NL.Input} value=${v.model} onInput=${x2 => set('model', x2)} mono /></${NL.Field}>
        <${NL.Field} label="What claude may do without asking" hint="auto = its safety classifier decides; plan = read-only"><${NL.Select} value=${v.permission_mode} onChange=${x2 => set('permission_mode', x2)}
          options=${[{ value: 'auto', label: 'auto (recommended)' }, { value: 'acceptEdits', label: 'accept file edits' }, { value: 'default', label: 'ask for everything' }, { value: 'plan', label: 'plan only (read-only)' }, { value: 'dontAsk', label: 'deny anything that would ask' }]} /></${NL.Field}>
        ${EXEC.map(([k, label, hint, min]) => html`<${NL.Field} label=${label} hint=${hint}><${NL.Input} type="number" min=${min} value=${v[k]} onInput=${x2 => set(k, x2)} /></${NL.Field}>`)}
      </div>
      <${NL.Toggle} on=${v.auto_spawn_on_gate1} onChange=${x2 => set('auto_spawn_on_gate1', x2)} label="Create the project as soon as I sign Gate 1" sub="queues /spawn-project right after your signature" />
      <div class="row end">${diff.length ? html`<span class="muted small">${NL.plural(diff.length, 'change')}</span><${NL.Btn} onClick=${() => setV(init())}>Reset</${NL.Btn}>` : null}<${NL.Btn} kind="primary" disabled=${!diff.length} onClick=${save}>Save…</${NL.Btn}></div></div>`;
  };

  NL.LaunchSwitch = () => {
    const s = NL.useLab();
    const on = NL.execOn(s);
    return html`<${NL.Toggle} on=${on} label="Start agents from the dashboard" sub=${on ? 'On — buttons here start agent sessions on this machine, as you.' : 'Off — the dashboard only records commands and signatures; agents act when you next run a session.'}
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
    const keys = ['name', 'projects_root', 'max_concurrent_runs', 'oversight', 'venue', 'page_limit', 'max_concurrent_projects'];
    const diff = keys.filter(k => String(v[k] ?? '') !== String(c[k] ?? ''));
    const set = (k, x) => setV(o => ({ ...o, [k]: x }));
    const save = async () => {
      if (!await NL.confirm({ title: 'Save lab settings?', ok: 'Save', body: html`<ul class="diff">${diff.map(k => html`<li><span class="mono">${k}</span>: ${String(c[k] ?? '—')} → <b>${String(v[k])}</b></li>`)}</ul>` })) return;
      const r = await NL.act('/api/lab/config', { confirm: true, changes: Object.fromEntries(diff.map(k => [k, v[k]])) }, 'Saved');
      if (r.ok) load();
    };
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
      <${NL.Field} label="World" hint="takes effect when the page reloads"><div class="row"><${NL.Seg} value=${p.world} onChange=${v => NL.setPref('world', v)} options=${[{ value: 'diorama', label: 'Paper diorama' }, { value: 'classic', label: 'Classic painted' }]} />
        <button class="link small" onClick=${() => location.reload()}>reload now</button></div></${NL.Field}>
      <${NL.Toggle} on=${p.motion} onChange=${v => { NL.setPref('motion', v); NL.Scene && NL.Scene.setAmbient(v); }} label="Ambient motion" sub="drifting motes, swaying plants (off also when your system asks for reduced motion)" />
      <${NL.Toggle} on=${p.rail} onChange=${v => NL.setPref('rail', v)} label="Show the Today rail on Home" />
      <${NL.Toggle} on=${p.narrate} onChange=${v => NL.setPref('narrate', v)} label="Newt narrates" sub="short speech bubbles quoting what just happened" /></div>`;
  };

  const Notifications = () => {
    const p = NL.usePrefs();
    const perm = window.Notification ? Notification.permission : 'unsupported';
    return html`<div class="form">
      <${NL.Toggle} on=${p.notify && perm === 'granted'} onChange=${async v => { if (v && window.Notification && Notification.permission !== 'granted') { const r = await Notification.requestPermission(); if (r !== 'granted') return NL.toast('The browser blocked notifications', 'warn'); } NL.setPref('notify', v); }}
        label="Desktop notifications" sub="when an agent asks you something, a gate opens, or a run finishes or fails — even with this tab in the background" />
      ${perm === 'denied' ? html`<div class="note note-warn">Notifications are blocked for this page in your browser's site settings.</div>` : null}
      <p class="muted small">The tab title always shows how many things are waiting on you.</p></div>`;
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

  const SECTIONS = [
    { id: 'agents', label: 'Agents & sign-in', C: () => html`<p class="muted">The lab runs these command-line agents on this machine, as you. At least one needs to be installed and signed in.</p><${NL.AgentsSignIn} />` },
    { id: 'autonomy', label: 'Autonomy & limits', C: () => html`<${NL.LaunchSwitch} /><${ExecForm} />` },
    { id: 'lab', label: 'Lab', C: LabForm },
    { id: 'keys', label: 'Research keys', C: Keys },
    { id: 'appearance', label: 'Appearance', C: Appearance },
    { id: 'notifications', label: 'Notifications', C: Notifications },
    { id: 'about', label: 'About & server', C: About },
  ];
  NL.SettingsPage = ({ args }) => {
    const cur = SECTIONS.find(x => x.id === args[0]) || SECTIONS[0];
    return html`<div class="page page-split">
      <aside class="split-left"><div class="split-head"><h1>Settings</h1></div><nav class="side-nav">${SECTIONS.map(x => html`<a class=${cls('side-link', x.id === cur.id && 'on')} href=${'#/settings/' + x.id}>${x.label}</a>`)}</nav></aside>
      <main class="split-right"><h2>${cur.label}</h2><${cur.C} /></main></div>`;
  };
})();
