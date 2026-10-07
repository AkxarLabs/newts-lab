/* Room · the Archive — finished work (final). Every finalized paper adds a box to its shelves. */
Lab3D.defineRoom({
  key: 'archive', size: [8, 6.5], floor: 'tiles', accent: 'violet',
  props: [
    { c: 'archiveShelf', at: [-2.4, -2.7] }, { c: 'archiveShelf', at: [-0.4, -2.7] },
    { c: 'press', at: [2.3, -2.4] },
    { c: 'cabinet', at: [3.5, 0.2], rot: -Math.PI / 2 },
    { c: 'armchair', at: [-2.6, 1.2], rot: Math.PI / 4, props: { c: 'violet' } },
    { c: 'plant', at: [3.2, 2.4], props: { kind: 'tall' } },
  ],
  stations: { finalize: [2.3, -1.75, Math.PI] },
});
