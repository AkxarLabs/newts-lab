/* Room · the Bench — where results are interpreted (analysis). Separate from the Lab on purpose: analysis
   reads the runs' artifacts and never writes under runs/. stations: [x, z, facing]. */
Lab3D.defineRoom({
  key: 'bench', size: [9, 6.5], floor: 'boards', accent: 'amber',
  props: [
    { c: 'workstation', at: [-2.6, -2.2], props: { monitors: 3 } },
    { c: 'workstation', at: [0.4, -2.2], props: { monitors: 2 } },
    { c: 'whiteboard', at: [3.9, -0.6], rot: -Math.PI / 2, props: { w: 2.2 } },
    { c: 'roundTable', at: [-0.6, 1.0], props: { stools: 3 } },
    { c: 'rug', at: [-0.6, 1.0], props: { r: 1.6, c: 'rug' } },
    { c: 'cabinet', at: [-3.8, 0.6], rot: Math.PI / 2 },
    { c: 'plant', at: [3.8, 2.4], props: { kind: 'fern' } }, { c: 'floorLamp', at: [-3.9, -1.6] },
  ],
  stations: { analyze: [-2.6, -1.45, Math.PI], 'make-figures': [0.4, -1.45, Math.PI] },
  roleStation: { overseer: [1.9, 1.0, -Math.PI / 2], 'fresh-context-reviewer': [-0.6, 2.2, Math.PI] },
});
