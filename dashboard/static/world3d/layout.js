/* Lab3D.plan — where each room stands on the table: plots on a grid, your desk on the plaza at [0, 0].
 * A room with `place: [col, row]` (and `facing: n|e|s|w`) in workflow/stages.yaml stands there; the rest take
 * the next free plot going round the plaza (clockwise from the back-left), in workflow order, the rooms that
 * hold the lifecycle first, door toward your desk. Shared by the world (world3d/lab.html) and Compose's
 * layout editor, so both always agree. */
(function () {
  'use strict';
  const L = (window.Lab3D = window.Lab3D || {});
  L.ringCells = k => { const c = []; for (let x = -k; x <= k; x++) c.push([x, -k]); for (let y = -k + 1; y <= k; y++) c.push([k, y]); for (let x = k - 1; x >= -k; x--) c.push([x, k]); for (let y = k - 1; y > -k; y--) c.push([-k, y]); return c; };
  L.autoFacing = ([c, w]) => (Math.abs(w) >= Math.abs(c) ? (w < 0 ? 's' : 'n') : (c < 0 ? 'e' : 'w'));
  /** rooms: the workflow's rooms · sideStates: ids of states off the lifecycle → {id: {cell, facing, auto}} */
  L.plan = function plan(rooms, sideStates) {
    const side = new Set(sideStates || []), out = {}, taken = new Set(['0,0']);
    const valid = r => Array.isArray(r.place) && r.place.length === 2 && r.place.every(Number.isInteger) && !(r.place[0] === 0 && r.place[1] === 0);
    rooms.filter(valid).forEach(r => { if (!taken.has(r.place.join(','))) { taken.add(r.place.join(',')); out[r.id] = { cell: r.place.slice(), auto: false }; } });
    const queue = []; for (let k = 1; queue.length < rooms.length + 8; k++) queue.push(...L.ringCells(k));
    const main = rooms.filter(r => (r.states || []).some(s => !side.has(s)));
    for (const r of main.concat(rooms.filter(x => !main.includes(x)))) {
      if (!out[r.id]) { const cell = queue.find(c => !taken.has(c.join(','))); taken.add(cell.join(',')); out[r.id] = { cell, auto: true }; }
      out[r.id].facing = ['n', 'e', 's', 'w'].includes(r.facing) ? r.facing : L.autoFacing(out[r.id].cell);
    }
    return out;
  };
})();
