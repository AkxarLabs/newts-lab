/* Lab3D.model — what the world shows, worked out from the lab's snapshot with no drawing at all (so it is
 * testable on its own, tests/test_world.py): which rooms stand on the table (a lab per live project), where
 * each stands (the plan, then the lab district), and which room every study and every run belongs in.
 * world.js draws what this decides. */
(function () {
  'use strict';
  const L = (window.Lab3D = window.Lab3D || {});
  const ACTIVE = new Set(['starting', 'running', 'resuming']);
  const M = {};

  /** the workflow the snapshot carries (else the dashboard's, else the shipped default) */
  M.wfOf = s => (s && s.workflow && Array.isArray(s.workflow.rooms) ? s.workflow
    : (window.NL && window.NL.WF && window.NL.WF.rooms ? window.NL.WF : window.__WORKFLOW_DEFAULT__)) || { rooms: [], states: [] };
  M.procsOf = (wf, states) => [...new Set((wf.stages || []).filter(st => (st.states || []).some(x => states.includes(x))).flatMap(st => st.procedures || []))];
  const terminal = (wf, st) => (wf.states || []).concat(wf.side_states || []).some(x => x.id === st && x.terminal);
  M.building = (s, it) => (s.runs || []).some(r => r.skill === 'spawn-project' && (r.subject === it.id || r.target === it.id) && (ACTIVE.has(r.status) || r.status === 'queued'));
  /** a room is one per live project when the workflow says so — or, unsaid, when most procedures it holds run
   *  inside a project (the Lab's do), so a lab made before the flag gets its project labs too */
  M.perProject = (wf, r) => {
    if (r.per_project != null) return !!r.per_project;
    const ps = M.procsOf(wf, r.states || []), lv = wf.procedures || {};
    return ps.length > 0 && ps.filter(p => (lv[p] || {}).level === 'project').length * 2 > ps.length;
  };

  /** the rooms on the table: the workflow's, with a per-project room standing once per live project (titled
   *  by its study), one more while /spawn-project builds a new one, and the bare room when there are none */
  M.roomList = function roomList(s) {
    const wf = M.wfOf(s), items = (s && s.items) || [], out = [];
    for (const r of wf.rooms || []) {
      if (!M.perProject(wf, r)) { out.push({ id: r.id, base: r, title: r.title || r.label || r.id, states: r.states || [], place: r.place, facing: r.facing }); continue; }
      const live = items.filter(i => i.has_project && !terminal(wf, i.state));
      const raising = items.filter(i => !i.has_project && M.building(s, i));
      if (!live.length && !raising.length) out.push({ id: r.id, base: r, title: r.title || r.id, states: r.states || [], place: r.place, facing: r.facing, empty: true });
      live.forEach((it, k) => out.push({ id: `${r.id}:${it.id}`, base: r, title: it.title || it.id, kicker: r.label || 'Lab', states: r.states || [], study: it.id, type: it.project_type,
        place: k === 0 ? r.place : null, facing: k === 0 ? r.facing : null, extra: k > 0 }));
      raising.forEach(it => out.push({ id: `${r.id}:${it.id}`, base: r, title: it.title || it.id, kicker: 'a lab being built', states: [], study: it.id, building: true, extra: true }));
    }
    return out;
  };

  /** where every room stands: the plan (layout.js) for the workflow's rooms, then each further project lab on
   *  the free plot nearest its kind's first lab — a lab district (outward on a tie) → {id: {cell, facing, auto}} */
  M.placeRooms = function placeRooms(list, wf) {
    const side = (wf.side_states || []).map(x => x.id);
    const plan = L.plan(list.filter(r => !r.extra).map(r => ({ id: r.id, place: r.place, facing: r.facing, states: r.states })), side);
    const taken = new Set(['0,0', ...Object.values(plan).map(x => x.cell.join(','))]);
    for (const r of list.filter(x => x.extra)) {
      const first = list.find(x => x.base === r.base && !x.extra), at = (first && plan[first.id]) ? plan[first.id].cell : [1, 0];
      let best = null;
      for (let k = 1; k <= Math.max(Math.abs(at[0]), Math.abs(at[1])) + 3 || !best; k++) for (const c of L.ringCells(k)) {
        if (taken.has(c.join(','))) continue;
        const d = Math.abs(c[0] - at[0]) + Math.abs(c[1] - at[1]) - Math.max(Math.abs(c[0]), Math.abs(c[1])) * 0.01;
        if (!best || d < best.d) best = { c, d };
      }
      taken.add(best.c.join(',')); plan[r.id] = { cell: best.c, facing: L.autoFacing(best.c), auto: true };
    }
    return plan;
  };

  // which room a study, a project's lab, a procedure and a run belong in — `rooms` is what stands: {id: {study, building}}
  M.item = (s, id) => ((s && s.items) || []).find(i => i.id === id);
  M.roomOfItem = function roomOfItem(s, it, rooms) {
    const base = (M.wfOf(s).rooms || []).find(r => (r.states || []).includes(it.state));
    if (!base) return null;
    if (rooms[`${base.id}:${it.id}`]) return `${base.id}:${it.id}`;
    if (!rooms[base.id]) return Object.keys(rooms).find(k => k.startsWith(base.id + ':')) || null;
    return base.id;
  };
  M.labOf = (it, rooms) => Object.keys(rooms).find(k => rooms[k].study === it.id && !rooms[k].building) || null;
  M.roomForProc = function roomForProc(s, proc, rooms) {
    const wf = M.wfOf(s), st = (wf.stages || []).find(x => (x.procedures || []).includes(proc));
    const state = st && (st.states || [])[0], base = state && (wf.rooms || []).find(r => (r.states || []).includes(state));
    return base && rooms[base.id] ? base.id : null;
  };
  /** a run stands where its work is: /design-room in the room it designs, /spawn-project in the lab it builds,
   *  a project-level procedure in its project's lab, other work on a study in that study's room, the rest in
   *  the room of the procedure's stage — or at your desk */
  M.placeOfRun = function placeOfRun(s, r, rooms) {
    const procs = M.wfOf(s).procedures || {}, subj = r.subject || (r.target && r.target !== 'hub' ? r.target : null), it = subj && M.item(s, subj);
    if (r.skill === 'design-room') { const rid = String(r.args || '').split(/\s+/)[0]; if (rooms[rid]) return rid; }
    if (r.skill === 'spawn-project' && it) { const site = Object.keys(rooms).find(k => rooms[k].study === it.id); if (site) return site; }
    if (it) { const lab = M.labOf(it, rooms); if ((procs[r.skill] || {}).level === 'project' && lab) return lab; return M.roomOfItem(s, it, rooms) || 'hub'; }
    return M.roomForProc(s, r.skill, rooms) || 'hub';
  };

  L.model = M;
})();
