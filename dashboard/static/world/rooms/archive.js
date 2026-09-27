/* Room · the Archive — finished work at rest; its knowledge feeds the next idea (final). */
VivWorld.defineRoom({
  key: 'archive', title: 'The Archive', order: 2, floor: 1, size: [1440, 820],
  states: ['final'],
  shell: { wall: 'stone', floor: 'tiles', windows: [0.5], accent: 'wash.violet', banner: 'The Archive', seed: 51 },
  stations: {
    reproduce: { x: 0.26, y: 0.58 }, writeback: { x: 0.46, y: 0.575 }, secure: { x: 0.72, y: 0.58 },
    finalize: { x: 0.36, y: 0.87 }, rest: { x: 0.68, y: 0.88 },
  },
  stateStation: { final: 'rest' },
  roleStation: {},
  props: [
    { c: 'boxes', at: [0.18, 0.52], props: { w: 240, h: 210, label: 'Reproduce' } },
    { c: 'cabinet', at: [0.46, 0.495], props: { kind: 'catalog', w: 220, h: 220, label: 'Write-back' } },
    { c: 'cabinet', at: [0.72, 0.50], props: { kind: 'safe', w: 180, h: 200, label: 'Secure' } },
    { c: 'press', at: [0.24, 0.83], props: { label: 'Finalize' } },
    { c: 'rug', at: [0.78, 0.86], props: { w: 360 } },
    { c: 'armchair', at: [0.79, 0.85], props: {} },
    { c: 'plant', at: [0.92, 0.90], props: { kind: 'fern', size: 160, seed: 52 } },
    { c: 'lantern', at: [0.5, 0.21], props: { color: 'glow.primary' } },
    { c: 'plant', at: [0.05, 0.96], props: { kind: 'mushrooms', size: 90, seed: 53 } },
    { c: 'stringLights', at: [0.5, 0.13], props: { w: 1100, n: 12, swags: 2 } },
    { c: 'hangingPlant', at: [0.34, 0.25], props: { drop: 190 } },
    { c: 'crates', at: [0.60, 0.60], props: { w: 140 } },
    { c: 'crates', at: [0.10, 0.70], props: { kind: 'books', w: 110 } },
  ],
  paths: [[0.26, 0.60], [0.36, 0.64], [0.46, 0.60], [0.58, 0.62], [0.72, 0.60], [0.74, 0.72], [0.68, 0.90], [0.56, 0.84], [0.44, 0.90], [0.34, 0.80]],
});
