/* Vivarium room kit — the shared toolkit for code-drawn rooms.
 *
 * A room is drawn in a fixed DESIGN space (1600 × 900 units) as three baked layers plus a live one:
 *   albedo    — what things are made of (textures, paint, wood, glass), lit neutrally
 *   light     — how much light reaches each point (ambient + lamps / sun patches − shadows); multiplied
 *   emissive  — what glows by itself (screens, bulbs, glowing liquid, a bright window); added + bloomed
 *   live      — per-frame motion drawn over the bake (steam, bubbles, LEDs, scrolling screens, dust)
 * Day and night are the SAME albedo under different light and emissive layers, so both themes always
 * match and a new object only has to be drawn once. Everything here is plain Canvas2D (no WebGL, no
 * build step); blur uses a down-then-up-scale so it works in every browser.
 */
(function () {
  'use strict';
  const VW = 1600, VH = 900;

  // ── deterministic noise ────────────────────────────────────────────────────
  function hash2(x, y, s) {
    let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(s | 0, 1442695041);
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
  }
  function vnoise(x, y, s) {
    const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
    const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
    const a = hash2(xi, yi, s), b = hash2(xi + 1, yi, s), c = hash2(xi, yi + 1, s), d = hash2(xi + 1, yi + 1, s);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
  }
  function fbm(x, y, s, oct) {
    let f = 0, a = 0.5, fr = 1;
    for (let i = 0; i < (oct || 4); i++) { f += a * vnoise(x * fr, y * fr, s + i * 17); fr *= 2.03; a *= 0.5; }
    return f;
  }
  function rng(seed) {
    let t = seed >>> 0;
    return function () { t += 0x6D2B79F5; let r = Math.imul(t ^ (t >>> 15), 1 | t); r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r; return ((r ^ (r >>> 14)) >>> 0) / 4294967296; };
  }
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

  // ── canvases ───────────────────────────────────────────────────────────────
  function canvas(w, h) { const c = document.createElement('canvas'); c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h)); return c; }
  /** A layer in design units at bake scale `s` (ctx pre-transformed so 1 unit = s px). */
  function layer(s) { const c = canvas(VW * s, VH * s), x = c.getContext('2d'); x.setTransform(s, 0, 0, s, 0, 0); return { c, x }; }
  /** Soft copy of a canvas: downscale by `k` then back up with smoothing ≈ a gaussian blur of ~k px. */
  function blurred(src, k) {
    const sm = canvas(src.width / k, src.height / k), sx = sm.getContext('2d');
    sx.imageSmoothingEnabled = true; sx.imageSmoothingQuality = 'high'; sx.drawImage(src, 0, 0, sm.width, sm.height);
    // a second, smaller pass smooths the blocky look of a single downscale
    const sm2 = canvas(sm.width / 2, sm.height / 2), s2 = sm2.getContext('2d');
    s2.imageSmoothingQuality = 'high'; s2.drawImage(sm, 0, 0, sm2.width, sm2.height);
    const out = canvas(src.width, src.height), ox = out.getContext('2d');
    ox.imageSmoothingEnabled = true; ox.imageSmoothingQuality = 'high'; ox.drawImage(sm2, 0, 0, out.width, out.height);
    return out;
  }

  // ── colour ─────────────────────────────────────────────────────────────────
  const rgba = (r, g, b, a) => `rgba(${r | 0},${g | 0},${b | 0},${a == null ? 1 : a})`;
  const hsl = (h, s, l, a) => `hsla(${h},${s}%,${l}%,${a == null ? 1 : a})`;
  function mix(c1, c2, t) { return [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)]; }

  // ── procedural textures (per-pixel, baked once, used as patterns) ──────────
  const texCache = {};
  /** Wood grain: long rings along x, fibres, knots. `tone` = [light rgb, dark rgb]. */
  function woodTexture(key, tone, w, h, seed) {
    const k = 'wood:' + key; if (texCache[k]) return texCache[k];
    const c = canvas(w || 640, h || 180), x = c.getContext('2d'), img = x.createImageData(c.width, c.height), d = img.data;
    const [lt, dk] = tone;
    for (let py = 0; py < c.height; py++) for (let px = 0; px < c.width; px++) {
      const n = fbm(px * 0.006, py * 0.035, seed, 4);
      const t = py * 0.11 + n * 7.5 + Math.sin(px * 0.004 + seed) * 1.2;
      const ring = Math.pow(Math.abs(Math.sin(t)), 0.55);
      const fibre = vnoise(px * 0.9, py * 0.08, seed + 7) * 0.18;
      const knot = Math.max(0, 1 - Math.hypot((px % 310) - 160, (py - c.height * 0.5) * 2.6) / 26) * 0.4;
      const m = clamp(ring * 0.75 + fibre - knot + (fbm(px * 0.02, py * 0.02, seed + 3, 2) - 0.5) * 0.3, 0, 1);
      const col = mix(dk, lt, m), i = (py * c.width + px) * 4;
      d[i] = col[0]; d[i + 1] = col[1]; d[i + 2] = col[2]; d[i + 3] = 255;
    }
    x.putImageData(img, 0, 0); texCache[k] = c; return c;
  }
  /** Fine mottled grain for plaster / resin / paper. */
  function grainTexture(key, base, amp, scale, seed) {
    const k = 'grain:' + key; if (texCache[k]) return texCache[k];
    const c = canvas(256, 256), x = c.getContext('2d'), img = x.createImageData(256, 256), d = img.data;
    for (let py = 0; py < 256; py++) for (let px = 0; px < 256; px++) {
      // tileable: blend four offsets so the pattern repeats cleanly
      const fx = px / 256, fy = py / 256;
      const n = (fbm(px * scale, py * scale, seed, 3) * (1 - fx) * (1 - fy) + fbm((px - 256) * scale, py * scale, seed, 3) * fx * (1 - fy)
        + fbm(px * scale, (py - 256) * scale, seed, 3) * (1 - fx) * fy + fbm((px - 256) * scale, (py - 256) * scale, seed, 3) * fx * fy);
      const g = (n - 0.5) * amp + (hash2(px, py, seed) - 0.5) * amp * 0.35, i = (py * 256 + px) * 4;
      d[i] = clamp(base[0] + g * 255, 0, 255); d[i + 1] = clamp(base[1] + g * 255, 0, 255); d[i + 2] = clamp(base[2] + g * 255, 0, 255); d[i + 3] = 255;
    }
    x.putImageData(img, 0, 0); texCache[k] = c; return c;
  }
  function pattern(ctx, tex, s, rot) {
    const p = ctx.createPattern(tex, 'repeat');
    if (p && p.setTransform && (s || rot)) { const m = new DOMMatrix(); m.rotateSelf(rot || 0); m.scaleSelf(s || 1, s || 1); p.setTransform(m); }
    return p;
  }

  // ── primitives (design units) ──────────────────────────────────────────────
  function rrect(x, X, y, w, h, r) { r = Math.min(r, w / 2, h / 2); x.beginPath(); x.moveTo(X + r, y); x.arcTo(X + w, y, X + w, y + h, r); x.arcTo(X + w, y + h, X, y + h, r); x.arcTo(X, y + h, X, y, r); x.arcTo(X, y, X + w, y, r); x.closePath(); }
  function poly(x, pts) { x.beginPath(); pts.forEach((p, i) => (i ? x.lineTo(p[0], p[1]) : x.moveTo(p[0], p[1]))); x.closePath(); }
  function lin(x, x0, y0, x1, y1, stops) { const g = x.createLinearGradient(x0, y0, x1, y1); stops.forEach(([o, c]) => g.addColorStop(o, c)); return g; }
  function rad(x, cx, cy, r0, r1, stops, cx1, cy1) { const g = x.createRadialGradient(cx1 == null ? cx : cx1, cy1 == null ? cy : cy1, r0, cx, cy, r1); stops.forEach(([o, c]) => g.addColorStop(o, c)); return g; }
  /** A light pool: additive radial falloff (for the light layer). */
  function glow(x, cx, cy, r, col, a, sy) {
    x.save(); x.globalCompositeOperation = 'lighter'; x.translate(cx, cy); x.scale(1, sy || 1);
    x.fillStyle = rad(x, 0, 0, 0, r, [[0, rgba(col[0], col[1], col[2], a)], [0.35, rgba(col[0], col[1], col[2], a * 0.55)], [1, rgba(col[0], col[1], col[2], 0)]]);
    x.beginPath(); x.arc(0, 0, r, 0, 6.2832); x.fill(); x.restore();
  }
  /** Soft contact shadow / ambient occlusion under an object (for the light layer). */
  function contact(x, cx, cy, rx, ry, a) {
    x.save(); x.translate(cx, cy); x.scale(1, ry / rx);
    x.fillStyle = rad(x, 0, 0, 0, rx, [[0, `rgba(0,0,0,${a})`], [0.6, `rgba(0,0,0,${a * 0.55})`], [1, 'rgba(0,0,0,0)']]);
    x.beginPath(); x.arc(0, 0, rx, 0, 6.2832); x.fill(); x.restore();
  }
  /** An oblique box: footprint x..x+w, depth y0..y1 on the floor, height h. Faces filled by callbacks. */
  function box(x, X, y0, y1, w, h, top, front, opts) {
    opts = opts || {};
    poly(x, [[X, y1 - h], [X + w, y1 - h], [X + w, y1], [X, y1]]); x.fillStyle = front; x.fill();
    poly(x, [[X, y0 - h], [X + w, y0 - h], [X + w, y1 - h], [X, y1 - h]]); x.fillStyle = top; x.fill();
    if (opts.edge !== false) {   // a thin lit edge where top meets front reads as a bevel
      x.strokeStyle = opts.edge || 'rgba(255,255,255,0.22)'; x.lineWidth = 1.4;
      x.beginPath(); x.moveTo(X + 1, y1 - h + 0.7); x.lineTo(X + w - 1, y1 - h + 0.7); x.stroke();
    }
    if (opts.aoFront !== false) {   // the front face darkens toward the floor
      x.fillStyle = lin(x, 0, y1 - h, 0, y1, [[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0.28)']]);
      x.fillRect(X, y1 - h, w, h);
    }
  }
  /** Brass / steel: a horizontal cylinder-ish gradient with a sharp specular band. */
  function metal(x, x0, x1, kind) {
    const c = kind === 'steel'
      ? [[0, '#3c434b'], [0.18, '#9aa4ae'], [0.32, '#e8eef2'], [0.42, '#8a949e'], [0.7, '#4b535c'], [1, '#2a3036']]
      : kind === 'copper'
        ? [[0, '#4a2616'], [0.2, '#a4552e'], [0.34, '#f0a57a'], [0.46, '#b0602f'], [0.75, '#6b3218'], [1, '#3a1a0d']]
        : [[0, '#4d3712'], [0.2, '#a8812f'], [0.33, '#f6dc8e'], [0.45, '#b88c34'], [0.75, '#6d4f19'], [1, '#3b2a0c']];
    return lin(x, x0, 0, x1, 0, c);
  }
  /** Glass body: faint tint, darker rims, a tall highlight streak and a small hot spot. */
  function glassShine(x, X, y, w, h) {
    x.save();
    x.fillStyle = lin(x, X, 0, X + w, 0, [[0, 'rgba(255,255,255,0.22)'], [0.12, 'rgba(255,255,255,0.05)'], [0.5, 'rgba(255,255,255,0)'], [0.86, 'rgba(255,255,255,0.06)'], [1, 'rgba(255,255,255,0.2)']]);
    x.fillRect(X, y, w, h);
    x.fillStyle = 'rgba(255,255,255,0.55)'; rrect(x, X + w * 0.16, y + h * 0.08, w * 0.07, h * 0.72, w * 0.04); x.fill();
    x.fillStyle = 'rgba(255,255,255,0.25)'; rrect(x, X + w * 0.28, y + h * 0.1, w * 0.03, h * 0.5, w * 0.02); x.fill();
    x.restore();
  }
  function text(x, str, cx, cy, size, col, opts) {
    opts = opts || {};
    x.save(); x.font = `${opts.weight || 600} ${size}px ${opts.font || '"Fraunces", Georgia, serif'}`;
    x.textAlign = opts.align || 'center'; x.textBaseline = 'middle'; x.fillStyle = col;
    if (opts.spacing && 'letterSpacing' in x) x.letterSpacing = opts.spacing + 'px';
    if (opts.shadow) { x.shadowColor = opts.shadow; x.shadowBlur = opts.blur || 2; x.shadowOffsetY = opts.dy || 1; }
    x.fillText(str, cx, cy); x.restore();
  }

  // ── plants (the room's organic frame) ──────────────────────────────────────
  function leaf(x, len, wid, col, vein) {   // drawn along +x from the origin
    x.beginPath(); x.moveTo(0, 0);
    x.bezierCurveTo(len * 0.3, -wid, len * 0.75, -wid * 0.8, len, 0);
    x.bezierCurveTo(len * 0.75, wid * 0.8, len * 0.3, wid, 0, 0);
    x.fillStyle = col; x.fill();
    if (vein) { x.strokeStyle = vein; x.lineWidth = Math.max(0.6, wid * 0.08); x.beginPath(); x.moveTo(0, 0); x.quadraticCurveTo(len * 0.5, -wid * 0.12, len * 0.95, 0); x.stroke(); }
  }
  /** A fern: arching fronds of paired leaflets. */
  function fern(x, cx, cy, size, seed, dark) {
    const r = rng(seed), n = 9 + Math.floor(r() * 5);
    for (let f = 0; f < n; f++) {
      const ang = -Math.PI / 2 + (f / (n - 1) - 0.5) * 2.5 + (r() - 0.5) * 0.3, len = size * (0.7 + r() * 0.45);
      const bend = (ang + Math.PI / 2) * 0.55;
      x.save(); x.translate(cx, cy);
      const steps = 14;
      let px = 0, py = 0, a = ang;
      for (let i = 0; i < steps; i++) {
        const t = i / steps, seg = len / steps;
        a += bend / steps * 1.4;
        const nx = px + Math.cos(a) * seg, ny = py + Math.sin(a) * seg;
        const lw = size * 0.2 * Math.sin(Math.PI * (0.15 + t * 0.85)) * (1 - t * 0.5);
        const shade = dark ? 22 + t * 10 + r() * 6 : 30 + t * 12 + r() * 6;
        const col = hsl(95 + r() * 30, 42 + r() * 12, shade);
        for (const side of [-1, 1]) {
          x.save(); x.translate(nx, ny); x.rotate(a + side * (1.05 - t * 0.3)); leaf(x, lw, lw * 0.28, col); x.restore();
        }
        x.strokeStyle = hsl(90, 35, dark ? 18 : 24); x.lineWidth = Math.max(0.6, size * 0.012 * (1 - t));
        x.beginPath(); x.moveTo(px, py); x.lineTo(nx, ny); x.stroke();
        px = nx; py = ny;
      }
      x.restore();
    }
  }
  /** Big split leaves (monstera-like). */
  function broadleaf(x, cx, cy, size, seed, dark) {
    const r = rng(seed), n = 6 + Math.floor(r() * 3);
    for (let i = 0; i < n; i++) {
      const ang = -Math.PI / 2 + (i / (n - 1) - 0.5) * 2.2 + (r() - 0.5) * 0.25, len = size * (0.55 + r() * 0.5);
      const ex = cx + Math.cos(ang) * len, ey = cy + Math.sin(ang) * len;
      x.strokeStyle = hsl(95, 30, dark ? 16 : 26); x.lineWidth = size * 0.02;
      x.beginPath(); x.moveTo(cx, cy); x.quadraticCurveTo(cx + Math.cos(ang) * len * 0.5, cy + Math.sin(ang) * len * 0.3, ex, ey); x.stroke();
      x.save(); x.translate(ex, ey); x.rotate(ang + (r() - 0.5) * 0.6);
      const L = size * (0.42 + r() * 0.2), Wd = L * 0.62, l = dark ? 20 + r() * 8 : 28 + r() * 10;
      x.fillStyle = lin(x, 0, -Wd, 0, Wd, [[0, hsl(120, 40, l + 8)], [1, hsl(135, 45, l - 6)]]);
      x.beginPath(); x.moveTo(0, 0); x.bezierCurveTo(L * 0.2, -Wd, L * 0.9, -Wd * 0.9, L, 0); x.bezierCurveTo(L * 0.9, Wd * 0.9, L * 0.2, Wd, 0, 0); x.fill();
      // splits + veins
      x.strokeStyle = dark ? 'rgba(5,10,8,0.8)' : 'rgba(40,52,38,0.55)'; x.lineWidth = L * 0.035;
      for (let k = 1; k < 5; k++) { const t = k / 5; x.beginPath(); x.moveTo(L * t, 0); x.lineTo(L * (t + 0.08), (k % 2 ? -1 : 1) * Wd * 0.8); x.stroke(); }
      x.strokeStyle = dark ? 'rgba(160,210,160,0.18)' : 'rgba(230,250,210,0.35)'; x.lineWidth = L * 0.02;
      x.beginPath(); x.moveTo(0, 0); x.lineTo(L * 0.96, 0); x.stroke();
      x.restore();
    }
  }
  /** A terracotta pot with rim, soil and a highlight. */
  function pot(x, cx, by, w, h, dark) {
    const top = by - h;
    x.fillStyle = lin(x, cx - w / 2, 0, cx + w / 2, 0, [[0, dark ? '#4a2518' : '#7a3b22'], [0.3, dark ? '#8a4a30' : '#c46c44'], [0.55, dark ? '#6e3822' : '#a45634'], [1, dark ? '#321a10' : '#5a2a16']]);
    poly(x, [[cx - w / 2, top + h * 0.14], [cx + w / 2, top + h * 0.14], [cx + w * 0.38, by], [cx - w * 0.38, by]]); x.fill();
    x.fillStyle = dark ? '#7a4128' : '#b8603c'; rrect(x, cx - w * 0.55, top, w * 1.1, h * 0.17, 3); x.fill();
    x.fillStyle = '#2b1d14'; x.beginPath(); x.ellipse(cx, top + h * 0.03, w * 0.47, h * 0.06, 0, 0, 6.2832); x.fill();
  }
  /** Ivy trailing down from a point. */
  function ivy(x, sx, sy, len, drift, seed, dark) {
    const r = rng(seed); let px = sx, py = sy;
    x.strokeStyle = hsl(85, 30, dark ? 14 : 22); x.lineWidth = 1.6;
    for (let i = 0; i < len; i += 9) {
      const nx = px + drift * 0.08 + Math.sin(i * 0.05 + seed) * 2.2, ny = py + 9;
      x.beginPath(); x.moveTo(px, py); x.lineTo(nx, ny); x.stroke();
      if (r() < 0.8) {
        const side = r() < 0.5 ? -1 : 1, sz = 6 + r() * 7;
        x.save(); x.translate(nx, ny); x.rotate(side * (0.6 + r() * 0.8) + Math.PI / 2 * (side < 0 ? 2 : 0));
        leaf(x, sz, sz * 0.55, hsl(100 + r() * 30, 40, dark ? 18 + r() * 8 : 28 + r() * 10), dark ? null : 'rgba(255,255,255,0.18)');
        x.restore();
      }
      px = nx; py = ny;
    }
  }

  window.RoomKit = { VW, VH, hash2, vnoise, fbm, rng, clamp, lerp, smooth, canvas, layer, blurred, rgba, hsl, mix,
    woodTexture, grainTexture, pattern, rrect, poly, lin, rad, glow, contact, box, metal, glassShine, text,
    leaf, fern, broadleaf, pot, ivy };
})();
