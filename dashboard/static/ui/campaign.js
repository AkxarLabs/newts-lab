/* Newts' Lab — a running campaign: what the lab is doing on its own while the PI is away. A compact card
   (Home's Today rail, the Studies page) and a sheet with everything: progress against the deadline and
   budget, each study (waiting for you? held?), the last passes, what was started or refused and why,
   questions a pass left, Gate 3 by delegation — with Pause / Resume / Stop / Revoke / Hold. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, cls } = NL;

  const WORD = { active: 'Running', finishing: 'Wrapping up', stopping: 'Stopping', paused: 'Paused', stalled: 'Needs you',
    done: 'Done', stopped: 'Stopped' };
  const TONE = { active: 'live', finishing: 'live', stopping: 'muted', paused: 'warn', stalled: 'bad', done: 'ok', stopped: 'muted' };
  const when = ts => NL.when(ts);   // "Sun 4 Oct, 13:47" (core.js)

  NL.campaignsOf = s => (s.campaign_states || (NL.DEMO && NL.demoCampaignStates ? NL.demoCampaignStates(0) : []));
  NL.liveCampaigns = s => NL.campaignsOf(s).filter(c => ['active', 'finishing', 'stopping', 'paused', 'stalled'].includes(c.status));

  // what the campaign's runs cost so far (from the runs this page sees; a subscription login may report none)
  const costOf = r => +((r.usage || {}).cost_usd) || 0;
  const spentOf = (s, c) => {
    if (c.spent_usd != null) return c.spent_usd;
    const runs = (s && s.runs) || [];
    if (c.demo_spend) {   // demo: a share of the demo runs on the campaign's studies, so it never exceeds the lab's total
      const mine = new Set(Object.keys(c.studies || {}));
      return 0.6 * runs.filter(r => mine.has(r.subject)).reduce((a, r) => a + costOf(r), 0);
    }
    return runs.filter(r => r.campaign === c.name).reduce((a, r) => a + costOf(r), 0);
  };
  const hhmm = ts => { const d = ts ? new Date(ts) : null; return d && !isNaN(d) ? `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` : ''; };
  // "≈ $4.20 since it started (09:12) of $20" — the cap, when the campaign has one, is a hard stop
  const spendLine = (c, spent) => {
    const cap = +(c.spend_cap_usd || (c.budget || {}).spend_usd) || 0;
    if (!spent && !cap) return null;
    const at = hhmm(c.created);
    return `≈ $${(spent || 0).toFixed(2)} since it started${at ? ` (${at})` : ''}${cap ? ` of $${cap.toFixed(2)}` : ''}`;
  };
  const left = c => { if (!c.deadline) return null; const ms = new Date(c.deadline) - Date.now(); if (ms <= 0) return 'deadline passed';
    const tm = Math.round(ms / 60e3), h = Math.floor(tm / 60), m = tm % 60; return (h ? `${h} h ` : '') + (m || !h ? `${m} min ` : '') + 'left'; };
  const nextIn = c => { if (!c.next_cycle_at || c.status !== 'active') return null; const ms = new Date(c.next_cycle_at) - Date.now();
    return ms > 60e3 ? `next pass in ${Math.round(ms / 60e3)} min` : 'next pass now'; };
  const counts = c => { const st = Object.values(c.studies || {}).filter(x => x.member);
    return { n: st.length, waiting: st.filter(x => x.waiting).length, held: st.filter(x => x.hold).length }; };

  const act = async (c, action, extra) => {
    const words = { stop: ['Stop this campaign?', 'It stops starting work, stops what is running, and writes a final report.', 'Stop'],
      revoke_gate3: ['Take Gate 3 back?', 'No paper of this campaign will finalize without you. A /finalize already running is stopped.', 'Take it back'] };
    if (words[action] && !await NL.confirm({ title: words[action][0], body: words[action][1], ok: words[action][2], danger: action === 'stop' })) return;
    return NL.act('/api/campaign/control', { name: c.name, action, confirm: true, ...(extra || {}) });
  };

  NL.campaignAct = act;   // the palette's Pause / Stop entries (app.js) go through the same confirms

  /* a question a pass left: answer it here and the next pass gets the answer */
  const CampaignQuestion = ({ c, q }) => {
    const [text, setText] = useState('');
    const send = async () => { if (!text.trim()) return; const x = await act(c, 'answer', { index: q.index, text: text.trim() }); if (x && x.ok) setText(''); };
    return html`<div class=${cls('inrow', q.answer ? 'sev-info' : 'sev-warn')}><div class="inrow-main"><span class="inrow-ico">?</span><span class="inrow-t"><b>${q.question}</b>
      <small>${when(q.ts)}${q.answer ? html` — you answered: <b>${NL.clip(q.answer, 120)}</b>${q.delivered ? ' (the next pass got it)' : ' (the next pass gets it)'}` : ' — your answer goes to the next pass'}</small></span></div>
      ${q.answer ? null : html`<div class="row grow"><${NL.Input} value=${text} onInput=${setText} onEnter=${send} placeholder="Your answer…" /><${NL.Btn} small kind="primary" onClick=${send} disabled=${!text.trim()}>Answer</${NL.Btn}></div>`}</div>`;
  };

  NL.CampaignCard = ({ c, compact }) => {
    const s = NL.useLab();
    const k = counts(c);
    const b = c.budget || {};
    const pct = b.agent_minutes ? Math.min(100, Math.round(100 * (c.used_minutes || 0) / b.agent_minutes)) : null;
    const spent = spentOf(s, c);
    const live = c.status === 'active' || c.status === 'finishing';
    return html`<div class=${cls('camp-card', 'st-' + c.status, compact && 'compact')}>
      <div class="row between"><button type="button" class="link camp-title" onClick=${() => NL.openCampaign(c.name)}>${NL.clip(c.name.replace(/^\d{4}-\d{2}-\d{2}-/, ''), compact ? 28 : 60)}</button>
        <${NL.Pill} tone=${TONE[c.status] || 'muted'}>${TONE[c.status] === 'live' ? html`<i class="dot-live"></i>` : null}${WORD[c.status] || c.status}</${NL.Pill}></div>
      <div class="muted small" title=${c.deadline ? 'runs until ' + when(c.deadline) : ''}>${[`pass ${c.cycles || 0}`, left(c), nextIn(c), `${Math.round(c.used_minutes || 0)} agent-min${b.agent_minutes ? ' of ' + Math.round(b.agent_minutes) : ''}`, spendLine(c, spent)].filter(Boolean).join(' · ')}</div>
      ${!compact && c.deadline ? html`<div class="muted small">Runs until ${when(c.deadline)}${c.created ? ` · started ${when(c.created)}` : ''}</div>` : null}
      ${pct != null ? html`<${NL.Bar} value=${pct} max=${100} />` : null}
      <div class="row gap wrap small">${k.n ? html`<span>${NL.plural(k.n, 'study', 'studies')}</span>` : html`<span class="muted">no studies yet</span>`}
        ${k.waiting ? html`<${NL.Pill} tone="ask">${k.waiting} waiting for you</${NL.Pill}>` : null}
        ${c.gate3_auto ? html`<${NL.Pill} tone="state" title="papers may finalize without you">Gate 3 delegated</${NL.Pill}>` : null}
        ${(c.questions || []).filter(q => !q.answer).length ? html`<${NL.Pill} tone="ask">${NL.plural(c.questions.filter(q => !q.answer).length, 'question')}</${NL.Pill}>` : null}</div>
      ${c.paused_reason && ['paused', 'stalled'].includes(c.status) ? html`<div class="small warn">${c.paused_reason}${c.paused_by_lab ? ' — it carries on when you resume the lab' : ''}</div>` : null}
      <div class=${cls('row gap', compact && 'camp-ctl')}>${live ? html`<${NL.Btn} small onClick=${() => act(c, 'pause')} title="no new pass starts; what is running finishes">Pause</${NL.Btn}>` : null}
        ${['paused', 'stalled'].includes(c.status) && !c.paused_by_lab ? html`<${NL.Btn} small kind="primary" onClick=${() => act(c, 'resume')}>Resume</${NL.Btn}>` : null}
        ${!['done', 'stopped', 'stopping'].includes(c.status) ? html`<${NL.Btn} small kind="ghost" onClick=${() => act(c, 'stop')} title="stop for good: ends what is running and writes a final report">Stop…</${NL.Btn}>` : null}
        ${!compact ? html`<${NL.Btn} small kind="ghost" onClick=${() => NL.openCampaign(c.name)}>Details</${NL.Btn}>` : null}</div></div>`;
  };

  NL.CampaignSheet = ({ name, onClose }) => {
    const s = NL.useLab();
    const c = NL.campaignsOf(s).find(x => x.name === name);
    const runs = (s.runs || []).filter(r => r.campaign === name);
    if (!c) return html`<${NL.Sheet} title="Campaign" onClose=${onClose}><${NL.Empty}>This campaign isn't being kept on this lab.</${NL.Empty}></${NL.Sheet}>`;
    const studies = Object.entries(c.studies || {}).filter(([, v]) => v.member);
    return html`<${NL.Sheet} wide title=${c.name} sub=${html`${WORD[c.status] || c.status} · <button type="button" class="link" onClick=${() => { onClose(); NL.openDoc('lab', null, c.file.replace(/^lab\//, '')); }}>the signed brief</button>`} onClose=${onClose}>
      <${NL.CampaignCard} c=${c} />
      ${c.gate3_auto ? html`<div class="note note-ask">Papers of this campaign may finalize without you: after internal review accepts one, the lab re-runs the paper audits and, if clean, records Gate 3 and runs /finalize.
        <div class="row end"><${NL.Btn} small onClick=${() => act(c, 'revoke_gate3')}>Take Gate 3 back…</${NL.Btn}></div></div>` : null}
      ${(c.questions || []).length ? html`<${NL.Section} title="Questions a pass left for you">${c.questions.map(q => html`<${CampaignQuestion} key=${q.index} c=${c} q=${q} />`)}</${NL.Section}>` : null}
      <${NL.Section} title="Studies" count=${studies.length}>${studies.length ? studies.map(([slug, v]) => html`<div class="camp-study">
          <a class="link" href=${'#/study/' + slug} onClick=${onClose}><b>${slug}</b></a>
          ${v.waiting ? html`<${NL.Pill} tone="ask">waiting for you: ${v.waiting}</${NL.Pill}>` : null}
          ${v.gate3_done ? html`<${NL.Pill} tone="ok">finalizing</${NL.Pill}>` : null}
          ${c.gate3_auto && !v.gate3_done ? html`<button type="button" class="link small" onClick=${() => act(c, v.hold ? 'unhold' : 'hold', { study: slug })}>${v.hold ? 'let it auto-finalize' : 'hold from auto-finalizing'}</button>` : null}</div>`)
        : html`<p class="muted">None yet — the first pass files ideas and adds them to the campaign log.</p>`}</${NL.Section}>
      <${NL.Section} title="What it did" count=${(c.events || []).length}>
        <div class="camp-events">${(c.events || []).slice().reverse().map(e => html`<div><span class="mono muted">${when(e.ts)}</span> ${e.what}</div>`)}</div></${NL.Section}>
      <${NL.Section} title="Steps it started" count=${(c.dispatch_log || []).length}>
        ${(c.dispatch_log || []).slice().reverse().map(d => html`<div class=${cls('camp-disp', d.result !== 'started' && 'refused')}>
          <span class="mono">/${d.skill} ${d.target !== 'hub' ? d.target : ''}</span>
          ${d.run_id ? html`<button type="button" class="link small" onClick=${() => NL.openRun(d.run_id)}>open</button>` : html`<span class="muted small">${d.result}</span>`}</div>`)}
        ${!(c.dispatch_log || []).length ? html`<p class="muted">Nothing yet.</p>` : null}</${NL.Section}>
      ${(c.gate3_log || []).length ? html`<${NL.Section} title="Gate 3 checks">${c.gate3_log.slice().reverse().map(g => html`<div class="small"><b>${g.study}</b> · ${g.result}</div>`)}</${NL.Section}>` : null}
      <${NL.Section} title="Runs" count=${runs.length}><div class="runlist">${runs.slice(0, 30).map(r => html`<${NL.RunRow} key=${r.run_id} r=${r} />`)}</div></${NL.Section}>
      ${c.last_error ? html`<div class="note note-warn small">Last problem: ${c.last_error}</div>` : null}
    </${NL.Sheet}>`;
  };
  NL.openCampaign = name => NL.open(NL.CampaignSheet, { name }, { key: 'campaign:' + name });

  /* demo mode: one campaign in the shape the keeper's summary() serves (tools/executor/campaigns.py) —
     demo.js puts NL.demoCampaignStates(T) into the synthetic state as `campaign_states`. T = the demo tick (4 s). */
  const DEMO_T0 = Date.now();
  NL.demoCampaignStates = (T) => {
    T = T || 0;
    const iso = ms => { const d = new Date(ms), p = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
    const start = DEMO_T0 - 5 * 3600e3, at = min => iso(start + min * 60e3);
    const name = iso(start).slice(0, 10) + '-sparse-routing-sprint';
    const passes = 14 + Math.floor(T / 15);
    const nextMin = 20 - (Math.floor(T / 3) % 20);
    const dispatch = [
      { ts: at(212), skill: 'experiment', target: 'moe', result: 'started', run_id: 'r-moe' },
      { ts: at(236), skill: 'improve', target: 'rl', result: 'refused: rl is waiting for the PI (Gate 2 — more FULL runs than the brief allows)' },
      { ts: at(251), skill: 'analyze', target: 'ana-1', result: 'started', run_id: 'r-ana' },
      { ts: at(268), skill: 'lit-review', target: 'lit-1', result: 'started', run_id: 'r-lit' },
      { ts: at(284), skill: 'ideate', target: 'hub', result: 'refused: the brief allows 2 idea(s) in flight' }];
    return [{
      name, file: `lab/campaigns/${name}.md`, status: 'active', created: at(0), deadline: iso(start + 12 * 3600e3),
      budget: { agent_minutes: 12 * 2 * 60, max_cycles: 0, spend_usd: 0 }, spend_cap_usd: null, used_minutes: 618 + T * 1.5, cycle_minutes: 90, repeat_minutes: 20,
      gate3_auto: false, consecutive_failures: 0, max_failures: 4, next_cycle_at: iso(Date.now() + nextMin * 60e3),
      paused_reason: null, last_error: null, cycles: passes, spent_usd: null, demo_spend: true, paused_by_lab: false,
      last_cycles: [{ run_id: 'c-' + passes, outcome: 'completed', progress: true }],
      studies: { moe: { member: true, waiting: null, hold: false, gate3_done: false },
        rl: { member: true, waiting: 'Gate 2 — more FULL runs than the brief allows', hold: false, gate3_done: false },
        'ana-1': { member: true, waiting: null, hold: false, gate3_done: false },
        'lit-1': { member: true, waiting: null, hold: false, gate3_done: false } },
      dispatch_log: dispatch,
      questions: [{ ts: at(262), run_id: 'r-c13', index: 0,
        question: 'Two seeds of moe diverge at step 6k. Re-run them with the balance loss, or drop the seed and move on?' }],
      gate3_log: [],
      events: [{ ts: at(0), what: 'started' }, { ts: at(41), what: 'pass 2: filed 3 ideas into the Campaign Log' },
        { ts: at(97), what: 'moe: Gate 1 approved within the signed bounds' }, { ts: at(150), what: 'pass 7 hit a usage limit — resumed when it lifted' },
        { ts: at(236), what: 'rl: waiting for you (Gate 2)' }, { ts: at(262), what: 'a pass left a question for you' },
        { ts: at(284), what: `pass ${passes}: 2 steps started, 1 refused` }],
    }];
  };
})();
