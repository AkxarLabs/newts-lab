/* Lab3D — the newt, in 3D: the lab's axolotl (static/assets/buddy/) rebuilt from primitives. A cream,
 * upright little body under a big round head with two bead eyes set wide; three branching gill fronds a
 * side and a curled tail, both shading pink → lavender → sky blue (they glow a little at night). A role
 * badge on its chest says what kind of agent it is.
 *
 *   const n = Lab3D.makeNewt(K, { color: '#5ccfbc', hue: 40, scale: 1 });
 *     color: the role badge on its chest · hue: turns its gills and tail round the colour wheel (a main agent's
 *     family colour — its subagents are smaller newts in the same colours) · scale: its size
 *   n.group                       — add it to the scene
 *   n.update(t, { pose, moving }) — pose: idle | work | walk | wait | sleep | fail | carry
 */
(function () {
  'use strict';
  const L = (window.Lab3D = window.Lab3D || {});
  const GILL = ['#ff9fd6', '#c9a7ff', '#8fd8ff'];
  const TAIL = ['#f7a6d2', '#c39cf3', '#9fd3ff'];

  const turn = (THREE, c, deg) => (deg ? '#' + new THREE.Color(c).offsetHSL(deg / 360, 0, 0).getHexString() : c);
  function lerpColor(THREE, cs, u) {
    const n = cs.length - 1, i = Math.min(n - 1, Math.floor(u * n)), f = u * n - i;
    return new THREE.Color(cs[i]).lerp(new THREE.Color(cs[i + 1]), f);
  }

  /** a tube along a curve whose radius tapers from r0 to r1, coloured along its length */
  function taperedTube(K, pts, r0, r1, colors) {
    const { THREE } = K, curve = new THREE.CatmullRomCurve3(pts.map(p => new THREE.Vector3(...p)));
    const segs = 28, radial = 10, geo = new THREE.TubeGeometry(curve, segs, 1, radial, false);
    const pos = geo.attributes.position, cols = new Float32Array(pos.count * 3), c = new THREE.Vector3(), v = new THREE.Vector3();
    for (let i = 0; i <= segs; i++) {
      const u = i / segs, r = r0 + (r1 - r0) * Math.pow(u, 0.85), col = lerpColor(THREE, colors, u);
      curve.getPointAt(u, c);
      for (let j = 0; j <= radial; j++) {
        const k = i * (radial + 1) + j;
        v.fromBufferAttribute(pos, k).sub(c).multiplyScalar(r).add(c); pos.setXYZ(k, v.x, v.y, v.z);
        cols[k * 3] = col.r; cols[k * 3 + 1] = col.g; cols[k * 3 + 2] = col.b;
      }
    }
    geo.setAttribute('color', new THREE.BufferAttribute(cols, 3)); geo.computeVertexNormals();
    // cap the thick end with a sphere so it reads as one body
    const m = K.mesh(geo, K.mat('#ffffff', { vc: true, smooth: true, glow: K.night ? '#6c4f8a' : null, gi: 0.5 }));
    return m;
  }

  /** one gill frond: a tapered stalk pointing up (+y) with little side twigs */
  function frond(K, len, color) {
    const { THREE } = K, g = new THREE.Group();
    const m = K.mat(color, { smooth: true, glow: K.night ? color : null, gi: K.night ? 0.55 : 0.12 });
    const stalk = K.mesh(new THREE.ConeGeometry(0.032, len, 7), m, 0, len / 2, 0); g.add(stalk);
    for (let i = 0; i < 3; i++) {
      const y = len * (0.3 + i * 0.22), side = i % 2 ? 1 : -1, tw = K.mesh(new THREE.ConeGeometry(0.016, len * 0.38, 6), m, 0, 0, 0);
      tw.position.set(side * 0.03, y + len * 0.12, 0); tw.rotation.z = -side * 0.95; g.add(tw);
    }
    return g;
  }

  L.makeNewt = function makeNewt(K, o) {
    o = o || {};
    const { THREE } = K, root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group();
    const gill = GILL.map(c => turn(THREE, c, o.hue || 0)), tailC = TAIL.map(c => turn(THREE, c, o.hue || 0));
    const skin = K.mat(o.skin || 'cream', { smooth: true, rough: 0.7 }), dark = K.mat('#151517', { smooth: true, rough: 0.3 });
    root.add(body);
    // legs + feet
    const legs = [-1, 1].map(s => { const l = K.mesh(new THREE.CapsuleGeometry(0.06, 0.1, 4, 8), skin, s * 0.11, 0.1, 0.02); body.add(l); return l; });
    // the upright, pear-shaped body (a lathe)
    const prof = [[0.001, 0.07], [0.15, 0.09], [0.205, 0.2], [0.215, 0.34], [0.19, 0.5], [0.15, 0.64], [0.12, 0.74], [0.001, 0.76]].map(([r, y]) => new THREE.Vector2(r, y));
    const torso = K.mesh(new THREE.LatheGeometry(prof, 18), skin); body.add(torso);
    // arms: little paws held in front
    const arms = [-1, 1].map(s => {
      const a = new THREE.Group(); a.position.set(s * 0.15, 0.55, 0.09);
      const limb = K.mesh(new THREE.CapsuleGeometry(0.042, 0.13, 4, 8), skin, 0, -0.08, 0); a.add(limb);
      a.rotation.x = -0.55; a.rotation.z = s * 0.18; body.add(a); return a;
    });
    // a role badge on the chest
    if (o.color) { const b = K.mesh(new THREE.SphereGeometry(0.045, 14, 10), K.mat(o.color, { glow: o.color, gi: K.night ? 0.9 : 0.25, smooth: true }), 0, 0.36, 0.2); b.scale.z = 0.5; body.add(b); }
    // the big round head
    head.position.set(0, 0.9, 0); body.add(head);
    const skull = K.mesh(new THREE.SphereGeometry(0.26, 22, 16), skin); skull.scale.set(1.16, 0.95, 1.05); head.add(skull);
    const eyes = [-1, 1].map(s => { const e = K.mesh(new THREE.SphereGeometry(0.034, 12, 10), dark, s * 0.16, -0.02, 0.243); head.add(e); return e; });
    eyes.forEach(e => { const hl = K.mesh(new THREE.SphereGeometry(0.009, 6, 6), K.mat('#ffffff', { smooth: true, glow: '#ffffff', gi: 0.6 }), 0.01, 0.012, 0.03); e.add(hl); });
    const mouth = K.mesh(new THREE.BoxGeometry(0.05, 0.006, 0.01), dark, 0, -0.085, 0.262); head.add(mouth);
    // gills: three fronds a side, fanned out behind the cheeks
    const gills = [-1, 1].map(s => {
      const g = new THREE.Group(); g.position.set(s * 0.25, 0.02, -0.05); g.scale.setScalar(1.5);
      [[0.32, 0.35, gill[0]], [0.27, 0.9, gill[1]], [0.22, 1.45, gill[2]]].forEach(([len, ang, c]) => { const f = frond(K, len, c); f.rotation.z = -s * ang; f.rotation.x = -0.25; g.add(f); });
      head.add(g); return g;
    });
    // the curled tail
    const tail = new THREE.Group(); tail.position.set(0, 0.14, -0.14); body.add(tail);
    tail.add(taperedTube(K, [[0, 0.02, 0], [0, -0.02, -0.2], [0.04, 0.03, -0.4], [0.09, 0.17, -0.5], [0.08, 0.3, -0.44]], 0.12, 0.025, tailC));
    root.traverse(m => { if (m.isMesh) m.castShadow = true; });
    if (o.scale) root.scale.setScalar(o.scale);

    const phase = Math.random() * 10;
    function update(t, s) {
      const pose = (s && s.pose) || 'idle', moving = s && s.moving, tt = t + phase;
      let bob = Math.sin(tt * 2) * 0.008, lean = 0, headTilt = 0, armL = -0.55, armR = -0.55, blink = Math.sin(tt * 0.7) > 0.985, raise = [0, 0];
      legs[0].position.y = legs[1].position.y = 0.1; legs[0].rotation.x = legs[1].rotation.x = 0;
      if (moving || pose === 'walk' || pose === 'carry') {
        const w = Math.sin(tt * 9); bob = Math.abs(w) * 0.04; legs[0].rotation.x = w * 0.5; legs[1].rotation.x = -w * 0.5; lean = 0.08;
        armL = -0.55 + w * 0.3; armR = -0.55 - w * 0.3;
      }
      if (pose === 'work') { lean = 0.12; armL = -1.05 + Math.max(0, Math.sin(tt * 11)) * 0.25; armR = -1.05 + Math.max(0, Math.sin(tt * 11 + 2)) * 0.25; headTilt = 0.12 + Math.sin(tt * 1.3) * 0.05; }
      if (pose === 'wait') { armR = -0.2; raise = [0, 2.55 + Math.sin(tt * 5) * 0.15]; bob = Math.abs(Math.sin(tt * 3)) * 0.03; headTilt = -0.12; }
      if (pose === 'carry') { armL = armR = -0.3; raise = [2.35, 2.35]; }
      if (pose === 'sleep') { headTilt = 0.35; blink = true; bob = Math.sin(tt * 1.2) * 0.012; }
      if (pose === 'fail') { headTilt = 0.45; lean = 0.18; armL = armR = -0.1; }
      body.position.y = bob; body.rotation.x = lean; head.rotation.x = headTilt; head.rotation.z = pose === 'idle' ? Math.sin(tt * 0.6) * 0.06 : 0;
      arms[0].rotation.x = armL; arms[1].rotation.x = armR;
      arms[0].rotation.z = -0.18 - (raise[0] || 0); arms[1].rotation.z = 0.18 + (raise[1] || 0);   // a raised arm goes up beside the head, not into it
      eyes.forEach(e => { e.scale.y = blink ? 0.15 : 1; });
      gills.forEach((g, i) => { g.rotation.z = (i ? -1 : 1) * Math.sin(tt * 2.2) * 0.07; });
      tail.rotation.y = Math.sin(tt * (moving ? 6 : 1.6)) * (moving ? 0.35 : 0.15);
    }
    update(0, {});
    return { group: root, update, head };
  };
})();
