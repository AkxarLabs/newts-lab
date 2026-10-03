/* Newts' Lab — runs as conversations. A run is one agent session the PI started (a procedure or a
   free-form instruction); the run sheet streams it like a chat: the agent's messages, its tool calls
   folded into groups, subagents inline, its questions as forms you answer in place, and the report
   with its next step as a button. Also: the runs list, and the per-agent inspector. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useRef, useMemo, cls } = NL;

  /* ── live transcript (polls /api/run/tail while the sheet is open) ──────── */
  function useRun(id) {
    const [detail, setDetail] = useState(null);
    const [lines, setLines] = useState([]);
    const [err, setErr] = useState(null);
    const st = useRef({ offset: 0, status: null, last: 0, alive: true, skipped: 0 });
    useEffect(() => {
      st.current = { offset: 0, status: null, last: 0, alive: true, skipped: 0 };
      setLines([]); setDetail(null); setErr(null);
      if (NL.DEMO) return undefined;
      let timer = null;
      const loadDetail = async () => {
        const d = await NL.get(`/api/run?${NL.qs({ run_id: id })}`);
        if (!st.current.alive) return;
        if (d.ok) { setDetail(d.run); st.current.last = Date.now(); } else setErr(d.error || 'no such run');
      };
      const tick = async () => {
        const t = await NL.get(`/api/run/tail?${NL.qs({ run_id: id, offset: st.current.offset })}`);
        if (!st.current.alive) return;
        if (t.ok) {
          if (t.skipped && !st.current.offset) st.current.skipped = t.skipped;
          st.current.offset = t.offset;
          if (t.lines && t.lines.length) setLines(prev => { const next = prev.concat(t.lines); return next.length > 2500 ? next.slice(-2000) : next; });
          if (t.status !== st.current.status || Date.now() - st.current.last > 5000) { st.current.status = t.status; await loadDetail(); }
          const done = NL.RUN_DONE.has(t.status) && t.eof;
          timer = setTimeout(tick, done ? 6000 : 1400);
        } else { setErr(t.error || 'no such run'); timer = setTimeout(tick, 5000); }
      };
      tick();
      return () => { st.current.alive = false; clearTimeout(timer); };
    }, [id]);
    const s = NL.useLab();
    const live = NL.run(s, id);        // the snapshot's compact copy is fresher for status/elapsed
    const run = detail ? { ...detail, ...(live || {}), qa: detail.qa, attempts: detail.attempts, transcript: detail.transcript } : live;
    return { run, lines, err, skipped: st.current.skipped, reload: () => { st.current.last = 0; } };
  }

  /* ── transcript → conversation blocks ──────────────────────────────────── */
  const EDITS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'apply_patch', 'edit', 'write', 'patch']);
  const SPAWNS = new Set(['Agent', 'Task', 'task', 'spawn_agent']);
  function toBlocks(lines) {
    const out = [];
    let group = null;
    const flush = () => { if (group) { out.push(group); group = null; } };
    for (const l of lines) {
      if (l.k === 'tool' && !SPAWNS.has(l.tool)) {
        if (!group || group.who !== (l.who || null)) { flush(); group = { k: 'tools', who: l.who || null, items: [] }; }
        group.items.push(l);
        continue;
      }
      flush();
      if (l.k === 'tool') out.push({ k: 'spawn', who: l.who || null, t: l.t, tool: l.tool });
      else if (l.k === 'text' && out.length && out[out.length - 1].k === 'text' && out[out.length - 1].who === (l.who || null)) out[out.length - 1].t += '\n\n' + l.t;
      else out.push({ ...l, who: l.who || null });
    }
    flush();
    return out;
  }
  function toolSummary(items) {
    const n = { run: 0, edit: 0, read: 0, other: 0 };
    for (const i of items) {
      if (i.tool === 'Bash' || i.tool === 'bash' || i.tool === 'shell' || i.tool === 'exec_command') n.run++;
      else if (EDITS.has(i.tool)) n.edit++;
      else if (/read|grep|glob|list|search|fetch/i.test(i.tool || '')) n.read++;
      else n.other++;
    }
    const parts = [];
    if (n.run) parts.push(`ran ${NL.plural(n.run, 'command')}`);
    if (n.edit) parts.push(`edited ${NL.plural(n.edit, 'file')}`);
    if (n.read) parts.push(`read ${NL.plural(n.read, 'thing')}`);
    if (n.other) parts.push(NL.plural(n.other, 'other step'));
    return parts.join(' · ');
  }

  const Who = ({ who }) => who ? html`<span class="msg-who">${who}</span>` : null;
  const ToolGroup = ({ b, last }) => {
    const [open, setOpen] = useState(false);
    const show = open ? b.items : [];
    const tail = b.items[b.items.length - 1];
    return html`<div class=${cls('tgroup', open && 'open')}>
      <button type="button" class="tgroup-head" onClick=${() => setOpen(!open)} aria-expanded=${open}>
        <span class="tg-caret">${open ? '▾' : '▸'}</span><${Who} who=${b.who} /><span class="tg-sum">${toolSummary(b.items)}</span>
        ${!open && last ? html`<span class="tg-last"><b>${tail.tool}</b> ${NL.clip(tail.t, 90)}</span>` : null}</button>
      ${show.map(i => html`<div class="tline"><b>${i.tool}</b> <span>${i.t}</span></div>`)}</div>`;
  };
  const Block = ({ b, last }) => {
    switch (b.k) {
      case 'text': return html`<div class="msg"><${Who} who=${b.who} /><${NL.Markdown} text=${b.t} /></div>`;
      case 'you': return html`<div class="msg msg-you"><span class="msg-who">${b.by === 'you' ? (b.kind === 'answer' ? 'you answered' : b.kind === 'permission' ? 'you decided' : 'you') : b.by}</span>${b.t}</div>`;
      case 'tools': return html`<${ToolGroup} b=${b} last=${last} />`;
      case 'spawn': return html`<div class="spawn"><span class="spawn-ico">⤷</span><span>started a subagent</span> <b>${NL.clip(b.t, 120)}</b></div>`;
      case 'sub': return html`<div class="subres"><div class="subres-h">↩ <b>${b.who || 'subagent'}</b> handed back</div><div class="subres-t">${NL.clip(b.t, 1800)}</div></div>`;
      case 'err': return html`<div class="msg-err"><${Who} who=${b.who} />${b.t}</div>`;
      case 'end': return html`<div class="msg-end">${'■ turn ended'}${b.cost != null ? html` <span class="muted">· $${(+b.cost).toFixed(3)}</span>` : null}</div>`;
      case 'attempt': case 'start': return html`<div class="msg-div"><span>${b.t}</span></div>`;
      default: return html`<div class="tline muted">${b.t}</div>`;
    }
  };

  /* ── the question card (AskUserQuestion) ───────────────────────────────── */
  const AskCard = ({ r }) => {
    const qs = (((r.pending_question || {}).input || {}).questions) || [];
    const [ans, setAns] = useState({});
    const [other, setOther] = useState({});
    const key = (r.pending_question || {}).tool_use_id;
    useEffect(() => { setAns({}); setOther({}); }, [key]);
    const pick = (q, label) => setAns(a => {
      if (!q.multiSelect) return { ...a, [q.question]: label };
      const cur = new Set(a[q.question] || []); cur.has(label) ? cur.delete(label) : cur.add(label);
      return { ...a, [q.question]: [...cur] };
    });
    const answers = () => { const o = { ...ans }; for (const [k, v] of Object.entries(other)) if (v.trim()) o[k] = v.trim(); return o; };
    const send = async () => {
      const a = answers();
      if (!Object.keys(a).length) return NL.toast('Pick an option, or type your own answer', 'warn');
      const x = await NL.act('/api/run/answer', { run_id: r.run_id, answers: a });
      return x;
    };
    return html`<div class="ask">
      <div class="ask-h"><span class="ask-ico">?</span> ${r.pid ? 'The agent is asking you — it is waiting for your answer' : 'The agent asked you — your answer resumes it'}</div>
      ${qs.map(q => html`<fieldset class="ask-q"><legend>${q.header ? html`<span class="ask-tag">${q.header}</span>` : null}${q.question}</legend>
        ${(q.options || []).map(o => {
          const on = q.multiSelect ? (ans[q.question] || []).includes(o.label) : ans[q.question] === o.label;
          return html`<button type="button" class=${cls('ask-opt', on && 'on')} role=${q.multiSelect ? 'checkbox' : 'radio'} aria-checked=${on} onClick=${() => pick(q, o.label)}>
            <span class="ask-mark">${q.multiSelect ? (on ? '☑' : '☐') : (on ? '◉' : '○')}</span><span><b>${o.label}</b>${o.description ? html`<small>${o.description}</small>` : null}</span></button>`;
        })}
        <${NL.Input} value=${other[q.question] || ''} onInput=${v => setOther(o => ({ ...o, [q.question]: v }))} placeholder="…or type your own answer" onEnter=${send} />
      </fieldset>`)}
      <div class="ask-actions"><${NL.Btn} kind="primary" onClick=${send}>Answer and continue</${NL.Btn}></div></div>`;
  };

  const PermissionRows = ({ r }) => {
    const s = NL.useLab();
    const items = ((s.attention) || []).filter(a => a.kind === 'permission' && a.run_id === r.run_id);
    if (!items.length) return null;
    return html`${items.map(a => html`<div class="perm"><div><b>${a.title}</b><div class="mono small">${a.body}</div></div>
      <div class="row"><${NL.Btn} small onClick=${() => NL.act('/api/run/permission', { run_id: r.run_id, n: a.detail.n, allow: false }, 'Denied')}>Deny</${NL.Btn}>
      <${NL.Btn} small kind="primary" onClick=${() => NL.act('/api/run/permission', { run_id: r.run_id, n: a.detail.n, allow: true }, 'Allowed once')}>Allow once</${NL.Btn}></div></div>`)}`;
  };

  const NEEDS = { gate1: 'Gate 1 — the proposal needs your signature', gate2: 'Gate 2 — FULL runs need your signature', gate3: 'Gate 3 — the paper needs your signature',
    kill_criteria: 'A kill criterion fired', null_result: 'A null result — decide what next', spawn_type: 'Pick the project type', other: 'It needs a decision from you' };
  const Report = ({ r }) => {
    const rep = r.report; if (!rep || !NL.RUN_DONE.has(r.status)) return null;
    return html`<div class=${cls('report', rep.needs_pi && 'report-needs')}>
      <div class="report-h">${rep.needs_pi ? '✋ ' + (NEEDS[rep.needs_pi] || rep.needs_pi) : r.status === 'completed' ? '✓ Finished' : NL.RUN_WORD[r.status]}</div>
      ${rep.summary ? html`<${NL.Markdown} text=${rep.summary} />` : null}
      <div class="row">
        ${rep.needs_pi && /^gate[123]$/.test(rep.needs_pi) && r.subject ? html`<${NL.Btn} kind="primary" onClick=${() => NL.openGate(r.subject, +rep.needs_pi.slice(-1))}>Review and sign</${NL.Btn}>` : null}
        ${rep.next ? html`<${NL.Btn} small=${!!rep.needs_pi} kind=${rep.needs_pi ? '' : 'primary'} onClick=${() => NL.launchCommand(rep.next, r.subject)}
          title=${rep.needs_pi ? 'the step after your decision' : ''}>${rep.needs_pi ? 'then ▸ ' : '▸ '}${rep.next}</${NL.Btn}>` : null}
      </div></div>`;
  };

  /* ── the run sheet ─────────────────────────────────────────────────────── */
  NL.RunSheet = ({ id, onClose }) => {
    const { run: r, lines, err, skipped } = useRun(id);
    const s = NL.useLab();
    const blocks = useMemo(() => toBlocks(lines), [lines]);
    const scroller = useRef();
    const [stick, setStick] = useState(true);
    const [reply, setReply] = useState('');
    useEffect(() => { const el = scroller.current; if (el && stick) el.scrollTop = el.scrollHeight; }, [blocks.length, r && r.status, stick]);
    const onScroll = e => { const el = e.target; setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 80); };
    if (!r) return html`<${NL.Sheet} title="Run" onClose=${onClose} wide>${err ? html`<${NL.Empty} icon="?">${err}</${NL.Empty}>` : html`<${NL.Spinner} />`}</${NL.Sheet}>`;
    const it = r.subject && NL.item(s, r.subject);
    const active = NL.RUN_ACTIVE.has(r.status);
    const budget = r.max_minutes ? r.max_minutes * 60 : null;
    const liveNow = r.transport === 'live' && (active || r.status === 'waiting_input') && r.pid;
    const canReply = r.session_id && (r.status === 'waiting_input' || NL.RUN_DONE.has(r.status) || liveNow);
    const sendReply = async () => { if (!reply.trim()) return; const x = await NL.act('/api/run/reply', { run_id: r.run_id, text: reply.trim() }); if (x.ok) setReply(''); };
    const hint = liveNow && active ? 'Message the agent while it works — it reads it after its current step (Ctrl+Enter)'
      : r.status === 'waiting_input' ? 'Your turn — reply in your own words (Ctrl+Enter)' : 'Reply — continues this same conversation (Ctrl+Enter to send)';
    const title = NL.runTitle(r);
    const sub = html`<span class="row-wrap"><${NL.RunPill} r=${r} />
      ${it ? html`<a class="chip" href=${'#/study/' + it.id}>${NL.clip(it.title || it.id, 40)}</a>` : html`<span class="chip">the lab</span>`}
      <span class="muted">${r.backend}${r.model_used || r.model ? ' · ' + (r.model_used || r.model) : ''}${r.attempt > 1 ? ' · attempt ' + r.attempt : ''}</span></span>`;
    const footer = html`<div class="runfoot">
      ${r.status === 'waiting_input' && r.pending_question ? null : canReply ? html`<div class="reply">
        <${NL.Textarea} rows="2" value=${reply} onInput=${setReply} onSubmit=${sendReply} placeholder=${hint} />
        <${NL.Btn} kind="primary" onClick=${sendReply} disabled=${!reply.trim()}>Send</${NL.Btn}></div>` : null}
      <div class="row">
        ${liveNow && active ? html`<${NL.Btn} onClick=${() => NL.act('/api/run/interrupt', { run_id: r.run_id })} title="Stop the current step; the session stays open for your next message">⏸ Interrupt</${NL.Btn}>` : null}
        ${active || (liveNow && r.status === 'waiting_input') ? html`<${NL.Btn} kind="danger" onClick=${async () => { if (await NL.confirm({ title: 'Stop this run?', body: 'The session ends now. It stays resumable — you can continue it later.', ok: 'Stop', danger: true })) NL.act('/api/run/stop', { run_id: r.run_id, confirm: true }, 'Stopping'); }}>■ Stop</${NL.Btn}>` : null}
        ${r.status === 'queued' ? html`<${NL.Btn} onClick=${() => NL.act('/api/run/cancel', { run_id: r.run_id }, 'Cancelled')}>Cancel</${NL.Btn}>` : null}
        ${NL.RUN_DONE.has(r.status) && r.session_id && r.status !== 'completed' ? html`<${NL.Btn} onClick=${() => NL.act('/api/run/resume', { run_id: r.run_id }, 'Resuming')}>↻ Resume</${NL.Btn}>` : null}
        <span class="grow"></span>
        ${r.transcript ? html`<${NL.EditorLink} path=${r.transcript}>transcript ↗</${NL.EditorLink}>` : null}
        <button class="link small" onClick=${async () => { const x = await NL.get(`/api/run/log?${NL.qs({ run_id: r.run_id })}`); NL.open(NL.TextSheet, { title: 'Supervisor log', sub: r.run_id, text: x.text || '(empty)' }); }}>supervisor log</button>
      </div></div>`;
    return html`<${NL.Sheet} title=${title} sub=${sub} onClose=${onClose} wide footer=${footer} icon=${r.kind === 'ask' ? '✎' : '▸'}>
      <div class="runmeta">
        ${r.elapsed_s != null ? html`<span><b>${NL.mins(r.elapsed_s)}</b>${budget ? html` of ${Math.round(r.max_minutes)}m <${NL.Bar} value=${r.elapsed_s} max=${budget} tone=${r.elapsed_s > budget * 0.85 ? 'warn' : ''} />` : null}</span>` : null}
        ${r.n_actions ? html`<span><b>${r.n_actions}</b> actions</span>` : null}
        ${(r.subagents || []).length ? html`<span><b>${r.subagents.length}</b> subagents</span>` : null}
        ${r.usage && r.usage.cost_usd != null ? html`<span>≈ $${(+r.usage.cost_usd).toFixed(2)}</span>` : null}
        ${r.status === 'queued' ? html`<span>${r.not_before ? 'scheduled for ' + NL.hhmm(r.not_before) : 'starts as soon as a slot is free'}</span>` : null}
      </div>
      ${r.reason && !active && !['completed', 'waiting_input', 'queued'].includes(r.status) ? html`<div class="note note-warn">${r.reason}</div>` : null}
      <${Lineage} r=${r} />
      <${Subagents} r=${r} />
      <div class="convo" ref=${scroller} onScroll=${onScroll}>
        ${skipped ? html`<div class="msg-div"><span>earlier output skipped (${Math.round(skipped / 1024)} KB)</span></div>` : null}
        ${!blocks.length ? html`<div class="muted pad">${r.status === 'queued' ? 'Waiting for a free slot…' : active ? 'Starting up…' : 'No transcript yet.'}</div>` : null}
        ${blocks.map((b, i) => html`<${Block} key=${i} b=${b} last=${i === blocks.length - 1 && active} />`)}
        ${active && r.last_action ? html`<div class="now"><i class="dot-live"></i> <b>${r.last_action.tool || ''}</b> ${NL.clip(r.last_action.summary, 140)}</div>` : null}
        <${PermissionRows} r=${r} />
        ${r.status === 'waiting_input' && r.pending_question ? html`<${AskCard} r=${r} />` : null}
        <${Report} r=${r} />
        ${(r.qa || []).length ? html`<details class="qa"><summary>${NL.plural(r.qa.length, 'earlier answer')}</summary>${r.qa.map(q => html`<div class="qa-row"><span class="muted">${NL.hhmm(q.answered_at)}</span>
          ${((q.question || {}).questions || []).map(x => x.question).join(' · ')} → <b>${Object.values(q.answers || {}).map(v => Array.isArray(v) ? v.join(', ') : v).join(' · ') || q.response || ''}</b></div>`)}</details>` : null}
      </div>
      ${!stick ? html`<button class="jump" onClick=${() => setStick(true)}>↓ latest</button>` : null}
    </${NL.Sheet}>`;
  };
  /* where this run came from and what it started: the PI, a chain, a repeat, a campaign pass */
  const Lineage = ({ r }) => {
    const s = NL.useLab();
    const all = s.runs || [];
    const parent = r.parent && all.find(x => x.run_id === r.parent);
    const kids = all.filter(x => x.parent === r.run_id);
    const by = { chain: 'the previous step', repeat: 'a repeat', campaign: 'a campaign', 'campaign-gate3': 'the campaign (Gate 3 by delegation)',
      dashboard: 'you', cli: 'the command line', gate3: 'your Gate 3 signature' }[r.created_by] || r.created_by;
    if (!parent && !kids.length && !r.campaign) return null;
    return html`<div class="lineage">
      <span class="muted">Started by</span> ${parent ? html`<button type="button" class="chip click" onClick=${() => NL.openRun(parent.run_id)}>${NL.clip(NL.runTitle(parent), 48)}</button>` : html`<span>${by || 'you'}</span>`}
      ${r.campaign ? html`<button type="button" class="chip click" onClick=${() => NL.openCampaign(r.campaign)}>⟳ ${NL.clip(r.campaign.replace(/^\d{4}-\d{2}-\d{2}-/, ''), 32)}${r.campaign_cycle ? ' · pass ' + r.campaign_cycle : ''}</button>` : null}
      ${kids.length ? html`<span class="muted">→ started</span>${kids.slice(0, 8).map(k => html`<button type="button" class="chip click" onClick=${() => NL.openRun(k.run_id)}>${NL.clip(NL.runTitle(k), 36)} <${NL.RunPill} r=${k} /></button>`)}${kids.length > 8 ? html`<span class="muted">+${kids.length - 8}</span>` : null}` : null}
      ${r.campaign_retries ? html`<span class="muted">· retried ${r.campaign_retries}× after ${r.failure_kind || 'a failure'}</span>` : null}
    </div>`;
  };

  /* subagents as a tree (a subagent may spawn its own), each linked to its own trace */
  const Subagents = ({ r }) => {
    const s = NL.useLab();
    const subs = r.subagents || [];
    if (!subs.length) return null;
    const live = subs.filter(x => x.status === 'working').length;
    const ids = new Set(subs.map(x => x.id));
    const kidsOf = pid => subs.filter(x => (x.parent && ids.has(x.parent) ? x.parent : null) === pid);
    const traceOf = sa => (s.workers || []).find(w => (w.spawn_id && w.spawn_id === sa.id) || (sa.session && w.worker_id === sa.session));
    const Row = ({ sa, depth }) => {
      const w = traceOf(sa);
      return html`<div class=${cls('sub-row', sa.status === 'working' && 'on')} style=${{ marginLeft: (depth * 18) + 'px' }}>
        ${depth ? html`<span class="muted">↳</span>` : null}<${NL.RoleDot} role=${sa.type} /><b>${NL.roleOf(sa.type).label}</b><span class="grow clip">${sa.description || ''}</span>
        ${sa.background ? html`<span class="muted small" title="started in the background">bg</span>` : null}
        <span class="muted">${sa.status || ''}${sa.n_actions ? ' · ' + sa.n_actions + ' actions' : ''}</span>
        ${w ? html`<button type="button" class="link small" onClick=${() => NL.openWorker(w.worker_id)}>trace</button>` : null}
        ${sa.status === 'working' && sa.last_action ? html`<div class="sub-last">▸ ${NL.clip(sa.last_action, 140)}</div>` : null}
        ${sa.result ? html`<details class="sub-res"><summary>result</summary><div>${sa.result}</div></details>` : null}</div>
        ${kidsOf(sa.id).map(k => html`<${Row} key=${k.id} sa=${k} depth=${depth + 1} />`)}`;
    };
    return html`<details class="subs" open=${live > 0}><summary>${NL.plural(subs.length, 'subagent')}${live ? html` · <b>${live} working</b>` : null}</summary>
      ${kidsOf(null).slice().reverse().map(sa => html`<${Row} key=${sa.id} sa=${sa} depth=${0} />`)}</details>`;
  };
  NL.openRun = id => { if (id) NL.open(NL.RunSheet, { id }, { key: 'run:' + id }); };

  NL.TextSheet = ({ title, sub, text, onClose }) => html`<${NL.Sheet} title=${title} sub=${sub} onClose=${onClose} wide><pre class="plain">${text}</pre></${NL.Sheet}>`;

  /* ── run rows (Home rail, Runs page, Study page) ───────────────────────── */
  NL.RunRow = ({ r, compact }) => {
    const s = NL.useLab();
    const it = r.subject && NL.item(s, r.subject);
    const budget = r.max_minutes ? r.max_minutes * 60 : null;
    return html`<button type="button" class=${cls('runrow', compact && 'compact', 'tone-' + (NL.RUN_TONE[r.status] || 'muted'))} onClick=${() => NL.openRun(r.run_id)}>
      <span class="runrow-top"><${NL.RunPill} r=${r} /><b class="clip">${NL.runTitle(r)}</b></span>
      <span class="runrow-sub muted">${it ? NL.clip(it.title || it.id, 34) : 'the lab'}
        ${r.status === 'waiting_input' ? (r.pending_question ? ' · asking you' : ' · your turn') : NL.RUN_ACTIVE.has(r.status) && r.last_action ? ' · ' + NL.clip(r.last_action.summary || r.last_action.tool, 60) : r.finished ? ' · ' + NL.ago(r.finished) : ''}</span>
      ${NL.RUN_ACTIVE.has(r.status) && budget && r.elapsed_s != null ? html`<${NL.Bar} value=${r.elapsed_s} max=${budget} />` : null}</button>`;
  };

  /* ── the Runs page ─────────────────────────────────────────────────────── */
  const FILTERS = [
    { id: 'all', label: 'All', f: () => true },
    { id: 'needs', label: 'Waiting for you', f: r => r.status === 'waiting_input' || (r.report && r.report.needs_pi && NL.RUN_DONE.has(r.status)) },
    { id: 'live', label: 'Running', f: r => NL.RUN_ACTIVE.has(r.status) },
    { id: 'queued', label: 'Queued', f: r => r.status === 'queued' },
    { id: 'done', label: 'Finished', f: r => r.status === 'completed' },
    { id: 'bad', label: 'Failed or stopped', f: r => ['failed', 'timeout', 'killed'].includes(r.status) },
  ];
  NL.RunsPage = () => {
    const s = NL.useLab();
    const [f, setF] = useState('all');
    const [q, setQ] = useState('');
    const all = (s.runs || []).slice().sort((a, b) => (b.created || '').localeCompare(a.created || ''));
    const flt = FILTERS.find(x => x.id === f);
    const list = all.filter(flt.f).filter(r => !q || (NL.runTitle(r) + ' ' + (r.subject || '')).toLowerCase().includes(q.toLowerCase()));
    const x = NL.exec(s);
    const caps = x.caps || {};
    const working = (s.workers || []).filter(w => w.status === 'working');
    return html`<div class="page">
      <header class="page-head"><div><h1>Runs</h1><p class="lede">Every agent session started from here — each one is a conversation you can open, answer and continue.</p></div>
        <${NL.Btn} kind="primary" icon="＋" onClick=${() => NL.openStart()}>Start something</${NL.Btn}></header>
      <div class="statline">
        <span><b>${x.active || 0}</b> running of ${caps.total || '—'} slots</span><span><b>${x.queued || 0}</b> queued</span><span><b>${x.waiting || 0}</b> waiting for you</span>
        ${x.brake ? html`<span class="warn">⚠ daily limit reached — ${x.brake}</span>` : null}
        ${!NL.execOn(s) ? html`<span class="warn">Starting agents from the dashboard is off — <a class="link" href="#/settings/autonomy">turn it on</a></span>` : null}
      </div>
      ${working.length ? html`<${NL.Section} title="Agents at work now" count=${working.length}><div class="agents-strip">${working.slice(0, 24).map(w => html`<button type="button" class="agent-chip" onClick=${() => NL.openWorker(w.worker_id)}>
        <${NL.RoleDot} role=${w.role} /><span class="clip">${NL.clip(w.label || NL.roleOf(w.role).label, 34)}</span>${w.in_tool ? html`<span class="muted small">▸ ${w.in_tool.tool}</span>` : null}</button>`)}</div></${NL.Section}>` : null}
      ${(s.workers || []).some(w => w.interactive && w.status !== 'done') ? html`<${NL.Section} title="Sessions started outside the dashboard" count=${(s.workers || []).filter(w => w.interactive && w.status !== 'done').length}>
        <p class="muted small">Claude Code, Codex or opencode sessions opened in a terminal or an editor in this lab. The lab's hooks trace them; they aren't runs, so their questions stay in that session.</p>
        <div class="agents-strip">${(s.workers || []).filter(w => w.interactive && w.status !== 'done').slice(0, 12).map(w => html`<button type="button" class="agent-chip" onClick=${() => NL.openWorker(w.worker_id)}>
          <${NL.RoleDot} role=${w.role} /><span class="clip">${NL.clip(w.idea || w.project || 'the lab', 26)}</span><span class="muted small">${w.status}${(w.children || []).length ? ' · ' + w.children.length + ' subagents' : ''}</span></button>`)}</div></${NL.Section}>` : null}
      <div class="toolbar"><${NL.Tabs} tabs=${FILTERS.map(x2 => ({ id: x2.id, label: x2.label, count: x2.id === 'all' ? null : all.filter(x2.f).length || null }))} value=${f} onChange=${setF} />
        <input class="input search" placeholder="Filter…" value=${q} onInput=${e => setQ(e.target.value)} /></div>
      ${list.length ? html`<div class="runlist">${list.slice(0, 200).map(r => html`<${NL.RunRow} key=${r.run_id} r=${r} />`)}</div>`
        : html`<${NL.Empty} icon="▸" title=${all.length ? 'Nothing here' : 'No runs yet'}>${all.length ? 'Try another filter.' : html`Start one with <b>Start something</b>, or ask Newt from Home.`}</${NL.Empty}>`}
    </div>`;
  };

  /* ── the agent inspector (a worker = one agent or subagent) ───────────── */
  NL.WorkerSheet = ({ id, onClose }) => {
    const s = NL.useLab();
    const byId = x => ((s.workers) || []).find(w => w.worker_id === x);
    const w = byId(id);
    const [follow, setFollow] = useState(NL.Scene && NL.Scene.following() === id);
    if (!w) return html`<${NL.Sheet} title="Agent" onClose=${onClose}><${NL.Empty} icon="🦎">This agent has finished and left the lab.</${NL.Empty}></${NL.Sheet}>`;
    const anchor = NL.item(s, w.project || w.idea);
    const parent = w.parent && byId(w.parent);
    const kids = (w.children || []).map(byId).filter(Boolean);
    const acts = (w.recent_actions || []).slice().reverse();
    const run = (s.runs || []).find(r => (w.run_id && r.run_id === w.run_id) || (r.session_id && (r.session_id === w.session_id || r.session_id === w.worker_id)));
    const toggle = () => { if (!NL.Scene) return; if (NL.Scene.following() === id) { NL.Scene.stopFollow(); setFollow(false); } else { NL.go(''); NL.Scene.followWorker(id); setFollow(true); } };
    return html`<${NL.Sheet} title=${NL.clip(w.label || NL.roleOf(w.role).label, 70)} onClose=${() => { NL.Scene && NL.Scene.stopFollow(); onClose(); }}
      sub=${html`<span class="row-wrap"><${NL.RoleDot} role=${w.role} /> ${NL.roleOf(w.role).label} · <span class=${w.status === 'working' ? 'live' : 'muted'}>${w.status}</span> · ${anchor ? html`<a class="link" href=${'#/study/' + anchor.id}>${NL.clip(anchor.title || anchor.id, 30)}</a>` : 'the lab'}</span>`}>
      <div class="row"><${NL.Btn} small kind=${follow ? 'primary' : ''} onClick=${toggle}>${follow ? '◉ Following in the world' : '⊙ Follow in the world'}</${NL.Btn}>
        ${run ? html`<${NL.Btn} small onClick=${() => NL.openRun(run.run_id)}>Open its run</${NL.Btn}>` : null}
        ${parent ? html`<${NL.Btn} small onClick=${() => NL.openWorker(parent.worker_id)}>↑ Started by ${NL.clip(parent.label || NL.roleOf(parent.role).label, 30)}</${NL.Btn}>` : null}</div>
      ${w.interactive ? html`<div class="note small">A session started outside the dashboard (a terminal or an editor) — traced here by the lab's hooks; its questions stay in that session.</div>` : null}
      <div class="runmeta"><span><b>${w.n_actions || 0}</b> actions</span>${w.started ? html`<span>started ${NL.hhmm(w.started)}</span>` : null}${w.last_ts ? html`<span>last ${NL.hhmm(w.last_ts)}</span>` : null}${w.variant ? html`<span>variant ${w.variant}</span>` : null}</div>
      ${w.in_tool ? html`<div class="now"><i class="dot-live"></i> inside <b>${w.in_tool.tool || 'a tool'}</b> since ${NL.hhmm(w.in_tool.since)} — ${NL.clip(w.in_tool.summary, 200)}</div>` : null}
      ${w.result ? html`<div class="subres"><div class="subres-h">↩ handed back</div><div class="subres-t">${w.result}</div></div>` : null}
      ${kids.length ? html`<${NL.Section} title="Its subagents" count=${kids.length}>${kids.map(k => html`<button type="button" class="agent-chip wide" onClick=${() => NL.openWorker(k.worker_id)}><${NL.RoleDot} role=${k.role} /><span class="clip grow">${k.label || NL.roleOf(k.role).label}</span><span class="muted small">${k.status}</span></button>`)}</${NL.Section}>` : null}
      <${NL.Section} title="What it did">${acts.length ? html`<div class="timeline">${acts.map(a => html`<div class="tl-row"><span class="muted mono small">${NL.hhmm(a.ts)}</span><span class="grow">${a.text || ''}</span><span class="muted small">${a.kind || ''}</span></div>`)}</div>` : html`<div class="muted">No actions logged yet.</div>`}</${NL.Section}>
    </${NL.Sheet}>`;
  };
  NL.openWorker = id => NL.open(NL.WorkerSheet, { id }, { key: 'worker' });
})();
