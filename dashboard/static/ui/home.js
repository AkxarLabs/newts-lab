/* Newts' Lab — Home: the living world with the Today rail (what needs you, what's running, what's next),
   Ask Newt underneath, the Key, and the room map. Also the one inbox (the bell and the rail show the
   same list) and the History page. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, cls } = NL;

  /* ── the inbox: one list, typed actions ─────────────────────────────────── */
  const ICON = { question: '?', assumed: '≈', needs_pi: '✋', gate: '✉', permission: '🔐', denied: '⊘', crashed: '✕', report: '✓', escalation: '⚠', stalled: '◴', subagent: '◌', brake: '⏸', proposal: '✎', campaign: '⟳', artifact: '❏' };
  const PRIMARY = new Set(['answer', 'sign', 'allow', 'next', 'proposal']);
  NL.attAct = async (it, a) => {
    const run = it.run_id, d = it.detail || {};
    switch (a.id) {
      case 'answer': case 'tail': return NL.openRun(run);
      case 'proposal': return NL.open(NL.ProposalSheet, { id: d.proposal });
      case 'campaign': return NL.openCampaign(d.campaign);
      case 'artifact': return NL.openArtifact(d.artifact);
      case 'reply': return run ? NL.openRun(run) : NL.go(it.idea && it.idea !== 'hub' ? `study/${it.idea}` : '');
      case 'stop': if (await NL.confirm({ title: 'Stop this run?', body: 'It stays resumable.', ok: 'Stop', danger: true })) return NL.act('/api/run/stop', { run_id: run, confirm: true }, 'Stopping'); return;
      case 'resume': return NL.act('/api/run/resume', { run_id: run }, 'Resuming');
      case 'next': return NL.launchCommand(a.command || d.next, (NL.run(NL.getState(), run) || {}).subject);
      case 'allow': case 'deny': return NL.act('/api/run/permission', { run_id: run, n: d.n, allow: a.id === 'allow' }, a.id === 'allow' ? 'Allowed once' : 'Denied');
      case 'sign': case 'bundle': return NL.openGate(it.idea, d.gate);
      case 'resolve': return NL.act('/api/escalation/resolve', { ref: d.id, source: d.source }, 'Marked handled');
      case 'inspect': return NL.openWorker(d.worker_id);
      case 'dismiss': return NL.act('/api/attention/ack', { id: it.id, action: 'dismiss' }, 'Dismissed');
      default: return null;
    }
  };
  const InboxRow = ({ it, compact }) => {
    const acts = (it.actions || []).filter(a => !(it.kind === 'gate' && a.id === 'bundle')).slice(0, compact ? 2 : 4);
    const open = () => it.kind === 'artifact' ? NL.openArtifact((it.detail || {}).artifact) : (it.detail || {}).campaign ? NL.openCampaign(it.detail.campaign) : it.kind === 'proposal' ? NL.open(NL.ProposalSheet, { id: (it.detail || {}).proposal }) : it.run_id ? NL.openRun(it.run_id) : it.kind === 'gate' ? NL.openGate(it.idea, (it.detail || {}).gate) : it.idea ? NL.go('study/' + it.idea) : null;
    return html`<div class=${cls('inrow', 'sev-' + it.sev, 'k-' + it.kind)}>
      <button type="button" class="inrow-main" onClick=${open}><span class="inrow-ico" aria-hidden="true">${ICON[it.kind] || '•'}</span>
        <span class="inrow-t"><b>${it.title}</b>${it.body ? html`<small>${NL.clip(it.body, compact ? 110 : 260)}</small>` : null}</span></button>
      ${acts.length ? html`<span class="inrow-acts">${acts.map(a => html`<${NL.Btn} small kind=${PRIMARY.has(a.id) ? 'primary' : ''} onClick=${() => NL.attAct(it, a)}>${a.label}</${NL.Btn}>`)}</span>` : null}</div>`;
  };
  const sortInbox = xs => xs.slice().sort((a, b) => ({ block: 0, warn: 1, info: 2 }[a.sev] - { block: 0, warn: 1, info: 2 }[b.sev]) || String(b.ts || '').localeCompare(String(a.ts || '')));
  NL.inboxItems = s => {
    const att = sortInbox(((s && s.attention) || []));
    const pend = [...((s && s.directives) || []), ...((s && s.items) || []).flatMap(i => (i.directives || []).map(d => ({ ...d, target: d.target || i.id })))].filter(d => d.state === 'pending');
    return { needs: att.filter(a => a.sev !== 'info'), info: att.filter(a => a.sev === 'info'), notes: pend };
  };

  NL.InboxSheet = ({ onClose }) => {
    const s = NL.useLab();
    const { needs, info, notes } = NL.inboxItems(s);
    return html`<${NL.Sheet} title="Needs you" sub=${needs.length ? NL.plural(needs.length, 'thing') + ' waiting on you' : 'Nothing is waiting on you'} onClose=${onClose}>
      ${needs.length ? needs.map(it => html`<${InboxRow} key=${it.id} it=${it} />`) : html`<${NL.Empty} icon="✓">All clear. Agents ask here when they need a decision.</${NL.Empty}>`}
      ${info.length ? html`<${NL.Section} title="Finished" count=${info.length}>${info.slice(0, 20).map(it => html`<${InboxRow} key=${it.id} it=${it} compact />`)}</${NL.Section}>` : null}
      ${notes.length ? html`<${NL.Section} title="Your notes, not read yet" count=${notes.length}>${notes.map(d => html`<div class="inrow sev-info"><div class="inrow-main"><span class="inrow-ico">✉</span><span class="inrow-t"><b>${NL.clip(d.text, 120)}</b><small>to ${d.target === 'hub' ? 'the lab' : d.target} · ${NL.hhmm(d.ts)}</small></span></div>
        <span class="inrow-acts"><${NL.Btn} small onClick=${() => NL.act('/api/withdraw', { target: d.target || 'hub', id: d.id, ts: d.ts }, 'Withdrawn')}>withdraw</${NL.Btn}></span></div>`)}</${NL.Section}>` : null}
      <div class="row end"><a class="link small" href="#/history" onClick=${onClose}>Full history →</a></div>
    </${NL.Sheet}>`;
  };

  /* ── the Today rail ─────────────────────────────────────────────────────── */
  const SinceVisit = () => {
    const s = NL.useLab();
    const [base] = useState(() => NL.ls.get('nl-seen-through', ''));
    const [hidden, setHidden] = useState(false);
    const ev = (s.events || []).filter(e => base && (e.ts || '') > base);
    // what you've seen moves on when you dismiss the line or open History — not just by glancing at Home
    useEffect(() => { if (!NL.ls.get('nl-seen-through', '')) { const last = (s.events || []).slice(-1)[0]; if (last) NL.ls.set('nl-seen-through', last.ts); } }, []);
    if (!base || hidden || !ev.length) return null;
    const count = k => ev.filter(e => k.includes(e.kind)).length;
    const failed = ev.filter(e => e.kind === 'run_finished' && ['failed', 'timeout', 'killed'].includes(e.status)).length;
    const bits = [[count(['run_finished', 'agent_finished']) - failed, 'runs finished'], [failed, 'failed'], [count(['gate_waiting']), 'gates opened'],
      [ev.filter(e => /self-approved|campaign/.test(e.detail || '') && /gate/i.test(e.detail || '')).length, 'approved by a campaign'],
      [count(['escalation']), 'escalations'], [count(['kill']), 'kills'], [count(['state_change']), 'stage changes'], [count(['artifact']), 'things for you']].filter(([n]) => n > 0);
    if (!bits.length) return null;
    return html`<div class="since"><a class="grow" href=${'#/history?since=' + encodeURIComponent(base)}>Since you were last here: ${bits.map(([n, l]) => `${n} ${l}`).join(' · ')} — see what happened →</a><button class="x" onClick=${() => { setHidden(true); const last = (s.events || []).slice(-1)[0]; if (last) NL.ls.set('nl-seen-through', last.ts); }} aria-label="dismiss">✕</button></div>`;
  };

  /* what agents made for you to look at, not opened yet (a question with one is already in Needs you) */
  const ForYou = () => {
    const s = NL.useLab();
    const fresh = NL.artifactsUnseen(s).filter(a => !a.question);
    if (!fresh.length) return null;
    return html`<${NL.Section} title="For you to look at" count=${fresh.length} className="rail-sec">${fresh.slice(0, 3).map(a => html`<button type="button" class="art-mini" onClick=${() => NL.openArtifact(a.id)}>
      <span class="art-ico">❏</span><span class="grow clip"><b>${a.title}</b><small class="muted">${(NL.item(s, a.study) || {}).title || a.study || 'the lab'} · ${NL.ago(a.created)}</small></span></button>`)}
      ${fresh.length > 3 ? html`<a class="link small" href="#/artifacts?f=new">all ${fresh.length} →</a>` : null}</${NL.Section}>`;
  };

  const UpNext = () => {
    const s = NL.useLab();
    const busy = new Set(NL.runs(s, r => NL.RUN_ACTIVE.has(r.status) || r.status === 'queued' || r.status === 'waiting_input').map(r => r.subject).filter(Boolean));
    const list = (s.items || []).filter(i => !busy.has(i.id) && !NL.isTerminal(i.state) && !(i.gate && !i.gate_signed))
      .map(i => ({ it: i, nx: NL.nextFor(s, i) })).filter(x => x.nx).slice(0, 5);
    if (!list.length) return null;
    return html`<${NL.Section} title="Up next" className="rail-sec">${list.map(({ it, nx }) => html`<div class="upnext">
      <a class="clip" href=${'#/study/' + it.id}><b>${NL.clip(it.title || it.id, 34)}</b><small class="muted">${NL.STATE_LABEL[it.state]}</small></a>
      <${NL.Btn} small onClick=${nx.run}>${nx.label}</${NL.Btn}></div>`)}</${NL.Section}>`;
  };

  const OnRamps = () => html`<div class="onramps">
    <p class="lede">The lab is quiet. Where do you want to start?</p>
    ${NL.intents().filter(i => i.onramp).map(i => [i.id, i.icon, i.onrampTitle || i.title, i.campaign ? 'Ideas carried to papers on their own, within bounds you sign' : i.does]).map(([id, ico, t, sub]) =>
      html`<button type="button" class="onramp" onClick=${() => NL.openStart({ intent: id })}><span class="intent-ico">${ico}</span><span><b>${t}</b><small>${sub}</small></span></button>`)}
    <button type="button" class="onramp" onClick=${() => NL.composeTour()}><span class="intent-ico"><${NL.Icon} name="layers" /></span><span><b>Make the lab yours</b><small>A one-minute tour of Compose — how this lab works, and how to change it</small></span></button></div>`;

  const Rail = () => {
    const s = NL.useLab();
    const prefs = NL.usePrefs();
    const { needs } = NL.inboxItems(s);
    const running = NL.runs(s, r => NL.RUN_ACTIVE.has(r.status) || r.status === 'queued').sort((a, b) => (b.created || '').localeCompare(a.created || ''));
    const finished = NL.runs(s, r => NL.RUN_DONE.has(r.status) && r.finished).sort((a, b) => (b.finished || '').localeCompare(a.finished || '')).slice(0, 3);
    const cold = !(s.items || []).length && !(s.runs || []).length;
    if (!prefs.rail) return html`<button class="rail-open" onClick=${() => NL.setPref('rail', true)} title="show Today">${needs.length ? html`<b class="badge">${needs.length}</b>` : null} Today ◂</button>`;
    return html`<aside class="rail" aria-label="Today" data-world-inset="right">
      <header class="rail-head"><h2>Today</h2><button class="x" title="hide" onClick=${() => NL.setPref('rail', false)}>▸</button></header>
      <${NL.Btn} kind="primary" icon="＋" onClick=${() => NL.openStart()}>Start something</${NL.Btn}>
      <${SinceVisit} />
      ${NL.liveCampaigns(s).length ? html`<${NL.Section} title="Campaigns" className="rail-sec">${NL.liveCampaigns(s).map(c => html`<${NL.CampaignCard} key=${c.name} c=${c} compact />`)}</${NL.Section}>` : null}
      ${cold ? html`<${OnRamps} />` : html`
        <${NL.Section} title="Needs you" count=${needs.length || null} className="rail-sec">${needs.length ? needs.slice(0, 6).map(it => html`<${InboxRow} key=${it.id} it=${it} compact />`)
          : html`<div class="muted small">Nothing is waiting on you.</div>`}${needs.length > 6 ? html`<button class="link small" onClick=${() => NL.open(NL.InboxSheet, {}, { key: 'inbox' })}>all ${needs.length} →</button>` : null}</${NL.Section}>
        <${NL.Section} title="Running" count=${running.length || null} className="rail-sec">${running.length ? running.slice(0, 5).map(r => html`<${NL.RunRow} key=${r.run_id} r=${r} compact />`)
          : html`<div class="muted small">No agents running.</div>`}</${NL.Section}>
        <${ForYou} />
        <${UpNext} />
        ${finished.length ? html`<${NL.Section} title="Just finished" className="rail-sec">${finished.map(r => html`<${NL.RunRow} key=${r.run_id} r=${r} compact />`)}</${NL.Section}>` : null}`}
    </aside>`;
  };

  /* ── the Key (roles + project colours) and the room map ─────────────────── */
  const Key = () => {
    const s = NL.useLab();
    const [open, setOpen] = useState(false);
    const [hl, setHl] = useState(null);
    const workers = (s.workers || []).filter(w => w.status !== 'done');
    const count = r => workers.filter(w => w.role === r).length;
    const pick = r => { const v = hl === r ? null : r; setHl(v); NL.Scene && NL.Scene.highlight(v); };
    if (!(s.items || []).length && !workers.length) return null;
    const prefs = NL.usePrefs(), c = prefs.cast || {}, chars = (window.Lab3D && Lab3D.CHARACTERS) || [];
    const wf = (s.workflow && s.workflow.rooms) ? s.workflow : (NL.WF || window.__WORKFLOW_DEFAULT__ || {});
    const isPer = r => (window.Lab3D && Lab3D.model ? Lab3D.model.perProject(wf, r) : !!r.per_project);
    const perProject = (wf.rooms || []).filter(isPer), stepped = (wf.stages || []).filter(st => (st.substages || []).length);
    const charName = id => ((chars.find(x => x.id === id) || {}).label || id || 'Newt').toLowerCase();
    const lens = NL.Scene && NL.Scene.lens ? NL.Scene.lens() : 'work';
    const LENS = { work: 'what each agent is doing — hover one to read it', cost: "today's spend: a brighter floor means more spent; the tags are each run's cost so far",
      waiting: 'only what waits on you: agents asking you something, and gates to sign', risk: 'runs that failed, were blocked, or have gone quiet' };
    return html`<div class=${cls('key', open && 'open')}>
      <button class="key-btn" onClick=${() => setOpen(!open)} aria-expanded=${open}>Key ${open ? '▾' : '▴'}</button>
      ${open ? html`<div class="key-body">
        <div class="key-h">Reading the table</div>
        <div class="key-note"><b>Rooms</b> are the stages a study moves through (their short name is on the label)${perProject.length ? html`; each live project gets its own <b>${perProject.map(r => r.label || r.title || r.id).join(' / ')}</b>` : ''}.</div>
        <div class="key-note"><b>A figure</b> is one agent at work; <b>a small one</b> is a subagent it started, in the same colours.</div>
        <div class="key-note"><b>?</b> = it's asking you something · <b>zzz</b> = gone quiet · <b>cards</b> on shelves are studies · <b>sheets</b> on a board = something for you · <b>scaffolding</b> = a project repo being set up</div>
        ${stepped.map(st => html`<div class="key-note"><b>${st.title}:</b> ${st.substages.join(' → ')}${st.gate ? ` — the last step needs what you approved at Gate ${st.gate}` : ''}.</div>`)}
        <div class="key-note"><b>This lens:</b> ${LENS[lens] || LENS.work}</div>
        <div class="key-h">Tools</div>
        <div class="key-note">${c.mode === 'one' ? `every agent is a ${charName(c.one)}` : `Claude = ${charName(c.claude || 'newt')} · Codex = ${charName(c.codex || 'human')} · opencode = ${charName(c.opencode || 'robot')}`} — <a class="link" href="#/settings/appearance">change</a></div>
        <div class="key-h">Agents</div>${Object.entries(NL.ROLE).map(([r, v]) => html`<button type="button" class=${cls('key-row', hl === r && 'on')} onClick=${() => pick(r)}>
          <i class="role-dot" style=${{ background: v.color }}></i><span class="grow">${v.label}${r === 'orchestrator' ? ' (Newt)' : ''}</span><span class="muted">${count(r) || ''}</span></button>`)}
        <div class="key-h">Studies</div>${(s.items || []).filter(i => !NL.isTerminal(i.state)).slice(0, 12).map(i => html`<button type="button" class="key-row" onClick=${() => NL.Scene && NL.Scene.focusProject(i.id)}>
          <i class="role-dot" style=${{ background: `hsl(${window.VivScene ? window.VivScene.projectHue(i.id) : 180} 45% 55%)` }}></i><span class="grow clip">${i.title || i.id}</span></button>`)}</div>` : null}</div>`;
  };

  const Crumb = () => {
    const [info, setInfo] = useState(NL.viewInfo || { level: 'WORLD' });
    useEffect(() => { const f = v => setInfo(v); NL.viewListeners.add(f); return () => NL.viewListeners.delete(f); }, []);
    if (!info || info.level === 'WORLD') return null;
    const lay = NL.Scene && NL.Scene.layout();
    let map = null;
    if (lay && lay.bbox) {
      const bb = lay.bbox, W = 170, H = 104, pad = 7, sc = Math.min((W - pad * 2) / bb.w, (H - pad * 2) / bb.h);
      const ox = (W - bb.w * sc) / 2, oy = (H - bb.h * sc) / 2;
      map = html`<div class="minimap" style=${{ width: W + 'px', height: H + 'px' }}>${lay.boxes.map(b => html`<button type="button" class=${cls('mm-room', b.key === lay.room && 'on')} title=${b.label || b.key}
        style=${{ left: (ox + (b.x - bb.x) * sc).toFixed(1) + 'px', top: (oy + (b.y - bb.y) * sc).toFixed(1) + 'px', width: (b.w * sc).toFixed(1) + 'px', height: (b.h * sc).toFixed(1) + 'px' }}
        onClick=${() => NL.Scene.goRoom(b.key)}>${b.n || ''}</button>`)}</div>`;
    }
    return html`<div class="crumb"><button class="btn btn-sm" onClick=${() => NL.Scene.back()}>◂ back</button><span class="crumb-t">${info.label || ''}</span>${map}</div>`;
  };

  /* what the world shows: the work, its cost, what waits on you, what went wrong */
  const LENSES = [['work', 'Work'], ['cost', 'Cost'], ['waiting', 'Waiting on you'], ['risk', 'Risk']];
  const Lenses = () => {
    const [l, setL] = useState(() => NL.ls.get('nl-lens', 'work'));
    useEffect(() => { if (NL.Scene) NL.Scene.setLens(l); NL.ls.set('nl-lens', l); }, [l]);
    return html`<div class="lenses" role="radiogroup" aria-label="what the world shows">${LENSES.map(([v, t]) =>
      html`<button type="button" role="radio" aria-checked=${l === v} class=${cls('lens', l === v && 'on')} onClick=${() => setL(v)}>${t}</button>`)}</div>`;
  };

  /* your other labs, drawn past the table's back edge (the same list as Labs & machines) */
  const Neighbours = () => {
    const live = NL.useFleet ? NL.useFleet() : null;
    const fl = NL.DEMO ? NL.demoFleet : live;
    const labs = ((fl && fl.labs) || []).filter(l => !l.current);
    const list = labs.map(l => ({ key: l.key, name: l.name || l.path, machine: l.machine, needs: (l.summary || {}).needs || 0, running: (l.summary || {}).running || 0, state: l.state }));
    useEffect(() => { if (!NL.Scene) return; NL.Scene.setNeighbours(list); NL.Scene.onLab(key => { const l = labs.find(x => x.key === key); if (!l) return;
      if (NL.DEMO) return NL.toast(`Demo mode — this would open ${l.name}`); NL.goToLab(l); }); }, [JSON.stringify(list)]);
    return null;
  };

  NL.Home = () => {
    const s = NL.useLab();
    const conn = NL.useConn();
    const prefs = NL.usePrefs();
    useEffect(() => { const t = setTimeout(() => NL.Scene && NL.Scene.insetsChanged(), 60); return () => clearTimeout(t); }, [prefs.rail]);
    return html`<div class="home">
      <${Lenses} />
      <${Neighbours} />
      <${Crumb} />
      <${Rail} />
      <${Key} />
      <div class="home-bottom"><${NL.AskBar} target="hub" /></div>
      ${conn === 'reconnecting' || conn === 'offline' ? html`<div class="veil">⟳ reconnecting to the lab — showing the last snapshot</div>` : null}
    </div>`;
  };

  /* ── History: commands, notes, events ───────────────────────────────────── */
  NL.HistoryPage = ({ query }) => {
    const s = NL.useLab();
    const [q, setQ] = useState('');
    const [tab, setTab] = useState('events');
    const [since, setSince] = useState((query && query.since) || '');
    // opening History counts as catching up
    useEffect(() => { const last = (s.events || []).slice(-1)[0], prev = NL.ls.get('nl-seen-through', ''); if (prev) NL.ls.set('nl-seen-through-prev', prev); if (last) NL.ls.set('nl-seen-through', last.ts); }, []);
    const evs = (s.events || []).slice().reverse().filter(e => (!since || (e.ts || '') > since) && (!q || JSON.stringify(e).toLowerCase().includes(q.toLowerCase())));
    const where = e => { const id = e.idea || (e.source !== 'hub' ? e.source : null), it = id && NL.item(s, id); return id ? html`<a class="link" href=${'#/study/' + id}>${NL.clip(it ? it.title || id : id, 28)}</a>` : 'the lab'; };
    const who = e => /campaign/i.test(`${e.detail || ''} ${(e.data || {}).by || ''}`) ? 'a campaign' : /PI|you\b|dashboard/.test(`${(e.data || {}).by || ''} ${e.source || ''}`) ? 'you' : e.run_id || /run|agent/.test(e.kind || '') ? 'an agent' : '';
    const outcome = e => e.kind === 'run_finished' && e.status ? html` <${NL.Pill} tone=${e.status === 'completed' ? 'ok' : 'bad'}>${e.status === 'completed' ? 'done' : e.status}</${NL.Pill}>` : null;
    const dirs = [...(s.directives || []), ...(s.items || []).flatMap(i => (i.directives || []).map(d => ({ ...d, target: d.target || i.id })))]
      .sort((a, b) => (b.ts || '').localeCompare(a.ts || '')).filter(d => !q || (d.text || '').toLowerCase().includes(q.toLowerCase()));
    return html`<div class="page">
      <header class="page-head"><div><h1>History</h1><p class="lede">What happened in the lab, and every command and note you sent — with whether an agent has acted on it.</p></div>
        <div class="row"><button type="button" class=${cls('lens', since && 'on')} onClick=${() => setSince(since ? '' : (NL.ls.get('nl-seen-through-prev', '') || (s.events || []).slice(-20)[0]?.ts || ''))}>Since my last visit</button>
          <input class="input search" placeholder="Filter…" value=${q} onInput=${e => setQ(e.target.value)} /></div></header>
      <${NL.Tabs} tabs=${[{ id: 'events', label: 'Events', count: evs.length }, { id: 'commands', label: 'Your commands & notes', count: dirs.length }]} value=${tab} onChange=${setTab} />
      ${tab === 'events' ? (!evs.length ? html`<${NL.Empty} icon="◷">${since ? 'Nothing has happened since your last visit.' : q ? 'Nothing matches that filter.' : 'Nothing has happened in this lab yet.'}</${NL.Empty}>`
        : html`<table class="table"><thead><tr><th>When</th><th>Where</th><th>What</th><th>By</th><th>Detail</th></tr></thead><tbody>
        ${evs.slice(0, 300).map(e => html`<tr class=${cls(e.run_id && 'click')} onClick=${e.run_id ? () => NL.openRun(e.run_id) : null}><td class="mono small">${NL.when ? NL.when(e.ts) : (e.ts || '').replace('T', ' ').slice(5, 16)}</td><td>${where(e)}</td>
          <td><b>${(e.kind || '').replace(/_/g, ' ')}</b>${outcome(e)}</td><td class="small muted">${who(e)}</td><td class="small">${NL.clip(e.detail, 160) || html`<span class="muted">—</span>`}${e.run_id ? html` <span class="link small">open ↗</span>` : null}</td></tr>`)}</tbody></table>`)
      : html`<table class="table"><thead><tr><th>When</th><th>To</th><th>What</th><th>State</th></tr></thead><tbody>
        ${dirs.map(d => html`<tr><td class="mono small">${(d.ts || '').replace('T', ' ').slice(5, 16)}</td><td>${d.target === 'hub' || !d.target ? 'lab' : d.target}</td>
          <td>${d.kind === 'command' ? html`<b>${(d.action || '').replace(/_/g, ' ')}</b> ` : null}${NL.clip(d.text, 160)}</td>
          <td><${NL.Pill} tone=${d.state === 'done' ? 'ok' : d.state === 'blocked' ? 'bad' : d.state === 'withdrawn' ? 'muted' : 'ask'}>${d.state}</${NL.Pill}>${d.state === 'done' && !(d.ack && d.ack.evidence) ? html` <span class="warn small" title="done without evidence">no evidence</span>` : null}</td></tr>`)}</tbody></table>`}
    </div>`;
  };
})();
