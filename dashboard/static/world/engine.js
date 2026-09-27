/* Vivarium world — the PixiJS engine ("the pop-up book laboratory").
 *
 * Implements the SAME contract as app.js `createWorld` (the Canvas2D painted world, kept as the fallback):
 *   sync · setPose · setLamp · setView · goRoom · focusProject · back · viewInfo · highlight · layout ·
 *   setAmbient · followWorker/stopFollow/following · onClick/onWorker/onNewt/onView/onFollow · kind
 * so the rest of the dashboard (tabs, inspector, minimap, Key panel, demo mode) doesn't know which world
 * it is talking to.
 *
 * Scene graph (one Pixi Application, one canvas — #scene):
 *   stage ─ bg (screen) ─ world[camera] ─ backdrop (slower parallax) ─ facade (cut walls, slabs, roof)
 *                                         └ rooms: one sortable Container per room (shell, props, creatures,
 *                                           each prop's glow + live fx as its children, sorted by feet y)
 *         └ screen: labels · hover tag · Newt · vignette
 * Everything static is baked once per theme (paper.js → canvas → texture); per frame only transforms,
 * a few Graphics (LEDs, screens, rings) and small sprites (bubbles, steam, spores) change.
 */
(function () {
  'use strict';
  const W = (window.VivWorld = window.VivWorld || {});
  const { clamp, lerp, ease, hash2, rng } = W.noise;
  const T = W.tokens;

  W.createPixiWorld = async function createPixiWorld(canvas, opts) {
    const PIXI = window.PIXI;
    if (!PIXI) throw new Error('PixiJS is not loaded');
    if (PIXI.isWebGLSupported && !PIXI.isWebGLSupported()) throw new Error('WebGL is not available');
    const D = opts.deps || {};
    const reduced = !!opts.reduced;
    const app = new PIXI.Application();
    await app.init({ canvas, resizeTo: window, antialias: true, backgroundAlpha: 0, autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2), preference: ['webgl'], autoStart: !reduced, powerPreference: 'high-performance' });
    if (reduced) app.ticker.stop();

    // ── model ────────────────────────────────────────────────────────────────
    let theme = opts.lamp === 'day' ? 'day' : 'night';
    const TH = () => T.themes[theme];
    const tokHex = ref => T.hexNum(T.tok(TH(), ref));
    let items = [], workforce = [], slots = { cap: 0, in_use: 0 }, t = 0, pose = 'idle', highlightRole = null, followId = null, ambient = true;
    let onItem = null, onGate = null, onWorker = null, onNewt = null, onView = null, onFollow = null;
    const LAYOUT = W.layoutBuilding(), BOX = LAYOUT.boxes;
    const ROOMS = Object.values(W.rooms).sort((a, b) => (b.floor - a.floor) || (a.order - b.order));
    const ROOM_KEYS = ROOMS.map(r => r.key);
    const STATE_ROOM = Object.assign({}, D.STATE_ROOM || {}, W.stateRoom());
    const roomOfState = st => (STATE_ROOM[st] && W.rooms[STATE_ROOM[st]] ? STATE_ROOM[st] : ROOM_KEYS[0]);
    const BUDDY_WH = 132, PROP_SCALE = 1.3;   // furniture reads a touch larger than life next to the axolotls

    // ── layers ───────────────────────────────────────────────────────────────
    const bg = new PIXI.Graphics(); app.stage.addChild(bg);
    const world = new PIXI.Container(); app.stage.addChild(world);
    const backdropC = new PIXI.Container(); world.addChild(backdropC);
    const facadeC = new PIXI.Container(); world.addChild(facadeC);
    const roomsC = new PIXI.Container(); world.addChild(roomsC);
    const ambientC = new PIXI.Container(); world.addChild(ambientC);
    const travelC = new PIXI.Container(); world.addChild(travelC);   // creatures hopping between rooms
    const screen = new PIXI.Container(); app.stage.addChild(screen);
    const labelsC = new PIXI.Container(); screen.addChild(labelsC);
    const hoverG = new PIXI.Graphics(); screen.addChild(hoverG);
    const hoverT = new PIXI.Text({ text: '', style: { fontFamily: getFont(), fontSize: 13, fontWeight: '600', fill: 0xffffff } }); hoverT.anchor.set(0.5); hoverT.resolution = 2; screen.addChild(hoverT);
    const newtC = new PIXI.Container(); screen.addChild(newtC);
    const grain = new PIXI.TilingSprite({ texture: PIXI.Texture.EMPTY, width: 16, height: 16 }); grain.blendMode = 'multiply'; screen.addChildAt(grain, 0);
    const vignette = new PIXI.Sprite(); screen.addChild(vignette);
    function getFont() { try { return D.getRound ? D.getRound() : 'system-ui, sans-serif'; } catch (e) { return 'system-ui, sans-serif'; } }

    // ── shared soft textures ─────────────────────────────────────────────────
    function canvasTex(w, h, fn) { const c = document.createElement('canvas'); c.width = w; c.height = h; fn(c.getContext('2d'), w, h); return PIXI.Texture.from(c); }
    const TEX = {
      radial: canvasTex(128, 128, (x) => { const g = x.createRadialGradient(64, 64, 0, 64, 64, 64); g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.35, 'rgba(255,255,255,0.5)'); g.addColorStop(1, 'rgba(255,255,255,0)'); x.fillStyle = g; x.fillRect(0, 0, 128, 128); }),
      dot: canvasTex(16, 16, (x) => { x.fillStyle = '#fff'; x.beginPath(); x.arc(8, 8, 7, 0, 6.2832); x.fill(); }),
      ring: canvasTex(16, 16, (x) => { x.strokeStyle = '#fff'; x.lineWidth = 2; x.beginPath(); x.arc(8, 8, 6, 0, 6.2832); x.stroke(); }),
      shadow: canvasTex(64, 16, (x) => { const g = x.createRadialGradient(32, 8, 0, 32, 8, 32); g.addColorStop(0, 'rgba(0,0,0,0.9)'); g.addColorStop(1, 'rgba(0,0,0,0)'); x.fillStyle = g; x.save(); x.scale(1, 0.25); x.beginPath(); x.arc(32, 32, 32, 0, 6.2832); x.restore(); x.fill(); }),
    };

    // ── baking components into textures ─────────────────────────────────────
    const bakeCache = new Map();   // key → baked {base, glow, …} for the current theme
    function bake(name, props, key, res) {
      const k = theme + '|' + key;
      if (bakeCache.has(k)) return bakeCache.get(k);
      const def = W.components[name]; if (!def) throw new Error(`unknown component '${name}'`);
      const [w, h] = def.size(props), seed = W.noise.strSeed(key);
      const P = W.paper.painter(TH(), w, h, res, seed);
      def.draw(P, props);
      const out = { w, h, pad: P.pad, res, base: PIXI.Texture.from(P.base), glow: P.glow ? PIXI.Texture.from(P.glow) : null, parts: [], fx: def.fx ? def.fx(props) : [] };
      for (const part of (def.parts ? def.parts(props) || [] : [])) {
        const PP = W.paper.painter(TH(), part.size[0], part.size[1], res, seed + 99);
        part.draw(PP, props);
        out.parts.push(Object.assign({}, part, { pad: PP.pad, base: PIXI.Texture.from(PP.base), glow: PP.glow ? PIXI.Texture.from(PP.glow) : null }));
      }
      bakeCache.set(k, out);
      return out;
    }
    function dropBakes() { for (const b of bakeCache.values()) { b.base.destroy(true); if (b.glow) b.glow.destroy(true); for (const p of b.parts) { p.base.destroy(true); if (p.glow) p.glow.destroy(true); } } bakeCache.clear(); }
    /** A sprite for a baked texture, anchored at a point given in the component's local units. */
    function spriteAt(tex, pad, w, h, res, ax, ay) {
      const s = new PIXI.Sprite(tex);
      s.anchor.set((pad + ax) / (w + pad * 2), (pad + ay) / (h + pad * 2));
      s.scale.set(1 / res); return s;
    }

    // ── rooms ────────────────────────────────────────────────────────────────
    const roomObjs = {};   // key → {c, spec, box, props:[inst], shell}
    function buildRoom(spec) {
      const box = BOX[spec.key], [rw, rh] = spec.size;
      const c = new PIXI.Container(); c.sortableChildren = true; c.position.set(box.x, box.y);
      const shellB = bake('shell', Object.assign({ w: rw, h: rh }, spec.shell), spec.key + ':shell', 1.15);
      const shell = spriteAt(shellB.base, shellB.pad, rw, rh, shellB.res, 0, 0); shell.zIndex = -1e9; c.addChild(shell);
      if (shellB.glow) { const g = spriteAt(shellB.glow, shellB.pad, rw, rh, shellB.res, 0, 0); g.blendMode = 'add'; g.zIndex = -1e9 + 1; c.addChild(g); }
      const R = { c, spec, box, props: [], rw, rh };
      spec.props.forEach((pr, i) => R.props.push(placeProp(R, pr, i)));
      roomsC.addChild(c);
      roomObjs[spec.key] = R;
      return R;
    }
    function placeProp(R, pr, i) {
      const def = W.components[pr.c], props = pr.props || {};
      const b = bake(pr.c, props, `${R.spec.key}:${i}:${pr.c}`, 1.35);
      const [nx, ny] = pr.at, s = W.depthScale(ny) * (pr.scale || PROP_SCALE);
      const c = new PIXI.Container(); c.position.set(nx * R.rw, ny * R.rh); c.scale.set(s); c.zIndex = def.flat ? -1e8 + ny * R.rh : ny * R.rh;
      const base = spriteAt(b.base, b.pad, b.w, b.h, b.res, b.w / 2, b.h); c.addChild(base);
      if (b.glow) { const g = spriteAt(b.glow, b.pad, b.w, b.h, b.res, b.w / 2, b.h); g.blendMode = 'add'; c.addChild(g); }
      const parts = b.parts.map(p => {
        const sp = spriteAt(p.base, p.pad, p.size[0], p.size[1], b.res, p.pivot[0], p.pivot[1]);
        sp.position.set(p.at[0] + p.pivot[0] - b.w / 2, p.at[1] + p.pivot[1] - b.h); c.addChild(sp);
        let gl = null; if (p.glow) { gl = spriteAt(p.glow, p.pad, p.size[0], p.size[1], b.res, p.pivot[0], p.pivot[1]); gl.position.copyFrom(sp.position); gl.blendMode = 'add'; c.addChild(gl); }
        return { p, sp, gl, fold: 1, spin: 0, ph: hash2(i, p.id.length, 7) * 6.28 };
      });
      const fx = b.fx.map(f => makeFx(f, c, b));
      R.c.addChild(c);
      const hoverable = !!def.hover && def.hover(props, {}) != null;   // decor with nothing to say isn't a hover target
      const inst = { pr, def, props, b, c, parts, fx, s, nx, ny, baseX: c.x, pop: 1, popDelay: 0, hoverable,
        rect: { x: R.box.x + nx * R.rw - b.w / 2 * s, y: R.box.y + ny * R.rh - b.h * s, w: b.w * s, h: b.h * s } };
      return inst;
    }

    // ── live effects (the FX vocabulary components declare) ─────────────────
    function makeFx(f, parent, b) {
      const L = (x, y) => [x - b.w / 2, y - b.h];   // component-local (top-left) → feet-origin
      const o = { f, update() {} };
      if (f.kind === 'bubbles') {
        const [rx, ry, rw, rh] = f.rect, n = 14, cont = new PIXI.Container(); parent.addChild(cont);
        const bubs = Array.from({ length: n }, (_, i) => { const s = new PIXI.Sprite(TEX.ring); s.anchor.set(0.5); s.scale.set(0.3 + (i % 3) * 0.14); cont.addChild(s); return { s, ph: hash2(i, 3, 5), x: hash2(i, 4, 5) }; });
        o.update = (dt, st) => {
          const load = clamp((st.slotsUse || 0) + (st.busy || 0) * 0.5, 0, 4), active = Math.round(5 + load * 2.3);
          bubs.forEach((bb, i) => {
            const sp = 22 + (i % 5) * 9 + load * 10, u = ((t * sp / rh) + bb.ph) % 1, [lx, ly] = L(rx + bb.x * rw + Math.sin(t * 2 + i) * 3, ry + rh - u * rh);
            bb.s.position.set(lx, ly); bb.s.visible = i < active; bb.s.alpha = 0.8 * Math.sin(u * Math.PI); bb.s.tint = tokHex(f.color || 'paper.white');
          });
        };
      } else if (f.kind === 'steam') {
        const cont = new PIXI.Container(); parent.addChild(cont);
        const puffs = Array.from({ length: 6 }, () => { const s = new PIXI.Sprite(TEX.radial); s.anchor.set(0.5); cont.addChild(s); return s; });
        o.update = () => { puffs.forEach((s, i) => { const u = (t * 0.22 + i / 6) % 1, [lx, ly] = L(f.at[0] + Math.sin(u * 5 + i) * 7 * u, f.at[1] - u * 64); s.position.set(lx, ly); s.scale.set((10 + u * 26) / 64); s.alpha = 0.32 * Math.sin(u * Math.PI); s.tint = tokHex(f.color || 'paper.white'); }); };
      } else if (f.kind === 'flicker' || f.kind === 'pulse') {
        const s = new PIXI.Sprite(TEX.radial); s.anchor.set(0.5); s.blendMode = 'add'; const [lx, ly] = L(f.at[0], f.at[1]); s.position.set(lx, ly); s.scale.set(f.r / 64); parent.addChild(s);
        const ph = Math.random() * 6.28;
        o.update = (dt, st) => {
          const night = theme === 'night'; s.tint = tokHex(f.color || 'glow.warm');
          if (f.kind === 'pulse') { const on = st[f.bind] ? 1 : 0; s.alpha = on * (0.35 + 0.3 * Math.sin(t * 3 + ph)) * (night ? 1 : 0.7); return; }
          if (f.nightOnly && !night) { s.alpha = 0; return; }
          const base = night ? 0.28 : 0.08; s.alpha = base * (1 + (f.amp || 0.1) * (Math.sin(t * 7.3 + ph) * 0.6 + Math.sin(t * 13.1 + ph * 2) * 0.4));
        };
      } else if (f.kind === 'leds' || f.kind === 'screen' || f.kind === 'ring' || f.kind === 'clock') {
        const g = new PIXI.Graphics(); parent.addChild(g);
        const glowS = f.kind === 'screen' ? null : null;
        o.update = (dt, st) => {
          g.clear();
          if (f.kind === 'leds') {
            const cap = Math.max(1, st.slotsCap || 1), use = st.slotsUse || 0;
            for (let i = 0; i < Math.min(cap, 9); i++) { const [lx, ly] = L(f.at[0], f.at[1] + i * f.step); const on = i < use, pulse = on ? 0.65 + 0.35 * Math.sin(t * 5 + i) : 0.5; g.roundRect(lx, ly, 26, 8, 2).fill({ color: tokHex(on ? 'glow.primary' : 'glow.warm'), alpha: on ? pulse : 0.35 }); }
          } else if (f.kind === 'screen') {
            const [rx, ry, rw, rh] = f.rect, [lx, ly] = L(rx, ry);
            if (f.mode === 'chart') {
              const n = 9 + (st.nAnalysis || 0) * 2;
              for (let i = 0; i < n; i++) { const v = 0.25 + 0.65 * (0.5 + 0.5 * Math.sin(i * 1.3 + (st.seed || 0) + t * 0.2)); g.rect(lx + 10 + i * (rw * 0.55 / n), ly + rh - 6 - v * (rh - 16), rw * 0.55 / n - 3, v * (rh - 16)).fill({ color: tokHex('glow.screen'), alpha: 0.8 }); }
              g.moveTo(lx + rw * 0.62, ly + rh * 0.7); for (let i = 1; i <= 30; i++) g.lineTo(lx + rw * 0.62 + i * rw * 0.34 / 30, ly + rh * 0.75 - (0.3 + 0.35 * Math.sin(i * 0.3 + (st.seed || 0)) + i / 30 * 0.25) * rh * 0.6);
              g.stroke({ width: 2, color: tokHex('glow.warm'), alpha: 0.9 });
            } else if (st[f.bind === 'busy' ? 'busy' : f.bind]) {
              const off = (t * 12) % 7;
              for (let r = 0; r < Math.floor(rh / 7); r++) { const w2 = 12 + hash2(r + Math.floor(t * 1.7), rx | 0, 9) * (rw - 30); g.rect(lx + 5 + (r % 3) * 5, ly + 4 + r * 7 - off + 7, w2, 2.4).fill({ color: tokHex(['glow.screen', 'glow.primary', 'glow.warm'][r % 3]), alpha: 0.8 }); }
              g.rect(lx, ly, rw, rh).fill({ color: 0, alpha: 0 });
            } else { g.rect(lx, ly, rw, rh).fill({ color: tokHex('glow.screen'), alpha: 0.08 + 0.04 * Math.sin(t) }); }
          } else if (f.kind === 'ring') {
            const [cx, cy] = L(f.center[0], f.center[1]), a0 = t * 0.9;
            for (const off of [0, Math.PI]) { g.moveTo(cx + Math.cos(a0 + off) * f.rx, cy + Math.sin(a0 + off) * f.ry); for (let i = 1; i <= 16; i++) { const a = a0 + off + i / 16 * 1.4; g.lineTo(cx + Math.cos(a) * f.rx, cy + Math.sin(a) * f.ry); } }
            g.stroke({ width: 2.5, color: tokHex(f.color || 'glow.primary'), alpha: theme === 'night' ? 0.9 : 0.6 });
          } else if (f.kind === 'clock') {
            const [cx, cy] = L(f.at[0], f.at[1]), now = new Date();
            const hA = ((now.getHours() % 12) + now.getMinutes() / 60) / 12 * 6.2832 - Math.PI / 2, mA = (now.getMinutes() + now.getSeconds() / 60) / 60 * 6.2832 - Math.PI / 2;
            g.moveTo(cx, cy).lineTo(cx + Math.cos(hA) * f.r * 0.55, cy + Math.sin(hA) * f.r * 0.55).stroke({ width: 3, color: tokHex('ink.line') });
            g.moveTo(cx, cy).lineTo(cx + Math.cos(mA) * f.r * 0.9, cy + Math.sin(mA) * f.r * 0.9).stroke({ width: 2, color: tokHex('ink.line') });
          }
        };
        void glowS;
      }
      return o;
    }

    // ── the building exterior + backdrop (baked per theme) ───────────────────
    function buildFacade() {
      facadeC.removeChildren().forEach(ch => ch.destroy({ texture: true }));
      backdropC.removeChildren().forEach(ch => ch.destroy({ texture: true }));
      const bb = LAYOUT.bbox, M = 260, ROOF = 380, fx0 = bb.x - M, fy0 = bb.y - M - ROOF, fw = bb.w + M * 2, fh = bb.h + M * 2 + ROOF;
      const res = Math.min(0.55, 2600 / fw);
      // the section cut: walls between rooms, slabs between floors, the roof, the ground
      const P = W.paper.painter(TH(), fw, fh, res, 777, 20), ox = -fx0, oy = -fy0, S = W.paper.S, night = theme === 'night';
      const WALL = LAYOUT.WALL, SLAB = LAYOUT.SLAB;
      const rowsByFloor = {}; LAYOUT.rows.forEach(r => (rowsByFloor[r.floor] = r));
      const groundY = oy + 0 + SLAB * 0.5;
      // earth / rock around the cellar + the ground line
      P.piece(S.rect(0, groundY, fw, fh - groundY), { fill: night ? 'surface.section' : 'plant.soil', lift: 2, hatch: 0.55, deckle: 1.4, pattern: (x2, b) => { x2.fillStyle = T.alpha(P.tk(night ? 'ink.faint' : 'paper.shade'), 0.35); const rr = rng(9); for (let i = 0; i < 900; i++) { const px = b.x0 + rr() * b.w, py = b.y0 + rr() * b.h; x2.beginPath(); x2.ellipse(px, py, 3 + rr() * 9, 2 + rr() * 5, rr() * 3, 0, 6.2832); x2.fill(); } } });   // earth by day, rock by night
      if (!night) for (let i = 0; i < 60; i++) { const gx = (i / 60) * fw + hash2(i, 1, 3) * 30; P.line([[gx, groundY + 2], [gx + 4, groundY - 14 - hash2(i, 2, 3) * 12]], { color: 'plant.leafDark', w: 1.4 }); }
      for (const r of LAYOUT.rows) {
        const x = ox + r.x, y = oy + r.y;
        P.piece(S.rect(x - 6, y - SLAB, r.w + 12, SLAB), { fill: 'surface.section', lift: 3, hatch: 0.7, deckle: 0.8 });           // the slab above the row
        P.piece(S.rect(x - 6, y + r.h, r.w + 12, SLAB * 0.6), { fill: 'surface.section', lift: 2, hatch: 0.7, deckle: 0.8 });      // the floor it stands on
        const rs = ROOMS.filter(q => BOX[q.key].floor === r.floor).map(q => BOX[q.key]).sort((a, b) => a.x - b.x);
        let wx = x;
        for (const bx of rs) { P.piece(S.rect(wx, y, ox + bx.x - wx, r.h), { fill: 'surface.section', lift: 3, hatch: 0.7, deckle: 0.8 }); wx = ox + bx.x + bx.w; }
        P.piece(S.rect(wx, y, x + r.w - wx, r.h), { fill: 'surface.section', lift: 3, hatch: 0.7, deckle: 0.8 });
      }
      // the roof over the top floor: a pitched paper roof with shingles; a glass roof where a floor is uncovered
      const top = LAYOUT.rows.reduce((a, b) => (a.y < b.y ? a : b));
      const tx = ox + top.x - 40, ty = oy + top.y - SLAB, tw = top.w + 80;
      P.piece(S.poly([[tx - 30, ty], [tx + tw + 30, ty], [tx + tw * 0.78, ty - ROOF * 0.8], [tx + tw * 0.22, ty - ROOF * 0.8]]), { fill: night ? 'paper.shade' : 'fabric.rug', lift: 4, hatch: 0.4, pattern: (x2, b) => { x2.strokeStyle = T.alpha(P.tk(night ? 'ink.soft' : 'ink.line'), 0.45); x2.lineWidth = 1.4; for (let yy = b.y0 + 22; yy < b.y1; yy += 22) { x2.beginPath(); x2.moveTo(b.x0, yy); x2.lineTo(b.x1, yy); x2.stroke(); for (let xx = b.x0 + ((yy / 22) % 2) * 20; xx < b.x1; xx += 40) { x2.beginPath(); x2.moveTo(xx, yy - 22); x2.lineTo(xx, yy); x2.stroke(); } } } });
      P.piece(S.rect(tx + tw * 0.62, ty - ROOF * 0.95, 70, ROOF * 0.4), { fill: 'surface.section', lift: 3, hatch: 0.5 });       // chimney
      const g0 = rowsByFloor[0];
      if (g0 && top.floor !== 0) {   // uncovered ends of the ground floor get glasshouse roofs
        const cov = { x0: ox + top.x, x1: ox + top.x + top.w };
        for (const [a, b2] of [[ox + g0.x, cov.x0], [cov.x1, ox + g0.x + g0.w]]) {
          if (b2 - a < 120) continue;
          const ry = oy + g0.y - SLAB;
          P.piece(S.poly([[a, ry], [b2, ry], [b2 - 30, ry - 150], [a + 30, ry - 150]]), { fill: 'glass.fill', lift: 3, glow: 'glow.secondary', glowAlpha: night ? 0.08 : 0.3, pattern: (x2, bb2) => { x2.strokeStyle = P.tk('metal.iron'); x2.lineWidth = 3; for (let xx = bb2.x0; xx < bb2.x1; xx += 60) { x2.beginPath(); x2.moveTo(xx, bb2.y1); x2.lineTo(xx + 10, bb2.y0); x2.stroke(); } x2.beginPath(); x2.moveTo(bb2.x0, bb2.y0 + 75); x2.lineTo(bb2.x1, bb2.y0 + 75); x2.stroke(); } });
          for (let i = 0; i < 4; i++) W.drawHelpers.plantAt(P, a + 60 + i * (b2 - a - 120) / 3, ry - 150, 60, i % 2 ? 'fern' : 'monstera', i + 5);
        }
      }
      const fs = new PIXI.Sprite(PIXI.Texture.from(P.base)); fs.position.set(fx0 - P.pad, fy0 - P.pad); fs.scale.set(1 / res); facadeC.addChild(fs);
      if (P.glow) { const gs = new PIXI.Sprite(PIXI.Texture.from(P.glow)); gs.position.copyFrom(fs.position); gs.scale.set(1 / res); gs.blendMode = 'add'; facadeC.addChild(gs); }
      // the backdrop: rolling sketched hills + trees + clouds by day; cave rock, hanging roots and fungi by night
      const BM = 2400, bx0 = bb.x - BM, by0 = bb.y - BM, bw = bb.w + BM * 2, bh = bb.h + BM * 2, bres = Math.min(0.2, 1800 / bw);
      const B = W.paper.painter(TH(), bw, bh, bres, 555, 0), gy = -by0 + SLAB * 0.5, r = rng(night ? 5 : 3);
      if (!night) {
        for (let i = 0; i < 9; i++) B.piece(S.blob(r() * bw, bh * 0.12 + r() * bh * 0.2, 220 + r() * 260, 60 + r() * 60, i * 3, 0.35), { fill: 'paper.light', lift: 3, wash: 'wash.blue', ink: false, deckle: 3 });
        B.piece(S.circle(bw * 0.78, bh * 0.14, 110), { fill: 'sky.celestial', lift: 0, wash: 'wash.ochre', glow: 'glow.warm', glowAlpha: 0.6 });
        for (const [k, tone, amp] of [[0.44, 'sky.far', 180], [0.5, 'sky.mid', 140], [0.56, 'sky.near', 110]]) {
          const pts = [[0, bh]]; for (let i = 0; i <= 40; i++) { const xx = i / 40 * bw; pts.push([xx, gy - bh * (0.56 - k) * 1.2 - (W.noise.fbm(i * 0.18, k * 10, 11, 3)) * amp * 2.2]); } pts.push([bw, bh]);
          B.piece(pts, { fill: tone, lift: 4, hatch: 0.25, wash: 'wash.green', deckle: 2 });
        }
        for (let i = 0; i < 40; i++) { const xx = r() * bw; if (Math.abs(xx - (-bx0 + bb.cx)) < bb.w * 0.62) continue; const hh = 120 + r() * 220; B.piece(S.rect(xx - 8, gy - hh * 0.5, 16, hh * 0.5), { fill: 'wood.dark', lift: 2 }); B.piece(S.blob(xx, gy - hh * 0.7, hh * 0.32, hh * 0.36, i * 7, 0.5), { fill: r() < 0.5 ? 'plant.leaf' : 'plant.leafDark', lift: 3, hatch: 0.35, wash: 'wash.green' }); }
      } else {
        for (let i = 0; i < 18; i++) { const xx = r() * bw, yy = r() * bh * 0.35; B.piece(S.blob(xx, yy, 300 + r() * 400, 200 + r() * 260, i * 5, 0.6), { fill: r() < 0.5 ? 'paper.deep' : 'paper.shade', lift: 5, hatch: 0.5, deckle: 4 }); }
        for (let i = 0; i < 14; i++) { const xx = r() * bw; if (Math.abs(xx - (-bx0 + bb.cx)) < bb.w * 0.6) continue; B.piece(S.blob(xx, gy - 100 - r() * 300, 200 + r() * 260, 260 + r() * 300, i * 9, 0.5), { fill: 'paper.shade', lift: 5, hatch: 0.4 }); }
        for (let i = 0; i < 70; i++) { const xx = r() * bw, len = 200 + r() * 800, pts = []; for (let k = 0; k <= 10; k++) pts.push([xx + Math.sin(k * 0.8 + i) * 14, k * len / 10]); B.line(pts, { color: 'plant.stem', w: 3 + r() * 4, glow: r() < 0.3 ? 'ink.faint' : null }); }
        for (let i = 0; i < 260; i++) { const xx = r() * bw, yy = r() * bh; B.glowSpot(xx, yy, 6 + r() * 16, r() < 0.8 ? 'glow.primary' : 'glow.accent', 0.5 + r() * 0.5); }
        B.piece(S.rect(0, gy, bw, bh - gy), { fill: 'paper.deep', lift: 3, hatch: 0.5, deckle: 3 });
      }
      const bs = new PIXI.Sprite(PIXI.Texture.from(B.base)); bs.position.set(bx0, by0); bs.scale.set(1 / bres); backdropC.addChild(bs);
      if (B.glow) { const g2 = new PIXI.Sprite(PIXI.Texture.from(B.glow)); g2.position.copyFrom(bs.position); g2.scale.set(1 / bres); g2.blendMode = 'add'; backdropC.addChild(g2); }
    }

    // ── theme build / rebuild ────────────────────────────────────────────────
    function paintBg() {
      const th = TH(); bg.clear();
      bg.rect(0, 0, app.screen.width, app.screen.height).fill({ color: T.hexNum(th.sky.top) });
      // vignette: a soft darkening at the edges (screen-space)
      const vc = document.createElement('canvas'); vc.width = 256; vc.height = 256; const vx = vc.getContext('2d');
      const g = vx.createRadialGradient(128, 128, 60, 128, 128, 181); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, `rgba(0,0,0,${th.grade.vignette})`); vx.fillStyle = g; vx.fillRect(0, 0, 256, 256);
      if (vignette.texture && vignette.texture !== PIXI.Texture.EMPTY) vignette.texture.destroy(true);
      vignette.texture = PIXI.Texture.from(vc); vignette.width = app.screen.width; vignette.height = app.screen.height;
      if (!grain._tex || grain._theme !== theme) {   // near-white paper grain: multiply darkens by a few percent only
        const gc = document.createElement('canvas'); gc.width = gc.height = 256; const gx = gc.getContext('2d'), img = gx.createImageData(256, 256), dd = img.data, amp = th.grade.grain * 255 * 1.6;
        for (let i = 0; i < 256 * 256; i++) { const n = hash2(i % 256, (i / 256) | 0, 21) * 0.6 + W.noise.fbm((i % 256) * 0.07, ((i / 256) | 0) * 0.07, 5, 3) * 0.4; const v = 255 - n * amp; dd[i * 4] = dd[i * 4 + 1] = dd[i * 4 + 2] = v; dd[i * 4 + 3] = 255; }
        gx.putImageData(img, 0, 0); if (grain._tex) grain._tex.destroy(true); grain._tex = PIXI.Texture.from(gc); grain.texture = grain._tex; grain._theme = theme;
      }
      grain.width = app.screen.width; grain.height = app.screen.height;
    }
    const timings = {};
    let buildQueue = [], buildToken = 0;
    function buildAll(sync) {
      // creature rigs live inside the room containers: forget them first (they're rebuilt on the next frame)
      for (const e of ents.values()) e.view = null;
      for (const k in roomObjs) { roomObjs[k].c.destroy({ children: true }); delete roomObjs[k]; }
      dropBakes();
      let t0 = performance.now();
      buildFacade(); timings.facade = Math.round(performance.now() - t0);
      paintBg(); buildAmbient();
      // rooms: the one in view first, then the rest, one per tick so the page never stalls
      const want = view.room || null;
      buildQueue = ROOMS.slice().sort((a, b) => (b.key === want) - (a.key === want));
      const token = ++buildToken;
      const step = () => {
        if (token !== buildToken || !buildQueue.length) { if (!buildQueue.length) timings.total = Math.round(performance.now() - t0); return; }
        const spec = buildQueue.shift(), r0 = performance.now();
        buildRoom(spec); timings[spec.key] = Math.round(performance.now() - r0);
        popRoom(spec.key, 0.05);
        if (reduced) kick();
        if (buildQueue.length) setTimeout(step, 0); else timings.total = Math.round(performance.now() - t0);
      };
      if (sync) { while (buildQueue.length) { const spec = buildQueue.shift(); buildRoom(spec); } timings.total = Math.round(performance.now() - t0); }
      else step();
    }

    // ── pop-up mechanics ─────────────────────────────────────────────────────
    function popRoom(key, delay) {
      const R = roomObjs[key]; if (!R || reduced) return;
      const order = R.props.slice().sort((a, b) => a.nx - b.nx);
      order.forEach((p, i) => { p.pop = 0; p.popDelay = (delay || 0) + i * 0.045; });
    }
    function popAll(delay) { ROOM_KEYS.forEach((k, i) => popRoom(k, (delay || 0) + i * 0.08)); }

    // ── ambient: dust motes by day, drifting spores by night ────────────────
    let motes = [];
    function buildAmbient() {
      ambientC.removeChildren().forEach(c => c.destroy());
      motes = [];
      if (reduced || !ambient) return;
      const bb = LAYOUT.bbox, n = 160;
      for (let i = 0; i < n; i++) { const s = new PIXI.Sprite(theme === 'night' ? TEX.radial : TEX.dot); s.anchor.set(0.5); if (theme === 'night') s.blendMode = 'add'; ambientC.addChild(s); motes.push({ s, x: bb.x + Math.random() * bb.w, y: bb.y + Math.random() * bb.h, ph: Math.random() * 6.28, sp: 6 + Math.random() * 14, d: 0.4 + Math.random() * 0.6 }); }
    }
    function updateAmbient(dt) {
      if (!motes.length) return;
      const night = theme === 'night', col = tokHex(night ? 'glow.primary' : 'paper.white'), bb = LAYOUT.bbox;
      for (const m of motes) {
        m.y -= m.sp * dt * (night ? 0.6 : 0.3); m.x += Math.sin(t * 0.4 + m.ph) * dt * 6;
        if (m.y < bb.y) { m.y = bb.y + bb.h; m.x = bb.x + Math.random() * bb.w; }
        m.s.position.set(m.x, m.y); m.s.tint = col;
        m.s.scale.set(night ? (6 + m.d * 10) / 64 : 0.25 + m.d * 0.25);
        m.s.alpha = (night ? 0.35 : 0.45) * (0.5 + 0.5 * Math.sin(t * 1.3 + m.ph)) * m.d;
      }
    }

    // ── creatures (the axolotls, ported from the painted world) ──────────────
    const buddyImg = {};
    async function loadImg(src) { return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; }); }
    await Promise.all(['body', 'body_closed', 'gills', 'tail', 'walk'].map(async n => { try { buddyImg[n] = await loadImg(`/static/assets/buddy/${n}.png`); } catch (e) { buddyImg[n] = null; } }));
    const CAL = calibrate();
    function calibrate() {
      const bbox = (img, sx, sy, sw, sh) => { const c = document.createElement('canvas'); c.width = sw; c.height = sh; const x = c.getContext('2d'); x.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh); const d = x.getImageData(0, 0, sw, sh).data; let a = sh, b = -1; for (let py = 0; py < sh; py += 2) for (let px = 0; px < sw; px += 2) if (d[(py * sw + px) * 4 + 3] > 24) { if (py < a) a = py; if (py > b) b = py; } return b < 0 ? null : { botFrac: (b + 1) / sh, hFrac: (b - a + 1) / sh }; };
      try {
        const body = buddyImg.body, sh = buddyImg.walk; const ib = bbox(body, 0, 0, body.width, body.height), cw = sh.width / 4, ch = sh.height / 2, cells = [];
        for (let i = 0; i < 8; i++) cells.push(bbox(sh, (i % 4) * cw, ((i / 4) | 0) * ch, cw, ch));
        const hs = cells.map(c => c.hFrac).sort((a, b) => a - b); return { K: ib.hFrac / ((hs[3] + hs[4]) / 2), botIdle: ib.botFrac, botWalk: cells.map(c => c.botFrac) };
      } catch (e) { return { K: 1.264, botIdle: 0.854, botWalk: Array(8).fill(0.896) }; }
    }
    const hueTex = {}, outlineTex = {};
    function tinted(name, deg) {
      const k = name + ':' + deg; if (hueTex[k]) return hueTex[k];
      const im = buddyImg[name]; if (!im) return null;
      const scale = name === 'walk' ? 0.5 : 1, c = document.createElement('canvas'); c.width = im.width * scale; c.height = im.height * scale; const x = c.getContext('2d');
      if (deg) x.filter = `hue-rotate(${deg}deg) saturate(1.15)`; x.drawImage(im, 0, 0, c.width, c.height);
      return (hueTex[k] = { tex: PIXI.Texture.from(c), w: c.width, h: c.height });
    }
    function outline(name) {   // a line-art edge for the day theme: the silhouette stamped around a ring
      if (outlineTex[name]) return outlineTex[name];
      const im = buddyImg[name]; if (!im) return null;
      const scale = name === 'walk' ? 0.5 : 1, iw = im.width * scale, ih = im.height * scale, rad = 0.017 * (name === 'walk' ? iw / 4 : iw), pad = Math.ceil(rad + 2);
      const sil = document.createElement('canvas'); sil.width = iw; sil.height = ih; const sx = sil.getContext('2d'); sx.drawImage(im, 0, 0, iw, ih); sx.globalCompositeOperation = 'source-in'; sx.fillStyle = '#2b313c'; sx.fillRect(0, 0, iw, ih);
      const c = document.createElement('canvas'); c.width = iw + pad * 2; c.height = ih + pad * 2; const x = c.getContext('2d');
      for (let i = 0; i < 12; i++) { const a = i / 12 * 6.2832; x.drawImage(sil, pad + Math.cos(a) * rad, pad + Math.sin(a) * rad); }
      return (outlineTex[name] = { tex: PIXI.Texture.from(c), w: iw, h: ih, pad });
    }
    const walkFrames = {};
    function frames(texInfo, key, pad) {
      if (walkFrames[key]) return walkFrames[key];
      const cw = texInfo.w / 4, ch = texInfo.h / 2, p = pad || 0;
      return (walkFrames[key] = Array.from({ length: 8 }, (_, i) => new PIXI.Texture({ source: texInfo.tex.source, frame: new PIXI.Rectangle((i % 4) * cw, ((i / 4) | 0) * ch, cw + p * 2, ch + p * 2) })));
    }
    function hslHex(h, s, l) { s /= 100; l /= 100; const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l), f = n => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))); return (Math.round(f(0) * 255) << 16) | (Math.round(f(8) * 255) << 8) | Math.round(f(4) * 255); }

    /** One creature's sprite rig at unit size (1 = BUDDY_WH world units); feet at (0,0). */
    function makeRig(deg) {
      const c = new PIXI.Container();
      const glow = new PIXI.Sprite(TEX.radial); glow.anchor.set(0.5); glow.blendMode = 'add'; c.addChild(glow);
      const shadow = new PIXI.Sprite(TEX.shadow); shadow.anchor.set(0.5); c.addChild(shadow);
      const mk = () => { const s = new PIXI.Sprite(); c.addChild(s); return s; };
      const rig = { c, glow, shadow, deg, tailO: mk(), tail: mk(), gillsO: mk(), gills: mk(), bodyO: mk(), body: mk(), walkC: new PIXI.Container(), pip: new PIXI.Graphics(), gate: new PIXI.Sprite(TEX.radial) };
      rig.walkO = new PIXI.Sprite(); rig.walk = new PIXI.Sprite(); rig.walkC.addChild(rig.walkO, rig.walk); c.addChild(rig.walkC);
      rig.gate.anchor.set(0.5); rig.gate.blendMode = 'add'; c.addChild(rig.gate); c.addChild(rig.pip);
      return rig;
    }
    function layer(sprite, outlineSprite, name, deg, k, pxf, pyf, dxf, dyf, ang, left, top, closed) {
      const src = name === 'body' ? tinted(closed ? 'body_closed' : 'body', 0) : tinted(name, deg); if (!src) { sprite.visible = false; return; }
      sprite.visible = true; sprite.texture = src.tex; sprite.anchor.set(pxf, pyf);
      sprite.position.set(left + pxf + dxf, top + pyf + dyf); sprite.scale.set(k / src.w, k / src.h); sprite.rotation = ang || 0;
      const O = theme === 'day' ? outline(name === 'body' ? (closed ? 'body_closed' : 'body') : name) : null;
      if (O) { outlineSprite.visible = true; outlineSprite.texture = O.tex; outlineSprite.anchor.set((O.pad + pxf * O.w) / (O.w + O.pad * 2), (O.pad + pyf * O.h) / (O.h + O.pad * 2)); outlineSprite.position.copyFrom(sprite.position); outlineSprite.scale.set(k / src.w, k / src.h); outlineSprite.rotation = sprite.rotation; }
      else outlineSprite.visible = false;
    }
    /** Pose a rig — the same maths as the painted world's drawBuddy, at unit size. */
    function poseRig(rig, o) {
      const idleBob = Math.sin(t * 1.6 + (o.phase || 0)) * 0.012, sway = reduced ? 0 : Math.sin(t * 0.8 + (o.phase || 0)) * 0.012;
      const left = -0.5 + sway, top = -1 - (o.bob || 0) - idleBob, day = theme === 'day';
      rig.c.alpha = o.alpha == null ? 1 : o.alpha;
      rig.glow.position.set(0, top + 0.5); rig.glow.scale.set(1.24 / 128); rig.glow.tint = hslHex((305 + (o.deg || 0)) % 360, 80, 62); rig.glow.alpha = o.glow ? 0.24 * o.glow * (day ? 1 : 0.66) * 1.6 : 0;
      rig.shadow.position.set(0, 0); rig.shadow.scale.set(0.48 / 64, 0.11 / 16); rig.shadow.alpha = 0.3;
      const bright = day ? 0xffffff : 0xe0e0e0;
      if (o.moving && buddyImg.walk) {
        rig.tail.visible = rig.gills.visible = rig.body.visible = rig.tailO.visible = rig.gillsO.visible = rig.bodyO.visible = false; rig.walkC.visible = true;
        const src = tinted('walk', o.deg), idx = ((o.walkAnim | 0) % 8 + 8) % 8, wc = o.walkAnim * Math.PI / 2, stride = reduced ? 0 : 1;
        const cw = src.w / 4, ch = src.h / 2, Hw = CAL.K * 1.04, fw = Hw * (cw / ch), bounce = stride * Hw * 0.035 * Math.abs(Math.sin(wc));
        const footY = -(o.bob || 0) - idleBob - (1 - CAL.botIdle), topw = footY - CAL.botWalk[idx] * Hw - bounce;
        const fs = o.faceScale == null ? (o.facing || 1) : o.faceScale, m = fs < 0 ? Math.min(fs, -0.16) : Math.max(fs, 0.16);
        rig.walkC.position.set(0, footY); rig.walkC.scale.set(m * (1 - 0.045 * Math.sin(wc) * stride), 1 + stride * 0.06 * Math.sin(wc));
        rig.walk.texture = frames(src, 'w' + o.deg)[idx]; rig.walk.anchor.set(0.5, 0); rig.walk.position.set(0, topw - footY); rig.walk.scale.set(fw / cw, Hw / ch); rig.walk.tint = bright;
        const O = day ? outline('walk') : null;
        if (O) { const och = O.h / 2; rig.walkO.visible = true; rig.walkO.texture = frames(O, 'wo', O.pad)[idx]; rig.walkO.anchor.set(0.5, O.pad / (och + O.pad * 2)); rig.walkO.position.copyFrom(rig.walk.position); rig.walkO.scale.copyFrom(rig.walk.scale); }
        else rig.walkO.visible = false;
      } else {
        rig.walkC.visible = false;
        layer(rig.tail, rig.tailO, 'tail', o.deg, 0.60, 0.42, 0.66, -0.06, 0.16, Math.sin(t * 1.7 + (o.phase || 0)) * 0.065, left, top);
        layer(rig.gills, rig.gillsO, 'gills', o.deg, 0.84, 0.50, 0.32, 0.0, -0.15, Math.sin(t * 2.3 + (o.phase || 0)) * 0.05, left, top);
        layer(rig.body, rig.bodyO, 'body', 0, 1, 0.5, 0.5, 0, 0, 0, left, top, o.closed);
        rig.body.tint = bright;
      }
      rig.gate.visible = !!o.gate; if (o.gate) { rig.gate.position.set(0, top + 0.2); rig.gate.scale.set(1.4 / 128); rig.gate.tint = hslHex(o.gate === 3 ? 12 : 45, 82, 64); rig.gate.alpha = 0.5; }
      rig.pip.clear(); if (o.pip != null) rig.pip.circle(0.3, top + 0.14, 0.045).fill({ color: o.pip, alpha: o.pipAlpha == null ? 1 : o.pipAlpha });
      return { top };
    }

    // entities: reconcile / place / wander — behaviour identical to the painted world
    const ents = new Map();
    function newEnt() { return { jx: 0, jy: 0, wtimer: Math.random() * 4, moving: false, facing: 1, faceVis: 1, walkAnim: 0, blinkT: Math.random() * 4, blinkOn: 0, blink: false, phase: Math.random() * 6.28, fade: 0, init: false, dying: false, dieT: 0 }; }
    function reconcile() {
      const seen = new Set();
      items.forEach(o => { const k = 'it:' + o.id; seen.add(k); let e = ents.get(k); if (!e) { e = Object.assign(newEnt(), { kind: 'item', o, jx: D.hash01(o.id + 'a') - 0.5, jy: D.hash01(o.id + 'b') - 0.5 }); ents.set(k, e); } e.o = o; });
      workforce.forEach(w => { if (w.role === 'orchestrator' && !w.run_id) return; const k = 'wk:' + w.worker_id; seen.add(k); let e = ents.get(k); if (!e) { e = Object.assign(newEnt(), { kind: 'worker', w, jx: D.hash01(w.worker_id + 'a') - 0.5, jy: D.hash01(w.worker_id + 'b') - 0.5 }); ents.set(k, e); } e.w = w; });
      for (const [k, e] of ents) if (!seen.has(k)) { if (e.kind === 'worker' && !e.dying) { e.dying = true; e.dieT = 0; } else if (e.kind === 'item') { if (e.view) e.view.c.destroy({ children: true }); ents.delete(k); } }
    }
    function stationOf(room, key) { const st = W.rooms[room].stations; return st[key] || st[Object.keys(st)[0]]; }
    function placeOf(e) {
      if (e.kind === 'item') {
        const o = e.o, room = roomOfState(o.state), spec = W.rooms[room];
        const dim = view.level === 'PROJECT' && view.proj && o.id !== view.proj;
        const key = spec.stateStation[o.state] || (D.STATE_STATION || {})[o.state];
        const st = stationOf(room, key); return { vis: true, dim, room, sx: st.x, sy: st.y };
      }
      const w = e.w, anchor = w.project ? items.find(x => x.id === w.project) : (w.idea ? items.find(x => x.id === w.idea) : null);
      const room = anchor ? roomOfState(anchor.state) : (view.level !== 'WORLD' ? view.room : ROOM_KEYS[0]);
      if (view.level === 'PROJECT') { if (w.project !== view.proj) return { vis: false }; }
      else if (view.level === 'REGION') { if (room !== view.room) return { vis: false }; }
      else if (w.project) return { vis: false };
      const spec = W.rooms[room]; if (!spec) return { vis: false };
      const key = spec.roleStation[w.role] || (D.ROLE_STATION || {})[w.role];
      const st = stationOf(room, key); return { vis: true, room, sx: st.x, sy: st.y, worker: true };
    }
    const samplePath = (P, u) => { const n = P.length; u = clamp(u, 0, n - 1); const i = Math.min(n - 2, Math.floor(u)), f = u - i; return { x: P[i][0] + (P[i + 1][0] - P[i][0]) * f, y: P[i][1] + (P[i + 1][1] - P[i][1]) * f }; };
    const nearestT = (P, x, y) => { let bi = 0, bd = 1e9; P.forEach((p, i) => { const d = (p[0] - x) ** 2 + (p[1] - y) ** 2; if (d < bd) { bd = d; bi = i; } }); return bi; };

    function updateEntities(dt) {
      reconcile();
      for (const [key, e] of ents) {
        const pl = placeOf(e); e._vis = !!pl.vis; e._dim = !!pl.dim; e._room = pl.room;
        if (!pl.vis) { if (e.view) e.view.c.visible = false; continue; }
        const P = W.rooms[pl.room].paths;
        if (e.pathInit && e._proom && e._proom !== pl.room && e.kind === 'item' && !reduced && roomObjs[e._proom]) {
          const b0 = BOX[e._proom]; e.travel = { x0: b0.x + e._nx * b0.w, y0: b0.y + e._ny * b0.h, u: 0 };
        }
        if (P && P.length > 1) {
          if (!e.pathInit || e._proom !== pl.room) { e.homeT = clamp(nearestT(P, pl.sx, pl.sy) + e.jx * 1.4, 0, P.length - 1); e.pt = e.homeT; e.targetT = e.homeT; e.pathInit = true; e._proom = pl.room; }
          const restless = (e.w && e.w.status === 'working') || (e.o && e.o.live);
          e.wtimer -= dt; if (e.wtimer < 0) { e.wtimer = (restless ? 1.4 : 2.4) + Math.random() * (restless ? 3.0 : 4.2); e.targetT = clamp(e.homeT + (Math.random() - 0.5) * (restless ? 4.2 : 3.2), 0, P.length - 1); }
          const dpt = e.targetT - e.pt; e.moving = !reduced && Math.abs(dpt) > 0.05;
          if (e.moving) { const step = Math.sign(dpt) * Math.min(Math.abs(dpt), dt * 1.25); e.pt += step; e.walkAnim += dt * 9; const p0 = samplePath(P, e.pt), p1 = samplePath(P, e.pt + 0.05 * Math.sign(step || 1)); e.facing = (p1.x - p0.x) < 0 ? -1 : 1; }
          e.faceVis = lerp(e.faceVis == null ? e.facing : e.faceVis, e.facing, Math.min(1, dt * 9));
          const pos = samplePath(P, e.pt); e._nx = pos.x; e._ny = pos.y;
        } else { e._nx = pl.sx; e._ny = pl.sy; e.moving = false; }
        e.blinkT -= dt; if (e.blinkT < 0) { e.blinkT = 2.6 + Math.random() * 3.6; e.blinkOn = 0.13; } if (e.blinkOn > 0) e.blinkOn -= dt; e.blink = !reduced && e.blinkOn > 0;
        if (e.dying) { e.dieT += reduced ? 1.0 : dt; if (e.dieT >= 1.0 && e.w) { if (e.view) e.view.c.destroy({ children: true }); ents.delete(key); continue; } }
        e.fade = lerp(e.fade, 1, dt * 3); if (!e.init) { e.fade = 1; e.init = true; }
        drawEntity(e, dt);
      }
    }
    function drawEntity(e, dt) {
      const R = roomObjs[e._room]; if (!R) return;
      const isItem = e.kind === 'item', o = e.o, w = e.w;
      const deg = isItem ? (o.dead ? 0 : D.projDeg(o.id)) : (() => { const a = w.project ? items.find(x => x.id === w.project) : (w.idea ? items.find(x => x.id === w.idea) : null); return D.projDeg(a ? a.id : (w.project || w.idea || w.worker_id)); })();
      if (!e.view || e.view.deg !== deg) { if (e.view) e.view.c.destroy({ children: true }); e.view = makeRig(deg); e.view.c.eventMode = 'none'; }
      const rig = e.view;
      const dieK = e.dying ? clamp(1 - e.dieT, 0, 1) : 1, depth = W.depthScale(e._ny);
      const s = BUDDY_WH * depth * (isItem ? (o.hasProject ? 1.05 : 0.9) : 0.8 * dieK);
      rig.c.visible = true; rig.c.scale.set(s);
      if (e.travel) {
        // hop along an arc from the old room to the new one, in world space, above everything
        e.travel.u = Math.min(1, e.travel.u + (dt || 1 / 60) / 1.3);
        const u = ease.inOut(e.travel.u), x1 = R.box.x + e._nx * R.rw, y1 = R.box.y + e._ny * R.rh;
        const lift = Math.min(900, Math.hypot(x1 - e.travel.x0, y1 - e.travel.y0) * 0.35 + 160);
        if (rig.c.parent !== travelC) travelC.addChild(rig.c);
        rig.c.position.set(lerp(e.travel.x0, x1, u), lerp(e.travel.y0, y1, u) - Math.sin(Math.PI * u) * lift);
        rig.c.rotation = Math.sin(Math.PI * u * 2) * 0.12;
        if (e.travel.u >= 1) { e.travel = null; rig.c.rotation = 0; }
      } else {
        if (rig.c.parent !== R.c) R.c.addChild(rig.c);
        rig.c.zIndex = e._ny * R.rh + 1;
        rig._baseX = e._nx * R.rw; rig.c.position.set(rig._baseX + parX * pz(e._ny), e._ny * R.rh);
      }
      const role = !isItem ? (D.ROLE_ORDER.includes(w.role) ? w.role : 'other') : null;
      const dimHL = (!isItem && highlightRole && highlightRole !== role) ? 0.5 : 1;
      let pip = null; if (!isItem) { const rc = D.roleHSL(role, 0); pip = hslHex(rc[0], Math.min(100, rc[1] + 16), Math.min(95, rc[2] + 8)); }
      const bob = isItem ? ((o.live && !e.moving) ? Math.abs(Math.sin(t * 3 + e.phase)) * 0.03 : 0) : ((w.status === 'working' && !e.moving) ? Math.abs(Math.sin(t * 2.5 + e.phase)) * 0.025 : 0);
      const r = poseRig(rig, { deg, glow: isItem ? (o.dead ? 0.12 : (o.live ? 1 : 0.55)) : (w.status === 'working' ? 0.85 : 0.4), alpha: isItem ? ((e._dim ? 0.55 : 1) * dieK * (o.dead ? 0.68 : 1)) : dimHL * (e.dying ? dieK : e.fade), closed: (e.blink || (isItem && o.parked)) && !e.moving, phase: e.phase, bob, moving: e.moving, walkAnim: e.walkAnim, facing: e.facing, faceScale: e.faceVis, gate: isItem ? o.gate : 0, pip, pipAlpha: dimHL });
      e._top = r.top;
    }

    // ── camera (ported: world units, fly/zoom, the visible band between the top bar and the HUD) ──
    const cam = { x: LAYOUT.bbox.cx, y: LAYOUT.bbox.cy, zoom: 0.2, q: [] };
    let camFrom = null, camT = 0, userT = -999;
    const view = { level: 'WORLD', room: null, proj: null, label: '' }, stack = [];
    const VIEWB = { top: 64, bot: 92, side: 20 };
    const SW = () => app.screen.width, SH = () => app.screen.height;
    const w2s = (wx, wy) => ({ x: SW() / 2 + (wx - cam.x) * cam.zoom, y: SH() / 2 + (wy - cam.y) * cam.zoom });
    const s2w = (sx, sy) => ({ x: cam.x + (sx - SW() / 2) / cam.zoom, y: cam.y + (sy - SH() / 2) / cam.zoom });
    const smoothstep = x => { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); };
    function flyTo(steps) { if (reduced) { const s = steps[steps.length - 1]; cam.x = s.x; cam.y = s.y; cam.zoom = s.zoom; cam.q = []; kick(); return; } cam.q = steps.slice(); camFrom = null; camT = 0; }
    function focusOn(x, y, zoom, cinematic) { if (cinematic && !reduced) flyTo([{ x: (cam.x + x) / 2, y: (cam.y + y) / 2, zoom: Math.min(cam.zoom, zoom) * 0.7, dur: 0.34 }, { x, y, zoom, dur: 0.6 }]); else flyTo([{ x, y, zoom, dur: 0.5 }]); }
    function camUpdate(dt) { if (!cam.q.length) return; const st = cam.q[0]; if (!camFrom) { camFrom = { x: cam.x, y: cam.y, zoom: cam.zoom }; camT = 0; } camT += dt / Math.max(0.0001, st.dur); const e = smoothstep(camT); cam.x = lerp(camFrom.x, st.x, e); cam.y = lerp(camFrom.y, st.y, e); cam.zoom = camFrom.zoom * Math.pow(st.zoom / camFrom.zoom, e); if (camT >= 1) { cam.x = st.x; cam.y = st.y; cam.zoom = st.zoom; cam.q.shift(); camFrom = null; camT = 0; } }
    function measureInsets() { try { const tb = document.querySelector('.topbar'); if (tb) { const h = tb.getBoundingClientRect().height; if (h > 4) VIEWB.top = Math.round(h) + 12; } const cb = document.querySelector('#commandBar'); if (cb) { const r = cb.getBoundingClientRect(); if (r.height > 4) VIEWB.bot = clamp(Math.round(SH() - r.top) + 14, 70, 260); } } catch (e) { /* keep defaults */ } }
    const bandCenterY = () => (VIEWB.top + (SH() - VIEWB.bot)) / 2;
    function frameBox(box, fill, maxZoom) { const bw = Math.max(160, SW() - VIEWB.side * 2), bh = Math.max(180, SH() - VIEWB.top - VIEWB.bot); const zoom = clamp(Math.min(bw / box.w, bh / box.h) * (fill || 1), 0.04, maxZoom || 2.4); return { x: box.x + box.w / 2, y: box.y + box.h / 2 + (SH() / 2 - bandCenterY()) / zoom, zoom }; }
    const worldBox = () => { const b = LAYOUT.bbox; return { x: b.x - 60, y: b.y - 420, w: b.w + 120, h: b.h + 480 }; };
    const worldFit = () => frameBox(worldBox(), 1.0, 0.6);
    function clampCam() { const b = worldBox(); cam.x = clamp(cam.x, b.x - 400, b.x + b.w + 400); cam.y = clamp(cam.y, b.y - 400, b.y + b.h + 400); }
    const roomLabel = k => (W.rooms[k] ? W.rooms[k].title : k);
    function fireView() { if (onView) onView(viewInfo()); }
    function fireFollow() { if (onFollow) onFollow(followId); }
    function viewInfo() { return { level: view.level, label: view.label }; }
    function goWorld() { followId = null; fireFollow(); view.level = 'WORLD'; view.room = null; view.proj = null; view.label = ''; stack.length = 0; userT = -999; measureInsets(); const f = worldFit(); focusOn(f.x, f.y, f.zoom, false); fireView(); }
    function goRegion(room, fromTab) { if (!BOX[room]) return; if (view.level === 'REGION' && view.room === room) return; if (!fromTab && view.level !== 'WORLD') stack.push({ ...view }); view.level = 'REGION'; view.room = room; view.proj = null; view.label = roomLabel(room); measureInsets(); const f = frameBox(BOX[room], 1.0); focusOn(f.x, f.y, f.zoom, true); popRoom(room, 0.25); fireView(); }
    function focusProject(id) { const o = items.find(x => x.id === id); if (!o) return; const room = roomOfState(o.state); if (view.level !== 'WORLD') stack.push({ ...view }); view.level = 'PROJECT'; view.room = room; view.proj = id; view.label = `${o.title || id} · its lab`; measureInsets(); const f = frameBox(BOX[room], 1.0); focusOn(f.x, f.y, f.zoom, true); popRoom(room, 0.25); fireView(); }
    function back() { followId = null; fireFollow(); if (stack.length) { const v = stack.pop(); Object.assign(view, v); measureInsets(); const f = v.level === 'WORLD' ? worldFit() : frameBox(BOX[v.room], 1.0); focusOn(f.x, f.y, f.zoom, true); fireView(); } else goWorld(); }
    function setView(mode) { if (mode === 'gates') { const g = items.find(o => o.gate); if (g) { goRegion(roomOfState(g.state), true); return; } } goWorld(); }
    function followWorker(id) {
      const w = workforce.find(x => x.worker_id === id); if (!w) return;
      const a = w.project ? items.find(x => x.id === w.project) : (w.idea ? items.find(x => x.id === w.idea) : null);
      if (w.project && a) focusProject(w.project); else if (a) goRegion(roomOfState(a.state)); else if (view.level === 'WORLD') goRegion(ROOM_KEYS[0]);
      followId = id; fireFollow();
    }
    function stopFollow() { if (followId !== null) { followId = null; fireFollow(); } }

    // ── room state for live bindings ─────────────────────────────────────────
    const roomState = {};
    function computeRoomStates() {
      for (const k of ROOM_KEYS) {
        const here = items.filter(o => roomOfState(o.state) === k), ids = new Set(here.map(o => o.id)), spec = W.rooms[k];
        const crew = workforce.filter(w => (w.project && ids.has(w.project)) || (w.idea && ids.has(w.idea)));
        const waiting = spec.gate ? items.filter(o => o.gate === spec.gate).length : 0;
        roomState[k] = { slotsCap: slots.cap || 0, slotsUse: slots.in_use || 0, busy: crew.filter(w => w.status === 'working').length, n: here.length,
          nActive: here.filter(o => o.state === 'active').length, nAnalysis: here.filter(o => o.state === 'analysis').length,
          gateWaiting: waiting, gateOpen: spec.gate !== 3 && !waiting, seed: here.length ? D.hash01(here.map(o => o.id).join()) * 6 : 1, load: (slots.in_use || 0) };
      }
    }

    // ── parallax (pointer-driven depth) ──────────────────────────────────────
    let parX = 0, parTX = 0, parY = 0, parTY = 0;
    const pz = ny => (ny - W.BOX.back) / (1 - W.BOX.back);   // 0 at the back wall → 1 at the front edge
    function updateProps(dt) {
      const vw = s2w(0, 0), ve = s2w(SW(), SH());
      for (const k of ROOM_KEYS) {
        const R = roomObjs[k]; if (!R) continue;
        const b = R.box, on = !(b.x > ve.x || b.x + b.w < vw.x || b.y > ve.y || b.y + b.h < vw.y);
        R.c.visible = on; if (!on) continue;
        const st = roomState[k] || {};
        for (const p of R.props) {
          p.c.x = p.baseX + parX * pz(p.ny);
          if (p.pop < 1) { if (p.popDelay > 0) p.popDelay -= dt; else p.pop = Math.min(1, p.pop + dt * 2.6); const e = ease.back(p.pop); p.c.scale.set(p.s, p.s * Math.max(0.02, e)); p.c.skew.x = (1 - p.pop) * 0.25; }
          else if (p.c.scale.y !== p.s) { p.c.scale.set(p.s); p.c.skew.x = 0; }
          for (const q of p.parts) {
            const a = q.p.anim || {}; let rot = 0, sx = 1;
            if (a.kind === 'sway') rot = reduced ? 0 : Math.sin(t * (a.speed || 1) * 2 + q.ph) * (a.amp || 0.03);
            else if (a.kind === 'spin') { if (!a.bind || st[a.bind]) q.spin += dt * (a.speed || 0.3) * 6.28; rot = q.spin; }
            else if (a.kind === 'bob') q.sp.y += 0;
            else if (a.kind === 'fold') { const target = st[a.bind] ? 0.16 : 1; q.fold = lerp(q.fold, target, Math.min(1, dt * 3)); sx = q.fold; }
            q.sp.rotation = rot; q.sp.scale.set(sx / p.b.res, 1 / p.b.res); if (q.gl) { q.gl.rotation = rot; q.gl.scale.copyFrom(q.sp.scale); }
          }
          for (const f of p.fx) f.update(dt, st);
        }
      }
    }

    // ── labels, hover, hits (screen space) ───────────────────────────────────
    let hits = [], hot = null;
    const labelPool = new Map();
    function label(key, text, x, y, size, color, alpha) {
      let tx = labelPool.get(key);
      if (!tx) { tx = new PIXI.Text({ text, style: { fontFamily: getFont(), fontSize: size, fontWeight: '600', fill: color, dropShadow: { color: 0x000000, alpha: 0.55, blur: 3, distance: 0 } } }); tx.anchor.set(0.5, 0); tx.resolution = 2; labelsC.addChild(tx); labelPool.set(key, tx); }
      if (tx.text !== text) tx.text = text;
      if (tx._fill !== color) { tx.style.fill = color; tx._fill = color; }
      tx.position.set(Math.round(x), Math.round(y)); tx.alpha = alpha; tx.visible = true; tx._seen = true;
    }
    /** A little paper tag (speech-label) with a pointer: used for what an agent is doing. */
    const tagPool = new Map();
    function tag(key, text, x, y, alpha) {
      const th = TH();
      let tg = tagPool.get(key);
      if (!tg) {
        tg = new PIXI.Container(); tg.g = new PIXI.Graphics();
        tg.t = new PIXI.Text({ text, style: { fontFamily: th.label.font, fontSize: 12, fontWeight: '700', fill: T.hexNum(th.label.color) } }); tg.t.anchor.set(0.5, 1); tg.t.resolution = 2;
        tg.addChild(tg.g, tg.t); labelsC.addChild(tg); tagPool.set(key, tg);
      }
      if (tg.t.text !== text || tg._theme !== theme) {
        tg.t.text = text; tg.t.style.fill = T.hexNum(th.label.color); tg.t.style.fontFamily = th.label.font;
        const w = tg.t.width + 14, h = tg.t.height + 4;
        tg.g.clear().roundRect(-w / 2, -h - 6, w, h, 6).fill({ color: T.hexNum(th.label.plate), alpha: 0.94 }).stroke({ width: 1, color: T.hexNum(th.ink.line), alpha: 0.5 })
          .moveTo(-5, -6).lineTo(0, 0).lineTo(5, -6).fill({ color: T.hexNum(th.label.plate), alpha: 0.94 });
        tg.t.position.set(0, -8); tg._theme = theme;
      }
      tg.position.set(Math.round(x), Math.round(y)); tg.alpha = alpha; tg.visible = true; tg._seen = true;
    }
    function drawScreen() {
      for (const tx of labelPool.values()) tx._seen = false;
      for (const tg of tagPool.values()) tg._seen = false;
      hits = [];
      const zoomedIn = cam.zoom > 0.42, day = theme === 'day';
      // furniture hover targets (only once a room is big enough to point at)
      for (const k of ROOM_KEYS) {
        const R = roomObjs[k]; if (!R || !R.c.visible) continue;
        const tl = w2s(R.box.x, R.box.y), br = w2s(R.box.x + R.box.w, R.box.y + R.box.h);
        if (br.x - tl.x < 480) { hits.push({ kind: 'room', room: k, rect: [tl.x, tl.y, br.x, br.y] }); continue; }
        for (const p of R.props) { if (!p.hoverable) continue; const a = w2s(p.rect.x, p.rect.y), b = w2s(p.rect.x + p.rect.w, p.rect.y + p.rect.h); hits.push({ kind: 'obj', room: k, prop: p, rect: [a.x, a.y, b.x, b.y] }); }
        hits.push({ kind: 'room', room: k, rect: [tl.x, tl.y, br.x, br.y] });
      }
      const top = [];
      for (const e of ents.values()) {
        if (!e._vis || !e.view || !e.view.c.visible || e.dying) continue;
        const R = roomObjs[e._room]; if (!R) continue;
        const s = e.view.c.scale.x, inRoom = e.view.c.parent === R.c, wx = (inRoom ? R.box.x : 0) + e.view.c.x, wy = (inRoom ? R.box.y : 0) + e.view.c.y, p = w2s(wx, wy), ss = s * cam.zoom;
        const cy = p.y + (e._top + 0.5) * ss;
        if (e.kind === 'item') {
          const o = e.o;
          if (!e._dim) top.push({ sx: p.x, sy: cy, r: Math.max(18, ss * 0.5), kind: 'item', id: o.id, name: o.title || o.id, ss });
          if (zoomedIn) { label('it:' + o.id, o.title || o.id, p.x, p.y + ss * 0.08, 13, day ? 0x3a2a16 : 0xf4ecd6, e._dim ? 0.6 : 0.97); if (o.hasProject && o.nWorkers && !(view.level === 'PROJECT' && view.proj === o.id)) label('in:' + o.id, `▸ ${o.nWorkers} inside`, p.x, p.y + ss * 0.08 + 17, 11, day ? 0x2f6f66 : 0xa8f0e6, e._dim ? 0.6 : 0.95); }
        } else {
          top.push({ sx: p.x, sy: cy, r: Math.max(16, ss * 0.5), kind: 'worker', id: e.w.worker_id, name: e.w.worker_id, ss });
          const act = zoomedIn && !e.dying ? actionText(e.w) : '';
          if (act) tag('act:' + e.w.worker_id, act, p.x, p.y + (e._top) * ss - 14, e.w.status === 'working' ? 1 : 0.65);
        }
      }
      hits = hits.concat(top);
      for (const [k, tx] of labelPool) if (!tx._seen) { tx.visible = false; if (labelPool.size > 120) { tx.destroy(); labelPool.delete(k); } }
      for (const [k, tg] of tagPool) if (!tg._seen) { tg.visible = false; if (tagPool.size > 60) { tg.destroy({ children: true }); tagPool.delete(k); } }
      drawNewt();
      // hover visuals
      hoverG.clear(); hoverT.visible = false;
      const h = hot && hits.find(x => x.kind === hot.kind && x.id === hot.id && x.prop === hot.prop && (x.kind !== 'room' || x.room === hot.room));
      if (h && (h.kind === 'item' || h.kind === 'worker' || h.kind === 'newt')) {
        hoverG.circle(h.sx, h.sy, Math.max(14, h.r * 1.04)).stroke({ width: 2, color: day ? 0x283448 : 0xb9e1e6, alpha: 0.7 });
        pill(h.name, h.sx, h.sy - Math.max(14, h.r) - 18);
      } else if (h && h.kind === 'obj') {
        const [x0, y0, x1, y1] = h.rect; const st = roomState[h.room] || {};
        hoverG.roundRect(x0, y0, x1 - x0, y1 - y0, 10).stroke({ width: 1.5, color: day ? 0x3c2c16 : 0xb9e1e6, alpha: 0.55 });
        const text = h.prop.def.hover(h.prop.props, st); if (text) pill(text, clamp((x0 + x1) / 2, 60, SW() - 60), Math.max(16, y0 - 16));
      }
      canvas.classList.toggle('is-hit', !!(h && h.kind !== 'room'));
    }
    /** "▸ run.py" / "edit model.py" — the worker's current tool, else its last action, short. */
    function actionText(w) {
      const cur = w.in_tool, last = (w.recent_actions || [])[w.recent_actions ? w.recent_actions.length - 1 : 0];
      let txt = cur ? (cur.summary || cur.tool || '') : (w.status === 'working' && last ? (last.text || '') : '');
      txt = String(txt).replace(/^[A-Z][a-zA-Z]+:\s*/, '').replace(/\s+/g, ' ').trim();
      if (!txt) return '';
      if (txt.length > 30) txt = txt.slice(0, 29) + '…';
      return (cur ? '▸ ' : '') + txt;
    }
    function pill(text, x, y) {
      const day = theme === 'day';
      if (hoverT.text !== text) hoverT.text = text;
      const fill = day ? 0x21242b : 0xe8f3f4; if (hoverT._fill !== fill) { hoverT.style.fill = fill; hoverT._fill = fill; }
      hoverT.position.set(Math.round(x), Math.round(y)); hoverT.visible = true;
      const w = hoverT.width + 18, h = 22; hoverG.roundRect(x - w / 2, y - h / 2, w, h, 7).fill({ color: day ? 0xffffff : 0x090e14, alpha: day ? 0.95 : 0.9 });
      screen.setChildIndex(hoverT, screen.children.length - 1);
    }

    // ── Newt (screen space, bottom centre — the orchestrator you talk to) ────
    const newt = { rig: null, blinkT: 0, blinkOn: 0, blink: false, glowP: 0.5, bounce: 0 };
    function drawNewt() {
      if (!newt.rig) { newt.rig = makeRig(0); newtC.addChild(newt.rig.c); newt.pool = new PIXI.Sprite(TEX.radial); newt.pool.anchor.set(0.5); newt.pool.blendMode = 'add'; newtC.addChildAt(newt.pool, 0); }
      const tp = (D.POSE_PARAMS || {})[pose] || { glow: 0.55, hue: 48 }, base = clamp(Math.min(SW(), SH()) * 0.2, 92, 168);
      const nx = SW() / 2, ny = SH() - 44 - newt.bounce * base * 0.12;
      newt.pool.position.set(nx, ny - base * 0.4); newt.pool.scale.set(base * 1.8 / 64, base * 0.9 / 64); newt.pool.tint = hslHex(tp.hue, 48, 60); newt.pool.alpha = 0.18 + 0.2 * newt.glowP;
      newt.rig.c.position.set(nx, ny); newt.rig.c.scale.set(base);
      const r = poseRig(newt.rig, { deg: 0, glow: 0.75 + newt.glowP * 0.5, closed: pose === 'sleep' || newt.blink, phase: 0.5 });
      hits.push({ sx: nx, sy: ny + (r.top + 0.5) * base, r: Math.max(44, base * 0.55), kind: 'newt', id: 'newt', name: 'Newt · orchestrator' });
    }
    function updateNewt(dt) {
      const tp = (D.POSE_PARAMS || {})[pose] || { glow: 0.55 };
      newt.bounce = lerp(newt.bounce, 0, dt * 2.4); newt.glowP = lerp(newt.glowP, tp.glow, dt * 2);
      newt.blinkT -= dt; if (newt.blinkT < 0) { newt.blinkT = 2 + Math.random() * 3; newt.blinkOn = 0.13; } if (newt.blinkOn > 0) newt.blinkOn -= dt; newt.blink = !reduced && newt.blinkOn > 0;
    }

    // ── the frame ────────────────────────────────────────────────────────────
    let lastW = 0, lastH = 0, fadeIn = 0;
    function frame(dt) {
      if (fadeIn > 0) { fadeIn = Math.max(0, fadeIn - dt * 2.5); world.alpha = 1 - fadeIn; }
      if (SW() !== lastW || SH() !== lastH) { lastW = SW(); lastH = SH(); paintBg(); }
      t += dt; camUpdate(dt);
      parX = lerp(parX, parTX, Math.min(1, dt * 4)); parY = lerp(parY, parTY, Math.min(1, dt * 4));
      if (followId && !cam.q.length) {
        const fe = ents.get('wk:' + followId);
        if (fe && fe._vis && roomObjs[fe._room]) { const b = BOX[fe._room], wx = b.x + fe._nx * b.w, wy = b.y + fe._ny * b.h, ty = wy + (SH() / 2 - bandCenterY()) / cam.zoom, k = Math.min(1, dt * 2.6); cam.x = lerp(cam.x, wx, k); cam.y = lerp(cam.y, ty, k); }
        else { followId = null; fireFollow(); }
      }
      if (view.level === 'WORLD' && !cam.q.length && (t - userT) > 4) { const f = worldFit(); if (Math.abs(f.zoom - cam.zoom) > 0.001 || Math.abs(f.x - cam.x) > 1 || Math.abs(f.y - cam.y) > 1) focusOn(f.x, f.y, f.zoom, false); }
      world.scale.set(cam.zoom); world.position.set(SW() / 2 - cam.x * cam.zoom, SH() / 2 - cam.y * cam.zoom);
      const bb = LAYOUT.bbox; backdropC.position.set((cam.x - bb.cx) * 0.35, (cam.y - bb.cy) * 0.35);
      computeRoomStates(); updateEntities(dt); updateProps(dt); updateAmbient(dt); updateNewt(dt); drawScreen();
    }
    const kick = () => { if (reduced) { frame(0.016); app.render(); } };
    app.ticker.add(tk => frame(Math.min(tk.deltaMS / 1000, 0.05)));

    // ── input ────────────────────────────────────────────────────────────────
    const toCanvas = ev => { const r = canvas.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; };
    function pick(p) {
      let best = null, bd = 1e9;
      for (const h of hits) { if (h.rect) continue; const d = Math.hypot(p.x - h.sx, p.y - h.sy); if (d < h.r && d < bd) { bd = d; best = h; } }
      if (best) return best;
      for (let i = hits.length - 1; i >= 0; i--) { const h = hits[i]; if (h.kind === 'obj' && inRect(p, h.rect)) return h; }
      for (let i = hits.length - 1; i >= 0; i--) { const h = hits[i]; if (h.kind === 'room' && inRect(p, h.rect)) return h; }
      return null;
    }
    const inRect = (p, r) => p.x >= r[0] && p.x <= r[2] && p.y >= r[1] && p.y <= r[3];
    let down = null, panned = false;
    canvas.addEventListener('pointerdown', ev => { down = toCanvas(ev); panned = false; try { canvas.setPointerCapture(ev.pointerId); } catch (e) { /* not capturable */ } });
    canvas.addEventListener('pointermove', ev => {
      const p = toCanvas(ev);
      parTX = (p.x / SW() - 0.5) * -18; parTY = (p.y / SH() - 0.5) * -8;
      if (down) { const dx = p.x - down.x, dy = p.y - down.y; if (panned || Math.hypot(dx, dy) > 6) { panned = true; if (followId !== null) { followId = null; fireFollow(); } cam.q = []; camFrom = null; cam.x -= dx / cam.zoom; cam.y -= dy / cam.zoom; clampCam(); down = p; userT = t; kick(); } }
      else { hot = pick(p); kick(); }
    });
    canvas.addEventListener('pointerleave', () => { hot = null; parTX = parTY = 0; kick(); });
    canvas.addEventListener('pointerup', ev => {
      const p = toCanvas(ev);
      if (down && !panned) {
        const h = pick(p);
        if (h && h.kind === 'item') { const o = items.find(x => x.id === h.id); if (o && o.has_project) { userT = t; focusProject(h.id); } else if (onItem) onItem(h.id); }
        else if (h && h.kind === 'worker') { if (onWorker) onWorker(h.id); }
        else if (h && h.kind === 'newt') { if (onNewt) onNewt(); }
        else if (h && h.kind === 'obj') {
          const act = h.prop.def.action, st = roomState[h.room] || {};
          if (view.level === 'WORLD') { userT = t; goRegion(h.room); }
          else if (act === 'slots' && D.runTool) D.runTool('slots');
          else if (act === 'gate' && st.gateWaiting && onGate && h.prop.props.gate !== 3) onGate(h.prop.props.gate);
          else if (D.toast) D.toast(h.prop.def.hover(h.prop.props, st));
        } else if (h && h.kind === 'room') { if (!(view.level !== 'WORLD' && view.room === h.room)) { userT = t; goRegion(h.room); } }
      }
      down = null; panned = false;
    });
    canvas.addEventListener('wheel', ev => { ev.preventDefault(); const p = toCanvas(ev), before = s2w(p.x, p.y); const k = ev.deltaY < 0 ? 1.14 : 1 / 1.14; cam.q = []; camFrom = null; cam.zoom = clamp(cam.zoom * k, 0.04, 2.6); const after = s2w(p.x, p.y); cam.x += before.x - after.x; cam.y += before.y - after.y; clampCam(); userT = t; if (followId !== null) { followId = null; fireFollow(); } kick(); }, { passive: false });
    window.addEventListener('resize', () => { measureInsets(); paintBg(); if (view.level === 'WORLD') { const f = worldFit(); cam.x = f.x; cam.y = f.y; cam.zoom = f.zoom; } kick(); });
    document.addEventListener('visibilitychange', () => { if (reduced) return; if (document.hidden) app.ticker.stop(); else app.ticker.start(); });

    // ── build ────────────────────────────────────────────────────────────────
    measureInsets();
    buildAll();
    { const f = worldFit(); cam.x = f.x; cam.y = f.y; cam.zoom = f.zoom; }
    kick();

    return {
      kind: 'pixi',
      sync(s) {
        items = (s.items || []).map(it => ({ id: it.id, title: it.title || it.id, state: it.state, has_project: !!it.has_project, hasProject: !!it.has_project, hasPaper: !!it.has_paper, gate: it.gate || 0, nWorkers: it.n_workers || 0, n_workers: it.n_workers || 0, loop_active: !!it.loop_active, inflight: it.inflight || [], live: (it.inflight || []).some(r => r.state !== 'stalled') && (it.inflight || []).length > 0, dead: it.state === 'killed', parked: it.state === 'parked' }));
        workforce = (s.workers || []).filter(w => w.status !== 'done'); slots = s.slots || slots;
        kick();
      },
      setPose(p) { if (p === pose) return; if (p === 'success') newt.bounce = 1; pose = p; kick(); },
      setLamp(th) { const next = th === 'day' ? 'day' : 'night'; if (next === theme) return; theme = next; buildAll(); if (!reduced) { world.alpha = 0; fadeIn = 1; } kick(); },
      setView(m) { setView(m); kick(); }, goRoom(k) { goRegion(k); kick(); }, focusProject(id) { focusProject(id); kick(); }, back() { back(); kick(); },
      viewInfo, highlight(r) { highlightRole = r; kick(); },
      layout() { return { boxes: ROOM_KEYS.map(k => ({ key: k, x: BOX[k].x, y: BOX[k].y, w: BOX[k].w, h: BOX[k].h, label: roomLabel(k), n: ROOM_KEYS.indexOf(k) + 1 })), bbox: LAYOUT.bbox, room: view.room, level: view.level }; },
      roomRect(k) { if (!BOX[k]) return null; const a = w2s(BOX[k].x, BOX[k].y), b = w2s(BOX[k].x + BOX[k].w, BOX[k].y + BOX[k].h); return { x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y }; },
      band() { return { top: VIEWB.top, bot: VIEWB.bot, W: SW(), H: SH() }; },
      setAmbient(on) { ambient = !!on; buildAmbient(); kick(); },
      followWorker(id) { followWorker(id); kick(); }, stopFollow() { stopFollow(); }, following() { return followId; },
      onClick(item, gate) { onItem = item; onGate = gate; }, onWorker(cb) { onWorker = cb; }, onNewt(cb) { onNewt = cb; }, onView(cb) { onView = cb; }, onFollow(cb) { onFollow = cb; },
      calInfo() { return CAL; },
      _debug: { app, cam, roomObjs, LAYOUT, timings, ents, rebuild: buildAll, step(dt, n) { for (let i = 0; i < (n || 1); i++) frame(dt || 0.05); app.render(); } },
    };
  };
})();
