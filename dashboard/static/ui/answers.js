/* Newts' Lab — answers without an agent. A question the lab's own live state already answers ("what needs
   me?", "what's running?", "what happened overnight?", "how much today?", "where is <study>?") is answered here,
   instantly and for free, instead of starting a Claude/Codex session that would spend ~50k tokens just loading
   its context. Anything that asks for WORK (run, write, compare, explain why…) still goes to an agent, and every
   answer offers "ask an agent anyway".

   NL.quickIntent(text, items) is pure (tested under node): → { intent, study } | null. */
(function () {
  'use strict';
  const NL = (window.NL = window.NL || {});

  // a request for work, judgement or explanation is an agent's — never answered from the snapshot
  const WORK = /\b(run|re-?run|start|launch|write|draft|compare|analy[sz]e|plan|fix|implement|try|make|create|design|review|critique|summari[sz]e|explain|why|should|suggest|recommend|propose|refactor|debug|investigate|read (the|this|that)|look into|figure out|find out why)\b/i;
  const ASKING = /^\s*(what|which|who|where|how|is|are|any|anything|show|list|did|has|have|whats|what's|status|give me|tell me)\b|\?\s*$/i;
  const INTENTS = [
    ['needs', /\b(needs? (me|you|my)|waiting (on|for) (me|you)|blocked on me|my (inbox|attention|turn)|to sign|what do i (need|have) to)\b/i],
    ['failed', /\b(fail(ed|ing|ure)?s?|errors?|broke(n)?|crash(ed)?|stuck|stall(ed)?|gone quiet|timed? ?out)\b/i],
    ['cost', /\b(cost|costs|spend|spent|spending|money|budget|\$|dollars?|tokens?)\b/i],
    ['overnight', /\b(overnight|last night|since (i|my|yesterday|this morning)|what (moved|happened|changed)|today so far|while i was (away|out|gone))\b/i],
    ['gates', /\bgates?\b/i],
    ['foryou', /\b(artifacts?|for (me|you) to (look|read|see)|anything (new )?for me|what did (the )?agents? (make|show|publish))\b/i],
    ['running', /\b(running|working|doing|busy|active|in progress|going on|happening|at work|agents?)\b/i],
  ];

  /** the study a question names: its id, its title, or most of its title's words */
  function studyIn(text, items) {
    const q = ` ${String(text).toLowerCase().replace(/[^a-z0-9 -]/g, ' ')} `;
    let best = null;
    for (const it of items || []) {
      const id = String(it.id || '').toLowerCase(), title = String(it.title || '').toLowerCase();
      if ((id && q.includes(` ${id} `)) || (title && q.includes(title))) return it;
      const words = title.split(/\s+/).filter(w => w.length > 3);
      const hit = words.filter(w => q.includes(w)).length;
      if (words.length && hit / words.length >= 0.6 && (!best || hit > best.hit)) best = { it, hit };
    }
    return best ? best.it : null;
  }

  NL.quickIntent = function quickIntent(text, items) {
    const t = String(text || '').trim();
    if (!t || t.length > 200 || WORK.test(t) || !ASKING.test(t)) return null;
    const study = studyIn(t, items);
    for (const [intent, rx] of INTENTS) if (rx.test(t)) return { intent: intent === 'running' && study ? 'status' : intent, study };
    if (study && /\b(status|where|how('s| is)|state|progress|stage|up to|doing)\b|\?\s*$/i.test(t)) return { intent: 'status', study };
    return null;
  };

  /* ── the answers, from the snapshot ─────────────────────────────────────────────────────────── */
  const { html } = NL;
  const runLine = (s, r) => { const it = r.subject && NL.item(s, r.subject);
    return html`<li><button type="button" class="link" onClick=${() => NL.openRun(r.run_id)}>${NL.runTitle(r)}</button>
      <span class="muted"> — ${r.status === 'waiting_input' ? 'asking you something' : r.status === 'queued' ? 'waiting for a free slot' : (r.last_action && r.last_action.summary) || r.status}${it ? '' : ''}</span></li>`; };
  const list = (xs, empty) => xs.length ? html`<ul class="qa-list">${xs}</ul>` : html`<p class="muted">${empty}</p>`;
  const money = n => '$' + (+n || 0).toFixed(2);
  const dayAgo = s => { const now = Date.parse(s.now) || Date.now(); return now - 86400e3; };

  function answer(intent, study, s) {
    const runs = s.runs || [], active = runs.filter(r => NL.RUN_ACTIVE.has(r.status) || r.status === 'waiting_input' || r.status === 'queued');
    const { needs } = NL.inboxItems ? NL.inboxItems(s) : { needs: [] };
    switch (intent) {
      case 'needs': return { title: needs.length ? `${NL.plural(needs.length, 'thing')} ${needs.length === 1 ? 'needs' : 'need'} you` : 'Nothing needs you right now',
        body: list(needs.slice(0, 12).map(a => html`<li><button type="button" class="link" onClick=${() => NL.attAct ? NL.attAct(a, (a.actions || [])[0] || { id: a.kind === 'artifact' ? 'artifact' : 'tail' }) : null}>${a.title}</button>${a.body ? html`<span class="muted"> — ${NL.clip(a.body, 90)}</span>` : null}</li>`), 'Agents ask here when they need a decision.') };
      case 'running': return { title: active.length ? `${NL.plural(active.length, 'agent')} at work` : 'No agents are running',
        body: list(active.map(r => runLine(s, r)), 'Start something from the button above the rail.') };
      case 'failed': {
        const bad = runs.filter(r => ['failed', 'timeout', 'killed'].includes(r.status) && (Date.parse(r.finished || r.created) || 0) > dayAgo(s));
        const quiet = runs.filter(r => NL.RUN_ACTIVE.has(r.status) && (r.heartbeat_age_s || 0) > 180);
        return { title: bad.length || quiet.length ? `${NL.plural(bad.length, 'run')} failed in the last day${quiet.length ? `, ${quiet.length} gone quiet` : ''}` : 'Nothing failed in the last day',
          body: list([...quiet.map(r => html`<li><button type="button" class="link" onClick=${() => NL.openRun(r.run_id)}>${NL.runTitle(r)}</button><span class="muted"> — no word for ${Math.round((r.heartbeat_age_s || 0) / 60)} min</span></li>`),
            ...bad.map(r => html`<li><button type="button" class="link" onClick=${() => NL.openRun(r.run_id)}>${NL.runTitle(r)}</button><span class="muted"> — ${r.reason || r.status}</span></li>`)], 'All runs in the last day finished or are still going.') };
      }
      case 'cost': {
        const today = runs.filter(r => (Date.parse(r.created || r.started) || 0) > dayAgo(s) && r.usage && r.usage.cost_usd != null);
        const total = today.reduce((a, r) => a + (+r.usage.cost_usd || 0), 0);
        const top = today.slice().sort((a, b) => b.usage.cost_usd - a.usage.cost_usd).slice(0, 5);
        return { title: `${money(total)} spent in the last day`, note: 'estimated from each run’s token use',
          body: list(top.map(r => html`<li><button type="button" class="link" onClick=${() => NL.openRun(r.run_id)}>${NL.runTitle(r)}</button><span class="muted"> — ${money(r.usage.cost_usd)}</span></li>`), 'No run reported a cost in the last day.') };
      }
      case 'overnight': {
        const since = (NL.ls && NL.ls.get('nl-seen-through', '')) || new Date(dayAgo(s)).toISOString();
        const ev = (s.events || []).filter(e => (e.ts || '') > since);
        const count = k => ev.filter(e => k.includes(e.kind)).length;
        const failed = ev.filter(e => e.kind === 'run_finished' && ['failed', 'timeout', 'killed'].includes(e.status)).length;
        const bits = [[count(['run_finished', 'agent_finished']) - failed, 'runs finished'], [failed, 'failed'], [count(['state_change']), 'studies moved on'],
          [count(['gate_waiting']), 'gates opened'], [count(['artifact']), 'things made for you'], [count(['escalation']), 'escalations']].filter(([n]) => n > 0);
        return { title: bits.length ? bits.map(([n, l]) => `${n} ${l}`).join(' · ') : 'Nothing has happened since your last visit',
          body: list(ev.slice(-10).reverse().map(e => html`<li><span class="mono small muted">${NL.when ? NL.when(e.ts) : e.ts}</span> ${(e.kind || '').replace(/_/g, ' ')}${e.detail ? html`<span class="muted"> — ${NL.clip(e.detail, 90)}</span>` : null}</li>`), ''),
          more: html`<a class="link small" href="#/history" onClick=${() => NL.closeTop && NL.closeTop()}>the full history →</a>` };
      }
      case 'gates': {
        const g = (s.items || []).filter(i => i.gate && !i.gate_signed);
        return { title: g.length ? `${NL.plural(g.length, 'gate')} waiting for your signature` : 'No gate is waiting for you',
          body: list(g.map(i => html`<li><button type="button" class="link" onClick=${() => NL.openGate(i.id, i.gate)}>Gate ${i.gate} — ${i.title || i.id}</button></li>`), '') };
      }
      case 'foryou': {
        const xs = (NL.artifactsOf ? NL.artifactsOf(s) : []).filter(a => !a.seen || (a.question && !a.answered));
        return { title: xs.length ? `${NL.plural(xs.length, 'thing')} for you to look at` : 'Nothing new for you',
          body: list(xs.slice(0, 10).map(a => html`<li><button type="button" class="link" onClick=${() => NL.openArtifact(a.id)}>${a.title}</button>${a.question && !a.answered ? html`<span class="muted"> — asks you</span>` : null}</li>`), '') };
      }
      case 'status': {
        const it = study, mine = runs.filter(r => r.subject === it.id && (NL.RUN_ACTIVE.has(r.status) || r.status === 'waiting_input' || r.status === 'queued'));
        const nx = NL.nextFor ? NL.nextFor(s, it) : null;
        return { title: `${it.title || it.id}: ${NL.STATE_LABEL ? NL.STATE_LABEL[it.state] || it.state : it.state}`,
          body: html`<div>${it.gate && !it.gate_signed ? html`<p>Waiting for you at <button type="button" class="link" onClick=${() => NL.openGate(it.id, it.gate)}>Gate ${it.gate}</button>.</p>` : null}
            ${mine.length ? list(mine.map(r => runLine(s, r)), '') : html`<p class="muted">No agent is working on it right now.${nx ? ` Its next step: ${nx.label}.` : ''}</p>`}</div>`,
          more: html`<a class="link small" href=${'#/study/' + it.id} onClick=${() => NL.closeTop && NL.closeTop()}>open the study →</a>` };
      }
      default: return null;
    }
  }

  /** an answer for this question from the live state, or null when it needs an agent */
  NL.quickAnswer = (text, s) => {
    const m = NL.quickIntent(text, (s && s.items) || []);
    if (!m || (m.intent === 'status' && !m.study)) return null;
    const a = answer(m.intent, m.study, s);
    return a ? { ...a, intent: m.intent } : null;
  };

  NL.AnswerSheet = ({ text, target, onAgent, onClose }) => {
    const s = NL.useLab();
    const a = NL.quickAnswer(text, s);
    if (!a) return html`<${NL.Sheet} title="Ask Newt" onClose=${onClose}><p class="muted">That needs an agent.</p></${NL.Sheet}>`;
    return html`<${NL.Sheet} title=${a.title} sub=${html`<span class="muted">“${NL.clip(text, 80)}” — answered from the lab's live state, no agent used${a.note ? ' · ' + a.note : ''}</span>`} onClose=${onClose}>
      <div class="qa-answer">${a.body}${a.more ? html`<div class="row end">${a.more}</div>` : null}</div>
      <div class="row end"><span class="muted small grow">Not what you meant?</span><${NL.Btn} onClick=${() => { onClose(); onAgent && onAgent(); }}>Ask an agent anyway</${NL.Btn}></div>
    </${NL.Sheet}>`;
  };
})();
