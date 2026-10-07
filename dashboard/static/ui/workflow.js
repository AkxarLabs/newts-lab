/* Newts' Lab — one study's own instructions, and agents' suggestions for the lab's.
   The lab-wide definition (stages, procedures, methods, roles, rules, rooms…) is edited in Compose
   (compose.js). Here: the study page's Instructions tab — per procedure, ADD instructions or REPLACE the
   method for this study only, saved at once (studies/<slug>/workflow/) — and an agent's proposal, which the
   PI accepts or declines. The procedure's contract always applies and is shown read-only. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useMemo, cls } = NL;

  const studyCustom = (s, study) => (((s.workflow || {}).study_custom || {})[study]) || { procedures: {}, stages: {} };

  /* a small line diff (yours vs the default · the draft vs the lab) */
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
  /** a line diff; `context` folds long unchanged runs */
  NL.Diff = ({ a, b, context }) => {
    const d = useMemo(() => {
      const all = lineDiff(a, b);
      if (!context) return all;
      const near = i => all.slice(Math.max(0, i - context), i + context + 1).some(y => y.t !== '=');
      const out = []; let gap = 0;
      all.forEach((x, i) => { if (x.t !== '=' || near(i)) { if (gap) out.push({ t: '…', s: `${gap} unchanged line${gap === 1 ? '' : 's'}` }); gap = 0; out.push(x); } else gap++; });
      if (gap) out.push({ t: '…', s: `${gap} unchanged line${gap === 1 ? '' : 's'}` });
      return out;
    }, [a, b, context]);
    return html`<pre class="diff">${d.map(x => html`<div class=${cls('dl', x.t === '+' && 'add', x.t === '-' && 'del', x.t === '…' && 'gap')}><i>${x.t === '=' || x.t === '…' ? ' ' : x.t}</i>${x.s || ' '}</div>`)}</pre>`;
  };

  /* the editor for one of the study's layers (saved at once) */
  const LayerEditor = ({ kind, name, study, value, placeholder, onSaved, rows }) => {
    const [text, setText] = useState(value || '');
    useEffect(() => setText(value || ''), [value, study]);
    const dirty = (text || '').trim() !== (value || '').trim();
    const save = async () => { const r = await NL.act('/api/workflow/save', { kind, name, study, text }, 'Saved for this study'); if (r.ok && onSaved) onSaved(); };
    return html`<div class="wf-editor">
      <${NL.Textarea} value=${text} rows=${rows || 7} onInput=${setText} placeholder=${placeholder} mono onSubmit=${save} />
      <div class="row end gap">${value ? html`<${NL.Btn} small kind="ghost" onClick=${async () => { if (await NL.confirm({ title: 'Remove these instructions?', ok: 'Remove', body: 'This study goes back to what the lab does.' })) { const r = await NL.act('/api/workflow/save', { kind, name, study, text: '' }, 'Removed'); if (r.ok && onSaved) onSaved(); } }}>Remove</${NL.Btn}>` : null}
        <${NL.Btn} small kind="primary" disabled=${!dirty} onClick=${save}>Save for this study</${NL.Btn}></div></div>`;
  };

  /* ── one procedure, for one study: instructions · method · what always applies · what the agent reads ── */
  NL.ProcedureSheet = ({ name, study, onClose }) => {
    const [tab, setTab] = useState('instructions');
    const [d, setD] = useState(null);
    const [n, setN] = useState(0);
    const reload = () => setN(x => x + 1);
    useEffect(() => { NL.get('/api/workflow/item?kind=procedure&name=' + encodeURIComponent(name) + '&study=' + encodeURIComponent(study)).then(setD); }, [name, study, n]);
    const p = (NL.WF.procedures || {})[name] || {};
    const layer = (d && d.study_layer) || {};
    const tabs = [{ id: 'instructions', label: 'Instructions' }, ...(p.replaceable ? [{ id: 'method', label: layer.method ? 'Method (this study’s)' : 'Method' }] : []),
      { id: 'contract', label: 'Always applies' }, { id: 'brief', label: 'What the agent reads' }];
    return html`<${NL.Sheet} wide kicker=${'For this study · /' + name} title=${p.title || '/' + name} sub=${p.does || ''} onClose=${onClose}>
      ${!d ? html`<${NL.Spinner} />` : d.error ? html`<div class="warn">${d.error}</div>` : html`
        <${NL.Tabs} tabs=${tabs} value=${tab} onChange=${setTab} />
        ${tab === 'instructions' ? html`
          <p class="muted">Added to <b>${p.title || name}</b> whenever it runs on <b>${study}</b>, on top of the lab's method. Preferences, datasets or baselines to use, things to avoid.</p>
          <${LayerEditor} kind="add" name=${name} study=${study} value=${layer.add} onSaved=${reload}
            placeholder=${'e.g.\n- The baseline for this study is the 2024 MoE router.\n- Run everything on CPU.'} />
          ${d.lab && d.lab.add ? html`<${NL.Section} title="Also applies — the lab's"><${NL.Markdown} text=${d.lab.add} /></${NL.Section}>` : null}` : null}
        ${tab === 'method' ? html`<${MethodTab} d=${d} name=${name} study=${study} layer=${layer} reload=${reload} />` : null}
        ${tab === 'contract' ? html`
          <p class="muted">The procedure's contract: its checks, records, gates and stop points. It binds whatever the method or the instructions say.</p>
          ${(p.outputs || []).length ? html`<${NL.Section} title="It must still produce"><ul>${p.outputs.map(o => html`<li>${o}</li>`)}</ul></${NL.Section}>` : null}
          <div class="wf-contract"><${NL.Markdown} text=${d.contract} /></div>` : null}
        ${tab === 'brief' ? html`
          <p class="muted">Exactly what an agent running <span class="mono">/${name}</span> on ${study} reads for this step (sha <span class="mono">${d.brief_sha}</span> — each run records the version it used).</p>
          <pre class="wf-brief">${d.brief}</pre>` : null}
        <div class="row end"><a class="link small" href=${'#/compose/procedure/' + name} onClick=${onClose}>Change it for the whole lab in Compose →</a></div>`}
    </${NL.Sheet}>`;
  };

  const MethodTab = ({ d, name, study, layer, reload }) => {
    const [editing, setEditing] = useState(false);
    const [text, setText] = useState('');
    const [view, setView] = useState('text');
    const replaced = layer.method;
    const lab = (d.lab && d.lab.method) || d.default_method || '';
    const save = async () => { const r = await NL.act('/api/workflow/save', { kind: 'method', name, study, text }, 'Method replaced for this study'); if (r.ok) { setEditing(false); reload(); } };
    const reset = async () => {
      if (!await NL.confirm({ title: 'Use the lab’s method again?', ok: 'Use the lab’s', body: `This study's own method for /${name} is removed.` })) return;
      const r = await NL.act('/api/workflow/save', { kind: 'method', name, study, text: '' }, 'Back to the lab’s method'); if (r.ok) reload();
    };
    if (editing) return html`<div>
      <p class="muted">How this study should do this step. The contract (<i>Always applies</i>) still holds.</p>
      <${NL.Textarea} value=${text} rows=${22} onInput=${setText} mono onSubmit=${save} />
      <div class="row end gap"><${NL.Btn} small kind="ghost" onClick=${() => setEditing(false)}>Cancel</${NL.Btn}><${NL.Btn} small kind="primary" onClick=${save}>Save for this study</${NL.Btn}></div></div>`;
    return html`<div>
      <div class="row between"><p class="muted">${replaced ? html`<b>This study's own method</b> replaces the lab's.` : html`The lab's method.`}</p>
        ${replaced ? html`<${NL.Seg} value=${view} onChange=${setView} options=${[{ value: 'text', label: 'This study’s' }, { value: 'diff', label: 'Compare with the lab’s' }]} />` : null}</div>
      ${view === 'diff' && replaced ? html`<${NL.Diff} a=${lab} b=${replaced} />` : html`<div class="wf-method"><${NL.Markdown} text=${replaced || lab || '_(no separate method — this procedure is all contract)_'} /></div>`}
      <div class="row end gap">${replaced ? html`<${NL.Btn} small kind="ghost" onClick=${reset}>Use the lab’s</${NL.Btn}>` : null}
        <${NL.Btn} small onClick=${() => { setText(replaced || lab); setEditing(true); }}>${replaced ? 'Edit' : 'Replace for this study…'}</${NL.Btn}></div></div>`;
  };

  /* instructions for every procedure of one stage, for one study */
  const StudyStageSheet = ({ stage, study, onClose }) => {
    const [d, setD] = useState(null);
    const [n, setN] = useState(0);
    const st = NL.STAGES.find(x => x.id === stage) || { title: stage };
    useEffect(() => { NL.get('/api/workflow/item?kind=stage&name=' + encodeURIComponent(stage) + '&study=' + encodeURIComponent(study)).then(setD); }, [stage, study, n]);
    return html`<${NL.Sheet} kicker="For this study · every procedure of the stage" title=${st.title} onClose=${onClose}>
      ${!d ? html`<${NL.Spinner} />` : d.error ? html`<div class="warn">${d.error}</div>` : html`
        <p class="muted">Added to every procedure of ${String(st.title).toLowerCase()} when it runs on <b>${study}</b>.</p>
        <${LayerEditor} kind="stage" name=${stage} study=${study} rows=${5} value=${(d.study_layer || {}).add} onSaved=${() => setN(x => x + 1)}
          placeholder="e.g. Keep every run in this stage under 2 GPU-hours." />`}
    </${NL.Sheet}>`;
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
    return html`<${NL.Sheet} wide kicker="An agent suggests" title=${r && r.ok ? `${r.kind === 'method' ? 'A new method for' : 'Instructions for'} ${r.kind === 'stage' ? 'the stage ' : r.kind === 'role' ? 'the role ' : '/'}${r.name}` : 'A suggested change'}
      sub=${r && r.ok ? (r.study ? 'for ' + r.study : 'for the whole lab') : ''} onClose=${onClose}
      footer=${r && r.ok && r.status === 'pending' ? html`<${NL.Btn} kind="ghost" onClick=${() => decide(false)}>Decline</${NL.Btn}><${NL.Btn} kind="primary" onClick=${() => decide(true)}>Accept</${NL.Btn}>` : null}>
      ${!r ? html`<${NL.Spinner} />` : r.error ? html`<div class="warn">${r.error}</div>` : html`
        ${r.why ? html`<blockquote class="quote">${r.why}</blockquote>` : null}
        <div class="muted small">from ${r.by ? html`<a class="link" href=${'#/run/' + r.by}>run ${r.by}</a>` : 'an agent'} · ${NL.ago(r.ts)} · ${r.status}</div>
        <${NL.Section} title="What changes"><${NL.Diff} a=${before} b=${after} /></${NL.Section}>`}
    </${NL.Sheet}>`;
  };

  /* ── a study's own instructions (the study page's Instructions tab) ─────────── */
  NL.StudyInstructions = ({ it }) => {
    const s = NL.useLab();
    const mine = studyCustom(s, it.id);
    const cur = NL.stageOf(it.state);
    return html`<div>
      <p class="lede">Instructions for this study only, added on top of the lab's.</p>
      <p class="muted">Useful for “use dataset Y”, “the baseline is Z”, “this study runs on CPU”. To change how the whole lab works, use <a class="link" href="#/compose">Compose</a>.</p>
      ${NL.STAGES.map(st => html`<div class=${cls('wf-srow', cur && cur.id === st.id && 'cur')} key=${st.id}>
        <b>${st.title}</b>${cur && cur.id === st.id ? html` <${NL.Pill} tone="live">now</${NL.Pill}>` : null}
        <span class="row gap wrap">${(st.procedures || []).map(p => { const f = (mine.procedures || {})[p] || {}; return html`<button type="button" class=${cls('chip', (f.add || f.method) && 'on')} onClick=${() => NL.open(NL.ProcedureSheet, { name: p, study: it.id })}>${NL.procTitle(p)}${f.method ? ' · method' : f.add ? ' · +' : ''}</button>`; })}
          <button type="button" class="link small" onClick=${() => NL.open(StudyStageSheet, { stage: st.id, study: it.id })}>whole stage${(mine.stages || {})[st.id] ? ' · +' : ''}…</button></span></div>`)}
    </div>`;
  };
})();
