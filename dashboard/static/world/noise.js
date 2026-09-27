/* Vivarium world — deterministic noise + small maths helpers (no dependencies).
 * Everything procedural in the world (paper fibre, deckled edges, ink wobble, plant placement) is
 * seeded, so a room looks identical on every load and in every browser. */
(function () {
  'use strict';
  const W = (window.VivWorld = window.VivWorld || {});

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
  function strSeed(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const ease = { out: t => 1 - Math.pow(1 - t, 3), inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2), back: t => { const c = 1.6; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); } };

  W.noise = { hash2, vnoise, fbm, rng, strSeed, clamp, lerp, smooth, ease };
})();
