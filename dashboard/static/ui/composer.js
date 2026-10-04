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
  // a skill appears here by giving its SKILL.md frontmatter a `start:` block (icon, order, label, …)
  const BUILT_IN = [{ id: 'study', icon: '◫', title: 'Work on a study', study: true, order: 4 },
    { id: 'campaign', icon: '⟳', title: 'Plan a campaign', campaign: true, order: 6,
      onramp: 'Sign a direction, a time limit and a budget once; the lab carries ideas all the way to reviewed papers by itself, restarting through timeouts and usage limits, and only stops for what is outside your bounds.',
      onrampTitle: 'Start a campaign' }];
  // a one-line "what it does" under each tile — so near neighbours (one step vs pick a step) read apart
  const INTENT_WORDS = {
    study: { title: 'Work on a study', desc: 'pick what to do on it, or give it notes' },
    advance: { title: 'Advance a study one step', desc: 'run its next step, then stop' },
    configure: { desc: 'an agent walks you through any setting, incl. ones not in Settings' },
    campaign: { desc: 'carry several ideas while you’re away, within signed bounds' } };
  NL.intents = () => Object.entries(NL.PROC).filter(([, p]) => p.start && p.launchable !== false).map(([name, p]) => {
    const st = p.start, args = p.args || '';
    return { id: name, icon: st.icon || '▸', title: st.title || p.title || name, skill: name, order: st.order ?? 50,
      arg: args.includes('text') ? 'text' : null, argLabel: st.label, placeholder: st.placeholder,
      target: args.startsWith('slug?') ? 'study?' : null, onramp: st.onramp, does: p.does };
  }).concat(BUILT_IN).map(i => ({ ...i, ...(INTENT_WORDS[i.id] || {}) })).sort((a, b) => a.order - b.order);

  NL.StartSheet = ({ onClose, intent: initial, target: initTarget, skill: initSkill, args: initArgs }) => {
    const s = NL.useLab();
    const [intent, setIntent] = useState(initial || (initSkill ? 'study' : null));
    const [target, setTarget] = useState(initTarget || '');
    const [skill, setSkill] = useState(initSkill || '');
    const [arg, setArg] = useState(initArgs || '');
    const [opts, setOpts] = useState(DEFAULT_OPTS);
    const [ask, setAsk] = useState('');
    const INTENTS = NL.intents();
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
      if (NL.quickAnswer && NL.quickAnswer(ask.trim(), NL.getState())) { onClose(); return NL.open(NL.AnswerSheet, { text: ask.trim(), target, onAgent: () => NL.launch({ prompt: ask.trim(), target: target && target !== 'hub' ? target : 'hub', ...optBody({ ...opts, chain: 'off' }) }) }, { key: 'answer' }); }
      const r = await NL.launch({ prompt: ask.trim(), target: target && target !== 'hub' ? target : 'hub', ...optBody({ ...opts, chain: 'off' }) });
      if (r) onClose();
    };
    // a campaign approves Gate 1 (within bounds) and derives Gate 2 — the header must not promise otherwise
    const sub = it && it.campaign ? 'Agents run on this machine, as you. A campaign may approve Gates 1–2 within the bounds you sign; everything else waits for you.'
      : 'Agents run on this machine, as you. Every gate still waits for your signature.';
    return html`<${NL.Sheet} title="Start something" sub=${sub} onClose=${onClose} wide>
      <div class="asknewt-big">
        <label class="field-label">Ask a question or give an instruction</label>
        <${NL.Textarea} rows="3" value=${ask} onInput=${setAsk} onSubmit=${sendAsk} autofocus=${!initial && !initSkill}
          placeholder="e.g. “Compare the last three trial runs of moe and say which setting mattered”. Ctrl+Enter sends." />
        <div class="row"><span class="muted small">Starts a run in ${study ? html`<b>${study.title || study.id}</b>` : 'the lab'}. It can use any procedure, but only you can approve gates.</span><span class="grow"></span>
          <${NL.Btn} kind="primary" disabled=${!ask.trim()} onClick=${sendAsk}>Send</${NL.Btn}></div>
      </div>
      <div class="or"><span>or start a procedure</span></div>
      <div class="intents">${INTENTS.map(i => html`<button type="button" class=${cls('intent', intent === i.id && 'on')} onClick=${() => setIntent(i.id)}>
        <span class="intent-ico" aria-hidden="true">${i.icon}</span><span class="intent-t" style="display:flex;flex-direction:column;gap:2px;min-width:0">${i.title}${i.desc ? html`<small class="muted" style="font-weight:400;font-size:12px;line-height:1.3">${i.desc}</small>` : null}</span></button>`)}</div>
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
    const toAgent = text => NL.open(AskConfirm, { text, target: target || 'hub', onSent: () => setV('') }, { kind: 'dialog', key: 'ask' });
    // a question the lab's live state already answers is answered here — free, instant, no agent session
    const send = () => { const q = v.trim(); if (!q) return; if (NL.quickAnswer && NL.quickAnswer(q, s)) return NL.open(NL.AnswerSheet, { text: q, target, onAgent: () => toAgent(q) }, { key: 'answer' }); toAgent(q); };
    return html`<div class="askbar" role="search">
      <span class="askbar-newt" aria-hidden="true">🦎</span>
      <input class="askbar-in" value=${v} onInput=${e => setV(e.target.value)} onKeyDown=${e => e.key === 'Enter' && (e.preventDefault(), send())}
        placeholder=${study ? `Ask about ${NL.clip(study.title || study.id, 30)}, or give an instruction…` : 'Ask a question, or give the lab an instruction…'} aria-label="Ask Newt" />
      <button class="askbar-more" title="leave a note for the next agent instead" onClick=${() => NL.openNote(target, v)}>✉</button>
      <button class="askbar-go" disabled=${!v.trim()} onClick=${send} aria-label="send">➤</button></div>`;
  };
  const AskConfirm = ({ text, target, onSent, onClose }) => {
    const s = NL.useLab();
    const [t, setT] = useState(text);
    const [tgt, setTgt] = useState(target);
    const [opts, setOpts] = useState(DEFAULT_OPTS);
    const go = async () => { const r = await NL.launch({ prompt: t.trim(), target: tgt || 'hub', ...optBody({ ...opts, chain: 'off' }) }); if (r) { onSent && onSent(); onClose(); } };
    return html`<div class="dialog dialog-wide"><h3>New instruction</h3>
      <${NL.Textarea} rows="4" value=${t} onInput=${setT} onSubmit=${go} autofocus />
      <${StudyPicker} label="Where" value=${tgt} onChange=${setTgt} allowLab />
      <${LaunchOptions} opts=${opts} setOpts=${setOpts} />
      <p class="muted small">A run using your account. It can use any lab procedure. Gates still wait for your approval; it cannot approve them.</p>
      <div class="dialog-actions"><${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!t.trim()} onClick=${go}>Send</${NL.Btn}></div></div>`;
  };
  NL.openNote = (target, text, opts) => NL.open(NoteDialog, { target: target || 'hub', text: text || '', ...(opts || {}) }, { kind: 'dialog' });
  const NoteDialog = ({ target, text, title, ok, sub, onClose }) => {
    const [t, setT] = useState(text || '');
    const go = async () => { const r = await NL.act('/api/directive', { target, text: t.trim() }, 'Note pinned — the next agent reads it at its next checkpoint'); if (r.ok) onClose(); };
    return html`<div class="dialog"><h3>${title || 'Leave a note for the next agent'}</h3>
      <p class="muted small">${sub || html`Doesn't start anything. The next agent working ${target === 'hub' ? 'in the lab' : 'on this study'} reads it at its next checkpoint and acknowledges it.`}</p>
      <${NL.Textarea} rows="3" value=${t} onInput=${setT} onSubmit=${go} autofocus />
      <div class="dialog-actions"><${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!t.trim()} onClick=${go}>${ok || 'Pin the note'}</${NL.Btn}></div></div>`;
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
    const s = NL.useLab();
    const [f, setF] = useState({ direction: '', name: '', ideas: 3, parallel: 1, compute_total: '', full_runs: 3, full_minutes: 60,
      max_open_questions: 2, mode: 'execute', explore_rounds: 1, explore_lines: 2, hours: 12, agent_hours: null,
      cycle_minutes: 90, repeat_minutes: 20, gate1: false, gate3: false, spend_cap: '' });
    const [ready, setReady] = useState(false);
    const [more, setMore] = useState(false);
    const set = (k, v) => setF(o => ({ ...o, [k]: v }));
    // agent-hours follow hours × at once until you type your own
    const autoAgentHours = Math.max(0, (+f.hours || 0) * Math.max(1, +f.parallel || 1));
    const agentHours = f.agent_hours == null ? autoAgentHours : f.agent_hours;
    const until = new Date(Date.now() + (+f.hours || 0) * 3600e3);
    const spendCap = Math.max(0, +f.spend_cap || 0);   // blank / 0 = no cap
    const labName = (s.lab_info || {}).name || 'this lab';
    const machine = s.remote ? s.remote.name : 'this computer';
    const G1_BOUNDS = 'Agents approve a proposal only if all of these hold: it is within the limits above, has kill criteria and a frozen evaluation, was judged novel, and passed scoping. Its full-run limits come from the same numbers. Anything else waits for you. Leave this unticked and every proposal waits for you.';
    const sign = async (launch) => {
      if (!f.direction.trim()) return NL.toast('Describe the direction first', 'warn');
      const body = html`<div><p>Your signature lets the lab work on its own <b>within these bounds</b>: ${f.gate1
          ? html`agents approve proposals that fit them (Gate 1) and derive each project's FULL-run envelope (Gate 2) from them.`
          : html`<b>every proposal waits for your Gate 1</b>; once you approve one, its FULL-run envelope (Gate 2) comes from these bounds.`} Anything outside the bounds waits for you, and the rest of the campaign carries on.</p>
        <p>${f.gate3 ? html`<b>Papers may finalize without you.</b> Once a paper passes internal review, the lab itself re-runs the paper audits and, if they are clean, records Gate 3 and runs /finalize. Nothing is sent outside the lab. You can revoke this, or hold a study, from the campaign card.` : html`Papers stop at <b>internal review</b> for your Gate 3.`}</p>
        <p>${spendCap ? html`It stops when its runs have spent <b>$${spendCap.toFixed(2)}</b> (estimated from token use), and writes its final report.`
          : html`<b>No spending cap — it can spend until its hours or agent-hours run out.</b>`}</p>
        <p class="muted">It runs in ${labName} on ${machine} until ${NL.when(until)}${+agentHours ? ` or ${+agentHours} agent-hours, whichever comes first` : ''}, restarting after timeouts, usage limits and network errors. ${launch ? '' : 'Signing only records the brief; you start it later. '}Stop or pause it any time from the campaign card on Home or Studies.</p></div>`;
      const ok = await NL.confirm({ title: 'Approve this campaign?', ok: launch ? 'Approve and start' : 'Approve', body,
        typed: f.gate3 ? 'finalize' : undefined });
      if (!ok) return;
      // gate1 is always sent explicitly (the backend treats a missing field as "on", for older callers)
      const fields = { ...f, agent_hours: +agentHours || 0, gate1: !!f.gate1, spend_cap: spendCap };
      const r = await NL.act('/api/campaign', { confirm: true, fields, launch, gate3_typed: f.gate3 ? 'finalize' : undefined });
      if (r.ok) { onDone && onDone(); if (r.campaign) NL.go('studies?campaign=' + encodeURIComponent(r.campaign)); }
    };
    return html`<div class="intent-detail">
      <div class="camp-where small">Runs in <b>${labName}</b> on <b>${machine}</b>. To run elsewhere, switch labs first (<a class="link" href="#/labs" onClick=${() => NL.closeTop && NL.closeTop()}>Labs & machines</a>).</div>
      <div class="explain"><div><b>A campaign</b> carries several ideas from ideation to reviewed papers while you're away — within bounds you sign here. The lab keeps it going by itself in <b>passes</b>: each pass, the lab checks every idea and starts its next step.</div></div>
      <${NL.Field} label="Research direction"><${NL.Textarea} rows="2" value=${f.direction} onInput=${v => set('direction', v)} placeholder="what the campaign explores" /></${NL.Field}>
      <div class="grid3">
        <${NL.Field} label="Ideas to carry"><${NL.Input} type="number" min="1" value=${f.ideas} onInput=${v => set('ideas', v)} /></${NL.Field}>
        <${NL.Field} label="At once" hint="ideas in flight together"><${NL.Input} type="number" min="1" value=${f.parallel} onInput=${v => set('parallel', v)} /></${NL.Field}>
      </div>
      <div class="camp-group"><div class="camp-group-h">Hard limits — the lab stops when any is reached</div>
        <div class="grid2">
          <${NL.Field} label="Run for (hours)" hint=${'until ' + NL.when(until)}><${NL.Input} type="number" min="1" value=${f.hours} onInput=${v => set('hours', v)} /></${NL.Field}>
          <${NL.Field} label="Agent-hours" hint=${f.agent_hours == null ? 'hours × at once · 0 = only the clock' : html`0 = only the clock · <button type="button" class="link small" onClick=${() => set('agent_hours', null)}>back to ${autoAgentHours}</button>`}><${NL.Input} type="number" min="0" value=${agentHours} onInput=${v => set('agent_hours', v)} /></${NL.Field}>
          <${NL.Field} label="Full runs per study" hint="A full run is the complete experiment, run after the trial runs."><${NL.Input} type="number" min="0" value=${f.full_runs} onInput=${v => set('full_runs', v)} /></${NL.Field}>
          <${NL.Field} label="Minutes per FULL run"><${NL.Input} type="number" min="0" value=${f.full_minutes} onInput=${v => set('full_minutes', v)} /></${NL.Field}>
          <${NL.Field} label="Spending cap ($)"
            hint=${spendCap ? 'The campaign stops there and writes its final report. Estimated from token use.' : 'Blank = no cap. The campaign can then spend until its hours run out.'}><${NL.Input} type="number" min="0" step="1" value=${f.spend_cap} onInput=${v => set('spend_cap', v)} placeholder="no cap" /></${NL.Field}>
        </div>
        <div class="muted small">Spend so far shows on the campaign card.</div></div>
      <div class="camp-group camp-group-soft"><div class="camp-group-h">Notes for the agents (not enforced)</div>
        <${NL.Field} label="Total compute" hint="written into the brief for the agents to plan by"><${NL.Input} value=${f.compute_total} onInput=${v => set('compute_total', v)} placeholder="e.g. 8 GPU-hours" /></${NL.Field}></div>
      <label class="check-row"><input type="checkbox" checked=${f.gate1} onChange=${e => set('gate1', e.target.checked)} />
        <span><b>Gate 1 is approved for me when a proposal fits these limits</b><small>${G1_BOUNDS}</small></span></label>
      <label class="check-row"><input type="checkbox" checked=${f.gate3} onChange=${e => set('gate3', e.target.checked)} />
        <span><b>Papers can be finalized without me</b><small>Only after internal review accepts the paper and the lab re-runs the paper audits (claims, seeds, ablations, evaluation, pre-registration) cleanly. Nothing leaves the lab. You can take this back from the campaign card.</small></span></label>
      <button type="button" class="link small" onClick=${() => setMore(!more)}>${more ? 'Fewer options' : 'More options…'}</button>
      ${more ? html`<div class="grid3">
        <${NL.Field} label="A pass every (min)" hint="a pass: the lab checks every idea and starts its next step"><${NL.Input} type="number" min="5" value=${f.repeat_minutes} onInput=${v => set('repeat_minutes', v)} /></${NL.Field}>
        <${NL.Field} label="Longest pass (min)"><${NL.Input} type="number" min="10" value=${f.cycle_minutes} onInput=${v => set('cycle_minutes', v)} /></${NL.Field}>
        <${NL.Field} label="Open questions allowed at scoping"><${NL.Input} type="number" min="0" value=${f.max_open_questions} onInput=${v => set('max_open_questions', v)} /></${NL.Field}>
        <${NL.Field} label="Research loops" hint=${f.mode === 'explore' ? 'Explore: a project may widen its plan within its envelope' : 'Follow the plan: run the approved plan, then stop'}><${NL.Seg} value=${f.mode} onChange=${v => set('mode', v)} options=${[{ value: 'execute', label: 'Follow the plan' }, { value: 'explore', label: 'Explore' }]} /></${NL.Field}>
        <${NL.Field} label="Name" hint="optional"><${NL.Input} value=${f.name} onInput=${v => set('name', v)} placeholder="e.g. routing-sprint" /></${NL.Field}>
      </div>` : null}
      <${NL.Section} title="Checks before you start"><${NL.Preflight} onReady=${setReady} /></${NL.Section}>
      <div class="row end"><span class="muted small">${ready ? `${f.ideas} ideas · ${f.hours} h · cap ${spendCap ? '$' + spendCap : 'none'}` : 'Fix the checks above before starting.'}</span>
        <${NL.Btn} onClick=${() => sign(false)} title="Records your approval now. Start it later from the campaign card.">Approve, start later</${NL.Btn}><${NL.Btn} kind="primary" disabled=${!ready} title=${ready ? '' : 'Fix the checks above first'} onClick=${() => sign(true)}>Approve and start</${NL.Btn}></div></div>`;
  };
})();
