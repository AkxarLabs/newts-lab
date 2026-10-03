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
  NL.campaignsOf = s => (s.campaign_states || []);
  NL.liveCampaigns = s => NL.campaignsOf(s).filter(c => ['active', 'finishing', 'stopping', 'paused', 'stalled'].includes(c.status));

  const left = c => { if (!c.deadline) return null; const ms = new Date(c.deadline) - Date.now(); if (ms <= 0) return 'deadline passed';
    const h = Math.floor(ms / 3600e3), m = Math.round((ms % 3600e3) / 60e3); return (h ? `${h} h ` : '') + `${m} min left`; };
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

  /* a question a pass left: answer it here and the next pass gets the answer */
  const CampaignQuestion = ({ c, q }) => {
    const [text, setText] = useState('');
    const send = async () => { if (!text.trim()) return; const x = await act(c, 'answer', { index: q.index, text: text.trim() }); if (x && x.ok) setText(''); };
    return html`<div class=${cls('inrow', q.answer ? 'sev-info' : 'sev-warn')}><div class="inrow-main"><span class="inrow-ico">?</span><span class="inrow-t"><b>${q.question}</b>
      <small>${NL.hhmm(q.ts)}${q.answer ? html` — you answered: <b>${NL.clip(q.answer, 120)}</b>${q.delivered ? ' (the next pass got it)' : ' (the next pass gets it)'}` : ' — your answer goes to the next pass'}</small></span></div>
      ${q.answer ? null : html`<div class="row grow"><${NL.Input} value=${text} onInput=${setText} onEnter=${send} placeholder="Your answer…" /><${NL.Btn} small kind="primary" onClick=${send} disabled=${!text.trim()}>Answer</${NL.Btn}></div>`}</div>`;
  };

  NL.CampaignCard = ({ c, compact }) => {
    const k = counts(c);
    const b = c.budget || {};
    const pct = b.agent_minutes ? Math.min(100, Math.round(100 * (c.used_minutes || 0) / b.agent_minutes)) : null;
    return html`<div class=${cls('camp-card', 'st-' + c.status, compact && 'compact')}>
      <div class="row between"><button type="button" class="link camp-title" onClick=${() => NL.openCampaign(c.name)}>${NL.clip(c.name.replace(/^\d{4}-\d{2}-\d{2}-/, ''), compact ? 28 : 60)}</button>
        <${NL.Pill} tone=${TONE[c.status] || 'muted'}>${TONE[c.status] === 'live' ? html`<i class="dot-live"></i>` : null}${WORD[c.status] || c.status}</${NL.Pill}></div>
      <div class="muted small">${[`pass ${c.cycles || 0}`, left(c), nextIn(c), `${Math.round(c.used_minutes || 0)} agent-min${b.agent_minutes ? ' of ' + Math.round(b.agent_minutes) : ''}`].filter(Boolean).join(' · ')}</div>
      ${pct != null ? html`<${NL.Bar} value=${pct} max=${100} />` : null}
      <div class="row gap wrap small">${k.n ? html`<span>${NL.plural(k.n, 'study', 'studies')}</span>` : html`<span class="muted">no studies yet</span>`}
        ${k.waiting ? html`<${NL.Pill} tone="ask">${k.waiting} waiting for you</${NL.Pill}>` : null}
        ${c.gate3_auto ? html`<${NL.Pill} tone="state" title="papers may finalize without you">Gate 3 delegated</${NL.Pill}>` : null}
        ${(c.questions || []).length ? html`<${NL.Pill} tone="ask">${c.questions.length} question${c.questions.length > 1 ? 's' : ''}</${NL.Pill}>` : null}</div>
      ${c.paused_reason && ['paused', 'stalled'].includes(c.status) ? html`<div class="small warn">${c.paused_reason}</div>` : null}
      ${!compact ? html`<div class="row gap">${c.status === 'active' || c.status === 'finishing' ? html`<${NL.Btn} small onClick=${() => act(c, 'pause')}>Pause</${NL.Btn}>` : null}
        ${['paused', 'stalled'].includes(c.status) ? html`<${NL.Btn} small kind="primary" onClick=${() => act(c, 'resume')}>Resume</${NL.Btn}>` : null}
        ${!['done', 'stopped', 'stopping'].includes(c.status) ? html`<${NL.Btn} small kind="ghost" onClick=${() => act(c, 'stop')}>Stop…</${NL.Btn}>` : null}
        <${NL.Btn} small kind="ghost" onClick=${() => NL.openCampaign(c.name)}>Details</${NL.Btn}></div>` : null}</div>`;
  };

  NL.CampaignSheet = ({ name, onClose }) => {
    const s = NL.useLab();
    const c = NL.campaignsOf(s).find(x => x.name === name);
    const runs = (s.runs || []).filter(r => r.campaign === name);
    if (!c) return html`<${NL.Sheet} title="Campaign" onClose=${onClose}><${NL.Empty}>This campaign isn't being kept on this lab.</${NL.Empty}></${NL.Sheet}>`;
    const studies = Object.entries(c.studies || {}).filter(([, v]) => v.member);
    return html`<${NL.Sheet} wide title=${c.name} sub=${html`${WORD[c.status] || c.status} · <button type="button" class="link" onClick=${() => { onClose(); NL.openDoc('lab', null, c.file.replace(/^lab\//, '')); }}>the signed brief</button>`} onClose=${onClose} icon="⟳">
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
        <div class="camp-events">${(c.events || []).slice().reverse().map(e => html`<div><span class="mono muted">${NL.hhmm(e.ts)}</span> ${e.what}</div>`)}</div></${NL.Section}>
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
})();
