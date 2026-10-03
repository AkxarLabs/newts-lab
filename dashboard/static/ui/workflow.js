/* Newts' Lab — the Workflow page: how this lab does research, stage by stage, and the PI's own
   instructions on top. Each stage runs its procedures; for each procedure the PI can ADD instructions or
   REPLACE its method (lab-wide, or for one study). The procedure's contract — gates, guard calls, ledgers,
   the run footer — always applies and is shown read-only. Agents can only PROPOSE changes; the PI accepts
   or declines them here. Everything lives in files (lab/workflow/, studies/<slug>/workflow/). */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useMemo, cls } = NL;

  const custom = (s, study) => {
    const wf = s.workflow || {};
    return study ? ((wf.study_custom || {})[study] || { procedures: {}, stages: {} }) : (wf.custom || { procedures: {}, stages: {}, roles: {} });
  };
  const flagsOf = (s, study, proc) => {
    const lab = (custom(s, null).procedures || {})[proc] || {};
    const st = study ? ((custom(s, study).procedures || {})[proc] || {}) : {};
    return { add: lab.add || st.add, method: lab.method || st.method, stale: lab.stale || st.stale, studyOwn: !!(st.add || st.method) };
  };

  const Chips = ({ f }) => html`${f.method ? html`<${NL.Pill} tone="ask" title="the PI replaced this procedure's method">method replaced</${NL.Pill}>` : null}
    ${f.add ? html`<${NL.Pill} tone="state" title="the PI added instructions">+ your instructions</${NL.Pill}>` : null}
    ${f.stale ? html`<${NL.Pill} tone="warn" title="the default method changed after you replaced it — review it">default changed</${NL.Pill}>` : null}`;

  /* a small line diff (for "your method vs the default") */
  function lineDiff(a, b) {
    const A = a ? a.split('\n') : [], B = b ? b.split('\n') : [];
    if (A.length * B.length > 250000) return [{ t: '=', s: '(too long to compare line by line)' }];
    const n = A.length, m = B.length, L = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    const out = []; let i = 0, j = 0;
    while (i < n && j < m) { if (A[i] === B[j]) { out.push({ t: '=', s: A[i] }); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) out.push({ t: '-', s: A[i++] }); else out.push({ t: '+', s: B[j++] }); }
    while (i < n) out.push({ t: '-', s: A[i++] }); while (j < m) out.push({ t: '+', s: B[j++] });
    return out;
  }
  const Diff = ({ a, b }) => {
    const d = useMemo(() => lineDiff(a, b), [a, b]);
    return html`<pre class="diff">${d.map(x => html`<div class=${cls('dl', x.t === '+' && 'add', x.t === '-' && 'del')}><i>${x.t === '=' ? ' ' : x.t}</i>${x.s || ' '}</div>`)}</pre>`;
  };

  /* the editor for one layer (lab-wide or one study's) of one kind */
  const LayerEditor = ({ kind, name, study, value, placeholder, onSaved, rows, hint }) => {
    const [text, setText] = useState(value || '');
    useEffect(() => setText(value || ''), [value, study]);
    const dirty = (text || '').trim() !== (value || '').trim();
    const save = async () => { const r = await NL.act('/api/workflow/save', { kind, name, study: study || null, text }, 'Saved'); if (r.ok && onSaved) onSaved(); };
    return html`<div class="wf-editor">
      <${NL.Textarea} value=${text} rows=${rows || 7} onInput=${setText} placeholder=${placeholder} mono onSubmit=${save} />
      ${hint ? html`<div class="field-hint">${hint}</div>` : null}
      <div class="row end gap">${value ? html`<${NL.Btn} small kind="ghost" onClick=${async () => { if (await NL.confirm({ title: 'Remove these instructions?', ok: 'Remove', body: 'The procedure goes back to its default for this scope.' })) { const r = await NL.act('/api/workflow/save', { kind, name, study: study || null, text: '' }, 'Removed'); if (r.ok && onSaved) onSaved(); } }}>Remove</${NL.Btn}>` : null}
        <${NL.Btn} small kind="primary" disabled=${!dirty} onClick=${save}>Save${study ? ' for this study' : ''}</${NL.Btn}></div></div>`;
  };

  /* ── one procedure: instructions · method · what always applies · what the agent reads ─────────── */
  NL.ProcedureSheet = ({ name, study: study0, onClose }) => {
    const s = NL.useLab();
    const [study, setStudy] = useState(study0 || '');
    const [tab, setTab] = useState('instructions');
    const [d, setD] = useState(null);
    const [n, setN] = useState(0);
    const reload = () => setN(x => x + 1);
    useEffect(() => { NL.get('/api/workflow/item?kind=procedure&name=' + encodeURIComponent(name) + (study ? '&study=' + encodeURIComponent(study) : '')).then(setD); }, [name, study, n]);
    const p = (NL.WF.procedures || {})[name] || {};
    const layer = d && (study ? d.study_layer || {} : d.lab || {});
    const replaced = layer && layer.method;
    const studies = (s.items || []).filter(i => i.state !== 'killed');
    const scopeSel = html`<div class="wf-scope"><span class="muted small">Applies to</span><${NL.Select} value=${study} onChange=${setStudy}
      options=${[{ value: '', label: 'the whole lab' }, ...studies.map(i => ({ value: i.id, label: 'only ' + (i.title || i.id) }))]} /></div>`;
    const tabs = [{ id: 'instructions', label: 'Your instructions' }, ...(p.replaceable ? [{ id: 'method', label: replaced ? 'Method (yours)' : 'Method' }] : []),
      { id: 'contract', label: 'Always applies' }, { id: 'brief', label: 'What the agent reads' }];
    return html`<${NL.Sheet} wide title=${p.title || '/' + name} sub=${html`<span class="mono">/${name}</span> · ${p.does || ''}`} onClose=${onClose} icon="✎">
      ${!d ? html`<${NL.Spinner} />` : d.error ? html`<div class="warn">${d.error}</div>` : html`
        ${scopeSel}
        ${d.stale ? html`<div class="note note-warn">The default method changed after you replaced it. Compare them in <b>Method</b> and decide whether to keep yours.</div>` : null}
        <${NL.Tabs} tabs=${tabs} value=${tab} onChange=${setTab} />
        ${tab === 'instructions' ? html`
          <p class="muted">Added to <b>${p.title || name}</b> every time it runs${study ? html` for <b>${study}</b>` : ' anywhere in the lab'} — on top of its method. Write what you would tell a new lab member: preferences, must-dos, datasets or tools to use, things to avoid.</p>
          <${LayerEditor} kind="add" name=${name} study=${study} value=${layer.add} onSaved=${reload}
            placeholder=${'e.g.\n- Always compare against the strongest 2024 baseline, not the classic one.\n- Log GPU-hours for every PILOT in the ledger entry.\n- Never use dataset X (license).'} />
          ${study && d.lab && d.lab.add ? html`<${NL.Section} title="Also applies (lab-wide)"><${NL.Markdown} text=${d.lab.add} /></${NL.Section}>` : null}` : null}
        ${tab === 'method' ? html`<${MethodTab} d=${d} name=${name} study=${study} layer=${layer} reload=${reload} />` : null}
        ${tab === 'contract' ? html`
          <p class="muted">The procedure's contract: its checks, records, gates and stop points. It binds whatever the method or your instructions say, so the lab's guarantees (evidence, gates, signatures) can't be switched off by accident.</p>
          ${(p.outputs || []).length ? html`<${NL.Section} title="It must still produce">${html`<ul>${p.outputs.map(o => html`<li>${o}</li>`)}</ul>`}</${NL.Section}>` : null}
          <div class="wf-contract"><${NL.Markdown} text=${d.contract} /></div>` : null}
        ${tab === 'brief' ? html`
          <p class="muted">Exactly what an agent running <span class="mono">/${name}</span>${study ? ' on ' + study : ''} reads for this stage (sha <span class="mono">${d.brief_sha}</span> — each run records which version it used).</p>
          <pre class="wf-brief">${d.brief}</pre>` : null}`}
    </${NL.Sheet}>`;
  };

  const MethodTab = ({ d, name, study, layer, reload }) => {
    const [editing, setEditing] = useState(false);
    const [text, setText] = useState('');
    const [view, setView] = useState('text');
    const replaced = layer.method;
    const inherited = study && !replaced && d.lab && d.lab.method;
    const start = () => { setText(replaced || (d.lab && d.lab.method) || d.default_method || ''); setEditing(true); };
    const save = async () => { const r = await NL.act('/api/workflow/save', { kind: 'method', name, study: study || null, text }, 'Method replaced'); if (r.ok) { setEditing(false); reload(); } };
    const reset = async () => {
      if (!await NL.confirm({ title: 'Go back to the default method?', ok: 'Use the default', body: `Your replacement ${study ? 'for this study ' : ''}is removed; /${name} follows the lab's ${study ? 'method' : 'default method'} again.` })) return;
      const r = await NL.act('/api/workflow/save', { kind: 'method', name, study: study || null, text: '' }, 'Back to the default'); if (r.ok) reload();
    };
    if (editing) return html`<div>
      <p class="muted">Write the method the way you want this stage done. The contract (<i>Always applies</i>) still holds, and the brief lists what the stage must still produce.</p>
      <${NL.Textarea} value=${text} rows=${22} onInput=${setText} mono onSubmit=${save} />
      <div class="row end gap"><${NL.Btn} small kind="ghost" onClick=${() => setEditing(false)}>Cancel</${NL.Btn}><${NL.Btn} small kind="primary" onClick=${save}>Save the method${study ? ' for this study' : ''}</${NL.Btn}></div></div>`;
    const current = replaced || inherited || d.default_method;
    if (!current) return html`<div class="note note-warn">This lab's copy of <span class="mono">/${name}</span> predates the split into a contract and a method, so it has no separate default method to show. Your instructions (the first tab) still apply. To replace the method as well, update the lab's procedures from the template first (<span class="mono">git pull</span> in the lab, or a fresh lab). A method you write now still reaches every headless run.
      <div class="row end"><${NL.Btn} small onClick=${start}>Write a method anyway…</${NL.Btn}></div></div>`;
    return html`<div>
      <div class="row between wrap"><p class="muted">${replaced ? html`<b>Your method</b>${study ? ' for this study' : ' for the whole lab'} replaces the default.` : inherited ? html`This study uses <b>the lab's replacement method</b>.` : html`The <b>default method</b> that ships with the lab.`}</p>
        <div class="row gap">${replaced ? html`<${NL.Seg} value=${view} onChange=${setView} options=${[{ value: 'text', label: 'Yours' }, { value: 'diff', label: 'Compare with the default' }]} />` : null}</div></div>
      ${view === 'diff' && replaced ? html`<${Diff} a=${d.default_method} b=${replaced} />` : html`<div class="wf-method"><${NL.Markdown} text=${current} /></div>`}
      <div class="row end gap">${replaced ? html`<${NL.Btn} small kind="ghost" onClick=${reset}>Use the default</${NL.Btn}>` : null}
        <${NL.Btn} small kind=${replaced ? '' : 'primary'} onClick=${start}>${replaced ? 'Edit your method' : 'Replace the method…'}</${NL.Btn}></div></div>`;
  };

  /* ── an agent's proposal ─────────────────────────────────────────────── */
  NL.ProposalSheet = ({ id, onClose }) => {
    const [r, setR] = useState(null);
    const [cur, setCur] = useState(null);
    useEffect(() => { NL.get('/api/workflow/proposal?id=' + encodeURIComponent(id)).then(x => {
      setR(x);
      if (x && x.ok) NL.get(`/api/workflow/item?kind=${x.kind === 'stage' ? 'stage' : x.kind === 'role' ? 'role' : 'procedure'}&name=${encodeURIComponent(x.name)}${x.study ? '&study=' + encodeURIComponent(x.study) : ''}`).then(setCur);
    }); }, [id]);
    const decide = async accept => { const x = await NL.act('/api/workflow/proposal', { id, accept }, accept ? 'Accepted' : 'Declined'); if (x.ok) onClose(); };
    const layer = cur && (r && r.study ? cur.study_layer || {} : cur.lab || {});
    const before = !cur || !r ? '' : r.kind === 'method' ? (layer.method || cur.default_method || '') : (layer.add || '');
    const after = !r ? '' : r.kind === 'method' ? r.text : (before ? before + '\n\n' : '') + r.text;
    return html`<${NL.Sheet} wide title="A suggested instruction change" sub=${r && r.ok ? `${r.kind === 'method' ? 'Replace the method of' : 'Add to'} ${r.kind === 'stage' ? 'the stage' : r.kind === 'role' ? 'the role' : '/'}${r.name}${r.study ? ' · for ' + r.study : ' · lab-wide'}` : ''} onClose=${onClose} icon="✎"
      footer=${r && r.ok && r.status === 'pending' ? html`<${NL.Btn} kind="ghost" onClick=${() => decide(false)}>Decline</${NL.Btn}><${NL.Btn} kind="primary" onClick=${() => decide(true)}>Accept</${NL.Btn}>` : null}>
      ${!r ? html`<${NL.Spinner} />` : r.error ? html`<div class="warn">${r.error}</div>` : html`
        ${r.why ? html`<${NL.Section} title="Why the agent suggests it"><p>${r.why}</p></${NL.Section}>` : null}
        <div class="muted small">from ${r.by ? html`<a class="link" href=${'#/run/' + r.by}>run ${r.by}</a>` : 'an agent'} · ${NL.ago ? NL.ago(r.ts) : r.ts} · ${r.status}</div>
        <${NL.Section} title="What changes"><${Diff} a=${before} b=${after} /></${NL.Section}>`}
    </${NL.Sheet}>`;
  };

  /* ── the page ───────────────────────────────────────────────────────── */
  const StageCard = ({ st, on, onClick, s, study, gate }) => {
    const procs = (st.procedures || []);
    const any = procs.some(p => { const f = flagsOf(s, study, p); return f.add || f.method; }) || (custom(s, null).stages || {})[st.id] || (study && (custom(s, study).stages || {})[st.id]);
    const n = (s.items || []).filter(i => (st.states || []).includes(i.state)).length;
    return html`${gate ? html`<div class="wf-gate" title=${(NL.GATES.find(g => g.n === gate) || {}).title}><span>Gate ${gate}</span></div>` : null}
      <button type="button" class=${cls('wf-stage', on && 'on', any && 'custom')} onClick=${onClick}>
        <b>${st.title}</b><small>${procs.map(NL.procTitle).slice(0, 2).join(' · ')}${procs.length > 2 ? ' …' : ''}</small>
        <span class="wf-stage-foot">${n ? html`<span class="muted">${NL.plural(n, 'study', 'studies')}</span>` : null}${any ? html`<i class="wf-dot" title="customised"></i>` : null}</span></button>`;
  };

  NL.WorkflowPage = ({ query }) => {
    const s = NL.useLab();
    const wf = s.workflow || NL.WF || {};
    const stages = NL.STAGES;
    const [sel, setSel] = useState((query && query.stage) || (stages[0] && stages[0].id));
    const [study, setStudy] = useState((query && query.study) || '');
    const [stageDoc, setStageDoc] = useState(null);
    const [n, setN] = useState(0);
    const st = stages.find(x => x.id === sel) || stages[0];
    useEffect(() => { if (st) NL.get('/api/workflow/item?kind=stage&name=' + st.id + (study ? '&study=' + encodeURIComponent(study) : '')).then(setStageDoc); }, [sel, study, n, JSON.stringify(wf.custom || {})]);
    if (wf.error) return html`<div class="page"><h1>Workflow</h1><div class="note note-warn">The workflow definition has a problem: ${wf.error}</div></div>`;
    const gateBefore = {}; (wf.gates || []).forEach(g => { const at = (wf.states || []).find(x => x.id === g.at); if (at && g.n !== 2) { const nx = stages[stages.findIndex(x => x.id === at.stage) + 1]; if (nx) gateBefore[nx.id] = g.n; } if (g.n === 2) gateBefore['__within_' + (at ? at.stage : '')] = 2; });
    const props = (wf.proposals || []);
    const studies = (s.items || []).filter(i => i.state !== 'killed');
    const roles = wf.roles || [];
    const rolesCustom = custom(s, null).roles || {};
    return html`<div class="page wf-page">
      <header class="page-head"><div><h1>Workflow</h1>
        <p class="muted">How this lab does research. Each stage runs its procedures. You can <b>add your own instructions</b> to any procedure, or <b>replace its method</b> — for the whole lab or just one study. The gates and the lab's rules always apply.</p></div>
        <div class="wf-scope"><span class="muted small">Showing</span><${NL.Select} value=${study} onChange=${setStudy} options=${[{ value: '', label: 'the whole lab' }, ...studies.map(i => ({ value: i.id, label: i.title || i.id }))]} /></div></header>
      ${props.length ? html`<div class="note note-ask wf-props"><b>${NL.plural(props.length, 'suggested change')} from agents</b> — nothing changes until you accept.
        ${props.map(p => html`<button type="button" class="link" onClick=${() => NL.open(NL.ProposalSheet, { id: p.id })}>${p.kind === 'method' ? 'replace' : 'add to'} ${p.kind === 'stage' ? 'stage ' : p.kind === 'role' ? 'role ' : '/'}${p.name}${p.study ? ' (' + p.study + ')' : ''}</button>`)}</div>` : null}
      <div class="wf-pipe" role="tablist">${stages.map(x => html`<${StageCard} key=${x.id} st=${x} s=${s} study=${study} on=${x.id === (st && st.id)} gate=${gateBefore[x.id]} onClick=${() => setSel(x.id)} />`)}</div>
      ${st ? html`<section class="wf-detail">
        <header class="section-head"><h3>${st.title}</h3><span class="muted small">${(st.states || []).map(x => NL.STATE_LABEL[x] || x).join(' · ')}${st.substages ? ' · stages ' + st.substages.join(' → ') : ''}${st.gate || gateBefore['__within_' + st.id] ? ` · ${(NL.GATES.find(g => g.n === (st.gate || gateBefore['__within_' + st.id])) || {}).title || ''}` : ''}</span></header>
        <div class="wf-procs">${(st.procedures || []).map(p => { const P = (wf.procedures || {})[p] || {}; const f = flagsOf(s, study, p);
          return html`<${NL.Card} key=${p} onClick=${() => NL.open(NL.ProcedureSheet, { name: p, study })}>
            <div class="row between"><b>${P.title || p}</b><span class="mono muted small">/${p}</span></div>
            <p class="muted small">${P.does || ''}${P.stops ? html` <i>Stops ${P.stops}.</i>` : ''}</p>
            <div class="row gap wrap"><${Chips} f=${f} />${!f.add && !f.method ? html`<span class="muted small">${P.replaceable ? 'default method' : 'built-in procedure'}</span>` : null}</div></${NL.Card}>`; })}</div>
        <${NL.Section} title=${'For every procedure of ' + st.title.toLowerCase()}>
          <p class="muted small">Instructions that apply to all of this stage's procedures${study ? ' for this study' : ''}.</p>
          ${stageDoc && stageDoc.ok ? html`<${LayerEditor} kind="stage" name=${st.id} study=${study} rows=${4} value=${(study ? stageDoc.study_layer || {} : stageDoc.lab || {}).add} onSaved=${() => setN(x => x + 1)}
            placeholder="e.g. Budget: keep every run in this stage under 2 GPU-hours." />` : html`<${NL.Spinner} />`}
        </${NL.Section}></section>` : null}
      ${!study ? html`<${NL.Section} title="Subagent roles" count=${roles.length}>
        <p class="muted small">The specialists procedures call on (critics, reviewers, runners, the overseer). Your instructions are added to the role everywhere it's used.</p>
        <div class="wf-procs">${roles.map(r => html`<${NL.Card} key=${r} onClick=${() => NL.open(RoleSheet, { name: r })}>
          <div class="row between"><b>${NL.roleOf(r).label}</b>${rolesCustom[r] ? html`<${NL.Pill} tone="state">+ your instructions</${NL.Pill}>` : null}</div>
          <span class="mono muted small">${r}</span></${NL.Card}>`)}</div></${NL.Section}>` : null}
      <p class="muted small">Stored as files: <span class="mono">lab/workflow/</span> (lab-wide) and <span class="mono">studies/&lt;study&gt;/workflow/</span>. The stages themselves are defined in <span class="mono">workflow/stages.yaml</span>.</p>
    </div>`;
  };

  const RoleSheet = ({ name, onClose }) => {
    const [d, setD] = useState(null);
    const [n, setN] = useState(0);
    useEffect(() => { NL.get('/api/workflow/item?kind=role&name=' + encodeURIComponent(name)).then(setD); }, [name, n]);
    return html`<${NL.Sheet} wide title=${NL.roleOf(name).label} sub=${html`<span class="mono">${name}</span> · a subagent role`} onClose=${onClose} icon="✎">
      ${!d ? html`<${NL.Spinner} />` : d.error ? html`<div class="warn">${d.error}</div>` : html`
        <p class="muted">Added to this role's instructions for every backend (Claude, Codex, opencode), in the lab and in its projects' next render.</p>
        <${LayerEditor} kind="role" name=${name} value=${d.lab.add} onSaved=${() => setN(x => x + 1)} placeholder="e.g. Be especially strict about data leakage between train and test." />
        <${NL.Section} title="The role as shipped"><div class="wf-contract"><${NL.Markdown} text=${d.contract} /></div></${NL.Section}>`}
    </${NL.Sheet}>`;
  };

  /* ── a study's own instructions (the study page's Instructions tab) ─────────── */
  NL.StudyInstructions = ({ it }) => {
    const s = NL.useLab();
    const mine = custom(s, it.id);
    const cur = NL.stageOf(it.state);
    return html`<div>
      <p class="muted">Instructions for <b>${it.title || it.id}</b> only — added on top of the lab's. Useful for things like "use dataset Y", "the baseline is Z", "this study must run on CPU".</p>
      ${NL.STAGES.map(st => html`<div class=${cls('wf-srow', cur && cur.id === st.id && 'cur')} key=${st.id}>
        <b>${st.title}</b>${cur && cur.id === st.id ? html` <${NL.Pill} tone="live">now</${NL.Pill}>` : null}
        <span class="row gap wrap">${(st.procedures || []).map(p => { const f = (mine.procedures || {})[p] || {}; return html`<button type="button" class=${cls('chip', (f.add || f.method) && 'on')} onClick=${() => NL.open(NL.ProcedureSheet, { name: p, study: it.id })}>${NL.procTitle(p)}${f.method ? ' · method' : f.add ? ' · +' : ''}</button>`; })}
          <a class="link small" href=${'#/workflow?stage=' + st.id + '&study=' + encodeURIComponent(it.id)}>stage-wide…</a></span></div>`)}
    </div>`;
  };
})();
