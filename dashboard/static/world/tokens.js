/* Vivarium world — the DESIGN LANGUAGE as data.
 *
 * Two "inks" of one paper diorama:
 *   day   — the ATELIER: parchment and card, sepia ink outlines with a slight hand wobble, watercolour
 *           washes, soft paper shadows, hand-lettered labels. (The spirit of the original parchment plates.)
 *   night — the CAVE: the same cut paper as deep teal card, lit from inside — cut-outs glow cyan, edges
 *           become faint luminous rims, mushrooms and specimens glow, spores drift. (The spirit of the
 *           original bioluminescent lab.)
 *
 * Components and rooms never hard-code colours: they name a token (`'paper.base'`, `'wash.teal'`,
 * `'glow.primary'`, …) and the painter resolves it for the active theme. Retune the whole world here.
 */
(function () {
  'use strict';
  const W = (window.VivWorld = window.VivWorld || {});

  const day = {
    name: 'day',
    paper: { base: '#efe3c6', light: '#f8f0dc', shade: '#dfcda6', deep: '#cbb385', card: '#e9d8b2', white: '#fbf6ea' },
    surface: { wall: '#ecdfc1', wallAlt: '#e3d2ad', floor: '#e2cfa7', floorLine: '#c9b085', ceiling: '#d9c49b', section: '#cdb488' },
    wood: { light: '#d8b688', mid: '#c19767', dark: '#9a7248', grain: '#7e5a36' },
    metal: { brass: '#d4b064', brassDark: '#a8843c', steel: '#b9c0bf', iron: '#6f6a60' },
    glass: { fill: '#e4efe9', rim: '#9fb8ae', liquid: '#8fd0c0', liquid2: '#b8d88f', liquid3: '#e8a58f' },
    plant: { leaf: '#9bba7c', leafLight: '#b9d197', leafDark: '#6f9058', stem: '#6d7f4a', pot: '#cf8e63', soil: '#6b4e33', mushroom: '#e7cfa6', cap: '#d9876c' },
    fabric: { rug: '#c7765e', rugAlt: '#6f8fa6', seat: '#b7754f', cloth: '#e9d3b8' },
    ink: { line: '#4a3521', soft: 'rgba(74,53,33,0.5)', faint: 'rgba(74,53,33,0.22)', red: '#a3483a', blue: '#40628a', width: 1.5, wobble: 0.8 },
    wash: { teal: 'rgba(93,165,152,0.34)', green: 'rgba(125,168,95,0.34)', rose: 'rgba(206,118,112,0.30)', ochre: 'rgba(214,164,74,0.30)', blue: 'rgba(96,136,186,0.30)', violet: 'rgba(150,120,180,0.26)' },
    glow: { primary: '#63d6c2', secondary: '#9fe7da', warm: '#f2c46a', accent: '#e8909e', screen: '#9cc8e6', strength: 0.28 },
    shadow: { color: '#56401f', alpha: 0.34, dx: 0.45, dy: 1.0, blur: 2.6 },
    edge: { deckle: 1.25, fibre: 0.07 },
    sky: { top: '#f4ecd6', bottom: '#eadcbd', far: '#dccdaa', mid: '#d2c099', near: '#c8b48c', cloud: 'rgba(255,252,242,0.75)', celestial: '#f7d98a' },
    label: { font: '"Newsreader","Iowan Old Style",Georgia,serif', color: '#4a3521', plate: '#f4e9cf' },
    grade: { grain: 0.05, vignette: 0.28, tint: 'rgba(255,240,210,0)' },
    ambient: 'dust',      // floating motes
  };

  const night = {
    name: 'night',
    paper: { base: '#173139', light: '#1f414a', shade: '#10252c', deep: '#0a181e', card: '#1a3840', white: '#26505a' },
    surface: { wall: '#122a31', wallAlt: '#0f242a', floor: '#11252b', floorLine: '#1f4a50', ceiling: '#0c1d23', section: '#0a171c' },
    wood: { light: '#2e4744', mid: '#253b39', dark: '#1a2b2a', grain: '#355652' },
    metal: { brass: '#6f7f63', brassDark: '#4e5b46', steel: '#4f6a6c', iron: '#2c3b3d' },
    glass: { fill: '#1a3e45', rim: '#5fd8c6', liquid: '#44e8cf', liquid2: '#9af07a', liquid3: '#ff9ac6' },
    plant: { leaf: '#1f564c', leafLight: '#2a7064', leafDark: '#143b35', stem: '#1c4a42', pot: '#2a3b44', soil: '#0c1a1d', mushroom: '#b8fff0', cap: '#5ff0d8' },
    fabric: { rug: '#3a2a4a', rugAlt: '#1f4a5a', seat: '#3a3048', cloth: '#223a44' },
    ink: { line: '#7fe9d7', soft: 'rgba(127,233,215,0.42)', faint: 'rgba(127,233,215,0.16)', red: '#ff8ab0', blue: '#8ab8ff', width: 1.05, wobble: 0.6 },
    wash: { teal: 'rgba(70,220,195,0.20)', green: 'rgba(120,230,120,0.16)', rose: 'rgba(255,120,190,0.16)', ochre: 'rgba(255,200,110,0.16)', blue: 'rgba(110,160,255,0.18)', violet: 'rgba(180,130,255,0.18)' },
    glow: { primary: '#5ff0d8', secondary: '#b0fff2', warm: '#ffcf7a', accent: '#ff8ad6', screen: '#7fb6ff', strength: 1.0 },
    shadow: { color: '#000000', alpha: 0.6, dx: 0.45, dy: 1.0, blur: 3.2 },
    edge: { deckle: 0.9, fibre: 0.05 },
    sky: { top: '#071419', bottom: '#0b1e24', far: '#0d2329', mid: '#0a1b20', near: '#07141a', cloud: 'rgba(90,200,190,0.06)', celestial: '#bff7ec' },
    label: { font: '"Newsreader","Iowan Old Style",Georgia,serif', color: '#c4fbef', plate: '#15333a' },
    grade: { grain: 0.06, vignette: 0.45, tint: 'rgba(20,80,90,0.10)' },
    ambient: 'spores',
  };

  /** Resolve 'group.key' (or a literal colour) for a theme. */
  function tok(theme, ref) {
    if (!ref || typeof ref !== 'string' || ref[0] === '#' || ref.startsWith('rgb')) return ref;
    const [g, k] = ref.split('.');
    const grp = theme[g];
    const v = grp && (k ? grp[k] : grp);
    if (v == null) throw new Error(`unknown design token '${ref}'`);
    return v;
  }
  /** '#rrggbb' → [r,g,b]; rgba() strings pass through parse. */
  function rgb(c) {
    if (c[0] === '#') { const n = parseInt(c.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255, 1]; }
    const m = c.match(/[\d.]+/g).map(Number); return [m[0], m[1], m[2], m[3] == null ? 1 : m[3]];
  }
  function shade(c, k) {   // k>0 lighten toward white, k<0 darken toward black
    const [r, g, b, a] = rgb(c), t = Math.abs(k), to = k > 0 ? 255 : 0;
    return `rgba(${Math.round(r + (to - r) * t)},${Math.round(g + (to - g) * t)},${Math.round(b + (to - b) * t)},${a})`;
  }
  function alpha(c, a) { const [r, g, b] = rgb(c); return `rgba(${r},${g},${b},${a})`; }
  function hexNum(c) { const [r, g, b] = rgb(c); return (r << 16) | (g << 8) | b; }

  W.tokens = { day, night, tok, rgb, shade, alpha, hexNum, themes: { day, night } };
})();
