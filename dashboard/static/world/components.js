/* Vivarium world — the COMPONENT library (the vocabulary rooms are built from).
 *
 *   VivWorld.defineComponent(name, {
 *     size(props)          → [w, h]   bounding box in world units; the anchor is bottom-centre (feet)
 *     draw(P, props)                  bake the static paper (P = paper painter; token colours only)
 *     parts?(props)        → [{ id, at:[x,y], size:[w,h], pivot:[px,py], draw(P,props), anim }]
 *                                     separately baked pieces the engine animates:
 *                                     anim = {kind:'sway'|'bob'|'spin'|'fold', amp, speed, bind}
 *     fx?(props)           → [{ kind, … }]   live effects in local coords (see engine.js FX):
 *                                     bubbles · steam · leds · screen · ring · flicker · clock · pulse · spark
 *     hover?(props, st)    → string   the live description shown on hover
 *     action?              → string   what a click does ('slots' · 'gate' · 'toast')
 *   })
 *
 * Rules of the design language (docs/world-design.md): everything is a paper piece (P.piece) with a
 * `lift` for depth; colours are tokens; shading is `hatch` (the painter turns it into cross-hatching by
 * day and a soft gradient by night); things that shine say `glow:` and nothing else.
 */
(function () {
  'use strict';
  const W = (window.VivWorld = window.VivWorld || {});
  const { rng } = W.noise;
  const T = W.tokens;
  const S = W.paper.S;
  const registry = {};
  W.components = registry;
  W.defineComponent = function (name, def) {
    if (!def || typeof def.draw !== 'function' || typeof def.size !== 'function') throw new Error(`component '${name}' needs size() and draw()`);
    registry[name] = Object.assign({ name }, def);
    return registry[name];
  };

  // ── shared drawing helpers (built on the painter) ────────────────────────────
  /** A piece of furniture seen from the front and a little above: top face + front face. */
  function box(P, x, y, w, front, top, o) {
    o = o || {};
    const inset = top * 0.35;
    P.piece(S.poly([[x + inset, y], [x + w - inset, y], [x + w, y + top], [x, y + top]]), { fill: o.top || 'wood.light', lift: o.lift == null ? 3 : o.lift, wash: o.washTop, ink: o.ink });
    P.piece(S.rect(x, y + top, w, front), { fill: o.front || 'wood.mid', lift: 0.6, hatch: o.hatch == null ? 0.35 : o.hatch, wash: o.wash, ink: o.ink, pattern: o.pattern });
    return { topY: y, frontY: y + top, bottom: y + top + front };
  }
  function drawers(P, x, y, w, h, n, o) {
    const dw = (w - 10) / n;
    for (let i = 0; i < n; i++) {
      const dx = x + 5 + i * dw;
      P.piece(S.rect(dx + 2, y + 5, dw - 4, h - 10), { fill: (o && o.fill) || 'wood.light', lift: 0.8, hatch: 0.18, deckle: 0.5 });
      P.piece(S.rrect(dx + dw / 2 - 8, y + 10, 16, 4, 2), { fill: 'metal.brass', lift: 0.6, deckle: 0.2, glow: o && o.knobGlow ? 'glow.warm' : null, glowAlpha: 0.4 });
    }
  }
  function legs(P, x, y, w, h, o) {
    for (const lx of [x + 6, x + w - 14]) P.piece(S.rect(lx, y, 8, h), { fill: (o && o.fill) || 'wood.dark', lift: 1.2, hatch: 0.3, deckle: 0.4 });
  }
  function papers(P, x, y, n, seed, spread) {
    const r = rng(seed);
    for (let i = 0; i < n; i++) {
      const px = x + (r() - 0.5) * (spread || 60), py = y + (r() - 0.5) * (spread || 60) * 0.35, a = (r() - 0.5) * 0.9, w = 22 + r() * 8, h = 14 + r() * 5;
      const c = Math.cos(a), s = Math.sin(a), pts = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]].map(([u, v]) => [px + u * c - v * s, py + (u * s + v * c) * 0.6]);
      P.piece(pts, { fill: 'paper.white', lift: 0.8, deckle: 0.3, inkW: 0.6 });
      P.line([[px - w * 0.3, py - 1.5], [px + w * 0.25, py - 1.5]], { w: 0.4, alpha: 0.6 });
      P.line([[px - w * 0.3, py + 1.5], [px + w * 0.15, py + 1.5]], { w: 0.4, alpha: 0.6 });
    }
  }
  function book(P, x, y, w, h, hue) {
    P.piece(S.rect(x, y - h, w, h), { fill: hue, lift: 0.8, deckle: 0.25, hatch: 0.25, hatchSide: 'right', inkW: 0.7 });
    P.line([[x + 1.5, y - h + 5], [x + w - 1.5, y - h + 5]], { w: 0.5, color: 'metal.brass' });
    P.line([[x + 1.5, y - 7], [x + w - 1.5, y - 7]], { w: 0.5, color: 'metal.brass' });
  }
  const BOOK_TONES = ['fabric.rug', 'wash.teal', 'fabric.rugAlt', 'wood.mid', 'plant.leafDark', 'fabric.seat', 'glass.rim'];
  function bookRow(P, x0, x1, y, seed, glowSome) {
    const r = rng(seed); let x = x0;
    while (x < x1 - 8) {
      const w = 6 + r() * 7, h = 22 + r() * 16;
      if (r() < 0.14) { x += 6; continue; }
      const tone = BOOK_TONES[Math.floor(r() * BOOK_TONES.length)];
      const fill = tone.startsWith('wash') ? 'paper.shade' : tone;
      if (r() < 0.12 && x + 30 < x1) {   // a small jar between books (some glow at night)
        P.piece(S.rrect(x + 2, y - 20, 14, 20, 4), { fill: 'glass.fill', lift: 0.8, deckle: 0.2, glow: glowSome ? 'glow.primary' : null, glowAlpha: 0.55 });
        x += 20; continue;
      }
      book(P, x, y, w, h, fill); x += w + 0.6;
    }
  }
  function plantAt(P, cx, by, size, kind, seed) {
    const r = rng(seed);
    if (kind === 'mushrooms') {
      for (let i = 0; i < 5; i++) {
        const mx = cx + (r() - 0.5) * size * 0.9, mh = size * (0.25 + r() * 0.35), cw = size * (0.16 + r() * 0.14);
        P.piece(S.rect(mx - cw * 0.14, by - mh, cw * 0.28, mh), { fill: 'plant.mushroom', lift: 0.8, deckle: 0.3, glow: 'glow.secondary', glowAlpha: 0.35 });
        P.piece(S.poly([[mx - cw, by - mh + 2], [mx + cw, by - mh + 2], [mx + cw * 0.5, by - mh - cw * 0.7], [mx - cw * 0.5, by - mh - cw * 0.7]]), { fill: 'plant.cap', lift: 1.2, deckle: 0.4, glow: 'glow.primary', glowAlpha: 0.8 });
      }
      return;
    }
    if (kind === 'sprout') {
      P.line([[cx, by], [cx + 2, by - size * 0.5], [cx, by - size]], { color: 'plant.stem', w: 1.4 });
      for (const [a, t] of [[-0.9, 0.55], [0.8, 0.75], [-0.3, 0.98]]) P.piece(S.leaf(cx, by - size * t, size * 0.42, size * 0.16, a - Math.PI / 2), { fill: 'plant.leafLight', lift: 1, deckle: 0.3, glow: 'glow.secondary', glowAlpha: 0.25 });
      return;
    }
    const n = kind === 'monstera' ? 7 : 11;
    for (let i = 0; i < n; i++) {
      const a = -Math.PI / 2 + (i / (n - 1) - 0.5) * (kind === 'monstera' ? 2.2 : 2.7) + (r() - 0.5) * 0.25;
      const len = size * (0.55 + r() * 0.45);
      const ex = cx + Math.cos(a) * len * 0.6, ey = by + Math.sin(a) * len * 0.6;
      P.line([[cx, by], [ex, ey]], { color: 'plant.stem', w: 1.1 });
      if (kind === 'monstera') P.piece(S.leaf(ex, ey, len * 0.62, len * 0.3, a + (r() - 0.5) * 0.4), { fill: r() < 0.5 ? 'plant.leaf' : 'plant.leafDark', lift: 1.6, hatch: 0.25, deckle: 0.6, pattern: (x, b) => { x.strokeStyle = T.alpha(P.tk('paper.shade'), 0.8); x.lineWidth = 2; for (let k = 1; k < 4; k++) { x.beginPath(); x.moveTo(b.x0 + b.w * k / 4, b.y0 + b.h / 2); x.lineTo(b.x0 + b.w * k / 4 + 6, b.y0); x.stroke(); } } });
      else for (let k = 1; k <= 7; k++) { const t = k / 8, px = cx + Math.cos(a) * len * t, py = by + Math.sin(a) * len * t, lw = size * 0.14 * Math.sin(Math.PI * (0.2 + t * 0.8)); for (const sd of [-1, 1]) P.piece(S.leaf(px, py, lw, lw * 0.36, a + sd * 1.0), { fill: k % 2 ? 'plant.leaf' : 'plant.leafLight', lift: 0.8, deckle: 0.25, ink: k % 3 === 0, inkW: 0.5 }); }
    }
  }

  // ── room furniture & apparatus ───────────────────────────────────────────────
  W.defineComponent('bench', {
    size: p => [p.w || 520, 170],
    draw(P, p) {
      const w = p.w || 520, top = 88;
      box(P, 0, top, w, 62, 18, { top: 'wood.dark', front: 'wood.mid' });
      drawers(P, 6, top + 20, w - 12, 50, Math.max(3, Math.round(w / 110)));
      let x = 30;
      for (const it of (p.items || ['flask', 'bell', 'rack'])) {
        drawItem(P, it, x, top + 6, p); x += (w - 60) / Math.max(1, (p.items || [1, 2, 3]).length);
      }
      if (p.label) plaque(P, w / 2, top + 26 + 38, p.label);
    },
    fx: p => {
      const w = p.w || 520, out = [], items = p.items || ['flask', 'bell', 'rack'];
      items.forEach((it, i) => { const x = 30 + i * (w - 60) / Math.max(1, items.length); if (it === 'flask') out.push({ kind: 'steam', at: [x + 20, 30], color: 'paper.white' }); if (it === 'burner') out.push({ kind: 'flicker', at: [x + 16, 84], r: 10, color: 'glow.warm' }); });
      return out;
    },
    hover: (p, st) => `${p.label || 'Bench'}${st && st.nActive != null ? ` · ${st.nActive} active project${st.nActive === 1 ? '' : 's'}` : ''}`,
  });
  function drawItem(P, it, x, baseY, p) {
    if (it === 'flask') {
      P.piece(S.poly([[x + 14, baseY - 54], [x + 26, baseY - 54], [x + 26, baseY - 36], [x + 40, baseY], [x, baseY], [x + 14, baseY - 36]]), { fill: 'glass.fill', lift: 1.4, deckle: 0.25, glow: 'glass.liquid2', glowAlpha: 0.25 });
      P.piece(S.poly([[x + 6, baseY - 16], [x + 34, baseY - 16], [x + 40, baseY], [x, baseY]]), { fill: 'glass.liquid2', lift: 0.3, deckle: 0.2, ink: false, glow: 'glass.liquid2', glowAlpha: 0.9 });
    } else if (it === 'bell') {
      P.piece(S.rrect(x - 4, baseY - 8, 56, 10, 4), { fill: 'wood.dark', lift: 1.2 });
      plantAt(P, x + 24, baseY - 8, 34, 'sprout', 5);
      P.piece(S.arch(x, baseY - 76, 48, 70), { fill: 'glass.fill', lift: 1.6, deckle: 0.2, glow: 'glass.rim', glowAlpha: 0.15, fibre: 0.3, pattern: x2 => { x2.globalAlpha = 0.5; } });
      P.line([[x + 10, baseY - 60], [x + 10, baseY - 20]], { color: 'paper.white', w: 2, alpha: 0.8 });
    } else if (it === 'rack') {
      P.piece(S.rect(x, baseY - 12, 58, 12), { fill: 'wood.light', lift: 1 });
      const tones = ['glass.liquid', 'glass.liquid2', 'glass.liquid3', 'glow.accent', 'glass.liquid'];
      tones.forEach((c, i) => { P.piece(S.rrect(x + 5 + i * 11, baseY - 44, 8, 38, 4), { fill: 'glass.fill', lift: 1, deckle: 0.15, inkW: 0.6 }); P.piece(S.rrect(x + 6 + i * 11, baseY - 22, 6, 16, 3), { fill: c, lift: 0.2, ink: false, glow: c, glowAlpha: 0.7 }); });
    } else if (it === 'microscope') {
      P.piece(S.rrect(x, baseY - 8, 44, 8, 3), { fill: 'metal.iron', lift: 1.2 });
      P.piece(S.poly([[x + 26, baseY - 8], [x + 34, baseY - 8], [x + 30, baseY - 60], [x + 22, baseY - 58]]), { fill: 'metal.steel', lift: 1.2, hatch: 0.3 });
      P.piece(S.poly([[x + 12, baseY - 70], [x + 22, baseY - 76], [x + 34, baseY - 42], [x + 24, baseY - 36]]), { fill: 'metal.brass', lift: 1.6 });
    } else if (it === 'notebook') {
      P.piece(S.poly([[x, baseY - 10], [x + 44, baseY - 14], [x + 48, baseY - 2], [x + 4, baseY + 2]]), { fill: 'fabric.seat', lift: 0.8 });
      P.piece(S.poly([[x + 3, baseY - 11], [x + 42, baseY - 14], [x + 45, baseY - 4], [x + 6, baseY]]), { fill: 'paper.white', lift: 0.4, deckle: 0.3 });
    } else if (it === 'burner') {
      P.piece(S.poly([[x + 8, baseY], [x + 24, baseY], [x + 20, baseY - 30], [x + 12, baseY - 30]]), { fill: 'metal.steel', lift: 1.2, hatch: 0.3 });
    } else if (it === 'scale') {
      P.piece(S.rect(x + 18, baseY - 50, 4, 44), { fill: 'metal.brass', lift: 1 }); P.piece(S.rect(x - 4, baseY - 50, 48, 3), { fill: 'metal.brass', lift: 1 });
      P.piece(S.ellipse(x, baseY - 30, 12, 4), { fill: 'metal.brassDark', lift: 1 }); P.piece(S.ellipse(x + 40, baseY - 34, 12, 4), { fill: 'metal.brassDark', lift: 1 });
    } else if (it === 'jars') {
      ['glass.liquid', 'glass.liquid3', 'glass.liquid2'].forEach((c, i) => { P.piece(S.rrect(x + i * 18, baseY - 30 - i * 4, 16, 30 + i * 4, 4), { fill: 'glass.fill', lift: 1, deckle: 0.2 }); P.piece(S.rrect(x + 2 + i * 18, baseY - 16, 12, 14, 3), { fill: c, lift: 0.2, ink: false, glow: c, glowAlpha: 0.8 }); });
    } else if (it === 'typewriter') {
      P.piece(S.poly([[x, baseY], [x + 60, baseY], [x + 52, baseY - 22], [x + 8, baseY - 22]]), { fill: 'metal.iron', lift: 1.6, hatch: 0.3 });
      P.piece(S.rect(x + 4, baseY - 34, 52, 10), { fill: 'metal.steel', lift: 1.2 });
      P.piece(S.rect(x + 14, baseY - 58, 32, 26), { fill: 'paper.white', lift: 1, deckle: 0.4 });
    } else if (it === 'quill') {
      P.piece(S.rrect(x, baseY - 16, 16, 16, 4), { fill: 'metal.iron', lift: 1 });
      P.piece(S.leaf(x + 8, baseY - 14, 46, 6, -1.2), { fill: 'paper.white', lift: 1.4, deckle: 0.6 });
    } else if (it === 'papers') papers(P, x + 24, baseY - 6, 5, Math.round(x));
    else if (it === 'lamp') { deskLamp(P, x + 10, baseY); }
    else if (it === 'mug') { P.piece(S.rrect(x, baseY - 22, 18, 22, 4), { fill: 'paper.white', lift: 1.2 }); }
  }
  function deskLamp(P, x, baseY) {
    P.piece(S.ellipse(x, baseY - 3, 14, 4), { fill: 'metal.brass', lift: 1 });
    P.line([[x, baseY - 3], [x + 6, baseY - 58], [x + 32, baseY - 78]], { color: 'metal.brassDark', w: 2.4 });
    P.piece(S.poly([[x + 24, baseY - 90], [x + 38, baseY - 90], [x + 52, baseY - 66], [x + 16, baseY - 66]]), { fill: 'plant.leafDark', lift: 1.6, hatch: 0.3 });
    P.piece(S.ellipse(x + 34, baseY - 66, 18, 3.5), { fill: 'paper.white', lift: 0.3, ink: false, glow: 'glow.warm', glowAlpha: 1 });
    P.glowSpot(x + 34, baseY - 40, 70, 'glow.warm', 0.55, 0.9);
  }
  function plaque(P, cx, cy, str, o) {
    o = o || {};
    const w = Math.max(64, str.length * (o.size || 11) * 0.62 + 20);
    P.piece(S.rrect(cx - w / 2, cy - 11, w, 22, 4), { fill: 'label.plate', lift: 1.2, deckle: 0.5, wash: o.wash || 'wash.ochre' });
    P.text(str, cx, cy + 0.5, { size: o.size || 11, weight: 700 });
  }
  W.plaque = plaque;

  W.defineComponent('vessel', {
    size: p => [p.w || 120, p.h || 300],
    draw(P, p) {
      const w = p.w || 120, h = p.h || 300, kind = p.kind || 'reactor', liq = p.liquid || 'glass.liquid';
      if (kind === 'reactor') {
        const r = w / 2 - 10;
        P.piece(S.poly([[4, h - 44], [w - 4, h - 44], [w, h], [0, h]]), { fill: 'metal.steel', lift: 2, hatch: 0.4 });
        P.piece(S.rrect(8, h - 62, w - 16, 20, 5), { fill: 'metal.brass', lift: 1.6 });
        P.piece(S.rrect(w / 2 - r, 40, r * 2, h - 100, 12), { fill: 'glass.fill', lift: 1.4, fibre: 0.4, glow: liq, glowAlpha: 0.25 });
        P.piece(S.rrect(w / 2 - r + 4, 84, r * 2 - 8, h - 148, 9), { fill: liq, lift: 0.2, ink: false, glow: liq, glowAlpha: 1 });
        // the coil inside
        const coil = []; for (let i = 0; i <= 40; i++) coil.push([w / 2 + Math.sin(i * 0.55) * r * 0.45, 96 + i * (h - 172) / 40]);
        P.line(coil, { color: 'paper.shade', w: 2.2 });
        P.piece(S.rrect(4, 22, w - 8, 24, 6), { fill: 'metal.brass', lift: 2, hatch: 0.25 });
        P.piece(S.rect(w / 2 - 5, 0, 10, 26), { fill: 'metal.brassDark', lift: 1 });
        P.line([[w / 2 - r + 10, 60], [w / 2 - r + 10, h - 80]], { color: 'paper.white', w: 3, alpha: 0.7 });
        P.glowSpot(w / 2, h * 0.55, w * 1.4, liq, 0.6, 1.3);
        if (p.label) plaque(P, w / 2, h - 22, p.label, { size: 10 });
      } else if (kind === 'tank') {
        P.piece(S.rrect(0, h * 0.15, w, h * 0.85, 10), { fill: 'glass.fill', lift: 2, glow: liq, glowAlpha: 0.2 });
        P.piece(S.rrect(6, h * 0.35, w - 12, h * 0.6, 8), { fill: liq, lift: 0.2, ink: false, glow: liq, glowAlpha: 0.9 });
        plantAt(P, w * 0.35, h * 0.93, h * 0.45, 'fern', 3);
        P.piece(S.rect(-4, h * 0.12, w + 8, 12), { fill: 'metal.iron', lift: 1.4 });
      } else {   // cloche / jar
        P.piece(S.rrect(w * 0.1, h - 12, w * 0.8, 12, 4), { fill: 'wood.dark', lift: 1.4 });
        plantAt(P, w / 2, h - 12, h * 0.55, p.plant || 'sprout', w);
        P.piece(S.arch(w * 0.14, h * 0.18, w * 0.72, h * 0.8), { fill: 'glass.fill', lift: 1.6, fibre: 0.3, glow: 'glass.rim', glowAlpha: 0.12 });
      }
    },
    fx: p => {
      const w = p.w || 120, h = p.h || 300;
      if ((p.kind || 'reactor') === 'reactor') return [{ kind: 'bubbles', rect: [w / 2 - w / 2 + 16, 90, w - 32, h - 160], color: 'paper.white', bind: 'load' }, { kind: 'flicker', at: [w / 2, h * 0.5], r: w * 0.9, color: p.liquid || 'glass.liquid', amp: 0.18 }];
      if (p.kind === 'tank') return [{ kind: 'bubbles', rect: [10, h * 0.4, w - 20, h * 0.5], color: 'paper.white' }];
      return [];
    },
    hover: (p, st) => p.hover ? p.hover(st || {}) : (p.label || 'Vessel'),
  });

  W.defineComponent('desk', {
    size: p => [p.w || 320, 240],
    draw(P, p) {
      const w = p.w || 320, top = 150;
      legs(P, 4, top + 18, w - 8, 72);
      box(P, 0, top, w, 34, 16, { top: 'wood.light', front: 'wood.mid' });
      drawers(P, w - 130, top + 16, 122, 34, 2);
      const mon = p.monitors || 0;
      for (let i = 0; i < mon; i++) {
        const mw = Math.min(118, (w - 60) / mon - 10), mx = 30 + i * (mw + 14), my = top - 92;
        P.piece(S.rect(mx + mw / 2 - 4, my + 66, 8, 22), { fill: 'metal.iron', lift: 1 });
        P.piece(S.rrect(mx - 5, my - 5, mw + 10, 76, 5), { fill: 'metal.iron', lift: 2.2 });
        P.piece(S.rect(mx, my, mw, 66), { fill: 'paper.deep', lift: 0.2, ink: false, glow: 'glow.screen', glowAlpha: 0.35 });
      }
      let x = 26 + mon * 128;
      for (const it of (p.items || [])) { drawItem(P, it, x, top + 4, p); x += 64; }
      if (p.lamp) deskLamp(P, 16, top + 4);
      if (p.chair) chair(P, w - 60, 240);
      if (p.label) plaque(P, w / 2, top + 36, p.label);
    },
    fx: p => { const out = [], mon = p.monitors || 0, w = p.w || 320; for (let i = 0; i < mon; i++) { const mw = Math.min(118, (w - 60) / mon - 10); out.push({ kind: 'screen', rect: [30 + i * (mw + 14), 58, mw, 66], mode: 'code', bind: 'busy' }); } if (p.lamp) out.push({ kind: 'flicker', at: [50, 104], r: 60, color: 'glow.warm', amp: 0.06 }); return out; },
    hover: (p, st) => `${p.label || 'Desk'}${st && st.busy ? ` · ${st.busy} agent${st.busy === 1 ? '' : 's'} working` : ' · quiet'}`,
  });
  function chair(P, cx, by) {
    P.piece(S.rect(cx - 3, by - 44, 6, 40), { fill: 'metal.iron', lift: 1 });
    P.piece(S.ellipse(cx, by - 46, 30, 9), { fill: 'fabric.seat', lift: 2, hatch: 0.2 });
    P.piece(S.rrect(cx - 24, by - 118, 48, 64, 12), { fill: 'fabric.seat', lift: 2.4, hatch: 0.35 });
    P.line([[cx - 26, by - 2], [cx + 26, by - 2]], { w: 2.4, color: 'metal.iron' });
  }

  W.defineComponent('console', {
    size: p => [p.w || 440, 280],
    draw(P, p) {
      const w = p.w || 440, top = 190;
      P.piece(S.poly([[0, top], [w, top], [w - 10, top + 70], [10, top + 70]]), { fill: 'wood.mid', lift: 2.6, hatch: 0.35 });
      P.piece(S.poly([[8, top - 16], [w - 8, top - 16], [w, top], [0, top]]), { fill: 'wood.dark', lift: 1.4 });
      drawers(P, 20, top + 12, w - 40, 44, 4);
      P.piece(S.rect(w / 2 - 6, top - 60, 12, 46), { fill: 'metal.iron', lift: 1 });
      P.piece(S.poly([[10, 20], [w / 2, 34], [w - 10, 20], [w - 10, 128], [w / 2, 142], [10, 128]]), { fill: 'metal.iron', lift: 3 });
      P.piece(S.poly([[20, 30], [w / 2, 43], [w - 20, 30], [w - 20, 120], [w / 2, 133], [20, 120]]), { fill: 'paper.deep', lift: 0.2, ink: false, glow: 'glow.screen', glowAlpha: 0.4 });
      P.piece(S.rrect(w / 2 - 70, top - 12, 140, 10, 3), { fill: 'metal.iron', lift: 0.8 });
      if (p.label) plaque(P, w / 2, top + 58, p.label);
    },
    fx: p => [{ kind: 'screen', rect: [24, 38, (p.w || 440) - 48, 88], mode: 'chart', bind: 'analysis' }],
    hover: (p, st) => `${p.label || 'Console'}${st && st.nAnalysis != null ? ` · ${st.nAnalysis} in analysis` : ''}`,
  });

  W.defineComponent('table', {
    size: p => [p.w || 300, 170],
    draw(P, p) {
      const w = p.w || 300, rx = w / 2 - 20, cy = 90;
      const stools = p.stools == null ? 4 : p.stools;
      const seat = a => { const sx = w / 2 + Math.cos(a) * (rx + 20), sy = cy + 40 + Math.sin(a) * 30; P.piece(S.rect(sx - 3, sy - 30, 6, 30), { fill: 'wood.dark', lift: 1 }); P.piece(S.ellipse(sx, sy - 32, 17, 6), { fill: 'wood.light', lift: 1.6, hatch: 0.2 }); };
      const angs = Array.from({ length: stools }, (_, i) => Math.PI * (1.15 + i * 0.7 / Math.max(1, stools - 1)) + (i % 2) * 0.1);
      angs.filter(a => Math.sin(a) < 0).forEach(seat);
      P.piece(S.rect(w / 2 - 8, cy, 16, 64), { fill: 'wood.dark', lift: 1.4, hatch: 0.3 });
      P.piece(S.ellipse(w / 2, cy + 64, 36, 9), { fill: 'wood.dark', lift: 1 });
      if (p.kind === 'rect') P.piece(S.poly([[20, cy - 22], [w - 20, cy - 22], [w, cy + 8], [0, cy + 8]]), { fill: 'wood.light', lift: 3, wash: 'wash.ochre' });
      else { P.piece(S.ellipse(w / 2, cy + 6, rx + 2, 34), { fill: 'wood.dark', lift: 3 }); P.piece(S.ellipse(w / 2, cy, rx, 30), { fill: 'wood.light', lift: 0.8, wash: 'wash.ochre' }); }
      if (p.papers !== false) papers(P, w / 2, cy - 2, 6, w, rx * 1.2);
      if (p.lamp) { P.piece(S.rect(w / 2 + 20, cy - 42, 3, 40), { fill: 'metal.brass', lift: 1 }); P.piece(S.poly([[w / 2 + 10, cy - 42], [w / 2 + 34, cy - 42], [w / 2 + 40, cy - 58], [w / 2 + 4, cy - 58]]), { fill: 'paper.light', lift: 1.4, glow: 'glow.warm', glowAlpha: 0.8 }); P.glowSpot(w / 2 + 22, cy - 20, 110, 'glow.warm', 0.5, 0.7); }
      angs.filter(a => Math.sin(a) >= 0).forEach(seat);
    },
    fx: p => p.lamp ? [{ kind: 'flicker', at: [(p.w || 300) / 2 + 22, 50], r: 70, color: 'glow.warm', amp: 0.08 }] : [],
    hover: p => p.label || 'Table',
  });

  W.defineComponent('board', {
    size: p => [p.w || 240, p.h || 250],
    draw(P, p) {
      const w = p.w || 240, h = p.h || 250, bh = h * 0.6, kind = p.kind || 'white';
      if (p.legs !== false) { P.line([[26, bh], [8, h]], { w: 3, color: 'wood.dark' }); P.line([[w - 26, bh], [w - 8, h]], { w: 3, color: 'wood.dark' }); P.line([[w / 2, bh], [w / 2, h - 10]], { w: 3, color: 'wood.dark' }); }
      const face = kind === 'cork' ? 'wood.light' : kind === 'chalk' ? 'plant.leafDark' : 'paper.white';
      P.piece(S.rect(0, 0, w, bh), { fill: 'wood.dark', lift: 3, hatch: 0.2 });
      P.piece(S.rect(8, 8, w - 16, bh - 16), { fill: face, lift: 0.4, wash: kind === 'cork' ? 'wash.ochre' : null, pattern: kind === 'cork' ? (x, b) => { x.fillStyle = T.alpha(P.tk('wood.dark'), 0.25); const r = rng(9); for (let i = 0; i < 220; i++) x.fillRect(b.x0 + r() * b.w, b.y0 + r() * b.h, 1.4, 1.4); } : null });
      const ink = kind === 'chalk' ? 'paper.white' : 'ink.blue', r = rng(w + h);
      if (kind === 'rank') {
        for (let i = 0; i < 5; i++) { P.text(`${i + 1}.`, 26, 30 + i * 22, { size: 12, color: ink }); P.line([[40, 32 + i * 22], [40 + (w - 80) * (1 - i * 0.15), 32 + i * 22]], { color: ink, w: 1.2 }); }
      } else {
        P.piece(S.rrect(22, 26, 52, 26, 5), { fill: face, lift: 0, ink: true, inkColor: ink, deckle: 0.3 });
        P.piece(S.rrect(104, 22, 52, 26, 5), { fill: face, lift: 0, inkColor: ink, deckle: 0.3 });
        P.piece(S.rrect(104, 70, 52, 26, 5), { fill: face, lift: 0, inkColor: ink, deckle: 0.3 });
        P.line([[74, 40], [104, 34]], { color: ink }); P.line([[74, 40], [104, 84]], { color: ink });
        P.line([[20, bh - 36], [50, bh - 56], [80, bh - 30], [110, bh - 50]], { color: 'ink.red' });
      }
      const notes = ['wash.ochre', 'wash.rose', 'wash.teal', 'wash.green'];
      for (let i = 0; i < (p.notes == null ? 4 : p.notes); i++) { const nx = w - 70 + (r() - 0.5) * 50, ny = 24 + i * (bh - 60) / 4 + r() * 6; P.piece(S.rect(nx, ny, 24, 22), { fill: 'paper.white', lift: 1.4, deckle: 0.4, wash: notes[i % 4], ink: false }); P.line([[nx + 4, ny + 8], [nx + 18, ny + 8]], { w: 0.5 }); P.line([[nx + 4, ny + 13], [nx + 14, ny + 13]], { w: 0.5 }); }
      if (p.label) plaque(P, w / 2, -16, p.label);
    },
    hover: p => p.label || 'Board',
  });

  W.defineComponent('bookcase', {
    size: p => [p.w || 260, p.h || 380],
    draw(P, p) {
      const w = p.w || 260, h = p.h || 380, rows = p.rows || 5;
      P.piece(S.rect(0, 0, w, h), { fill: 'wood.dark', lift: 3, hatch: 0.3 });
      P.piece(S.rect(10, 12, w - 20, h - 24), { fill: 'wood.grain', lift: 0, ink: false });
      const rh = (h - 24) / rows;
      for (let i = 0; i < rows; i++) {
        const y = 12 + (i + 1) * rh;
        bookRow(P, 14, w - 14, y - 4, (p.seed || 3) + i * 13, p.glowJars !== false);
        P.piece(S.rect(8, y - 4, w - 16, 7), { fill: 'wood.mid', lift: 1.2, deckle: 0.3 });
      }
      if (p.ladder) { P.line([[w - 30, h + 4], [w - 60, -10]], { w: 3.2, color: 'wood.light' }); P.line([[w + 4, h + 4], [w - 26, -10]], { w: 3.2, color: 'wood.light' }); for (let k = 1; k < 9; k++) { const t = k / 9; P.line([[w - 30 - 30 * t + 2, h + 4 - (h + 14) * t], [w + 4 - 30 * t - 2, h + 4 - (h + 14) * t]], { w: 2.4, color: 'wood.light' }); } }
      if (p.label) plaque(P, w / 2, -14, p.label);
    },
    hover: p => p.label || 'Bookcase',
  });

  W.defineComponent('rack', {
    size: p => [p.w || 170, p.h || 320],
    draw(P, p) {
      const w = p.w || 170, h = p.h || 320;
      P.piece(S.rect(0, 0, w, h), { fill: 'metal.iron', lift: 3, hatch: 0.4 });
      for (let y = 14, u = 0; y < h - 30; y += 28, u++) {
        P.piece(S.rrect(12, y, w - 24, 24, 2), { fill: u % 3 === 1 ? 'metal.steel' : 'paper.deep', lift: 0.6, deckle: 0.2 });
        for (let vx = 18; vx < 56; vx += 5) P.line([[vx, y + 5], [vx, y + 19]], { w: 0.7, alpha: 0.7 });
      }
      P.piece(S.rrect(w / 2 - 44, -18, 88, 20, 3), { fill: 'label.plate', lift: 1.4, wash: 'wash.ochre' });
      P.text(p.label || 'COMPUTE', w / 2, -8, { size: 10, weight: 700 });
      for (let k = 0; k < 3; k++) P.line([[30 + k * 30, 0], [40 + k * 30, -60], [20 + k * 40, -140]], { w: 3, color: 'metal.iron' });
    },
    fx: p => [{ kind: 'leds', at: [(p.w || 170) - 44, 22], step: 28, bind: 'slots' }],
    hover: (p, st) => `Compute · ${(st && st.slotsUse) || 0} of ${(st && st.slotsCap) || '?'} slot${st && st.slotsCap === 1 ? '' : 's'} in use`,
    action: 'slots',
  });

  W.defineComponent('dais', {
    size: p => [p.w || 300, 180],
    draw(P, p) {
      const w = p.w || 300, rx = w / 2 - 6, cy = 140;
      P.piece(S.ellipse(w / 2, cy + 8, rx, 34), { fill: 'surface.section', lift: 2.6, hatch: 0.3 });
      P.piece(S.ellipse(w / 2, cy, rx, 32), { fill: 'paper.card', lift: 0.8, pattern: (x, b) => { x.strokeStyle = P.tk('metal.brass'); x.lineWidth = 2; for (const k of [0.92, 0.66, 0.4]) { x.beginPath(); x.ellipse(w / 2, cy, rx * k, 32 * k, 0, 0, 6.2832); x.stroke(); } } });
      P.piece(S.rect(w / 2 - 12, cy - 70, 24, 70), { fill: 'metal.brass', lift: 1.6, hatch: 0.3 });
      P.piece(S.circle(w / 2, cy - 88, 20), { fill: 'glass.fill', lift: 1.6, glow: 'glow.primary', glowAlpha: 0.9 });
      P.glowSpot(w / 2, cy - 60, 150, 'glow.primary', 0.45, 0.9);
      if (p.label) plaque(P, w / 2, cy + 30, p.label);
    },
    fx: p => [{ kind: 'ring', center: [(p.w || 300) / 2, 140], rx: ((p.w || 300) / 2 - 6) * 0.78, ry: 25, color: 'glow.primary' }],
    hover: p => p.label || 'Quality check · the overseer audits claims here',
  });

  W.defineComponent('trays', {
    size: p => [p.w || 320, 150],
    draw(P, p) {
      const w = p.w || 320, rows = p.rows || 2;
      legs(P, 0, 60, w, 90);
      for (let r = 0; r < rows; r++) {
        const y = 60 - r * 34, inset = r * 16;
        P.piece(S.poly([[inset, y], [w - inset, y], [w - inset - 8, y + 20], [inset + 8, y + 20]]), { fill: 'wood.mid', lift: 2, hatch: 0.25 });
        const n = Math.floor((w - inset * 2 - 20) / 26);
        for (let i = 0; i < n; i++) plantAt(P, inset + 18 + i * 26, y + 4, 22 + ((i * 7 + r * 3) % 5) * 4, 'sprout', i * 31 + r);
      }
      if (p.label) plaque(P, w / 2, 110, p.label);
    },
    hover: p => p.label || 'Seed trays',
  });

  W.defineComponent('lectern', {
    size: () => [120, 200],
    draw(P, p) {
      P.piece(S.poly([[40, 190], [80, 190], [70, 70], [50, 70]]), { fill: 'wood.dark', lift: 2, hatch: 0.35 });
      P.piece(S.poly([[0, 60], [120, 40], [120, 70], [0, 90]]), { fill: 'wood.mid', lift: 2.4 });
      P.piece(S.poly([[8, 56], [60, 46], [60, 66], [8, 78]]), { fill: 'paper.white', lift: 1, deckle: 0.4 });
      P.piece(S.poly([[60, 46], [112, 38], [112, 58], [60, 66]]), { fill: 'paper.white', lift: 1, deckle: 0.4 });
      for (let i = 0; i < 4; i++) { P.line([[14, 60 + i * 4], [54, 52 + i * 4]], { w: 0.5 }); P.line([[66, 50 + i * 4], [106, 44 + i * 4]], { w: 0.5 }); }
      if (p.label) plaque(P, 60, 130, p.label, { size: 10 });
    },
    hover: p => p.label || 'Lectern',
  });

  W.defineComponent('easel', {
    size: () => [180, 260],
    draw(P, p) {
      P.line([[30, 250], [90, 0]], { w: 4, color: 'wood.dark' }); P.line([[150, 250], [90, 0]], { w: 4, color: 'wood.dark' }); P.line([[90, 250], [90, 60]], { w: 3, color: 'wood.dark' });
      P.piece(S.rect(16, 40, 148, 120), { fill: 'paper.white', lift: 2.4, deckle: 0.6 });
      const bars = [0.4, 0.7, 0.55, 0.9, 0.65];
      bars.forEach((v, i) => P.piece(S.rect(30 + i * 26, 146 - v * 90, 18, v * 90), { fill: 'paper.shade', lift: 0.4, wash: ['wash.teal', 'wash.ochre', 'wash.rose', 'wash.teal', 'wash.green'][i], inkW: 0.6 }));
      P.piece(S.rect(20, 160, 140, 8), { fill: 'wood.dark', lift: 1.4 });
      if (p.label) plaque(P, 90, 200, p.label, { size: 10 });
    },
    hover: p => p.label || 'Figures',
  });

  W.defineComponent('cabinet', {
    size: p => [p.w || 200, p.h || 220],
    draw(P, p) {
      const w = p.w || 200, h = p.h || 220, kind = p.kind || 'catalog';
      P.piece(S.rect(0, 0, w, h), { fill: kind === 'safe' ? 'metal.iron' : 'wood.mid', lift: 3, hatch: 0.35 });
      if (kind === 'safe') {
        P.piece(S.rect(14, 14, w - 28, h - 28), { fill: 'metal.steel', lift: 1, hatch: 0.3 });
        P.piece(S.circle(w / 2, h / 2, 26), { fill: 'metal.brass', lift: 1.6 });
        for (let i = 0; i < 6; i++) { const a = i / 6 * 6.28; P.line([[w / 2, h / 2], [w / 2 + Math.cos(a) * 22, h / 2 + Math.sin(a) * 22]], { w: 2, color: 'metal.brassDark' }); }
      } else {
        const cols = Math.max(2, Math.round(w / 48)), rows = Math.max(3, Math.round(h / 42)), cw = (w - 16) / cols, ch = (h - 16) / rows;
        for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) { const x = 8 + c * cw, y = 8 + r * ch; P.piece(S.rect(x + 2, y + 2, cw - 4, ch - 4), { fill: 'wood.light', lift: 0.7, deckle: 0.3 }); P.piece(S.rect(x + cw / 2 - 7, y + ch / 2 - 4, 14, 7), { fill: 'label.plate', lift: 0.4, deckle: 0.2, inkW: 0.5 }); }
      }
      if (p.label) plaque(P, w / 2, -14, p.label);
    },
    hover: p => p.label || 'Cabinet',
  });

  W.defineComponent('press', {
    size: () => [240, 260],
    draw(P, p) {
      P.piece(S.rect(20, 40, 24, 200), { fill: 'metal.iron', lift: 2.4, hatch: 0.4 });
      P.piece(S.rect(196, 40, 24, 200), { fill: 'metal.iron', lift: 2.4, hatch: 0.4 });
      P.piece(S.rect(10, 20, 220, 30), { fill: 'metal.iron', lift: 2.6, hatch: 0.3 });
      P.piece(S.rect(40, 150, 160, 24), { fill: 'wood.dark', lift: 2 });
      P.piece(S.rect(60, 120, 120, 30), { fill: 'paper.white', lift: 1.4, deckle: 0.6 });
      P.piece(S.rect(0, 220, 240, 30), { fill: 'wood.mid', lift: 2.6, hatch: 0.3 });
      if (p.label) plaque(P, 120, 236, p.label, { size: 10 });
    },
    parts: () => [{ id: 'wheel', at: [120 - 44, 36 - 44], size: [88, 88], pivot: [44, 44], anim: { kind: 'spin', speed: 0.25, bind: 'busy' },
      draw(P) { P.piece(S.circle(44, 44, 40), { fill: 'metal.brass', lift: 1.6, pattern: x => { x.globalCompositeOperation = 'destination-out'; x.beginPath(); x.arc(44, 44, 30, 0, 6.2832); x.fill(); } }); for (let i = 0; i < 8; i++) { const a = i / 8 * 6.28; P.line([[44, 44], [44 + Math.cos(a) * 38, 44 + Math.sin(a) * 38]], { w: 3, color: 'metal.brassDark' }); } P.piece(S.circle(44, 44, 8), { fill: 'metal.brassDark', lift: 1 }); } }],
    hover: p => p.label || 'Printing press',
  });

  W.defineComponent('boxes', {
    size: p => [p.w || 220, p.h || 200],
    draw(P, p) {
      const w = p.w || 220, h = p.h || 200, r = rng(w * 3 + h);
      let y = h;
      for (let row = 0; y > 40; row++) {
        const bh = 40 + r() * 16; let x = row * 10;
        while (x < w - 50 - row * 10) { const bw = 56 + r() * 30; P.piece(S.rect(x, y - bh, bw, bh), { fill: r() < 0.5 ? 'paper.card' : 'paper.shade', lift: 2, hatch: 0.25, hatchSide: 'right', wash: r() < 0.3 ? 'wash.ochre' : null }); P.piece(S.rect(x + bw / 2 - 12, y - bh + 10, 24, 12), { fill: 'label.plate', lift: 0.5, inkW: 0.6 }); x += bw + 4; }
        y -= bh + 2;
      }
      if (p.label) plaque(P, w / 2, h + 14, p.label);
    },
    hover: p => p.label || 'Boxes',
  });

  W.defineComponent('armchair', {
    size: () => [170, 170],
    draw(P) {
      P.piece(S.rrect(20, 20, 130, 110, 30), { fill: 'fabric.seat', lift: 3, hatch: 0.35 });
      P.piece(S.rrect(0, 70, 40, 90, 16), { fill: 'fabric.seat', lift: 2.4, hatch: 0.3 });
      P.piece(S.rrect(130, 70, 40, 90, 16), { fill: 'fabric.seat', lift: 2.4, hatch: 0.3 });
      P.piece(S.rrect(34, 110, 102, 40, 12), { fill: 'fabric.cloth', lift: 1.6, wash: 'wash.rose' });
      P.line([[20, 160], [20, 170]], { w: 3 }); P.line([[150, 160], [150, 170]], { w: 3 });
    },
    hover: () => 'A place to rest — finished work',
  });

  W.defineComponent('shrouded', {   // parked things under dust cloths
    size: p => [p.w || 240, p.h || 200],
    draw(P, p) {
      const w = p.w || 240, h = p.h || 200;
      P.piece(S.poly([[20, h], [10, 40], [60, 10], [w - 60, 14], [w - 12, 50], [w - 20, h]]), { fill: 'fabric.cloth', lift: 3, hatch: 0.45, creases: [[60, 20, 70, h], [120, 14, 110, h], [w - 70, 20, w - 60, h]] });
      if (p.label) plaque(P, w / 2, h - 20, p.label);
    },
    hover: p => p.label || 'Parked, under a dust cloth',
  });

  W.defineComponent('jars', {   // a row of bell jars; the killed ideas' dried specimens
    size: p => [p.w || 280, 150],
    draw(P, p) {
      const w = p.w || 280, n = Math.max(3, Math.round(w / 70));
      P.piece(S.rect(0, 110, w, 16), { fill: 'wood.dark', lift: 2, hatch: 0.3 });
      legs(P, 0, 126, w, 24);
      for (let i = 0; i < n; i++) { const cx = 30 + i * (w - 60) / (n - 1); P.line([[cx, 110], [cx - 4, 80], [cx + 3, 70]], { color: p.dry ? 'wood.grain' : 'plant.stem', w: 1.4 }); P.piece(S.leaf(cx, 82, 16, 5, p.dry ? 2.4 : -2.2), { fill: p.dry ? 'wood.light' : 'plant.leaf', lift: 0.8 }); P.piece(S.arch(cx - 20, 44, 40, 66), { fill: 'glass.fill', lift: 1.4, fibre: 0.3, glow: p.dry ? null : 'glass.rim', glowAlpha: 0.2 }); }
      if (p.label) plaque(P, w / 2, 142, p.label, { size: 10 });
    },
    hover: p => p.label || 'Specimen jars',
  });

  W.defineComponent('lantern', {
    size: () => [60, 150],
    draw(P, p) {
      P.line([[30, 0], [30, 60]], { w: 1.2, color: 'metal.iron' });
      P.piece(S.poly([[16, 60], [44, 60], [52, 72], [8, 72]]), { fill: 'metal.iron', lift: 1.4 });
      P.piece(S.rrect(12, 72, 36, 50, 6), { fill: 'paper.light', lift: 1.6, glow: p.color || 'glow.warm', glowAlpha: 0.9, fibre: 1.5 });
      P.piece(S.poly([[10, 122], [50, 122], [42, 132], [18, 132]]), { fill: 'metal.iron', lift: 1.2 });
      P.glowSpot(30, 98, 90, p.color || 'glow.warm', 0.6);
    },
    parts: null,
    fx: p => [{ kind: 'flicker', at: [30, 98], r: 80, color: p.color || 'glow.warm', amp: 0.14 }],
    hover: () => 'A lantern',
  });

  W.defineComponent('plant', {
    size: p => [p.size || 160, (p.size || 160) * 1.05],
    draw(P, p) {
      const s = p.size || 160, kind = p.kind || 'fern';
      if (kind === 'mushrooms') { plantAt(P, s / 2, s, s * 0.8, 'mushrooms', p.seed || 1); return; }
      if (p.pot !== false) { P.piece(S.poly([[s * 0.3, s * 0.78], [s * 0.7, s * 0.78], [s * 0.64, s], [s * 0.36, s]]), { fill: 'plant.pot', lift: 2, hatch: 0.35, hatchSide: 'right' }); P.piece(S.rrect(s * 0.26, s * 0.74, s * 0.48, s * 0.08, 3), { fill: 'plant.pot', lift: 1 }); }
    },
    parts: p => { const s = p.size || 160, kind = p.kind || 'fern'; if (kind === 'mushrooms') return []; return [{ id: 'leaves', at: [0, 0], size: [s, s * 0.8], pivot: [s / 2, s * 0.78], anim: { kind: 'sway', amp: 0.035, speed: 0.7 }, draw(P) { plantAt(P, s / 2, s * 0.78, s * 0.72, kind, p.seed || s); } }]; },
    fx: p => (p.kind === 'mushrooms' ? [{ kind: 'flicker', at: [(p.size || 160) / 2, (p.size || 160) * 0.8], r: (p.size || 160) * 0.8, color: 'glow.primary', amp: 0.25, nightOnly: true }] : []),
    hover: p => p.hover || null,
  });

  W.defineComponent('rug', {
    size: p => [p.w || 380, 110],
    draw(P, p) {
      const w = p.w || 380;
      P.piece(S.ellipse(w / 2, 55, w / 2, 50), { fill: 'fabric.rug', lift: 0.6, pattern: (x) => { for (const [k, c] of [[0.86, 'metal.brass'], [0.7, 'fabric.rugAlt'], [0.44, 'metal.brass']]) { x.strokeStyle = P.tk(c); x.lineWidth = 5; x.beginPath(); x.ellipse(w / 2, 55, w / 2 * k, 50 * k, 0, 0, 6.2832); x.stroke(); } } });
    },
    hover: () => null,
  });

  W.defineComponent('door', {
    size: p => [p.w || 150, p.h || 280],
    draw(P, p) {
      const w = p.w || 150, h = p.h || 280, vault = p.kind === 'vault';
      if (vault) {
        P.piece(S.circle(w / 2, h / 2, w / 2), { fill: 'metal.iron', lift: 3, hatch: 0.4 });
        P.piece(S.circle(w / 2, h / 2, w / 2 - 14), { fill: 'surface.section', lift: 0.4, glow: 'glow.primary', glowAlpha: 0.2 });
      } else {
        P.piece(S.arch(0, 0, w, h), { fill: 'wood.dark', lift: 3, hatch: 0.3 });
        P.piece(S.arch(12, 12, w - 24, h - 12), { fill: 'surface.section', lift: 0.3, glow: 'glow.primary', glowAlpha: 0.25 });
      }
      P.piece(S.rrect(w / 2 - 34, -30, 68, 22, 4), { fill: 'label.plate', lift: 1.4, wash: p.gate === 3 ? 'wash.rose' : 'wash.ochre' });
      P.text(`Gate ${p.gate}`, w / 2, -19, { size: 11, weight: 700 });
    },
    parts: p => {
      const w = p.w || 150, h = p.h || 280, vault = p.kind === 'vault';
      return [{ id: 'leaf', at: vault ? [8, 8] : [12, 12], size: vault ? [w - 16, h - 16] : [w - 24, h - 12], pivot: [0, (vault ? h - 16 : h - 12) / 2], anim: { kind: 'fold', bind: 'gateOpen' },
        draw(P) {
          if (vault) { const r = (w - 16) / 2; P.piece(S.circle(r, r, r), { fill: 'metal.steel', lift: 2, hatch: 0.35 }); P.piece(S.circle(r, r, r * 0.3), { fill: 'metal.brass', lift: 1.6 }); for (let i = 0; i < 6; i++) { const a = i / 6 * 6.28; P.line([[r, r], [r + Math.cos(a) * r * 0.7, r + Math.sin(a) * r * 0.7]], { w: 3, color: 'metal.brassDark' }); } return; }
          const lw = w - 24, lh = h - 12;
          P.piece(S.arch(0, 0, lw, lh), { fill: 'wood.mid', lift: 2, hatch: 0.25, creases: [[lw / 2, lw / 2, lw / 2, lh]] });
          for (const yy of [lh * 0.45, lh * 0.8]) P.line([[8, yy], [lw - 8, yy]], { w: 2.2, color: 'metal.iron' });
          P.piece(S.circle(lw - 16, lh * 0.6, 6), { fill: 'metal.brass', lift: 1 });
          if (p.gate === 3) { P.piece(S.rrect(lw / 2 - 12, lh * 0.52, 24, 30, 5), { fill: 'metal.brass', lift: 1.6 }); }
        } }];
    },
    fx: p => [{ kind: 'pulse', at: [(p.w || 150) / 2, (p.h || 280) * 0.55], r: (p.w || 150) * 0.9, color: p.gate === 3 ? 'glow.accent' : 'glow.warm', bind: 'gateWaiting' }],
    hover: (p, st) => {
      const n = p.gate, wait = st && st.gateWaiting;
      if (n === 3) return wait ? 'Gate 3 · waiting — finalization is signed in a session, never here' : 'Gate 3 · finalization happens in a session';
      return wait ? `Gate ${n} · ${wait} waiting for your signature — click to review` : `Gate ${n} · nothing waiting`;
    },
    action: 'gate',
  });

  W.defineComponent('sign', {   // a small hand-lettered sign on a stake: names a station
    size: p => [Math.max(90, (p.text || '').length * 9 + 30), 96],
    draw(P, p) {
      const w = Math.max(90, (p.text || '').length * 9 + 30);
      P.piece(S.rect(w / 2 - 3, 30, 6, 66), { fill: 'wood.dark', lift: 1.2 });
      P.piece(S.poly([[4, 4], [w - 4, 0], [w - 2, 32], [2, 36]]), { fill: 'label.plate', lift: 2, wash: p.wash || 'wash.ochre' });
      P.text(p.text || '', w / 2, 18, { size: 13, weight: 700, rot: -0.03 });
    },
    hover: p => p.hover || p.text,
  });

  // ── decor: the small things that make a room feel lived-in ──────────────────
  W.defineComponent('stringLights', {   // a garland swagged under the ceiling; bulbs glow (and flicker) at night
    size: p => [p.w || 900, 90],
    draw(P, p) {
      const w = p.w || 900, n = p.n || 14, pts = [];
      for (let i = 0; i <= 40; i++) { const u = i / 40; pts.push([u * w, 10 + Math.sin(u * Math.PI * (p.swags || 2)) ** 2 * 60]); }
      P.line(pts, { color: 'metal.iron', w: 1.2 });
      const tones = ['glow.warm', 'glow.primary', 'glow.accent', 'glow.secondary'];
      for (let i = 0; i < n; i++) { const u = (i + 0.5) / n, x = u * w, y = 14 + Math.sin(u * Math.PI * (p.swags || 2)) ** 2 * 60; P.piece(S.rrect(x - 5, y, 10, 14, 5), { fill: 'paper.light', lift: 1, deckle: 0.2, glow: tones[i % 4], glowAlpha: 1, inkW: 0.6 }); P.glowSpot(x, y + 8, 30, tones[i % 4], 0.5); }
    },
    fx: p => { const w = p.w || 900, n = p.n || 14; return Array.from({ length: Math.ceil(n / 3) }, (_, k) => { const i = k * 3, u = (i + 0.5) / n; return { kind: 'flicker', at: [u * w, 22 + Math.sin(u * Math.PI * (p.swags || 2)) ** 2 * 60], r: 26, color: ['glow.warm', 'glow.primary', 'glow.accent', 'glow.secondary'][i % 4], amp: 0.5, nightOnly: true }; }); },
    hover: () => null,
  });

  W.defineComponent('hangingPlant', {
    size: p => [120, p.drop || 220],
    draw(P, p) { const d = p.drop || 220; P.line([[60, 0], [40, d - 70]], { w: 0.9, color: 'metal.iron' }); P.line([[60, 0], [80, d - 70]], { w: 0.9, color: 'metal.iron' }); },
    parts: p => { const d = p.drop || 220; return [{ id: 'pot', at: [10, d - 90], size: [100, 90], pivot: [50, 0], anim: { kind: 'sway', amp: 0.05, speed: 0.4 },
      draw(PP) { PP.piece(S.poly([[22, 16], [78, 16], [70, 46], [30, 46]]), { fill: 'plant.pot', lift: 1.6, hatch: 0.3 }); const r = rng(d); for (let k = 0; k < 7; k++) { const x0 = 26 + k * 8, len = 20 + r() * 40, pts = []; for (let j = 0; j <= 6; j++) pts.push([x0 + Math.sin(j + k) * 4, 40 + j * len / 6]); PP.line(pts, { color: 'plant.stem', w: 1 }); for (let j = 2; j <= 6; j += 2) PP.piece(S.leaf(pts[j][0], pts[j][1], 9, 3.5, k % 2 ? 0.6 : 2.5), { fill: 'plant.leaf', lift: 0.6, deckle: 0.2, inkW: 0.5 }); } W.drawHelpers.plantAt(PP, 50, 18, 34, 'fern', d + 3); } }]; },
    hover: () => null,
  });

  W.defineComponent('pinned', {   // notes, a chart and a map pinned to a wall
    size: p => [p.w || 220, 130],
    draw(P, p) {
      const w = p.w || 220, r = rng(w + 17), washes = ['wash.ochre', 'wash.teal', 'wash.rose', 'wash.green', 'wash.blue'];
      for (let i = 0; i < (p.n || 5); i++) {
        const x = 8 + r() * (w - 60), y = 6 + r() * 70, ww = 34 + r() * 22, hh = 30 + r() * 20, a = (r() - 0.5) * 0.25;
        const pts = [[0, 0], [ww, 0], [ww, hh], [0, hh]].map(([u, v]) => [x + u * Math.cos(a) - v * Math.sin(a), y + u * Math.sin(a) + v * Math.cos(a)]);
        P.piece(pts, { fill: 'paper.white', lift: 1.2, deckle: 0.5, wash: washes[i % 5], inkW: 0.6 });
        for (let k = 0; k < 3; k++) P.line([[x + 5, y + 8 + k * 6], [x + ww - 8 - k * 4, y + 8 + k * 6]], { w: 0.4, alpha: 0.7 });
        P.piece(S.circle(x + ww / 2, y + 2, 2.6), { fill: 'fabric.rug', lift: 0.6, deckle: 0, ink: false });
      }
    },
    hover: p => p.hover || null,
  });

  W.defineComponent('crates', {   // a stack of crates / book piles on the floor
    size: p => [p.w || 150, 110],
    draw(P, p) {
      const w = p.w || 150;
      if (p.kind === 'books') { const r = rng(w); let y = 110; for (let i = 0; i < 6; i++) { const bw = 60 + r() * 30, bh = 10 + r() * 6; P.piece(S.rect(w / 2 - bw / 2 + (r() - 0.5) * 12, y - bh, bw, bh), { fill: BOOK_TONES[i % BOOK_TONES.length].startsWith('wash') ? 'paper.shade' : BOOK_TONES[i % BOOK_TONES.length], lift: 1.4, hatch: 0.2, deckle: 0.3 }); y -= bh; } return; }
      box(P, 0, 50, w * 0.62, 50, 12, { top: 'wood.light', front: 'wood.mid', hatch: 0.4 });
      P.line([[4, 66], [w * 0.62 - 4, 96]], { color: 'wood.dark', w: 2 });
      box(P, w * 0.5, 64, w * 0.5, 36, 10, { top: 'wood.light', front: 'wood.mid', hatch: 0.35 });
      box(P, w * 0.12, 14, w * 0.42, 30, 10, { top: 'paper.card', front: 'paper.shade', hatch: 0.3 });
    },
    hover: p => p.hover || null,
  });

  W.defineComponent('clock', {
    size: () => [64, 64],
    draw(P) { P.piece(S.circle(32, 32, 30), { fill: 'metal.brass', lift: 2 }); P.piece(S.circle(32, 32, 24), { fill: 'paper.white', lift: 0.4 }); for (let i = 0; i < 12; i++) { const a = i / 12 * 6.28; P.line([[32 + Math.cos(a) * 19, 32 + Math.sin(a) * 19], [32 + Math.cos(a) * 23, 32 + Math.sin(a) * 23]], { w: i % 3 ? 0.8 : 1.6 }); } },
    fx: () => [{ kind: 'clock', at: [32, 32], r: 20 }],
    hover: () => 'The lab clock · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  });

  W.drawHelpers = { box, drawers, legs, papers, book, bookRow, plantAt, deskLamp, chair, plaque };
})();
