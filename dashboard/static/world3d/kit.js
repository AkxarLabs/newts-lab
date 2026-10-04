/* Lab3D — the tabletop lab's kit. Rooms and furniture are DATA and small builders, so a lab (or its
 * coding agent) can add its own without touching the engine:
 *
 *   Lab3D.defineComponent('bench', {           // one piece of furniture: built from primitives
 *     build(K, props) { return K.group(K.box(2, 0.9, 0.7, 'wood'), …); },   // 1 unit = 1 m, y up,
 *   });                                          //  standing on y = 0, its front facing +z
 *
 *   Lab3D.defineRoom({                           // one room's look (which rooms exist is the workflow's)
 *     key: 'lab', size: [10, 7], floor: 'tiles', wall: 'plaster', accent: 'teal',
 *     props: [{ c: 'bench', at: [x, z], rot: 0, props: {…} }],   // room-local: x across, z toward the
 *     stations: { experiment: [x, z], improve: [x, z] },          //  open front (the hub); back wall at -z
 *     roleStation: { overseer: [x, z] },                           // where a subagent role works here
 *   });
 *
 * A station is where an agent running that procedure stands; a procedure with no station gets a desk of
 * its own, laid out by the engine. A room with no file at all is drawn plain: a floor, low walls and a
 * desk per procedure. Colours are theme names (K.col), so every piece reads right by day and by night.
 */
