/* Newts' Lab — signatures. One pattern for every place the PI signs: the review bundle and the
   signing controls in the same sheet (reading never closes it), exactly what gets written, an explicit
   confirm, and a way to withdraw the signature. Gate 1 (proposal, optionally its envelope), Gate 2
   (edit the envelope, then sign), Gate 3 (readiness checklist + type the study name), the loop brief,
   and reviving a parked/killed idea. Agents can't sign any of these — the signature guard denies it. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, cls } = NL;

  const Bundle = ({ slug, gate }) => {
    const [b, setB] = useState(null);
    useEffect(() => { let on = true; NL.api('/api/read', { what: 'gate', idea: slug, gate }).then(x => on && setB(x)); return () => { on = false; }; }, [slug, gate]);
    if (!b) return html`<${NL.Spinner} />`;
    if (!b.ok) return html`<div class="note note-warn">${b.error || 'could not read the review bundle'}</div>`;
    return html`<div class="bundle">${(b.sections || []).map((s2, i) => html`<details class="bundle-sec" open=${i < 3}>
      <summary>${s2.title}<${NL.EditorLink} path=${s2.path} /></summary>${/\.(ya?ml|json|jsonl|txt|tex|bib|csv)$/i.test(s2.path || s2.title || '') || /^\s*[{[]/.test(s2.text || '')
        ? html`<pre class="plain">${s2.text || '(empty)'}</pre>` : html`<${NL.Markdown} text=${s2.text || '(empty)'} />`}</details>`)}
      ${b.note ? html`<p class="muted small">${b.note}</p>` : null}</div>`;
  };

  const Revoke = ({ slug, what, label }) => html`<button class="link small danger" onClick=${async () => {
    if (await NL.confirm({ title: 'Withdraw your signature?', body: label || 'The agents will treat it as unsigned again. Logged.', ok: 'Withdraw', danger: true }))
      NL.act('/api/gate/revoke', { idea: slug, what, confirm: true }, 'Signature withdrawn');
  }}>Withdraw my signature</button>`;

  /* ── Gate 1 ─────────────────────────────────────────────────────────────── */
  const Gate1 = ({ it }) => {
    const [env, setEnv] = useState(false);
    const signed = it.gate_signed || it.state !== 'proposal' && !it.gate;
    const sign = async () => {
      const ok = await NL.confirm({ title: `Sign Gate 1 for “${it.title || it.id}”?`, ok: 'Sign the proposal',
        body: html`<p>This records your approval in <span class="mono">studies/${it.id}/proposal.md</span>${env ? ' — including its Gate-2 envelope (§5)' : ''}, logged. Next: create the project repo.</p>` });
      if (!ok) return;
      const r = await NL.act('/api/gate', { idea: it.id, gate: 1, envelope: env, confirm: true }, 'Proposal signed');
      if (r.ok && !(r.launch && r.launch.run_id)) {
        if (await NL.confirm({ title: 'Create the project repo now?', body: 'Runs /spawn-project: the repo, its config from the proposal, and a green smoke test.', ok: 'Create it', cancel: 'Later' }))
          NL.launch({ skill: 'spawn-project', target: it.id });
      } else if (r.launch && r.launch.run_id) NL.openRun(r.launch.run_id);
    };
    return html`<div class="signbox">
      <div class="signbox-h">Gate 1 · approve the proposal</div>
      <p>You approve the hypothesis, the frozen evaluation, the staged plan with its promotion criteria, the budgets and the kill criteria. Nothing is built or spent before this.</p>
      ${signed ? html`<div class="note note-ok">✓ Signed${it.state === 'proposal' ? ' — the project repo is created next' : ''}.</div>
        ${it.state === 'proposal' ? html`<div class="row"><${NL.Btn} kind="primary" onClick=${() => NL.launch({ skill: 'spawn-project', target: it.id })}>Create the project repo</${NL.Btn}><${Revoke} slug=${it.id} what="gate1" /></div>` : null}`
        : html`<label class="check"><input type="checkbox" checked=${env} onChange=${e => setEnv(e.target.checked)} /> Also approve the proposal's Gate-2 envelope (§5), so FULL runs within it can proceed once the project exists</label>
        <div class="row"><${NL.Btn} kind="primary" onClick=${sign}>Sign Gate 1</${NL.Btn}></div>`}
    </div>`;
  };

  /* ── Gate 2 — the envelope editor ───────────────────────────────────────── */
  NL.EnvelopeEditor = ({ it }) => {
    const e = it.envelope || {};
    const [v, setV] = useState({ full_runs: e.full_cap || 0, per_run_max_minutes: e.per_cap || 0, total_max_minutes: e.total_cap || 0, expires: e.expires && e.expires !== 'None' ? e.expires : '' });
    const set = (k, x) => setV(o => ({ ...o, [k]: x }));
    const changed = +v.full_runs !== +(e.full_cap || 0) || +v.per_run_max_minutes !== +(e.per_cap || 0) || +v.total_max_minutes !== +(e.total_cap || 0) || (v.expires || '') !== (e.expires && e.expires !== 'None' ? e.expires : '');
    const used = (e.full_done || 0) + (e.full_resv || 0), usedMin = (e.min_done || 0) + (e.min_resv || 0);
    const save = async (sign) => {
      const ok = await NL.confirm({ title: sign ? 'Sign this envelope?' : 'Save the envelope (unsigned)?', ok: sign ? 'Sign' : 'Save',
        body: sign ? html`<p>Authorizes up to <b>${v.full_runs}</b> FULL runs of at most <b>${v.per_run_max_minutes}</b> min each, <b>${v.total_max_minutes}</b> min in total${v.expires ? `, until ${v.expires}` : ''}. Written to the project's <span class="mono">control.yaml</span>, logged.</p>`
          : html`<p>${e.signed && changed ? 'Changing the values withdraws the current signature until you sign again.' : 'Saved without a signature — FULL runs still need your approval.'}</p>` });
      if (ok) NL.act('/api/envelope', { idea: it.id, confirm: true, sign, values: v }, sign ? 'Envelope signed' : 'Envelope saved');
    };
    return html`<div class="signbox">
      <div class="signbox-h">Gate 2 · the FULL-run envelope ${e.signed ? html`<${NL.Pill} tone=${e.status === 'active' ? 'ok' : 'warn'}>${e.status}</${NL.Pill}>` : html`<${NL.Pill} tone="muted">unsigned</${NL.Pill}>`}</div>
      <p>Smoke and pilot runs are autonomous. FULL-scale runs need your signature — per run, or in advance for a batch inside this envelope.</p>
      <div class="grid2">
        <${NL.Field} label="FULL runs" hint=${e.full_cap ? `${used} used or reserved` : null}><${NL.Input} type="number" min="0" value=${v.full_runs} onInput=${x => set('full_runs', x)} /></${NL.Field}>
        <${NL.Field} label="Minutes per run"><${NL.Input} type="number" min="0" value=${v.per_run_max_minutes} onInput=${x => set('per_run_max_minutes', x)} /></${NL.Field}>
        <${NL.Field} label="Total minutes" hint=${e.total_cap ? `${usedMin} used or reserved` : null}><${NL.Input} type="number" min="0" value=${v.total_max_minutes} onInput=${x => set('total_max_minutes', x)} /></${NL.Field}>
        <${NL.Field} label="Expires" hint="optional"><${NL.Input} type="date" value=${v.expires} onInput=${x => set('expires', x)} /></${NL.Field}>
      </div>
      ${e.full_cap ? html`<div class="capacity"><span>FULL runs <${NL.Bar} value=${used} max=${e.full_cap} tone=${used >= e.full_cap ? 'warn' : ''} /> ${used}/${e.full_cap}</span>
        ${e.total_cap ? html`<span>minutes <${NL.Bar} value=${usedMin} max=${e.total_cap} tone=${usedMin >= e.total_cap ? 'warn' : ''} /> ${usedMin}/${e.total_cap}</span>` : null}</div>` : null}
      <div class="row">${!e.signed || changed ? html`<${NL.Btn} kind="primary" disabled=${!(+v.full_runs || +v.per_run_max_minutes || +v.total_max_minutes)} onClick=${() => save(true)}>Sign the envelope</${NL.Btn}>` : null}
        ${changed ? html`<${NL.Btn} onClick=${() => save(false)}>Save without signing</${NL.Btn}>` : null}
        ${e.signed && !changed ? html`<${Revoke} slug=${it.id} what="gate2" />` : null}</div>
    </div>`;
  };

  /* ── Gate 3 ─────────────────────────────────────────────────────────────── */
  const Gate3 = ({ it }) => {
    const [r, setR] = useState(null);
    const [launch, setLaunch] = useState(true);
    const load = () => NL.get(`/api/gate3/readiness?${NL.qs({ idea: it.id })}`).then(setR);
    useEffect(() => { load(); }, [it.id, it.state]);
    const sign = async () => {
      const typed = await NL.confirm({ title: 'Sign Gate 3', typed: it.id, ok: 'Sign Gate 3', danger: true,
        body: html`<p>Gate 3 authorizes <b>finalization</b>: the reproducibility pass, locking artifacts, and anything that leaves the lab. It is the one gate agents are never allowed near.</p>
          ${r && r.checks.some(c => !c.ok) ? html`<p class="warn">You're signing despite: ${r.checks.filter(c => !c.ok).map(c => c.label).join('; ')}.</p>` : null}` });
      if (!typed) return;
      const x = await NL.act('/api/gate', { idea: it.id, gate: 3, typed: it.id, confirm: true, launch }, 'Gate 3 signed');
      if (x.launch && x.launch.run_id) NL.openRun(x.launch.run_id);
      load();
    };
    return html`<div class="signbox signbox-g3">
      <div class="signbox-h">Gate 3 · finalize</div>
      <p>The paper passed internal review. Signing lets <span class="mono">/finalize</span> run for this study — once, started by you.</p>
      ${!r ? html`<${NL.Spinner} />` : html`<ul class="checklist">${r.checks.map(c => html`<li class=${c.ok ? 'ok' : c.blocking ? 'bad' : 'warn'}><span>${c.ok ? '✓' : c.blocking ? '✕' : '!'}</span><div><b>${c.label}</b><small>${c.detail}</small></div></li>`)}</ul>`}
      ${r && r.signed ? html`${String(r.signed_via || '').startsWith('campaign:') ? html`<div class=${cls('note', r.valid ? 'note-ok' : 'note-warn')}>${r.valid ? '✓ Gate 3 was recorded by delegation' : 'Gate 3 was recorded by delegation, but it no longer counts'} — <span class="mono">${r.signed_via.slice(9)}</span>${r.valid ? ': the lab re-ran the paper audits and they were clean. Take it back (or hold this study) on the campaign card.' : ': ' + (r.valid_why || '')}</div>` : html`<div class="note note-ok">✓ Gate 3 is signed.</div>`}<div class="row">${it.state !== 'final' ? html`<${NL.Btn} kind="primary" onClick=${async () => {
            const x = await NL.act('/api/finalize', { idea: it.id, confirm: true }, '/finalize queued'); if (x.run_id) NL.openRun(x.run_id); }}>Start /finalize</${NL.Btn}>` : null}
          ${it.state !== 'final' ? html`<${Revoke} slug=${it.id} what="gate3" />` : null}</div>`
        : html`<label class="check"><input type="checkbox" checked=${launch} onChange=${e => setLaunch(e.target.checked)} /> Start <span class="mono">/finalize</span> right after signing, and watch it here</label>
        <div class="row"><${NL.Btn} kind="danger" disabled=${!r || !r.can_sign} onClick=${sign}>Sign Gate 3…</${NL.Btn}>
          ${r && !r.can_sign ? html`<span class="muted small">${r.checks.filter(c => c.blocking && !c.ok).map(c => c.detail).join('; ')}</span>` : null}</div>`}
    </div>`;
  };

  /* ── the gate sheet ─────────────────────────────────────────────────────── */
  NL.GateSheet = ({ slug, gate, onClose }) => {
    const s = NL.useLab();
    const it = NL.item(s, slug);
    if (!it) return html`<${NL.Sheet} title="Gate" onClose=${onClose}><${NL.Empty}>No such study.</${NL.Empty}></${NL.Sheet}>`;
    const G = gate === 3 ? Gate3 : gate === 2 ? NL.EnvelopeEditor : Gate1;
    return html`<${NL.Sheet} wide icon="✉" title=${`Gate ${gate} · ${it.title || it.id}`} sub=${html`<span class="row-wrap"><${NL.StatePill} state=${it.state} /><a class="link" href=${'#/study/' + it.id}>open the study</a></span>`} onClose=${onClose}>
      <div class="gate-grid"><div class="gate-sign"><${G} it=${it} /></div>
        <div class="gate-read"><h4>What you're signing</h4><${Bundle} slug=${slug} gate=${gate} />
          ${gate === 3 && it.has_paper ? html`<div class="row"><${NL.Btn} small onClick=${() => NL.openPaper(it.id)}>Open the paper</${NL.Btn}><${NL.Btn} small onClick=${() => NL.openClaims(it.id)}>Claims ↔ evidence</${NL.Btn}></div>` : null}</div></div>
    </${NL.Sheet}>`;
  };
  NL.openGate = (slug, gate) => { if (slug && gate) NL.open(NL.GateSheet, { slug, gate }, { key: 'gate' }); };

  /* ── the loop brief ─────────────────────────────────────────────────────── */
  NL.LoopBriefSheet = ({ slug, onClose }) => {
    const s = NL.useLab();
    const it = NL.item(s, slug) || { id: slug };
    const [doc, setDoc] = useState(null);
    const [mode, setMode] = useState('execute');
    const load = () => NL.api('/api/libdoc', { scope: 'project', slug, rel: 'LOOP_BRIEF.md' }).then(setDoc);
    useEffect(() => { load(); }, [slug]);
    const signed = doc && doc.ok && /-\s*\[[xX]\]\s*Authorized/.test(doc.text || '');
    useEffect(() => { const m = doc && doc.ok && /\*\*Mode:\*\*\s*`(execute|explore)`/.exec(doc.text || ''); if (m) setMode(m[1]); }, [doc]);
    const sign = async (launch) => {
      if (!await NL.confirm({ title: 'Authorize the research loop?', ok: launch ? 'Authorize and start' : 'Authorize',
        body: html`<p>The loop runs unattended within this brief, the project's frozen set and its signed envelope, in <b>${mode}</b> mode, until its stop conditions. Logged.</p>` })) return;
      const r = await NL.act('/api/loopbrief/sign', { idea: slug, mode, confirm: true, launch }, 'Loop authorized');
      if (r.launch && r.launch.run_id) NL.openRun(r.launch.run_id);
      load();
    };
    return html`<${NL.Sheet} wide icon="⟳" title=${`Loop brief · ${it.title || slug}`} onClose=${onClose}>
      ${!doc ? html`<${NL.Spinner} />` : !doc.ok ? html`<${NL.Empty} icon="⟳" title="No loop brief yet">The loop writes its brief on the first start. <div class="row"><${NL.Btn} kind="primary" onClick=${() => NL.launch({ skill: 'research-loop', target: slug })}>Start the loop (it drafts the brief)</${NL.Btn}></div></${NL.Empty}>`
      : html`<div class="gate-grid"><div class="gate-sign"><div class="signbox"><div class="signbox-h">Authorize the loop</div>
          ${signed ? html`<div class="note note-ok">✓ Authorized.</div><div class="row"><${NL.Btn} kind="primary" onClick=${() => NL.launch({ skill: 'research-loop', target: slug })}>Start the loop</${NL.Btn}><${Revoke} slug=${slug} what="loop" /></div>`
            : html`<${NL.Field} label="Mode"><${NL.Seg} value=${mode} onChange=${setMode} options=${[{ value: 'execute', label: 'Execute the plan' }, { value: 'explore', label: 'Explore' }]} /></${NL.Field}>
            <p class="muted small">${mode === 'explore' ? 'May expand the frontier and reopen non-headline decisions within the envelope.' : 'Runs PLAN.md and stops when it is done.'}</p>
            <div class="row"><${NL.Btn} onClick=${() => sign(false)}>Authorize</${NL.Btn}><${NL.Btn} kind="primary" onClick=${() => sign(true)}>Authorize and start</${NL.Btn}></div>`}</div></div>
        <div class="gate-read"><h4>The brief</h4><${NL.Markdown} text=${doc.text} /></div></div>`}
    </${NL.Sheet}>`;
  };

  NL.revive = async (it) => {
    const reason = await NL.confirm({ title: `Bring back “${it.title || it.id}”?`, input: 'Why it comes back (recorded)', placeholder: 'e.g. new evidence from …', ok: 'Revive' });
    if (!reason) return;
    NL.act('/api/revive', { idea: it.id, reason, to: 'triaged', confirm: true }, 'Revived — back in Ideas');
  };
})();
