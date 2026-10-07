/* Room · the Lab — a project's own lab (active · analysis): every live project gets one of these (the
   workflow marks the room `per_project`), so it is the biggest room on the table. Gate 2 (FULL runs) lives
   here. stations: [x, z, facing] — facing is the newt's turn (0 = toward the open front, π = the back wall). */
Lab3D.defineRoom({
  key: 'lab', size: [13.5, 8.5], floor: 'tiles', accent: 'teal',
  props: [
    { c: 'labBench', at: [-4.4, -3.1], props: { w: 2.8 } },
    { c: 'labBench', at: [-1.2, -3.1], props: { w: 2.2, flasks: 4 } },
    { c: 'vessel', at: [1.5, -3.3], props: { h: 2.0 } },
    { c: 'rack', at: [5.8, -3.4] }, { c: 'rack', at: [5.0, -3.4] },
    { c: 'workstation', at: [3.3, -2.7], props: { monitors: 2 } },
    { c: 'workstation', at: [4.6, -0.2], rot: -Math.PI / 2, props: { monitors: 2 } },
    { c: 'whiteboard', at: [-6.0, -0.4], rot: Math.PI / 2, props: { w: 1.8 } },
    { c: 'roundTable', at: [-2.4, 0.9], props: { stools: 4 } },
    { c: 'rug', at: [-2.4, 0.9], props: { r: 1.9, c: 'rug' } },
    { c: 'cabinet', at: [1.2, 0.2], rot: 0 },
    { c: 'plant', at: [6.1, 3.4], props: { kind: 'tall' } }, { c: 'plant', at: [-6.2, 3.5], props: { kind: 'fern' } },
    { c: 'floorLamp', at: [0.2, -1.0] }, { c: 'crates', at: [5.6, 2.2], props: { n: 3 } },
  ],
  stations: { experiment: [-4.4, -2.3, Math.PI], improve: [3.3, -1.95, Math.PI], 'research-loop': [1.5, -2.45, Math.PI], analyze: [3.85, -0.2, Math.PI / 2] },
  roleStation: { 'experiment-runner': [-1.2, -2.35, Math.PI], overseer: [-2.4, 2.1, Math.PI], 'fresh-context-reviewer': [-1.2, 0.9, -Math.PI / 2], 'ideation-critic': [-5.2, -0.4, -Math.PI / 2] },
});
