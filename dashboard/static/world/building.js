/* Vivarium world — ROOMS and the cutaway BUILDING.
 *
 *   VivWorld.defineRoom({              // a room's ART (rooms/<key>.js); WHICH rooms exist and where is the workflow's
 *     key, size:[w,h] (default 1440×820),
 *     shell:{ wall, floor, windows:[x…], accent },                     // the room box (see 'shell' below)
 *     stations:{ name:{x,y} },          // where creatures stand (normalised to the room box, feet on the floor)
 *     roleStation:{role:station},        // where each subagent role works here
 *     props:[{ c:'component', at:[x,y], props:{…}, hover?, action? }],   // furniture (feet position, normalised)
 *     paths:[[x,y]…],                   // the walk they stroll along (normalised)
 *   })
 *
 * W.applyWorkflow(wf) makes W.rooms the workflow's rooms (workflow/stages.yaml `rooms:` — title, states,
 * gate, floor, order; each state's `station`) dressed in their art; a room with no art is drawn plain
 * (stations for its states, a standard decor). The building lays rooms out as one cross-section: floors
 * stacked, rooms side by side in `order`, the cut walls and slabs drawn as section poché.
 * Depth: the room is a diorama box; its floor runs from the back wall (y = BACK) to the front edge (y = 1),
 * and anything standing on it is scaled by its depth (smaller toward the back wall).
 */