(function () {
  'use strict';
  const L = (window.Lab3D = window.Lab3D || {});
  L.components = {};
  L.rooms = {};
  L.defineComponent = (name, def) => { L.components[name] = def; return def; };
  L.defineRoom = spec => { L.rooms[spec.key] = Object.assign({ size: [9, 7], floor: 'boards', wall: 'plaster', accent: 'teal', props: [], stations: {}, roleStation: {} }, spec); return L.rooms[spec.key]; };

  // palettes: soft, warm, low-saturation by day; the same hues dimmed by night, with what shines lit
  L.THEMES = {
    day: { sky: ['#bcd7ee', '#f3efe6'], table: '#efe7d6', tableSide: '#8a6f55', soil: '#6f5640', path: '#ddd2bd', grass: '#a9c99a',
      sun: 2.6, hemi: 1.15, ambient: 0.25, fog: '#eef0ea',
      colors: { wood: '#c9a27a', woodLight: '#e3c9a4', woodDark: '#8a6648', plaster: '#f1e9dc', plasterDark: '#e0d4c2', boards: '#d8b88f', tiles: '#d7e4df',
        carpet: '#c98f7d', rug: '#7f9fb8', paper: '#fbf7ef', ink: '#2d2a26', metal: '#9aa7ad', steel: '#6f7f86', glass: '#bfe3ea', screen: '#2f4d57',
        plant: '#6faf6c', leaf: '#5d9c5d', soil: '#6f5640', pot: '#c97c5d', teal: '#2d8a7c', rose: '#cf7a8f', ochre: '#d9a441', blue: '#5b86b8', violet: '#8b74c2',
        lamp: '#ffd98a', liquid: '#44e8cf', cream: '#f1e4da', amber: '#f0b24a', red: '#d0584a', green: '#5fae6e', white: '#ffffff', black: '#1d1d1f' } },
    night: { sky: ['#0b1622', '#101b1f'], table: '#3a5257', tableSide: '#1a2624', soil: '#0d1214', path: '#4f6668', grass: '#2f5f50',
      sun: 0.95, hemi: 0.85, ambient: 0.16, fog: '#0d161a', neon: '#3fbfae',
      colors: { wood: '#7a5f47', woodLight: '#93775c', woodDark: '#4d3a2b', plaster: '#3a4446', plasterDark: '#2f383a', boards: '#5e4a39', tiles: '#38494a',
        carpet: '#6b4a4a', rug: '#3d5568', paper: '#cfd6d2', ink: '#1a1d1f', metal: '#5f6b70', steel: '#46545a', glass: '#4f8f99', screen: '#2b6f7a',
        plant: '#478a68', leaf: '#3c7858', soil: '#2a2420', pot: '#7d4f3e', teal: '#5ccfbc', rose: '#d27b98', ochre: '#c99a45', blue: '#6d93c9', violet: '#9b85d6',
        lamp: '#ffcf7a', liquid: '#5ff0d8', cream: '#e9ddd2', amber: '#f0c26c', red: '#e06a5a', green: '#6fd39a', white: '#e9efed', black: '#0c0e10' } },
  };

  /** A room given as DATA (a lab's own room, lab/rooms3d/<id>.json, or an agent's design): new furniture is a
   *  list of parts — {shape: box|cyl|cone|sphere, size, at: [x, y, z], rot?, color, glow?, alpha?} — so nothing
   *  in it is code. box size [w, h, d] · cyl [rTop, rBottom, h] · cone [r, h] · sphere [r]; y is the part's base
   *  (a sphere's centre). */
  L.defineRoomData = function defineRoomData(d) {
    for (const [name, c] of Object.entries(d.components || {})) {
      L.defineComponent(name, { build(K) {
        const g = K.group();
        for (const p of c.parts || []) {
          const [a, b, h] = p.size, [x, y, z] = p.at, o = { glow: p.glow ? p.color : null, alpha: p.alpha };
          const m = p.shape === 'box' ? K.box(a, b, h, p.color, x, y, z, o) : p.shape === 'cyl' ? K.cyl(a, b, h, p.color, x, y, z, o)
            : p.shape === 'cone' ? K.cone(a, b, p.color, x, y, z, o) : K.sphere(a, p.color, x, y, z, o);
          if (p.rot) m.rotation.set(p.rot[0], p.rot[1], p.rot[2]);
          g.add(m);
        }
        return g;
      } });
    }
    return L.defineRoom({ key: d.key, title: d.title, size: d.size, floor: d.floor || 'boards', wall: d.wall || 'plaster', accent: d.accent || 'teal',
      walls: d.walls !== false, props: d.props || [], stations: d.stations || {}, roleStation: d.roleStation || {} });
  };

  /** the builder's toolbox for one theme: materials, primitives, a sign */
  L.kit = function kit(THREE, themeName) {
    const th = L.THEMES[themeName], night = themeName === 'night', cache = new Map();
    const col = c => (typeof c === 'string' && th.colors[c]) || c;
    const mat = (c, o) => {
      o = o || {};
      const key = c + '|' + JSON.stringify(o);
      if (!cache.has(key)) cache.set(key, new THREE.MeshStandardMaterial({ color: col(c), roughness: o.rough ?? 0.82, metalness: o.metal ?? 0, flatShading: o.smooth ? false : true,
        emissive: o.glow ? col(o.glow === true ? c : o.glow) : 0x000000, emissiveIntensity: o.glow ? (o.gi ?? (night ? 1.3 : 0.25)) : 0,
        transparent: o.alpha != null, opacity: o.alpha ?? 1, vertexColors: !!o.vc }));
      return cache.get(key);
    };
    const asMat = (c, o) => (c && c.isMaterial ? c : mat(c, o));
    const mesh = (geo, m, x, y, z) => { const me = new THREE.Mesh(geo, m); me.position.set(x || 0, y || 0, z || 0); me.castShadow = true; me.receiveShadow = true; return me; };
    const K = {
      THREE, th, themeName, night, col, mat, mesh,
      /** a box standing on y (its base at y) */
      box: (w, h, d, c, x, y, z, o) => mesh(new THREE.BoxGeometry(w, h, d), asMat(c, o), x, (y || 0) + h / 2, z),
      cyl: (rt, rb, h, c, x, y, z, o) => mesh(new THREE.CylinderGeometry(rt, rb, h, (o && o.seg) || 14), asMat(c, o), x, (y || 0) + h / 2, z),
      sphere: (r, c, x, y, z, o) => mesh(new THREE.SphereGeometry(r, (o && o.seg) || 16, (o && o.seg) ? Math.max(6, o.seg * 0.7 | 0) : 12), asMat(c, o), x, y, z),
      cone: (r, h, c, x, y, z, o) => mesh(new THREE.ConeGeometry(r, h, (o && o.seg) || 10), asMat(c, o), x, (y || 0) + h / 2, z),
      group(...kids) { const g = new THREE.Group(); kids.flat().forEach(k => k && g.add(k)); return g; },
      at(obj, x, y, z, ry) { obj.position.set(x || 0, y || 0, z || 0); if (ry) obj.rotation.y = ry; return obj; },
      /** another component, by name */
      build(name, props) {
        const d = L.components[name];
        if (!d) { console.warn(`Lab3D: no component '${name}'`); return new THREE.Group(); }
        const o = d.build(K, props || {}); o.userData.component = name; return o;
      },
      /** a flat sign with text (a canvas texture), facing +z */
      sign(text, o) {
        o = o || {};
        const c = document.createElement('canvas'), px = 64, font = o.font || '600 40px Newsreader, Georgia, serif';
        const x = c.getContext('2d'); x.font = font; const tw = Math.ceil(x.measureText(text).width) + 40;
        c.width = tw; c.height = px; const y = c.getContext('2d');
        y.fillStyle = o.bg || col('paper'); y.fillRect(0, 0, tw, px); y.fillStyle = o.fg || col('ink'); y.font = font; y.textBaseline = 'middle'; y.textAlign = 'center'; y.fillText(text, tw / 2, px / 2 + 2);
        const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
        const h = o.h || 0.3, w = h * tw / px;
        const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.9, emissive: night ? 0xffffff : 0x000000, emissiveMap: night ? tex : null, emissiveIntensity: night ? 0.35 : 0 }));
        return m;
      },
    };
    return K;
  };
})();
