/* Vivarium world — the PAPER material kit.
 *
 * `painter()` gives a component a tiny drawing API in which every shape is a piece of cut paper:
 *   P.piece(shape, {fill, lift, deckle, ink, wash, hatch, glow, …})
 *     → a deckled edge (noise-displaced outline), paper fibre, an optional watercolour wash and
 *       cross-hatching, an ink outline with a hand wobble (day) or a faint luminous rim (night), and a
 *       soft shadow on whatever is beneath it (`lift` = how far it stands off the page);
 *   P.line / P.text / P.glowSpot / P.window
 * Two canvases are baked: `base` (the paper) and `glow` (what shines by itself — added over the scene with
 * bloom at night, barely at all by day). The engine turns them into Pixi textures.
 * Colours are always design tokens (tokens.js), so a component looks right in both themes.
 */
(function () {
  'use strict';
  const W = (window.VivWorld = window.VivWorld || {});
  const { hash2, vnoise, fbm, rng, clamp, lerp } = W.noise;
  const T = W.tokens;

  // ── shapes (arrays of [x,y], component-local units) ─────────────────────────
  const S = {
    rect: (x, y, w, h) => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
    rrect(x, y, w, h, r) {
      r = Math.min(r, w / 2, h / 2); const p = [];
      const arc = (cx, cy, a0) => { for (let i = 0; i <= 5; i++) { const a = a0 + i / 5 * Math.PI / 2; p.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); } };
      arc(x + w - r, y + r, -Math.PI / 2); arc(x + w - r, y + h - r, 0); arc(x + r, y + h - r, Math.PI / 2); arc(x + r, y + r, Math.PI);
      return p;
    },
    ellipse(cx, cy, rx, ry, n) { const p = []; n = n || Math.max(18, Math.round((rx + ry) / 3)); for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2; p.push([cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]); } return p; },
    circle: (cx, cy, r) => S.ellipse(cx, cy, r, r),
    arch(x, y, w, h) { const r = w / 2, p = [[x, y + h]]; for (let i = 0; i <= 16; i++) { const a = Math.PI + i / 16 * Math.PI; p.push([x + r + Math.cos(a) * r, y + r + Math.sin(a) * r]); } p.push([x + w, y + h]); return p; },
    trap: (x0, x1, y0, x2, x3, y1) => [[x0, y0], [x1, y0], [x3, y1], [x2, y1]],   // top edge x0..x1 at y0, bottom x2..x3 at y1
    poly: pts => pts.map(p => [p[0], p[1]]),
    /** a soft irregular blob (leaves, stones, clouds) */
    blob(cx, cy, rx, ry, seed, wob) { const p = [], n = 28; for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2, k = 1 + (vnoise(i * 0.45, 0, seed) - 0.5) * (wob == null ? 0.4 : wob); p.push([cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k]); } return p; },
    leaf(x, y, len, wid, ang) { const p = [], ca = Math.cos(ang), sa = Math.sin(ang); for (let i = 0; i <= 12; i++) { const t = i / 12, w = Math.sin(Math.PI * t) * wid * (1 - t * 0.25); p.push([t * len, -w]); } for (let i = 12; i >= 0; i--) { const t = i / 12, w = Math.sin(Math.PI * t) * wid * (1 - t * 0.25); p.push([t * len, w]); } return p.map(([u, v]) => [x + u * ca - v * sa, y + u * sa + v * ca]); },
  };

  // ── shared textures (per theme, lazily) ─────────────────────────────────────
  const texCache = {};
  function fibreTexture(theme) {
    const k = 'fibre:' + theme.name; if (texCache[k]) return texCache[k];
    const c = document.createElement('canvas'); c.width = c.height = 256; const x = c.getContext('2d'), r = rng(theme.name === 'day' ? 11 : 12);
    const img = x.createImageData(256, 256), d = img.data;
    for (let i = 0; i < 256 * 256; i++) { const g = (hash2(i % 256, (i / 256) | 0, 3) - 0.5) * 60 + (fbm((i % 256) * 0.05, ((i / 256) | 0) * 0.05, 7, 3) - 0.5) * 70; d[i * 4] = d[i * 4 + 1] = d[i * 4 + 2] = 128 + g; d[i * 4 + 3] = 255; }
    x.putImageData(img, 0, 0);
    x.lineCap = 'round';
    for (let i = 0; i < 260; i++) {   // fibres
      const px = r() * 256, py = r() * 256, a = r() * Math.PI, l = 3 + r() * 12;
      x.strokeStyle = r() < 0.5 ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.25)'; x.lineWidth = 0.5 + r() * 0.8;
      x.beginPath(); x.moveTo(px, py); x.quadraticCurveTo(px + Math.cos(a + 0.6) * l * 0.5, py + Math.sin(a + 0.6) * l * 0.5, px + Math.cos(a) * l, py + Math.sin(a) * l); x.stroke();
    }
    texCache[k] = c; return c;
  }

  // ── geometry helpers ───────────────────────────────────────────────────────
  /** Resample a closed polygon every `step` units and push points along the normal by noise: a torn/deckled edge. */
  function deckle(pts, amp, seed, step) {
    if (!amp) return pts;
    step = step || 4.5; const out = [];
    let k = 0;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], b = pts[(i + 1) % pts.length], dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
      const nx = -dy / L, ny = dx / L, n = Math.max(1, Math.round(L / step));
      for (let j = 0; j < n; j++) {
        const t = j / n, off = (vnoise(k * 0.55, 0.5, seed) - 0.5) * 2 * amp + (hash2(k, 1, seed) - 0.5) * amp * 0.5;
        out.push([a[0] + dx * t + nx * off, a[1] + dy * t + ny * off]); k++;
      }
    }
    return out;
  }
  function trace(x, pts, close) { x.beginPath(); pts.forEach((p, i) => (i ? x.lineTo(p[0], p[1]) : x.moveTo(p[0], p[1]))); if (close !== false) x.closePath(); }
  function bounds(pts) { let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const [x, y] of pts) { if (x < x0) x0 = x; if (y < y0) y0 = y; if (x > x1) x1 = x; if (y > y1) y1 = y; } return { x0, y0, x1, y1, w: x1 - x0, h: y1 - y0 }; }

  // ── the painter ────────────────────────────────────────────────────────────
  /** A bake surface for one component: w×h units (+pad for shadows/glow), at `res` px per unit. */
  function painter(theme, w, h, res, seed, pad) {
    pad = pad == null ? 14 : pad;
    const cw = Math.ceil((w + pad * 2) * res), ch = Math.ceil((h + pad * 2) * res);
    const base = document.createElement('canvas'); base.width = cw; base.height = ch;
    const glowC = document.createElement('canvas'); glowC.width = cw; glowC.height = ch;
    const x = base.getContext('2d'), g = glowC.getContext('2d');
    for (const c of [x, g]) { c.setTransform(res, 0, 0, res, pad * res, pad * res); c.lineJoin = 'round'; c.lineCap = 'round'; }
    const tk = ref => T.tok(theme, ref);
    const day = theme.name === 'day';
    let seedK = seed >>> 0, glowUsed = false;
    const fibre = fibreTexture(theme);

    function piece(pts, o) {
      o = o || {};
      const sd = (seedK = (seedK + 7919) >>> 0);
      const edge = deckle(pts, (o.deckle == null ? 1 : o.deckle) * theme.edge.deckle, sd, o.step);
      const fill = tk(o.fill || 'paper.base');
      const lift = o.lift == null ? 2 : o.lift;
      // 1 · the shadow it casts on what is beneath
      if (lift > 0) {
        x.save(); x.shadowColor = T.alpha(theme.shadow.color, theme.shadow.alpha * (o.shadow == null ? 1 : o.shadow));
        x.shadowBlur = theme.shadow.blur * (0.8 + lift * 0.9) * res; x.shadowOffsetX = theme.shadow.dx * lift * res; x.shadowOffsetY = theme.shadow.dy * lift * res;
        trace(x, edge); x.fillStyle = fill; x.fill(); x.restore();
      }
      // 2 · the paper itself: fill + a gentle top-lit gradient
      trace(x, edge); const b = bounds(edge);
      if (o.gradient !== false) {
        const gr = x.createLinearGradient(0, b.y0, 0, b.y1);
        gr.addColorStop(0, T.shade(fill, day ? 0.06 : 0.07)); gr.addColorStop(1, T.shade(fill, day ? -0.07 : -0.12));
        x.fillStyle = gr;
      } else x.fillStyle = fill;
      x.fill();
      x.save(); trace(x, edge); x.clip();
      // 3 · fibre
      const pat = x.createPattern(fibre, 'repeat'); if (pat && pat.setTransform) { const m = new DOMMatrix(); m.scaleSelf(1 / res, 1 / res); m.translateSelf(hash2(sd, 2, 9) * 256, hash2(sd, 3, 9) * 256); pat.setTransform(m); }
      x.globalCompositeOperation = 'soft-light'; x.globalAlpha = theme.edge.fibre * 6 * (o.fibre == null ? 1 : o.fibre); x.fillStyle = pat; x.fillRect(b.x0 - 2, b.y0 - 2, b.w + 4, b.h + 4);
      x.globalCompositeOperation = 'source-over'; x.globalAlpha = 1;
      // 4 · watercolour wash: blotches + pooled edges
      if (o.wash) {
        const wc = tk(o.wash), r = rng(sd);
        for (let i = 0; i < 5; i++) { const cx = b.x0 + r() * b.w, cy = b.y0 + r() * b.h, rr = Math.max(b.w, b.h) * (0.25 + r() * 0.45); const gr = x.createRadialGradient(cx, cy, 0, cx, cy, rr); gr.addColorStop(0, wc); gr.addColorStop(1, T.alpha(wc, 0)); x.fillStyle = gr; x.fillRect(b.x0, b.y0, b.w, b.h); }
        x.strokeStyle = wc; x.lineWidth = 3.2; trace(x, edge); x.stroke();
      }
      // 5 · shading: cross-hatching by day, a soft dark gradient by night
      if (o.hatch) {
        const side = o.hatchSide || 'bottom';
        if (day) {
          // hatch only the shaded part of the piece (a sketcher's shadow side)
          x.save(); x.beginPath();
          if (side === 'bottom') x.rect(b.x0, b.y0 + b.h * 0.55, b.w, b.h * 0.45);
          else if (side === 'left') x.rect(b.x0, b.y0, b.w * 0.4, b.h);
          else if (side === 'right') x.rect(b.x0 + b.w * 0.6, b.y0, b.w * 0.4, b.h);
          else x.rect(b.x0, b.y0, b.w, b.h);
          x.clip();
          x.strokeStyle = tk('ink.soft'); x.lineWidth = 0.55; x.globalAlpha = clamp(o.hatch, 0, 1);
          const sp = 3.6, span = b.w + b.h;
          x.beginPath(); for (let s = -b.h; s < span; s += sp) { x.moveTo(b.x0 + s, b.y1); x.lineTo(b.x0 + s + b.h, b.y0); } x.stroke();
          x.restore();
        } else {
          const gr = side === 'left' ? x.createLinearGradient(b.x0, 0, b.x1, 0) : side === 'right' ? x.createLinearGradient(b.x1, 0, b.x0, 0) : x.createLinearGradient(0, b.y0, 0, b.y1);
          gr.addColorStop(0, 'rgba(0,0,0,0)'); gr.addColorStop(1, `rgba(0,0,0,${0.45 * o.hatch})`); x.fillStyle = gr; x.fillRect(b.x0, b.y0, b.w, b.h);
        }
      }
      if (o.pattern) o.pattern(x, b, theme);   // component-specific detail drawn inside the piece
      x.restore();
      // 6 · what glows (cut-outs lit from inside, liquids, bulbs, screens)
      if (o.glow) {
        glowUsed = true;
        g.save(); trace(g, edge); g.globalAlpha = (o.glowAlpha == null ? 1 : o.glowAlpha) * theme.glow.strength; g.fillStyle = tk(o.glow); g.fill(); g.restore();
        if (!day) { x.save(); trace(x, edge); x.globalAlpha = 0.5; x.fillStyle = T.shade(tk(o.glow), -0.1); x.fill(); x.restore(); }
      }
      // 7 · the outline: sepia ink with a hand wobble (day) / a faint luminous rim (night)
      if (o.ink !== false) {
        const wob = deckle(edge, theme.ink.wobble * 0.5, sd + 3, 7);
        x.strokeStyle = tk(o.inkColor || (day ? 'ink.line' : 'ink.soft')); x.lineWidth = theme.ink.width * (o.inkW || 1);
        trace(x, wob); x.stroke();
        if (!day && o.rimGlow !== false) { glowUsed = true; g.save(); g.strokeStyle = tk('ink.line'); g.globalAlpha = 0.22 * (o.rimGlow || 1); g.lineWidth = theme.ink.width * 1.6; trace(g, wob); g.stroke(); g.restore(); }
      }
      if (o.creases) for (const [a0, b0, a1, b1] of o.creases) { x.strokeStyle = 'rgba(255,255,255,0.35)'; x.lineWidth = 0.8; x.beginPath(); x.moveTo(a0, b0); x.lineTo(a1, b1); x.stroke(); x.strokeStyle = 'rgba(0,0,0,0.22)'; x.beginPath(); x.moveTo(a0 + 0.8, b0 + 0.8); x.lineTo(a1 + 0.8, b1 + 0.8); x.stroke(); }
      return edge;
    }

    /** A hand-drawn ink line (open or closed). */
    function line(pts, o) {
      o = o || {}; const sd = (seedK = (seedK + 104729) >>> 0);
      const wob = [];
      for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i], b = pts[i + 1], L = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(1, Math.round(L / 6));
        for (let j = 0; j < n; j++) { const t = j / n, off = (vnoise((i * 9 + j) * 0.5, 2, sd) - 0.5) * theme.ink.wobble * (o.wobble == null ? 1 : o.wobble); const nx = -(b[1] - a[1]) / (L || 1), ny = (b[0] - a[0]) / (L || 1); wob.push([a[0] + (b[0] - a[0]) * t + nx * off, a[1] + (b[1] - a[1]) * t + ny * off]); }
      }
      wob.push(pts[pts.length - 1]);
      x.save(); x.strokeStyle = tk(o.color || (day ? 'ink.line' : 'ink.soft')); x.lineWidth = theme.ink.width * (o.w || 1); x.globalAlpha = o.alpha == null ? 1 : o.alpha;
      if (o.dash) x.setLineDash(o.dash);
      trace(x, wob, !!o.close); x.stroke(); x.restore();
      if (o.glow) { glowUsed = true; g.save(); g.strokeStyle = tk(o.glow); g.globalAlpha = theme.glow.strength * (o.glowAlpha == null ? 0.8 : o.glowAlpha); g.lineWidth = theme.ink.width * (o.w || 1) * 1.8; trace(g, wob, !!o.close); g.stroke(); g.restore(); }
    }
    /** Hand-lettered text. */
    function text(str, cx, cy, o) {
      o = o || {};
      for (const c of [x].concat(!day && o.glow !== false ? [g] : [])) {
        c.save(); c.translate(cx, cy); if (o.rot) c.rotate(o.rot);
        c.font = `${o.weight || 600} ${o.size || 14}px ${o.font || theme.label.font}`; c.textAlign = o.align || 'center'; c.textBaseline = 'middle';
        if ('letterSpacing' in c && o.spacing) c.letterSpacing = o.spacing + 'px';
        c.fillStyle = tk(o.color || 'label.color');
        if (c === g) { c.globalAlpha = 0.35 * theme.glow.strength; glowUsed = true; }
        c.fillText(str, 0, 0); c.restore();
      }
    }
    /** A soft pool of light in the glow layer (lamps, jars, screens). */
    function glowSpot(cx, cy, r, ref, a, sy) {
      glowUsed = true; const col = tk(ref);
      g.save(); g.translate(cx, cy); g.scale(1, sy || 1);
      const gr = g.createRadialGradient(0, 0, 0, 0, 0, r); gr.addColorStop(0, T.alpha(col, (a == null ? 0.7 : a) * theme.glow.strength)); gr.addColorStop(1, T.alpha(col, 0));
      g.fillStyle = gr; g.beginPath(); g.arc(0, 0, r, 0, 6.2832); g.fill(); g.restore();
    }
    /** Raw access for bespoke detail (still token-coloured by convention). */
    function raw(fn) { x.save(); fn(x, tk, theme); x.restore(); }
    function rawGlow(fn) { glowUsed = true; g.save(); g.globalAlpha = theme.glow.strength; fn(g, tk, theme); g.restore(); }

    return { theme, day, res, pad, w, h, base, get glow() { return glowUsed ? glowC : null; }, piece, line, text, glowSpot, raw, rawGlow, tk, S, seed: () => (seedK = (seedK + 31) >>> 0) };
  }

  W.paper = { S, painter, deckle, bounds, trace, fibreTexture };
})();
