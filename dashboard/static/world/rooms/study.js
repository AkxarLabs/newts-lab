/* Room · the Study — shape the idea before spending compute (lit-review · scoping · proposal). Gate 1 is its door. */
VivWorld.defineRoom({
  key: 'study', size: [1440, 820], floor: 0, order: 2,   // placement for a lab whose workflow doesn't place its rooms
  shell: { wall: 'panels', floor: 'boards', windows: [0.52], accent: 'wash.blue', seed: 21 },
  stations: {
    stacks: { x: 0.22, y: 0.55 }, novelty: { x: 0.44, y: 0.60 }, decisions: { x: 0.70, y: 0.545 },
    scoping: { x: 0.62, y: 0.76 }, proposal: { x: 0.48, y: 0.85 }, gate: { x: 0.86, y: 0.53 },
  },
  roleStation: { 'fresh-context-reviewer': 'stacks', overseer: 'novelty', 'scoping-advocate': 'decisions' },
  props: [
    { c: 'bookcase', at: [0.13, 0.47], props: { w: 230, h: 360, ladder: true, label: 'Stacks', seed: 3 } },
    { c: 'bookcase', at: [0.30, 0.46], props: { w: 190, h: 320, seed: 7 } },
    { c: 'door', at: [0.88, 0.455], props: { gate: 1, w: 130, h: 250 } },
    { c: 'board', at: [0.68, 0.47], props: { kind: 'cork', w: 230, h: 250, label: 'Decisions', notes: 5 } },
    { c: 'desk', at: [0.45, 0.525], props: { w: 260, lamp: true, items: ['papers', 'quill'], label: 'Novelty' } },
    { c: 'table', at: [0.62, 0.68], props: { kind: 'rect', w: 300, stools: 3 } },
    { c: 'sign', at: [0.73, 0.78], props: { text: 'Scoping', hover: 'Scoping · decisions + kill criteria' } },
    { c: 'lectern', at: [0.40, 0.83], props: { label: 'Proposal' } },
    { c: 'lantern', at: [0.52, 0.22], props: {} },
    { c: 'plant', at: [0.06, 0.93], props: { kind: 'mushrooms', size: 80, seed: 9 } },
    { c: 'plant', at: [0.97, 1.0], props: { kind: 'fern', size: 190, seed: 22 } },
    { c: 'stringLights', at: [0.5, 0.13], props: { w: 1100, n: 14, swags: 2 } },
    { c: 'hangingPlant', at: [0.66, 0.25], props: { drop: 190 } },
    { c: 'pinned', at: [0.53, 0.40], props: { w: 150, n: 3 } },
    { c: 'crates', at: [0.30, 0.62], props: { kind: 'books', w: 110 } },
    { c: 'crates', at: [0.76, 0.93], props: { kind: 'books', w: 110 } },
  ],
  paths: [[0.22, 0.57], [0.30, 0.66], [0.40, 0.70], [0.48, 0.80], [0.56, 0.86], [0.62, 0.80], [0.70, 0.72], [0.76, 0.60], [0.86, 0.56], [0.72, 0.56], [0.56, 0.60], [0.44, 0.62], [0.32, 0.58]],
});
