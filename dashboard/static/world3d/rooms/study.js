/* Room · the Study — literature, scoping and the proposal (lit-review · scoping · proposal). Gate 1 is signed
   on the way out of it. */
Lab3D.defineRoom({
  key: 'study', size: [10, 7], floor: 'boards', accent: 'blue',
  props: [
    { c: 'bookshelf', at: [-3.6, -3.0], props: { w: 1.8 } }, { c: 'bookshelf', at: [-1.7, -3.0], props: { w: 1.8 } },
    { c: 'workstation', at: [1.0, -2.4], props: { monitors: 1 } },
    { c: 'workstation', at: [3.3, -2.4], props: { monitors: 2 } },
    { c: 'lectern', at: [3.9, 0.6], rot: -Math.PI / 2 },
    { c: 'roundTable', at: [-1.6, 0.4] },
    { c: 'rug', at: [-1.6, 0.4], props: { r: 1.7, c: 'rug' } },
    { c: 'armchair', at: [-4.3, 1.4], rot: Math.PI / 2 },
    { c: 'plant', at: [4.4, 2.6], props: { kind: 'fern' } }, { c: 'floorLamp', at: [-4.4, -1.4] },
  ],
  stations: { 'lit-review': [-2.6, -2.3, Math.PI], 'critique-paper': [1.0, -1.65, Math.PI], scope: [-1.6, 1.45, Math.PI], propose: [3.3, -1.65, Math.PI], 'spawn-project': [3.2, 0.6, Math.PI / 2] },
  roleStation: { 'fresh-context-reviewer': [-3.6, -2.3, Math.PI], 'scoping-advocate': [-0.55, 0.4, -Math.PI / 2], overseer: [-2.65, 0.4, Math.PI / 2] },
});
