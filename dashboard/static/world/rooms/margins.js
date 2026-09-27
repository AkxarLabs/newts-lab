/* Room · the Margins — out of play: parked ideas rest under cloths, killed ones dry in their jars (parked · killed). */
VivWorld.defineRoom({
  key: 'margins', title: 'The Margins', order: 1, floor: -1, size: [1280, 720],
  states: ['parked', 'killed'],
  shell: { wall: 'stone', floor: 'boards', windows: [], accent: 'wash.blue', banner: 'The Margins', seed: 61 },
  stations: {
    parked: { x: 0.26, y: 0.60 }, recorded: { x: 0.50, y: 0.61 }, killed: { x: 0.78, y: 0.66 }, revive: { x: 0.74, y: 0.86 },
  },
  stateStation: { parked: 'parked', killed: 'killed' },
  roleStation: {},
  props: [
    { c: 'shrouded', at: [0.20, 0.545], props: { w: 220, h: 190, label: 'Parked' } },
    { c: 'lectern', at: [0.50, 0.535], props: { label: 'Recorded' } },
    { c: 'jars', at: [0.78, 0.585], props: { w: 260, dry: true, label: 'Killed' } },
    { c: 'vessel', at: [0.68, 0.86], props: { kind: 'cloche', w: 110, h: 150, plant: 'sprout', hover: () => 'Revive · a killed idea can come back as a new seed' } },
    { c: 'lantern', at: [0.5, 0.22], props: {} },
    { c: 'plant', at: [0.08, 0.95], props: { kind: 'mushrooms', size: 90, seed: 62 } },
    { c: 'plant', at: [0.93, 0.93], props: { kind: 'mushrooms', size: 100, seed: 63 } },
    { c: 'stringLights', at: [0.5, 0.14], props: { w: 1000, n: 10, swags: 2 } },
    { c: 'crates', at: [0.36, 0.64], props: { w: 130 } },
    { c: 'crates', at: [0.86, 0.86], props: { kind: 'books', w: 110 } },
  ],
  paths: [[0.26, 0.62], [0.38, 0.68], [0.50, 0.64], [0.64, 0.66], [0.78, 0.68], [0.72, 0.80], [0.60, 0.89], [0.44, 0.84], [0.32, 0.74]],
});
