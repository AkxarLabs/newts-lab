/* Newts' Lab — Labs & machines (#/labs): every lab you can open, on this computer and on the machines
   you reach over SSH. Opening a lab elsewhere starts that lab's own dashboard there and tunnels to it;
   the whole UI then works on it unchanged (agents, files and the terminal all run on that machine). */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useRef, cls } = NL;

  const reach = m => !m.reach ? { tone: 'muted', text: 'not checked' } : m.reach.ok ? { tone: 'ok', text: 'reachable' }
    : m.reach.kind === 'auth' ? { tone: 'warn', text: 'needs sign-in' } : m.reach.kind === 'hostkey' ? { tone: 'warn', text: 'host key not trusted' }
    : { tone: 'bad', text: 'unreachable' };
  const STATE = { idle: ['muted', 'not connected'], starting: ['live', 'starting…'], waiting: ['ask', 'waiting for your sign-in'],
    connected: ['ok', 'connected'], reconnecting: ['warn', 'reconnecting…'], error: ['bad', 'error'], auth: ['warn', 'needs sign-in'] };

  /* ── every lab at once: GET /api/fleet, polled while a page shows it (shared by the top bar) ─────── */
  const fleet = { data: null, t: null, subs: new Set(), at: 0 };
  const pull = async () => { if (NL.DEMO) return; const x = await NL.get('/api/fleet'); if (x && x.ok) { fleet.data = x; fleet.at = Date.now(); fleet.subs.forEach(f => f(x)); } };
  /* demo mode: the synthetic fleet (NL.demoFleet, demo.js) in /api/fleet's shape — never the real labs */
  const slug = x => String(x || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  let demoFl = null;
  const demoFleet = () => {
    if (demoFl) return demoFl;
    const src = NL.demoFleet || { labs: [] };
    const labs = (src.labs || []).map(l => ({ ...l, path: l.path || (l.kind === 'remote' ? '~/labs/' : 'C:/demo/labs/') + slug(l.name),
      machine_id: l.machine_id || (l.kind === 'remote' ? slug(l.machine) : null),
      keep_connected: l.keep_connected != null ? l.keep_connected : l.kind === 'remote' && l.state === 'connected' }));
    const sum = (xs, k) => xs.reduce((a, l) => a + (+((l.summary || {})[k]) || 0), 0);
    demoFl = { ...src, labs, needs_elsewhere: sum(labs.filter(l => !l.current), 'needs'), needs_total: sum(labs, 'needs'), running_total: sum(labs, 'running') };
    return demoFl;
  };
  // what GET /api/labs and /api/machines would say, built from the demo fleet
  const demoLabs = () => { const fl = demoFleet(), here = fl.labs.find(l => l.current) || {};
    return { current: here.path, labs: fl.labs.filter(l => l.kind === 'local').map((l, i) => ({ name: l.name, path: l.path, current: !!l.current, exists: true,
      ideas: l.current ? 13 : 4, opened: new Date(Date.now() - (i + 1) * 26 * 3600e3).toISOString() })) }; };
  const demoMachines = () => { const by = {};
    demoFleet().labs.filter(l => l.kind === 'remote').forEach(l => {
      const m = by[l.machine_id] = by[l.machine_id] || { id: l.machine_id, name: l.machine, host: `you@${l.machine}.example.org`, reach: { ok: true }, labs: [],
        facts: { os: 'Linux', arch: 'x86_64', cpus: l.machine === 'gpu-cluster' ? 64 : 16, gpus: l.machine === 'gpu-cluster' ? ['GPU 0: NVIDIA A100 80GB', 'GPU 1: NVIDIA A100 80GB', 'GPU 2: NVIDIA A100 80GB', 'GPU 3: NVIDIA A100 80GB'] : [],
          scheduler: l.machine === 'gpu-cluster' ? 'slurm' : null, partitions: l.machine === 'gpu-cluster' ? [{ name: 'gpu' }, { name: 'cpu' }] : [], tools: { uv: true, git: true, claude: true, codex: l.machine !== 'lab-pc', opencode: false } } };
      m.labs.push({ path: l.path, lab_name: l.name, state: l.state, exists: true, keep_connected: !!l.keep_connected });
    });
    return { machines: Object.values(by), suggestions: [] }; };

  NL.useFleet = () => {
    const [d, setD] = useState(NL.DEMO ? null : fleet.data);
    useEffect(() => {
      if (NL.DEMO) return undefined;
      fleet.subs.add(setD);
      if (!fleet.t) { pull(); fleet.t = setInterval(() => { if (!document.hidden) pull(); }, 15000); }
      else if (Date.now() - fleet.at > 15000) pull();
      return () => { fleet.subs.delete(setD); if (!fleet.subs.size && fleet.t) { clearInterval(fleet.t); fleet.t = null; } };
    }, []);
    return NL.DEMO ? demoFleet() : d;
  };
  NL.refreshFleet = () => NL.DEMO ? null : pull();

  /* go to a lab (and optionally straight to one thing in it) */
  NL.goToLab = async (l, then) => {
    if (l.current) { if (then) location.hash = then; else NL.go(''); return; }
    const r = l.kind === 'local' ? await NL.act('/api/labs/open', { path: l.path }, 'Opened')
      : await NL.api('/api/machines/open', { id: l.machine_id, path: l.path });
    if (l.kind === 'remote' && !(r.ok && r.state === 'connected')) { NL.toast(r.error || r.note || 'could not connect — open it from its machine below', r.ok ? 'info' : 'bad'); return; }
    if (r.ok) { location.hash = then || '#/'; setTimeout(() => location.reload(), 250); }
  };
  const itemHash = it => it.kind === 'gate' && it.idea ? `#/study/${it.idea}?gate=${(it.detail || {}).gate}` : it.run_id ? `#/runs?run=${it.run_id}`
    : (it.detail || {}).campaign ? `#/studies?campaign=${encodeURIComponent(it.detail.campaign)}` : it.idea ? `#/study/${it.idea}` : '#/';

  /* what a lab needs and runs, from the fleet summary — shown on that lab's own row */
  const fleetLab = (fl, kind, path, machine) => ((fl && fl.labs) || []).find(l => l.kind === kind && l.path === path && (kind === 'local' || l.machine_id === machine));
  function LabStatus({ l }) {
    if (!l || !l.summary) return null;
    const sm = l.summary;
    return html`<div class="small row gap wrap">${sm.needs ? html`<span class="warn"><b>${sm.needs}</b> need you</span>` : null}
        ${sm.running || sm.queued || sm.waiting ? html`<span>${sm.running || 0} running${sm.queued ? ` · ${sm.queued} queued` : ''}${sm.waiting ? ` · ${sm.waiting} waiting` : ''}</span>` : null}
        ${(sm.campaigns || []).map(c => html`<span class="chip">⟳ ${NL.clip(c.name.replace(/^\d{4}-\d{2}-\d{2}-/, ''), 22)} · ${c.status}</span>`)}
        ${l.kind === 'remote' && l.summary_age > 60 ? html`<span class="muted">as of ${Math.round(l.summary_age / 60)} min ago</span>` : null}</div>
      ${(sm.top || []).length ? html`<div class="fleet-items">${sm.top.slice(0, 3).map(it => html`<button type="button" class="link small" onClick=${() => NL.goToLab(l, itemHash(it))}>› ${NL.clip(it.title || it.kind, 80)}</button>`)}</div>` : null}`;
  }

  function Facts({ f }) {
    if (!f) return null;
    const t = f.tools || {};
    const tool = k => html`<span class=${cls('fact-tool', t[k] ? 'on' : 'off')}>${t[k] ? '✓' : '–'} ${k}</span>`;
    const gpus = (f.gpus || []).length;
    return html`<div class="facts-line">
      <span>${f.os || '?'} ${f.arch || ''}</span>${f.cpus ? html`<span>${f.cpus} CPUs</span>` : null}
      <span>${gpus ? `${gpus} GPU${gpus > 1 ? 's' : ''}${f.gpus[0] ? ' · ' + NL.clip(f.gpus[0].replace(/^GPU \d+: /, '').replace(/\s*\(UUID.*$/, ''), 34) : ''}` : 'no GPU found'}</span>
      <span>${f.scheduler ? `${f.scheduler.toUpperCase()}${(f.partitions || []).length ? ' · ' + f.partitions.slice(0, 4).map(p => p.name).join(', ') : ''}` : 'no scheduler'}</span>
      <span class="row-wrap">${['uv', 'git', 'claude', 'codex', 'opencode'].map(tool)}</span></div>`;
  }

  function RemoteLab({ m, lab, reload, fl }) {
    const [busy, setBusy] = useState(false);
    const st = STATE[lab.state] || STATE.idle;
    const open = async (interactive) => {
      setBusy(true);
      const r = await NL.api('/api/machines/open', { id: m.id, path: lab.path, interactive });
      setBusy(false);
      if (r.ok && r.state === 'connected') { NL.toast(`Opened ${r.name || lab.path} on ${m.name}`, 'ok'); NL.go(''); setTimeout(() => location.reload(), 250); return; }
      if (r.ok && r.state === 'waiting') { NL.toast(r.note, 'info'); reload(); return; }
      if (r.needs_interactive) {
        if (await NL.confirm({ title: `${m.name} needs you to sign in`, ok: 'Open a terminal to sign in',
          body: html`<p>It asks for a password or a verification code, so the connection runs in a terminal window on this computer. Sign in there and leave the window open — this page connects by itself.</p>` }))
          return open(true);
        return;
      }
      NL.toast(r.error || 'could not connect', 'bad'); reload();
    };
    // an interactive connect: poll until it's up, then switch to it
    useEffect(() => {
      if (lab.state !== 'waiting') return undefined;
      const t = setInterval(async () => {
        const x = await NL.get('/api/machines');
        const l2 = ((x.machines || []).find(y => y.id === m.id) || { labs: [] }).labs.find(y => y.path === lab.path);
        if (l2 && l2.state === 'connected') {
          clearInterval(t);
          const u = await NL.api('/api/machines/use', { id: m.id, path: lab.path });
          if (u.ok) { NL.go(''); location.reload(); }
        } else if (l2 && l2.state !== 'waiting') { clearInterval(t); reload(); }
      }, 2500);
      return () => clearInterval(t);
    }, [lab.state]);
    return html`<div class="labrow">
      <div class="grow"><b>${lab.lab_name || lab.name || lab.path.split('/').filter(Boolean).pop()}</b> <${NL.Pill} tone=${st[0]}>${st[1]}</${NL.Pill}>
        ${lab.exists === false ? html` <${NL.Pill} tone="warn">no lab there yet</${NL.Pill}>` : null}
        <div class="mono small muted">${lab.path}</div>${lab.error ? html`<div class="small warn">${lab.error}</div>` : null}
        <${LabStatus} l=${fleetLab(fl, 'remote', lab.path, m.id)} />
        <div class="small muted keep-why">${lab.keep_connected ? 'Kept connected in the background: what it needs shows here, on Home and in the top bar, refreshed every 15 s.'
          : 'Not kept connected: you see what it needs only while you have it open. Tick “keep connected” to watch it from here.'}</div></div>
      <div class="row">${lab.state === 'waiting' ? html`<${NL.Spinner} /><span class="small muted">sign in in the terminal window…</span>` : html`<${NL.Btn} small kind="primary" busy=${busy} onClick=${() => open(false)}>Switch to this lab</${NL.Btn}>`}
        ${['connected', 'reconnecting', 'waiting', 'error'].includes(lab.state) ? html`<button class="link small" onClick=${async () => { const r = await NL.api('/api/machines/disconnect', { id: m.id, path: lab.path }); if (r.was_current) { NL.go('labs'); location.reload(); } else reload(); }}>Disconnect</button>` : null}
        <label class="small keep keep-vis" title="stay connected in the background so Home and the top bar show what it needs"><input type="checkbox" checked=${!!lab.keep_connected}
          onChange=${async e => { await NL.act('/api/fleet/keep', { id: m.id, path: lab.path, keep: e.target.checked }); reload(); NL.refreshFleet(); }} /> keep connected</label></div></div>`;
  }

  function MachineCard({ m, reload, fl }) {
    const [path, setPath] = useState('');
    const [newName, setNewName] = useState('');
    const [newPath, setNewPath] = useState('~/labs/');
    const [mode, setMode] = useState(null);
    const r = reach(m);
    const probe = async () => { const x = await NL.api('/api/machines/probe', { id: m.id }); NL.toast(x.ok ? 'Checked' : (x.error || 'unreachable'), x.ok ? 'ok' : 'warn'); reload(); };
    const addLab = async () => { const x = await NL.act('/api/machines/add-lab', { id: m.id, path: path.trim() }); if (x.ok) { setPath(''); setMode(null); reload(); } };
    const create = async () => {
      if (!newName.trim() || !newPath.trim()) return NL.toast('A name and a folder', 'warn');
      if (!await NL.confirm({ title: `Create “${newName.trim()}” on ${m.name}?`, ok: 'Create it', body: html`<p>Copies this template's committed files to <span class="mono">${newPath.trim()}</span> on ${m.name} over SSH, then sets it up as an empty lab (it needs <span class="mono">python3</span> and <span class="mono">git</span> there).</p>` })) return;
      const x = await NL.act('/api/machines/create-lab', { id: m.id, path: newPath.trim(), name: newName.trim(), confirm: true });
      if (x.ok) { setMode(null); reload(); }
    };
    return html`<section class="machine">
      <header class="machine-head"><div class="grow"><h3>${m.name}</h3><span class="mono small muted">${m.host}</span> <${NL.Pill} tone=${r.tone}>${r.text}</${NL.Pill}>
        ${m.reach && !m.reach.ok ? html`<div class="small muted">${m.reach.error}</div>` : null}</div>
        <div class="row"><button class="link small" onClick=${probe}>Check again</button>
          ${m.facts && !(m.facts.tools || {}).uv ? html`<${NL.Btn} small onClick=${() => NL.act('/api/machines/install-uv', { id: m.id }, 'Installing uv in a terminal window')}>Install uv…</${NL.Btn}>` : null}
          <button class="link small danger" onClick=${async () => { if (await NL.confirm({ title: `Forget ${m.name}?`, body: 'Removes it from this list. Nothing on that machine changes.', ok: 'Forget', danger: true })) { await NL.api('/api/machines/remove', { id: m.id }); reload(); } }}>Forget</button></div></header>
      <${Facts} f=${m.facts} />
      ${(m.labs || []).length ? (m.labs || []).map(l => html`<${RemoteLab} key=${l.path} m=${m} lab=${l} reload=${reload} fl=${fl} />`) : html`<div class="muted small pad">No labs on this machine yet.</div>`}
      <div class="row">${mode === 'add' ? html`<${NL.Input} value=${path} onInput=${setPath} placeholder="the lab's folder on that machine, e.g. ~/my-lab" mono onEnter=${addLab} /><${NL.Btn} small onClick=${addLab}>Add</${NL.Btn}><button class="link small" onClick=${() => setMode(null)}>cancel</button>`
        : mode === 'create' ? html`<${NL.Input} value=${newName} onInput=${setNewName} placeholder="lab name" /><${NL.Input} value=${newPath} onInput=${setNewPath} mono /><${NL.Btn} small kind="primary" onClick=${create}>Create</${NL.Btn}><button class="link small" onClick=${() => setMode(null)}>cancel</button>`
        : html`<${NL.Btn} small onClick=${() => setMode('add')}>Add a lab folder</${NL.Btn}><${NL.Btn} small onClick=${() => setMode('create')}>Create a lab here</${NL.Btn}>`}</div>
    </section>`;
  }

  function AddMachine({ suggestions, reload }) {
    const [host, setHost] = useState('');
    const [name, setName] = useState('');
    const [busy, setBusy] = useState(false);
    const add = async () => {
      if (!host.trim()) return;
      setBusy(true);
      const x = await NL.api('/api/machines/add', { host: host.trim(), name: name.trim() || host.trim() });
      setBusy(false);
      if (!x.ok) return NL.toast(x.error, 'bad');
      const p = x.probe || {};
      NL.toast(p.ok ? `Added ${x.machine.name} — reachable` : p.needs_interactive ? `Added ${x.machine.name} — it needs an interactive sign-in` : `Added ${x.machine.name} — ${p.error || 'not reachable right now'}`, p.ok ? 'ok' : 'warn');
      setHost(''); setName(''); reload();
    };
    return html`<${NL.Section} title="Add a machine"><div class="form">
      <p class="muted small">Any machine you can <span class="mono">ssh</span> into: an alias from your <span class="mono">~/.ssh/config</span> (jump hosts and keys work as usual) or <span class="mono">user@hostname</span>. The lab and its agents run there; this page is your window onto it.</p>
      <div class="grid2"><${NL.Field} label="SSH host"><input class="input mono" list="nl-ssh-hosts" value=${host} onInput=${e => setHost(e.target.value)} placeholder="e.g. lambda or me@gpu-box.example.org" />
          <datalist id="nl-ssh-hosts">${(suggestions || []).map(h => html`<option value=${h} />`)}</datalist></${NL.Field}>
        <${NL.Field} label="Name (optional)"><${NL.Input} value=${name} onInput=${setName} placeholder=${host || 'GPU box'} onEnter=${add} /></${NL.Field}></div>
      ${(suggestions || []).length ? html`<div class="row-wrap small">${suggestions.slice(0, 12).map(h => html`<button type="button" class="chip click" onClick=${() => setHost(h)}>${h}</button>`)}</div>` : null}
      <div class="row end"><${NL.Btn} kind="primary" busy=${busy} disabled=${!host.trim()} onClick=${add}>Add and check</${NL.Btn}></div></div></${NL.Section}>`;
  }

  /* this computer's labs (open / create / switch) */
  function LocalLabs({ d, reload, fl }) {
    const [path, setPath] = useState('');
    const [nm, setNm] = useState('');
    const [where, setWhere] = useState('');
    useEffect(() => { if (d && d.current && !where) setWhere(d.current.replace(/[\\/][^\\/]+$/, '')); }, [d]);
    const s = NL.getState() || {};
    const slug = (nm || 'my-lab').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'my-lab';
    const sep = (where || '').includes('\\') ? '\\' : '/';
    const dest = where ? where.replace(/[\\/]$/, '') + sep + slug : '';
    const open = async p => { const r = await NL.act('/api/labs/open', { path: p }, 'Opened'); if (r.ok) { NL.go(''); setTimeout(() => location.reload(), 300); } };
    const create = async () => {
      if (!nm.trim() || !dest) return NL.toast('Give the lab a name and a place', 'warn');
      if (!await NL.confirm({ title: `Create “${nm.trim()}”?`, ok: 'Create the lab', body: html`<p>A new, empty lab at <span class="mono">${dest}</span> — this template's procedures and tools, an empty registry and knowledge base, its own git repository. Its projects will live next to it in <span class="mono">${slug}-projects</span>.</p>` })) return;
      const r = await NL.act('/api/labs/create', { confirm: true, name: nm.trim(), path: dest, open: true }, 'Lab created');
      if (r.ok) { NL.go('setup'); setTimeout(() => location.reload(), 300); }
    };
    return html`<section class="machine machine-local">
      <header class="machine-head"><div class="grow"><h3>This computer</h3></div></header>
      ${!d ? html`<${NL.Spinner} />` : (d.labs || []).map(l => html`<div class=${cls('labrow', l.current && !s.remote && 'on', !l.exists && 'gone')}>
        <div class="grow"><b>${l.name}</b>${l.current && !s.remote ? html` <${NL.Pill} tone="ok">open</${NL.Pill}>` : null}<div class="mono small muted">${l.path}</div>
          ${l.exists ? html`<div class="small muted">${l.ideas ? NL.plural(l.ideas, 'study', 'studies') : 'no studies yet'}${l.opened ? ' · opened ' + NL.when(l.opened) : ''}</div>` : html`<div class="small warn">folder not found</div>`}
          <${LabStatus} l=${fleetLab(fl, 'local', l.path)} /></div>
        <div class="row">${l.current && !s.remote ? html`<span class="muted small">You are in this lab</span>` : l.exists ? html`<${NL.Btn} small kind="primary" onClick=${() => open(l.path)}>Switch to this lab</${NL.Btn}>` : null}
          ${!l.current ? html`<button class="link small" onClick=${async () => { await NL.api('/api/labs/forget', { path: l.path }); reload(); }}>Forget</button>` : null}</div></div>`)}
      <details class="more"><summary>Create or open another lab on this computer</summary><div class="form">
        <div class="grid2"><${NL.Field} label="New lab name"><${NL.Input} value=${nm} onInput=${setNm} placeholder="e.g. Sparse models lab" /></${NL.Field}>
          <${NL.Field} label="Inside this folder"><${NL.Input} value=${where} onInput=${setWhere} mono /></${NL.Field}></div>
        ${dest ? html`<div class="muted small">It will be created at <span class="mono">${dest}</span></div>` : null}
        <div class="row end"><${NL.Btn} kind="primary" onClick=${create}>Create the lab</${NL.Btn}></div>
        <div class="row"><${NL.Input} value=${path} onInput=${setPath} placeholder="or open an existing lab folder (it contains lab/config.yaml)" mono onEnter=${() => open(path)} />
          <${NL.Btn} onClick=${() => open(path)} disabled=${!path.trim()}>Open</${NL.Btn}></div></div></details></section>`;
  }

  NL.LabsPage = () => {
    const [local, setLocal] = useState(null);
    const [mach, setMach] = useState(null);
    const s = NL.useLab();
    const load = () => { if (NL.DEMO) { setLocal(demoLabs()); setMach(demoMachines()); return; } NL.get('/api/labs').then(setLocal); NL.get('/api/machines').then(setMach); };
    useEffect(() => { load(); if (NL.DEMO) return undefined; const t = setInterval(() => NL.get('/api/machines').then(setMach), 8000); return () => clearInterval(t); }, []);
    const cur = s.remote;
    const fl = NL.useFleet();
    return html`<div class="page page-narrow">
      <header class="page-head"><div><h1>Labs & machines</h1><p class="lede">A lab is one folder: its ideas, studies, papers and knowledge. It can live on this computer or on any machine you reach over SSH — the lab and its agents run where it lives; this page is your window onto each.</p></div></header>
      ${cur ? html`<div class="note">Showing <b>${cur.lab_name || cur.lab}</b> on <b>${cur.name}</b> (${cur.host}). <button class="link" onClick=${async () => { await NL.api('/api/machines/local', {}); NL.go(''); location.reload(); }}>Back to this computer</button></div>` : null}
      ${fl && (fl.labs || []).length > 1 ? (() => {
        const sum = (xs, k) => xs.reduce((a, l) => a + (+((l.summary || {})[k]) || 0), 0);
        const here = fl.labs.filter(l => l.current && Object.keys(l.summary || {}).length), others = fl.labs.filter(l => !l.current);
        const line = xs => { const n = sum(xs, 'needs'), r = sum(xs, 'running');
          return html`${n ? html`<b class="warn">${n} ${n === 1 ? 'thing needs' : 'things need'} you</b>` : 'nothing needs you'} · ${NL.plural(r, 'run')} working`; };
        return html`<div class="muted labs-summary">${here.length ? html`<p>This lab: ${line(here)}</p>` : null}
          <p>Other labs: ${line(others)}. Remote labs with “keep connected” ticked refresh every 15 s.</p></div>`;
      })() : null}
      ${NL.DEMO ? html`<div class="note small">Demo — these labs and machines are made up; nothing connects.</div>` : null}
      <${LocalLabs} d=${local} reload=${load} fl=${fl} />
      ${mach ? (mach.machines || []).map(m => html`<${MachineCard} key=${m.id} m=${m} reload=${load} fl=${fl} />`) : html`<${NL.Spinner} />`}
      <${AddMachine} suggestions=${mach && mach.suggestions} reload=${load} />
    </div>`;
  };
})();
