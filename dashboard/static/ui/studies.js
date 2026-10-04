/* Newts' Lab — studies. The pipeline board (a column per room of the building), and one page per study:
   a lifecycle stepper with the gates drawn as doors, ONE primary next-step button, and tabs for its
   overview, documents, runs, experiments, paper and controls. Also the paper viewer and the claims map. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useMemo, cls } = NL;

  /* what the study needs next → the one primary button */
  NL.nextFor = (s, it) => {
    if (!it) return null;
    const live = NL.runsOf(s, it.id).find(r => NL.RUN_ACTIVE.has(r.status) || r.status === 'queued' || r.status === 'waiting_input');
    if (live) return { label: live.status === 'waiting_input' ? 'Answer its question' : 'Watch the agent live', icon: '▸', run: () => NL.openRun(live.run_id), live };
    if (it.gate && !it.gate_signed) return { label: `Review and sign Gate ${it.gate}`, icon: '✉', run: () => NL.openGate(it.id, it.gate), gate: it.gate };
    if (it.state === NL.gateAt(3) && it.gate === 3 && it.gate_signed) return { label: 'Finalize', icon: '▸', run: async () => {
      if (!await NL.confirm({ title: `Finalize “${it.title || it.id}”?`, ok: 'Start /finalize', body: 'The reproducibility pass, artifact locking and knowledge write-back — under your Gate 3 signature.' })) return;
      const x = await NL.act('/api/finalize', { idea: it.id, confirm: true }, '/finalize queued'); if (x.run_id) NL.openRun(x.run_id); } };
    const skill = NL.nextSkill(it.state, it.gate_signed);   // workflow/stages.yaml next_for_state
    if (!skill) return NL.isDone(it.state) ? null : NL.isShelved(it.state) ? { label: 'Revive it', icon: '↺', run: () => NL.revive(it) } : null;
    if (((s.skills || {})[skill] || {}).level === 'project' && !it.has_project) return null;
    return { label: NL.procTitle(skill), icon: '▸', skill, run: () => NL.launch({ skill, target: it.id }) };
  };

  const StudyCard = ({ it }) => {
    const s = NL.useLab();
    const runs = NL.runsOf(s, it.id);
    const live = runs.filter(r => NL.RUN_ACTIVE.has(r.status)).length;
    const asking = runs.some(r => r.status === 'waiting_input');
    return html`<a class=${cls('scard', it.gate && !it.gate_signed && 'scard-gate', asking && 'scard-ask')} href=${'#/study/' + it.id}>
      <div class="scard-top"><span class="scard-dot" style=${{ background: `hsl(${window.VivScene ? window.VivScene.projectHue(it.id) : 180} 45% 55%)` }}></span><b class="clip">${it.title || it.id}</b></div>
      <div class="scard-meta"><${NL.StatePill} state=${it.state} />
        ${it.gate && !it.gate_signed ? html`<${NL.Pill} tone="gate">✉ Gate ${it.gate}</${NL.Pill}>` : null}
        ${asking ? html`<${NL.Pill} tone="ask">asking you</${NL.Pill}>` : live ? html`<${NL.Pill} tone="live"><i class="dot-live"></i>${live} running</${NL.Pill}>` : null}
        ${it.n_workers ? html`<span class="muted small mono" title="agents working on it">${NL.plural(it.n_workers, 'agent')}</span>` : null}
        ${it.envelope && it.envelope.signed ? html`<span class="muted small" title="FULL runs used of the signed envelope">FULL ${it.envelope.full_done + it.envelope.full_resv}/${it.envelope.full_cap || '∞'}</span>` : null}</div>
      ${it.next && it.next !== '-' ? html`<div class="scard-next muted small clip">${it.next}</div>` : null}</a>`;
  };

  NL.StudiesPage = ({ query }) => {
    const s = NL.useLab();
    useEffect(() => { if (query && query.campaign) NL.openCampaign(query.campaign); }, [query && query.campaign]);
    const camps = NL.campaignsOf(s).filter(c => !['done', 'stopped'].includes(c.status) || (Date.now() - new Date(c.created)) < 3 * 86400e3);
    const [view, setView] = useState(NL.ls.get('nl-studies-view', 'board'));
    const [q, setQ] = useState('');
    const items = (s.items || []).filter(i => !q || (i.title + ' ' + i.id).toLowerCase().includes(q.toLowerCase()));
    const setV = v => { setView(v); NL.ls.set('nl-studies-view', v); };
    return html`<div class="page page-wide">
      <header class="page-head"><div><h1>Studies</h1><p class="lede">Every idea and project, by stage. An idea and the project it grows into are one study.</p></div>
        <div class="row"><input class="input search" placeholder="Filter…" value=${q} onInput=${e => setQ(e.target.value)} />
          <${NL.Seg} value=${view} onChange=${setV} options=${[{ value: 'board', label: 'Board' }, { value: 'table', label: 'Table' }]} />
          <${NL.Btn} icon="⟳" onClick=${() => NL.openStart({ intent: 'campaign' })}>Campaign</${NL.Btn}>
          <${NL.Btn} kind="primary" icon="✦" onClick=${() => NL.openStart({ intent: 'ideate' })}>New direction</${NL.Btn}></div></header>
      ${camps.length ? html`<div class="camp-row">${camps.map(c => html`<${NL.CampaignCard} key=${c.name} c=${c} />`)}</div>` : null}
      ${!(s.items || []).length ? html`<${NL.Empty} icon="🌱" title="No studies yet">Explore a direction and the lab files its best ideas here as studies.
        <div class="row center"><${NL.Btn} kind="primary" onClick=${() => NL.openStart({ intent: 'ideate' })}>Explore a new direction</${NL.Btn}><${NL.Btn} onClick=${() => NL.openStart({ intent: 'adopt' })}>Bring in what I have</${NL.Btn}></div></${NL.Empty}>`
      : view === 'board' ? html`<div class="board">${NL.ROOMS.map(room => {
          const col = items.filter(i => room.states.includes(i.state));
          return html`<section class=${cls('board-col', 'room-' + room.key)}><header><h3>${room.label}</h3><span class="count">${col.length}</span></header>
            <div class="board-cards">${col.length ? col.map(it => html`<${StudyCard} key=${it.id} it=${it} />`) : html`<div class="muted small pad">—</div>`}</div></section>`;
        })}</div>`
      : html`<table class="table"><thead><tr><th>Study</th><th>Stage</th><th>Next</th><th>Runs</th><th>Updated</th></tr></thead>
        <tbody>${items.map(it => html`<tr onClick=${() => NL.go('study/' + it.id)} class="click"><td><b>${it.title || it.id}</b><div class="muted small mono">${it.id}</div></td>
          <td><${NL.StatePill} state=${it.state} />${it.gate && !it.gate_signed ? html` <${NL.Pill} tone="gate">Gate ${it.gate}</${NL.Pill}>` : null}</td>
          <td class="small">${it.next && it.next !== '-' ? it.next : ''}</td><td>${NL.runsOf(s, it.id).length || ''}</td><td class="muted small">${it.updated || ''}</td></tr>`)}</tbody></table>`}
    </div>`;
  };

  /* ── the lifecycle stepper (gates as doors) ─────────────────────────────── */
  const Stepper = ({ it }) => {
    const idx = NL.LIFECYCLE.indexOf(it.state);
    const off = NL.isShelved(it.state);
    return html`<ol class=${cls('stepper', off && 'off')}>${NL.LIFECYCLE.map((st, i) => {
      const gate = NL.GATE_AT[st];
      const done = !off && i < idx, cur = !off && i === idx;
      return html`${gate ? html`<li class=${cls('door', (i < idx || (i === idx && it.gate_signed)) && 'open', cur && it.gate && !it.gate_signed && 'waiting')}
          title=${`Gate ${gate}`}><button type="button" onClick=${() => cur || i < idx ? NL.openGate(it.id, gate) : null}>✉<small>G${gate}</small></button></li>` : null}
        <li class=${cls('step', done && 'done', cur && 'cur')}><span class="step-dot"></span><span class="step-l">${NL.STATE_LABEL[st]}</span></li>`;
    })}${off ? html`<li class="step cur off-state"><span class="step-dot"></span><span class="step-l">${NL.STATE_LABEL[it.state]}</span></li>` : null}</ol>`;
  };

  /* ── the study page ─────────────────────────────────────────────────────── */
  NL.StudyPage = ({ args }) => {
    const s = NL.useLab();
    const slug = args[0], tab = args[1] || 'overview';
    const it = NL.item(s, slug);
    useEffect(() => { if (it && NL.Scene) NL.Scene.highlight(null); }, [slug]);
    if (!it) return html`<div class="page"><${NL.Empty} icon="?" title="No such study">It may have been renamed. <a class="link" href="#/studies">All studies</a></${NL.Empty}></div>`;
    const next = NL.nextFor(s, it);
    const runs = NL.runsOf(s, it.id);
    const setTab = t => NL.go(`study/${it.id}/${t}`);
    const tabs = [{ id: 'overview', label: 'Overview' }, { id: 'docs', label: 'Documents' }, { id: 'runs', label: 'Runs', count: runs.length || null },
      ...(it.has_project ? [{ id: 'experiments', label: 'Experiments', count: (it.inflight || []).length || null }] : []),
      ...(it.has_paper || it.paper ? [{ id: 'paper', label: 'Paper' }] : []),
      { id: 'instructions', label: 'Instructions', count: Object.keys(((((s.workflow || {}).study_custom || {})[it.id]) || {}).procedures || {}).length || null },
      { id: 'controls', label: 'Controls' }];
    return html`<div class="page page-wide">
      <header class="page-head study-head"><div class="grow"><div class="crumbs"><a class="link" href="#/studies">Studies</a> › <span class="mono">${it.id}</span></div>
        <h1>${it.title || it.id}</h1><${Stepper} it=${it} /></div>
        <div class="study-actions">${next ? html`<${NL.Btn} kind="primary" icon=${next.icon} onClick=${next.run}>${next.label}</${NL.Btn}>` : null}
          <${NL.Btn} onClick=${() => NL.openStart({ intent: 'study', target: it.id })}>Work on it…</${NL.Btn}>
          <${NL.Btn} onClick=${() => { NL.go(''); NL.Scene && NL.Scene.focusProject(it.id); }} title="see it in the world">In the world</${NL.Btn}></div></header>
      <${NL.Tabs} tabs=${tabs} value=${tab} onChange=${setTab} />
      <div class="tabpane">
        ${tab === 'overview' ? html`<${Overview} it=${it} />` : null}
        ${tab === 'docs' ? html`<${Documents} it=${it} rel=${args.slice(2).join('/')} />` : null}
        ${tab === 'runs' ? html`<div class="runlist">${runs.length ? runs.slice().sort((a, b) => (b.created || '').localeCompare(a.created || '')).map(r => html`<${NL.RunRow} key=${r.run_id} r=${r} />`) : html`<${NL.Empty} icon="▸">No runs on this study yet.</${NL.Empty}>`}</div>` : null}
        ${tab === 'experiments' ? html`<${Experiments} it=${it} />` : null}
        ${tab === 'paper' ? html`<${PaperPane} it=${it} />` : null}
        ${tab === 'instructions' ? html`<${NL.StudyInstructions} it=${it} />` : null}
        ${tab === 'controls' ? html`<${Controls} it=${it} />` : null}
      </div></div>`;
  };

  const Overview = ({ it }) => {
    const s = NL.useLab();
    const workers = NL.workersOf(s, it.id).filter(w => w.status !== 'done');
    const pending = (it.directives || []).filter(d => d.state === 'pending');
    return html`<div class="cols">
      <div class="col-main"><${NL.DocReader} scope="study" slug=${it.id} rel="IDEA.md" bare fallback=${html`<${NL.Empty} icon="🌱" title="No idea write-up yet">
        This study has no <span class="mono">studies/${it.id}/IDEA.md</span>${it.has_project ? ' — its project repo is under Documents' : ''}.</${NL.Empty}>`} /></div>
      <aside class="col-side">
        <${NL.Section} title="Now">
          <div class="facts"><div><span>Stage</span><b>${NL.STATE_LABEL[it.state]}</b></div>
            ${it.next && it.next !== '-' ? html`<div><span>Next</span><b>${it.next}</b></div>` : null}
            <div><span>Updated</span><b>${it.updated || '—'}</b></div>
            ${it.best ? html`<div><span>Best so far</span><b class="mono">${typeof it.best === 'object' ? Object.entries(it.best).filter(([k]) => k !== 'run_id').map(([k, v]) => `${k} ${typeof v === 'number' ? (+v).toPrecision(4) : v}`).join(' · ') : it.best}</b></div>` : null}
            ${it.envelope ? html`<div><span>FULL runs</span><b>${it.envelope.status}${it.envelope.full_cap ? ` · ${it.envelope.full_done + it.envelope.full_resv}/${it.envelope.full_cap}` : ''}</b></div>` : null}
            ${it.loop_active ? html`<div><span>Loop</span><b class="live">running</b></div>` : null}</div></${NL.Section}>
        ${workers.length ? html`<${NL.Section} title="Agents on it" count=${workers.length}>${workers.map(w => html`<button type="button" class="agent-chip wide" onClick=${() => NL.openWorker(w.worker_id)}><${NL.RoleDot} role=${w.role} /><span class="clip grow">${w.label || NL.roleOf(w.role).label}</span><span class="muted small">${w.in_tool ? '▸ ' + w.in_tool.tool : w.status}</span></button>`)}</${NL.Section}>` : null}
        ${pending.length ? html`<${NL.Section} title="Notes waiting for an agent" count=${pending.length}>${pending.map(d => html`<div class="note"><div>${d.text}</div><div class="row"><span class="muted small">${NL.hhmm(d.ts)}</span><span class="grow"></span>
          <button class="link small" onClick=${() => NL.act('/api/withdraw', { target: it.id, id: d.id, ts: d.ts }, 'Withdrawn')}>withdraw</button></div></div>`)}</${NL.Section}>` : null}
        ${(it.events || []).length ? html`<${NL.Section} title="Recent">${it.events.slice(-8).reverse().map(e => html`<div class="ev"><span class="muted mono small">${NL.hhmm(e.ts)}</span> <b>${e.kind.replace(/_/g, ' ')}</b> <span class="muted">${NL.clip(e.detail, 80)}</span></div>`)}</${NL.Section}>` : null}
      </aside></div>`;
  };

  const Documents = ({ it, rel }) => {
    const tree = NL.useLibTree();
    const g = tree && (tree.groups || []).find(x => x.slug === it.id);
    const docs = g ? g.sections.flatMap(sec => sec.docs.map(d => ({ ...d, sec: sec.title }))) : [];
    const [sel, setSel] = useState(null);
    const cur = sel || (rel ? docs.find(d => d.rel === rel) : null) || docs[0];
    const shown = NL.artifactsOf(NL.useLab()).filter(a => a.study === it.id);
    return html`<div class="page-split inner">
      <aside class="split-left">${shown.length ? html`<div class="shelf-sec"><div class="shelf-sec-h">❏ For you (${shown.length})</div>${shown.map(a => html`<button type="button" class="shelf-doc" onClick=${() => NL.openArtifact(a.id)}>${a.title}${a.question && !a.answered ? ' · asks you' : ''}</button>`)}</div>` : null}
        ${!tree ? html`<${NL.Spinner} />` : !docs.length ? html`<div class="muted small">No documents in the study or its project yet.</div>` :
        g.sections.map(sec => html`<div class="shelf-sec"><div class="shelf-sec-h">${sec.icon || ''} ${sec.title}</div>${sec.docs.map(d => html`<button type="button" class=${cls('shelf-doc', cur && cur.rel === d.rel && cur.scope === d.scope && 'on')} onClick=${() => setSel(d)}>${d.title}</button>`)}</div>`)}</aside>
      <main class="split-right">${cur ? html`<${NL.DocReader} scope=${cur.scope} slug=${cur.slug} rel=${cur.rel} />` : null}</main></div>`;
  };

  const Experiments = ({ it }) => {
    const [out, setOut] = useState(null);
    const tool = async (name) => { setOut({ name, busy: true }); const r = await NL.api('/api/tool', { name, idea: it.id }); setOut({ name, ...r }); };
    const inflight = it.inflight || [];
    return html`<div class="cols"><div class="col-main">
      <${NL.Section} title="Running now" count=${inflight.length || null}>${inflight.length ? inflight.map(r => html`<div class="exp-row">
        <div class="row"><b class="mono">${r.run_id}</b><${NL.Pill} tone=${r.state === 'stalled' ? 'warn' : 'live'}>${r.stage || ''} · ${r.state}</${NL.Pill}><span class="grow"></span>
          <button class="link small" onClick=${async () => { const x = await NL.api('/api/read', { what: 'run', idea: it.id, run: r.run_id }); NL.open(NL.SectionsSheet, { title: r.run_id, data: x }); }}>peek</button></div>
        ${r.budget_min ? html`<${NL.Bar} value=${r.elapsed_s} max=${r.budget_min * 60} tone=${r.elapsed_s > r.budget_min * 51 ? 'warn' : ''} />` : null}
        <div class="muted small">${NL.mins(r.elapsed_s)}${r.budget_min ? ' of ' + r.budget_min + 'm' : ''}${Object.keys(r.last || {}).length ? ' · ' + Object.entries(r.last).slice(0, 4).map(([k, v]) => `${k} ${(+v).toPrecision(4)}`).join(' · ') : ''}</div></div>`)
        : html`<div class="muted">Nothing training right now.${it.n_runs ? ` ${NL.plural(it.n_runs, 'run')} recorded.` : ''}</div>`}</${NL.Section}>
      ${out ? html`<${NL.Section} title=${out.name} action=${html`<button class="link small" onClick=${() => setOut(null)}>close</button>`}>${out.busy ? html`<${NL.Spinner} />` : html`<pre class="plain">${out.output || out.error || '(no output)'}</pre>`}</${NL.Section}>` : null}
    </div><aside class="col-side"><${NL.Section} title="Look closer"><div class="stack">
      <${NL.Btn} onClick=${() => tool('status')}>Project status</${NL.Btn}><${NL.Btn} onClick=${() => tool('compare')}>Compare runs</${NL.Btn}>
      <${NL.Btn} onClick=${() => tool('show_config')}>Effective config</${NL.Btn}><${NL.Btn} onClick=${() => tool('inbox')}>Agent inbox</${NL.Btn}></div></${NL.Section}>
      <${NL.Section} title="Start"><div class="stack">${(NL.PROCS_FOR_STATE[it.state] || []).filter(p => (NL.getState().skills || {})[p]).map(p => {
        const brief = (NL.PROC[p] || {}).kind === 'driver' && (NL.PROC[p] || {}).level === 'project';   // a loop needs its signed brief first
        return html`<${NL.Btn} onClick=${() => brief ? NL.open(NL.LoopBriefSheet, { slug: it.id }, { key: 'loop' }) : NL.launch({ skill: p, target: it.id })}>${NL.procTitle(p)}${brief ? '…' : ''}</${NL.Btn}>`; })}
        </div></${NL.Section}></aside></div>`;
  };

  NL.SectionsSheet = ({ title, data, onClose }) => html`<${NL.Sheet} wide title=${title} onClose=${onClose}>${!data || !data.ok ? html`<div class="note note-warn">${(data && data.error) || 'nothing to show'}</div>` :
    (data.sections || []).map(sec => html`<${NL.Section} title=${sec.title}><pre class="plain">${sec.text}</pre></${NL.Section}>`)}</${NL.Sheet}>`;

  /* ── paper ─────────────────────────────────────────────────────────────── */
  const PaperPane = ({ it }) => {
    const [figs, setFigs] = useState([]);
    const mt = (it.paper && it.paper.mtime) || '';
    useEffect(() => { NL.get(`/api/figs?${NL.qs({ idea: it.id })}`).then(x => setFigs((x && x.figures) || [])); }, [it.id, mt]);
    const src = `/api/paper?${NL.qs({ idea: it.id, t: mt })}`;
    return html`<div class="cols"><div class="col-main">${it.paper ? html`<iframe class="pdf" src=${src} title="the paper"></iframe>` : html`<${NL.Empty} icon="📜">No compiled paper yet (studies/${it.id}/paper/main.pdf).</${NL.Empty}>`}</div>
      <aside class="col-side"><${NL.Section} title="Paper"><div class="stack">${it.paper ? html`<a class="btn" href=${src} target="_blank" rel="noopener">Open the PDF ↗</a>` : null}
        <${NL.Btn} onClick=${() => NL.openClaims(it.id)}>Claims ↔ evidence${it.claims ? ` (${it.claims})` : ''}</${NL.Btn}>
        <${NL.Btn} onClick=${() => NL.launch({ skill: 'make-figures', target: it.id })}>Rebuild figures</${NL.Btn}>
        <${NL.Btn} onClick=${() => NL.launch({ skill: 'critique-paper', target: it.id })}>Critique it</${NL.Btn}>
        ${it.state === NL.gateAt(3) ? html`<${NL.Btn} kind="primary" onClick=${() => NL.openGate(it.id, 3)}>Gate 3…</${NL.Btn}>` : null}</div></${NL.Section}>
        ${figs.length ? html`<${NL.Section} title="Figures" count=${figs.length}><div class="figs">${figs.map(f => /\.pdf$/i.test(f) ? html`<a class="link small" href=${`/api/figure?${NL.qs({ idea: it.id, name: f })}`} target="_blank">${f}</a>` :
          html`<a href=${`/api/figure?${NL.qs({ idea: it.id, name: f })}`} target="_blank" rel="noopener"><img src=${`/api/figure?${NL.qs({ idea: it.id, name: f, t: mt })}`} alt=${f} loading="lazy" /></a>`)}</div></${NL.Section}>` : null}</aside></div>`;
  };
  NL.openPaper = slug => NL.go(`study/${slug}/paper`);

  NL.ClaimsSheet = ({ slug, onClose }) => {
    const [r, setR] = useState(null);
    const [audit, setAudit] = useState(null);
    useEffect(() => { NL.api('/api/claims', { idea: slug }).then(setR); }, [slug]);
    const claims = (r && r.claims) || [];
    return html`<${NL.Sheet} wide title="Claims ↔ evidence" sub="Every number in the paper should point at an artifact on disk (hard rule 1)." onClose=${onClose}
      footer=${html`<div class="row"><${NL.Btn} onClick=${async () => { setAudit({ busy: true }); setAudit(await NL.api('/api/tool', { name: 'audit_claims', idea: slug })); }}>Run the claims audit</${NL.Btn}><span class="grow"></span>${r && r.claims_path ? html`<${NL.EditorLink} path=${r.claims_path}>claims.yaml ↗</${NL.EditorLink}>` : null}</div>`}>
      ${!r ? html`<${NL.Spinner} />` : r.error ? html`<div class="note note-warn">${r.error}</div>` : !claims.length ? html`<${NL.Empty}>claims.yaml has no entries yet.</${NL.Empty}>` : html`
        <div class="muted small">${NL.plural(claims.length, 'claim')} · ${claims.filter(c => c.linked).length} fully linked to artifacts on disk</div>
        ${claims.map(c => { const arts = c.artifacts || [], miss = arts.filter(a => !a.exists).length; return html`<div class="claim">
          <div class="row">${c.id ? html`<b class="mono">${c.id}</b>` : null}<${NL.Pill} tone=${c.linked ? 'ok' : 'warn'}>${c.linked ? 'linked' : arts.length ? miss + ' missing' : 'no artifacts'}</${NL.Pill}><span class="grow">${c.claim || ''}</span></div>
          <div class="row-wrap small">${(c.numbers || []).map(n => html`<span class="chip mono">${n}</span>`)}${c.metric ? html`<span class="chip">metric: ${c.metric}</span>` : null}${c.location ? html`<span class="chip">${c.location}</span>` : null}${c.has_hashes ? html`<span class="chip">🔒 hashed</span>` : null}</div>
          ${arts.map(a => html`<div class="art ${a.exists ? '' : 'miss'}"><span class="mono small">${a.exists ? '' : '○ '}${a.rel}</span>${a.exists && a.run_id && a.project ? html`<button class="link small" onClick=${async () => NL.open(NL.SectionsSheet, { title: a.run_id, data: await NL.api('/api/read', { what: 'run', idea: a.project, run: a.run_id }) })}>peek</button>` : null}<${NL.EditorLink} path=${a.exists ? a.abs : null} /></div>`)}</div>`; })}`}
      ${audit ? html`<${NL.Section} title="Audit">${audit.busy ? html`<${NL.Spinner} />` : html`<pre class="plain">${audit.output || audit.error}</pre>`}</${NL.Section}>` : null}
    </${NL.Sheet}>`;
  };
  NL.openClaims = slug => NL.open(NL.ClaimsSheet, { slug }, { key: 'claims' });

  /* ── controls: steering, signatures, park/kill/revive ───────────────────── */
  const Controls = ({ it }) => {
    const cmd = async (action, label, args, danger) => {
      if (danger && !await NL.confirm({ title: `${label}?`, body: 'The agent does this in-protocol at its next checkpoint (recorded in the study).', ok: label, danger: true })) return;
      const launch = ['start_loop', 'stop_loop', 'run_smoke', 'request_run', 'analyze'].includes(action) && NL.execOn(NL.getState());
      const r = await NL.act('/api/command', { target: it.id, action, args: args || {}, launch }, launch ? `${label} — started` : `${label} — the next agent picks it up at its next checkpoint`);
      if (r.launch && r.launch.run_id) NL.openRun(r.launch.run_id);
    };
    const off = NL.isShelved(it.state);
    return html`<div class="cols"><div class="col-main">
      ${it.has_project ? html`<${NL.Section} title="Loop and experiments"><div class="btn-grid">
        <${NL.Btn} onClick=${() => NL.open(NL.LoopBriefSheet, { slug: it.id }, { key: 'loop' })}>Research loop — brief & start</${NL.Btn}>
        ${it.loop_active ? html`<${NL.Btn} kind="danger" onClick=${() => cmd('stop_loop', 'Stop the loop', {}, true)}>Stop the loop</${NL.Btn}>` : null}
        <${NL.Btn} onClick=${() => cmd('set_mode', 'Switch to explore', { mode: 'explore' })}>Switch the loop to explore</${NL.Btn}>
        <${NL.Btn} onClick=${() => cmd('set_mode', 'Switch to execute', { mode: 'execute' })}>Switch the loop to execute</${NL.Btn}>
        <${NL.Btn} onClick=${() => cmd('run_smoke', 'Run a smoke test')}>Run a smoke test</${NL.Btn}>
        <${NL.Btn} onClick=${() => cmd('request_run', 'Request a run')}>Request a run</${NL.Btn}></div></${NL.Section}>` : null}
      ${it.has_project ? html`<${NL.EnvelopeEditor} it=${it} />` : null}
      <${NL.Section} title="Priority and fate"><div class="btn-grid">
        <${NL.Btn} onClick=${() => cmd('prioritize', 'Prioritize')}>Prioritize it</${NL.Btn}>
        ${off ? html`<${NL.Btn} kind="primary" onClick=${() => NL.revive(it)}>Revive it</${NL.Btn}>` : html`<${NL.Btn} onClick=${() => cmd('park', 'Park it', {}, true)}>Park it</${NL.Btn}><${NL.Btn} kind="danger" onClick=${() => cmd('kill', 'Kill it', {}, true)}>Kill it</${NL.Btn}>`}</div></${NL.Section}>
    </div><aside class="col-side">
      <${NL.Section} title="Signatures"><div class="stack">
        <${NL.Btn} onClick=${() => NL.openGate(it.id, 1)}>Gate 1 — proposal</${NL.Btn}>
        ${it.has_project ? html`<${NL.Btn} onClick=${() => NL.openGate(it.id, 2)}>Gate 2 — FULL-run envelope</${NL.Btn}>` : null}
        ${[NL.gateAt(3), NL.gateOpens(3)].includes(it.state) ? html`<${NL.Btn} onClick=${() => NL.openGate(it.id, 3)}>Gate 3 — finalize</${NL.Btn}>` : null}</div></${NL.Section}>
      <${NL.Section} title="Elsewhere"><div class="stack">${it.project_dir ? html`<${NL.EditorLink} path=${it.project_dir}>Open the project repo ↗</${NL.EditorLink}>` : null}
        <button class="link small" onClick=${() => NL.openNote(it.id)}>Leave a note for the next agent</button></div></${NL.Section}></aside></div>`;
  };
})();
