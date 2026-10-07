/* Room · the Writing Room — drafting and internal review (writing · internal-review). Gate 3 is signed on the
   way out of it. */
Lab3D.defineRoom({
  key: 'writing', size: [10, 7], floor: 'boards', accent: 'rose',
  props: [
    { c: 'workstation', at: [-3.0, -2.4], props: { monitors: 1 } },
    { c: 'workstation', at: [-0.8, -2.4], props: { monitors: 2 } },
    { c: 'easel', at: [2.0, -2.5] },
    { c: 'press', at: [3.9, -2.3] },
    { c: 'noticeBoard', at: [-4.6, 0.2], rot: Math.PI / 2 },
    { c: 'roundTable', at: [1.2, 0.6], props: { stools: 4 } },
    { c: 'cabinet', at: [4.4, 0.2], rot: -Math.PI / 2 },
    { c: 'plant', at: [-4.2, 2.6], props: { kind: 'bush' } }, { c: 'floorLamp', at: [4.4, 2.4] },
  ],
  stations: { 'write-paper': [-3.0, -1.65, Math.PI], 'review-paper': [1.2, 1.65, Math.PI], 'make-figures': [2.0, -1.8, Math.PI], 'critique-paper': [-0.8, -1.65, Math.PI] },
  roleStation: { 'fresh-context-reviewer': [2.25, 0.6, -Math.PI / 2], overseer: [0.15, 0.6, Math.PI / 2] },
});
