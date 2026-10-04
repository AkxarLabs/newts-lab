/* Lab3D — the cast: other little characters an agent can be drawn as, besides the newt. Each one is a soft,
 * toy-like figure built from primitives with the same interface as Lab3D.makeNewt (world3d/newt.js):
 *
 *   Lab3D.CHARACTERS                       — [{ id, label, blurb }] in display order
 *   const c = Lab3D.makeCharacter(K, 'human', { color: '#5ccfbc', hue: 40, scale: 1 });
 *     color: the role badge on its chest · hue: turns its FAMILY colour round the wheel (a main agent and its
 *     subagents share it: the scientist's scarf, the frog's spots and toes, the owl's tufts and wing tips, the
 *     fox's scarf, the robot's antenna and chest light) · scale: its size. An unknown id gives the newt.
 *   c.group                       — add it to the scene (stands on y = 0, faces +z)
 *   c.update(t, { pose, moving }) — pose: idle | work | walk | wait | sleep | fail | carry
 *   c.head                        — the head's group
 *
 * Loaded after kit.js and newt.js. At night the family colour glows a little, as the newt's gills do.
 */
(function () {
  'use strict';
  const L = (window.Lab3D = window.Lab3D || {});

  L.CHARACTERS = [
    { id: 'newt', label: 'Newt', blurb: "the lab's axolotl: gills and a curled tail" },
    { id: 'human', label: 'Scientist', blurb: 'a mini human in a lab coat, glasses and a scarf' },
    { id: 'frog', label: 'Frog', blurb: 'a round frog with spotted back and bright toes' },
    { id: 'owl', label: 'Owl', blurb: 'a wise little owl with tufted ears' },
    { id: 'fox', label: 'Fox', blurb: 'a fox with a bushy tail and a scarf' },
    { id: 'robot', label: 'Robot', blurb: 'a boxy toy robot with an antenna light' },
  ];

  // the family colour at hue 0 (the newt's pink), turned like the newt's gills
  const FAM = '#f58cc4';
  const turn = (THREE, c, deg) => (deg ? '#' + new THREE.Color(c).offsetHSL(deg / 360, 0, 0).getHexString() : c);

  // geometries are shared by every instance (they don't depend on the theme)
  const GEO = new Map();
  const geo = (key, make) => { let g = GEO.get(key); if (!g) { g = make(); GEO.set(key, g); } return g; };

  /** the per-character toolbox: shared geometry, materials, a mesh-adder */
  function tools(K, o) {
    const { THREE } = K, fam = turn(THREE, FAM, o.hue || 0);
    const T = {
      THREE, fam,
      sph: (r, w, h) => geo(`s${r}|${w || 14}|${h || 10}`, () => new THREE.SphereGeometry(r, w || 14, h || 10)),
      cap: (r, l) => geo(`c${r}|${l}`, () => new THREE.CapsuleGeometry(r, l, 4, 8)),
      cone: (r, h, s) => geo(`k${r}|${h}|${s || 8}`, () => new THREE.ConeGeometry(r, h, s || 8)),
      cyl: (rt, rb, h, s) => geo(`y${rt}|${rb}|${h}|${s || 12}`, () => new THREE.CylinderGeometry(rt, rb, h, s || 12)),
      box: (w, h, d) => geo(`b${w}|${h}|${d}`, () => new THREE.BoxGeometry(w, h, d)),
      torus: (r, t, arc) => geo(`t${r}|${t}|${arc || 0}`, () => new THREE.TorusGeometry(r, t, 6, 16, arc || Math.PI * 2)),
      lathe: (name, prof) => geo('l' + name, () => new THREE.LatheGeometry(prof.map(([r, y]) => new THREE.Vector2(r, y)), 18)),
      mat: (c, extra) => K.mat(c, Object.assign({ smooth: true, rough: 0.7 }, extra)),
      // the family colour: soft by day, glowing a little at night (like the newt's gills)
      famMat: (gid, gn) => K.mat(fam, { smooth: true, rough: 0.6, glow: fam, gi: K.night ? (gn ?? 0.55) : (gid ?? 0.12) }),
      dark: K.mat('#151517', { smooth: true, rough: 0.3 }),
      hl: K.mat('#ffffff', { smooth: true, glow: '#ffffff', gi: 0.6 }),
      blush: K.mat('#f4a3a8', { smooth: true, rough: 0.9 }),
      /** add a mesh to parent; returns it */
      add(parent, g, m, x, y, z, sx, sy, sz) {
        const me = K.mesh(g, m, x, y, z);
        if (sx != null) me.scale.set(sx, sy ?? sx, sz ?? sx);
        parent.add(me); return me;
      },
      /** the role badge on the chest, like the newt's */
      badge(parent, x, y, z) {
        if (!o.color) return null;
        const b = K.mesh(T.sph(0.045, 14, 10), K.mat(o.color, { glow: o.color, gi: K.night ? 0.9 : 0.25, smooth: true }), x, y, z);
        b.scale.z = 0.5; parent.add(b); return b;
      },
      /** a pair of dark bead eyes with a highlight each */
      eyes(parent, dx, y, z, r) {
        return [-1, 1].map(s => {
          const e = T.add(parent, T.sph(r, 12, 10), T.dark, s * dx, y, z);
          T.add(e, T.sph(r * 0.28, 6, 6), T.hl, r * 0.3, r * 0.35, r * 0.85);
          return e;
        });
      },
      /** an arm: a group pivoting at the shoulder, the limb hanging down (-y) */
      arm(parent, s, x, y, z) { const a = new THREE.Group(); a.position.set(s * x, y, z); parent.add(a); return a; },
    };
    return T;
  }

  /** the shared animation: the newt's poses, for any rig {body, head, legs, arms, eyes, legY, armRest, extra} */
  function animator(R) {
    const phase = Math.random() * 10, rest = R.armRest ?? -0.55, spread = R.armSpread ?? 0.18, legY = R.legY;
    R.eyes.forEach(e => { e.userData.sy = e.scale.y; });
    return function update(t, s) {
      const pose = (s && s.pose) || 'idle', moving = s && s.moving, tt = t + phase;
      let bob = Math.sin(tt * 2) * 0.008, lean = 0, headTilt = 0, headTurn = 0, armL = rest, armR = rest, raise = [0, 0];
      let blink = Math.sin(tt * 0.7) > 0.985;
      R.legs.forEach(l => { l.position.y = legY; l.rotation.x = 0; });
      if (moving || pose === 'walk' || pose === 'carry') {
        const w = Math.sin(tt * 9); bob = Math.abs(w) * 0.04; R.legs[0].rotation.x = w * 0.5; R.legs[1].rotation.x = -w * 0.5; lean = 0.08;
        armL = rest + w * 0.35; armR = rest - w * 0.35;
      }
      if (pose === 'idle') { headTurn = Math.sin(tt * 0.45) * 0.35 * Math.max(0, Math.sin(tt * 0.21)); }
      if (pose === 'work') { lean = 0.12; armL = -1.1 + Math.max(0, Math.sin(tt * 11)) * 0.28; armR = -1.1 + Math.max(0, Math.sin(tt * 11 + 2)) * 0.28; headTilt = 0.14 + Math.sin(tt * 1.3) * 0.05; }
      if (pose === 'wait') { armR = -0.15; raise = [0, 2.55 + Math.sin(tt * 6) * 0.3]; bob = Math.abs(Math.sin(tt * 3)) * 0.035; headTilt = -0.15; headTurn = 0.12; }
      if (pose === 'carry') { armL = armR = -0.3; raise = [2.35, 2.35]; }
      if (pose === 'sleep') { headTilt = 0.38; blink = true; bob = Math.sin(tt * 1.1) * 0.014 - 0.01; armL = armR = -0.15; }
      if (pose === 'fail') { headTilt = 0.5; lean = 0.2; armL = armR = -0.05; bob = -0.02; headTurn = Math.sin(tt * 0.5) * 0.08; }
      R.body.position.y = bob; R.body.rotation.x = lean;
      R.head.rotation.x = headTilt; R.head.rotation.y = headTurn; R.head.rotation.z = pose === 'idle' ? Math.sin(tt * 0.6) * 0.06 : pose === 'wait' ? 0.1 : 0;
      R.arms[0].rotation.x = armL; R.arms[1].rotation.x = armR;
      R.arms[0].rotation.z = -spread - raise[0]; R.arms[1].rotation.z = spread + raise[1];
      R.eyes.forEach(e => { e.scale.y = blink ? e.userData.sy * 0.15 : e.userData.sy; });
      if (R.extra) R.extra(tt, pose, moving);
    };
  }

  /** wrap up: shadows, scale, first frame */
  function finish(root, o, R) {
    root.traverse(m => { if (m.isMesh) m.castShadow = true; });
    if (o.scale) root.scale.setScalar(o.scale);
    const update = animator(R); update(0, {});
    return { group: root, update, head: R.head };
  }

  function legsPair(T, body, g, m, dx, y) {
    return [-1, 1].map(s => T.add(body, g, m, s * dx, y, 0.02));
  }

  // ── the mini human: a little scientist in a lab coat, round glasses and a scarf in the family colour ──
  function human(K, o) {
    const T = tools(K, o), { THREE } = T, root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group();
    root.add(body);
    const skin = T.mat('#f2c6a2'), coat = T.mat('white', { rough: 0.8 }), trousers = T.mat('#3d4a63'), shoe = T.mat('#5a3a2a'), hairM = T.mat('#5b3b26', { rough: 0.9 }), fam = T.famMat();
    // legs in trousers, with round shoes
    const legs = legsPair(T, body, T.cap(0.055, 0.1), trousers, 0.085, 0.11);
    legs.forEach(l => T.add(l, T.sph(0.066, 12, 8), shoe, 0, -0.085, 0.035, 1, 0.55, 1.45));
    // the lab coat: a flared lathe, two buttons
    T.add(body, T.lathe('coat', [[0.001, 0.1], [0.19, 0.1], [0.205, 0.18], [0.185, 0.38], [0.16, 0.55], [0.12, 0.67], [0.001, 0.72]]), coat);
    [0.3, 0.2].forEach(y => T.add(body, T.sph(0.014, 6, 6), T.mat('#9aa7ad'), 0.0, y, 0.195));
    // the scarf: a ring round the neck and one end hanging down the front
    const ring = T.add(body, T.torus(0.11, 0.042), fam, 0, 0.665, 0); ring.rotation.x = Math.PI / 2;
    const end = T.add(body, T.box(0.075, 0.2, 0.04), fam, 0.07, 0.54, 0.16); end.rotation.set(-0.2, 0, 0.12);
    // the role badge, clipped on the coat
    T.badge(body, -0.085, 0.43, 0.165);
    // arms: white sleeves, hands
    const arms = [-1, 1].map(s => {
      const a = T.arm(body, s, 0.155, 0.58, 0.05);
      T.add(a, T.cap(0.046, 0.14), coat, 0, -0.08, 0); T.add(a, T.sph(0.048, 10, 8), skin, 0, -0.19, 0);
      return a;
    });
    // the round head: hair cap tilted back, a side fringe and a cowlick
    head.position.set(0, 0.95, 0); body.add(head);
    T.add(head, T.sph(0.22, 20, 14), skin, 0, 0, 0, 1.06, 0.98, 1);
    const cap = T.add(head, geo('hairCap', () => new THREE.SphereGeometry(0.236, 20, 10, 0, Math.PI * 2, 0, Math.PI * 0.56)), hairM, 0, 0.0, -0.005, 1.07, 1, 1.06);
    cap.rotation.x = -0.55;
    const fringe = T.add(head, T.sph(0.1, 12, 8), hairM, -0.06, 0.15, 0.145, 1.5, 0.5, 0.8); fringe.rotation.set(0.5, 0, 0.3);
    const lick = T.add(head, T.cone(0.035, 0.12, 6), hairM, 0.03, 0.25, -0.02); lick.rotation.set(-0.3, 0, -0.5);
    [-1, 1].forEach(s => T.add(head, T.sph(0.045, 8, 6), skin, s * 0.23, -0.01, 0, 0.6, 1, 1));   // ears
    const eyes = T.eyes(head, 0.078, 0.0, 0.2, 0.03);
    // round glasses
    const rim = T.mat('#2d2a26', { rough: 0.4 });
    [-1, 1].forEach(s => T.add(head, T.torus(0.052, 0.009), rim, s * 0.078, 0.0, 0.222));
    T.add(head, T.box(0.05, 0.01, 0.01), rim, 0, 0.012, 0.228);
    [-1, 1].forEach(s => T.add(head, T.sph(0.035, 8, 6), T.blush, s * 0.135, -0.075, 0.165, 1, 0.6, 0.4));   // rosy cheeks
    const smile = T.add(head, T.torus(0.035, 0.007, Math.PI), T.dark, 0, -0.085, 0.205); smile.rotation.z = Math.PI;
    return finish(root, o, { body, head, legs, arms, eyes, legY: 0.11 });
  }

  // ── the frog: squat and round, big eyes on top, family-coloured spots and toes ──
  function frog(K, o) {
    const T = tools(K, o), { THREE } = T, root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group();
    root.add(body);
    const green = T.mat('#86c46c'), belly = T.mat('#eef2cf'), fam = T.famMat();
    const legs = legsPair(T, body, T.cap(0.07, 0.06), green, 0.12, 0.1);
    legs.forEach(l => T.add(l, T.sph(0.075, 12, 8), fam, 0, -0.085, 0.06, 1.15, 0.35, 1.45));
    T.add(body, T.lathe('frog', [[0.001, 0.07], [0.17, 0.09], [0.235, 0.2], [0.235, 0.34], [0.2, 0.48], [0.15, 0.6], [0.001, 0.66]]), green);
    T.add(body, T.sph(0.17, 14, 10), belly, 0, 0.32, 0.12, 1, 1.15, 0.6);
    T.badge(body, 0, 0.42, 0.215);
    // spots on the back
    [[0.09, 0.48, -0.16], [-0.1, 0.34, -0.2], [0.11, 0.25, -0.2], [-0.19, 0.28, 0.06], [0.2, 0.36, 0.0]].forEach(([x, y, z]) => T.add(body, T.sph(0.06, 10, 8), fam, x, y, z, 1, 1, 0.45));
    const arms = [-1, 1].map(s => {
      const a = T.arm(body, s, 0.19, 0.5, 0.07);
      T.add(a, T.cap(0.045, 0.12), green, 0, -0.08, 0); T.add(a, T.sph(0.05, 10, 8), fam, 0, -0.18, 0.01, 1, 0.7, 1);
      return a;
    });
    // the wide head with eyes bulging on top
    head.position.set(0, 0.84, 0); body.add(head);
    T.add(head, T.sph(0.27, 20, 14), green, 0, 0, 0, 1.2, 0.78, 1);
    [[-0.02, 0.2, -0.04], [0.15, 0.17, -0.1], [-0.16, 0.16, -0.12]].forEach(([x, y, z]) => T.add(head, T.sph(0.06, 10, 8), fam, x, y, z, 1, 0.4, 1));   // spots on top
    const eyes = [-1, 1].map(s => {
      const bulb = T.add(head, T.sph(0.1, 14, 10), green, s * 0.16, 0.15, 0.06);
      const e = T.add(bulb, T.sph(0.058, 12, 10), T.dark, 0, 0.015, 0.06);
      T.add(e, T.sph(0.016, 6, 6), T.hl, 0.018, 0.02, 0.05);
      return e;
    });
    const smile = T.add(head, T.torus(0.12, 0.008, Math.PI), T.dark, 0, -0.005, 0.252, 1, 0.35, 1); smile.rotation.z = Math.PI;
    [-1, 1].forEach(s => T.add(head, T.sph(0.04, 8, 6), T.blush, s * 0.2, -0.04, 0.19, 1, 0.6, 0.4));
    return finish(root, o, { body, head, legs, arms, eyes, legY: 0.1 });
  }

  // ── the owl: an egg of brown feathers, a pale face, amber eyes, family-coloured tufts and wing tips ──
  function owl(K, o) {
    const T = tools(K, o), { THREE } = T, root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group();
    root.add(body);
    const brown = T.mat('#a97f5a', { rough: 0.85 }), wingM = T.mat('#8a6446', { rough: 0.85 }), pale = T.mat('#efdfc4'), amber = T.mat('#f0b24a'), fam = T.famMat();
    const legs = legsPair(T, body, T.cap(0.035, 0.06), amber, 0.09, 0.075);
    legs.forEach(l => T.add(l, T.sph(0.06, 10, 8), amber, 0, -0.055, 0.04, 1.1, 0.4, 1.3));
    T.add(body, T.lathe('owl', [[0.001, 0.09], [0.17, 0.1], [0.24, 0.22], [0.25, 0.38], [0.225, 0.55], [0.17, 0.68], [0.001, 0.74]]), brown);
    T.add(body, T.sph(0.18, 14, 10), pale, 0, 0.36, 0.14, 1, 1.3, 0.55);
    T.badge(body, 0, 0.44, 0.235);
    // wings (the arms), their tips in the family colour
    const arms = [-1, 1].map(s => {
      const a = T.arm(body, s, 0.215, 0.6, 0.0);
      T.add(a, T.sph(0.17, 12, 10), wingM, 0, -0.15, 0, 0.32, 1, 0.62);
      T.add(a, T.sph(0.1, 10, 8), fam, 0, -0.27, -0.01, 0.36, 0.85, 0.6);
      return a;
    });
    head.position.set(0, 0.95, 0); body.add(head);
    T.add(head, T.sph(0.25, 20, 14), brown, 0, 0, 0, 1.15, 0.95, 1);
    [-1, 1].forEach(s => T.add(head, T.sph(0.115, 14, 10), pale, s * 0.095, -0.005, 0.185, 1, 1, 0.38));   // the facial disc
    const eyes = [-1, 1].map(s => {
      const e = T.add(head, T.sph(0.062, 12, 10), amber, s * 0.095, 0.0, 0.215);
      const p = T.add(e, T.sph(0.036, 10, 8), T.dark, 0, 0, 0.038);
      T.add(p, T.sph(0.012, 6, 6), T.hl, 0.012, 0.014, 0.03);
      return e;
    });
    const beak = T.add(head, T.cone(0.032, 0.09, 6), amber, 0, -0.075, 0.245); beak.rotation.x = Math.PI - 0.35;
    const tufts = [-1, 1].map(s => { const tf = T.add(head, T.cone(0.065, 0.17, 6), fam, s * 0.17, 0.2, -0.02); tf.rotation.z = -s * 0.55; return tf; });
    return finish(root, o, { body, head, legs, arms, eyes, legY: 0.075, armRest: -0.12, armSpread: 0.12,
      extra(tt, pose) { tufts.forEach((tf, i) => { tf.rotation.z = (i ? -1 : 1) * (0.55 + (pose === 'wait' ? Math.sin(tt * 6) * 0.12 : Math.sin(tt * 1.7) * 0.04)); }); } });
  }

  // ── the fox: orange with a cream chest and muzzle, pointed ears, a bushy tail and a family scarf ──
  function fox(K, o) {
    const T = tools(K, o), { THREE } = T, root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group();
    root.add(body);
    const orange = T.mat('#e48a48'), cream = T.mat('#f7ecdc'), sock = T.mat('#4a3328'), fam = T.famMat();
    const legs = legsPair(T, body, T.cap(0.058, 0.1), sock, 0.1, 0.1);
    T.add(body, T.lathe('fox', [[0.001, 0.07], [0.15, 0.09], [0.2, 0.2], [0.21, 0.34], [0.185, 0.5], [0.145, 0.64], [0.115, 0.72], [0.001, 0.75]]), orange);
    T.add(body, T.sph(0.13, 14, 10), cream, 0, 0.4, 0.14, 1, 1.45, 0.55);
    T.badge(body, 0, 0.36, 0.21);
    const ring = T.add(body, T.torus(0.115, 0.042), fam, 0, 0.69, 0); ring.rotation.x = Math.PI / 2;
    const end = T.add(body, T.box(0.075, 0.18, 0.04), fam, -0.08, 0.57, 0.15); end.rotation.set(-0.25, 0, -0.15);
    const arms = [-1, 1].map(s => {
      const a = T.arm(body, s, 0.15, 0.56, 0.08);
      T.add(a, T.cap(0.043, 0.13), orange, 0, -0.08, 0); T.add(a, T.sph(0.046, 10, 8), sock, 0, -0.17, 0);
      return a;
    });
    head.position.set(0, 0.96, 0); body.add(head);
    T.add(head, T.sph(0.23, 20, 14), orange, 0, 0, 0, 1.15, 0.95, 1);
    [-1, 1].forEach(s => T.add(head, T.sph(0.1, 12, 8), cream, s * 0.12, -0.075, 0.13, 1, 0.75, 0.75));   // white cheeks
    const snout = T.add(head, T.cone(0.085, 0.17, 10), cream, 0, -0.065, 0.24); snout.rotation.x = Math.PI / 2;
    T.add(head, T.sph(0.03, 8, 6), T.dark, 0, -0.065, 0.325);
    const ears = [-1, 1].map(s => {
      const e = T.add(head, T.cone(0.08, 0.21, 6), orange, s * 0.14, 0.2, -0.02); e.rotation.z = -s * 0.35;
      T.add(e, T.cone(0.034, 0.085, 6), sock, 0, 0.064, 0);
      return e;
    });
    const eyes = T.eyes(head, 0.088, 0.035, 0.2, 0.032);
    // the bushy tail, curving up behind, a cream tip
    const tail = new THREE.Group(); tail.position.set(0, 0.2, -0.16); body.add(tail);
    const tailBend = new THREE.Group(); tailBend.rotation.x = 0.75; tail.add(tailBend);
    T.add(tailBend, T.sph(0.13, 14, 10), orange, 0, 0, -0.2, 0.78, 0.78, 1.9);
    T.add(tailBend, T.sph(0.085, 12, 8), cream, 0, 0, -0.42, 1, 1, 1.3);
    return finish(root, o, { body, head, legs, arms, eyes, legY: 0.1,
      extra(tt, pose, moving) {
        tail.rotation.y = Math.sin(tt * (moving ? 7 : pose === 'wait' ? 5 : 1.6)) * (moving || pose === 'wait' ? 0.4 : 0.15);
        tailBend.rotation.x = pose === 'fail' || pose === 'sleep' ? 0.2 : 0.75;
        ears.forEach((e, i) => { e.rotation.z = (i ? -1 : 1) * (pose === 'fail' ? 0.9 : 0.35 + Math.max(0, Math.sin(tt * 0.9 + i)) * 0.06); });
      } });
  }

  // ── the robot: a boxy toy with a face screen, an antenna light and a chest light in the family colour ──
  function robot(K, o) {
    const T = tools(K, o), { THREE } = T, root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group();
    root.add(body);
    const shell = T.mat('#d3dcdf', { rough: 0.45, metal: 0.15 }), joint = T.mat('#8e9ba2', { rough: 0.5, metal: 0.2 }), screen = T.mat('#26353c', { rough: 0.3 });
    const famLight = T.famMat(0.45, 0.9), eyeM = K.mat('#bff6ff', { smooth: true, glow: '#8fefff', gi: K.night ? 1.0 : 0.6 });
    const legs = legsPair(T, body, T.cyl(0.05, 0.05, 0.14, 10), joint, 0.095, 0.12);
    legs.forEach(l => T.add(l, T.box(0.12, 0.06, 0.17), shell, 0, -0.08, 0.025));
    T.add(body, T.box(0.38, 0.4, 0.3), shell, 0, 0.4, 0);
    T.add(body, T.box(0.2, 0.075, 0.02), famLight, 0, 0.29, 0.155);   // the chest light
    T.badge(body, 0, 0.47, 0.158);
    T.add(body, T.cyl(0.055, 0.065, 0.1, 10), joint, 0, 0.64, 0);    // neck
    const arms = [-1, 1].map(s => {
      const a = T.arm(body, s, 0.215, 0.56, 0.0);
      T.add(a, T.sph(0.05, 10, 8), joint, 0, 0, 0);
      T.add(a, T.cyl(0.035, 0.035, 0.2, 8), joint, 0, -0.11, 0); T.add(a, T.sph(0.055, 10, 8), shell, 0, -0.23, 0);
      return a;
    });
    head.position.set(0, 0.87, 0); body.add(head);
    T.add(head, T.box(0.46, 0.33, 0.34), shell, 0, 0, 0);
    T.add(head, T.box(0.37, 0.22, 0.02), screen, 0, -0.005, 0.17);
    const eyes = [-1, 1].map(s => T.add(head, T.sph(0.038, 10, 8), eyeM, s * 0.085, 0.02, 0.18, 1, 1.35, 0.6));
    const smile = T.add(head, T.torus(0.04, 0.008, Math.PI), eyeM, 0, -0.045, 0.182); smile.rotation.z = Math.PI;
    [-1, 1].forEach(s => { const b = T.add(head, T.cyl(0.055, 0.055, 0.04, 10), joint, s * 0.245, 0, 0); b.rotation.z = Math.PI / 2; });
    T.add(head, T.cyl(0.012, 0.012, 0.14, 6), joint, 0, 0.235, 0);
    const bulb = T.add(head, T.sph(0.045, 12, 10), famLight, 0, 0.33, 0);
    return finish(root, o, { body, head, legs, arms, eyes, legY: 0.12,
      extra(tt, pose) {
        const k = pose === 'wait' ? 1 + Math.abs(Math.sin(tt * 6)) * 0.5 : pose === 'sleep' || pose === 'fail' ? 0.75 : 1 + Math.sin(tt * 2.5) * 0.08;
        bulb.scale.setScalar(k);
        smile.scale.y = pose === 'fail' ? -1 : 1;   // a frown when it fails
        smile.position.y = pose === 'fail' ? -0.07 : -0.045;
      } });
  }

  const BUILDERS = { human, frog, owl, fox, robot };

  /** any character by id (an unknown id gives the newt); the same interface as Lab3D.makeNewt */
  L.makeCharacter = function makeCharacter(K, id, o) {
    o = o || {};
    const b = BUILDERS[id];
    return b ? b(K, o) : L.makeNewt(K, o);
  };
})();
