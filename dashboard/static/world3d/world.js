/* Newts' Lab — the world: the lab as an open-plan tabletop (three.js), drawn from the live lab.
 *
 * The rooms are the workflow's, on plots round the PI's desk (world3d/layout.js), each in its own look
 * (a built-in world3d/rooms/<id>.js, the lab's lab/rooms3d/<id>.json, or plain). A room the workflow marks
 * `per_project` (the Lab) is one room PER LIVE PROJECT: a new project gets a new lab, built while
 * /spawn-project runs; its look can follow the project's type (lab/rooms3d/lab.<type>.json).
 * Every RUN is a newt at the station of the procedure it runs, in a family colour of its own; its
 * SUBAGENTS are smaller newts in the same colours. A run waiting for the PI walks to the desk and raises a
 * hand; a stalled one dozes; a failed one slumps. Studies are cards on their room's shelf; when a study
 * moves on, a newt carries its card along the streets to the next room (and waits at a gate for the
 * signature). Lenses re-tint the table by what the PI asks: work, cost, waiting, risk.
 *
 * Lab3D.createWorld(canvas, {lamp, reduced}) → the world contract scene.js wraps (sync, setPose, setLamp,
 * setView, goRoom, focusProject, back, viewInfo, highlight, layout, setAmbient, followWorker/stopFollow/
 * following, setLens, on* callbacks). Nothing in here writes anything: clicks call back into the dashboard.
 */
