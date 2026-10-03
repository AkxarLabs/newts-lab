/* Room · the Lab — experiments and their analysis (active · analysis). Gate 2 (FULL runs) lives here.
   stations: [x, z, facing] — facing is the newt's turn (0 = toward the open front, π = toward the back wall). */
Lab3D.defineRoom({
  key: 'lab', size: [11, 7.5], floor: 'tiles', accent: 'teal',
  props: [
    { c: 'labBench', at: [-3.2, -2.6], props: { w: 2.6 } },
    { c: 'vessel', at: [-0.6, -2.8], props: { h: 1.9 } },
    { c: 'rack', at: [4.6, -2.9] }, { c: 'rack', at: [3.8, -2.9] },
    { c: 'workstation', at: [1.6, -2.3], props: { monitors: 2 } },
    { c: 'workstation', at: [3.4, -0.4], rot: -Math.PI / 2, props: { monitors: 2 } },
    { c: 'whiteboard', at: [-4.6, -0.2], rot: Math.PI / 2 },
    { c: 'roundTable', at: [-1.8, 0.6] },
    { c: 'plant', at: [5, 2.8], props: { kind: 'tall' } }, { c: 'plant', at: [-5, 3], props: { kind: 'fern' } },
    { c: 'floorLamp', at: [0.6, -0.4] },
  ],
  stations: { experiment: [-3.2, -1.8, Math.PI], improve: [1.6, -1.55, Math.PI], 'research-loop': [-0.6, -2.0, Math.PI], analyze: [2.75, -0.4, Math.PI / 2] },
  roleStation: { 'experiment-runner': [-2.4, -1.8, Math.PI], overseer: [-1.8, 1.55, Math.PI], 'fresh-context-reviewer': [-0.85, 0.6, -Math.PI / 2], 'ideation-critic': [-3.9, -0.2, -Math.PI / 2] },
});
