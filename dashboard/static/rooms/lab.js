/* The Lab — a code-drawn room (see rooms/kit.js for the layer model).
 *
 * A glasshouse laboratory: an ashlar back wall with three arched windows, limestone flagstones, a
 * resin-topped experiments bench (smoke flask · pilot bell jar · the FULL reactor), the improve/debug
 * desk, a brass quality-check dais, the in-project ideation table and the analysis console, framed by
 * plants. Day = sunlight through the windows with cast shadows; night = the same room lit by its lamps,
 * screens and the glowing reactor. Live layer: steam, bubbles, compute LEDs (= real slots in use),
 * screens that scroll while an agent works here, drifting dust / spores, the wall clock.
 */
(function () {
  'use strict';
  const K = window.RoomKit; if (!K) return;
  const { VW, VH, rgba, hsl, lin, rad, rrect, poly, box, metal, glassShine, contact, glow, fbm, vnoise, hash2, clamp, smooth, rng } = K;
  const F = 200;   // where the back wall meets the floor (design units)

  // ── layout (design units) ─────────────────────────────────────────────────
  const WIN = [330, 800, 1270], WIN_R = 75, WIN_TOP = 22, WIN_BOT = 176;
  const BENCH = { x: 420, w: 540, y0: 262, y1: 336, h: 74 };
  const REACTOR = { cx: 1040, base: 352, r: 50, glassTop: 96, glassBot: 290 };
  const PEND = [560, 826], PEND_Y = 116;
  const DESK = { x: 1130, w: 320, y0: 298, y1: 362, h: 72 };
  const CHAIR = { cx: 1392, cy: 432 };
  const RACK = { x: 40, w: 172, y0: 382, y1: 432, h: 252 };
  const DAIS = { cx: 800, cy: 612, rx: 152, ry: 56, h: 16 };
  const TABLE = { cx: 300, cy: 742, rx: 150, ry: 50, h: 52 };
  const BOARD = { x: 78, w: 244, y: 468, h: 140 };
  const ANAL = { x: 1030, w: 450, y0: 700, y1: 762, h: 70 };
  const SCREEN = { x: 1064, w: 382, y: 520, h: 96 };

  // where buddies stand (normalised) and the walkway they stroll along
  const STATIONS = {
    experiments: { x: 0.48, y: 0.43 }, improve: { x: 0.80, y: 0.465 }, ideate: { x: 0.31, y: 0.80 },
    quality: { x: 0.555, y: 0.675 }, analysis: { x: 0.76, y: 0.90 },
  };
  const PATHS = [[0.31, 0.83], [0.40, 0.75], [0.47, 0.69], [0.50, 0.56], [0.48, 0.45], [0.62, 0.47], [0.80, 0.48], [0.86, 0.62], [0.80, 0.90], [0.64, 0.84]];
  const WALK = [[496, 760], [640, 676], [760, 600], [800, 500], [768, 396], [990, 410], [1280, 424], [1370, 560], [1250, 820], [1010, 780], [800, 700]];

  // ── albedo pieces ─────────────────────────────────────────────────────────
  function paintWall(x, s) {
    const r = Math.min(s, 1.25), w = Math.ceil(VW * r), h = Math.ceil(F * r);
    const c = K.canvas(w, h), cx = c.getContext('2d'), img = cx.createImageData(w, h), d = img.data;
    const ROW = 34;
    for (let py = 0; py < h; py++) {
      const y = py / r, row = Math.floor(y / ROW), yr = y - row * ROW, off = hash2(row, 3, 91) * 90;
      for (let px = 0; px < w; px++) {
        const xx = px / r + off;
        // block boundaries: variable widths from a per-row hash chain
        const bw = 72 + hash2(Math.floor(xx / 96), row, 7) * 60;
        const col = Math.floor(xx / bw), xr = xx - col * bw, id = col * 131 + row * 71;
        const mortar = Math.min(xr, bw - xr, yr, ROW - yr);
        const tone = 0.88 + hash2(id, 5, 13) * 0.2, warm = hash2(id, 9, 17) * 10;
        const n = fbm(xx * 0.05, y * 0.05, 31, 3), fine = hash2(px, py, 77);
        let R = (176 + warm) * tone, G = 168 * tone, B = (150 - warm * 0.5) * tone;
        const m = (n - 0.5) * 34 + (fine - 0.5) * 12;
        R += m; G += m; B += m;
        const bevel = smooth(0, 3.4, mortar);
        if (mortar < 2.2) { R = 120; G = 113; B = 100; }            // mortar
        else { const lit = (yr < 6 ? 10 : 0) - (ROW - yr < 5 ? 14 : 0); R = R * (0.82 + 0.18 * bevel) + lit; G = G * (0.82 + 0.18 * bevel) + lit; B = B * (0.82 + 0.18 * bevel) + lit; }
        // moss creeping up from the floor line, and a darker band under the ceiling
        const moss = smooth(0.55, 0.75, fbm(xx * 0.02, y * 0.03, 5, 3)) * smooth(F - 70, F - 6, y);
        R = R * (1 - moss * 0.5) + 70 * moss * 0.5; G = G * (1 - moss * 0.35) + 110 * moss * 0.35; B = B * (1 - moss * 0.55) + 55 * moss * 0.55;
        const shade = 0.78 + 0.22 * smooth(0, 70, y);
        const i = (py * w + px) * 4;
        d[i] = clamp(R * shade, 0, 255); d[i + 1] = clamp(G * shade, 0, 255); d[i + 2] = clamp(B * shade, 0, 255); d[i + 3] = 255;
      }
    }
    cx.putImageData(img, 0, 0);
    x.drawImage(c, 0, 0, VW, F);
    // skirting board
    x.fillStyle = lin(x, 0, F - 16, 0, F, [[0, '#6d4a2c'], [0.25, '#8c6440'], [1, '#3e2917']]); x.fillRect(0, F - 16, VW, 16);
    x.fillStyle = 'rgba(255,240,210,0.25)'; x.fillRect(0, F - 16, VW, 1.5);
  }

  function paintFloor(x, s) {
    const r = Math.min(s, 1), w = Math.ceil(VW * r), h = Math.ceil((VH - F) * r), L = VH - F;
    const c = K.canvas(w, h), cx = c.getContext('2d'), img = cx.createImageData(w, h), d = img.data;
    const SW = 168, SH = 84;   // slab size in floor space
    for (let py = 0; py < h; py++) {
      const t = (py / r) / L, p = 0.62 + 0.38 * t;           // perspective: slabs shrink toward the wall
      const v = ((py / r) / (0.5 * p + 0.02)) ;
      const row = Math.floor(v / SH), vr = v - row * SH;
      for (let px = 0; px < w; px++) {
        const u = ((px / r) - VW / 2) / p + VW / 2 + (row % 2) * SW * 0.5 + hash2(row, 1, 3) * 30;
        const col = Math.floor(u / SW), ur = u - col * SW, id = col * 7919 + row * 104729;
        const joint = Math.min(ur, SW - ur, vr * 1.6, (SH - vr) * 1.6);
        const tone = 0.92 + hash2(id, 1, 3) * 0.12, warm = (hash2(id, 2, 5) - 0.5) * 12;
        // limestone: soft cloudy mottling + faint veins + fossil flecks + fine grain
        const cloud = fbm(u * 0.012, v * 0.024, 41 + (id % 7), 4) - 0.5;
        const vein = Math.pow(1 - Math.abs(Math.sin((u * 0.02 + v * 0.05 + fbm(u * 0.01, v * 0.01, 9, 3) * 6))), 18) * (hash2(id, 4, 1) > 0.5 ? 1 : 0);
        const fl = hash2(px, py, 9), fleck = fl > 0.992 ? -30 : fl < 0.004 ? 18 : 0;
        let R = (206 + warm) * tone, G = 198 * tone, B = (182 - warm * 0.6) * tone;
        const m = cloud * 26 - vein * 22 + fleck + (fl - 0.5) * 6;
        R += m; G += m; B += m;
        const bev = smooth(0.6, 5, joint);
        const k = 0.8 + 0.2 * bev;
        let rr = R * k, gg = G * k, bb = B * k;
        if (joint < 0.9) { rr = 112; gg = 104; bb = 92; }            // grout line
        const i = (py * w + px) * 4;
        d[i] = clamp(rr, 0, 255); d[i + 1] = clamp(gg, 0, 255); d[i + 2] = clamp(bb, 0, 255); d[i + 3] = 255;
      }
    }
    cx.putImageData(img, 0, 0);
    x.drawImage(c, 0, F, VW, L);
    // a faintly worn trail where feet go between the stations (scuffed, not paved)
    const path = new Path2D(); path.moveTo(WALK[0][0], WALK[0][1]);
    for (let i = 1; i < WALK.length - 1; i++) { const mx = (WALK[i][0] + WALK[i + 1][0]) / 2, my = (WALK[i][1] + WALK[i + 1][1]) / 2; path.quadraticCurveTo(WALK[i][0], WALK[i][1], mx, my); }
    path.lineTo(WALK[WALK.length - 1][0], WALK[WALK.length - 1][1]);
    const trail = K.layer(Math.min(s, 1) * 0.5);
    trail.x.lineCap = 'round'; trail.x.lineJoin = 'round'; trail.x.strokeStyle = 'rgba(70,56,40,1)'; trail.x.lineWidth = 58; trail.x.stroke(path);
    x.save(); x.globalAlpha = 0.13; x.globalCompositeOperation = 'multiply'; x.drawImage(K.blurred(trail.c, 6), 0, 0, VW, VH); x.restore();
  }

  function windowGlass(x, cx) {
    x.beginPath(); x.moveTo(cx - WIN_R, WIN_BOT); x.lineTo(cx - WIN_R, WIN_TOP + WIN_R);
    x.arc(cx, WIN_TOP + WIN_R, WIN_R, Math.PI, 0); x.lineTo(cx + WIN_R, WIN_BOT); x.closePath();
  }
  function windowBars(x, cx, col, lw) {
    x.save(); x.strokeStyle = col; x.lineWidth = lw; x.lineCap = 'butt';
    x.beginPath(); x.moveTo(cx, WIN_TOP); x.lineTo(cx, WIN_BOT); x.stroke();
    for (const yy of [WIN_TOP + WIN_R, 136]) { x.beginPath(); x.moveTo(cx - WIN_R, yy); x.lineTo(cx + WIN_R, yy); x.stroke(); }
    for (const a of [-2.4, -0.74]) { x.beginPath(); x.moveTo(cx, WIN_TOP + WIN_R); x.lineTo(cx + Math.cos(a) * WIN_R, WIN_TOP + WIN_R + Math.sin(a) * WIN_R); x.stroke(); }
    x.lineWidth = lw * 1.5; windowGlass(x, cx); x.stroke();
    x.restore();
  }
  function paintWindows(x) {
    for (const cx of WIN) {
      // stone surround (a deeper reveal), glass, frame, sill
      x.save(); x.translate(0, 0);
      x.beginPath(); x.moveTo(cx - WIN_R - 14, WIN_BOT + 4); x.lineTo(cx - WIN_R - 14, WIN_TOP + WIN_R); x.arc(cx, WIN_TOP + WIN_R, WIN_R + 14, Math.PI, 0); x.lineTo(cx + WIN_R + 14, WIN_BOT + 4); x.closePath();
      x.fillStyle = lin(x, 0, WIN_TOP, 0, WIN_BOT, [[0, '#8f8674'], [1, '#6e6656']]); x.fill();
      x.restore();
      windowGlass(x, cx); x.fillStyle = '#2d3a44'; x.fill();
      windowBars(x, cx, '#2c241b', 4.5);
      // sill
      x.fillStyle = lin(x, 0, WIN_BOT, 0, WIN_BOT + 14, [[0, '#cfc6b3'], [0.4, '#b3a993'], [1, '#6f6756']]);
      rrect(x, cx - WIN_R - 22, WIN_BOT, WIN_R * 2 + 44, 12, 2); x.fill();
    }
  }

  function bottle(x, bx, by, kind, col, r) {
    const [H, Wd] = kind === 'tall' ? [44, 13] : kind === 'flask' ? [30, 22] : kind === 'jar' ? [26, 20] : [34, 16];
    x.save();
    if (kind === 'flask') {
      x.beginPath(); x.moveTo(bx - 3.5, by - H); x.lineTo(bx - 3.5, by - H * 0.55); x.lineTo(bx - Wd / 2, by - 2); x.quadraticCurveTo(bx, by + 2, bx + Wd / 2, by - 2); x.lineTo(bx + 3.5, by - H * 0.55); x.lineTo(bx + 3.5, by - H); x.closePath();
    } else { rrect(x, bx - Wd / 2, by - H, Wd, H, kind === 'jar' ? 4 : 5); }
    x.fillStyle = col; x.globalAlpha = 0.85; x.fill(); x.globalAlpha = 1;
    // liquid line + shine + cap
    x.clip(); x.fillStyle = 'rgba(0,0,0,0.25)'; x.fillRect(bx - Wd, by - H * (0.35 + r * 0.3), Wd * 2, 3);
    glassShine(x, bx - Wd / 2, by - H, Wd, H);
    x.restore();
    if (kind !== 'flask') { x.fillStyle = kind === 'jar' ? '#6b5a44' : '#3a2e24'; rrect(x, bx - Wd * 0.34, by - H - 5, Wd * 0.68, 6, 1.5); x.fill(); }
  }
  function books(x, x0, by, n, seed) {
    const r = rng(seed); let bx = x0;
    for (let i = 0; i < n; i++) {
      const w = 7 + r() * 6, h = 30 + r() * 14, hue = [8, 28, 200, 150, 40, 350, 215][Math.floor(r() * 7)];
      const lean = i === n - 1 ? 0.18 : 0;
      x.save(); x.translate(bx, by); x.rotate(lean);
      x.fillStyle = lin(x, 0, 0, w, 0, [[0, hsl(hue, 38, 22)], [0.4, hsl(hue, 42, 36)], [1, hsl(hue, 38, 20)]]); x.fillRect(0, -h, w, h);
      x.fillStyle = 'rgba(240,210,140,0.55)'; x.fillRect(1, -h + 6, w - 2, 1.4); x.fillRect(1, -10, w - 2, 1.4);
      x.restore(); bx += w + 0.8;
    }
    return bx;
  }
  function shelf(x, x0, x1, seed) {
    const r = rng(seed), rows = [72, 124, 172];
    for (const [ri, y] of rows.entries()) {
      // brackets + plank
      x.fillStyle = '#2d241b'; for (const bx of [x0 + 14, x1 - 20]) { poly(x, [[bx, y + 4], [bx + 6, y + 4], [bx + 6, y + 18], [bx, y + 10]]); x.fill(); }
      x.fillStyle = K.pattern(x, K.woodTexture('oak', [[176, 126, 78], [104, 68, 38]], 640, 180, 4), 0.35);
      x.fillRect(x0, y - 2, x1 - x0, 8);
      x.fillStyle = 'rgba(0,0,0,0.35)'; x.fillRect(x0, y + 6, x1 - x0, 2.5);
      let cx = x0 + 10 + r() * 10;
      while (cx < x1 - 30) {
        const pick = r();
        if (pick < 0.32) cx = books(x, cx, y - 2, 3 + Math.floor(r() * 4), seed * 7 + ri * 3 + Math.floor(cx)) + 8;
        else if (pick < 0.82) {
          const kinds = ['tall', 'flask', 'jar', 'round'], kind = kinds[Math.floor(r() * 4)];
          const cols = ['rgba(150,98,40,0.9)', 'rgba(60,120,80,0.8)', 'rgba(190,210,215,0.55)', 'rgba(120,60,40,0.85)', 'rgba(80,130,150,0.75)'];
          bottle(x, cx + 8, y - 2, kind, cols[Math.floor(r() * cols.length)], r()); cx += 26 + r() * 6;
        } else { K.pot(x, cx + 10, y - 2, 18, 14, false); K.fern(x, cx + 10, y - 16, 16, seed + Math.floor(cx), false); cx += 30; }
      }
    }
  }

  function pipes(x) {
    x.save();
    // a copper line along the top of the wall that drops to the reactor
    x.fillStyle = K.lin(x, 0, 6, 0, 18, [[0, '#4a2616'], [0.35, '#f0a57a'], [0.6, '#a4552e'], [1, '#3a1a0d']]); x.fillRect(0, 6, VW, 12);
    for (let px = 40; px < VW; px += 180) { x.fillStyle = '#2b2118'; x.fillRect(px, 3, 8, 18); }
    x.fillStyle = metal(x, REACTOR.cx + 34, REACTOR.cx + 46, 'copper'); x.fillRect(REACTOR.cx + 34, 12, 12, REACTOR.glassTop - 12);
    x.restore();
  }

  function pendant(x, cx, shadeY) {
    x.strokeStyle = '#1d1a16'; x.lineWidth = 1.6; x.beginPath(); x.moveTo(cx, 0); x.lineTo(cx, shadeY - 16); x.stroke();
    x.fillStyle = metal(x, cx - 8, cx + 8, 'brass'); x.fillRect(cx - 5, shadeY - 18, 10, 8);
    x.beginPath(); x.moveTo(cx - 8, shadeY - 11); x.lineTo(cx + 8, shadeY - 11); x.lineTo(cx + 30, shadeY + 8); x.lineTo(cx - 30, shadeY + 8); x.closePath();
    x.fillStyle = lin(x, cx - 30, 0, cx + 30, 0, [[0, '#1f3a30'], [0.35, '#4f8a70'], [0.55, '#2e5a48'], [1, '#14281f']]); x.fill();
    x.fillStyle = '#e8e2cf'; x.beginPath(); x.ellipse(cx, shadeY + 8, 30, 5, 0, 0, 6.2832); x.fill();
  }

  function rack(x) {
    const { x: X, w, y0, y1, h } = RACK;
    box(x, X, y0, y1, w, h, lin(x, 0, y0 - h, 0, y1 - h, [[0, '#5a626c'], [1, '#474e57']]), lin(x, X, 0, X + w, 0, [[0, '#343a41'], [0.5, '#4a525b'], [1, '#30353b']]));
    // front: rails, a stack of rack-mounted units with handles + vents, the LED panel (lit live)
    x.fillStyle = metal(x, X + 6, X + 14, 'steel'); x.fillRect(X + 7, y1 - h + 8, 6, h - 16); x.fillRect(X + w - 13, y1 - h + 8, 6, h - 16);
    for (let yy = y1 - h + 12, u = 0; yy < y1 - 20; yy += 26, u++) {
      x.fillStyle = u % 3 === 1 ? '#2a2f35' : '#1f2328'; rrect(x, X + 15, yy, w - 30, 22, 2); x.fill();
      x.fillStyle = 'rgba(255,255,255,0.07)'; x.fillRect(X + 15, yy, w - 30, 1.2);
      for (let vx = X + 22; vx < X + 64; vx += 5) { x.fillStyle = 'rgba(0,0,0,0.55)'; x.fillRect(vx, yy + 5, 2.4, 12); }
      x.fillStyle = metal(x, X + w - 28, X + w - 20, 'steel'); x.fillRect(X + w - 26, yy + 4, 4, 14);
    }
    x.fillStyle = 'rgba(8,10,12,0.92)'; rrect(x, X + 72, y1 - h + 18, w - 104, Math.min(8, 8) * 22 + 22, 4); x.fill();
    // a small wall sconce above it
    x.fillStyle = metal(x, X + w / 2 - 10, X + w / 2 + 10, 'brass'); x.fillRect(X + w / 2 - 3, 70, 6, 22);
    x.beginPath(); x.moveTo(X + w / 2 - 16, 70); x.lineTo(X + w / 2 + 16, 70); x.lineTo(X + w / 2 + 9, 52); x.lineTo(X + w / 2 - 9, 52); x.closePath(); x.fillStyle = '#e9dcc0'; x.fill();
    x.fillStyle = metal(x, X + 40, X + w - 40, 'brass'); rrect(x, X + 40, y0 - h - 2, w - 80, 16, 2); x.fill();
    // cables up to the ceiling
    x.strokeStyle = '#15181b'; x.lineWidth = 5; for (const k of [0, 1, 2]) { x.beginPath(); x.moveTo(X + 50 + k * 30, y0 - h); x.bezierCurveTo(X + 60 + k * 30, 80, X + 20 + k * 40, 40, X + 40 + k * 50, 0); x.stroke(); }
  }

  function bench(x) {
    const { x: X, w, y0, y1, h } = BENCH;
    const wood = K.pattern(x, K.woodTexture('walnut', [[150, 100, 60], [74, 46, 26]], 640, 180, 9), 0.6);
    const resin = lin(x, 0, y0 - h, 0, y1 - h, [[0, '#2b3034'], [0.5, '#3a4045'], [1, '#22272b']]);
    box(x, X, y0, y1, w, h, resin, wood);
    // cabinet doors with brass pulls
    const doors = 5, dw = (w - 24) / doors;
    for (let i = 0; i < doors; i++) {
      const dx = X + 12 + i * dw;
      x.strokeStyle = 'rgba(0,0,0,0.45)'; x.lineWidth = 1.6; rrect(x, dx + 3, y1 - h + 14, dw - 6, h - 22, 3); x.stroke();
      x.strokeStyle = 'rgba(255,220,170,0.12)'; x.lineWidth = 1; rrect(x, dx + 5, y1 - h + 16, dw - 10, h - 26, 2); x.stroke();
      x.fillStyle = metal(x, dx + dw / 2 - 9, dx + dw / 2 + 9, 'brass'); rrect(x, dx + dw / 2 - 9, y1 - h + 22, 18, 4, 2); x.fill();
    }
    // resin top: a soft specular sheen
    x.fillStyle = lin(x, X, 0, X + w, 0, [[0, 'rgba(255,255,255,0)'], [0.45, 'rgba(255,255,255,0.09)'], [0.55, 'rgba(255,255,255,0.02)'], [1, 'rgba(255,255,255,0)']]);
    x.fillRect(X, y0 - h, w, y1 - y0);
    // plaque
    x.fillStyle = metal(x, X + w / 2 - 82, X + w / 2 + 82, 'brass'); rrect(x, X + w / 2 - 82, y1 - 22, 164, 18, 2); x.fill();
    const top = y1 - h - 8;   // where things stand on the bench
    // test-tube rack
    x.fillStyle = '#5e4028'; x.fillRect(X + 26, top - 18, 60, 6); x.fillRect(X + 26, top - 2, 60, 5);
    ['#d86a4a', '#5fb07a', '#5a8fd0', '#e0b24a', '#b06ad0'].forEach((c, i) => { const tx = X + 32 + i * 11; x.fillStyle = 'rgba(210,230,235,0.5)'; rrect(x, tx, top - 36, 7, 36, 3.5); x.fill(); x.fillStyle = c; rrect(x, tx + 1, top - 16, 5, 14, 2.5); x.fill(); });
    // SMOKE: ring stand, burner, Erlenmeyer flask
    const sx = X + 150;
    x.fillStyle = '#26221e'; x.fillRect(sx - 36, top - 2, 72, 5); x.fillStyle = metal(x, sx + 26, sx + 30, 'steel'); x.fillRect(sx + 26, top - 92, 4, 90);
    x.strokeStyle = '#8a949e'; x.lineWidth = 2.4; x.beginPath(); x.ellipse(sx, top - 34, 20, 5, 0, 0, 6.2832); x.stroke();
    x.fillStyle = metal(x, sx - 7, sx + 7, 'steel'); x.fillRect(sx - 6, top - 26, 12, 24);
    x.beginPath(); x.moveTo(sx - 5, top - 74); x.lineTo(sx - 5, top - 58); x.lineTo(sx - 24, top - 36); x.quadraticCurveTo(sx, top - 30, sx + 24, top - 36); x.lineTo(sx + 5, top - 58); x.lineTo(sx + 5, top - 74); x.closePath();
    x.fillStyle = 'rgba(200,225,230,0.35)'; x.fill();
    x.save(); x.clip(); x.fillStyle = 'rgba(110,200,120,0.75)'; x.fillRect(sx - 30, top - 50, 60, 22); glassShine(x, sx - 24, top - 74, 48, 44); x.restore();
    x.fillStyle = metal(x, X + 140 - 40, X + 140 + 40, 'brass'); rrect(x, sx - 22, y1 - 36, 44, 11, 2); x.fill();
    // notebook
    x.save(); x.translate(X + 250, top - 12); x.rotate(-0.08); x.fillStyle = '#6b3b24'; x.fillRect(-26, -16, 52, 30); x.fillStyle = '#efe6d2'; x.fillRect(-23, -14, 46, 25);
    x.strokeStyle = 'rgba(80,90,120,0.45)'; x.lineWidth = 0.8; for (let i = 0; i < 6; i++) { x.beginPath(); x.moveTo(-19, -9 + i * 4); x.lineTo(19 - (i % 3) * 6, -9 + i * 4); x.stroke(); } x.restore();
    // PILOT: a bell jar over a seedling on a turned-wood base
    const px0 = X + 340;
    x.fillStyle = lin(x, px0 - 36, 0, px0 + 36, 0, [[0, '#4a2e18'], [0.4, '#9a6a40'], [1, '#3a2412']]); x.beginPath(); x.ellipse(px0, top - 4, 38, 9, 0, 0, 6.2832); x.fill(); x.fillRect(px0 - 38, top - 4, 76, 6);
    x.fillStyle = '#3b2a1c'; x.beginPath(); x.ellipse(px0, top - 7, 16, 4, 0, 0, 6.2832); x.fill();
    x.beginPath(); x.moveTo(px0 - 32, top - 6); x.lineTo(px0 - 32, top - 70); x.quadraticCurveTo(px0 - 32, top - 104, px0, top - 104); x.quadraticCurveTo(px0 + 32, top - 104, px0 + 32, top - 70); x.lineTo(px0 + 32, top - 6); x.closePath();
    x.fillStyle = 'rgba(210,232,236,0.16)'; x.fill();
    x.save(); x.clip(); glassShine(x, px0 - 32, top - 104, 64, 98); x.restore();
    x.fillStyle = '#d8dde0'; x.beginPath(); x.arc(px0, top - 108, 6, 0, 6.2832); x.fill();
    x.fillStyle = metal(x, px0 - 22, px0 + 22, 'brass'); rrect(x, px0 - 22, y1 - 36, 44, 11, 2); x.fill();
    // microscope
    const mx = X + 460;
    x.fillStyle = '#23272b'; rrect(x, mx - 24, top - 8, 48, 9, 3); x.fill();
    x.fillStyle = metal(x, mx - 6, mx + 8, 'steel'); x.beginPath(); x.moveTo(mx + 4, top - 8); x.quadraticCurveTo(mx + 26, top - 40, mx + 6, top - 70); x.lineTo(mx - 4, top - 64); x.quadraticCurveTo(mx + 12, top - 38, mx - 6, top - 8); x.fill();
    x.save(); x.translate(mx - 2, top - 66); x.rotate(-0.45); x.fillStyle = metal(x, -6, 6, 'steel'); x.fillRect(-5, -34, 10, 38); x.fillStyle = '#1b1e21'; x.fillRect(-6, -40, 12, 7); x.restore();
    x.fillStyle = '#2d3136'; x.fillRect(mx - 16, top - 30, 26, 4);
  }

  function reactor(x) {
    const { cx, base, r, glassTop, glassBot } = REACTOR;
    // pedestal
    x.fillStyle = metal(x, cx - r - 12, cx + r + 12, 'steel'); x.fillRect(cx - r - 10, glassBot + 12, (r + 10) * 2, base - glassBot - 12);
    x.fillStyle = '#2a2f35'; x.beginPath(); x.ellipse(cx, glassBot + 12, r + 10, 12, 0, 0, 6.2832); x.fill();
    x.fillStyle = metal(x, cx - r - 4, cx + r + 4, 'brass'); x.fillRect(cx - r - 4, glassBot - 2, (r + 4) * 2, 16);
    x.beginPath(); x.ellipse(cx, glassBot - 2, r + 4, 9, 0, 0, 6.2832); x.fill();
    // glass cylinder with liquid
    x.save(); rrect(x, cx - r, glassTop, r * 2, glassBot - glassTop, 6); x.clip();
    x.fillStyle = 'rgba(190,225,230,0.14)'; x.fillRect(cx - r, glassTop, r * 2, glassBot - glassTop);
    x.fillStyle = lin(x, cx - r, 0, cx + r, 0, [[0, 'rgba(20,110,100,0.9)'], [0.5, 'rgba(60,200,175,0.9)'], [1, 'rgba(15,90,85,0.9)']]); x.fillRect(cx - r, glassTop + 44, r * 2, glassBot - glassTop - 44);
    x.fillStyle = 'rgba(180,255,240,0.55)'; x.beginPath(); x.ellipse(cx, glassTop + 44, r, 7, 0, 0, 6.2832); x.fill();
    x.strokeStyle = 'rgba(10,50,48,0.75)'; x.lineWidth = 3;   // a glass coil down the middle
    x.beginPath(); for (let i = 0; i <= 60; i++) { const yy = glassTop + 56 + i * (glassBot - glassTop - 70) / 60, xx = cx + Math.sin(i * 0.52) * 18; i ? x.lineTo(xx, yy) : x.moveTo(xx, yy); } x.stroke();
    x.fillStyle = metal(x, cx - 5, cx + 5, 'steel'); x.fillRect(cx - 3, glassTop, 6, 58);
    glassShine(x, cx - r, glassTop, r * 2, glassBot - glassTop);
    x.restore();
    // caps, gauge, plaque
    x.fillStyle = metal(x, cx - r - 6, cx + r + 6, 'brass'); x.fillRect(cx - r - 6, glassTop - 16, (r + 6) * 2, 18); x.beginPath(); x.ellipse(cx, glassTop - 16, r + 6, 9, 0, 0, 6.2832); x.fill();
    x.fillStyle = '#2a2f35'; x.beginPath(); x.ellipse(cx, glassTop - 18, r - 10, 5, 0, 0, 6.2832); x.fill();
    x.fillStyle = metal(x, cx + r - 2, cx + r + 22, 'brass'); x.beginPath(); x.arc(cx + r + 12, glassBot - 60, 12, 0, 6.2832); x.fill();
    x.fillStyle = '#efe8d6'; x.beginPath(); x.arc(cx + r + 12, glassBot - 60, 9, 0, 6.2832); x.fill();
    x.strokeStyle = '#a02a1c'; x.lineWidth = 1.6; x.beginPath(); x.moveTo(cx + r + 12, glassBot - 60); x.lineTo(cx + r + 17, glassBot - 65); x.stroke();
    x.fillStyle = metal(x, cx - 24, cx + 24, 'brass'); rrect(x, cx - 22, base - 26, 44, 11, 2); x.fill();
  }

  function monitor(x, sx, sy, sw, sh) {
    x.fillStyle = '#16191c'; rrect(x, sx - 6, sy - 6, sw + 12, sh + 12, 5); x.fill();
    x.fillStyle = '#0b1622'; x.fillRect(sx, sy, sw, sh);
    x.fillStyle = 'rgba(255,255,255,0.06)'; poly(x, [[sx, sy], [sx + sw * 0.6, sy], [sx + sw * 0.25, sy + sh], [sx, sy + sh]]); x.fill();
  }
  function desk(x) {
    const { x: X, w, y0, y1, h } = DESK;
    const wood = K.pattern(x, K.woodTexture('oak', [[176, 126, 78], [104, 68, 38]], 640, 180, 4), 0.5);
    box(x, X, y0, y1, w, h, K.pattern(x, K.woodTexture('oaktop', [[190, 142, 92], [120, 82, 48]], 640, 180, 21), 0.45), wood);
    for (const [dx, dw] of [[14, 110], [w - 124, 110]]) { x.strokeStyle = 'rgba(0,0,0,0.4)'; x.lineWidth = 1.5; rrect(x, X + dx, y1 - h + 12, dw, 22, 2); x.stroke(); x.fillStyle = metal(x, X + dx + dw / 2 - 10, X + dx + dw / 2 + 10, 'brass'); rrect(x, X + dx + dw / 2 - 10, y1 - h + 21, 20, 4, 2); x.fill(); }
    x.fillStyle = metal(x, X + w / 2 - 88, X + w / 2 + 88, 'brass'); rrect(x, X + w / 2 - 88, y1 - 22, 176, 18, 2); x.fill();
    const top = y1 - h;
    // two monitors on stands
    for (const mx of [X + 40, X + 170]) { x.fillStyle = metal(x, mx + 50, mx + 62, 'steel'); x.fillRect(mx + 52, top - 34, 8, 26); x.fillStyle = '#23272b'; rrect(x, mx + 32, top - 12, 48, 7, 3); x.fill(); monitor(x, mx, top - 108, 112, 70); }
    // keyboard, mouse, mug, lamp
    x.fillStyle = '#2a2e33'; rrect(x, X + 100, top + 12 - (y1 - y0) + 30, 120, 14, 3); x.fill();
    x.fillStyle = 'rgba(255,255,255,0.08)'; for (let i = 0; i < 12; i++) x.fillRect(X + 104 + i * 9.6, top + 12 - (y1 - y0) + 33, 7, 3);
    x.fillStyle = '#2a2e33'; x.beginPath(); x.ellipse(X + 238, top - 20, 7, 5, 0, 0, 6.2832); x.fill();
    x.fillStyle = lin(x, X + w - 40, 0, X + w - 22, 0, [[0, '#b9b3a8'], [0.4, '#f4efe6'], [1, '#9c968b']]); rrect(x, X + w - 40, top - 42, 18, 20, 3); x.fill();
    x.strokeStyle = '#d8d2c6'; x.lineWidth = 2.5; x.beginPath(); x.arc(X + w - 21, top - 32, 5, -1.3, 1.3); x.stroke();
    const lx = X + 18;
    x.fillStyle = metal(x, lx - 12, lx + 12, 'brass'); x.beginPath(); x.ellipse(lx, top - 36, 14, 4, 0, 0, 6.2832); x.fill();
    x.strokeStyle = '#8c6a2c'; x.lineWidth = 3; x.beginPath(); x.moveTo(lx, top - 36); x.lineTo(lx + 6, top - 96); x.lineTo(lx + 34, top - 118); x.stroke();
    x.save(); x.translate(lx + 36, top - 118); x.rotate(0.6); x.beginPath(); x.moveTo(-6, -4); x.lineTo(6, -4); x.lineTo(16, 16); x.lineTo(-16, 16); x.closePath(); x.fillStyle = lin(x, -16, 0, 16, 0, [[0, '#1f3a30'], [0.4, '#4f8a70'], [1, '#14281f']]); x.fill(); x.restore();
  }
  function chair(x) {
    const { cx, cy } = CHAIR;
    x.fillStyle = '#1a1c1f'; for (const a of [0.3, 1.6, 2.9, 4.2, 5.5]) { x.beginPath(); x.moveTo(cx, cy + 6); x.lineTo(cx + Math.cos(a) * 30, cy + 10 + Math.sin(a) * 9); x.lineWidth = 4; x.strokeStyle = '#1a1c1f'; x.stroke(); }
    x.fillStyle = metal(x, cx - 4, cx + 4, 'steel'); x.fillRect(cx - 3, cy - 30, 6, 36);
    x.fillStyle = lin(x, 0, cy - 44, 0, cy - 24, [[0, '#6b3a26'], [1, '#3e2014']]); x.beginPath(); x.ellipse(cx, cy - 32, 32, 12, 0, 0, 6.2832); x.fill();
    x.fillStyle = lin(x, cx - 28, 0, cx + 28, 0, [[0, '#3e2014'], [0.45, '#7a4430'], [1, '#34190f']]); rrect(x, cx - 26, cy - 104, 52, 60, 12); x.fill();
    x.strokeStyle = 'rgba(255,220,190,0.12)'; x.lineWidth = 1; for (let i = 1; i < 4; i++) { x.beginPath(); x.moveTo(cx - 20, cy - 104 + i * 15); x.lineTo(cx + 20, cy - 104 + i * 15); x.stroke(); }
  }

  function dais(x) {
    const { cx, cy, rx, ry, h } = DAIS;
    x.fillStyle = lin(x, 0, cy - h, 0, cy + ry, [[0, '#9a917f'], [1, '#6a6254']]); x.beginPath(); x.ellipse(cx, cy, rx, ry, 0, 0, Math.PI); x.lineTo(cx - rx, cy - h); x.ellipse(cx, cy - h, rx, ry, 0, Math.PI, 0, true); x.closePath(); x.fill();
    x.fillStyle = K.pattern(x, K.grainTexture('dais', [184, 176, 160], 0.22, 0.05, 44), 1); x.beginPath(); x.ellipse(cx, cy - h, rx, ry, 0, 0, 6.2832); x.fill();
    x.strokeStyle = '#b89a52'; x.lineWidth = 3; x.beginPath(); x.ellipse(cx, cy - h, rx - 6, ry - 3, 0, 0, 6.2832); x.stroke();
    x.lineWidth = 1.5; for (const k of [0.72, 0.46]) { x.beginPath(); x.ellipse(cx, cy - h, rx * k, ry * k, 0, 0, 6.2832); x.stroke(); }
    x.strokeStyle = 'rgba(90,70,40,0.5)'; x.lineWidth = 1.2;
    for (let i = 0; i < 48; i++) { const a = i / 48 * 6.2832, r0 = i % 4 ? 0.8 : 0.76; x.beginPath(); x.moveTo(cx + Math.cos(a) * rx * r0, cy - h + Math.sin(a) * ry * r0); x.lineTo(cx + Math.cos(a) * rx * 0.86, cy - h + Math.sin(a) * ry * 0.86); x.stroke(); }
    // pedestal + lens sphere
    x.fillStyle = metal(x, cx - 16, cx + 16, 'brass'); x.fillRect(cx - 14, cy - h - 46, 28, 46); x.beginPath(); x.ellipse(cx, cy - h, 14, 5, 0, 0, Math.PI); x.fill();
    x.fillStyle = '#3b2c14'; x.beginPath(); x.ellipse(cx, cy - h - 46, 14, 5, 0, 0, 6.2832); x.fill();
    x.fillStyle = rad(x, cx, cy - h - 64, 1, 20, [[0, 'rgba(235,250,250,0.95)'], [0.4, 'rgba(150,210,215,0.55)'], [1, 'rgba(60,110,120,0.7)']], cx - 6, cy - h - 70);
    x.beginPath(); x.arc(cx, cy - h - 64, 19, 0, 6.2832); x.fill();
    x.fillStyle = metal(x, cx - 70, cx + 70, 'brass'); rrect(x, cx - 72, cy + ry - 16, 144, 17, 2); x.fill();
  }

  function rug(x) {
    const { cx, cy } = TABLE;
    x.save(); x.translate(cx, cy + 14); x.scale(1, 0.4);
    x.fillStyle = '#6b2a22'; x.beginPath(); x.arc(0, 0, 250, 0, 6.2832); x.fill();
    x.fillStyle = K.pattern(x, K.grainTexture('rug', [150, 64, 48], 0.35, 0.2, 61), 1); x.beginPath(); x.arc(0, 0, 236, 0, 6.2832); x.fill();
    for (const [r, c, lw] of [[222, '#d9b36a', 5], [200, '#2d3a5a', 9], [150, '#d9b36a', 3], [120, '#8a3a2a', 14]]) { x.strokeStyle = c; x.lineWidth = lw; x.beginPath(); x.arc(0, 0, r, 0, 6.2832); x.stroke(); }
    x.restore();
  }
  function stool(x, sx, sy) {
    x.fillStyle = '#4a3020'; for (const dx of [-11, 11]) x.fillRect(sx + dx - 2, sy - 34, 4, 34);
    x.fillStyle = lin(x, sx - 20, 0, sx + 20, 0, [[0, '#5a3a22'], [0.4, '#9a6a42'], [1, '#4a2e1a']]); x.fillRect(sx - 20, sy - 42, 40, 8);
    x.fillStyle = '#b0804f'; x.beginPath(); x.ellipse(sx, sy - 42, 20, 7, 0, 0, 6.2832); x.fill();
  }
  function whiteboard(x) {
    const { x: X, w, y, h } = BOARD;
    x.strokeStyle = '#5a4630'; x.lineWidth = 6; x.beginPath(); x.moveTo(X + 30, y + h); x.lineTo(X + 10, y + h + 88); x.moveTo(X + w - 30, y + h); x.lineTo(X + w - 10, y + h + 88); x.stroke();
    x.fillStyle = '#b8b4ad'; rrect(x, X - 5, y - 5, w + 10, h + 10, 4); x.fill();
    x.fillStyle = lin(x, X, y, X + w, y + h, [[0, '#f7f6f2'], [1, '#e2e0da']]); x.fillRect(X, y, w, h);
    x.fillStyle = '#8f8a82'; x.fillRect(X, y + h, w, 5);
    // diagrams in marker + sticky notes
    x.strokeStyle = 'rgba(40,70,140,0.75)'; x.lineWidth = 2;
    rrect(x, X + 16, y + 38, 56, 28, 5); x.stroke(); rrect(x, X + 104, y + 30, 56, 28, 5); x.stroke(); rrect(x, X + 104, y + 86, 56, 28, 5); x.stroke();
    x.beginPath(); x.moveTo(X + 72, y + 52); x.lineTo(X + 104, y + 44); x.moveTo(X + 72, y + 52); x.lineTo(X + 104, y + 100); x.stroke();
    x.strokeStyle = 'rgba(170,50,40,0.7)'; x.beginPath(); x.moveTo(X + 16, y + 118); x.bezierCurveTo(X + 40, y + 96, X + 60, y + 128, X + 86, y + 104); x.stroke();
    [['#f3d65a', X + 176, y + 30, -0.05], ['#f59ab0', X + 200, y + 70, 0.06], ['#9ad5f5', X + 170, y + 96, -0.08], ['#f3d65a', X + 40, y + 78, 0.04]].forEach(([c, sx, sy, a]) => { x.save(); x.translate(sx, sy); x.rotate(a); x.fillStyle = 'rgba(0,0,0,0.15)'; x.fillRect(1, 2, 26, 26); x.fillStyle = c; x.fillRect(0, 0, 26, 26); x.fillStyle = 'rgba(0,0,0,0.3)'; for (let i = 0; i < 3; i++) x.fillRect(4, 7 + i * 6, 16 - i * 3, 1.3); x.restore(); });
    x.fillStyle = metal(x, X + w / 2 - 100, X + w / 2 + 100, 'brass'); rrect(x, X + w / 2 - 102, y - 28, 204, 18, 2); x.fill();
  }
  function table(x) {
    const { cx, cy, rx, ry, h } = TABLE;
    x.fillStyle = '#3a2616'; x.fillRect(cx - 12, cy - h, 24, h); x.beginPath(); x.ellipse(cx, cy, 44, 12, 0, 0, 6.2832); x.fill();
    const wood = K.pattern(x, K.woodTexture('walnut', [[150, 100, 60], [74, 46, 26]], 640, 180, 9), 0.5);
    x.fillStyle = '#4a3020'; x.beginPath(); x.ellipse(cx, cy - h + 6, rx, ry, 0, 0, Math.PI); x.lineTo(cx - rx, cy - h); x.ellipse(cx, cy - h, rx, ry, 0, Math.PI, 0, true); x.closePath(); x.fill();
    x.fillStyle = wood; x.beginPath(); x.ellipse(cx, cy - h, rx, ry, 0, 0, 6.2832); x.fill();
    x.fillStyle = rad(x, cx - 30, cy - h - 20, 10, rx, [[0, 'rgba(255,240,220,0.18)'], [1, 'rgba(0,0,0,0.12)']]); x.beginPath(); x.ellipse(cx, cy - h, rx, ry, 0, 0, 6.2832); x.fill();
    // papers, a tablet, a mug, pencils
    const r = rng(77);
    for (let i = 0; i < 7; i++) { const a = r() * 6.28, d = 0.25 + r() * 0.55, px = cx + Math.cos(a) * rx * d, py = cy - h + Math.sin(a) * ry * d; x.save(); x.translate(px, py); x.scale(1, 0.42); x.rotate(r() * 6.28); x.fillStyle = 'rgba(0,0,0,0.18)'; x.fillRect(-15, -19, 32, 42); x.fillStyle = '#f4efe3'; x.fillRect(-16, -21, 32, 42); x.fillStyle = 'rgba(60,60,80,0.4)'; for (let k = 0; k < 6; k++) x.fillRect(-12, -16 + k * 6, 20 - (k % 2) * 6, 1.6); x.restore(); }
    x.save(); x.translate(cx + 48, cy - h - 6); x.scale(1, 0.45); x.rotate(0.4); x.fillStyle = '#1b1e22'; rrect(x, -22, -30, 44, 60, 5); x.fill(); x.fillStyle = '#18324a'; x.fillRect(-18, -26, 36, 52); x.restore();
    x.fillStyle = lin(x, cx - 70, 0, cx - 54, 0, [[0, '#2c4a6a'], [0.4, '#4a78a6'], [1, '#22384f']]); rrect(x, cx - 70, cy - h - 22, 16, 18, 3); x.fill();
    // a small table lamp
    x.fillStyle = metal(x, cx + 6, cx + 18, 'brass'); x.fillRect(cx + 10, cy - h - 44, 4, 38);
    x.beginPath(); x.moveTo(cx + 2, cy - h - 44); x.lineTo(cx + 22, cy - h - 44); x.lineTo(cx + 30, cy - h - 64); x.lineTo(cx - 6, cy - h - 64); x.closePath(); x.fillStyle = '#e8d8b0'; x.fill();
  }
  function analysis(x) {
    const { x: X, w, y0, y1, h } = ANAL;
    const sag = 16, top = y1 - h;
    // curved desk: front face follows a gentle arc
    x.beginPath(); x.moveTo(X, top); x.quadraticCurveTo(X + w / 2, top + sag * 2, X + w, top); x.lineTo(X + w, y1); x.quadraticCurveTo(X + w / 2, y1 + sag * 2, X, y1); x.closePath();
    x.fillStyle = K.pattern(x, K.woodTexture('walnut', [[150, 100, 60], [74, 46, 26]], 640, 180, 9), 0.55); x.fill();
    x.fillStyle = lin(x, 0, top, 0, y1 + sag, [[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0.3)']]); x.fill();
    x.beginPath(); x.moveTo(X, y0 - h); x.quadraticCurveTo(X + w / 2, y0 - h + sag * 2, X + w, y0 - h); x.lineTo(X + w, top); x.quadraticCurveTo(X + w / 2, top + sag * 2, X, top); x.closePath();
    x.fillStyle = lin(x, 0, y0 - h, 0, top, [[0, '#2b3034'], [1, '#3a4045']]); x.fill();
    x.strokeStyle = 'rgba(255,255,255,0.18)'; x.lineWidth = 1.2; x.beginPath(); x.moveTo(X, top); x.quadraticCurveTo(X + w / 2, top + sag * 2, X + w, top); x.stroke();
    for (let i = 0; i < 4; i++) {   // drawer fronts follow the curve
      const u0 = 0.04 + i * 0.24, u1 = u0 + 0.2, yOf = u => top + 4 * sag * u * (1 - u);
      x.strokeStyle = 'rgba(0,0,0,0.45)'; x.lineWidth = 1.5;
      x.beginPath(); x.moveTo(X + w * u0, yOf(u0) + 12); x.lineTo(X + w * u1, yOf(u1) + 12); x.lineTo(X + w * u1, yOf(u1) + 50); x.lineTo(X + w * u0, yOf(u0) + 50); x.closePath(); x.stroke();
      const um = (u0 + u1) / 2; x.fillStyle = metal(x, X + w * um - 10, X + w * um + 10, 'brass'); rrect(x, X + w * um - 10, yOf(um) + 20, 20, 4, 2); x.fill();
    }
    x.fillStyle = metal(x, X + w / 2 - 66, X + w / 2 + 66, 'brass'); rrect(x, X + w / 2 - 66, y1 - 5, 132, 18, 2); x.fill();
    // the curved ultrawide screen on two arms
    const S = SCREEN;
    x.fillStyle = metal(x, X + w / 2 - 6, X + w / 2 + 6, 'steel'); x.fillRect(X + w / 2 - 5, S.y + S.h, 10, (y0 - h) - (S.y + S.h) + 10);
    x.beginPath(); x.moveTo(S.x - 8, S.y - 8); x.quadraticCurveTo(S.x + S.w / 2, S.y + 6, S.x + S.w + 8, S.y - 8); x.lineTo(S.x + S.w + 8, S.y + S.h + 8); x.quadraticCurveTo(S.x + S.w / 2, S.y + S.h + 22, S.x - 8, S.y + S.h + 8); x.closePath(); x.fillStyle = '#15181b'; x.fill();
    screenPath(x); x.fillStyle = '#0a1420'; x.fill();
    // printer, paper stack, keyboard
    x.fillStyle = '#d9d6cf'; rrect(x, X + w - 86, y0 - h - 18, 62, 26, 4); x.fill(); x.fillStyle = '#2a2d31'; x.fillRect(X + w - 80, y0 - h - 10, 50, 3);
    x.fillStyle = '#f2ede2'; x.fillRect(X + 26, y0 - h - 4, 44, 14); x.fillStyle = 'rgba(0,0,0,0.15)'; for (let i = 0; i < 4; i++) x.fillRect(X + 26, y0 - h + 1 + i * 3, 44, 0.8);
    x.fillStyle = '#2a2e33'; rrect(x, X + w / 2 - 70, y0 - h + 22, 140, 14, 3); x.fill();
  }
  function screenPath(x) {
    const S = SCREEN; x.beginPath(); x.moveTo(S.x, S.y); x.quadraticCurveTo(S.x + S.w / 2, S.y + 14, S.x + S.w, S.y); x.lineTo(S.x + S.w, S.y + S.h); x.quadraticCurveTo(S.x + S.w / 2, S.y + S.h + 14, S.x, S.y + S.h); x.closePath();
  }

  function clockFace(x, cx, cy) {
    x.fillStyle = metal(x, cx - 30, cx + 30, 'brass'); x.beginPath(); x.arc(cx, cy, 30, 0, 6.2832); x.fill();
    x.fillStyle = '#f1ead8'; x.beginPath(); x.arc(cx, cy, 25, 0, 6.2832); x.fill();
    x.strokeStyle = '#3a3026'; for (let i = 0; i < 12; i++) { const a = i / 12 * 6.2832; x.lineWidth = i % 3 ? 1 : 2.2; x.beginPath(); x.moveTo(cx + Math.cos(a) * 20, cy + Math.sin(a) * 20); x.lineTo(cx + Math.cos(a) * 24, cy + Math.sin(a) * 24); x.stroke(); }
  }

  function plants(x, dark, front) {
    if (!front) {
      K.pot(x, 1522, 470, 46, 40, dark); K.fern(x, 1522, 432, 92, 5, dark);
      K.pot(x, 352, 432, 38, 34, dark); K.broadleaf(x, 352, 400, 70, 12, dark);
      for (const cx of WIN) { K.pot(x, cx - 54, WIN_BOT + 2, 20, 16, dark); K.fern(x, cx - 54, WIN_BOT - 14, 22, cx, dark); }
      K.ivy(x, 250, 0, 120, 20, 3, dark); K.ivy(x, 700, 0, 70, -10, 8, dark); K.ivy(x, 1180, 0, 90, 14, 13, dark); K.ivy(x, 1560, 0, 260, -30, 21, dark);
      return;
    }
    K.pot(x, 18, 950, 110, 90, dark); K.broadleaf(x, 18, 868, 150, 31, dark);
    K.pot(x, 1540, 940, 110, 90, dark); K.fern(x, 1540, 852, 200, 44, dark);
    K.ivy(x, 14, 0, 420, 40, 51, dark); K.ivy(x, 44, 0, 300, 20, 57, dark);
  }

  // ── bake ──────────────────────────────────────────────────────────────────
  function albedo(s) {
    const { c, x } = K.layer(s);
    paintWall(x, s); paintFloor(x, s); pipes(x); paintWindows(x);
    shelf(x, 440, 700, 101); shelf(x, 902, 1160, 202); shelf(x, 1372, 1470, 303);
    clockFace(x, 1510, 104);
    plants(x, false, false);
    rug(x); dais(x); rack(x); bench(x); reactor(x); PEND.forEach(cx => pendant(x, cx, PEND_Y)); desk(x); chair(x); whiteboard(x);
    const STOOLS = [-2.6, -1.9, -1.1, 1.2, 2.2, 2.9];
    STOOLS.forEach(a => { if (Math.sin(a) < 0) stool(x, TABLE.cx + Math.cos(a) * 200, TABLE.cy + Math.sin(a) * 78); });
    table(x);
    STOOLS.forEach(a => { if (Math.sin(a) >= 0) stool(x, TABLE.cx + Math.cos(a) * 200, TABLE.cy + Math.sin(a) * 78); });
    analysis(x);
    return c;
  }

  const SUN = { A: 0.3, B: 2.55 };
  function projectWall(x) { x.transform(1, 0, -SUN.A, -SUN.B, SUN.A * F, F * (1 + SUN.B)); }
  /** Standing objects: footprint + height, for contact shadows and day cast shadows. */
  const CASTERS = [
    { x0: BENCH.x, x1: BENCH.x + BENCH.w, y: BENCH.y1, h: BENCH.h },
    { x0: REACTOR.cx - 60, x1: REACTOR.cx + 60, y: REACTOR.base, h: REACTOR.base - REACTOR.glassTop + 20 },
    { x0: DESK.x, x1: DESK.x + DESK.w, y: DESK.y1, h: DESK.h },
    { x0: RACK.x, x1: RACK.x + RACK.w, y: RACK.y1, h: RACK.h },
    { x0: CHAIR.cx - 30, x1: CHAIR.cx + 30, y: CHAIR.cy + 8, h: 110 },
    { x0: TABLE.cx - TABLE.rx, x1: TABLE.cx + TABLE.rx, y: TABLE.cy + 6, h: TABLE.h },
    { x0: BOARD.x, x1: BOARD.x + BOARD.w, y: BOARD.y + BOARD.h + 88, h: 150 },
    { x0: ANAL.x, x1: ANAL.x + ANAL.w, y: ANAL.y1 + 10, h: ANAL.h },
    { x0: DAIS.cx - 20, x1: DAIS.cx + 20, y: DAIS.cy - DAIS.h, h: 80 },
  ];
  function lightLayer(s, day) {
    const { c, x } = K.layer(s);
    x.fillStyle = day ? 'rgb(184,178,168)' : 'rgb(38,48,70)'; x.fillRect(0, 0, VW, VH);
    // the wall is darker than the floor at night (no light reaches up there)
    if (!day) { x.fillStyle = lin(x, 0, 0, 0, F, [[0, 'rgba(0,0,0,0.35)'], [1, 'rgba(0,0,0,0)']]); x.fillRect(0, 0, VW, F); }
    else { x.fillStyle = lin(x, 0, 0, 0, F, [[0, 'rgba(0,0,0,0.18)'], [1, 'rgba(0,0,0,0)']]); x.fillRect(0, 0, VW, F); }
    // window light projected onto the floor — bars and all (day: sun; night: moon, one window only)
    const shaft = K.layer(s);
    for (const [i, cx] of WIN.entries()) {
      if (!day && i !== 0) continue;
      shaft.x.save(); projectWall(shaft.x);
      windowGlass(shaft.x, cx); shaft.x.fillStyle = day ? 'rgba(255,238,205,0.72)' : 'rgba(120,150,210,0.32)'; shaft.x.fill();
      shaft.x.globalCompositeOperation = 'destination-out'; windowBars(shaft.x, cx, 'rgba(0,0,0,1)', 7);
      shaft.x.restore();
    }
    // bars must not make black: take the shaft's alpha only
    const soft = K.blurred(shaft.c, 3);
    x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.globalCompositeOperation = 'lighter';
    const tint = K.canvas(soft.width, soft.height), tx = tint.getContext('2d'); tx.drawImage(soft, 0, 0);
    tx.globalCompositeOperation = 'source-in'; tx.fillStyle = day ? 'rgba(255,238,206,1)' : 'rgba(110,140,205,0.55)'; tx.fillRect(0, 0, tint.width, tint.height);
    if (day) { x.drawImage(tint, 0, 0); }   // twice by day: a sunlit patch is much brighter than the shade
    x.drawImage(tint, 0, 0); x.restore();
    // the wall around each window catches a little bounce light
    for (const cx of WIN) glow(x, cx, WIN_BOT - 40, 170, day ? [255, 244, 220] : [70, 90, 140], day ? 0.28 : (cx === WIN[0] ? 0.18 : 0.05), 0.6);
    if (!day) {
      glow(x, REACTOR.cx, 230, 380, [60, 225, 200], 0.5, 0.8);
      for (const cx of PEND) glow(x, cx, 236, 250, [255, 196, 130], 0.55, 0.62);
      glow(x, DESK.x + 60, 262, 270, [255, 186, 115], 0.7, 0.7);
      glow(x, DESK.x + 200, 240, 220, [110, 160, 255], 0.3, 0.7);
      glow(x, SCREEN.x + SCREEN.w / 2, 640, 340, [100, 150, 255], 0.42, 0.62);
      glow(x, DAIS.cx, DAIS.cy - 30, 230, [70, 225, 205], 0.36, 0.5);
      glow(x, TABLE.cx + 12, TABLE.cy - 70, 260, [255, 190, 120], 0.58, 0.62);
      glow(x, RACK.x + 120, 300, 150, [90, 255, 150], 0.22, 0.9);
      glow(x, RACK.x + RACK.w / 2, 150, 260, [255, 200, 140], 0.55, 1.35);
      for (const [px, py] of [[480, 110], [960, 60], [1100, 160], [1420, 110]]) glow(x, px, py, 60, [70, 230, 200], 0.18);
    } else {
      glow(x, VW / 2, 520, 900, [255, 250, 240], 0.12, 0.5);
    }
    // shadows: day = long cast shadows away from the windows + contact; night = contact only
    const sh = K.layer(s);
    sh.x.fillStyle = '#000';
    for (const o of CASTERS) {
      if (day) {
        const L = o.h * 1.15, dx = SUN.A * L * 0.4;
        sh.x.globalAlpha = 0.5; poly(sh.x, [[o.x0, o.y - 4], [o.x1, o.y - 4], [o.x1 + dx, o.y + L * 0.55], [o.x0 + dx, o.y + L * 0.55]]); sh.x.fill();
      }
      sh.x.globalAlpha = 1; contact(sh.x, (o.x0 + o.x1) / 2, o.y + 2, (o.x1 - o.x0) * 0.62, 16, day ? 0.55 : 0.7);
    }
    contact(sh.x, DAIS.cx, DAIS.cy + 4, DAIS.rx * 1.05, DAIS.ry * 0.9, 0.45);
    for (const [px, py, r] of [[18, 950, 110], [1540, 940, 110], [1522, 474, 40], [352, 434, 32]]) contact(sh.x, px, py, r, 12, 0.6);
    const sb = K.blurred(sh.c, day ? 7 : 5);
    x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.globalCompositeOperation = 'multiply';
    const inv = K.canvas(sb.width, sb.height), ix = inv.getContext('2d'); ix.fillStyle = '#fff'; ix.fillRect(0, 0, inv.width, inv.height); ix.globalCompositeOperation = 'destination-out'; ix.globalAlpha = day ? 0.75 : 0.55; ix.drawImage(sb, 0, 0);
    ix.globalCompositeOperation = 'destination-over'; ix.globalAlpha = 1; ix.fillStyle = day ? 'rgb(96,86,78)' : 'rgb(40,40,48)'; ix.fillRect(0, 0, inv.width, inv.height);
    x.drawImage(inv, 0, 0); x.restore();
    return c;
  }

  function emissiveLayer(s, day) {
    const { c, x } = K.layer(s);
    // window skies
    for (const [i, cx] of WIN.entries()) {
      x.save(); windowGlass(x, cx); x.clip();
      if (day) {
        x.fillStyle = lin(x, 0, WIN_TOP, 0, WIN_BOT, [[0, '#9ec9e8'], [0.55, '#dcebf0'], [1, '#f4f0dc']]); x.fillRect(cx - WIN_R, WIN_TOP, WIN_R * 2, WIN_BOT - WIN_TOP);
        const r = rng(cx);   // the garden outside: soft tree canopy
        for (let k = 0; k < 22; k++) { const bx = cx - WIN_R + r() * WIN_R * 2, by = 110 + r() * 70, br = 14 + r() * 26; x.fillStyle = hsl(95 + r() * 30, 30 + r() * 15, 52 + r() * 16, 0.85); x.beginPath(); x.arc(bx, by, br, 0, 6.2832); x.fill(); }
        if (i === 2) glow(x, cx + 40, 40, 70, [255, 250, 230], 0.9);
      } else {
        x.fillStyle = lin(x, 0, WIN_TOP, 0, WIN_BOT, [[0, '#0c1630'], [1, '#1c2c4a']]); x.fillRect(cx - WIN_R, WIN_TOP, WIN_R * 2, WIN_BOT - WIN_TOP);
        const r = rng(cx + 9); for (let k = 0; k < 26; k++) { x.fillStyle = `rgba(230,236,255,${0.3 + r() * 0.6})`; x.fillRect(cx - WIN_R + r() * WIN_R * 2, WIN_TOP + r() * 120, 1.4, 1.4); }
        if (i === 0) { glow(x, cx + 24, 62, 40, [220, 230, 255], 0.5); x.fillStyle = '#eef2ff'; x.beginPath(); x.arc(cx + 24, 62, 13, 0, 6.2832); x.fill(); }
        const r2 = rng(cx + 3); for (let k = 0; k < 14; k++) { x.fillStyle = 'rgba(8,14,24,0.95)'; x.beginPath(); x.arc(cx - WIN_R + r2() * WIN_R * 2, 150 + r2() * 40, 16 + r2() * 20, 0, 6.2832); x.fill(); }
      }
      x.restore();
      windowBars(x, cx, '#000', 4.5);
    }
    const k = day ? 0.45 : 1;
    // screens (their base glow; the content is live)
    x.globalAlpha = k;
    for (const mx of [DESK.x + 40, DESK.x + 170]) { x.fillStyle = lin(x, 0, DESK.y1 - DESK.h - 108, 0, DESK.y1 - DESK.h - 38, [[0, '#1d3f66'], [1, '#12283f']]); x.fillRect(mx, DESK.y1 - DESK.h - 108, 112, 70); }
    screenPath(x); x.fillStyle = lin(x, 0, SCREEN.y, 0, SCREEN.y + SCREEN.h, [[0, '#183a60'], [1, '#0f2238']]); x.fill();
    // the reactor liquid
    x.globalAlpha = day ? 0.18 : 0.42;
    x.save(); rrect(x, REACTOR.cx - REACTOR.r, REACTOR.glassTop + 44, REACTOR.r * 2, REACTOR.glassBot - REACTOR.glassTop - 44, 6); x.clip();
    x.fillStyle = lin(x, REACTOR.cx - REACTOR.r, 0, REACTOR.cx + REACTOR.r, 0, [[0, 'rgba(6,60,56,1)'], [0.3, 'rgba(30,170,150,1)'], [0.5, 'rgba(120,255,225,1)'], [0.7, 'rgba(30,170,150,1)'], [1, 'rgba(6,60,56,1)']]); x.fillRect(REACTOR.cx - REACTOR.r, 0, REACTOR.r * 2, VH);
    x.fillStyle = lin(x, 0, REACTOR.glassTop + 44, 0, REACTOR.glassBot, [[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0.45)']]); x.globalCompositeOperation = 'destination-out'; x.fillRect(REACTOR.cx - REACTOR.r, 0, REACTOR.r * 2, VH);
    x.globalAlpha = 1; x.strokeStyle = '#000'; x.lineWidth = 4;
    x.beginPath(); for (let i = 0; i <= 60; i++) { const yy = REACTOR.glassTop + 56 + i * (REACTOR.glassBot - REACTOR.glassTop - 70) / 60, xx = REACTOR.cx + Math.sin(i * 0.52) * 18; i ? x.lineTo(xx, yy) : x.moveTo(xx, yy); } x.stroke();
    x.fillRect(REACTOR.cx - 4, REACTOR.glassTop, 8, 60);
    x.restore();
    x.globalAlpha = 1;
    if (!day) {
      // lamps: shade undersides, the desk lamp, the table lamp, glowing specimen jars
      x.fillStyle = 'rgba(255,214,150,0.95)'; x.beginPath(); x.ellipse(RACK.x + RACK.w / 2, 70, 16, 3.5, 0, 0, 6.2832); x.fill();
      for (const cx of PEND) { x.fillStyle = 'rgba(255,214,150,1)'; x.beginPath(); x.ellipse(cx, PEND_Y + 8, 26, 4.5, 0, 0, 6.2832); x.fill(); }
      x.save(); x.translate(DESK.x + 54, DESK.y1 - DESK.h - 118); x.rotate(0.6); x.fillStyle = 'rgba(255,210,140,1)'; x.beginPath(); x.ellipse(0, 16, 15, 4, 0, 0, 6.2832); x.fill(); x.restore();
      x.fillStyle = 'rgba(255,214,150,0.85)'; poly(x, [[TABLE.cx + 2, TABLE.cy - TABLE.h - 44], [TABLE.cx + 22, TABLE.cy - TABLE.h - 44], [TABLE.cx + 30, TABLE.cy - TABLE.h - 64], [TABLE.cx - 6, TABLE.cy - TABLE.h - 64]]); x.fill();
      for (const [px, py] of [[480, 110], [960, 60], [1100, 160], [1420, 110]]) { x.fillStyle = 'rgba(80,240,210,0.9)'; rrect(x, px - 6, py - 12, 12, 16, 3); x.fill(); }
      x.strokeStyle = 'rgba(80,230,210,0.55)'; x.lineWidth = 1.5; x.beginPath(); x.ellipse(DAIS.cx, DAIS.cy - DAIS.h, DAIS.rx * 0.46, DAIS.ry * 0.46, 0, 0, 6.2832); x.stroke();
      x.fillStyle = 'rgba(170,240,240,0.8)'; x.beginPath(); x.arc(DAIS.cx, DAIS.cy - DAIS.h - 64, 12, 0, 6.2832); x.fill();
    }
    return c;
  }

  function foreground(s, dark) {   // near plants, drawn slightly out of focus (depth of field)
    const { c, x } = K.layer(s); plants(x, dark, true); return c;
  }

  const cache = {};
  let albedoCache = {};
  function bake(theme, s) {
    const key = theme + '@' + s; if (cache[key]) return cache[key];
    const day = theme === 'day';
    const A = albedoCache[s] || (albedoCache[s] = albedo(s));
    const Lc = lightLayer(s, day), E = emissiveLayer(s, day);
    const out = K.canvas(VW * s, VH * s), o = out.getContext('2d');
    o.drawImage(A, 0, 0);
    o.globalCompositeOperation = 'multiply'; o.drawImage(Lc, 0, 0);
    o.globalCompositeOperation = 'lighter'; o.drawImage(E, 0, 0);
    if (!day) {   // a honed floor mirrors the glowing things, stretched and soft
      const refl = K.layer(s);
      for (const [cx, cy, rw, col, a] of [[REACTOR.cx, REACTOR.base + 70, 60, [80, 240, 210], 0.28], [SCREEN.x + SCREEN.w / 2, ANAL.y1 + 60, 180, [90, 140, 255], 0.14],
        [DESK.x + 60, DESK.y1 + 40, 60, [255, 190, 120], 0.2], [TABLE.cx + 12, TABLE.cy + 50, 50, [255, 190, 120], 0.14], [DAIS.cx, DAIS.cy + 50, 90, [80, 230, 210], 0.12]]) glow(refl.x, cx, cy, rw * 1.2, col, a, 1.6);
      o.save(); o.globalCompositeOperation = 'lighter'; o.drawImage(K.blurred(refl.c, 4), 0, 0); o.restore();
    }
    o.globalAlpha = day ? 0.35 : 0.8; o.drawImage(K.blurred(E, 6), 0, 0);
    o.globalAlpha = day ? 0.2 : 0.55; o.drawImage(K.blurred(E, 22), 0, 0);
    o.globalAlpha = 1;
    // foreground plants: lit like the scene, softened
    const fg = foreground(s, !day), fl = K.canvas(out.width, out.height), fx = fl.getContext('2d');
    fx.drawImage(fg, 0, 0); fx.globalCompositeOperation = 'multiply'; fx.drawImage(Lc, 0, 0); fx.globalCompositeOperation = 'destination-in'; fx.drawImage(fg, 0, 0);
    o.globalCompositeOperation = 'source-over'; o.drawImage(K.blurred(fl, 2), 0, 0);
    // atmosphere + grade
    o.setTransform(s, 0, 0, s, 0, 0);
    if (day) {
      o.globalCompositeOperation = 'screen';
      for (const cx of WIN) {   // faint sunbeams in the air, window → floor
        o.save(); o.beginPath(); o.moveTo(cx - WIN_R, WIN_TOP + 20); o.lineTo(cx + WIN_R, WIN_TOP + 20); o.lineTo(cx + WIN_R + SUN.A * 180 + 40, F + SUN.B * 170); o.lineTo(cx - WIN_R + SUN.A * 30, F + SUN.B * 40); o.closePath();
        o.fillStyle = lin(o, 0, WIN_TOP, 0, F + 400, [[0, 'rgba(255,240,210,0.16)'], [1, 'rgba(255,240,210,0)']]); o.fill(); o.restore();
      }
      o.fillStyle = lin(o, 0, 0, 0, VH, [[0, 'rgba(255,246,228,0.14)'], [1, 'rgba(255,246,228,0.02)']]); o.fillRect(0, 0, VW, VH);
      o.globalCompositeOperation = 'multiply';
      o.fillStyle = rad(o, VW / 2, VH * 0.55, VH * 0.45, VW * 0.72, [[0, 'rgba(255,255,255,1)'], [1, 'rgba(214,196,170,1)']]); o.fillRect(0, 0, VW, VH);
    } else {
      o.globalCompositeOperation = 'multiply';
      o.fillStyle = rad(o, VW / 2, VH * 0.5, VH * 0.35, VW * 0.7, [[0, 'rgba(255,255,255,1)'], [1, 'rgba(40,50,70,1)']]); o.fillRect(0, 0, VW, VH);
      o.globalCompositeOperation = 'soft-light'; o.fillStyle = 'rgba(40,120,140,0.25)'; o.fillRect(0, 0, VW, VH);
    }
    o.globalCompositeOperation = 'source-over';
    cache[key] = out;
    return out;
  }

  // ── live layer (design units; called every frame over the bake) ────────────
  const motes = Array.from({ length: 44 }, (_, i) => ({ x: hash2(i, 1, 5), y: hash2(i, 2, 5), s: 0.4 + hash2(i, 3, 5), p: hash2(i, 4, 5) * 6.28 }));
  function live(x, theme, t, st) {
    const day = theme === 'day', act = clamp((st.slotsUse || 0) + (st.busy || 0) * 0.5, 0, 4);
    x.save();
    const add = day ? 'screen' : 'lighter';
    // compute rack LEDs — one per compute slot (lit = in use) + small activity LEDs
    const cap = Math.max(1, st.slotsCap || 1), px0 = RACK.x + 84, py0 = RACK.y1 - RACK.h + 34;
    for (let i = 0; i < Math.min(cap, 8); i++) {
      const on = i < (st.slotsUse || 0), yy = py0 + i * 22, pulse = on ? 0.65 + 0.35 * Math.sin(t * 5 + i) : 0.25;
      x.fillStyle = on ? `rgba(90,255,150,${pulse})` : 'rgba(255,170,60,0.45)'; K.rrect(x, px0, yy, 44, 8, 2); x.fill();
      if (on && !day) { x.globalCompositeOperation = 'lighter'; K.glow(x, px0 + 22, yy + 4, 26, [90, 255, 150], 0.35 * pulse); x.globalCompositeOperation = 'source-over'; }
      x.fillStyle = 'rgba(200,220,230,0.5)'; x.font = '8px ui-monospace, monospace'; x.textAlign = 'left'; x.fillText('SLOT ' + (i + 1), px0 + 50, yy + 7);
    }
    for (let i = 0; i < 6; i++) { const on = Math.sin(t * (3 + i) + i * 2) > 0.4 - act * 0.15; x.fillStyle = on ? 'rgba(120,220,255,0.9)' : 'rgba(60,80,90,0.6)'; x.fillRect(px0 + i * 9, RACK.y1 - 40, 5, 4); }
    // the reactor: bubbles rising faster with more compute in use
    x.save(); K.rrect(x, REACTOR.cx - REACTOR.r, REACTOR.glassTop + 46, REACTOR.r * 2, REACTOR.glassBot - REACTOR.glassTop - 48, 6); x.clip();
    const nb = 7 + Math.round(act * 5);
    for (let i = 0; i < nb; i++) {
      const sp = 22 + (i % 5) * 9 + act * 10, ph = hash2(i, 7, 3), yy = REACTOR.glassBot - ((t * sp + ph * 400) % (REACTOR.glassBot - REACTOR.glassTop - 50)), xx = REACTOR.cx - REACTOR.r + 8 + hash2(i, 8, 3) * (REACTOR.r * 2 - 16) + Math.sin(t * 2 + i) * 3;
      x.strokeStyle = `rgba(210,255,245,${day ? 0.55 : 0.8})`; x.lineWidth = 1.2; x.beginPath(); x.arc(xx, yy, 1.5 + (i % 3), 0, 6.2832); x.stroke();
    }
    x.restore();
    if (!day) { x.globalCompositeOperation = 'lighter'; K.glow(x, REACTOR.cx, 210, 120 + act * 20, [80, 255, 215], 0.12 + 0.05 * Math.sin(t * 1.7), 1.6); x.globalCompositeOperation = 'source-over'; }
    // steam from the smoke flask
    const fx = BENCH.x + 150, fy = BENCH.y1 - BENCH.h - 84;
    for (let i = 0; i < 7; i++) {
      const u = ((t * 0.25 + i / 7) % 1), yy = fy - u * 70, xx = fx + Math.sin(u * 5 + i) * 8 * u;
      x.fillStyle = `rgba(${day ? '255,255,255' : '200,230,225'},${0.22 * Math.sin(u * Math.PI)})`; x.beginPath(); x.arc(xx, yy, 5 + u * 13, 0, 6.2832); x.fill();
    }
    // mug steam
    for (let i = 0; i < 3; i++) { const u = ((t * 0.3 + i / 3) % 1); x.fillStyle = `rgba(255,255,255,${0.14 * Math.sin(u * Math.PI)})`; x.beginPath(); x.arc(DESK.x + DESK.w - 31 + Math.sin(u * 6) * 3, DESK.y1 - DESK.h - 46 - u * 26, 3 + u * 5, 0, 6.2832); x.fill(); }
    // improve/debug monitors: scrolling code while an agent works in the lab, a dim idle glow otherwise
    for (const [j, mx] of [DESK.x + 40, DESK.x + 170].entries()) {
      const sy = DESK.y1 - DESK.h - 108;
      x.save(); x.beginPath(); x.rect(mx, sy, 112, 70); x.clip();
      if (st.busy) {
        const off = (t * 14 + j * 30) % 8;
        for (let r = -1; r < 10; r++) { const yy = sy + 4 + r * 8 - off + 8; const w = 20 + hash2(r + Math.floor(t * 1.75), j, 9) * 70; const hue = [200, 140, 40, 320][Math.floor(hash2(r + Math.floor(t * 1.75), j, 3) * 4)]; x.fillStyle = hsl(hue, 70, 70, day ? 0.6 : 0.85); x.fillRect(mx + 6 + (r % 3) * 6, yy, w, 2.6); }
      } else { x.fillStyle = `rgba(90,140,200,${0.12 + 0.05 * Math.sin(t + j)})`; x.fillRect(mx, sy, 112, 70); }
      x.restore();
    }
    // analysis console: bars + a trend line drawn from the lab's projects (live data, seeded look)
    x.save(); screenPath(x); x.clip();
    const S = SCREEN, n = Math.max(4, Math.min(12, (st.nAnalysis || 0) * 3 + 6));
    x.strokeStyle = 'rgba(120,170,230,0.18)'; x.lineWidth = 1; for (let g = 1; g < 4; g++) { x.beginPath(); x.moveTo(S.x + 12, S.y + g * S.h / 4 + 6); x.lineTo(S.x + S.w * 0.55, S.y + g * S.h / 4 + 6); x.stroke(); }
    for (let i = 0; i < n; i++) { const hh = (0.25 + 0.65 * (0.5 + 0.5 * Math.sin(i * 1.3 + (st.seed || 0) + t * 0.15))) * (S.h - 26); x.fillStyle = hsl(195 + i * 6, 70, 62, day ? 0.6 : 0.85); x.fillRect(S.x + 16 + i * ((S.w * 0.52) / n), S.y + S.h - 8 - hh + 6, (S.w * 0.52) / n - 4, hh); }
    x.strokeStyle = day ? 'rgba(255,190,90,0.8)' : 'rgba(255,200,110,0.95)'; x.lineWidth = 2; x.beginPath();
    for (let i = 0; i <= 40; i++) { const xx = S.x + S.w * 0.6 + i * (S.w * 0.36 / 40), yy = S.y + S.h * 0.75 - (0.3 + 0.35 * Math.sin(i * 0.25 + (st.seed || 0)) + i / 40 * 0.25) * S.h * 0.6 + 8; i ? x.lineTo(xx, yy) : x.moveTo(xx, yy); }
    x.stroke();
    const sweep = S.x + ((t * 60) % S.w); x.fillStyle = 'rgba(160,210,255,0.08)'; x.fillRect(sweep, S.y, 18, S.h + 20);
    x.restore();
    // the quality dais: a scanning ring
    const qa = t * 0.9;
    x.save(); x.globalCompositeOperation = add; x.strokeStyle = day ? 'rgba(255,230,150,0.55)' : 'rgba(90,240,220,0.75)'; x.lineWidth = day ? 2 : 2.5;
    x.beginPath(); x.ellipse(DAIS.cx, DAIS.cy - DAIS.h, DAIS.rx * 0.72, DAIS.ry * 0.72, 0, qa, qa + 1.4); x.stroke();
    x.beginPath(); x.ellipse(DAIS.cx, DAIS.cy - DAIS.h, DAIS.rx * 0.72, DAIS.ry * 0.72, 0, qa + Math.PI, qa + Math.PI + 1.4); x.stroke();
    x.restore();
    // pilot seedling sways in its jar
    const sx0 = BENCH.x + 340, sy0 = BENCH.y1 - BENCH.h - 14, sw = Math.sin(t * 1.3) * 0.08;
    x.save(); x.translate(sx0, sy0); x.rotate(sw); x.strokeStyle = '#4a7a3a'; x.lineWidth = 2; x.beginPath(); x.moveTo(0, 0); x.quadraticCurveTo(2, -20, 0, -38); x.stroke();
    for (const [a, yy] of [[-0.9, -22], [0.8, -30], [-0.4, -38]]) { x.save(); x.translate(0, yy); x.rotate(a - Math.PI / 2); K.leaf(x, 16, 7, day ? '#5c9a44' : '#3f7a34', 'rgba(255,255,255,0.2)'); x.restore(); }
    x.restore();
    // the wall clock tells the real time
    const now = new Date(), hA = ((now.getHours() % 12) + now.getMinutes() / 60) / 12 * 6.2832 - Math.PI / 2, mA = (now.getMinutes() + now.getSeconds() / 60) / 60 * 6.2832 - Math.PI / 2;
    x.strokeStyle = '#2a221a'; x.lineCap = 'round';
    x.lineWidth = 3; x.beginPath(); x.moveTo(1510, 104); x.lineTo(1510 + Math.cos(hA) * 12, 104 + Math.sin(hA) * 12); x.stroke();
    x.lineWidth = 2; x.beginPath(); x.moveTo(1510, 104); x.lineTo(1510 + Math.cos(mA) * 19, 104 + Math.sin(mA) * 19); x.stroke();
    // dust in the sunbeams (day) / drifting spores (night)
    for (const m of motes) {
      const u = (m.y + t * 0.012 * m.s) % 1, xx = (m.x * VW + Math.sin(t * 0.3 + m.p) * 20), yy = F + u * (VH - F) - 60;
      if (day) { const inBeam = WIN.some(cx => Math.abs(xx - (cx + SUN.A * (yy - F) * 0.35)) < WIN_R + 20) && yy < 640; if (!inBeam) continue; x.fillStyle = `rgba(255,248,225,${0.55 * Math.sin(u * Math.PI)})`; x.beginPath(); x.arc(xx, yy, 1.2 + m.s, 0, 6.2832); x.fill(); }
      else { x.globalCompositeOperation = 'lighter'; K.glow(x, xx, yy, 7 + m.s * 3, [90, 240, 210], 0.25 * Math.sin(u * Math.PI) * (0.6 + 0.4 * Math.sin(t * 2 + m.p))); x.globalCompositeOperation = 'source-over'; }
    }
    // plaque lettering (live so it stays crisp at any zoom)
    const ink = day ? '#2d2310' : '#fbecc4';
    const eng = day ? { font: '"Nunito", system-ui, sans-serif', weight: 800, spacing: 1.2, shadow: 'rgba(255,240,200,0.5)', blur: 0, dy: 0.8 }
      : { font: '"Nunito", system-ui, sans-serif', weight: 800, spacing: 1.2, shadow: 'rgba(0,0,0,0.9)', blur: 3, dy: 0.5 };
    K.text(x, 'EXPERIMENTS', BENCH.x + BENCH.w / 2, BENCH.y1 - 13, 12, ink, eng);
    K.text(x, 'SMOKE', BENCH.x + 150, BENCH.y1 - 30.5, 7, ink, eng);
    K.text(x, 'PILOT', BENCH.x + 340, BENCH.y1 - 30.5, 7, ink, eng);
    K.text(x, 'FULL', REACTOR.cx, REACTOR.base - 20.5, 7, ink, eng);
    K.text(x, 'IMPROVE · DEBUG', DESK.x + DESK.w / 2, DESK.y1 - 13, 12, ink, eng);
    K.text(x, 'QUALITY CHECK', DAIS.cx, DAIS.cy + DAIS.ry - 7.5, 11, ink, eng);
    K.text(x, 'IN-PROJECT IDEATION', BOARD.x + BOARD.w / 2, BOARD.y - 19, 11, ink, eng);
    K.text(x, 'ANALYSIS', ANAL.x + ANAL.w / 2, ANAL.y1 + 4, 12, ink, eng);
    K.text(x, 'COMPUTE', RACK.x + RACK.w / 2, RACK.y0 - RACK.h + 6, 8, ink, eng);
    x.restore();
  }

  /** Hoverable things, with live descriptions (design-unit rects). */
  function objects(st) {
    const use = st.slotsUse || 0, cap = st.slotsCap || 0;
    return [
      { id: 'rack', x: RACK.x, y: RACK.y0 - RACK.h, w: RACK.w, h: RACK.h + RACK.y1 - RACK.y0, label: `Compute · ${use} of ${cap || '?'} slot${cap === 1 ? '' : 's'} in use` },
      { id: 'reactor', x: REACTOR.cx - 60, y: REACTOR.glassTop - 24, w: 120, h: REACTOR.base - REACTOR.glassTop + 24, label: use ? 'FULL runs · bubbling (compute in use)' : 'FULL runs · idle' },
      { id: 'bench', x: BENCH.x, y: BENCH.y0 - BENCH.h - 110, w: BENCH.w, h: BENCH.y1 - BENCH.y0 + BENCH.h + 110, label: `Experiments · ${st.nActive || 0} active project${st.nActive === 1 ? '' : 's'}` },
      { id: 'desk', x: DESK.x, y: DESK.y0 - DESK.h - 110, w: DESK.w, h: DESK.y1 - DESK.y0 + DESK.h + 110, label: st.busy ? `Improve / debug · ${st.busy} agent${st.busy === 1 ? '' : 's'} working here` : 'Improve / debug · quiet' },
      { id: 'dais', x: DAIS.cx - DAIS.rx, y: DAIS.cy - DAIS.ry - 90, w: DAIS.rx * 2, h: DAIS.ry * 2 + 90, label: 'Quality check · the overseer audits claims here' },
      { id: 'ideate', x: BOARD.x, y: BOARD.y - 30, w: 420, h: TABLE.cy + 40 - BOARD.y + 30, label: 'In-project ideation · method approaches within the frozen problem' },
      { id: 'analysis', x: ANAL.x, y: SCREEN.y - 10, w: ANAL.w, h: ANAL.y1 + 30 - SCREEN.y, label: `Analysis · ${st.nAnalysis || 0} project${st.nAnalysis === 1 ? '' : 's'} in analysis` },
      { id: 'clock', x: 1478, y: 72, w: 64, h: 64, label: 'The lab clock · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
    ];
  }

  window.CodeRooms = window.CodeRooms || {};
  window.CodeRooms.lab = { name: 'The Lab', bake, live, objects, stations: STATIONS, paths: PATHS, aspect: VW / VH };
})();