(function () {
'use strict';
const L = window.Lab3D;
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const hash01 = s => { let h = 2166136261; for (let i = 0; i < (s || '').length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 100000) / 100000; };
const ROLE_BADGE = { 'experiment-runner': '#3fb8a6', overseer: '#6f9be6', 'fresh-context-reviewer': '#9b84ea', 'ideation-critic': '#e57ab5',
  'scoping-advocate': '#e0a346', 'general-purpose': '#9aa7ad', orchestrator: '#e0b44e' };
const ACTIVE = new Set(['starting', 'running', 'resuming']);
const WALK = 3.0, STREET = 3.4, PLAZA = 13, ROOMSCALE = 1.15, SUB_SCALE = 0.62;
function three() { return window.THREE ? Promise.resolve(window.THREE) : new Promise(r => addEventListener('three:ready', () => r(window.THREE), { once: true })); }
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

L.createWorld = async function createWorld(canvas, opts) {
  opts = opts || {};
  const THREE = await Promise.race([three(), new Promise(r => setTimeout(() => r(null), 8000))]);
  if (!THREE) throw new Error('three.js did not load');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });     // throws without WebGL
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(30, 1, 0.5, 900);
  const overlay = document.createElement('div'); overlay.className = 'world-labels'; overlay.setAttribute('aria-hidden', 'true'); canvas.after(overlay);
  const tip = document.createElement('div'); tip.className = 'world-tip'; overlay.after(tip);

  let theme = opts.lamp === 'day' ? 'day' : 'night', K = null, TH = null, reduced = !!opts.reduced, ambient = true;
  let snap = null, lens = 'work', pose = 'idle', highlightRole = null, followKey = null, view = { level: 'WORLD', room: null, label: '' };
  let onLab = null, onArtifact = null, onItem = null, onInbox = null, onWorker = null, onRun = null, onNewt = null, onView = null, onFollow = null;
  let staticSig = '', W = null;                 // the built table: rooms, streets, gates, hub
  const actors = new Map(), cards = new Map(), pickables = new Set();
  let looksSig = null, settled = false;      // (null: the starter looks load even for a lab with none of its own)
  const knownRooms = new Set();

  // ── the lab's own room looks (data), fetched when they change ──────────────────────────────────
  async function loadLooks(sig) {
    if (sig === looksSig) return false;
    looksSig = sig;
    try { const r = await fetch('/api/rooms3d', { credentials: 'same-origin' }); if (r.ok) ((await r.json()).rooms || []).forEach(d => L.defineRoomData(d)); } catch (e) { /* a page with no lab behind it */ }
    return true;
  }

  // ── what the table holds: the workflow's rooms, a lab per live project ───────────────────────────
  const M = L.model, wfOf = M.wfOf, procsOf = M.procsOf, roomList = M.roomList;
  function plainSpec(id, procs) {
    const n = Math.max(1, procs.length), w = Math.max(7, 2.4 * n + 2), stations = {}, props = [];
    procs.forEach((p, i) => { const x = -w / 2 + 1.6 + i * 2.4; props.push({ c: 'workstation', at: [x, -1.6], props: { monitors: 1 + (i % 2) } }); stations[p] = [x, -0.95, Math.PI]; });
    props.push({ c: 'plant', at: [w / 2 - 0.8, 1.8], props: { kind: 'tall' } }, { c: 'cabinet', at: [-w / 2 + 0.6, 1.2], rot: Math.PI / 2 });
    return { key: id, size: [w, 6], floor: 'tiles', accent: 'blue', props, stations, roleStation: {} };
  }
  function scaled(sp, k) {
    const pt = a => a && [a[0] * k, a[1] * k, a[2]];
    return Object.assign({}, sp, { size: [sp.size[0] * k, sp.size[1] * k], props: (sp.props || []).map(p => Object.assign({}, p, { at: [p.at[0] * k, p.at[1] * k] })),
      stations: Object.fromEntries(Object.entries(sp.stations || {}).map(([n, a]) => [n, pt(a)])), roleStation: Object.fromEntries(Object.entries(sp.roleStation || {}).map(([n, a]) => [n, pt(a)])) });
  }

  // ── building the table (again whenever its rooms, their looks or the theme change) ───────────────
  function buildStatic(s) {
    const wf = wfOf(s), list = roomList(s);
    const sig = JSON.stringify([theme, looksSig, list.map(r => [r.id, r.place, r.facing, r.type, r.building, r.empty]), (wf.gates || []).map(g => [g.n, g.at, g.before])]);
    if (sig === staticSig && W) return false;
    staticSig = sig;
    if (W) { scene.remove(W.group); W.rooms && Object.values(W.rooms).forEach(o => o.g && pickables.delete(o.floor)); pickables.clear(); }
    const sameTheme = !!K && K.themeName === theme;
    K = L.kit(THREE, theme); TH = K.th;
    // the agents stay where they are while the table changes round them (a new lab rising, a room moved):
    // each walks on from where it stands; only couriers (their cards are rebuilt) and a theme change start over
    for (const [key, a] of actors) {
      if (a.courier) { scene.remove(a.n.group); actors.delete(key); continue; }
      if (!sameTheme) { const old = a.n.group, n = body(a.spec); n.character = characterOf(a.spec);
        n.group.position.copy(old.position); n.group.rotation.copy(old.rotation); n.group.scale.copy(old.scale); n.group.userData.pick = old.userData.pick;
        scene.remove(old); scene.add(n.group); a.n = n; }
      a.room = 'street'; a.dest = null; a.path = []; pickables.add(a.n.group);
    }
    for (const c of cards.values()) scene.remove(c); cards.clear();
    const group = new THREE.Group(); scene.add(group);
    // lights
    while (scene.children.some(c => c.isLight)) scene.remove(scene.children.find(c => c.isLight));
    scene.add(new THREE.HemisphereLight(theme === 'night' ? 0x7f9fb0 : 0xffffff, theme === 'night' ? 0x1a2024 : 0xd8cbb4, TH.hemi));
    const sun = new THREE.DirectionalLight(theme === 'night' ? 0x9fc7ff : 0xfff3df, TH.sun); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.03; scene.add(sun);
    renderer.toneMappingExposure = theme === 'night' ? 1.1 : 1.0;
    // where every room stands
    const plan = M.placeRooms(list, wf);      // the plan, then the lab district
    const DIR = { s: [0, 1], n: [0, -1], e: [1, 0], w: [-1, 0] }, RY = { s: 0, n: Math.PI, e: Math.PI / 2, w: -Math.PI / 2 };
    const rooms = {};
    for (const r of list) {
      const look = (r.type && L.rooms[`${r.base.id}.${r.type}`]) || L.rooms[r.base.id] || plainSpec(r.base.id, procsOf(wf, r.states));
      const sp = scaled(look, r.study || r.empty ? ROOMSCALE * 1.05 : ROOMSCALE), p = plan[r.id], turned = p.facing === 'e' || p.facing === 'w';
      rooms[r.id] = { ...r, cell: p.cell, facing: p.facing, spec: sp, ry: RY[p.facing], dir: DIR[p.facing], ex: turned ? sp.size[1] : sp.size[0], ez: turned ? sp.size[0] : sp.size[1], procs: procsOf(wf, r.states) };
    }
    // the grid: columns as wide as their widest room, rows as deep as their deepest, streets between
    const cells = Object.values(rooms).map(o => o.cell).concat([[0, 0]]);
    const C0 = Math.min(...cells.map(c => c[0])), C1 = Math.max(...cells.map(c => c[0])), R0 = Math.min(...cells.map(c => c[1])), R1 = Math.max(...cells.map(c => c[1]));
    const colW = {}, rowH = {};
    for (let c = C0; c <= C1; c++) colW[c] = Math.max(c === 0 ? PLAZA : 8, ...Object.values(rooms).filter(o => o.cell[0] === c).map(o => o.ex + 1.2)) + STREET;
    for (let w = R0; w <= R1; w++) rowH[w] = Math.max(w === 0 ? PLAZA : 8, ...Object.values(rooms).filter(o => o.cell[1] === w).map(o => o.ez + 1.2)) + STREET;
    const XS = [], ZS = [];
    { let x = 0; for (let c = C0; c <= C1; c++) { XS.push(x); x += colW[c]; } XS.push(x); let z = 0; for (let w = R0; w <= R1; w++) { ZS.push(z); z += rowH[w]; } ZS.push(z); }
    const ox = XS[-C0] + colW[0] / 2, oz = ZS[-R0] + rowH[0] / 2;
    XS.forEach((v, i) => { XS[i] = v - ox; }); ZS.forEach((v, i) => { ZS[i] = v - oz; });
    const cx = c => XS[c - C0] + colW[c] / 2, cz = w => ZS[w - R0] + rowH[w] / 2;
    const toWorld = (o, lx, lz) => [o.x + lx * Math.cos(o.ry) + lz * Math.sin(o.ry), o.z - lx * Math.sin(o.ry) + lz * Math.cos(o.ry)];
    for (const o of Object.values(rooms)) {
      o.x = cx(o.cell[0]); o.z = cz(o.cell[1]); o.hx = colW[o.cell[0]] / 2; o.hz = rowH[o.cell[1]] / 2;
      o.door = toWorld(o, 0, o.spec.size[1] / 2 + 0.5); o.street = [o.x + o.dir[0] * o.hx, o.z + o.dir[1] * o.hz];
      // every procedure of the room has a station: the look's, else a desk added by the front
      o.st = Object.assign({}, o.spec.stations); o.extraProps = [];
      o.procs.filter(p => !o.st[p]).forEach((p, i) => { const [w, d] = o.spec.size, x = w / 2 - 1.3 - i * 2.2; o.extraProps.push({ c: 'workstation', at: [x, d / 2 - 1.8] }); o.st[p] = [x, d / 2 - 1.2, Math.PI]; });
      const [w, d] = o.spec.size; o.spots = [];                               // somewhere to stand when no station fits
      for (let i = 0; i < 12; i++) o.spots.push([(-0.32 + (i % 4) * 0.2) * w, (0.05 + Math.floor(i / 4) * 0.12) * d, Math.PI]);
      o.shelfAt = [-w / 2 + 0.5, d / 2 - 0.55]; o.toWorld = (lx, lz) => toWorld(o, lx, lz);
    }
    const EXT = { x0: XS[0], x1: XS[XS.length - 1], z0: ZS[0], z1: ZS[ZS.length - 1] };
    const SPAN = Math.max(EXT.x1 - EXT.x0, EXT.z1 - EXT.z0) / 2 + 2.5;
    sun.position.set(-SPAN * 0.7, SPAN * 1.3, SPAN * 0.9); Object.assign(sun.shadow.camera, { left: -SPAN - 4, right: SPAN + 4, top: SPAN + 4, bottom: -SPAN - 4, near: 1, far: SPAN * 4 }); sun.shadow.camera.updateProjectionMatrix();
    // the tabletop, its streets, the plaza, a park on any empty plot
    const slab = (x0, z0, x1, z1, r, h, y, c) => {
      const sh = new THREE.Shape(); sh.moveTo(x0 + r, z0); sh.lineTo(x1 - r, z0); sh.quadraticCurveTo(x1, z0, x1, z0 + r); sh.lineTo(x1, z1 - r); sh.quadraticCurveTo(x1, z1, x1 - r, z1);
      sh.lineTo(x0 + r, z1); sh.quadraticCurveTo(x0, z1, x0, z1 - r); sh.lineTo(x0, z0 + r); sh.quadraticCurveTo(x0, z0, x0 + r, z0);
      const g = new THREE.ExtrudeGeometry(sh, { depth: h, bevelEnabled: false, curveSegments: 10 }); g.rotateX(Math.PI / 2);
      const m = new THREE.Mesh(g, K.mat(c)); m.position.y = y; m.receiveShadow = true; return m;
    };
    const RIM = 1.6;
    group.add(slab(EXT.x0 - RIM, EXT.z0 - RIM, EXT.x1 + RIM, EXT.z1 + RIM, 2.2, 0.35, 0, TH.table));
    group.add(slab(EXT.x0 - RIM + 0.1, EXT.z0 - RIM + 0.1, EXT.x1 + RIM - 0.1, EXT.z1 + RIM - 0.1, 2.1, 1.3, -0.35, TH.tableSide));
    group.add(slab(EXT.x0 - RIM + 0.6, EXT.z0 - RIM + 0.6, EXT.x1 + RIM - 0.6, EXT.z1 + RIM - 0.6, 1.8, 1.5, -1.65, TH.soil));
    const flat = (geo, c, y) => { const m = new THREE.Mesh(geo, K.mat(c)); m.rotation.x = -Math.PI / 2; m.position.y = y || 0.012; m.receiveShadow = true; return m; };
    for (const x of XS) { const st = flat(new THREE.PlaneGeometry(STREET - 0.6, EXT.z1 - EXT.z0 + STREET), TH.path); st.position.set(x, 0.012, (EXT.z0 + EXT.z1) / 2); group.add(st); }
    for (const z of ZS) { const st = flat(new THREE.PlaneGeometry(EXT.x1 - EXT.x0 + STREET, STREET - 0.6), TH.path, 0.013); st.position.set((EXT.x0 + EXT.x1) / 2, 0.013, z); group.add(st); }
    group.add(K.cyl(Math.min(colW[0], rowH[0]) / 2 - 2.0, Math.min(colW[0], rowH[0]) / 2 - 1.9, 0.1, TH.path, 0, 0, 0, { seg: 48 }));
    const taken = new Set(cells.map(c => c.join(',')));
    let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    for (let c = C0; c <= C1; c++) for (let w = R0; w <= R1; w++) {
      if (taken.has(c + ',' + w)) continue;
      const pw = colW[c] - STREET, ph = rowH[w] - STREET; group.add(K.box(pw, 0.08, ph, TH.grass, cx(c), 0, cz(w)));
      for (let i = 0; i < 5; i++) group.add(K.at(K.build('tree', { size: 0.8 + rnd() * 0.6 }), cx(c) + (rnd() - 0.5) * (pw - 2), 0.08, cz(w) + (rnd() - 0.5) * (ph - 2)));
    }
    for (let i = 0; i < 18; i++) { const sd = i % 4, u = rnd(); const x = sd < 2 ? EXT.x0 + u * (EXT.x1 - EXT.x0) : (sd === 2 ? EXT.x0 - M * 0.55 : EXT.x1 + M * 0.55), z = sd < 2 ? (sd ? EXT.z1 + M * 0.55 : EXT.z0 - M * 0.55) : EXT.z0 + u * (EXT.z1 - EXT.z0); group.add(K.at(K.build('tree', { size: 0.55 + rnd() * 0.4 }), x, 0, z)); }
    // your desk, Newt at it, the inbox tray
    const hub = K.build('hubDesk'); hub.userData.pick = { kind: 'hub' }; group.add(hub); pickables.add(hub);
    const inbox = new THREE.Group(); inbox.position.set(0.55, 0.98, 0.1); group.add(inbox);
    const bigNewt = L.makeNewt(K, { scale: 1.4 }); bigNewt.group.position.set(0, 0.12, -1.0); bigNewt.group.userData.pick = { kind: 'newt' }; group.add(bigNewt.group); pickables.add(bigNewt.group);
    // the rooms
    for (const o of Object.values(rooms)) buildRoom(o, group);
    // gates: an arch on the street at the door of the room where each gate is signed
    const gates = {};
    for (const g of wf.gates || []) {
      const host = Object.values(rooms).find(o => (o.states || []).includes(g.at) && !o.extra && !o.building) || Object.values(rooms).find(o => (o.states || []).includes(g.at));
      if (!host || !g.before) continue;
      const p = [host.street[0] + (host.door[0] - host.street[0]) * 0.3, host.street[1] + (host.door[1] - host.street[1]) * 0.3];
      const arch = K.build('gateArch'); arch.position.set(p[0], 0, p[1]); arch.rotation.y = host.ry; arch.userData.pick = { kind: 'gate', gate: g.n }; group.add(arch); pickables.add(arch);
      const lamp = K.sphere(0.16, 'amber', 0, 2.62, 0, { glow: 'amber', gi: 0.2 }); arch.add(lamp);
      [0.17, -0.17].forEach((zz, i) => { const pl = K.sign('Gate ' + g.n, { h: 0.26, font: '600 40px "IBM Plex Mono", monospace' }); pl.position.set(0, 2.33, zz); if (i) pl.rotation.y = Math.PI; arch.add(pl); });
      gates[g.n] = { arch, lamp, g, pos: p, host };
    }
    group.traverse(m => { if (m.isMesh && m.geometry && m.geometry.type === 'PlaneGeometry') m.castShadow = false; });
    W = { group, rooms, XS, ZS, colW, rowH, EXT, SPAN, hub, inbox, bigNewt, gates, sun, hubExits: Object.values(DIR).map(d => [d[0] * colW[0] / 2, d[1] * rowH[0] / 2]) };
    buildNeighbours();
    fitCamera(true);
    return true;
  }

  // ── what agents made for you: a sheet pinned on a little board in the room the work happened in (amber when it
  // asks you something); opened artifacts come down. Click one to read it.
  let sheetGroup = null, sheetSig = '';
  function pinSheets(s) {
    if (!W) return;
    const runs = new Map(((s && s.runs) || []).map(r => [r.run_id, r]));
    const where = a => {
      const r = a.run_id && runs.get(a.run_id);
      if (r) { const rid = placeOfRun(s, r); if (W.rooms[rid]) return rid; }
      const it = a.study && item(s, a.study), rid = it && (labOf(it) || roomOfItem(s, it));
      return rid && W.rooms[rid] ? rid : null;
    };
    const up = ((s && s.artifacts) || []).filter(a => !a.answered && (!a.seen || a.question)).slice(0, 30).map(a => ({ a, room: where(a) })).filter(x => x.room);
    const sig = JSON.stringify([staticSig, up.map(x => [x.a.id, x.room, !!x.a.question])]);
    if (sig === sheetSig && sheetGroup) return;
    sheetSig = sig;
    if (sheetGroup) { scene.remove(sheetGroup); sheetGroup.traverse(o => pickables.delete(o)); }
    sheetGroup = new THREE.Group(); scene.add(sheetGroup);
    const byRoom = {};
    up.forEach(x => (byRoom[x.room] = byRoom[x.room] || []).push(x.a));
    for (const [rid, list] of Object.entries(byRoom)) {
      const o = W.rooms[rid], [w, d] = o.spec.size, n = Math.min(list.length, 4);
      const board = K.group(K.cyl(0.04, 0.04, 1.3, 'woodDark', -0.75, 0, 0), K.cyl(0.04, 0.04, 1.3, 'woodDark', 0.75, 0, 0), K.box(1.7, 0.95, 0.06, 'woodLight', 0, 0.75, 0));
      const [bx, bz] = o.toWorld(w / 2 - 1.3, d / 2 - 0.45);
      board.position.set(bx, 0, bz); board.rotation.y = o.ry; sheetGroup.add(board);
      list.slice(0, n).forEach((a, i) => {
        const sh = K.group(K.box(0.34, 0.44, 0.02, a.question ? 'amber' : 'paper', 0, 0, 0, a.question ? { glow: true, gi: K.night ? 0.8 : 0.25 } : null),
          K.sphere(0.045, a.question ? 'red' : 'teal', 0, 0.4, 0.03));
        sh.position.set(-0.55 + i * 0.37, 0.98 + (i % 2) * 0.06, 0.05); sh.rotation.z = (i % 2 ? -1 : 1) * 0.06;
        sh.userData.pick = { kind: 'artifact', id: a.id }; board.add(sh); pickables.add(sh);
      });
      if (list.length > n) board.add(K.sphere(0.1, 'amber', 0.78, 1.32, 0.05, { glow: true }));
    }
  }

  // ── your other labs (this computer's and other machines', all in this one dashboard): small tables beyond the
  // back edge, a bridge to each — its name, what waits on you there, how many agents are at work. Click to go.
  let neighbours = [], nbGroup = null, nbSig = '';
  function buildNeighbours() {
    if (!W) return;
    const sig = JSON.stringify([theme, W.EXT, neighbours.map(n => [n.key, n.needs, n.running, n.state])]);
    if (sig === nbSig && nbGroup) return;
    nbSig = sig;
    if (nbGroup) { scene.remove(nbGroup); nbGroup.traverse(o => pickables.delete(o)); }
    nbGroup = new THREE.Group(); scene.add(nbGroup);
    const list = neighbours.slice(0, 6), E = W.EXT, wide = E.x1 - E.x0, step = Math.min(22, (wide + 16) / Math.max(1, list.length));
    list.forEach((nb, i) => {
      const x = (E.x0 + E.x1) / 2 + (i - (list.length - 1) / 2) * step, z = E.z0 - 11;   // spread along the back edge
      const g = new THREE.Group(); g.position.set(x, 0, z);
      const off = nb.state !== 'here' && nb.state !== 'connected';
      g.add(K.box(9, 0.3, 6, off ? TH.tableSide : TH.table, 0, -0.3, 0), K.box(8.6, 1.0, 5.6, TH.tableSide, 0, -1.3, 0));
      [[-2.6, -1.2], [0, -1.4], [2.6, -1.1], [-1.4, 1.2], [1.6, 1.3]].forEach(([a, b], k) => g.add(K.box(2.0, 0.55 + (k % 2) * 0.2, 1.6, off ? 'plasterDark' : 'plaster', a, 0, b)));
      for (let k = 0; k < Math.min(8, nb.running || 0); k++) g.add(K.sphere(0.22, 'teal', -3 + k * 0.85, 1.05, 2.3, { glow: true }));   // agents at work
      if (nb.needs) { const f = K.group(K.cyl(0.05, 0.05, 2.2, 'woodDark', 0, 0, 0), K.box(0.9, 0.55, 0.05, 'amber', 0.47, 1.6, 0, { glow: true })); f.position.set(3.6, 0, -2.2); g.add(f); }
      const bridge = K.box(1.4, 0.18, 11 - 3 - 1.6, TH.table, 0, -0.12, 3 + (11 - 3 - 1.6) / 2 - 0.4); g.add(bridge);
      g.userData.pick = { kind: 'otherlab', key: nb.key };
      g.traverse(o => { if (o.isMesh) o.castShadow = false; });
      nbGroup.add(g); pickables.add(g); nb._at = [x, z];
    });
  }

  function buildRoom(o, group) {
    const sp = o.spec, [w, d] = sp.size, g = new THREE.Group(); g.position.set(o.x, 0, o.z); g.rotation.y = o.ry; group.add(g); o.g = g;
    o.floorMat = K.mat(sp.floor === 'grass' ? TH.grass : sp.floor).clone(); o.floorBase = o.floorMat.color.clone();
    const fl = new THREE.Mesh(new THREE.BoxGeometry(w, 0.14, d), o.floorMat); fl.position.y = 0.07; fl.receiveShadow = true; fl.userData.pick = { kind: 'room', id: o.id }; g.add(fl); pickables.add(fl); o.floor = fl;
    g.add(K.box(w, 0.05, 0.22, sp.accent, 0, 0.14, d / 2 - 0.11));
    o.walls = [];
    const wallH = o.building ? 0.5 : 1.5;
    if (sp.walls !== false) for (const [lx, lz, len, nx, nz] of [[0, -d / 2, w, 0, -1], [-w / 2, 0, d, -1, 0], [w / 2, 0, d, 1, 0]]) {
      const wall = K.box(nz ? len : 0.16, wallH, nz ? 0.16 : len, sp.wall || 'plaster', lx, 0.14, lz, o.building ? { alpha: 0.55 } : undefined); g.add(wall);
      const cap = K.box(nz ? len + 0.02 : 0.2, 0.06, nz ? 0.2 : len + 0.02, sp.accent, lx, 0.14 + wallH + 0.0, lz); g.add(cap);
      o.walls.push({ wall, cap, n: [nx, nz], lx, lz, h: wallH });
    }
    const sign = K.sign(o.title, { h: 0.42 }); sign.position.set(0, 1.25, -d / 2 + 0.1); g.add(sign);
    if (knownRooms.size && !knownRooms.has(o.id) && !reduced) { g.scale.y = 0.02; o.rising = true; }   // a new room rises out of the table
    knownRooms.add(o.id);
    if (o.building) {            // a lab going up: scaffolding, cones, crates, the furniture still to come
      [[-w / 2 + 0.4, -d / 2 + 0.4], [w / 2 - 0.4, -d / 2 + 0.4], [-w / 2 + 0.4, d / 2 - 0.6], [w / 2 - 0.4, d / 2 - 0.6]].forEach(([x, z]) => g.add(K.box(0.12, 2.6, 0.12, 'ochre', x, 0.14, z)));
      g.add(K.box(w, 0.1, 0.12, 'ochre', 0, 2.6, -d / 2 + 0.4)); for (let i = 0; i < 4; i++) g.add(K.cone(0.18, 0.45, 'amber', -w / 3 + i * w / 4.5, 0.14, d / 2 - 0.4));
      g.add(K.at(K.build('crates', { n: 4 }), 0, 0.14, 0));
      return;
    }
    for (const p of (sp.props || []).concat(o.extraProps)) { const m = K.build(p.c, p.props); m.position.set(p.at[0], 0.14, p.at[1]); m.rotation.y = p.rot || 0; g.add(m); }
    g.add(K.box(Math.min(3.4, w * 0.4), 0.42, 0.5, 'woodLight', o.shelfAt[0] + Math.min(3.4, w * 0.4) / 2, 0.14, o.shelfAt[1]));
    if (o.empty) { const s2 = K.sign('No projects yet — a lab is built for each one', { h: 0.28, font: 'italic 500 34px Newsreader, Georgia, serif' }); s2.position.set(0, 0.6, d / 2 - 0.05); g.add(s2); }
    if (theme === 'night') { const pl = new THREE.PointLight(0xffc98a, 14, 10, 1.6); pl.position.set(0, 2.8, 0); g.add(pl); }
  }

  // ── streets: a walk between any two places ───────────────────────────────────────────────────────
  const near = (v, arr) => arr.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));
  const onX = p => W.XS.some(x => Math.abs(p[0] - x) < 1e-6);
  const corner = p => (onX(p) ? [p[0], near(p[1], W.ZS)] : [near(p[0], W.XS), p[1]]);
  function streetPath(p, q) { const a = corner(p), b = corner(q), pts = [p, a, [b[0], a[1]], b, q], out = []; for (const x of pts) if (!out.length || Math.hypot(x[0] - out[out.length - 1][0], x[1] - out[out.length - 1][1]) > 0.01) out.push(x); return out; }
  const hubExit = to => W.hubExits.reduce((a, b) => (Math.hypot(b[0] - to[0], b[1] - to[1]) < Math.hypot(a[0] - to[0], a[1] - to[1]) ? b : a));
  /** from a place to a place — {room: a room id | 'hub' | 'street', at: [x, z]}: out of the door, along the
   *  streets, in at the other door (a newt already on the street goes on from where it is) */
  function route(from, to) {
    if (from.room === to.room && from.room !== 'street') return [to.at];
    const A = W.rooms[from.room], B = W.rooms[to.room];
    const p1 = A ? A.street : from.room === 'hub' ? hubExit(B ? B.street : [0, 0]) : from.at;
    const p2 = B ? B.street : hubExit(p1);
    return [...(A ? [A.door] : []), ...streetPath(p1, p2), ...(B ? [B.door] : []), to.at];
  }

  // ── who should be where, from the snapshot ───────────────────────────────────────────────────────
  const item = M.item, roomOfItem = (s, it) => M.roomOfItem(s, it, W.rooms), labOf = it => M.labOf(it, W.rooms);
  const placeOfRun = (s, r) => M.placeOfRun(s, r, W.rooms);
  function desired(s) {
    const want = new Map(), runs = (s.runs || []).filter(r => ACTIVE.has(r.status) || r.status === 'waiting_input' || r.status === 'queued');
    const used = {};                     // room → the stations and spots already taken this time
    const spot = (roomId, key, prefer, role) => {
      const o = W.rooms[roomId], u = (used[roomId] = used[roomId] || new Set()), cands = [];
      if (prefer && o.st[prefer]) cands.push(['st:' + prefer, o.st[prefer]]);       // the procedure's own station
      if (role && o.spec.roleStation[role]) cands.push(['role:' + role, o.spec.roleStation[role]]);   // the role's
      const off = Math.floor(hash01(key) * o.spots.length);
      o.spots.forEach((_, i) => { const j = (i + off) % o.spots.length; cands.push(['spot' + j, o.spots[j]]); });
      const pick = cands.find(([k]) => !u.has(k)) || cands[cands.length - 1];
      u.add(pick[0]); const a = pick[1], [x, z] = o.toWorld(a[0], a[1]);
      return { room: roomId, at: [x, z], ry: o.ry + (a[2] ?? Math.PI) };
    };
    let queue = 0;
    const deskSlot = () => { const k = queue++, th = Math.PI + (k - 3) * 0.42, x = 2.6 * Math.sin(th), z = -2.6 * Math.cos(th); return { room: 'hub', at: [x, z], ry: Math.atan2(-x, -z) }; };
    for (const r of runs) {
      const hue = Math.floor(hash01(r.run_id) * 12) * 30, roomId = placeOfRun(s, r);
      const main = `run:${r.run_id}`, atDesk = roomId === 'hub' || r.status === 'queued' || r.status === 'waiting_input';
      const stalled = (r.heartbeat_age_s || 0) > 180;
      want.set(main, { key: main, kind: 'main', hue, badge: ROLE_BADGE.orchestrator, scale: 1, target: atDesk ? deskSlot() : spot(roomId, main, r.skill),
        pose: r.status === 'waiting_input' ? 'wait' : atDesk ? 'idle' : stalled ? 'sleep' : 'work', run: r, room: roomId });
      for (const sub of (r.subagents || []).filter(x => !['done', 'finished', 'completed'].includes(x.status))) {
        const k = `sub:${r.run_id}:${sub.id}`, role = sub.type || 'general-purpose';
        want.set(k, { key: k, kind: 'sub', hue, badge: ROLE_BADGE[role] || ROLE_BADGE['general-purpose'], scale: SUB_SCALE, parent: main,
          target: roomId === 'hub' ? deskSlot() : spot(roomId, k, null, role), pose: 'work', run: r, sub });
      }
    }
    // agents the lab traced that no run accounts for (your own sessions, or a demo): by their study's room
    const inRuns = new Set(runs.map(r => r.run_id));
    for (const w of (s.workers || []).filter(x => x.status !== 'done' && !(x.run_id && inRuns.has(x.run_id)))) {
      const it = item(s, w.project || w.idea), roomId = (it && (w.project ? labOf(it) : null)) || (it && roomOfItem(s, it)) || 'hub';
      const k = `w:${w.worker_id}`, sub = !!w.is_subagent, hue = Math.floor(hash01(w.parent || w.worker_id) * 12) * 30;
      want.set(k, { key: k, kind: sub ? 'sub' : 'main', hue, badge: ROLE_BADGE[w.role] || ROLE_BADGE.orchestrator, scale: sub ? SUB_SCALE : 1,
        target: roomId === 'hub' ? deskSlot() : spot(roomId, k, null, w.role), pose: w.status === 'stalled' ? 'sleep' : 'work', worker: w });
    }
    return want;
  }

  // ── actors: newts (or the cast you chose) walking to where they should be ────────────────────────
  // the cast: one character for every agent, or one per tool (Claude, Codex, opencode) so you can tell them apart
  let cast = Object.assign({ mode: 'backend', one: 'newt', claude: 'newt', codex: 'human', opencode: 'robot' }, opts.cast || {});
  const characterOf = spec => {
    const be = (spec.run && spec.run.backend) || (spec.worker && spec.worker.backend) || '';
    return cast.mode === 'one' ? cast.one : (cast[be] || cast.one || 'newt');
  };
  const body = spec => (L.makeCharacter ? L.makeCharacter(K, characterOf(spec), { color: spec.badge, hue: spec.hue, scale: spec.scale * 1.25 })
    : L.makeNewt(K, { color: spec.badge, hue: spec.hue, scale: spec.scale * 1.25 }));
  function makeActor(spec, from) {
    const n = body(spec);
    n.character = characterOf(spec);
    n.group.userData.pick = { kind: 'actor', key: spec.key }; scene.add(n.group); pickables.add(n.group);
    const a = { key: spec.key, spec, n, room: from.room, pos: from.at.slice(), ry: from.ry || 0, path: [], fade: 0, leaving: false };
    return a;
  }
  function sendTo(a, target) {
    a.path = route({ room: a.room, at: a.pos }, target).map(p => p.slice());
    if (a.room !== target.room) a.room = 'street';
    a.dest = target;
  }
  function reconcile(s) {
    const want = desired(s);
    for (const [key, spec] of want) {
      let a = actors.get(key);
      if (!a) {
        const parent = spec.parent && actors.get(spec.parent);
        const from = parent ? { room: parent.room, at: parent.pos.slice() } : { room: 'hub', at: [0, 1.8] };
        a = makeActor(spec, from); actors.set(key, a); sendTo(a, spec.target);
      } else if (a.leaving || !a.dest || a.dest.room !== spec.target.room || Math.hypot(a.dest.at[0] - spec.target.at[0], a.dest.at[1] - spec.target.at[1]) > 0.3) {
        a.leaving = false; sendTo(a, spec.target);
      }
      a.spec = spec;
    }
    for (const [key, a] of actors) if (!want.has(key) && !a.leaving && !a.courier) {
      a.leaving = true;
      if (a.spec.kind === 'sub') a.path = []; else sendTo(a, { room: 'hub', at: [0, 2.2], ry: 0 });
    }
    pinSheets(s);
    // studies: their card on the shelf, at its gate, or carried to its new room
    for (const it of s.items || []) {
      const rid = roomOfItem(s, it); let c = cards.get(it.id);
      if (!c) c = makeCard(it);
      const prev = c.userData.room;
      c.userData.room = rid; c.userData.gate = it.gate && !it.gate_signed ? it.gate : null;
      if (prev && rid && prev !== rid && W.rooms[prev] && W.rooms[rid] && !reduced) carry(it, prev, rid);
    }
    for (const id of [...cards.keys()]) if (!item(s, id)) { scene.remove(cards.get(id)); cards.delete(id); }
  }
  function makeCard(it) {
    const hue = Math.floor(hash01(it.id + 'hue') * 12) * 30;
    const m = new THREE.MeshStandardMaterial({ color: new THREE.Color(`hsl(${hue}, 55%, 60%)`), roughness: 0.6, emissive: new THREE.Color(`hsl(${hue}, 60%, 40%)`), emissiveIntensity: theme === 'night' ? 0.35 : 0 });
    const c = new THREE.Group(); const b = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.09, 0.4), m); b.castShadow = true; c.add(b);
    const lab = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.012, 0.1), K.mat('paper')); lab.position.set(-0.04, 0.05, -0.08); c.add(lab);
    c.userData = { pick: { kind: 'card', id: it.id }, id: it.id }; scene.add(c); pickables.add(c); cards.set(it.id, c);
    return c;
  }
  function carry(it, fromRoom, toRoom) {
    const A = W.rooms[fromRoom], B = W.rooms[toRoom], key = `carry:${it.id}:${Date.now()}`;
    const spec = { key, kind: 'courier', hue: Math.floor(hash01(it.id + 'hue') * 12) * 30, badge: null, scale: 1, pose: 'carry' };
    const a = makeActor(spec, { room: fromRoom, at: A.door.slice() }); a.courier = it.id; actors.set(key, a);
    sendTo(a, { room: toRoom, at: B.door.slice(), ry: B.ry + Math.PI });
    a.path.pop();                         // stop at the door; the card goes onto the shelf
    cards.get(it.id).userData.carrier = key;
  }

  // ── the camera: the whole table, or one room; it keeps clear of the rail and the ask bar ──────────
  const cam = { az: 0, el: 0.92, r: 80, tx: 0, tz: 0 }, camT = { ...cam };
  let insets = { right: 0, bottom: 0, top: 56, k: 0.5 };
  const nbRoom = () => (neighbours.length ? 14 : 0);   // the back edge's other labs need a little more of the view
  function fitCamera(snapNow) {
    if (!W) return;
    const r = canvas.getBoundingClientRect(), aspect = Math.max(0.3, (r.width - insets.right) / Math.max(1, r.height - insets.top - insets.bottom * insets.k)), base = W.SPAN * 3.5 * Math.max(1, 1.4 / aspect, 1.25 * r.height / Math.max(1, r.width - insets.right));   // (narrow screens: fit the width)
    if (view.level === 'ROOM' && W.rooms[view.room]) { const o = W.rooms[view.room]; Object.assign(camT, { tx: o.x, tz: o.z, r: Math.max(o.spec.size[0], 10) * 2.0, az: Math.atan2(o.dir[0], o.dir[1]), el: 0.95 }); }
    else Object.assign(camT, { tx: (W.EXT.x0 + W.EXT.x1) / 2, tz: (W.EXT.z0 - nbRoom() + W.EXT.z1) / 2 + 1, r: base * (1 + nbRoom() / Math.max(10, W.EXT.z1 - W.EXT.z0) * 0.75), el: 0.92, az: camT.az && view.level === 'WORLD' ? camT.az : 0 });
    if (snapNow) Object.assign(cam, camT);
  }
  function measureInsets() {
    const rail = document.querySelector('[data-world-inset="right"]'), bar = document.querySelector('.home-bottom');
    const rr = rail ? rail.getBoundingClientRect() : null;   // (a fixed element has no offsetParent: measure it)
    const sheet = rr && rr.width > innerWidth * 0.6;          // on a phone the rail is a sheet along the bottom
    insets = sheet ? { right: 0, bottom: Math.min(innerHeight * 0.55, innerHeight - rr.top), top: 100, k: 1, cut: rr.top - 8 }
      : { right: rr && rr.width ? rr.width + 24 : 0, bottom: bar ? 90 : 0, top: 56, k: 0.5, cut: innerHeight - (bar ? 90 : 0) };
  }
  function setViewState(level, room) {
    view = { level, room: room || null, label: room && W && W.rooms[room] ? W.rooms[room].title : '' };
    fitCamera(false); if (onView) onView({ level: level === 'ROOM' ? 'REGION' : 'WORLD', room, label: view.label });
  }

  // ── input: drag to turn, wheel to zoom, hover to read, click to open ──────────────────────────────
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let drag = null, hovered = null;
  function pickAt(x, y) {
    const r = canvas.getBoundingClientRect(); mouse.set((x - r.left) / r.width * 2 - 1, -((y - r.top) / r.height) * 2 + 1); ray.setFromCamera(mouse, camera);
    const hits = ray.intersectObjects([...pickables].filter(p => p.visible !== false), true);
    for (const h of hits) { let o = h.object; while (o && !o.userData.pick) o = o.parent; if (o) return o.userData.pick; }
    return null;
  }
  const blocked = e => e.target !== canvas;
  addEventListener('pointerdown', e => { if (blocked(e) || e.button !== 0) return; drag = { x: e.clientX, y: e.clientY, az: camT.az, el: camT.el, moved: false }; });
  addEventListener('pointerup', e => { if (drag && !drag.moved && !blocked(e)) click(pickAt(e.clientX, e.clientY)); drag = null; });
  addEventListener('pointermove', e => {
    if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true; camT.az = drag.az - dx * 0.006; camT.el = clamp(drag.el + dy * 0.004, 0.35, 1.35); }
    if (blocked(e)) { tip.style.display = 'none'; canvas.style.cursor = ''; hovered = null; return; }
    hovered = pickAt(e.clientX, e.clientY); canvas.style.cursor = hovered ? 'pointer' : '';
    const html = hovered && describe(hovered);
    if (!html) { tip.style.display = 'none'; return; }
    tip.innerHTML = html; tip.style.display = 'block'; tip.style.left = Math.min(innerWidth - 330, e.clientX + 16) + 'px'; tip.style.top = (e.clientY + 14) + 'px';
  });
  canvas.addEventListener('wheel', e => { e.preventDefault(); if (!W) return; camT.r = clamp(camT.r * (1 + Math.sign(e.deltaY) * 0.1), 9, W.SPAN * 4); }, { passive: false });
  function click(p) {
    if (!p) return;
    if (p.kind === 'room') { if (view.level === 'ROOM' && view.room === p.id) return; setViewState('ROOM', p.id); return; }
    if (p.kind === 'card' && onItem) return onItem(p.id);
    if (p.kind === 'hub' && onInbox) return onInbox();
    if (p.kind === 'newt' && onNewt) return onNewt();
    if (p.kind === 'otherlab' && onLab) return onLab(p.key);
    if (p.kind === 'artifact' && onArtifact) return onArtifact(p.id);
    if (p.kind === 'gate' && onItem) { const it = ((snap && snap.items) || []).find(i => i.gate === p.gate && !i.gate_signed); if (it) return onItem(it.id); }
    if (p.kind === 'actor') {
      const a = actors.get(p.key); if (!a) return;
      if (a.spec.run && onRun) return onRun(a.spec.run.run_id, a.spec.sub ? a.spec.sub.id : null);
      if (a.spec.worker && onWorker) return onWorker(a.spec.worker.worker_id);
      if (a.courier && onItem) return onItem(a.courier);
    }
  }
  function doing(spec) {
    const r = spec.run;
    if (spec.sub) return spec.sub.last_action || spec.sub.description || spec.sub.type;
    if (r) { if (r.status === 'waiting_input') return '? ' + ((r.pending_question && (r.pending_question.question || r.pending_question.text)) || 'a question for you'); if (r.status === 'queued') return 'queued — starts when a slot frees'; return (r.last_action && r.last_action.summary) || r.label || r.command || r.skill; }
    if (spec.worker) { const w = spec.worker; return (w.in_tool && (w.in_tool.summary || w.in_tool.tool)) || ((w.recent_actions || []).slice(-1)[0] || {}).text || w.role; }
    return '';
  }
  function describe(p) {
    const s = snap || {};
    if (p.kind === 'artifact') { const a = ((snap && snap.artifacts) || []).find(x => x.id === p.id); return a ? `<b>${esc(a.title)}</b><small>${a.question ? 'asks you: ' + esc(a.question) : 'made for you to look at'} — click to read</small>` : null; }
    if (p.kind === 'otherlab') { const nb = neighbours.find(n => n.key === p.key); return nb ? `<b>${esc(nb.name)}</b><small>${esc(nb.machine || '')} — click to go to this lab</small>` : null; }
    if (p.kind === 'actor') {
      const a = actors.get(p.key); if (!a) return null;
      if (a.courier) { const it = item(s, a.courier); return `<b>Carrying “${esc(it ? it.title || it.id : a.courier)}”</b><small>to its next room</small>`; }
      const sp = a.spec, r = sp.run, who = sp.sub ? `${esc(sp.sub.type || 'subagent')} · a subagent` : r ? `${esc((window.NL && NL.procTitle) ? NL.procTitle(r.skill || 'ask') : r.skill)}` : esc((sp.worker || {}).role || 'agent');
      const on = r && (r.subject || (r.target !== 'hub' ? r.target : '')); const it = on && item(s, on);
      const tok = r && r.usage && r.usage.cost_usd != null ? ` · $${(+r.usage.cost_usd).toFixed(2)}` : '';
      return `<b>${who}</b><small>${it ? 'on “' + esc(it.title || it.id) + '” — ' : ''}${esc(doing(sp))}</small>${r ? `<small>${esc(r.backend || '')}${r.model_used ? ' · ' + esc(r.model_used) : ''}${tok}</small>` : ''}`;
    }
    if (p.kind === 'card') { const it = item(s, p.id); return it ? `<b>${esc(it.title || it.id)}</b><small>${esc((window.NL && NL.STATE_LABEL && NL.STATE_LABEL[it.state]) || it.state)}${it.gate && !it.gate_signed ? ` · waiting at Gate ${it.gate} for your signature` : ''}${it.project_type ? ' · ' + esc(it.project_type) + ' project' : ''}</small>` : null; }
    if (p.kind === 'room') { const o = W.rooms[p.id]; if (!o) return null; const n = [...actors.values()].filter(a => a.room === p.id && !a.leaving).length; return `<b>${esc(o.title)}</b><small>${o.kicker ? esc(o.kicker) + ' · ' : ''}${n} agent${n === 1 ? '' : 's'} here${o.building ? ' · being built' : ''}</small>`; }
    if (p.kind === 'hub') { const n = needs(s).length; return `<b>Your desk</b><small>${n ? n + ' waiting for you' : 'nothing waiting for you'}</small>`; }
    if (p.kind === 'newt') return '<b>Newt</b><small>click to start something</small>';
    if (p.kind === 'gate') { const g = W.gates[p.gate]; return g ? `<b>${esc(g.g.title)}</b><small>${esc(g.g.means || '')}</small>` : null; }
    return null;
  }
  const needs = s => ((s && s.attention) || []).filter(a => a.sev !== 'info');

  // ── lenses and labels ─────────────────────────────────────────────────────────────────────────────
  const tmpV = new THREE.Vector3();
  function toScreen(x, y, z) { tmpV.set(x, y, z).project(camera); const r = canvas.getBoundingClientRect(); return [(tmpV.x + 1) / 2 * r.width + r.left, (1 - tmpV.y) / 2 * r.height + r.top, tmpV.z < 1]; }
  const runCost = r => (r.usage && +r.usage.cost_usd) || 0;
  function roomStats(s) {
    const st = {}, now = Date.parse(s.now) || Date.now();
    for (const o of Object.values(W.rooms)) st[o.id] = { cost: 0, risk: 0, asks: 0, n: 0 };
    for (const r of (s.runs || [])) {
      const rid = placeOfRun(s, r); if (!st[rid]) continue;
      if (now - Date.parse(r.created || r.started || 0) < 86400e3) st[rid].cost += runCost(r);   // (today by the lab's clock)
      if ((r.denials || 0) > 0 || ['failed', 'timeout', 'killed'].includes(r.status) || (ACTIVE.has(r.status) && (r.heartbeat_age_s || 0) > 180)) st[rid].risk += 1;
    }
    for (const a of actors.values()) if (!a.leaving && st[a.room]) { st[a.room].n += 1; if (a.spec.pose === 'wait') st[a.room].asks += 1; }
    for (const it of (s.items || [])) if (it.gate && !it.gate_signed) { const rid = roomOfItem(s, it); if (st[rid]) st[rid].gate = it.gate; }
    return st;
  }
  function overlays() {
    if (!W || !snap) return;
    const out = [], close = cam.r < 48, stats = roomStats(snap), maxCost = Math.max(0.01, ...Object.values(stats).map(x => x.cost));
    // labels never pile up: the busiest rooms are named first, and a label that would cover one is left out
    const lensBar = document.querySelector('.lenses'), lr = lensBar && lensBar.getBoundingClientRect();   // never under the lens bar
    const placed = lr && lr.width ? [[lr.left - 6, lr.top - 6, lr.right + 6, lr.bottom + 6]] : [], busy = o => { const x = stats[o.id] || {}; return (x.asks || 0) * 100 + (x.n || 0) * 10 + (o.building ? 5 : 0); };
    for (const o of Object.values(W.rooms).sort((a, b) => busy(b) - busy(a))) {
      const [sx, sy, vis] = toScreen(o.x, 1.7, o.z - o.ez / 2 + 0.6); if (!vis) continue;
      const x = stats[o.id] || {};
      const hw = Math.max(56, o.title.length * 5.2, 70), box = [sx - hw, sy - 44, sx + hw, sy + 2];
      const free = sy - 36 > insets.top + 40 && sy < (insets.cut || innerHeight) && !placed.some(q => box[0] < q[2] && q[0] < box[2] && box[1] < q[3] && q[1] < box[3]);
      // a project's lab whose agent is working elsewhere (writing, say) says where, rather than looking idle
      const away = o.study && !x.n ? [...actors.values()].find(a => !a.leaving && a.spec.run && a.spec.run.subject === o.study && a.room !== o.id && W.rooms[a.room]) : null;
      const kick = o.kicker ? esc(o.kicker) + ' · ' : '';
      const line = lens === 'cost' ? `<span class="hot">$${x.cost.toFixed(2)} today</span>`
        : lens === 'risk' ? (x.risk ? `<span class="hot">${x.risk} to look at — failed, blocked or gone quiet</span>` : `<span>${kick}nothing risky</span>`)
        : lens === 'waiting' ? (x.asks || x.gate ? `<span class="hot">${[x.asks ? `${x.asks} asking you` : '', x.gate ? `Gate ${x.gate} to sign` : ''].filter(Boolean).join(' · ')}</span>` : `<span>${kick}nothing for you</span>`)
        : o.building ? '<span class="hot">being built — its project repo is being set up</span>'
        : away ? `<span>${kick}its agent is in ${esc(W.rooms[away.room].title)}</span>`
        : `<span>${kick}${x.n} agent${x.n === 1 ? '' : 's'}${x.asks ? ` · <em class="hot">${x.asks} asking you</em>` : ''}</span>`;
      if (free) { placed.push(box); out.push(`<div class="wl-room" style="left:${sx}px;top:${sy}px"><b>${esc(o.title)}</b>${line}</div>`); }
      // the floor tells the lens
      let tint = null, k = 0;
      if (lens === 'cost') { tint = 0xe0503a; k = Math.min(0.7, x.cost / maxCost * 0.6 + (x.cost ? 0.1 : 0)); }
      else if (lens === 'risk') { tint = 0xe0503a; k = Math.min(0.6, x.risk * 0.2); }
      o.floorMat.color.copy(o.floorBase); if (tint) o.floorMat.color.lerp(new THREE.Color(tint), k); if (lens === 'waiting') o.floorMat.color.multiplyScalar(0.55);
    }
    for (const nb of neighbours.slice(0, 6)) {
      if (!nb._at) continue;
      const [sx, sy, vis] = toScreen(nb._at[0], 2.2, nb._at[1]); if (!vis || sy < insets.top + 30) continue;
      const state = [nb.needs ? `<em class="hot">${nb.needs} need${nb.needs === 1 ? 's' : ''} you</em>` : '', nb.running ? `${nb.running} at work` : '',
        nb.state !== 'here' && nb.state !== 'connected' ? 'not connected' : ''].filter(Boolean).join(' · ');
      const hw = Math.max(nb.name.length * 4.6, (nb.machine || '').length * 3.8, 56), hit = bx => placed.some(q => bx[0] < q[2] && q[0] < bx[2] && bx[1] < q[3] && q[1] < bx[3]);
      let at = [sx, sy], box = [sx - hw, sy - 62, sx + hw, sy];
      if (hit(box)) {            // above its table is taken: try beside it, toward the middle of the view
        const side = sx < innerWidth / 2 ? 1 : -1, [tx, ty] = toScreen(nb._at[0] + side * 7.5, 0.6, nb._at[1]);
        at = [tx, ty]; box = [tx - hw, ty - 62, tx + hw, ty];
        if (hit(box)) continue;
      }
      placed.push(box);
      out.push(`<div class="wl-room wl-nb" style="left:${at[0]}px;top:${at[1]}px"><b>${esc(nb.name)}</b><span>${esc(nb.machine || '')}</span>${state ? `<span>${state}</span>` : ''}<span class="wl-go">click to go there</span></div>`);
    }
    for (const a of actors.values()) {
      if (a.leaving && a.spec.kind === 'sub') continue;
      const h = a.n.group.position, [sx, sy, vis] = toScreen(h.x, 1.75 * a.spec.scale * 1.25 + 0.15, h.z); if (!vis) continue;
      const sp = a.spec, r = sp.run;
      let cls = '', txt = '';
      if (sp.pose === 'wait' && r) { cls = 'ask'; txt = close ? doing(sp) : '?'; }
      else if (sp.pose === 'sleep') { cls = 'zzz'; txt = 'zzz'; }
      else if (lens === 'risk' && r && (r.denials || 0) > 0) { cls = 'bad'; txt = close ? `blocked ${r.denials}×` : '⛨'; }
      else if (lens === 'cost' && r && sp.kind === 'main') { cls = 'cost'; txt = '$' + runCost(r).toFixed(2); }
      else if (lens === 'work' && close && !a.path.length && !a.leaving && !a.courier && (view.level === 'WORLD' || a.room === view.room)) txt = doing(sp);
      if (lens === 'waiting' && cls !== 'ask') continue;
      if (highlightRole && sp.badge !== ROLE_BADGE[highlightRole]) continue;
      if (txt) out.push(`<div class="wl-bub ${cls}${txt.length < 4 ? ' icon' : ''}" style="left:${sx}px;top:${sy}px">${esc(txt)}</div>`);
    }
    if (lens === 'cost') { const total = Object.values(stats).reduce((a, x) => a + x.cost, 0);
      out.push(`<div class="wl-total"><b>$${total.toFixed(2)}</b> spent today across the lab<small>estimated from each run's token use · brighter floor = more spent</small></div>`); }
    overlay.innerHTML = out.join('');
  }

  // ── each frame ────────────────────────────────────────────────────────────────────────────────────
  let last = performance.now(), dirty = true, raf = 0;
  function frame(now, quiet) {     // quiet: move the world on without drawing it (fast-forward)
    if (!quiet) raf = 0;
    const raw = Math.max(0, (now - last) / 1000), dt = Math.min(0.05, raw), dtWalk = Math.min(0.5, raw); last = now;   // walks keep pace on a slow machine
    const t = now / 1000;
    if (W && snap) {
      // actors walk their paths; leavers fade
      for (const [key, a] of actors) {
        let moving = false;
        if (a.path.length) {
          const p = a.path[0], dx = p[0] - a.pos[0], dz = p[1] - a.pos[1], d = Math.hypot(dx, dz), step = WALK * (a.spec.kind === 'sub' ? 1.15 : 1) * dtWalk * (reduced ? 4 : 1);
          if (d <= step) { a.pos = p.slice(); a.path.shift(); if (!a.path.length && a.dest) a.room = a.dest.room; }
          else { a.pos[0] += dx / d * step; a.pos[1] += dz / d * step; a.ry = Math.atan2(dx, dz); moving = true; }
        } else if (a.dest && a.dest.ry != null) { a.ry += (((a.dest.ry - a.ry + Math.PI * 3) % (Math.PI * 2)) - Math.PI) * Math.min(1, dt * 6); }
        const done = !a.path.length;
        if (a.leaving && done) a.fade = Math.min(1, a.fade + dt * 2.5); else if (!a.leaving) a.fade = Math.max(0, a.fade - dt * 4);
        if (a.courier && done) { a.leaving = true; const c = cards.get(a.courier); if (c && c.userData.carrier === key) c.userData.carrier = null; }
        if (a.leaving && a.fade >= 1) { scene.remove(a.n.group); pickables.delete(a.n.group); actors.delete(key); continue; }
        const g = a.n.group, sc = a.spec.scale * 1.25 * (1 - a.fade * 0.9);
        g.position.set(a.pos[0], 0.14, a.pos[1]); g.rotation.y = a.ry; g.scale.setScalar(Math.max(0.01, sc));
        const pz = moving ? (a.courier ? 'carry' : 'walk') : a.spec.pose;
        if (ambient || moving) a.n.update(t, { pose: pz, moving });
      }
      // cards: carried, at a gate, or on their room's shelf
      const shelfN = {};
      for (const [id, c] of cards) {
        const carrier = c.userData.carrier && actors.get(c.userData.carrier);
        if (carrier) { c.position.set(carrier.pos[0], 1.85 * 1.25 + 0.25, carrier.pos[1]); c.rotation.y = carrier.ry; c.visible = true; continue; }
        const o = W.rooms[c.userData.room]; if (!o) { c.visible = false; continue; }
        const g = c.userData.gate && W.gates[c.userData.gate];
        if (g && g.host === o) { const k = (shelfN['gate' + c.userData.gate] = (shelfN['gate' + c.userData.gate] || 0) + 1) - 1; c.position.set(g.pos[0], 0.3 + k * 0.1, g.pos[1]); c.rotation.y = t * 0.6; c.visible = true; continue; }
        const i = (shelfN[o.id] = (shelfN[o.id] || 0) + 1) - 1, perRow = Math.max(1, Math.floor(Math.min(3.4, o.spec.size[0] * 0.4) / 0.62));
        const [x, z] = o.toWorld(o.shelfAt[0] + 0.34 + (i % perRow) * 0.62, o.shelfAt[1]);
        c.position.set(x, 0.62 + Math.floor(i / perRow) * 0.1, z); c.rotation.y = o.ry; c.visible = true;
      }
      // the desk: one envelope per thing waiting; Newt poses by the lab's mood; gates glow when someone waits
      const n = needs(snap).length;
      while (W.inbox.children.length < n) W.inbox.add(K.box(0.4, 0.035, 0.28, 'amber', 0, W.inbox.children.length * 0.045, 0, { glow: 'amber', gi: 0.4 }));
      W.inbox.children.forEach((e, i) => { e.visible = i < n; });
      W.bigNewt.update(t, { pose: pose === 'gate' || n ? 'wait' : pose === 'sleep' ? 'sleep' : pose === 'failure' ? 'fail' : pose === 'running' ? 'work' : 'idle' });
      const waitingGates = new Set(((snap.items) || []).filter(i => i.gate && !i.gate_signed).map(i => i.gate));
      for (const g of Object.values(W.gates)) g.lamp.material.emissiveIntensity = waitingGates.has(g.g.n) ? 1.6 + Math.sin(t * 6) * 0.6 : 0.15;
      // the camera: follow, ease, keep clear of the rail
      if (followKey) { const a = actors.get(followKey); if (a) { camT.tx = a.pos[0]; camT.tz = a.pos[1]; } else { followKey = null; if (onFollow) onFollow(null); } }
      const k = 1 - Math.pow(0.002, dt);
      for (const key of ['az', 'el', 'r', 'tx', 'tz']) cam[key] += (camT[key] - cam[key]) * k;
      camera.position.set(cam.tx + cam.r * Math.cos(cam.el) * Math.sin(cam.az), cam.r * Math.sin(cam.el), cam.tz + cam.r * Math.cos(cam.el) * Math.cos(cam.az));
      camera.lookAt(cam.tx, 0.6, cam.tz);
      for (const o of Object.values(W.rooms)) if (o.rising) { o.g.scale.y += (1 - o.g.scale.y) * Math.min(1, dt * 1.6); if (o.g.scale.y > 0.995) { o.g.scale.y = 1; o.rising = false; } }
      // walls duck when they stand between you and their room
      for (const o of Object.values(W.rooms)) for (const wl of o.walls) {
        const [wx, wz] = o.toWorld(wl.lx, wl.lz), nn = [wl.n[0] * Math.cos(o.ry) + wl.n[1] * Math.sin(o.ry), -wl.n[0] * Math.sin(o.ry) + wl.n[1] * Math.cos(o.ry)];
        const target = nn[0] * (camera.position.x - wx) + nn[1] * (camera.position.z - wz) > 0 ? 0.12 : 1;
        wl.wall.scale.y += (target - wl.wall.scale.y) * k * 1.5; wl.wall.position.y = 0.14 + wl.h / 2 * wl.wall.scale.y; wl.cap.position.y = 0.14 + wl.h * wl.wall.scale.y + 0.03;
      }
      if (quiet) return;
      renderer.render(scene, camera);
      overlays();
    }
    if (!document.hidden) raf = requestAnimationFrame(frame);
  }
  const kick = () => { if (!raf) raf = requestAnimationFrame(frame); };
  document.addEventListener('visibilitychange', kick);
  function resize() {
    const r = canvas.getBoundingClientRect(), w = Math.max(1, r.width), h = Math.max(1, r.height);
    renderer.setSize(w, h, false); camera.aspect = w / h;
    measureInsets();
    camera.setViewOffset(w, h, insets.right / 2, (insets.bottom - insets.top) / 2 * insets.k, w, h);
    camera.updateProjectionMatrix(); fitCamera(false); kick();
  }
  addEventListener('resize', resize);

  return {
    kind: '3d',
    _debug: () => ({ W, actors, cards, snap, view, lens, click, pickAt, toScreen, step(sec, fps) { const f = fps || 20; for (let i = 0; i < sec * f; i++) frame(last + 1000 / f, true); } }),
    async boot() { resize(); kick(); },
    async sync(s) {
      snap = s;
      await loadLooks(String((s && s.rooms3d_sig) || '') + '|' + (s && s.workflow ? JSON.stringify((s.workflow.rooms || []).map(r => r.id)) : ''));
      const rebuilt = buildStatic(s);
      reconcile(s);
      if ((!settled || rebuilt) && /[?&]settle\b/.test(location.search)) { settled = true; for (let i = 0; i < 900; i++) frame(last + 50, true); }   // screenshots: everyone in place (again after a rebuild: walks start over)
      kick();
    },
    setPose(p) { pose = p; },
    setLamp(m) { const next = m === 'day' ? 'day' : 'night'; if (next === theme) return; theme = next; staticSig = ''; if (snap) { buildStatic(snap); reconcile(snap); } kick(); },
    setView(m) { if (m === 'WORLD') setViewState('WORLD'); },
    goRoom(k) { if (W && W.rooms[k]) setViewState('ROOM', k); },
    focusProject(id) { if (!W) return; const it = item(snap, id), rid = (it && (labOf(it) || roomOfItem(snap, it))) || null; if (rid) setViewState('ROOM', rid); },
    back() { setViewState('WORLD'); },
    viewInfo() { return { level: view.level === 'ROOM' ? 'REGION' : 'WORLD', label: view.label }; },
    highlight(role) { highlightRole = role || null; kick(); },
    roomRect() { return null; }, band() { return null; },
    followWorker(id) { const key = [...actors.keys()].find(k => k.endsWith(':' + id) || k === 'run:' + id || k === 'w:' + id); if (key) { followKey = key; camT.r = 22; if (onFollow) onFollow(id); } },
    stopFollow() { followKey = null; if (onFollow) onFollow(null); }, following() { return followKey; },
    layout() {                         // the plan of the table, for the minimap
      if (!W) return null;
      const boxes = Object.values(W.rooms).map((o, i) => ({ key: o.id, x: o.x - o.ex / 2, y: o.z - o.ez / 2, w: o.ex, h: o.ez, label: o.title, n: i + 1 }));
      return { boxes, bbox: { x: W.EXT.x0, y: W.EXT.z0, w: W.EXT.x1 - W.EXT.x0, h: W.EXT.z1 - W.EXT.z0 }, room: view.room, level: view.level };
    },
    setAmbient(on) { ambient = !!on; kick(); },
    setLens(l) { lens = ['work', 'cost', 'waiting', 'risk'].includes(l) ? l : 'work'; kick(); }, lens() { return lens; },
    /** your other labs: [{key, name, machine, needs, running, state}] — drawn as small tables past the back edge */
    setNeighbours(list) { const had = neighbours.length; neighbours = (list || []).map(n => ({ ...n })); nbSig = ''; buildNeighbours(); if (!had !== !neighbours.length && view.level === 'WORLD') fitCamera(false); kick(); },
    onLab(cb) { onLab = cb; }, onArtifact(cb) { onArtifact = cb; },
    /** who plays the agents: {mode: 'one'|'backend', one, claude, codex, opencode} — swapped in place, mid-stride */
    setCast(c) {
      cast = Object.assign({}, cast, c || {});
      for (const a of actors.values()) {
        if (a.n.character === characterOf(a.spec)) continue;
        const old = a.n.group, n = body(a.spec);
        n.character = characterOf(a.spec);
        n.group.position.copy(old.position); n.group.rotation.copy(old.rotation); n.group.scale.copy(old.scale);
        n.group.userData.pick = old.userData.pick;
        scene.remove(old); pickables.delete(old); scene.add(n.group); pickables.add(n.group); a.n = n;
      }
      kick();
    },
    insetsChanged() { resize(); },
    onClick(item, inbox) { onItem = item; onInbox = inbox; }, onWorker(cb) { onWorker = cb; }, onRun(cb) { onRun = cb; }, onNewt(cb) { onNewt = cb; },
    onView(cb) { onView = cb; }, onFollow(cb) { onFollow = cb; },
  };
};
})();
