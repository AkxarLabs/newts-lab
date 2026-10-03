/* Newts' Lab — starting work. One "Start something" sheet (intents in plain words, each saying what it
   will do, where it runs and where it stops), Ask Newt (a free-form instruction), the options every
   launch shares, and the Plan-a-campaign form (writes and signs the brief). */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useMemo, cls } = NL;

  /* ── options shared by every launch ────────────────────────────────────── */
  const DEFAULT_OPTS = { backend: '', model: '', effort: '', max_minutes: '', chain: 'off', repeat_minutes: '', max_repeats: '' };
  const LaunchOptions = ({ opts, setOpts, allowChain, allowRepeat }) => {
    const s = NL.useLab();
    const x = NL.exec(s);
    const bs = NL.backends(s);
    const set = (k, v) => setOpts(o => ({ ...o, [k]: v }));
    return html`<details class="opts"><summary>Options <span class="muted">— ${opts.backend || x.backend || 'claude'}${opts.model ? ' · ' + opts.model : ''}${opts.max_minutes ? ' · ' + opts.max_minutes + ' min' : ''}${opts.chain !== 'off' ? ' · then ' + (opts.chain === 'next' ? 'the next step' : 'keep going') : ''}</span></summary>
      <div class="grid2">
        <${NL.Field} label="Agent"><${NL.Select} value=${opts.backend || x.backend || 'claude'} onChange=${v => set('backend', v)}
          options=${bs.map(b => ({ value: b.id, label: b.id + (b.found ? (b.logged_in === false ? ' (not signed in)' : '') : ' (not installed)'), disabled: !b.found }))} /></${NL.Field}>
        <${NL.Field} label="Model" hint="blank = the lab default"><${NL.Input} value=${opts.model} onInput=${v => set('model', v)} placeholder=${(x.config || {}).model || 'default'} mono /></${NL.Field}>
        <${NL.Field} label="Effort"><${NL.Select} value=${opts.effort} onChange=${v => set('effort', v)} options=${[{ value: '', label: 'default' }, 'low', 'medium', 'high', 'xhigh', 'max']} /></${NL.Field}>
        <${NL.Field} label="Time limit (minutes)" hint=${'default ' + Math.round((x.config || {}).max_minutes || 240)}><${NL.Input} type="number" min="5" value=${opts.max_minutes} onInput=${v => set('max_minutes', v)} /></${NL.Field}>
        ${allowChain ? html`<${NL.Field} label="When it finishes"><${NL.Select} value=${opts.chain} onChange=${v => set('chain', v)}
          options=${[{ value: 'off', label: 'Stop and report' }, { value: 'next', label: 'Run its reported next step' }, { value: 'loop', label: 'Keep going until a gate' }]} /></${NL.Field}>` : null}
        ${allowRepeat ? html`<${NL.Field} label="Repeat every (minutes)" hint="blank = once · stops at a gate or a failure"><${NL.Input} type="number" min="5" value=${opts.repeat_minutes} onInput=${v => set('repeat_minutes', v)} /></${NL.Field}>` : null}
        ${allowRepeat && opts.repeat_minutes ? html`<${NL.Field} label="At most (times)"><${NL.Input} type="number" min="1" value=${opts.max_repeats} onInput=${v => set('max_repeats', v)} /></${NL.Field}>` : null}
      </div></details>`;
  };
  const optBody = o => {
    const b = {};
    for (const k of ['backend', 'model', 'effort', 'max_minutes', 'repeat_minutes', 'max_repeats']) if (o[k] !== '' && o[k] != null) b[k] = o[k];
    if (o.chain && o.chain !== 'off') b.chain = o.chain;
    return b;
  };

  const StudyPicker = ({ value, onChange, filter, allowLab, label }) => {
    const s = NL.useLab();
    const items = (s.items || []).filter(filter || (() => true));
    return html`<${NL.Field} label=${label || 'Which study'}><${NL.Select} value=${value} onChange=${onChange}
      options=${[...(allowLab ? [{ value: 'hub', label: 'The whole lab' }] : [{ value: '', label: 'Choose a study…' }]),
        ...items.map(i => ({ value: i.id, label: `${i.title || i.id} · ${NL.STATE_LABEL[i.state] || i.state}` }))]} /></${NL.Field}>`;
  };

  /* ── intents ───────────────────────────────────────────────────────────── */
  const INTENTS = [
    { id: 'ideate', icon: '✦', title: 'Explore a new direction', skill: 'ideate', arg: 'text', argLabel: 'The direction', placeholder: 'e.g. sparse routing for small mixture-of-experts models' },
    { id: 'adopt', icon: '⇲', title: 'Bring in what I have', skill: 'adopt', arg: 'text', argLabel: 'What exists', placeholder: 'an idea, a design, a repo path, or a draft paper' },
    { id: 'discuss', icon: '❝', title: 'Talk it through', skill: 'discuss', arg: 'text', argLabel: 'What about', placeholder: 'direction · <study> · scope <study> · paper <study>' },
    { id: 'study', icon: '◫', title: 'Work on a study', study: true },
    { id: 'advance', icon: '→', title: 'Advance a study one step', skill: 'advance', target: 'study?' },
    { id: 'campaign', icon: '⟳', title: 'Plan a campaign', campaign: true },
    { id: 'compete', icon: '◎', title: 'Compete on a target', skill: 'compete', arg: 'text', argLabel: 'The task or benchmark', placeholder: 'e.g. beat the baseline on …' },
    { id: 'status', icon: '☰', title: 'Check on the lab', skill: 'lab-status' },
    { id: 'configure', icon: '⚙', title: 'Change lab settings with an agent', skill: 'configure', arg: 'text', argLabel: 'What to change (optional)' },
  ];

  NL.StartSheet = ({ onClose, intent: initial, target: initTarget, skill: initSkill, args: initArgs }) => {
    const s = NL.useLab();
    const [intent, setIntent] = useState(initial || (initSkill ? 'study' : null));
    const [target, setTarget] = useState(initTarget || '');
    const [skill, setSkill] = useState(initSkill || '');
    const [arg, setArg] = useState(initArgs || '');
    const [opts, setOpts] = useState(DEFAULT_OPTS);
    const [ask, setAsk] = useState('');
    const it = INTENTS.find(i => i.id === intent);
    const study = target && target !== 'hub' ? NL.item(s, target) : null;
    // for "work on a study": the procedures that fit its state
    const procs = study ? (NL.PROCS_FOR_STATE[study.state] || []).filter(p => (s.skills || {})[p]) : [];
    useEffect(() => { if (it && it.study && study && (!skill || !procs.includes(skill))) setSkill(procs[0] || ''); }, [intent, target]);
    const theSkill = it ? (it.study ? skill : it.skill) : null;
    const cfg = theSkill ? (s.skills || {})[theSkill] : null;
    const proc = theSkill ? NL.PROC[theSkill] || {} : {};
    const needsProject = cfg && cfg.level === 'project';
    const blocked = needsProject && study && !study.has_project ? 'This study has no project repo yet — create it first (after Gate 1).' : null;
    const go = async () => {
      if (!theSkill) return;
      const body = { skill: theSkill, ...optBody(opts) };
      if (it.study || it.target) { if (target && target !== 'hub') body.target = target; else if (it.study) return NL.toast('Choose a study', 'warn'); }
      if (cfg && cfg.args && cfg.args.includes('text') && arg.trim()) body.args = arg.trim();
      if (it.arg === 'text' && arg.trim()) body.args = arg.trim();
      const r = await NL.launch(body);
      if (r) onClose();
    };
    const sendAsk = async () => {
      if (!ask.trim()) return;
      const r = await NL.launch({ prompt: ask.trim(), target: target && target !== 'hub' ? target : 'hub', ...optBody({ ...opts, chain: 'off' }) });
      if (r) onClose();
    };
    return html`<${NL.Sheet} title="Start something" sub="Agents run on this machine, as you. Every gate still waits for your signature." onClose=${onClose} wide icon="＋">
      <div class="asknewt-big">
        <label class="field-label">Ask Newt — or tell it what to do</label>
        <${NL.Textarea} rows="3" value=${ask} onInput=${setAsk} onSubmit=${sendAsk} autofocus=${!initial && !initSkill}
          placeholder="e.g. “Compare the last three pilots of moe and tell me which knob mattered” (Ctrl+Enter to send)" />
        <div class="row"><span class="muted small">Runs as a free-form agent session in ${study ? html`<b>${study.title || study.id}</b>` : 'the lab'} — it can use every procedure; only you sign.</span><span class="grow"></span>
          <${NL.Btn} kind="primary" disabled=${!ask.trim()} onClick=${sendAsk}>Send to Newt</${NL.Btn}></div>
      </div>
      <div class="or"><span>or start a procedure</span></div>
      <div class="intents">${INTENTS.map(i => html`<button type="button" class=${cls('intent', intent === i.id && 'on')} onClick=${() => setIntent(i.id)}>
        <span class="intent-ico" aria-hidden="true">${i.icon}</span><span class="intent-t">${i.title}</span></button>`)}</div>
      ${it && it.campaign ? html`<${CampaignForm} onDone=${onClose} />` : null}
      ${it && !it.campaign ? html`<div class="intent-detail">
        ${(it.study || it.target) ? html`<${StudyPicker} value=${target} onChange=${setTarget} allowLab=${it.target === 'study?'} filter=${i => !NL.isTerminal(i.state)} />` : null}
        ${it.study && study ? html`<${NL.Field} label="What to do"><div class="procs">${procs.length ? procs.map(p => html`<button type="button" class=${cls('proc', skill === p && 'on')} onClick=${() => setSkill(p)}>
          <b>${NL.procTitle(p)}</b><small>${(NL.PROC[p] || {}).does || ''}</small></button>`) : html`<span class="muted">Nothing to start for a study in “${NL.STATE_LABEL[study.state]}”.</span>`}</div></${NL.Field}>` : null}
        ${theSkill && !(it.study && !study) ? html`<div class="explain">
          <div><b>What happens:</b> ${proc.does || NL.procTitle(theSkill)}</div>
          <div><b>Where:</b> ${needsProject ? 'inside the study’s project repo' : study ? 'in the lab, on this study' : 'in the lab'}</div>
          ${proc.stops ? html`<div><b>Stops:</b> ${proc.stops}</div>` : null}
          ${cfg && cfg.mode === 'interactive' ? html`<div><b>Talks with you:</b> one question at a time, answered right here</div>` : null}
          ${blocked ? html`<div class="warn">${blocked}</div>` : null}
          <div class="muted mono small">/${theSkill}${study && cfg && cfg.args.startsWith('slug') ? ' ' + study.id : ''}${arg ? ' ' + arg : ''}</div></div>` : null}
        ${it.arg === 'text' || (cfg && it.study && cfg.args.includes('text')) ? html`<${NL.Field} label=${it.argLabel || 'Notes for the agent (optional)'}>
          <${NL.Input} value=${arg} onInput=${setArg} placeholder=${it.placeholder || ''} onEnter=${go} /></${NL.Field}>` : null}
        ${theSkill ? html`<${LaunchOptions} opts=${opts} setOpts=${setOpts} allowChain=${cfg && cfg.mode !== 'interactive'} allowRepeat=${cfg && cfg.mode !== 'interactive'} />` : null}
        <div class="row end"><${NL.Btn} kind="primary" disabled=${!theSkill || !!blocked || (it.study && !study)} onClick=${go}>Start</${NL.Btn}></div>
      </div>` : null}
    </${NL.Sheet}>`;
  };
  NL.openStart = (props) => NL.open(NL.StartSheet, props || {}, { key: 'start' });

  /* ── Ask Newt: the bar under the world ─────────────────────────────────── */
  NL.AskBar = ({ target }) => {
    const s = NL.useLab();
    const [v, setV] = useState('');
    const study = target && target !== 'hub' ? NL.item(s, target) : null;
    const send = () => { if (!v.trim()) return; NL.open(AskConfirm, { text: v.trim(), target: target || 'hub', onSent: () => setV('') }, { kind: 'dialog', key: 'ask' }); };
    return html`<div class="askbar" role="search">
      <span class="askbar-newt" aria-hidden="true">🦎</span>
      <input class="askbar-in" value=${v} onInput=${e => setV(e.target.value)} onKeyDown=${e => e.key === 'Enter' && (e.preventDefault(), send())}
        placeholder=${study ? `Ask Newt about ${NL.clip(study.title || study.id, 30)} — or tell it what to do…` : 'Ask Newt anything — or tell it what to do…'} aria-label="Ask Newt" />
      <button class="askbar-more" title="leave a note for the next agent instead" onClick=${() => NL.openNote(target, v)}>✉</button>
      <button class="askbar-go" disabled=${!v.trim()} onClick=${send} aria-label="send">➤</button></div>`;
  };
  const AskConfirm = ({ text, target, onSent, onClose }) => {
    const s = NL.useLab();
    const [t, setT] = useState(text);
    const [tgt, setTgt] = useState(target);
    const [opts, setOpts] = useState(DEFAULT_OPTS);
    const go = async () => { const r = await NL.launch({ prompt: t.trim(), target: tgt || 'hub', ...optBody({ ...opts, chain: 'off' }) }); if (r) { onSent && onSent(); onClose(); } };
    return html`<div class="dialog dialog-wide"><h3>Send to Newt</h3>
      <${NL.Textarea} rows="4" value=${t} onInput=${setT} onSubmit=${go} autofocus />
      <${StudyPicker} label="Where" value=${tgt} onChange=${setTgt} allowLab />
      <${LaunchOptions} opts=${opts} setOpts=${setOpts} />
      <p class="muted small">A free-form agent session, as you, with your login. It can run any lab procedure; gates, envelopes and Gate 3 still wait for your signature — it cannot sign them.</p>
      <div class="dialog-actions"><${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!t.trim()} onClick=${go}>Send</${NL.Btn}></div></div>`;
  };
  NL.openNote = (target, text) => NL.open(NoteDialog, { target: target || 'hub', text: text || '' }, { kind: 'dialog' });
  const NoteDialog = ({ target, text, onClose }) => {
    const [t, setT] = useState(text || '');
    const go = async () => { const r = await NL.act('/api/directive', { target, text: t.trim() }, 'Note pinned — the next agent reads it at its next checkpoint'); if (r.ok) onClose(); };
    return html`<div class="dialog"><h3>Leave a note for the next agent</h3>
      <p class="muted small">Doesn't start anything. The next agent working ${target === 'hub' ? 'in the lab' : 'on this study'} reads it at its next checkpoint and acknowledges it.</p>
      <${NL.Textarea} rows="3" value=${t} onInput=${setT} onSubmit=${go} autofocus />
      <div class="dialog-actions"><${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!t.trim()} onClick=${go}>Pin the note</${NL.Btn}></div></div>`;
  };

  /* ── Plan a campaign (writes + signs lab/campaigns/<date>-<slug>.md) ───── */
  /* what a walk-away start needs, checked live (GET /api/campaign/preflight) */
  NL.Preflight = ({ onReady }) => {
    const [p, setP] = useState(null);
    const load = () => NL.get('/api/campaign/preflight').then(x => { setP(x); onReady && onReady(!!(x && x.ready)); });
    useEffect(() => { load(); }, []);
    if (!p) return html`<${NL.Spinner} />`;
    return html`<div class="preflight">${(p.checks || []).map(c => html`<div class=${cls('pf-row', c.ok ? 'ok' : c.warn_only ? 'warn' : 'bad')} key=${c.id}>
        <span class="pf-ico">${c.ok ? '✓' : c.warn_only ? '!' : '✕'}</span><span class="pf-t"><b>${c.label}</b>${c.detail ? html`<small>${c.detail}</small>` : null}</span>
        ${!c.ok && c.fix ? html`<a class="link small" href=${'#/' + c.fix} onClick=${() => NL.closeTop && NL.closeTop()}>fix →</a>` : null}</div>`)}
      <div class="row end"><button type="button" class="link small" onClick=${load}>check again</button></div></div>`;
  };

  const CampaignForm = ({ onDone }) => {
    const [f, setF] = useState({ direction: '', name: '', ideas: 3, parallel: 1, compute_total: '', full_runs: 3, full_minutes: 60,
      max_open_questions: 2, mode: 'execute', explore_rounds: 1, explore_lines: 2, hours: 12, agent_hours: 0,
      cycle_minutes: 90, repeat_minutes: 20, gate3: false });
    const [ready, setReady] = useState(false);
    const [more, setMore] = useState(false);
    const set = (k, v) => setF(o => ({ ...o, [k]: v }));
    const until = new Date(Date.now() + (+f.hours || 0) * 3600e3);
    const sign = async (launch) => {
      if (!f.direction.trim()) return NL.toast('Describe the direction first', 'warn');
      const body = html`<div><p>Your signature lets the lab work on its own <b>within these bounds</b>: agents approve proposals that fit them (Gate 1) and derive each project's FULL-run envelope (Gate 2) from it. Anything outside the bounds waits for you, and the rest of the campaign carries on.</p>
        <p>${f.gate3 ? html`<b>Papers may finalize without you.</b> Once a paper passes internal review, the lab itself re-runs the paper audits and, if they are clean, records Gate 3 and runs /finalize. Nothing is sent outside the lab. You can revoke this, or hold a study, from the campaign card.` : html`Papers stop at <b>internal review</b> for your Gate 3.`}</p>
        <p class="muted">It runs until ${until.toLocaleString()}${+f.agent_hours ? ` or ${f.agent_hours} agent-hours` : ''}, restarting after timeouts, usage limits and network errors. Stop it any time.</p></div>`;
      const ok = await NL.confirm({ title: 'Sign this campaign?', ok: launch ? 'Sign and start' : 'Sign', body,
        typed: f.gate3 ? 'finalize' : undefined });
      if (!ok) return;
      const r = await NL.act('/api/campaign', { confirm: true, fields: f, launch, gate3_typed: f.gate3 ? 'finalize' : undefined });
      if (r.ok) { onDone && onDone(); if (r.campaign) NL.go('studies?campaign=' + encodeURIComponent(r.campaign)); }
    };
    return html`<div class="intent-detail"><div class="explain"><div><b>A campaign</b> carries several ideas from ideation to reviewed papers while you're away — within bounds you sign here. The lab keeps it going by itself: each pass looks at every idea and starts its next step.</div></div>
      <${NL.Field} label="Research direction"><${NL.Textarea} rows="2" value=${f.direction} onInput=${v => set('direction', v)} placeholder="what the campaign explores" /></${NL.Field}>
      <div class="grid3">
        <${NL.Field} label="Ideas to carry"><${NL.Input} type="number" min="1" value=${f.ideas} onInput=${v => set('ideas', v)} /></${NL.Field}>
        <${NL.Field} label="At once"><${NL.Input} type="number" min="1" value=${f.parallel} onInput=${v => set('parallel', v)} /></${NL.Field}>
        <${NL.Field} label="Run for (hours)" hint=${'until ' + until.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}><${NL.Input} type="number" min="1" value=${f.hours} onInput=${v => set('hours', v)} /></${NL.Field}>
        <${NL.Field} label="Total compute" hint="written into the brief"><${NL.Input} value=${f.compute_total} onInput=${v => set('compute_total', v)} placeholder="e.g. 8 GPU-hours" /></${NL.Field}>
        <${NL.Field} label="FULL runs per project"><${NL.Input} type="number" min="0" value=${f.full_runs} onInput=${v => set('full_runs', v)} /></${NL.Field}>
        <${NL.Field} label="Minutes per FULL run"><${NL.Input} type="number" min="0" value=${f.full_minutes} onInput=${v => set('full_minutes', v)} /></${NL.Field}>
      </div>
      <label class="check-row"><input type="checkbox" checked=${f.gate3} onChange=${e => set('gate3', e.target.checked)} />
        <span><b>Papers may finalize without me</b><small>The lab records Gate 3 only after internal review accepts the paper and its own re-run of the paper audits (claims, seeds, ablations, eval discipline) is clean. Nothing leaves the lab.</small></span></label>
      <button type="button" class="link small" onClick=${() => setMore(!more)}>${more ? 'Fewer options' : 'More options…'}</button>
      ${more ? html`<div class="grid3">
        <${NL.Field} label="Agent-hours budget" hint="0 = only the wall-clock limit"><${NL.Input} type="number" min="0" value=${f.agent_hours} onInput=${v => set('agent_hours', v)} /></${NL.Field}>
        <${NL.Field} label="A pass every (min)"><${NL.Input} type="number" min="5" value=${f.repeat_minutes} onInput=${v => set('repeat_minutes', v)} /></${NL.Field}>
        <${NL.Field} label="Longest pass (min)"><${NL.Input} type="number" min="10" value=${f.cycle_minutes} onInput=${v => set('cycle_minutes', v)} /></${NL.Field}>
        <${NL.Field} label="Open questions allowed at scoping"><${NL.Input} type="number" min="0" value=${f.max_open_questions} onInput=${v => set('max_open_questions', v)} /></${NL.Field}>
        <${NL.Field} label="Research loops"><${NL.Seg} value=${f.mode} onChange=${v => set('mode', v)} options=${[{ value: 'execute', label: 'Follow the plan' }, { value: 'explore', label: 'Explore' }]} /></${NL.Field}>
        <${NL.Field} label="Name" hint="optional"><${NL.Input} value=${f.name} onInput=${v => set('name', v)} placeholder="e.g. routing-sprint" /></${NL.Field}>
      </div>` : null}
      <div class="muted small">Proposals are self-approved only when all hold: within the budget above, kill criteria + frozen eval present, novelty verdict “novel”, scoping passed. Anything else waits for you.</div>
      <${NL.Section} title="Before you walk away"><${NL.Preflight} onReady=${setReady} /></${NL.Section}>
      <div class="row end"><${NL.Btn} onClick=${() => sign(false)}>Sign only</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!ready} title=${ready ? '' : 'fix the checks above first'} onClick=${() => sign(true)}>Sign and start</${NL.Btn}></div></div>`;
  };
})();
