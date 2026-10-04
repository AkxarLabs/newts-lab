/* Newts' Lab — demo mode (?demo, only when the server was started with --demo): a synthetic, living
   lab so the world and the panels can be seen with no real session. Pure client-side; nothing is
   written (every API write is refused in demo mode). Every few seconds the lab moves on: runs start and
   finish, a study advances (a newt carries its card), a question comes and goes, a new lab gets built. */
(function () {
'use strict';
const NL = window.NL;

const BASE_ITEMS = [
  { id: 'spark-1', title: 'Sparse attention', state: 'seed' },
  { id: 'spark-2', title: 'Token routing', state: 'triaged' },
  { id: 'lit-1', title: 'Distillation curricula', state: 'lit-review' },
  { id: 'scope-1', title: 'Adaptive optimizers', state: 'scoping' },
  { id: 'prop-1', title: 'Curriculum distillation', state: 'proposal', gate: 1, next: 'Gate 1' },
  { id: 'prop-2', title: 'Retrieval heads', state: 'proposal', gate: 1, gate_signed: true, next: 'spawn-project' },
  { id: 'moe', title: 'Sparse MoE routing', state: 'active', has_project: true, project_type: 'ml', loop_active: true, next: 'experiment',
    best: { val_loss: 1.31, run_id: 'exp-012' } },
  { id: 'rl', title: 'RL fine-tuning', state: 'active', has_project: true, project_type: 'ml', gate: 2, next: 'Gate 2' },
  { id: 'ana-1', title: 'Scaling probes', state: 'analysis', has_project: true, project_type: 'simulation', next: 'analyze' },
  { id: 'paper-1', title: 'Scaling laws note', state: 'writing', has_project: true, project_type: 'theory', has_paper: true, next: 'write-paper' },
  { id: 'rev-1', title: 'Long-context eval', state: 'internal-review', has_paper: true, gate: 3, next: 'Gate 3' },
  { id: 'final-1', title: 'Quantization study', state: 'final', has_paper: true },
  { id: 'park-1', title: 'Old idea (parked)', state: 'parked' },
];
const ACT = {
  experiment: ['Bash: uv run scripts/run.py --stage PILOT --seed 2', 'Edit: src/router.py', 'Read: runs/exp-014/metrics.json'],
  improve: ['Edit: src/policy.py', 'Bash: uv run scripts/run.py --stage SMOKE'], analyze: ['Bash: uv run scripts/compare.py', 'Write: analysis.md § H1'],
  'lit-review': ['WebSearch: curriculum distillation 2025', 'Read: papers/hinton-2015.pdf'], scope: ['Write: decisions.md — D3 eval set', 'Task: scoping advocate for B'],
  'write-paper': ['Edit: paper/main.tex § Results', 'Bash: latexmk -pdf'], ideate: ['Write: seeds/cheap-routing.md', 'Task: ideation critic ×2'],
  'review-paper': ['Task: fresh-context reviewer ×3', 'Write: meta-review.md'], 'spawn-project': ['Bash: tools/spawn_project.py retrieval-heads', 'Write: control.yaml'],
  ask: ['Read: lab/REGISTRY.md', 'Read: studies/moe/IDEA.md'],
};
const SUBS = { experiment: ['experiment-runner', 'overseer'], improve: ['experiment-runner'], 'lit-review': ['fresh-context-reviewer'], scope: ['scoping-advocate', 'scoping-advocate'],
  'review-paper': ['fresh-context-reviewer', 'fresh-context-reviewer'], ideate: ['ideation-critic'] };


// the demo happens now: every time is minutes before this page loaded (local time, like the lab's own stamps)
const T0 = Date.now();
const iso = ms => { const d = new Date(ms), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
const ago = min => iso(T0 - min * 60e3);

/* artifacts the demo agents "published": the page, the rail and the world show them; nothing is written */
const SVG_LOSS = (() => {
  const line = (k, c) => { let d = ''; for (let i = 0; i <= 40; i++) { const x = 40 + i * 13, y = 40 + 200 * Math.exp(-i / (9 + k * 2)) + 30 + Math.sin(i * 0.9 + k) * 4; d += (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1); } return `<path d="${d}" fill="none" stroke="${c}" stroke-width="2.5"/>`; };
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="320" viewBox="0 0 600 320"><rect width="600" height="320" fill="#fbf8f2"/><g stroke="#d9d1c3">${[80, 140, 200, 260].map(y => `<line x1="40" x2="580" y1="${y}" y2="${y}"/>`).join('')}</g>${line(0, '#2e8f84')}${line(1, '#6f9be6')}${line(2, '#d9884a')}<text x="300" y="304" font-family="sans-serif" font-size="13" text-anchor="middle" fill="#555">steps (k)</text><text x="300" y="24" font-family="sans-serif" font-size="15" text-anchor="middle" fill="#222">Validation loss, seeds 1–3</text></svg>`;
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
})();
const ARTS = [
  { id: 'a-20260619-081200-0001', title: 'Pilot results — sparse MoE routing', kind: 'md', study: 'moe', run_id: 'r-moe', skill: 'experiment', created: ago(52),
    note: 'The pilot beats the dense baseline on 2 of 3 seeds; one seed diverged at step 6k — details below.',
    text: '# Pilot results\n\n| run | seed | val loss | Δ vs dense |\n|---|---|---|---|\n| exp-012 | 1 | **1.31** | −0.09 |\n| exp-013 | 2 | 1.36 | −0.04 |\n| exp-014 | 3 | 1.52 | +0.12 |\n\nThe router load stays balanced ($\\mathrm{CV} < 0.15$) except seed 3, where one expert takes\n$41\\%$ of tokens after step 6k.\n\n## What I would do next\n\n1. Re-run seed 3 with the auxiliary balance loss at $\\lambda = 10^{-2}$.\n2. If it holds, scale to PILOT-L (4× tokens).\n\n> Every number above links to `runs/exp-01x/metrics.json` in the project.' },
  { id: 'a-20260619-082500-0002', title: 'Which eval set should we freeze?', kind: 'choice', study: 'scope-1', run_id: 'r-scope', skill: 'scope', created: ago(38),
    question: 'Freeze the held-out benchmark (slower, standard) or the synthetic suite (fast, ours)?', choices: ['Held-out benchmark', 'Synthetic suite', 'Both — synthetic for pilots'] },
  { id: 'a-20260619-083000-0003', title: 'Loss curves, seeds 1–3', kind: 'image', study: 'moe', run_id: 'r-moe', skill: 'experiment', created: ago(31), src: SVG_LOSS },
  { id: 'a-20260619-084000-0004', title: 'Ablation explorer', kind: 'html', study: 'ana-1', run_id: 'r-ana', skill: 'analyze', created: ago(22),
    note: 'Drag the slider to see how the probe accuracy moves with model scale.',
    html: '<body style="font-family:sans-serif;margin:24px;background:#fbf8f2"><h3>Probe accuracy vs scale</h3><input id=s type=range min=0 max=4 value=2 style="width:300px"><p id=o></p><script>const v=[0.61,0.68,0.74,0.79,0.81],n=["70M","160M","410M","1B","2.8B"];const f=()=>o.textContent=n[s.value]+": "+(v[s.value]*100).toFixed(1)+"%";s.oninput=f;f();</script></body>' },
  { id: 'a-20260619-085000-0005', title: 'Routing ablation table', kind: 'table', study: 'moe', run_id: 'r-moe', skill: 'experiment', created: ago(14),
    rows: [['variant', 'top-k', 'val loss', 'tokens/s'], ['dense', '-', '1.40', '41k'], ['switch', '1', '1.36', '58k'], ['ours', '2', '1.31', '52k'], ['ours + balance', '2', '1.30', '51k']] },
  { id: 'a-20260619-090000-0006', title: 'Plan: the next three experiments', kind: 'md', study: 'rl', run_id: 'r-rl', skill: 'improve', created: ago(6),
    question: 'Good to run these three at PILOT scale?', choices: ['Yes, go', 'Only the first two', 'Not yet — let’s talk'],
    text: '# Plan\n\n- **E1** — KL penalty sweep $\\beta \\in \\{0.01, 0.05, 0.1\\}$, 3 seeds each.\n- **E2** — reward-model ensemble of 3 vs 1.\n- **E3** — curriculum on prompt difficulty.\n\nBudget: ~2.5 GPU-hours in total, inside the Gate-2 envelope.' },
];
const demoSeen = new Set(), demoReplied = {};
NL.demoArtifact = async id => { const a = ARTS.find(x => x.id === id); if (!a) return { error: 'no such artifact' };
  demoSeen.add(id);
  return { ok: true, artifact: { ...a, seen: true, reply: demoReplied[id] || null }, text: a.text, html: a.html, src: a.src, table: a.rows ? { rows: a.rows, more: 0 } : null }; };
NL.demoReply = (id, choice, text) => { demoReplied[id] = { ts: new Date().toISOString(), by: 'PI', choice, text: text || null, delivered: 'the demo (nothing is sent)' }; NL.toast('Demo mode — the reply is kept on this page only'); return { ok: true, reply: demoReplied[id] }; };
NL.demoFleet = { ok: true, labs: [
  { kind: 'local', key: 'demo::here', name: 'Demo lab', machine: 'This computer', current: true, state: 'here', summary: {} },
  { kind: 'remote', key: 'demo::cluster', name: 'Protein folding', machine: 'gpu-cluster', state: 'connected', summary: { needs: 2, running: 5 } },
  { kind: 'local', key: 'demo::side', name: 'Side project', machine: 'This computer', state: 'here', summary: { needs: 0, running: 1 } },
  { kind: 'remote', key: 'demo::lab-pc', name: 'Wet-lab analysis', machine: 'lab-pc', state: 'idle', summary: null }] };
NL.demoRunFile = f => ({ ok: true, kind: f.kind, path: f.path, text: f.kind === 'md'
  ? '# Experiment log\n\n## exp-014 — PILOT, seed 3\n- config: `configs/experiments/exp-014.yaml`\n- val loss **1.52** (diverged at step 6k: one expert took 41% of tokens)\n- next: rerun with the balance loss at 1e-2\n\n## exp-013 — PILOT, seed 2\n- val loss 1.36\n'
  : 'def route(x, experts, k=2):\n    scores = x @ experts.T\n    top = scores.topk(k)\n    return top.indices, top.values.softmax(-1)\n' });
const PROPOSAL = it => `# Proposal — ${it.title}\n\n## Hypothesis\nA curriculum ordered by teacher confidence distils a 7B teacher into a 1B student with **≥ 2 points** less accuracy loss than random order.\n\n## Frozen evaluation\nThe held-out split of the benchmark, fixed before any run; reported over 3 seeds.\n\n## Staged plan\n| stage | what | promote when |\n|---|---|---|\n| SMOKE | 100 steps, 1 seed | it runs end to end |\n| PILOT | 2k steps, 3 seeds | ≥ 1 point better than random order |\n| FULL | 20k steps, 3 seeds | — |\n\n## Budget\nPILOT ≈ 6 GPU-hours · FULL ≈ 40 GPU-hours.\n\n## Kill criteria\nStop if PILOT shows no gain over random order on 2 of 3 seeds.\n\n## §5 Gate 2 envelope\nUp to **3 FULL runs**, ≤ 15 GPU-hours each.`;
const DOCS = { 'IDEA.md': it => `# ${it.title}\n\nState: **${it.state}**.\n\nThe idea in one paragraph, its scores from triage, and the state log the lab keeps.`,
  'lit-review.md': it => `# Literature review — ${it.title}\n\n**Verdict: incremental.** Three close papers; none orders the curriculum by teacher confidence.`,
  'proposal.md': PROPOSAL, 'PLAN.md': it => `# Plan — ${it.title}\n\n| exp | stage | status |\n|---|---|---|\n| exp-012 | PILOT | done |\n| exp-014 | PILOT | rerun |`,
  'EXPERIMENT_LOG.md': () => NL.demoRunFile({ kind: 'md' }).text };
NL.demoRead = (path, b) => {
  const it = BASE_ITEMS.find(i => i.id === (b.idea || b.slug)) || BASE_ITEMS[4];
  if (path === '/api/read' && b.what === 'gate') return { ok: true, sections: b.gate === 3
    ? [{ title: 'Meta-review', path: 'paper/reviews/meta-review.md', text: '# Meta-review\n\n**Verdict: accept.** All three reviewers agree the claims are supported; two minor fixes were made.' }]
    : [{ title: 'proposal.md', path: `studies/${it.id}/proposal.md`, text: PROPOSAL(it) }], note: 'Demo — a made-up proposal.' };
  if (path === '/api/read') return { ok: true, sections: [{ title: 'metrics.json', path: 'runs/exp-014/metrics.json', text: '{"val_loss": 1.52, "step": 6000}' }] };
  const f = DOCS[(b.rel || '').split('/').pop()];
  return f ? { ok: true, format: 'markdown', text: f(it), path: `(demo)/${b.rel}` } : { error: 'not in the demo' };
};
NL.demoGet = path => {
  if (path.startsWith('/api/lab/config')) return { ok: true, config: { name: 'Demo lab', projects_root: '../projects', max_concurrent_runs: 4, oversight: 'standard',
    loop_mode: 'execute', keep_awake: 'auto', claude_model: 'claude-sonnet-5-5', claude_effort: 'medium', codex_model: 'gpt-6-luna', codex_effort: 'low',
    opencode_model: '', opencode_variant: '', tier_strong: 'opus', tier_standard: 'inherit', tier_fast: 'haiku', reviewer_model: 'strong', runner_model: 'standard',
    overseer_model: 'standard', critic_model: 'standard', reviewer_effort: '', runner_effort: '', overseer_effort: '', critic_effort: '' }, setup: { completed: true } };
  if (!path.startsWith('/api/library')) return null;
  const groups = BASE_ITEMS.filter(i => i.state !== 'parked').map(i => {
    const order = ['seed', 'triaged', 'lit-review', 'scoping', 'proposal', 'active', 'analysis', 'writing', 'internal-review', 'final'], at = order.indexOf(i.state);
    const study = ['IDEA.md', ...(at > 2 ? ['lit-review.md'] : []), ...(at > 3 ? ['proposal.md'] : [])].map(rel => ({ scope: 'study', slug: i.id, rel, title: rel }));
    const proj = i.has_project ? ['PLAN.md', 'EXPERIMENT_LOG.md'].map(rel => ({ scope: 'project', slug: i.id, rel, title: rel })) : [];
    return { kind: 'study', key: 'study:' + i.id, slug: i.id, title: i.title, state: i.state,
      sections: [{ title: 'Study', icon: '📋', docs: study }, ...(proj.length ? [{ title: 'Project repo', icon: '🛠', docs: proj }] : [])] };
  });
  return { ok: true, groups };
};
NL.demoRunFiles = r => r.run_id === 'r-moe' ? [{ path: 'C:/demo/projects/moe/EXPERIMENT_LOG.md', name: 'EXPERIMENT_LOG.md', exists: true, kind: 'md', size: 2048 },
  { path: 'C:/demo/projects/moe/src/router.py', name: 'router.py', exists: true, kind: 'text', size: 4096 }] : [];
const artifactsAt = T => ARTS.filter((a, i) => i < ARTS.length - 1 || T >= 3).map(a => ({ id: a.id, title: a.title, kind: a.kind, study: a.study, run_id: a.run_id, skill: a.skill,
  created: a.created, question: a.question || null, choices: (a.choices || []).length, seen: demoSeen.has(a.id), answered: !!demoReplied[a.id] }));

function demoState(T, items) {
  const h = id => [...id].reduce((a, c) => a + c.charCodeAt(0), 0);
  const run = (id, skill, subject, status, extra) => {
    const subs = (SUBS[skill] || []).map((type, i) => ({ id: `${id}-s${i}`, type, status: (T + i) % 7 === 0 ? 'done' : 'running', last_action: (ACT[skill] || ACT.ask)[(T + i + 1) % (ACT[skill] || ACT.ask).length] }));
    const a = ACT[skill] || ACT.ask;
    return Object.assign({ run_id: id, skill, subject, target: subject || 'hub', status, backend: ['claude', 'codex', 'opencode'][h(id) % 3], created: ago(20 + h(id) % 70), session_id: 'S-' + id, transport: 'live', pid: 1000 + h(id),
      label: skill === 'ask' ? 'Summarise what moved overnight' : null, last_action: { summary: a[T % a.length] }, subagents: subs, n_actions: 12 + T * 3 + h(id) % 20, elapsed_s: (20 + h(id) % 70) * 60 + T * 4,
      usage: { cost_usd: +(0.15 + (h(id) % 9) * 0.11 + T * (0.004 + (h(id) % 5) * 0.002)).toFixed(2) } }, extra || {});
  };
  const runs = [
    run('r-moe', 'experiment', 'moe', 'running'),
    run('r-rl', 'improve', 'rl', 'running'),
    run('r-ana', 'analyze', 'ana-1', T % 9 < 5 ? 'running' : 'completed'),
    run('r-lit', 'lit-review', 'lit-1', 'running', { heartbeat_age_s: 420, reason: 'no word from it for 7 minutes' }),
    run('r-scope', 'scope', 'scope-1', 'running'),
    run('r-paper', 'write-paper', 'paper-1', 'waiting_input', { pending_question: { tool_use_id: 'tq-paper', asked_at: ago(9), live: true, input: { questions: [
      { header: 'Paper structure', question: 'Lead the Results section with the scaling law or with the ablation?', options: [
        { label: 'The scaling law', description: 'the headline claim first; the ablation backs it up' },
        { label: 'The ablation', description: 'build up to the law from what each part contributes' }] }] } } }),
    run('r-sweep', 'experiment', 'rl', 'failed', { reason: 'timed out after its 45-minute limit (exp-019, seed 2)', finished: ago(95) }),
    run('r-rev', 'review-paper', 'rev-1', 'running'),
    run('r-ask', 'ask', null, 'running'),
    run('r-spawn', 'spawn-project', 'prop-2', items.find(i => i.id === 'prop-2' && !i.has_project) ? 'running' : 'completed'),
    run('r-ideate', 'ideate', null, T % 10 < 6 ? 'queued' : 'running'),
  ];
  const done = [run('r-night1', 'lit-review', 'lit-1', 'completed', { finished: ago(300) }), run('r-night2', 'experiment', 'moe', 'completed', { finished: ago(180) })];
  const GATE_WHAT = { 1: 'approve the proposal', 2: 'approve full-scale runs', 3: 'finalize the paper' };
  const attention = items.filter(i => i.gate && !i.gate_signed).map(i => ({ id: 'gate:' + i.id, sev: 'block', kind: 'gate', title: `Gate ${i.gate} — ${i.title}: ${GATE_WHAT[i.gate]}`,
    idea: i.id, detail: { gate: i.gate }, actions: [{ id: 'sign', label: 'review & sign' }] }));
  attention.push({ id: 'q:r-paper', sev: 'block', kind: 'question', title: 'Lead the Results with the scaling law or the ablation?', body: 'Scaling laws note · the writing agent is paused until you answer',
    run_id: 'r-paper', actions: [{ id: 'answer', label: 'answer' }] });
  attention.push({ id: 'fail:r-sweep', sev: 'warn', kind: 'crashed', title: 'An RL fine-tuning experiment timed out', body: 'exp-019, seed 2 — after its 45-minute limit', run_id: 'r-sweep', actions: [{ id: 'tail', label: 'open' }] });
  const artifacts = artifactsAt(T);
  for (const x of artifacts.filter(x => x.question && !x.answered)) attention.push({ id: 'artifact:' + x.id, sev: 'warn', kind: 'artifact', title: x.title, body: `asks you: ${x.question} — the agent keeps working meanwhile`, idea: x.study, run_id: x.run_id, detail: { artifact: x.id }, actions: [{ id: 'artifact', label: 'answer' }] });
  const events = [['state_change', 'Distillation curricula moved to literature review', 420, 'lit-1'], ['run_finished', 'lit-review finished', 300, 'lit-1', 'completed'],
    ['gate_waiting', 'Gate 1 is waiting — Curriculum distillation', 260, 'prop-1'], ['run_finished', 'experiment finished — exp-014', 180, 'moe', 'completed'],
    ['run_finished', 'exp-019 timed out', 95, 'rl', 'failed'], ['agent_waiting', 'the writing agent asked you something', 9, 'paper-1']]
    .map(([kind, detail, min, idea, status]) => ({ ts: ago(min), source: 'hub', kind, detail, idea, ...(status ? { status } : {}) }));
  return { artifacts, workflow: window.__WORKFLOW_DEFAULT__, now: iso(Date.now()), items: items.map(it => ({ inflight: [], events: [], directives: [], ...it })), runs: runs.concat(done), attention, workers: [],
    slots: { cap: 3, in_use: 2 }, directives: [], gates_waiting: attention.filter(a => a.kind === 'gate').length, cold: false, events,
    executor: { available: true, enabled: true, caps: { total: 10 } },
    campaign_states: NL.demoCampaignStates ? NL.demoCampaignStates(T) : [],
    campaigns: [{ name: 'scaling-laws', title: 'Scaling-laws sweep', status: 'active', signed: 'PI · 2026-06-12',
      budget: { full_runs: 12, total_max_minutes: 480, pi_signed: true, expires: '2026-06-30' }, projects: ['moe', 'rl', 'ana-1'] }] };
}

NL.startDemo = function startDemo() {
  document.title = "Newts' Lab — demo";
  setTimeout(() => NL.toast('Demo mode — nothing here is real, and nothing is written'), 700);
  const items = BASE_ITEMS.map(x => Object.assign({}, x));
  let T = 0;
  function step() {
    // the lab moves on: a study advances now and then, and the new lab finishes building
    if (T === 4) Object.assign(items.find(i => i.id === 'prop-2'), { has_project: true, state: 'active', gate: null, project_type: 'ml', next: 'experiment' });
    if (T % 6 === 3) { const it = items.find(i => i.id === 'spark-2'); const order = ['triaged', 'lit-review', 'scoping', 'triaged']; it.state = order[(order.indexOf(it.state) + 1) % order.length]; }
    const s = demoState(T, items);
    s.lab_info = { name: 'Demo lab', path: '(synthetic)', setup: { completed: true } };
    NL.setState(s); T++;
  }
  step(); setInterval(step, 4000);
};
})();
