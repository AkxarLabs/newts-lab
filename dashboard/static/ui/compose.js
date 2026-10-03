/* Newts' Lab — Compose: everything the lab is made of, in one place, all of it editable.
   Stages and their states, procedures (each a skill folder: a contract and a method), subagent roles, the
   rooms of the building, rules, checks and project types — as forms where a form helps, as their files for
   everything else. Every edit goes into a DRAFT (dashboard/compose.py): nothing reaches the lab or a run
   until the PI reviews it and publishes, and a publish can be undone. Adding anything starts from a copy
   of the closest thing the lab already has. Routes: #/compose · #/compose/<list> · #/compose/<kind>/<name>. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useMemo, cls } = NL;

  /* ── data: GET /api/compose, read again after every edit ─────────────────── */
  const C = { d: null, listeners: new Set() };
  const bump = () => C.listeners.forEach(f => f());
  const reload = async () => { const r = await NL.get('/api/compose'); if (r && !r.error || (r && r.draft)) C.d = r; else C.d = C.d || r; bump(); return r; };
  const useCompose = () => {
    const [, force] = NL.useReducer(x => x + 1, 0);
    useEffect(() => { C.listeners.add(force); reload(); return () => C.listeners.delete(force); }, []);
    return C.d;
  };
  /** one edit of the draft; toasts the outcome and reads the lab again */
  const edit = async (body, ok) => {
    const r = await NL.api('/api/compose', body);
    if (r && r.ok) { if (ok !== false) NL.toast(ok || r.note, 'ok'); (r.warnings || []).forEach(w => NL.toast(w, 'warn')); await reload(); }
    else NL.toast((r && r.error) || 'that did not work', 'bad');
    return r || {};
  };
  const getFile = path => NL.get('/api/compose/file?path=' + encodeURIComponent(path));
  const stripFm = t => String(t || '').replace(/\r\n/g, '\n').replace(/^---\n[\s\S]*?\n---\n?/, '').trim();
  const slugify = t => String(t || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
  const href = (...p) => '#/compose/' + p.filter(Boolean).map(encodeURIComponent).join('/');
  const go = (...p) => NL.go(href(...p).slice(2));
  const stateLabel = (d, id) => ((d.states || []).concat(d.side_states || []).find(s => s.id === id) || {}).label || id;
  const changes = d => (d && d.draft && d.draft.changes) || [];
  const touched = (d, ...prefixes) => changes(d).some(c => prefixes.some(p => c.path === p || c.path.startsWith(p)));

  const KINDS = [
    { id: 'stages', item: 'stage', label: 'Stages', one: 'stage', n: d => d.stages.length, blurb: 'The steps a study moves through, and where you sign the gates.',
      dirty: d => touched(d, 'workflow/stages.yaml', 'lab/workflow/stage.') },
    { id: 'procedures', item: 'procedure', label: 'Procedures', one: 'procedure', n: d => Object.keys(d.procedures).length, blurb: 'What agents do at each step. Each is a skill folder: a contract that always binds, and a method you can rewrite.',
      dirty: d => touched(d, '.claude/skills/') || changes(d).some(c => c.path.startsWith('lab/workflow/') && !/^lab\/workflow\/(stage\.|roles\/)/.test(c.path)) },
    { id: 'roles', item: 'role', label: 'Roles', one: 'role', n: d => d.roles.length, blurb: 'The specialist subagents that procedures call on — critics, reviewers, runners.',
      dirty: d => touched(d, 'agent-roles/', 'lab/workflow/roles/') },
    { id: 'rooms', item: 'room', label: 'Rooms', one: 'room', n: d => d.rooms.length, blurb: 'The building on Home. Each state of a study stands in one room.',
      dirty: d => touched(d, 'lab/rooms/') },
    { id: 'rules', item: 'rule', label: 'Rules', one: 'rule', n: d => ['hard', 'subagent', 'project'].reduce((a, g) => a + (d.rules[g] || []).length, 0), blurb: 'What every agent always does. They are written into every agent’s manual.',
      dirty: d => touched(d, 'workflow/rules.yaml') },
    { id: 'checks', item: 'check', label: 'Checks', one: 'check', n: d => d.checks.length, blurb: 'Small programs that enforce a rule mechanically, so it doesn’t rest on an agent’s word.',
      dirty: d => touched(d, 'checks/') },
    { id: 'types', item: 'type', label: 'Project types', one: 'project type', n: d => d.types.length, blurb: 'Kinds of project — each with its own conventions, read by every agent working in one.',
      dirty: d => touched(d, 'templates/', 'lab/templates/') },
  ];
  const KIND_OF = Object.fromEntries(KINDS.map(k => [k.item, k]));

  /* ── the page ─────────────────────────────────────────────────────────────── */
  NL.ComposePage = ({ args, query }) => {
    const d = useCompose();
    const where = args[0] || '', name = args[1] || '';
    useEffect(() => { if (query && query.tour !== undefined) Tour.start(); }, [query && query.tour]);
    if (NL.DEMO) return html`<div class="page"><div class="kicker">Compose</div><h1>How your lab works</h1><p class="lede">Compose edits a real lab's files — open it from that lab's own dashboard.</p></div>`;
    if (!d) return html`<div class="page"><${NL.Spinner} /></div>`;
    if (d.error && !d.stages) return html`<div class="compose"><${Nav} d=${{ ...d, stages: [], procedures: {}, roles: [], rooms: [], rules: {}, checks: [], types: [] }} where="" />
      <main class="cmp-main"><${DraftBar} d=${d} /><div class="cmp-page"><div class="kicker">Compose</div><h1>The workflow can't be read</h1>
        <div class="note note-warn">${d.error}</div><p class="muted">Fix the file below, or discard the draft.</p>
        <${FileEditor} path="workflow/stages.yaml" /></div></main></div>`;
    let body;
    if (!where) body = html`<${Overview} d=${d} />`;
    else if (where === 'suggestions') body = html`<${Suggestions} d=${d} />`;
    else if (where === 'history') body = html`<${History} d=${d} />`;
    else if (where === 'rules') body = html`<${RulesPage} d=${d} />`;
    else if (where === 'domain') body = html`<${DomainEditor} d=${d} name=${name} />`;
    else if (where === 'rule') body = html`<div class="cmp-page"><${ItemHead} k=${KIND_OF.rule} name="rules.yaml" title="The rules, as text" sub="The forms edit this same file. The tables after the rules are read by the lab's safety code and stay as they are." />
      <${FileEditor} path="workflow/rules.yaml" rows=${32} /></div>`;
    else {
      const k = KINDS.find(x => x.id === where || x.item === where);
      const Ed = { stage: StageEditor, procedure: ProcedureEditor, role: RoleEditor, room: RoomEditor, check: CheckEditor, type: TypeEditor }[where];
      const List = { stages: StagesList, procedures: ProceduresList, roles: RolesList, rooms: RoomsList, checks: ChecksList, types: TypesList }[where];
      body = Ed ? html`<${Ed} key=${name} d=${d} name=${name} query=${query || {}} />` : List ? html`<${List} d=${d} k=${k} />` : html`<${Overview} d=${d} />`;
    }
    return html`<div class="compose">
      <${Nav} d=${d} where=${where} />
      <main class="cmp-main"><${DraftBar} d=${d} />${body}</main></div>`;
  };

  const Nav = ({ d, where }) => {
    const on = id => where === id || (KINDS.find(k => k.id === id) || {}).item === where;
    const props = (d.proposals || []).length;
    return html`<nav class="cmp-nav" aria-label="Compose">
      <a class=${cls('cmp-link', !where && 'on')} href="#/compose"><${NL.Icon} name="layers" /><span class="grow">Overview</span></a>
      <div class="cmp-nav-sec">The lab is made of</div>
      ${KINDS.map(k => html`<a class=${cls('cmp-link', on(k.id) && 'on')} href=${href(k.id)}><span class="grow">${k.label}</span>
        ${k.dirty(d) ? html`<i class="cmp-dot" title="changed in your draft"></i>` : null}<span class="cmp-n">${k.n(d)}</span></a>`)}
      <div class="cmp-nav-sec">Changes</div>
      <a class=${cls('cmp-link', where === 'suggestions' && 'on')} href=${href('suggestions')}><span class="grow">Agents’ suggestions</span>${props ? html`<span class="cmp-n hot">${props}</span>` : null}</a>
      <a class=${cls('cmp-link', where === 'history' && 'on')} href=${href('history')}><span class="grow">Published</span></a>
      <div class="cmp-nav-foot"><button type="button" class="link small" onClick=${Tour.start}>Take the one-minute tour</button></div>
    </nav>`;
  };

  /* ── the draft: a bar on every page, the review, publish / discard ─────────── */
  const discard = async () => {
    if (!await NL.confirm({ title: 'Discard the draft?', ok: 'Discard it', danger: true, body: 'Every edit since you last published is dropped. The lab stays exactly as it is.' })) return;
    const r = await edit({ op: 'discard' }); if (r.ok) Tour.event('closed');
  };
  const openReview = () => NL.open(ReviewSheet, {}, { key: 'cmp-review' });
  const DraftBar = ({ d }) => {
    const dr = d.draft || {};
    if (!dr.active) return html`<div class="cmp-bar"><span class="cmp-bar-dot live"></span><span class="grow"><b>Live.</b> This is what every agent uses now. An edit starts a draft; nothing changes until you publish it.</span></div>`;
    const n = (dr.changes || []).length, p = (dr.problems || []).length;
    return html`<div class=${cls('cmp-bar', 'draft', p && 'bad')}><span class="cmp-bar-dot"></span>
      <span class="grow"><b>Draft</b> · ${n ? NL.plural(n, 'file') + ' changed' : 'nothing changed yet'}${n ? html` · ${p ? html`<button type="button" class="link danger" onClick=${openReview}>${NL.plural(p, 'problem')} to fix</button>` : html`<span class="ok-t">ready to publish</span>`}` : null}</span>
      <${NL.Btn} small kind="ghost" onClick=${discard}>Discard</${NL.Btn}>
      <${NL.Btn} small kind="primary" disabled=${!n} onClick=${openReview}>Review & publish</${NL.Btn}></div>`;
  };

  const ChangeRow = ({ c, open: open0 }) => {
    const [open, setOpen] = useState(!!open0);
    const [f, setF] = useState(null);
    useEffect(() => { if (open && !f) getFile(c.path).then(setF); }, [open]);
    return html`<div class="cmp-change">
      <button type="button" class="cmp-change-h" onClick=${() => setOpen(!open)}><span class=${'chg chg-' + c.status}>${c.status}</span>
        <span class="grow clip"><b>${c.path.split('/').pop()}</b> <span class="mono muted small">${c.path.split('/').slice(0, -1).join('/')}</span></span><${NL.Icon} name=${open ? 'caret' : 'chevron'} /></button>
      ${open ? (f ? html`<${NL.Diff} a=${f.published || ''} b=${f.text || ''} context=${3} />` : html`<${NL.Spinner} />`) : null}</div>`;
  };
  const ReviewSheet = ({ onClose }) => {
    const d = useCompose() || {};
    const dr = d.draft || {};
    const [note, setNote] = useState('');
    const probs = dr.problems || [], ch = dr.changes || [];
    const publish = async () => {
      const r = await edit({ op: 'publish', note }, false);
      if (r.ok) { NL.toast(r.note, 'ok'); onClose(); NL.refresh(); Tour.event('closed'); }
    };
    return html`<${NL.Sheet} wide kicker="Compose" title="Review your draft" sub="Exactly what publishing changes. Runs already going finish with what they started with." onClose=${onClose}
      footer=${html`<${NL.Btn} kind="ghost" onClick=${async () => { await discard(); if (!(C.d.draft || {}).active) onClose(); }}>Discard the draft</${NL.Btn}>
        <${NL.Btn} kind="primary" disabled=${!!probs.length || !ch.length} onClick=${publish}>Publish ${ch.length ? NL.plural(ch.length, 'change') : ''}</${NL.Btn}>`}>
      ${probs.length ? html`<div class="cmp-problems"><b>Fix ${probs.length === 1 ? 'this' : 'these'} first</b><ul>${probs.map(p => html`<li>${p}</li>`)}</ul></div>`
        : ch.length ? html`<div class="cmp-ok"><${NL.Icon} name="check" /> The lab reads consistently with these changes.</div>` : null}
      <${NL.Section} title="Changes" count=${ch.length}>${ch.length ? ch.map((c, i) => html`<${ChangeRow} key=${c.path} c=${c} open=${ch.length <= 3 && i < 3} />`) : html`<div class="muted">Nothing changed yet.</div>`}</${NL.Section}>
      ${ch.length ? html`<${NL.Field} label="A note for the lab’s history (optional)"><${NL.Input} value=${note} onInput=${setNote} placeholder="e.g. a quicker literature pass for workshop papers" onEnter=${() => !probs.length && publish()} /></${NL.Field}>` : null}
    </${NL.Sheet}>`;
  };

  /* ── overview: the pipeline and the building ─────────────────────────────── */
  const gatesBetween = d => {
    const stageOf = st => ((d.states || []).find(s => s.id === st) || {}).stage;
    const after = {}, inside = {};
    (d.gates || []).forEach(g => { if (g.before) after[stageOf(g.at)] = g; else inside[stageOf(g.at)] = g; });
    return { after, inside };
  };
  const Overview = ({ d }) => {
    const { after, inside } = gatesBetween(d);
    const counts = d.studies_in || {};
    return html`<div class="cmp-page">
      <header class="cmp-hero"><div class="kicker">Compose</div><h1>How your lab works</h1>
        <p class="lede">Everything the lab is made of, in one place. Change how any step is done, add procedures, rooms and rules of your own — nothing reaches an agent until you publish.</p>
        <div class="row"><${NL.Btn} kind="primary" onClick=${() => openNew('procedure')}><${NL.Icon} name="plus" /> New procedure</${NL.Btn}>
          <${NL.Btn} onClick=${Tour.start}>Take the one-minute tour</${NL.Btn}></div></header>
      <section class="cmp-sec"><div class="cmp-sec-h"><h2>The pipeline</h2><span class="muted small grow">A study moves left to right. You sign the gates.</span><a class="link small" href=${href('stages')}>All stages →</a></div>
        <div class="cmp-pipe">${(d.stages || []).map((st, i) => html`
          <div class="cmp-stage" role="link" tabIndex="0" onClick=${() => go('stage', st.id)} onKeyDown=${e => e.key === 'Enter' && go('stage', st.id)}>
            <div class="cmp-stage-top"><span class="kicker">${String(i + 1).padStart(2, '0')}</span>${(st.states || []).reduce((a, s) => a + (counts[s] || 0), 0) ? html`<span class="cmp-n" title="studies here now">${(st.states || []).reduce((a, s) => a + (counts[s] || 0), 0)}</span>` : null}</div>
            <b>${st.title}</b>
            <div class="cmp-states">${(st.states || []).map(s => html`<span>${stateLabel(d, s)}</span>`)}</div>
            <div class="cmp-procs">${(st.procedures || []).map(p => html`<a href=${href('procedure', p)} onClick=${e => e.stopPropagation()} class=${cls(touched(d, `.claude/skills/${p}/`) && 'edited')}>${(d.procedures[p] || {}).title || p}</a>`)}
              ${!(st.procedures || []).length ? html`<span class="muted small">no procedure yet</span>` : null}</div>
            ${inside[st.id] ? html`<div class="cmp-gate-in"><${NL.Icon} name="lock" /> Gate ${inside[st.id].n} inside</div>` : null}
          </div>${after[st.id] ? html`<div class="cmp-gate" title=${after[st.id].title}><${NL.Icon} name="lock" /><span>Gate ${after[st.id].n}</span></div>` : null}`)}
          <button type="button" class="cmp-pipe-add" onClick=${() => NL.open(StageAddDialog, {}, { kind: 'dialog' })}><${NL.Icon} name="plus" /><span>Add a stage</span></button></div></section>
      <section class="cmp-sec"><div class="cmp-sec-h"><h2>The building</h2><span class="muted small grow">Where each state of a study stands on Home.</span><a class="link small" href=${href('rooms')}>All rooms →</a></div>
        <${Building} d=${d} /></section>
      <section class="cmp-sec"><div class="cmp-tiles">${KINDS.filter(k => ['roles', 'rules', 'checks', 'types'].includes(k.id)).map(k => html`
        <a class="cmp-tile" href=${href(k.id)}><div class="row between"><b>${k.label}</b><span class="cmp-n">${k.n(d)}</span></div><p class="muted small">${k.blurb}</p></a>`)}</div></section>
    </div>`;
  };

  const FLOOR = f => f > 0 ? (f === 1 ? 'Upstairs' : `Floor ${f}`) : f < 0 ? (f === -1 ? 'Cellar' : `Basement ${-f}`) : 'Ground floor';
  const Building = ({ d }) => {
    const floors = [...new Set((d.rooms || []).map(r => r.floor ?? 0))].sort((a, b) => b - a);
    return html`<div class="cmp-building">${floors.map(f => html`<div class="cmp-floor"><span class="kicker cmp-floor-l">${FLOOR(f)}</span>
      <div class="cmp-floor-rooms">${(d.rooms || []).filter(r => (r.floor ?? 0) === f).sort((a, b) => (a.order || 0) - (b.order || 0)).map(r => html`
        <a class=${cls('cmp-room', r.art === 'plain' && 'plain')} href=${href('room', r.id)}><b>${r.title || r.label}</b>
          <div class="cmp-room-states">${(r.states || []).map(s => html`<span class="chip">${stateLabel(d, s)}</span>`)}</div>
          ${r.gate ? html`<span class="cmp-room-gate"><${NL.Icon} name="lock" /> ${r.gate}</span>` : null}</a>`)}</div></div>`)}
      <button type="button" class="cmp-pipe-add wide" onClick=${() => openNew('room')}><${NL.Icon} name="plus" /><span>Add a room</span></button></div>`;
  };

  /* ── shared pieces: a page head, an item head, files ─────────────────────── */
  const ListHead = ({ k, children }) => html`<header class="cmp-head"><div class="grow"><a class="kicker" href="#/compose">Compose</a><h1>${k.label}</h1><p class="lede">${k.blurb}</p></div>
    <div class="row">${children}${k.item !== 'stage' && k.item !== 'rule' ? html`<${NL.Btn} kind="primary" onClick=${() => openNew(k.item)}><${NL.Icon} name="plus" /> New ${k.one}</${NL.Btn}>` : null}</div></header>`;
  const ItemHead = ({ k, name, title, sub, chips, actions }) => html`<header class="cmp-head"><div class="grow">
      <div class="kicker"><a href=${href(k.id)}>${k.label}</a> / ${name}</div><h1>${title}</h1>${sub ? html`<p class="lede">${sub}</p>` : null}
      ${chips ? html`<div class="row cmp-chips">${chips}</div>` : null}</div><div class="row">${actions}</div></header>`;
  const Origin = ({ o, like }) => html`<span class=${cls('pill', o === 'yours' ? 'pill-live' : '')}>${o === 'yours' ? (like ? `yours · from ${like}` : 'yours') : 'built in'}</span>`;
  const CopyBtn = ({ kind, like }) => html`<${NL.Btn} small onClick=${() => openNew(kind, { like })}><${NL.Icon} name="copy" /> Make a copy</${NL.Btn}>`;
  const DeleteBtn = ({ kind, name, label, body, extra }) => html`<${NL.Btn} small kind="ghost" onClick=${async () => {
    if (!await NL.confirm({ title: `Remove ${label}?`, ok: 'Remove', danger: true, body: body || 'It is removed in your draft; the lab keeps it until you publish.' })) return;
    const r = await edit({ op: 'delete', kind, name, ...(extra || {}) }); if (r.ok) go(KIND_OF[kind].id); }}><${NL.Icon} name="trash" /> Remove</${NL.Btn}>`;

  /** one definition file: edit it in the draft, compare it with the published one */
  const FileEditor = ({ path, intro, rows, onSaved }) => {
    const [f, setF] = useState(null);
    const [t, setT] = useState('');
    const [view, setView] = useState('edit');
    const load = () => getFile(path).then(x => { setF(x); setT((x && x.text) || ''); });
    useEffect(() => { setF(null); setView('edit'); load(); }, [path]);
    if (!f) return html`<${NL.Spinner} />`;
    if (f.error) return html`<div class="note note-warn">${f.error}</div>`;
    const dirty = t !== (f.text || '');
    const state = f.text == null ? 'removed' : f.published == null ? 'new' : f.text !== f.published ? 'edited' : null;
    const save = async () => { const r = await edit({ op: 'write', path, text: t }, 'Saved to the draft'); if (r.ok) { await load(); onSaved && onSaved(); } };
    const revert = async () => { const r = await edit({ op: 'write', path, text: f.published }, 'Back to the published version'); if (r.ok) load(); };
    return html`<div class="cmp-file">
      ${intro ? html`<p class="muted small">${intro}</p>` : null}
      <div class="cmp-file-bar"><${NL.Icon} name="file" /><span class="mono clip grow">${path}</span>${state ? html`<span class=${'chg chg-' + (state === 'edited' ? 'changed' : state === 'new' ? 'added' : 'removed')}>${state}</span>` : null}
        ${f.published != null && f.text != null ? html`<${NL.Seg} value=${view} onChange=${setView} options=${[{ value: 'edit', label: 'Edit' }, { value: 'diff', label: 'Changes' }]} />` : null}</div>
      ${view === 'diff' ? html`<${NL.Diff} a=${f.published || ''} b=${t} context=${4} />`
        : html`<textarea class="cmp-code" spellcheck="false" rows=${rows || 22} value=${t} onInput=${e => setT(e.target.value)}
            onKeyDown=${e => { if ((e.key === 's' || e.key === 'Enter') && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (dirty) save(); } }}></textarea>`}
      <div class="row end">${state && f.published != null ? html`<${NL.Btn} small kind="ghost" onClick=${revert}><${NL.Icon} name="undo" /> Back to published</${NL.Btn}>` : null}
        ${dirty ? html`<${NL.Btn} small kind="ghost" onClick=${() => setT(f.text || '')}>Cancel</${NL.Btn}>` : null}
        <${NL.Btn} small kind="primary" disabled=${!dirty} onClick=${save}>Save to draft</${NL.Btn}></div></div>`;
  };
  const FilesTab = ({ files, intro }) => {
    const [sel, setSel] = useState(files[0]);
    useEffect(() => { if (!files.includes(sel)) setSel(files[0]); }, [files.join('|')]);
    if (!files.length) return html`<div class="muted">No files.</div>`;
    return html`<div class="cmp-files">${files.length > 1 ? html`<div class="cmp-file-list">${files.map(f => html`<button type="button" class=${cls('cmp-file-pick', f === sel && 'on')} onClick=${() => setSel(f)}>${f.split('/').slice(-1)[0]}<small class="mono">${f.split('/').slice(0, -1).join('/')}</small></button>`)}</div>` : null}
      <div class="grow"><${FileEditor} key=${sel} path=${sel} intro=${intro} /></div></div>`;
  };
  /** text the brief adds (instructions) or swaps in (a method) — edited as plain text, saved to the draft */
  const LayerText = ({ path, kind, name, placeholder, hint, rows, onSaved, saveLabel }) => {
    const [cur, setCur] = useState(null);
    const [t, setT] = useState('');
    const load = () => getFile(path).then(x => { const v = stripFm(x && x.text); setCur(v); setT(v); });
    useEffect(() => { load(); }, [path]);
    if (cur == null) return html`<${NL.Spinner} />`;
    const save = async text => { const r = await edit({ op: 'instructions', kind, name, text }, text.trim() ? 'Saved to the draft' : 'Removed in the draft'); if (r.ok) { await load(); onSaved && onSaved(text); } };
    return html`<div class="wf-editor">
      <${NL.Textarea} value=${t} rows=${rows || 9} onInput=${setT} placeholder=${placeholder} mono onSubmit=${() => save(t)} />
      ${hint ? html`<div class="field-hint">${hint}</div>` : null}
      <div class="row end">${cur ? html`<${NL.Btn} small kind="ghost" onClick=${() => save('')}>Remove</${NL.Btn}>` : null}
        <${NL.Btn} small kind="primary" disabled=${t.trim() === cur} onClick=${() => save(t)}>${saveLabel || 'Save to draft'}</${NL.Btn}></div></div>`;
  };
  const useTab = (query, first) => {
    const [t, setT] = useState((query && query.tab) || first);
    useEffect(() => { if (query && query.tab) setT(query.tab); }, [query && query.tab]);
    return [t, setT];
  };

  /* ── procedures ───────────────────────────────────────────────────────────── */
  const GROUPS = [['stage', 'Stage procedures', 'Each does the work of a stage.'], ['driver', 'Drivers', 'Carry studies through several steps on their own.'],
    ['entry', 'Ways in', 'Start something new.'], ['utility', 'Utilities', 'Everything else agents can be asked to do.']];
  const ProcRow = ({ d, name, p }) => {
    const cu = (d.custom.procedures || {})[name] || {};
    return html`<a class="cmp-row" href=${href('procedure', name)}>
      <div class="cmp-row-main"><div class="row"><b>${p.title}</b><span class="mono muted small">/${name}</span>${touched(d, `.claude/skills/${name}/`, `lab/workflow/${name}.`) ? html`<i class="cmp-dot" title="changed in your draft"></i>` : null}</div>
        <div class="muted small clip">${p.does || p.description}</div></div>
      <div class="cmp-row-side">${(p.stages || []).map(s => html`<span class="chip">${((d.stages.find(x => x.id === s)) || {}).title || s}</span>`)}
        ${cu.method ? html`<span class="pill pill-ask">method replaced</span>` : null}${cu.add ? html`<span class="pill pill-state">+ instructions</span>` : null}
        ${p.origin === 'yours' ? html`<${Origin} o="yours" like=${p.like} />` : null}</div></a>`;
  };
  const ProceduresList = ({ d, k }) => {
    const [q, setQ] = useState('');
    const all = Object.entries(d.procedures).filter(([n, p]) => !q || `${n} ${p.title} ${p.does} ${p.description}`.toLowerCase().includes(q.toLowerCase()));
    const eng = all.filter(([, p]) => p.engineering);
    return html`<div class="cmp-page"><${ListHead} k=${k}><input class="input search" placeholder="Find a procedure…" value=${q} onInput=${e => setQ(e.target.value)} /></${ListHead}>
      ${GROUPS.map(([kind, title, sub]) => { const xs = all.filter(([, p]) => !p.engineering && (p.kind || 'utility') === kind); return xs.length ? html`
        <section class="cmp-sec"><div class="cmp-sec-h"><h2>${title}</h2><span class="muted small grow">${sub}</span><span class="cmp-n">${xs.length}</span></div>
          <div class="cmp-rows">${xs.map(([n, p]) => html`<${ProcRow} key=${n} d=${d} name=${n} p=${p} />`)}</div></section>` : null; })}
      ${eng.length ? html`<details class="cmp-sec more"><summary>Engineering helpers <span class="cmp-n">${eng.length}</span></summary><div class="cmp-rows">${eng.map(([n, p]) => html`<${ProcRow} key=${n} d=${d} name=${n} p=${p} />`)}</div></details>` : null}
    </div>`;
  };

  const ProcedureEditor = ({ d, name, query }) => {
    const p = d.procedures[name];
    const [tab, setTab] = useTab(query, 'about');
    if (!p) return html`<${Missing} k=${KIND_OF.procedure} name=${name} />`;
    const cu = (d.custom.procedures || {})[name] || {};
    const canMethod = p.replaceable || p.has_method;
    const tabs = [{ id: 'about', label: 'About' }, ...(canMethod ? [{ id: 'method', label: 'Method' }] : []), { id: 'instructions', label: 'Your instructions' }, { id: 'files', label: 'Files', count: p.files.length }];
    return html`<div class="cmp-page">
      <${ItemHead} k=${KIND_OF.procedure} name=${'/' + name} title=${p.title} sub=${p.does}
        chips=${html`<${Origin} o=${p.origin} like=${p.like} />${cu.method ? html`<span class="pill pill-ask">method replaced</span>` : null}${cu.add ? html`<span class="pill pill-state">+ your instructions</span>` : null}${cu.stale ? html`<span class="pill pill-warn" title="the default method changed after you replaced it">default changed</span>` : null}`}
        actions=${html`<${CopyBtn} kind="procedure" like=${name} /><${DeleteBtn} kind="procedure" name=${name} label=${'/' + name} body=${'Its folder is removed in your draft, and it leaves every stage. If anything still names it, Review will say so before you publish.'} />`} />
      <${NL.Tabs} tabs=${tabs} value=${tab} onChange=${setTab} />
      <div class="tabpane">
        ${tab === 'about' ? html`<${ProcAbout} key=${JSON.stringify(p)} d=${d} name=${name} p=${p} />` : null}
        ${tab === 'method' ? html`<${MethodTab} d=${d} name=${name} p=${p} />` : null}
        ${tab === 'instructions' ? html`<div class="cmp-narrow"><p class="muted">Added to <b>${p.title}</b> every time it runs, anywhere in the lab — on top of its method. Write what you'd tell a new lab member: preferences, must-dos, datasets or tools to use, things to avoid.</p>
          <${LayerText} path=${`lab/workflow/${name}.add.md`} kind="add" name=${name} placeholder=${'e.g.\n- Always compare against the strongest 2024 baseline.\n- Never use dataset X (license).'} /></div>` : null}
        ${tab === 'files' ? html`<${FilesTab} files=${p.files} intro="SKILL.md is the contract every run follows: its steps, checks, gates and stop points. Its first block (between the --- lines) is the procedure's definition; the generated part refreshes itself." />` : null}
      </div></div>`;
  };

  const ICONS_START = ['▸', '✦', '◫', '⟳', '✎', '⌕', '☰', '◎', '△', '❖'];
  const ProcAbout = ({ d, name, p }) => {
    const init = { title: p.title || '', does: p.does || '', description: p.description || '', stops: p.stops || '', kind: p.kind, level: p.level, mode: p.mode,
      args: p.args || '', hint: p.hint || '', launchable: !!p.launchable, replaceable: !!p.replaceable, start: p.start || null };
    const [f, setF] = useState(init);
    const [stages, setStages] = useState(p.stages || []);
    const set = (k, v) => setF(o => ({ ...o, [k]: v }));
    const fields = Object.fromEntries(Object.entries(f).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(init[k])));
    const stDirty = JSON.stringify(stages) !== JSON.stringify(p.stages || []);
    const dirty = Object.keys(fields).length || stDirty;
    const from = k => p.like && !(p.own || []).includes(k) ? html`<span class="muted">from /${p.like}</span>` : null;
    const save = () => edit({ op: 'procedure', name, fields, ...(stDirty ? { stages } : {}) }, 'Saved to the draft');
    return html`<div class="cmp-form">
      <div class="grid2"><${NL.Field} label="Title" hint=${from('title')}><${NL.Input} value=${f.title} onInput=${v => set('title', v)} /></${NL.Field}>
        <${NL.Field} label="When it stops" hint=${from('stops') || 'e.g. “with the verdict”'}><${NL.Input} value=${f.stops} onInput=${v => set('stops', v)} /></${NL.Field}></div>
      <${NL.Field} label="What it does — one line" hint="shown on buttons and lists"><${NL.Input} value=${f.does} onInput=${v => set('does', v)} /></${NL.Field}>
      <${NL.Field} label="Description for agents" hint="agent CLIs read this to know when the skill applies"><${NL.Textarea} rows=${3} value=${f.description} onInput=${v => set('description', v)} /></${NL.Field}>
      <${NL.Field} label="Stages it serves"><div class="row">${d.stages.map(st => html`<button type="button" class=${cls('chip', 'click', stages.includes(st.id) && 'on')}
        onClick=${() => setStages(xs => xs.includes(st.id) ? xs.filter(x => x !== st.id) : [...xs, st.id])}>${st.title}</button>`)}</div></${NL.Field}>
      <${NL.Toggle} on=${!!f.start} onChange=${v => set('start', v ? { icon: '▸', order: 50, ...(p.start || {}) } : null)} label="Offer it in Start something" sub="a button in the launcher on Home" />
      ${f.start ? html`<div class="grid3"><${NL.Field} label="Icon"><div class="row">${ICONS_START.map(i => html`<button type="button" class=${cls('chip', 'click', f.start.icon === i && 'on')} onClick=${() => set('start', { ...f.start, icon: i })}>${i}</button>`)}</div></${NL.Field}>
        <${NL.Field} label="Its label there" hint="blank = the title"><${NL.Input} value=${f.start.title || ''} onInput=${v => set('start', { ...f.start, title: v || undefined })} /></${NL.Field}>
        <${NL.Field} label="Position" hint="lower comes first"><${NL.Input} type="number" value=${f.start.order ?? 50} onInput=${v => set('start', { ...f.start, order: +v })} /></${NL.Field}></div>` : null}
      <details class="more"><summary>How it runs</summary><div class="grid2">
        <${NL.Field} label="Kind" hint=${from('kind')}><${NL.Select} value=${f.kind} onChange=${v => set('kind', v)} options=${[{ value: 'stage', label: 'Stage — does a stage’s work' }, { value: 'driver', label: 'Driver — runs several steps' }, { value: 'entry', label: 'Way in — starts something new' }, { value: 'utility', label: 'Utility' }]} /></${NL.Field}>
        <${NL.Field} label="Runs in" hint=${from('level')}><${NL.Select} value=${f.level} onChange=${v => set('level', v)} options=${[{ value: 'hub', label: 'the lab' }, { value: 'project', label: 'a study’s project repo' }]} /></${NL.Field}>
        <${NL.Field} label="Talks with you?" hint=${from('mode')}><${NL.Select} value=${f.mode} onChange=${v => set('mode', v)} options=${[{ value: 'headless', label: 'No — it works on its own' }, { value: 'interactive', label: 'Yes — it asks you questions' }]} /></${NL.Field}>
        <${NL.Field} label="Arguments" hint=${from('args') || 'slug = a study · text = free text · ? = optional'}><${NL.Input} mono value=${f.args} onInput=${v => set('args', v)} /></${NL.Field}>
      </div>
      <${NL.Toggle} on=${f.launchable} onChange=${v => set('launchable', v)} label="Can be started from the dashboard" sub=${name === 'finalize' ? 'never: Gate 3 is the only way in' : 'otherwise only another procedure or an agent runs it'} />
      <${NL.Toggle} on=${f.replaceable} onChange=${v => set('replaceable', v)} label="Its method can be replaced" sub="needs a METHOD.md beside it, and a brief step in its contract" /></details>
      <div class="row end sticky-save">${dirty ? html`<span class="muted small">unsaved</span><${NL.Btn} small kind="ghost" onClick=${() => { setF(init); setStages(p.stages || []); }}>Cancel</${NL.Btn}>` : null}
        <${NL.Btn} kind="primary" disabled=${!dirty} onClick=${save}>Save to draft</${NL.Btn}></div></div>`;
  };

  const MethodTab = ({ d, name, p }) => {
    const yours = p.origin === 'yours';
    const cu = (d.custom.procedures || {})[name] || {};
    const [def, setDef] = useState(null);
    const [rep, setRep] = useState(null);
    const [mode, setMode] = useState('read');
    const [view, setView] = useState('text');
    const load = () => Promise.all([getFile(`.claude/skills/${name}/METHOD.md`), getFile(`lab/workflow/${name}.method.md`)])
      .then(([a, b]) => { setDef((a && a.text) || ''); setRep(stripFm(b && b.text)); });
    useEffect(() => { load(); }, [name]);
    if (def == null) return html`<${NL.Spinner} />`;
    if (yours) return html`<div><p class="muted">How the work is done — this procedure is yours, so its method is its own file. Its contract (in Files) still binds whatever this says.</p>
      <${FileEditor} path=${`.claude/skills/${name}/METHOD.md`} onSaved=${() => Tour.event('method')} /></div>`;
    if (!p.replaceable) return html`<div class="note">This procedure is all contract: what it does is written in its SKILL.md (Files). You can still add your own instructions.</div>`;
    if (mode === 'edit') return html`<div><p class="muted">Write the method the way you want this step done. The contract still holds, and the brief lists what the step must still produce.</p>
      <${LayerText} path=${`lab/workflow/${name}.method.md`} kind="method" name=${name} rows=${24} saveLabel="Save the method to draft"
        onSaved=${() => { setMode('read'); load(); Tour.event('method'); }} />
      <div class="row"><button type="button" class="link small" onClick=${() => setMode('read')}>← back</button></div></div>`;
    const startEdit = async () => { if (!rep) await edit({ op: 'instructions', kind: 'method', name, text: def || ' ' }, false); setMode('edit'); };
    return html`<div>
      <div class="row between"><p class="muted">${rep ? html`<b>Your method</b> replaces the default for the whole lab.` : html`The <b>default method</b> that ships with the lab.`}</p>
        ${rep ? html`<${NL.Seg} value=${view} onChange=${setView} options=${[{ value: 'text', label: 'Yours' }, { value: 'diff', label: 'Compare with the default' }]} />` : null}</div>
      ${cu.stale ? html`<div class="note note-warn">The default changed after you replaced it — compare them and decide whether to keep yours.</div>` : null}
      ${view === 'diff' && rep ? html`<${NL.Diff} a=${def} b=${rep} context=${4} />` : html`<div class="wf-method"><${NL.Markdown} text=${rep || def || '_(empty)_'} /></div>`}
      <div class="row end">${rep ? html`<${NL.Btn} small kind="ghost" onClick=${async () => { await edit({ op: 'instructions', kind: 'method', name, text: '' }, 'Back to the default (in the draft)'); load(); }}>Use the default</${NL.Btn}>` : null}
        <${NL.Btn} small kind=${rep ? '' : 'primary'} onClick=${startEdit}>${rep ? 'Edit your method' : 'Rewrite the method…'}</${NL.Btn}></div></div>`;
  };

  /* ── stages ───────────────────────────────────────────────────────────────── */
  const StagesList = ({ d, k }) => {
    const { after, inside } = gatesBetween(d);
    return html`<div class="cmp-page"><${ListHead} k=${k}><${NL.Btn} kind="primary" onClick=${() => NL.open(StageAddDialog, {}, { kind: 'dialog' })}><${NL.Icon} name="plus" /> New stage</${NL.Btn}></${ListHead}>
      <div class="cmp-rows">${d.stages.map((st, i) => html`<a class="cmp-row" href=${href('stage', st.id)}>
        <span class="cmp-num">${String(i + 1).padStart(2, '0')}</span>
        <div class="cmp-row-main"><b>${st.title}</b><div class="muted small">${(st.states || []).map(s => stateLabel(d, s)).join(' · ') || 'no states'}</div></div>
        <div class="cmp-row-side">${(st.procedures || []).map(p => html`<span class="chip">${(d.procedures[p] || {}).title || p}</span>`)}
          ${inside[st.id] ? html`<span class="pill pill-gate"><${NL.Icon} name="lock" /> Gate ${inside[st.id].n}</span>` : null}
          ${after[st.id] ? html`<span class="pill pill-gate"><${NL.Icon} name="lock" /> then Gate ${after[st.id].n}</span>` : null}</div></a>`)}</div>
      <p class="muted small cmp-foot">Under the hood: <a class="link" href=${href('stage', '_file')}>workflow/stages.yaml</a> — every table there is editable as text too.</p></div>`;
  };

  const StageEditor = ({ d, name, query }) => {
    const [tab, setTab] = useTab(query, 'about');
    if (name === '_file') return html`<div class="cmp-page"><${ItemHead} k=${KIND_OF.stage} name="stages.yaml" title="The workflow, as text" sub="States, stages, rooms, gates and what each state offers — the forms edit this same file." />
      <${FileEditor} path="workflow/stages.yaml" rows=${32} /></div>`;
    const st = d.stages.find(x => x.id === name);
    if (!st) return html`<${Missing} k=${KIND_OF.stage} name=${name} />`;
    const gates = (d.gates || []).filter(g => (st.states || []).includes(g.at));
    return html`<div class="cmp-page">
      <${ItemHead} k=${KIND_OF.stage} name=${name} title=${st.title} sub=${(st.states || []).map(s => stateLabel(d, s)).join(' → ')}
        actions=${gates.length ? null : html`<${DeleteBtn} kind="stage" name=${name} label=${'the stage ' + st.title} body=${`The stage and its states (${(st.states || []).join(', ') || 'none'}) are removed in your draft. Studies in those states would be stranded — Review checks that before you publish.`} />`} />
      <${NL.Tabs} tabs=${[{ id: 'about', label: 'About' }, { id: 'instructions', label: 'Your instructions' }]} value=${tab} onChange=${setTab} />
      <div class="tabpane">${tab === 'about' ? html`<${StageAbout} key=${JSON.stringify(st)} d=${d} st=${st} gates=${gates} />` : html`<div class="cmp-narrow">
        <p class="muted">Added to every procedure of ${st.title.toLowerCase()}, wherever it runs.</p>
        <${LayerText} path=${`lab/workflow/stage.${name}.add.md`} kind="stage" name=${name} rows=${6} placeholder="e.g. Keep every run in this stage under 2 GPU-hours." /></div>`}</div></div>`;
  };
  const StageAbout = ({ d, st, gates }) => {
    const [title, setTitle] = useState(st.title);
    const [procs, setProcs] = useState(st.procedures || []);
    const [add, setAdd] = useState('');
    const dirty = title !== st.title || JSON.stringify(procs) !== JSON.stringify(st.procedures || []);
    const move = (i, dlt) => setProcs(xs => { const a = xs.slice(); const j = i + dlt; if (j < 0 || j >= a.length) return a; [a[i], a[j]] = [a[j], a[i]]; return a; });
    const others = Object.keys(d.procedures).filter(p => !procs.includes(p));
    return html`<div class="cmp-form">
      <${NL.Field} label="Title"><${NL.Input} value=${title} onInput=${setTitle} /></${NL.Field}>
      <${NL.Field} label="Its procedures" hint="the first is the stage's main one"><div class="cmp-list">${procs.map((p, i) => html`<div class="cmp-li">
          <span class="cmp-num">${i + 1}</span><a class="grow" href=${href('procedure', p)}><b>${(d.procedures[p] || {}).title || p}</b> <span class="mono muted small">/${p}</span></a>
          <button type="button" class="iconbtn sm" title="up" disabled=${!i} onClick=${() => move(i, -1)}><${NL.Icon} name="up" /></button>
          <button type="button" class="iconbtn sm" title="down" disabled=${i === procs.length - 1} onClick=${() => move(i, 1)}><${NL.Icon} name="down" /></button>
          <button type="button" class="iconbtn sm" title="take it out of this stage" onClick=${() => setProcs(xs => xs.filter(x => x !== p))}><${NL.Icon} name="x" /></button></div>`)}
        <div class="row"><${NL.Select} value=${add} onChange=${setAdd} options=${[{ value: '', label: 'Add a procedure…' }, ...others.map(p => ({ value: p, label: `${(d.procedures[p] || {}).title} (/${p})` }))]} />
          <${NL.Btn} small disabled=${!add} onClick=${() => { setProcs(xs => [...xs, add]); setAdd(''); }}>Add</${NL.Btn}></div></div></${NL.Field}>
      <div class="row end"><${NL.Btn} kind="primary" disabled=${!dirty} onClick=${() => edit({ op: 'stage', id: st.id, fields: { title, procedures: procs } }, 'Saved to the draft')}>Save to draft</${NL.Btn}></div>
      <${NL.Section} title="Its states">${(st.states || []).map(s => html`<${StateRow} key=${s} d=${d} id=${s} />`)}</${NL.Section}>
      ${gates.map(g => html`<div class="cmp-lock"><${NL.Icon} name="lock" /><div><b>${g.title}</b><div class="muted small">${g.means} — signed at ${stateLabel(d, g.at)}. The three gates are fixed: no customisation moves one.</div></div></div>`)}
    </div>`;
  };
  const StateRow = ({ d, id }) => {
    const s = (d.states || []).concat(d.side_states || []).find(x => x.id === id) || {};
    const [label, setLabel] = useState(s.label || id);
    const n = (d.studies_in || {})[id] || 0;
    return html`<div class="cmp-li"><span class="mono muted small cmp-state-id">${id}</span>
      <input class="input grow" value=${label} onInput=${e => setLabel(e.target.value)} aria-label="label" />
      <${NL.Select} value=${s.room} onChange=${room => edit({ op: 'state', id, fields: { room } }, `${label} now stands in ${room}`)} options=${d.rooms.map(r => ({ value: r.id, label: 'in ' + (r.title || r.label) }))} />
      ${n ? html`<span class="cmp-n" title="studies in this state now">${n}</span>` : null}
      ${label !== (s.label || id) ? html`<${NL.Btn} small kind="primary" onClick=${() => edit({ op: 'state', id, fields: { label } }, 'Saved to the draft')}>Save</${NL.Btn}>` : null}</div>`;
  };
  const StageAddDialog = ({ onClose }) => {
    const d = C.d;
    const [title, setTitle] = useState('');
    const [id, setId] = useState('');
    const [after, setAfter] = useState((d.stages.slice(-2)[0] || {}).id || '');
    const [room, setRoom] = useState((d.rooms[0] || {}).id || '');
    const sid = id || slugify(title);
    const go2 = async () => { const r = await edit({ op: 'stage-add', id: sid, title, after, room, state: sid, state_label: title }, `Added the stage ${title} to your draft`); if (r.ok) { onClose(); go('stage', sid); } };
    return html`<div class="dialog dialog-wide"><h3>A new stage</h3>
      <p class="muted small">A stage is a step every study passes through, with a state of its own. Studies reach it in order; give it procedures to run once it exists.</p>
      <div class="grid2"><${NL.Field} label="Its name"><${NL.Input} value=${title} onInput=${setTitle} autofocus placeholder="e.g. Replication" /></${NL.Field}>
        <${NL.Field} label="Its id" hint="lower-case, dashes"><${NL.Input} mono value=${sid} onInput=${setId} /></${NL.Field}>
        <${NL.Field} label="Comes after"><${NL.Select} value=${after} onChange=${setAfter} options=${d.stages.map(s => ({ value: s.id, label: s.title }))} /></${NL.Field}>
        <${NL.Field} label="Happens in the room"><${NL.Select} value=${room} onChange=${setRoom} options=${d.rooms.map(r => ({ value: r.id, label: r.title || r.label }))} /></${NL.Field}></div>
      <div class="dialog-actions"><${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!title.trim() || !sid} onClick=${go2}>Add the stage</${NL.Btn}></div></div>`;
  };

  /* ── rooms ────────────────────────────────────────────────────────────────── */
  const RoomsList = ({ d, k }) => html`<div class="cmp-page"><${ListHead} k=${k} />
    <${Building} d=${d} />
    <p class="muted small cmp-foot">A room with no art of its own is drawn plain. Art is a small script — start one from any room's art, then shape it.</p></div>`;

  const RoomEditor = ({ d, name, query }) => {
    const [tab, setTab] = useTab(query, 'about');
    const r = d.rooms.find(x => x.id === name);
    if (!r) return html`<${Missing} k=${KIND_OF.room} name=${name} />`;
    return html`<div class="cmp-page">
      <${ItemHead} k=${KIND_OF.room} name=${name} title=${r.title || r.label} sub=${`${FLOOR(r.floor ?? 0)} · ${r.art === 'plain' ? 'drawn plain' : r.art === 'yours' ? 'its own art' : 'built-in art'}`}
        actions=${html`<${CopyBtn} kind="room" like=${name} />${!r.gate ? html`<${NL.Btn} small kind="ghost" onClick=${() => NL.open(RoomRemoveDialog, { r }, { kind: 'dialog' })}><${NL.Icon} name="trash" /> Remove</${NL.Btn}>` : null}`} />
      <${NL.Tabs} tabs=${[{ id: 'about', label: 'About' }, { id: 'art', label: 'Art' }]} value=${tab} onChange=${setTab} />
      <div class="tabpane">${tab === 'about' ? html`<${RoomAbout} key=${JSON.stringify(r)} d=${d} r=${r} />` : html`<${RoomArt} d=${d} r=${r} />`}</div></div>`;
  };
  const RoomAbout = ({ d, r }) => {
    const init = { label: r.label || '', title: r.title || '', floor: r.floor ?? 0, order: r.order ?? 1 };
    const [f, setF] = useState(init);
    const [pick, setPick] = useState('');
    const set = (k, v) => setF(o => ({ ...o, [k]: v }));
    const dirty = JSON.stringify(f) !== JSON.stringify(init);
    const here = r.states || [];
    const elsewhere = (d.states || []).concat(d.side_states || []).filter(s => !here.includes(s.id));
    return html`<div class="cmp-form">
      <div class="grid2"><${NL.Field} label="Its sign" hint="the name on the building"><${NL.Input} value=${f.title} onInput=${v => set('title', v)} /></${NL.Field}>
        <${NL.Field} label="Short name" hint="the column on the Studies board"><${NL.Input} value=${f.label} onInput=${v => set('label', v)} /></${NL.Field}>
        <${NL.Field} label="Floor"><${NL.Select} value=${String(f.floor)} onChange=${v => set('floor', +v)} options=${[2, 1, 0, -1].map(x => ({ value: String(x), label: FLOOR(x) }))} /></${NL.Field}>
        <${NL.Field} label="Position on the floor" hint="1 = leftmost"><${NL.Input} type="number" min="1" value=${f.order} onInput=${v => set('order', +v)} /></${NL.Field}></div>
      <div class="row end"><${NL.Btn} kind="primary" disabled=${!dirty} onClick=${() => edit({ op: 'room', id: r.id, fields: f }, 'Saved to the draft')}>Save to draft</${NL.Btn}></div>
      <${NL.Section} title="What stands here">${here.length ? here.map(s => html`<${StateRow} key=${s} d=${d} id=${s} />`) : html`<div class="muted small">No state stands here yet.</div>`}
        <div class="row"><${NL.Select} value=${pick} onChange=${setPick} options=${[{ value: '', label: 'Move a state here…' }, ...elsewhere.map(s => ({ value: s.id, label: `${s.label} (now in ${s.room})` }))]} />
          <${NL.Btn} small disabled=${!pick} onClick=${async () => { await edit({ op: 'state', id: pick, fields: { room: r.id } }); setPick(''); }}>Move</${NL.Btn}></div></${NL.Section}>
      ${r.gate ? html`<div class="cmp-lock"><${NL.Icon} name="lock" /><div><b>Gate ${r.gate} is signed in this room</b><div class="muted small">A room with a gate stays.</div></div></div>` : null}</div>`;
  };
  const RoomArt = ({ d, r }) => {
    const [from, setFrom] = useState(d.built_in_art.includes(r.id) ? r.id : d.built_in_art[0] || '');
    if (r.art === 'yours') return html`<div><${FileEditor} path=${`lab/rooms/${r.id}.js`} rows=${28} intro="The room's art: a small script for the world on Home (its shapes, stations and props — see docs/world-design.md). It shows after you publish." />
      <div class="row end"><button type="button" class="link small danger" onClick=${async () => { if (await NL.confirm({ title: 'Remove this art?', ok: 'Remove', body: d.built_in_art.includes(r.id) ? 'The room goes back to its built-in art.' : 'The room is drawn plain.' })) edit({ op: 'write', path: `lab/rooms/${r.id}.js`, text: null }); }}>Remove the lab's art</button></div></div>`;
    return html`<div class="cmp-narrow">
      <p class="lede">${r.art === 'built-in' ? 'This room uses the art it ships with.' : 'This room is drawn plain — walls, a sign and a door.'}</p>
      <p class="muted">To shape it, give it art of its own, starting from any room's.</p>
      <div class="row"><${NL.Select} value=${from} onChange=${setFrom} options=${d.built_in_art.map(a => ({ value: a, label: `Start from ${a === r.id ? 'its own art' : 'the art of ' + a}` }))} />
        <${NL.Btn} kind="primary" disabled=${!from} onClick=${() => edit({ op: 'room-art', id: r.id, from })}>Make it the lab's own</${NL.Btn}></div></div>`;
  };
  const RoomRemoveDialog = ({ r, onClose }) => {
    const d = C.d;
    const others = d.rooms.filter(x => x.id !== r.id);
    const [to, setTo] = useState((others[0] || {}).id || '');
    return html`<div class="dialog"><h3>Remove ${r.title || r.label}?</h3>
      ${(r.states || []).length ? html`<${NL.Field} label=${`Its states (${r.states.map(s => stateLabel(d, s)).join(', ')}) move to`}><${NL.Select} value=${to} onChange=${setTo} options=${others.map(x => ({ value: x.id, label: x.title || x.label }))} /></${NL.Field}>` : html`<p class="muted">Nothing stands in it.</p>`}
      <div class="dialog-actions"><${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="danger" onClick=${async () => { const x = await edit({ op: 'delete', kind: 'room', name: r.id, move_to: to }); if (x.ok) { onClose(); go('rooms'); } }}>Remove it</${NL.Btn}></div></div>`;
  };

  /* ── roles ────────────────────────────────────────────────────────────────── */
  const RolesList = ({ d, k }) => html`<div class="cmp-page"><${ListHead} k=${k} />
    <div class="cmp-rows">${d.roles.map(r => html`<a class="cmp-row" href=${href('role', r.name)}><${NL.RoleDot} role=${r.name} />
      <div class="cmp-row-main"><div class="row"><b>${r.label}</b><span class="mono muted small">${r.name}</span>${touched(d, `agent-roles/${r.name}.`, `lab/workflow/roles/${r.name}.`) ? html`<i class="cmp-dot"></i>` : null}</div><div class="muted small clip">${r.description}</div></div>
      <div class="cmp-row-side">${(d.custom.roles || {})[r.name] ? html`<span class="pill pill-state">+ instructions</span>` : null}${r.origin === 'yours' ? html`<${Origin} o="yours" like=${r.like} />` : null}</div></a>`)}</div></div>`;
  const RoleEditor = ({ d, name, query }) => {
    const [tab, setTab] = useTab(query, 'about');
    const r = d.roles.find(x => x.name === name);
    if (!r) return html`<${Missing} k=${KIND_OF.role} name=${name} />`;
    return html`<div class="cmp-page">
      <${ItemHead} k=${KIND_OF.role} name=${name} title=${r.label} sub=${r.description} chips=${html`<${Origin} o=${r.origin} like=${r.like} />`}
        actions=${html`<${CopyBtn} kind="role" like=${name} /><${DeleteBtn} kind="role" name=${name} label=${'the role ' + r.label} />`} />
      <${NL.Tabs} tabs=${[{ id: 'about', label: 'About' }, { id: 'instructions', label: 'Your instructions' }, { id: 'files', label: 'Files' }]} value=${tab} onChange=${setTab} />
      <div class="tabpane">
        ${tab === 'about' ? html`<${RoleAbout} key=${r.label + r.description} r=${r} />` : null}
        ${tab === 'instructions' ? html`<div class="cmp-narrow"><p class="muted">Added to this role's instructions for every agent CLI (Claude, Codex, opencode), wherever it is used.</p>
          <${LayerText} path=${`lab/workflow/roles/${name}.add.md`} kind="role" name=${name} placeholder="e.g. Be especially strict about leakage between train and test." /></div>` : null}
        ${tab === 'files' ? html`<${FilesTab} files=${r.files} intro="The .yaml says which tools and model it gets; the .md is what it is told. Both are rendered for every agent CLI when you publish." />` : null}
      </div></div>`;
  };
  const RoleAbout = ({ r }) => {
    const [label, setLabel] = useState(r.label);
    const [desc, setDesc] = useState(r.description);
    const dirty = label !== r.label || desc !== r.description;
    return html`<div class="cmp-form"><${NL.Field} label="Its name in the dashboard"><${NL.Input} value=${label} onInput=${setLabel} /></${NL.Field}>
      <${NL.Field} label="What it is for" hint="agents read this to decide when to call it"><${NL.Textarea} rows=${3} value=${desc} onInput=${setDesc} /></${NL.Field}>
      <div class="row end"><${NL.Btn} kind="primary" disabled=${!dirty} onClick=${() => edit({ op: 'role', name: r.name, fields: { label, description: desc } }, 'Saved to the draft')}>Save to draft</${NL.Btn}></div></div>`;
  };

  /* ── rules ────────────────────────────────────────────────────────────────── */
  const RULE_GROUPS = [['hard', 'Hard rules', 'Every agent, every session. Numbered — skills cite them by number, so new ones go at the end.'],
    ['subagent', 'Subagent rules', 'Every subagent, and every agent that starts one.'], ['project', 'Project rules', 'Every session inside a study’s project repo.']];
  const RulesPage = ({ d }) => {
    const k = KIND_OF.rule;
    const checks = [...d.built_in_checks, ...d.checks.filter(c => c.guard).map(c => c.name), ...d.checks.filter(c => !c.guard).map(c => c.file.split('/').pop().replace(/\.py$/, ''))];
    return html`<div class="cmp-page"><${ListHead} k=${k} />
      ${RULE_GROUPS.map(([g, title, sub]) => html`<section class="cmp-sec"><div class="cmp-sec-h"><h2>${title}</h2><span class="muted small grow">${sub}</span><span class="cmp-n">${(d.rules[g] || []).length}</span></div>
        ${(d.rules[g] || []).map((r, i) => html`<${RuleCard} key=${r.id + r.text} r=${r} n=${g === 'hard' ? i + 1 : null} group=${g} checks=${checks} />`)}
        <${RuleAdd} group=${g} checks=${checks} /></section>`)}
      <details class="cmp-sec more"><summary><${NL.Icon} name="lock" /> Read by the lab's safety code — fixed here</summary>
        <p class="muted small">What a headless run may never write, which settings only you change, the rigor floors no profile lowers, and the audits a delegated Gate 3 re-runs.</p>
        <pre class="plain">${Object.entries(d.locked || {}).map(([k2, v]) => `${k2}: ${JSON.stringify(v, null, 1)}`).join('\n\n')}</pre></details>
      <p class="muted small cmp-foot">Under the hood: <a class="link" href=${href('rule', '_file')}>workflow/rules.yaml</a>.</p></div>`;
  };
  const RuleCard = ({ r, n, group, checks }) => {
    const [ed, setEd] = useState(false);
    const [t, setT] = useState(r.text);
    const [cs, setCs] = useState(r.checks || []);
    if (!ed) return html`<div class="cmp-rule">${n ? html`<span class="cmp-num">${n}</span>` : null}<div class="grow"><${NL.Markdown} text=${r.text} />
        <div class="row"><span class="mono muted small">${r.id}</span>${(r.checks || []).map(c => html`<span class="chip">checked by ${c}</span>`)}</div></div>
      <div class="cmp-rule-acts"><button type="button" class="link small" onClick=${() => setEd(true)}>Edit</button>
        ${group !== 'hard' ? html`<button type="button" class="link small danger" onClick=${async () => { if (await NL.confirm({ title: `Remove the rule “${r.id}”?`, ok: 'Remove', danger: true, body: 'Removed in your draft; every manual drops it when you publish.' })) edit({ op: 'rule', id: r.id, remove: true }); }}>Remove</button>` : null}</div></div>`;
    return html`<div class="cmp-rule editing">${n ? html`<span class="cmp-num">${n}</span>` : null}<div class="grow">
      <${NL.Textarea} rows=${4} value=${t} onInput=${setT} autofocus />
      <div class="row">${checks.map(c => html`<button type="button" class=${cls('chip', 'click', cs.includes(c) && 'on')} onClick=${() => setCs(x => x.includes(c) ? x.filter(y => y !== c) : [...x, c])}>${c}</button>`)}</div>
      <div class="row end"><${NL.Btn} small kind="ghost" onClick=${() => { setEd(false); setT(r.text); setCs(r.checks || []); }}>Cancel</${NL.Btn}>
        <${NL.Btn} small kind="primary" onClick=${async () => { const x = await edit({ op: 'rule', id: r.id, text: t, checks: cs }, 'Saved to the draft'); if (x.ok) setEd(false); }}>Save to draft</${NL.Btn}></div></div></div>`;
  };
  const RuleAdd = ({ group, checks }) => {
    const [open, setOpen] = useState(false);
    const [t, setT] = useState('');
    const [id, setId] = useState('');
    const [c, setC] = useState('');
    const rid = id || slugify(t.replace(/\*\*/g, '').split(/[.!?]/)[0]).slice(0, 30);
    if (!open) return html`<button type="button" class="cmp-add" onClick=${() => setOpen(true)}><${NL.Icon} name="plus" /> Add a rule</button>`;
    return html`<div class="cmp-rule editing"><div class="grow">
      <${NL.Textarea} rows=${3} value=${t} onInput=${setT} autofocus placeholder="**Short title.** What every agent must do, in a sentence or two." />
      <div class="grid2"><${NL.Field} label="Its id"><${NL.Input} mono value=${rid} onInput=${setId} /></${NL.Field}>
        <${NL.Field} label="Checked by (optional)"><${NL.Select} value=${c} onChange=${setC} options=${[{ value: '', label: 'nothing — agents keep it' }, ...checks.map(x => ({ value: x, label: x }))]} /></${NL.Field}></div>
      <div class="row end"><${NL.Btn} small kind="ghost" onClick=${() => setOpen(false)}>Cancel</${NL.Btn}>
        <${NL.Btn} small kind="primary" disabled=${!t.trim() || !rid} onClick=${async () => { const x = await edit({ op: 'copy', kind: 'rule', name: rid, text: t, list: group, check: c }, 'Rule added to the draft'); if (x.ok) { setOpen(false); setT(''); setId(''); } }}>Add to draft</${NL.Btn}></div></div></div>`;
  };

  /* ── checks, project types, domain profiles ───────────────────────────────── */
  const checkId = c => c.file.split('/').pop().replace(/\.py$/, '');
  const ChecksList = ({ d, k }) => html`<div class="cmp-page"><${ListHead} k=${k} />
    <section class="cmp-sec"><div class="cmp-sec-h"><h2>Guard checks</h2><span class="muted small grow">Run as <span class="mono">tools/guard.py &lt;name&gt;</span> by procedures, and named by rules.</span></div>
      <div class="cmp-rows">${d.checks.filter(c => c.guard).map(c => html`<a class="cmp-row" href=${href('check', checkId(c))}><div class="cmp-row-main"><b class="mono">${c.name}</b><div class="muted small clip">${c.doc}</div></div>${c.origin === 'yours' ? html`<${Origin} o="yours" />` : null}</a>`)}</div></section>
    <section class="cmp-sec"><div class="cmp-sec-h"><h2>Paper audits</h2><span class="muted small grow">Re-run on every paper before Gate 3.</span></div>
      <div class="cmp-rows">${d.checks.filter(c => !c.guard).map(c => html`<a class="cmp-row" href=${href('check', checkId(c))}><div class="cmp-row-main"><b class="mono">${checkId(c)}</b><div class="muted small clip">${c.doc}</div></div></a>`)}</div></section>
    <p class="muted small cmp-foot">Built into the guard: ${d.built_in_checks.map(c => html`<span class="chip mono">${c}</span> `)}</p></div>`;
  const CheckEditor = ({ d, name }) => {
    const c = d.checks.find(x => checkId(x) === name);
    if (!c) return html`<${Missing} k=${KIND_OF.check} name=${name} />`;
    return html`<div class="cmp-page"><${ItemHead} k=${KIND_OF.check} name=${c.name} title=${c.name} sub=${c.doc} chips=${html`<${Origin} o=${c.origin} />`}
      actions=${html`${c.guard ? html`<${CopyBtn} kind="check" like=${c.name} />` : null}<${DeleteBtn} kind="check" name=${name.replace(/_/g, '-')} label=${'the check ' + c.name} />`} />
      <${FileEditor} path=${c.file} rows=${30} intro="Python, run by the guard. NAME is how rules and procedures call it; run(args, guard) returns the problems it finds." /></div>`;
  };
  const TypesList = ({ d, k }) => html`<div class="cmp-page"><${ListHead} k=${k} />
    <div class="cmp-rows">${d.types.map(t => html`<a class="cmp-row" href=${href('type', t.name)}><div class="cmp-row-main"><b>${t.name}</b><div class="muted small clip">${t.title}</div></div>${t.origin === 'yours' ? html`<${Origin} o="yours" />` : null}</a>`)}</div>
    ${d.domains.length ? html`<section class="cmp-sec"><div class="cmp-sec-h"><h2>Domain profiles</h2><span class="muted small grow">Field conventions a study can adopt.</span></div>
      <div class="cmp-rows">${d.domains.filter(x => x.file).map(x => html`<a class="cmp-row" href=${href('domain', x.name)}><div class="cmp-row-main"><b>${x.name}</b><div class="mono muted small">${x.file}</div></div></a>`)}</div></section>` : null}</div>`;
  const TypeEditor = ({ d, name }) => {
    const t = d.types.find(x => x.name === name);
    if (!t) return html`<${Missing} k=${KIND_OF.type} name=${name} />`;
    return html`<div class="cmp-page"><${ItemHead} k=${KIND_OF.type} name=${name} title=${name} sub=${t.title} chips=${html`<${Origin} o=${t.origin} />`}
      actions=${html`<${CopyBtn} kind="type" like=${name} />${t.origin === 'yours' ? html`<${DeleteBtn} kind="type" name=${name} label=${'the project type ' + name} />` : null}`} />
      <${FilesTab} files=${t.files} intro="TYPE.md is what every agent in a project of this type reads first." /></div>`;
  };
  const DomainEditor = ({ d, name }) => {
    const x = d.domains.find(y => y.name === name);
    if (!x || !x.file) return html`<${Missing} k=${KIND_OF.type} name=${name} />`;
    return html`<div class="cmp-page"><${ItemHead} k=${KIND_OF.type} name=${name} title=${name} sub="A domain profile" /><${FileEditor} path=${x.file} /></div>`;
  };

  const Missing = ({ k, name }) => html`<div class="cmp-page"><${NL.Empty} title="Not in this lab">There is no ${k.one} called <span class="mono">${name}</span>${(C.d && C.d.draft && C.d.draft.active) ? ' in your draft' : ''}. <a class="link" href=${href(k.id)}>All ${k.label.toLowerCase()}</a></${NL.Empty}></div>`;

  /* ── suggestions and history ──────────────────────────────────────────────── */
  const Suggestions = ({ d }) => html`<div class="cmp-page"><header class="cmp-head"><div class="grow"><a class="kicker" href="#/compose">Compose</a><h1>Agents’ suggestions</h1>
      <p class="lede">Agents can't change how the lab works. When one thinks a procedure, a stage or a role should, it files a suggestion — you accept or decline it here.</p></div></header>
    ${(d.proposals || []).length ? html`<div class="cmp-rows">${d.proposals.map(p => html`<button type="button" class="cmp-row" onClick=${() => NL.open(NL.ProposalSheet, { id: p.id, onClose: reload })}>
      <div class="cmp-row-main"><b>${p.kind === 'replace' || p.kind === 'method' ? 'A new method for' : 'Instructions for'} ${p.kind === 'stage' ? 'the stage ' : p.kind === 'role' ? 'the role ' : '/'}${p.name}</b>
        <div class="muted small clip">${p.why || ''}</div></div><div class="cmp-row-side"><span class="muted small">${p.study ? 'for ' + p.study : 'lab-wide'} · ${NL.ago(p.ts)}</span></div></button>`)}</div>`
      : html`<${NL.Empty} title="Nothing to review">When an agent suggests a change, it waits here.</${NL.Empty}>`}</div>`;
  const History = ({ d }) => {
    const latest = (d.history || []).find(h => !h.undone);
    return html`<div class="cmp-page"><header class="cmp-head"><div class="grow"><a class="kicker" href="#/compose">Compose</a><h1>Published</h1>
      <p class="lede">Every change you published, newest first. The latest can be undone.</p></div></header>
      ${(d.history || []).length ? html`<div class="cmp-rows">${d.history.map(h => html`<div class=${cls('cmp-row', h.undone && 'undone')}>
        <div class="cmp-row-main"><div class="row"><b>${h.note || NL.plural(h.n, 'change')}</b>${h.undone ? html`<span class="pill">undone</span>` : null}</div>
          <div class="mono muted small clip">${(h.files || []).join(' · ')}</div></div>
        <div class="cmp-row-side"><span class="mono muted small">${(h.ts || '').replace('T', ' ').slice(0, 16)}</span>
          ${latest && h.id === latest.id ? html`<${NL.Btn} small onClick=${async () => { if (await NL.confirm({ title: 'Undo this publish?', ok: 'Undo it', body: 'The files go back to how they were before it. Runs started since keep what they started with.' })) { const r = await edit({ op: 'undo', id: h.id }); if (r.ok) NL.refresh(); } }}><${NL.Icon} name="undo" /> Undo</${NL.Btn}>` : null}</div></div>`)}</div>`
        : html`<${NL.Empty} title="Nothing published yet">What you publish from a draft is listed here.</${NL.Empty}>`}</div>`;
  };

  /* ── "New …": start from a copy of the closest thing ──────────────────────── */
  const optionsFor = (d, kind) => kind === 'procedure' ? Object.entries(d.procedures).filter(([, p]) => !p.engineering).map(([n, p]) => ({ id: n, title: p.title, sub: p.does, tag: '/' + n }))
    : kind === 'room' ? d.rooms.map(r => ({ id: r.id, title: r.title || r.label, sub: (r.states || []).map(s => stateLabel(d, s)).join(' · ') }))
    : kind === 'role' ? d.roles.map(r => ({ id: r.name, title: r.label, sub: r.description }))
    : kind === 'check' ? d.checks.filter(c => c.guard).map(c => ({ id: c.name, title: c.name, sub: c.doc }))
    : kind === 'type' ? d.types.map(t => ({ id: t.name, title: t.name, sub: t.title })) : [];
  const openNew = async (kind, props) => { if (!C.d || !C.d.procedures) await reload(); NL.open(NewDialog, { kind, ...(props || {}) }, { kind: 'dialog', key: 'cmp-new' }); };
  const NewDialog = ({ kind, like: like0, title: title0, onClose }) => {
    const d = C.d;
    const opts = optionsFor(d, kind);
    const [like, setLike] = useState(like0 || (opts[0] || {}).id);
    const [q, setQ] = useState('');
    const [title, setTitle] = useState(title0 || '');
    const [name, setName] = useState('');
    const [plain, setPlain] = useState(false);
    const nm = name || slugify(title);
    const k = KIND_OF[kind];
    const list = opts.filter(o => !q || `${o.id} ${o.title} ${o.sub}`.toLowerCase().includes(q.toLowerCase()));
    const make = async () => {
      const r = await edit({ op: 'copy', kind, like, name: nm, title: title || undefined, plain }, `Made ${nm} from ${like} — now make it its own`);
      if (r.ok) { onClose(); go(kind, kind === 'check' ? nm.replace(/-/g, '_') : nm); Tour.event('copied', nm); }
    };
    return html`<div class="dialog dialog-wide cmp-new"><h3>A new ${k.one}</h3>
      <p class="muted">Start from the closest one the lab has. The copy keeps everything; you change what makes yours different.</p>
      <${NL.Field} label="Start from">${opts.length > 6 ? html`<input class="input" placeholder="Find…" value=${q} onInput=${e => setQ(e.target.value)} />` : null}
        <div class="cmp-pick">${list.map(o => html`<button type="button" class=${cls('cmp-pick-row', like === o.id && 'on')} onClick=${() => setLike(o.id)}>
          <span class="grow"><b>${o.title}</b>${o.tag ? html` <span class="mono muted small">${o.tag}</span>` : null}<small class="clip">${o.sub || ''}</small></span>${like === o.id ? html`<${NL.Icon} name="check" />` : null}</button>`)}</div></${NL.Field}>
      <div class="grid2"><${NL.Field} label=${`Name your ${k.one}`}><${NL.Input} value=${title} onInput=${setTitle} autofocus placeholder=${kind === 'procedure' ? 'e.g. Quick literature scan' : kind === 'room' ? 'e.g. The Data Room' : 'e.g. Data wrangler'} onEnter=${() => nm && like && make()} /></${NL.Field}>
        <${NL.Field} label="Its id" hint=${kind === 'procedure' ? 'agents run it as /' + (nm || 'its-id') : 'lower-case, dashes'}><${NL.Input} mono value=${nm} onInput=${setName} /></${NL.Field}></div>
      ${kind === 'room' ? html`<label class="check"><input type="checkbox" checked=${plain} onChange=${e => setPlain(e.target.checked)} /> Draw it plain (no art of its own yet)</label>` : null}
      <div class="dialog-actions"><${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!nm || !like} onClick=${make}>Make it</${NL.Btn}></div></div>`;
  };
  NL.composeNew = openNew;

  /* ── the one-minute tour (the setup wizard's last step, Home, and the nav offer it) ───────── */
  const TOUR_KEY = 'nl-compose-tour';
  const Tour = {
    get: () => NL.ls.get(TOUR_KEY, null),
    set: v => { NL.ls.set(TOUR_KEY, v); bump(); },
    start: () => { Tour.set({ step: 0 }); NL.go('compose'); },
    stop: () => Tour.set(null),
    to: step => Tour.set({ ...(Tour.get() || {}), step }),
    event: (what, data) => {
      const t = Tour.get(); if (!t) return;
      if (what === 'copied' && t.step === 1) Tour.set({ ...t, step: 2, made: data });
      else if (what === 'method' && t.step === 2) Tour.to(3);
      else if (what === 'closed' && t.step === 3) Tour.to(4);
    },
  };
  NL.composeTour = Tour.start;
  const STEPS = [
    { title: 'This is your lab, laid out', body: 'The pipeline is the steps a study moves through; the building is where each step happens on Home. Every card opens into something you can change.', cta: 'Next', act: () => Tour.to(1) },
    { title: 'Make a procedure of your own', body: 'Start from the closest one. Copy “Review the literature” into a quicker variant — the copy keeps everything else.', cta: 'Copy it for me',
      act: () => openNew('procedure', { like: 'lit-review', title: 'Quick literature scan' }) },
    { title: 'Change what makes it different', body: 'Its method is how the work gets done. Change a line — say, “skim only the ten most-cited papers” — and save it to the draft.', cta: 'Open its method',
      act: t => NL.go(`compose/procedure/${t.made}?tab=method`) },
    { title: 'Publish it — or don’t', body: 'Review shows exactly what changes, and whether the lab still reads consistently. Publish when it reads right, or discard the draft if you were only trying.', cta: 'Review the draft', act: openReview },
    { title: 'That’s the whole idea', body: 'Copy the closest thing, change what is different, publish. Stages, rooms, roles, rules, checks and project types all work this way — and agents can only suggest changes, which you accept here.', cta: 'Done', act: () => Tour.stop() },
  ];
  /** the tour's card — the app shell draws it over the Compose page */
  NL.ComposeTourCard = () => {
    const [, force] = NL.useReducer(x => x + 1, 0);
    useEffect(() => { C.listeners.add(force); return () => C.listeners.delete(force); }, []);
    const t = Tour.get();
    if (!t || !STEPS[t.step]) return null;
    const st = STEPS[t.step];
    return html`<aside class="tour" role="dialog" aria-label="tour">
      <div class="row between"><span class="kicker">Tour · ${t.step + 1} of ${STEPS.length}</span><button type="button" class="x" aria-label="end the tour" onClick=${Tour.stop}><${NL.Icon} name="x" /></button></div>
      <h3>${st.title}</h3><p>${st.body}</p>
      <div class="row between"><span class="tour-dots">${STEPS.map((_, i) => html`<i class=${cls(i === t.step && 'on', i < t.step && 'done')}></i>`)}</span>
        <${NL.Btn} small kind="primary" onClick=${() => st.act(t)}>${st.cta}</${NL.Btn}></div></aside>`;
  };
})();
