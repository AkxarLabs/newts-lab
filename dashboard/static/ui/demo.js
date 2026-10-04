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


/* artifacts the demo agents "published": the page, the rail and the world show them; nothing is written */
const SVG_LOSS = (() => {
  const line = (k, c) => { let d = ''; for (let i = 0; i <= 40; i++) { const x = 40 + i * 13, y = 40 + 200 * Math.exp(-i / (9 + k * 2)) + 30 + Math.sin(i * 0.9 + k) * 4; d += (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1); } return `<path d="${d}" fill="none" stroke="${c}" stroke-width="2.5"/>`; };
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="320" viewBox="0 0 600 320"><rect width="600" height="320" fill="#fbf8f2"/><g stroke="#d9d1c3">${[80, 140, 200, 260].map(y => `<line x1="40" x2="580" y1="${y}" y2="${y}"/>`).join('')}</g>${line(0, '#2e8f84')}${line(1, '#6f9be6')}${line(2, '#d9884a')}<text x="300" y="304" font-family="sans-serif" font-size="13" text-anchor="middle" fill="#555">steps (k)</text><text x="300" y="24" font-family="sans-serif" font-size="15" text-anchor="middle" fill="#222">Validation loss, seeds 1–3</text></svg>`;
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
})();
const ARTS = [
  { id: 'a-20260619-081200-0001', title: 'Pilot results — sparse MoE routing', kind: 'md', study: 'moe', run_id: 'r-moe', skill: 'experiment', created: '2026-06-19T08:12:00',
    note: 'The pilot beats the dense baseline on 2 of 3 seeds; one seed diverged at step 6k — details below.',
    text: '# Pilot results\n\n| run | seed | val loss | Δ vs dense |\n|---|---|---|---|\n| exp-012 | 1 | **1.31** | −0.09 |\n| exp-013 | 2 | 1.36 | −0.04 |\n| exp-014 | 3 | 1.52 | +0.12 |\n\nThe router load stays balanced ($\\mathrm{CV} < 0.15$) except seed 3, where one expert takes\n$41\\%$ of tokens after step 6k.\n\n## What I would do next\n\n1. Re-run seed 3 with the auxiliary balance loss at $\\lambda = 10^{-2}$.\n2. If it holds, scale to PILOT-L (4× tokens).\n\n> Every number above links to `runs/exp-01x/metrics.json` in the project.' },
  { id: 'a-20260619-082500-0002', title: 'Which eval set should we freeze?', kind: 'choice', study: 'scope-1', run_id: 'r-scope', skill: 'scope', created: '2026-06-19T08:25:00',
    question: 'Freeze the held-out benchmark (slower, standard) or the synthetic suite (fast, ours)?', choices: ['Held-out benchmark', 'Synthetic suite', 'Both — synthetic for pilots'] },
  { id: 'a-20260619-083000-0003', title: 'Loss curves, seeds 1–3', kind: 'image', study: 'moe', run_id: 'r-moe', skill: 'experiment', created: '2026-06-19T08:30:00', src: SVG_LOSS },
  { id: 'a-20260619-084000-0004', title: 'Ablation explorer', kind: 'html', study: 'ana-1', run_id: 'r-ana', skill: 'analyze', created: '2026-06-19T08:40:00',
    note: 'Drag the slider to see how the probe accuracy moves with model scale.',
    html: '<body style="font-family:sans-serif;margin:24px;background:#fbf8f2"><h3>Probe accuracy vs scale</h3><input id=s type=range min=0 max=4 value=2 style="width:300px"><p id=o></p><script>const v=[0.61,0.68,0.74,0.79,0.81],n=["70M","160M","410M","1B","2.8B"];const f=()=>o.textContent=n[s.value]+": "+(v[s.value]*100).toFixed(1)+"%";s.oninput=f;f();</script></body>' },
  { id: 'a-20260619-085000-0005', title: 'Routing ablation table', kind: 'table', study: 'moe', run_id: 'r-moe', skill: 'experiment', created: '2026-06-19T08:50:00',
    rows: [['variant', 'top-k', 'val loss', 'tokens/s'], ['dense', '-', '1.40', '41k'], ['switch', '1', '1.36', '58k'], ['ours', '2', '1.31', '52k'], ['ours + balance', '2', '1.30', '51k']] },
  { id: 'a-20260619-090000-0006', title: 'Plan: the next three experiments', kind: 'md', study: 'rl', run_id: 'r-rl', skill: 'improve', created: '2026-06-19T09:00:00',
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
NL.demoRunFiles = r => r.run_id === 'r-moe' ? [{ path: 'C:/demo/projects/moe/EXPERIMENT_LOG.md', name: 'EXPERIMENT_LOG.md', exists: true, kind: 'md', size: 2048 },
  { path: 'C:/demo/projects/moe/src/router.py', name: 'router.py', exists: true, kind: 'text', size: 4096 }] : [];
const artifactsAt = T => ARTS.filter((a, i) => i < 2 + Math.floor(T / 2)).map(a => ({ id: a.id, title: a.title, kind: a.kind, study: a.study, run_id: a.run_id, skill: a.skill,
  created: a.created, question: a.question || null, choices: (a.choices || []).length, seen: demoSeen.has(a.id), answered: !!demoReplied[a.id] }));

function demoState(T, items) {
  const stamp = k => { const sec = k * 7; const p = n => String(n).padStart(2, '0'); return `2026-06-19T${p((8 + ((sec / 3600) | 0)) % 24)}:${p(((sec / 60) | 0) % 60)}:${p(sec % 60)}`; };
  const run = (id, skill, subject, status, extra) => {
    const subs = (SUBS[skill] || []).map((type, i) => ({ id: `${id}-s${i}`, type, status: (T + i) % 7 === 0 ? 'done' : 'running', last_action: (ACT[skill] || ACT.ask)[(T + i + 1) % (ACT[skill] || ACT.ask).length] }));
    const a = ACT[skill] || ACT.ask;
    return Object.assign({ run_id: id, skill, subject, target: subject || 'hub', status, backend: ['claude', 'codex', 'opencode'][[...id].reduce((a, c) => a + c.charCodeAt(0), 0) % 3], created: stamp(T),
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
  const artifacts = artifactsAt(T);
  for (const x of artifacts.filter(x => x.question && !x.answered)) attention.push({ id: 'artifact:' + x.id, sev: 'warn', kind: 'artifact', title: x.question, body: `with “${x.title}”`, idea: x.study, run_id: x.run_id, detail: { artifact: x.id }, actions: [{ id: 'artifact', label: 'open' }] });
  return { artifacts, now: stamp(T), items: items.map(it => ({ inflight: [], events: [], directives: [], ...it })), runs, attention, workers: [],
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
