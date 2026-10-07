/* Room · the Incubator — where ideas are seeded and triaged (seed · triaged). */
Lab3D.defineRoom({
  key: 'incubator', size: [8, 6.5], floor: 'boards', accent: 'green',
  props: [
    { c: 'trays', at: [-2.0, -2.3], props: { w: 2.4 } },
    { c: 'whiteboard', at: [1.6, -2.6], props: { w: 1.8 } },
    { c: 'roundTable', at: [0.4, 0.4], props: { stools: 3 } },
    { c: 'rug', at: [0.4, 0.4], props: { r: 1.6, c: 'carpet' } },
    { c: 'plant', at: [3.4, 2.4], props: { kind: 'bush', size: 1.2 } }, { c: 'plant', at: [-3.4, 2.4], props: { kind: 'tall' } },
    { c: 'floorLamp', at: [3.3, -2.2] },
  ],
  stations: { ideate: [1.6, -1.7, Math.PI], advance: [-2.0, -1.6, Math.PI], discuss: [0.4, 1.45, Math.PI] },
  roleStation: { 'ideation-critic': [-0.65, 0.4, Math.PI / 2] },
});
