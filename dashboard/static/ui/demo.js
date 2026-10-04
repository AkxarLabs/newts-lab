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
    best: { series: [{ value: 2.0 }, { value: 1.74 }, { value: 1.55 }, { value: 1.4 }, { value: 1.31 }] } },
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

function demoState(T, items) {
  const stamp = k => { const sec = k * 7; const p = n => String(n).padStart(2, '0'); return `2026-06-19T${p((8 + ((sec / 3600) | 0)) % 24)}:${p(((sec / 60) | 0) % 60)}:${p(sec % 60)}`; };
  const run = (id, skill, subject, status, extra) => {
    const subs = (SUBS[skill] || []).map((type, i) => ({ id: `${id}-s${i}`, type, status: (T + i) % 7 === 0 ? 'done' : 'running', last_action: (ACT[skill] || ACT.ask)[(T + i + 1) % (ACT[skill] || ACT.ask).length] }));
    const a = ACT[skill] || ACT.ask;
    return Object.assign({ run_id: id, skill, subject, target: subject || 'hub', status, backend: ['claude', 'codex', 'opencode'][id.length % 3], created: stamp(T),
      label: skill === 'ask' ? 'Summarise what moved overnight' : null, last_action: { summary: a[T % a.length] }, subagents: subs, usage: { cost_usd: 0.12 + ((T * id.length) % 40) / 20 } }, extra || {});
  };
  const runs = [
    run('r-moe', 'experiment', 'moe', 'running'),
    run('r-rl', 'improve', 'rl', 'running'),
    run('r-ana', 'analyze', 'ana-1', T % 9 < 5 ? 'running' : 'completed'),
    run('r-lit', 'lit-review', 'lit-1', 'running'),
    run('r-scope', 'scope', 'scope-1', 'running'),
    run('r-paper', 'write-paper', 'paper-1', T % 8 < 4 ? 'waiting_input' : 'running', { pending_question: { question: 'Lead with the scaling law or the ablation?' } }),
    run('r-rev', 'review-paper', 'rev-1', 'running'),
    run('r-ask', 'ask', null, 'running'),
    run('r-spawn', 'spawn-project', 'prop-2', items.find(i => i.id === 'prop-2' && !i.has_project) ? 'running' : 'completed'),
    run('r-ideate', 'ideate', null, T % 10 < 6 ? 'queued' : 'running'),
  ].filter(r => r.status !== 'completed');
  const attention = [{ id: 'a1', sev: 'block', kind: 'gate', title: 'Gate 1 — Curriculum distillation', idea: 'prop-1', detail: { gate: 1 } },
    { id: 'a3', sev: 'block', kind: 'gate', title: 'Gate 3 — Long-context eval', idea: 'rev-1', detail: { gate: 3 } }];
  if (runs.some(r => r.status === 'waiting_input')) attention.push({ id: 'a2', sev: 'block', kind: 'question', title: 'A question about Scaling laws note', run_id: 'r-paper' });
  return { now: stamp(T), items: items.map(it => ({ inflight: [], events: [], directives: [], ...it })), runs, attention, workers: [],
    slots: { cap: 3, in_use: 2 }, directives: [], gates_waiting: 2, cold: false, events: [],
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
