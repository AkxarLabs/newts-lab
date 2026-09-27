/* Newts' Lab — getting started: the first-run setup wizard (#/setup/<step>): welcome → agents → autonomy → the
   /setup-lab interview as a conversation → the first step. Resumable, skippable. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, cls } = NL;

  /* the lab picker (#/labs) lives in machines.js — this computer's labs and every machine you reach over SSH */

  /* ── the setup wizard ───────────────────────────────────────────────────── */
  const STEPS = [{ id: 'welcome', label: 'Welcome' }, { id: 'agents', label: 'Agents' }, { id: 'autonomy', label: 'Autonomy' }, { id: 'interview', label: 'Your research' }, { id: 'start', label: 'First step' }];

  const Welcome = ({ next }) => {
    const s = NL.useLab();
    const li = s.lab_info || {};
    return html`<div class="wz-body">
      <h2>Welcome to ${li.name || 'your lab'}</h2>
      <p class="lede">Newts' Lab runs research with AI agents: they generate ideas, review literature, write proposals, run experiments and draft papers. You steer, and you sign the three gates.</p>
      <div class="concepts">
        <div class="concept"><span class="concept-ico">🏛</span><b>The lab</b><small>This folder — <span class="mono" title=${li.path || ''}>${(li.path || '').split(/[\/]/).filter(Boolean).slice(-1)[0] || ''}</span>. Ideas, studies, papers and the lab's knowledge live here.</small></div>
        <div class="concept"><span class="concept-ico">🛠</span><b>Projects</b><small>An approved study gets its own code repository next to the lab, where experiments run.</small></div>
        <div class="concept"><span class="concept-ico">✉</span><b>Three gates</b><small>Gate 1 approves a proposal · Gate 2 authorizes full-scale runs · Gate 3 finalizes a paper. Only you sign them.</small></div>
      </div>
      <div class="row end"><${NL.Btn} kind="primary" onClick=${next}>Set it up</${NL.Btn}></div></div>`;
  };
  const Agents = ({ next, back }) => {
    const s = NL.useLab();
    const ready = NL.backends(s).some(b => b.found && b.logged_in);
    return html`<div class="wz-body"><h2>Connect an agent</h2>
      <p class="lede">The lab drives command-line agents installed on this machine. Install at least one and sign in — the sign-in happens in the agent's own window, so this page never sees your credentials.</p>
      <${NL.AgentsSignIn} />
      <div class="row end"><${NL.Btn} onClick=${back}>Back</${NL.Btn}>${!ready ? html`<span class="muted small">You can continue and sign in later.</span>` : null}<${NL.Btn} kind="primary" onClick=${next}>${ready ? 'Continue' : 'Skip for now'}</${NL.Btn}></div></div>`;
  };
  const Autonomy = ({ next, back }) => {
    const s = NL.useLab();
    const x = NL.exec(s);
    const [v, setV] = useState({ launching: true, tier: 'medium', slots: 1, oversight: 'standard', backend: x.backend || 'claude', daily: (x.config || {}).daily_max_runs || 0 });
    const set = (k, val) => setV(o => ({ ...o, [k]: val }));
    const save = async () => {
      const lab = await NL.api('/api/lab/config', { confirm: true, changes: { budget_tier: v.tier, max_concurrent_runs: +v.slots || 1, oversight: v.oversight } });
      if (!lab.ok) return NL.toast(lab.error, 'bad');
      const ex = await NL.api('/api/executor/config', { confirm: true, changes: { backend: v.backend, daily_max_runs: +v.daily || 0 } });
      if (!ex.ok) return NL.toast(ex.error, 'bad');
      if (v.launching !== NL.execOn(s)) { const r = await NL.api('/api/executor/enable', { enabled: v.launching, confirm: true }); if (!r.ok) return NL.toast(r.error, 'bad'); }
      NL.toast('Saved', 'ok'); NL.refresh(); next();
    };
    return html`<div class="wz-body"><h2>How much should the lab do on its own?</h2>
      <p class="lede">You can change all of this later in Settings. Nothing here lets an agent sign a gate.</p>
      <${NL.Toggle} on=${v.launching} onChange=${x2 => set('launching', x2)} label="Start agents from the dashboard" sub="Every button that starts work runs the agent CLI here, as you. Off = the dashboard only records your commands." />
      <div class="grid2">
        <${NL.Field} label="Default agent"><${NL.Select} value=${v.backend} onChange=${x2 => set('backend', x2)} options=${NL.backends(s).map(b => ({ value: b.id, label: b.id + (b.found ? '' : ' (not installed)'), disabled: !b.found }))} /></${NL.Field}>
        <${NL.Field} label="Budget" hint="how many ideas, critics and parallel agents each step uses"><${NL.Seg} value=${v.tier} onChange=${x2 => set('tier', x2)} options=${[{ value: 'low', label: 'Low' }, { value: 'medium', label: 'Medium' }, { value: 'high', label: 'High' }]} /></${NL.Field}>
        <${NL.Field} label="Training runs at once" hint="how many experiments this machine can run in parallel (≈ GPUs)"><${NL.Input} type="number" min="1" value=${v.slots} onInput=${x2 => set('slots', x2)} /></${NL.Field}>
        <${NL.Field} label="Oversight" hint="strict = an independent overseer checks more steps"><${NL.Seg} value=${v.oversight} onChange=${x2 => set('oversight', x2)} options=${[{ value: 'standard', label: 'Standard' }, { value: 'strict', label: 'Strict' }]} /></${NL.Field}>
        <${NL.Field} label="Daily run limit" hint="0 = no limit"><${NL.Input} type="number" min="0" value=${v.daily} onInput=${x2 => set('daily', x2)} /></${NL.Field}>
      </div>
      <div class="row end"><${NL.Btn} onClick=${back}>Back</${NL.Btn}><${NL.Btn} kind="primary" onClick=${save}>Save and continue</${NL.Btn}></div></div>`;
  };
  const Interview = ({ next, back }) => {
    const s = NL.useLab();
    const run = NL.runs(s, r => r.skill === 'setup-lab').sort((a, b) => (b.created || '').localeCompare(a.created || ''))[0];
    const ready = NL.backends(s).some(b => b.found && b.logged_in !== false);
    return html`<div class="wz-body"><h2>Tell the lab about your research</h2>
      <p class="lede">A short interview with an agent: your research areas and first directions, compute, venue, which models to use for which roles. It asks a few questions at a time; you answer right here.</p>
      ${run ? html`<div class="wz-run"><${NL.RunRow} r=${run} />${run.status === 'waiting_input' ? html`<div class="note">It's waiting for your answer — open it to reply.</div>` : null}</div>` : null}
      <div class="row end"><${NL.Btn} onClick=${back}>Back</${NL.Btn}>
        ${!run || NL.RUN_DONE.has(run.status) && run.status !== 'completed' ? html`<${NL.Btn} kind="primary" disabled=${!ready} onClick=${() => NL.launch({ skill: 'setup-lab' })}>${run ? 'Start it again' : 'Start the interview'}</${NL.Btn}>` : null}
        ${run && !NL.RUN_DONE.has(run.status) ? html`<${NL.Btn} kind="primary" onClick=${() => NL.openRun(run.run_id)}>Open the interview</${NL.Btn}>` : null}
        <${NL.Btn} kind=${run && run.status === 'completed' ? 'primary' : ''} onClick=${next}>${run && run.status === 'completed' ? 'Continue' : 'Skip'}</${NL.Btn}></div>
      ${!ready ? html`<p class="muted small">Connect an agent first (step 2) to run the interview.</p>` : null}</div>`;
  };
  const FirstStep = ({ back, finish }) => html`<div class="wz-body"><h2>Where do you want to start?</h2>
    <p class="lede">Pick one — you can do all of them later from <b>Start something</b>.</p>
    <div class="onramps big">${[['campaign', '⟳', 'Start a campaign and walk away', 'Sign a direction, a time limit and a budget once; the lab carries ideas all the way to reviewed papers by itself, restarting through timeouts and usage limits, and only stops for what is outside your bounds.'],
      ['ideate', '✦', 'Explore a new direction', 'Describe a direction; the lab researches it, generates and critiques ideas, and files the best as studies.'],
      ['adopt', '⇲', 'Bring in what I have', 'An idea you had, a design, an existing repository or a draft paper — enter the lifecycle mid-way.'],
      ['discuss', '❝', 'Talk it through first', 'A one-question-at-a-time conversation with live research. Commits to nothing.'],
      ['compete', '◎', 'Compete on a target', 'A benchmark or a score to beat, with a fixed evaluation.']].map(([id, ico, t, sub]) =>
      html`<button type="button" class="onramp" onClick=${() => { finish(); NL.openStart({ intent: id }); }}><span class="intent-ico">${ico}</span><span><b>${t}</b><small>${sub}</small></span></button>`)}</div>
    <div class="row end"><${NL.Btn} onClick=${back}>Back</${NL.Btn}><${NL.Btn} onClick=${finish}>Go to the lab</${NL.Btn}></div></div>`;

  NL.SetupPage = ({ args }) => {
    const i = Math.max(0, STEPS.findIndex(x => x.id === (args[0] || 'welcome')));
    const go = j => NL.go('setup/' + STEPS[Math.max(0, Math.min(STEPS.length - 1, j))].id);
    const finish = async () => { await NL.api('/api/setup/complete', { done: true }); NL.ls.set('nl-setup-skip', true); NL.go(''); };
    const C = [Welcome, Agents, Autonomy, Interview, FirstStep][i];
    return html`<div class="page page-narrow wizard">
      <ol class="wz-steps">${STEPS.map((st, j) => html`<li class=${cls(j < i && 'done', j === i && 'cur')}><button type="button" onClick=${() => go(j)}><span>${j < i ? '✓' : j + 1}</span>${st.label}</button></li>`)}</ol>
      <${C} next=${() => go(i + 1)} back=${() => go(i - 1)} finish=${finish} />
      <div class="wz-skip"><button class="link small" onClick=${finish}>Skip setup — I'll do it later</button></div></div>`;
  };
})();
