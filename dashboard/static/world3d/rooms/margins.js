/* Room · the Margins — a quiet garden for parked and killed studies (parked · killed). Revived ones walk back
   to the Incubator. */
Lab3D.defineRoom({
  key: 'margins', size: [8, 5.5], floor: 'grass', accent: 'ochre', walls: false,
  props: [
    { c: 'tree', at: [-2.8, -1.6], props: { size: 1.3 } }, { c: 'tree', at: [2.9, -1.9], props: { size: 1.1 } }, { c: 'tree', at: [0.2, -2.2], props: { size: 0.9 } },
    { c: 'parkBench', at: [-0.8, 0.4] }, { c: 'parkBench', at: [1.9, 0.6], rot: -0.4 },
    { c: 'crates', at: [3.2, 1.6], props: { n: 2 } },
  ],
  stations: {},
});
