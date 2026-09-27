/* Newts' Lab — demo mode (?demo, only when the server was started with --demo): a synthetic, living
   lab so the world and the panels can be seen with no real session. Pure client-side; nothing is
   written (every API write is refused in demo mode). */
(function () {
'use strict';
const NL = window.NL;
function demoState(tick) {
  const T = tick;
  const items = [
    { id: 'spark-1', title: 'Sparse attention', state: 'seed' },
    { id: 'spark-2', title: 'Token routing', state: 'triaged' },
    { id: 'lit-1', title: 'Distillation curricula', state: 'lit-review', n_workers: 1 },
    { id: 'scope-1', title: 'Adaptive optimizers', state: 'scoping', n_workers: 2 },
    { id: 'prop-1', title: 'Curriculum distillation', state: 'proposal', gate: 1, next: 'Gate 1' },
    { id: 'moe', title: 'Sparse MoE routing', state: 'active', has_project: true, loop_active: true, n_workers: 3, next: 'experiment',
      inflight: [{ run_id: 'exp-' + (7 + (T % 3)), stage: (T % 6 < 3 ? 'pilot' : 'full'), state: 'alive', budget_min: 30, elapsed_s: 120 + (T * 47) % 1650, last: { val_loss: +(1.62 - (T % 14) * 0.025).toFixed(3) } }],
      best: { series: [{ value: 2.0 }, { value: 1.74 }, { value: 1.55 }, { value: 1.4 }, { value: 1.31 }] } },
    { id: 'rl', title: 'RL fine-tuning', state: 'active', has_project: true, n_workers: 2, gate: 2, next: 'Gate 2' },
    { id: 'ana-1', title: 'Scaling probes', state: 'analysis', has_project: true, n_workers: 1, next: 'analyze' },
    { id: 'paper-1', title: 'Scaling laws note', state: 'writing', has_project: true, has_paper: true, next: 'write-paper' },
    { id: 'rev-1', title: 'Long-context eval', state: 'internal-review', has_paper: true, n_workers: 2, gate: 3, next: 'Gate 3' },
    { id: 'final-1', title: 'Quantization study', state: 'final', has_paper: true },
    { id: 'final-2', title: 'Pruning at scale', state: 'final', has_paper: true },
    { id: 'park-1', title: 'Old idea (parked)', state: 'parked' },
    { id: 'kill-1', title: 'Abandoned approach', state: 'killed' },
  ].map(it => ({ inflight: [], events: [], directives: [], ...it }));
  // worker pool — idea-anchored ones show in the world overview; project ones live inside their room.
  // A few are `transient` (come and go each cycle, to show spawn/despawn); the rest are a stable crew.
  const pool = [
    { worker_id: 'crit-1', role: 'ideation-critic', idea: 'spark-1' },
    { worker_id: 'crit-2', role: 'ideation-critic', idea: 'spark-2', transient: true },
    { worker_id: 'rev-lit', role: 'fresh-context-reviewer', idea: 'lit-1' },
    { worker_id: 'adv-1', role: 'scoping-advocate', idea: 'scope-1' },
    { worker_id: 'adv-2', role: 'scoping-advocate', idea: 'scope-1', transient: true },
    { worker_id: 'er-moe-1', role: 'experiment-runner', project: 'moe' },
    { worker_id: 'er-moe-2', role: 'experiment-runner', project: 'moe' },
    { worker_id: 'over-moe', role: 'overseer', project: 'moe' },
    { worker_id: 'er-rl-1', role: 'experiment-runner', project: 'rl' },
    { worker_id: 'over-ana', role: 'overseer', project: 'ana-1' },
    { worker_id: 'rev-lc-1', role: 'fresh-context-reviewer', idea: 'rev-1' },
    { worker_id: 'rev-lc-2', role: 'fresh-context-reviewer', idea: 'rev-1', transient: true },
  ];
  // a small role-flavoured action vocabulary → believable, evolving per-agent timelines for the inspector
  const VERB = {
    'experiment-runner': [['Bash: python scripts/run.py --seed 0', 'run'], ['Read: configs/base.yaml', 'read'], ['Edit: src/model.py', 'edit'], ['Bash: git commit -m "exp"', 'git'], ['Grep: val_loss in runs/', 'read']],
    'overseer': [['Read: runs/exp-007/metrics.json', 'read'], ['Grep: claim vs artifact', 'read'], ['Read: analysis.md', 'read']],
    'fresh-context-reviewer': [['Read: studies/<slug>/paper/main.tex', 'read'], ['Grep: unsupported claims', 'read'], ['Write: review-notes.md', 'edit']],
    'ideation-critic': [['Read: IDEA.md', 'read'], ['Write: critique.md', 'edit'], ['Grep: prior work', 'read']],
    'scoping-advocate': [['Read: decisions.md', 'read'], ['Write: scoping/option-a.md', 'edit'], ['Grep: baselines', 'read']],
  };
  const tstamp = k => { const sec = k * 7; const p = n => String(n).padStart(2, '0'); return `2026-06-19T${p((8 + ((sec / 3600) | 0)) % 24)}:${p(((sec / 60) | 0) % 60)}:${p(sec % 60)}`; };
  const present = pool.filter((w, i) => !w.transient || ((T + i) % 4) !== 0);   // transient ones blink in/out
  const workers = present.map((w, i) => {
    const vocab = VERB[w.role] || VERB['experiment-runner'], n = 3 + ((T + i) % 5);
    const recent = Array.from({ length: n }, (_, j) => { const v = vocab[(T + i + j) % vocab.length]; return { ts: tstamp(Math.max(0, T - (n - 1 - j))), text: v[0], kind: v[1] }; });
    return { ...w, status: 'working', n_actions: 6 + ((T * (i + 2)) % 60), started: tstamp(Math.max(0, T - 9)), last_ts: tstamp(T), recent_actions: recent };
  });
  return { now: '', items, events: [], slots: { cap: 3, in_use: 1 + (T % 3), held: [] },
    directives: [{ id: 'd-1', ts: '', text: 'prioritise the MoE routing work', state: 'pending', kind: 'note' }],
    campaigns: [{ name: 'scaling-laws', title: 'Scaling-laws sweep', status: 'active', signed: 'PI · 2026-06-12',
      budget: { full_runs: 12, total_max_minutes: 480, pi_signed: true, expires: '2026-06-30' }, projects: ['moe', 'rl', 'ana-1'] }],
    workers, gates_waiting: items.filter(it => it.gate).length, cold: false };
}
NL.startDemo = function startDemo() {
  document.title = "Newts' Lab — demo";
  setTimeout(() => NL.toast('Demo mode — nothing here is real, and nothing is written'), 700);
  let T = 0; const evs = [];
  const stamp = k => { const sec = k * 7; const p = n => String(n).padStart(2, '0'); return `2026-06-19T${p((8 + ((sec / 3600) | 0)) % 24)}:${p(((sec / 60) | 0) % 60)}:${p(sec % 60)}`; };
  function step() {
    const s = demoState(T), ph = T % 9;
    if (ph === 3) evs.push({ ts: stamp(T), source: 'moe', kind: 'run_finished', status: 'completed', run_id: 'exp-' + (7 + (T % 3)) });
    else if (ph === 6) evs.push({ ts: stamp(T), source: 'rl', kind: 'escalation', detail: 'requesting a FULL-run envelope bump' });
    else if (ph === 0 && T > 0) evs.push({ ts: stamp(T), source: 'moe', kind: 'run_started', run_id: 'exp-' + (7 + (T % 3)) });
    s.now = stamp(T); s.events = evs.slice(-40);
    s.lab_info = { name: 'Demo lab', path: '(synthetic)', setup: { completed: true } };
    NL.setState(s); T++;
  }
  step(); setInterval(step, 2600);
};
})();