(function () {
  'use strict';
  const W = (window.VivWorld = window.VivWorld || {});
  const S = W.paper.S;
  const { rng } = W.noise;
  const T = W.tokens;
  const rooms = {};      // what the world draws: the workflow's rooms in their art (W.applyWorkflow)
  const art = {};        // each room file's spec, as written
  W.rooms = rooms;
  W.roomArt = art;
  W.defineRoom = function (spec) {
    if (!spec || !spec.key || !spec.stations) throw new Error('defineRoom needs key and stations');
    art[spec.key] = Object.assign({ size: [1440, 820], order: 99, floor: 0, states: [], props: [], paths: [], shell: {}, stateStation: {}, roleStation: {} }, spec);
    rooms[spec.key] = art[spec.key];
    return art[spec.key];
  };

  /** the furniture every room has (lights, a lantern, plants, a crate) — a plain room's, or any room's: props: W.decor().concat([…]) */
  W.decor = () => [
    { c: 'stringLights', at: [0.5, 0.13], props: { w: 1000, n: 12, swags: 2 } },
    { c: 'lantern', at: [0.5, 0.21], props: {} },
    { c: 'hangingPlant', at: [0.3, 0.25], props: { drop: 180 } },
    { c: 'plant', at: [0.06, 0.93], props: { kind: 'mushrooms', size: 80, seed: 5 } },
    { c: 'plant', at: [0.97, 1.0], props: { kind: 'fern', size: 180, seed: 11 } },
    { c: 'crates', at: [0.8, 0.93], props: { kind: 'books', w: 110 } },
  ];

  /** a room in the workflow with no art: a station per state, signs, the standard decor, its gate's door */
  function plainRoom(m, st) {
    if (typeof console !== 'undefined') console.warn(`Newts' Lab: no art for the room '${m.id}' (rooms/${m.id}.js or lab/rooms/${m.id}.js) — drawing it plain.`);
    const states = m.states || [], n = states.length, stations = {}, signs = [];
    states.forEach((s, i) => {
      const key = (st[s] && st[s].station) || s, x = n <= 1 ? 0.45 : 0.2 + 0.5 * i / (n - 1);
      stations[key] = { x, y: 0.7 };
      signs.push({ c: 'sign', at: [x, 0.6], props: { text: (st[s] && st[s].label) || s } });
    });
    if (!n) stations.middle = { x: 0.45, y: 0.7 };
    const props = W.decor().concat(signs);
    if (m.gate) { stations.gate = { x: 0.86, y: 0.53 }; props.push({ c: 'door', at: [0.88, 0.455], props: { gate: m.gate, w: 130, h: 250 } }); }
    const xs = Object.values(stations).map(p => p.x).sort((a, b) => a - b);
    return Object.assign({}, { key: m.id, size: [1200, 820], order: 99, floor: 0, states: [], stateStation: {}, roleStation: {},
      shell: { wall: 'panels', floor: 'boards', windows: [0.5], accent: 'wash.blue', seed: 7 }, stations, props,
      paths: [[0.12, 0.8], ...xs.map(x => [x, 0.74]), [0.9, 0.8], [0.5, 0.9]], plain: true });
  }

  /** W.rooms ← every room of the workflow, dressed in its art (or plain); without a workflow, the art as declared */
  W.applyWorkflow = function (wf) {
    const man = wf && Array.isArray(wf.rooms) && wf.rooms.length ? wf.rooms : null;
    for (const k of Object.keys(rooms)) delete rooms[k];
    if (!man) { Object.assign(rooms, art); return rooms; }
    const st = {};
    (wf.states || []).concat(wf.side_states || []).forEach(s => { st[s.id] = s; });
    man.forEach((m, i) => {
      const a = art[m.id] || plainRoom(m, st);
      const first = Object.keys(a.stations)[0], stateStation = {};
      (m.states || []).forEach(s => { const want = st[s] && st[s].station; stateStation[s] = a.stations[want] ? want : (a.stateStation[s] || first); });
      rooms[m.id] = Object.assign({}, a, {
        key: m.id, title: m.title || a.title || m.id, states: m.states || [], stateStation,
        gate: m.gate != null ? m.gate : a.gate, floor: m.floor != null ? m.floor : a.floor,
        order: m.order != null ? m.order : (a.order !== 99 ? a.order : 50 + i),
        shell: Object.assign({}, a.shell, { banner: m.title || (a.shell && a.shell.banner) || a.title || m.id }),
      });
    });
    return rooms;
  };

  // the diorama box, normalised: back wall inset, floor from BACK to the front edge
  const BOX = { bx0: 0.07, bx1: 0.93, by0: 0.07, back: 0.44 };
  W.BOX = BOX;
  function depthScale(ny) { const z = Math.max(0, Math.min(1, (ny - BOX.back) / (1 - BOX.back))); return 0.64 + 0.36 * z; }
  W.depthScale = depthScale;

  // ── the room shell component ─────────────────────────────────────────────────
  W.defineComponent('shell', {
    size: p => [p.w, p.h],
    draw(P, p) {
      const w = p.w, h = p.h, X0 = BOX.bx0 * w, X1 = BOX.bx1 * w, Y0 = BOX.by0 * h, YB = BOX.back * h;
      const r = rng(p.seed || 1), night = !P.day;
      // back wall + its motif
      P.piece(S.rect(X0, Y0, X1 - X0, YB - Y0), { fill: 'surface.wall', lift: 0, deckle: 0.3, wash: p.accent || 'wash.ochre', pattern: (x, b) => wallMotif(x, b, p.wall || 'panels', P, r) });
      // windows (show the world outside: sky by day, a luminous night by night)
      for (const wx of (p.windows || [])) {
        const ww = 0.1 * w, cx = X0 + wx * (X1 - X0), wy = Y0 + 0.07 * h, wh = (YB - Y0) * 0.62;
        P.piece(S.arch(cx - ww / 2 - 8, wy - 8, ww + 16, wh + 16), { fill: 'wood.dark', lift: 1.6, hatch: 0.2 });
        P.piece(S.arch(cx - ww / 2, wy, ww, wh), { fill: night ? 'paper.deep' : 'glass.fill', lift: 0.2, wash: night ? 'wash.blue' : 'wash.teal', glow: 'glow.secondary', glowAlpha: night ? 0.35 : 0.6, pattern: (x, b) => { if (night) { x.fillStyle = P.tk('glow.secondary'); for (let i = 0; i < 14; i++) x.fillRect(b.x0 + r() * b.w, b.y0 + r() * b.h * 0.7, 1.4, 1.4); } else { x.fillStyle = T.alpha(P.tk('plant.leaf'), 0.5); for (let i = 0; i < 10; i++) { x.beginPath(); x.arc(b.x0 + r() * b.w, b.y1 - r() * b.h * 0.35, 8 + r() * 14, 0, 6.2832); x.fill(); } } } });
        P.line([[cx, wy + 4], [cx, wy + wh]], { color: 'wood.dark', w: 2.4 }); P.line([[cx - ww / 2, wy + wh * 0.55], [cx + ww / 2, wy + wh * 0.55]], { color: 'wood.dark', w: 2.4 });
        P.piece(S.rect(cx - ww / 2 - 14, wy + wh + 4, ww + 28, 10), { fill: 'surface.wallAlt', lift: 1.6 });
      }
      // skirting
      P.piece(S.rect(X0, YB - 12, X1 - X0, 12), { fill: 'wood.dark', lift: 0.6, deckle: 0.2 });
      // ceiling, side walls, floor (the box around the back wall)
      P.piece(S.poly([[0, 0], [w, 0], [X1, Y0], [X0, Y0]]), { fill: 'surface.ceiling', lift: 0.4, hatch: 0.55, deckle: 0.3, pattern: (x) => { x.strokeStyle = T.alpha(P.tk('wood.dark'), 0.7); x.lineWidth = 5; for (let i = 1; i < 6; i++) { const t = i / 6; x.beginPath(); x.moveTo(t * w, 0); x.lineTo(X0 + t * (X1 - X0), Y0); x.stroke(); } } });
      P.piece(S.poly([[0, 0], [X0, Y0], [X0, YB], [0, h]]), { fill: 'surface.wallAlt', lift: 0.4, hatch: 0.5, hatchSide: 'left', deckle: 0.3 });
      P.piece(S.poly([[w, 0], [X1, Y0], [X1, YB], [w, h]]), { fill: 'surface.wallAlt', lift: 0.4, hatch: 0.5, hatchSide: 'right', deckle: 0.3 });
      P.piece(S.poly([[X0, YB], [X1, YB], [w, h], [0, h]]), { fill: 'surface.floor', lift: 0.4, deckle: 0.3, pattern: (x) => floorMotif(x, w, h, X0, X1, YB, p.floor || 'boards', P) });
      // a banner with the room's name, hand-lettered, pinned to the back wall
      if (p.banner) {
        const bw = Math.max(200, p.banner.length * 17 + 60), cx = w / 2, by = Y0 + 16;
        P.piece(S.poly([[cx - bw / 2 - 18, by], [cx - bw / 2, by + 16], [cx - bw / 2 - 18, by + 32], [cx + bw / 2 + 18, by + 32], [cx + bw / 2, by + 16], [cx + bw / 2 + 18, by]]), { fill: 'label.plate', lift: 2, wash: p.accent || 'wash.ochre' });
        P.text(p.banner, cx, by + 17, { size: 22, weight: 700 });
      }
      // night: roots creep down from the ceiling and mushrooms glow along the skirting — the cave remembers
      // day: sketchy ivy in the corners
      const vines = night ? 7 : 4;
      for (let i = 0; i < vines; i++) {
        const sx = (i < vines / 2 ? r() * X0 * 1.6 : w - r() * X0 * 1.6), len = 60 + r() * (night ? 220 : 120), pts = [[sx, 0]];
        for (let k = 1; k <= 8; k++) pts.push([sx + Math.sin(k * 0.9 + i) * 10 + (i < vines / 2 ? k * 3 : -k * 3), k * len / 8]);
        P.line(pts, { color: night ? 'plant.stem' : 'plant.leafDark', w: night ? 2.2 : 1.3, glow: night ? 'ink.faint' : null });
        for (let k = 2; k <= 8; k += 2) P.piece(S.leaf(pts[k][0], pts[k][1], 12 + r() * 8, 4 + r() * 3, (i % 2 ? 0.6 : 2.5) + r() * 0.5), { fill: 'plant.leaf', lift: 0.8, deckle: 0.3, inkW: 0.5 });
      }
      if (night) {
        for (let i = 0; i < 6; i++) { const mx = i < 3 ? X0 + 20 + r() * 80 : X1 - 20 - r() * 80; W.drawHelpers.plantAt(P, mx, YB - 10 + (i % 3) * 4, 30 + r() * 20, 'mushrooms', i * 7 + (p.seed || 1)); }
        for (let i = 0; i < 4; i++) { const mx = r() < 0.5 ? 20 + r() * 60 : w - 20 - r() * 60; W.drawHelpers.plantAt(P, mx, h - 20 - r() * 40, 40 + r() * 30, 'mushrooms', i * 13 + (p.seed || 3)); }
      }
    },
  });

  function wallMotif(x, b, kind, P, r) {
    const line = T.alpha(P.tk(P.day ? 'ink.line' : 'ink.soft'), P.day ? 0.35 : 0.5);
    x.strokeStyle = line; x.lineWidth = 1;
    if (kind === 'bricks' || kind === 'stone') {
      const rh = kind === 'stone' ? 34 : 22;
      for (let y = b.y0 + rh, row = 0; y < b.y1; y += rh, row++) {
        x.beginPath(); x.moveTo(b.x0, y); x.lineTo(b.x1, y); x.stroke();
        const bw = kind === 'stone' ? 70 : 46;
        for (let xx = b.x0 + (row % 2) * bw / 2 + (kind === 'stone' ? r() * 20 : 0); xx < b.x1; xx += bw + (kind === 'stone' ? r() * 30 : 0)) { x.beginPath(); x.moveTo(xx, y - rh); x.lineTo(xx, y); x.stroke(); }
      }
    } else if (kind === 'tiles') {
      for (let y = b.y0; y < b.y1; y += 26) { x.beginPath(); x.moveTo(b.x0, y); x.lineTo(b.x1, y); x.stroke(); }
      for (let xx = b.x0; xx < b.x1; xx += 26) { x.beginPath(); x.moveTo(xx, b.y0); x.lineTo(xx, b.y1); x.stroke(); }
    } else {   // panels: wainscot below, a picture rail, vertical boards
      const rail = b.y0 + b.h * 0.55;
      x.lineWidth = 2; x.beginPath(); x.moveTo(b.x0, rail); x.lineTo(b.x1, rail); x.stroke(); x.lineWidth = 1;
      for (let xx = b.x0 + 40; xx < b.x1; xx += 80) { x.strokeRect(xx - 30, rail + 12, 60, b.y1 - rail - 30); }
      for (let xx = b.x0; xx < b.x1; xx += 16) { x.globalAlpha = 0.35; x.beginPath(); x.moveTo(xx, b.y0); x.lineTo(xx, rail); x.stroke(); } x.globalAlpha = 1;
    }
  }
  function floorMotif(x, w, h, X0, X1, YB, kind, P) {
    x.strokeStyle = T.alpha(P.tk('surface.floorLine'), P.day ? 0.9 : 0.8); x.lineWidth = 1.2;
    const n = kind === 'tiles' ? 12 : 16;
    for (let i = 0; i <= n; i++) { const t = i / n; x.beginPath(); x.moveTo(X0 + t * (X1 - X0), YB); x.lineTo(t * w, h); x.stroke(); }
    const m = kind === 'tiles' ? 8 : 5;
    for (let k = 1; k <= m; k++) { const t = Math.pow(k / (m + 1), 1.35), y = YB + (h - YB) * t, xl = X0 * (1 - t), xr = X1 + (w - X1) * t; x.beginPath(); x.moveTo(xl, y); x.lineTo(xr, y); x.stroke(); }
    if (kind === 'boards') { x.globalAlpha = 0.25; for (let i = 0; i < n; i++) { const t = (i + 0.5) / n; x.beginPath(); x.moveTo(X0 + t * (X1 - X0), YB + 20); x.lineTo(t * w, h - 30); x.stroke(); } x.globalAlpha = 1; }
  }

  // ── the building layout ─────────────────────────────────────────────────────
  const WALL = 56, SLAB = 72;
  /** Place every defined room: floors stacked (upper floors centred on the ground floor), rooms in order. */
  function layout() {
    const list = Object.values(rooms), floors = {};
    for (const r of list) (floors[r.floor] = floors[r.floor] || []).push(r);
    for (const k in floors) floors[k].sort((a, b) => a.order - b.order);
    const rowW = f => floors[f].reduce((s, r) => s + r.size[0], 0) + WALL * (floors[f].length + 1);
    const rowH = f => Math.max(...floors[f].map(r => r.size[1]));
    const groundW = floors[0] ? rowW(0) : Math.max(...Object.keys(floors).map(rowW));
    const boxes = {}, rows = [];
    const keys = Object.keys(floors).map(Number).sort((a, b) => a - b);
    // y of each floor's bottom: ground at 0, upper floors stacked above, cellars below
    const bottom = {}; bottom[0] = 0;
    for (const f of keys.filter(f => f > 0)) bottom[f] = bottom[f - 1 in bottom ? f - 1 : 0] - (floors[f - 1] ? rowH(f - 1) : 0) - SLAB;
    for (const f of keys.filter(f => f < 0).sort((a, b) => b - a)) bottom[f] = (bottom[f + 1] != null ? bottom[f + 1] : 0) + SLAB + rowH(f);
    for (const f of keys) {
      const w = rowW(f), hh = rowH(f);
      let x = (groundW - w) / 2 + WALL;
      for (const r of floors[f]) { boxes[r.key] = { x, y: bottom[f] - r.size[1], w: r.size[0], h: r.size[1], floor: f }; x += r.size[0] + WALL; }
      rows.push({ floor: f, x: (groundW - w) / 2, y: bottom[f] - hh, w, h: hh });
    }
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const b of Object.values(boxes)) { x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h); }
    return { boxes, rows, WALL, SLAB, bbox: { x: x0, y: y0, w: x1 - x0, h: y1 - y0, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 } };
  }
  W.layoutBuilding = layout;

  /** registry state → room key (the lifecycle grouping, declared by the rooms themselves) */
  W.stateRoom = function () { const m = {}; for (const r of Object.values(rooms)) for (const s of r.states) m[s] = r.key; return m; };
})();
