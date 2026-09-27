# The world's design language

The dashboard's world is a **paper diorama**: the whole lab is drawn as one cutaway building, and each
workflow stage is a room built from cut paper. It is drawn by code (`dashboard/static/world/`, rendered
with PixiJS), so anyone adding a workflow can add a room, or a new piece of furniture, and it will
automatically match everything else in both themes.

This page is the style guide and the recipe book.

## Two inks, one diorama

| | Day: *the atelier* | Night: *the cave* |
|---|---|---|
| Paper | parchment and card, cream to ochre | deep teal and indigo card |
| Lines | sepia ink with a slight hand wobble | faint luminous rims (cyan) |
| Shading | cross-hatching on the shadow side | a soft dark gradient |
| Colour | watercolour washes | washes turn into glow |
| Light | even daylight, windows show the garden | the room lights itself: lamps, screens, specimens, mushrooms |
| Air | dust motes drifting | spores drifting |
| Outside | a sketched landscape under a watercolour sky | cave rock with hanging roots and fungi |

Day and night are **the same drawing**. Every piece is drawn once and the painter renders it in the
active theme's inks, so both themes always match.

## The rules

1. **Everything is a paper piece.** Draw with `P.piece(shape, {…})`, never raw fills. A piece gets:
   - a deckled edge;
   - paper fibre;
   - an ink outline or luminous rim;
   - a soft shadow on whatever is under it.
2. **Depth is `lift`.** How far a piece stands off the page: `0` is flat on its backing, `1–2` is a layer
   of card, and `3–4` is a thick cut-out. Shadows grow with lift, which is what makes the diorama read as
   layered.
3. **Colours are tokens, never literals.** Write `'wood.mid'`, `'glass.liquid'`, `'wash.teal'` or
   `'glow.primary'`. The token table in `world/tokens.js` is the only place colours live; a test fails
   on any `#hex`, `rgb()` or `hsl()` in components or rooms. Retune the palette there and the whole world
   follows.
4. **Shade with `hatch`, colour with `wash`.** `hatch: 0.3, hatchSide: 'right'` becomes cross-hatching
   by day and a gradient by night. `wash: 'wash.ochre'` is a watercolour blotch with pooled edges.
5. **Only say `glow:` for things that shine.** Liquids, bulbs, screens, window light, specimens. By day
   glow is faint (`glow.strength` 0.28); by night it carries the room.
6. **Labels are hand-lettered** (`P.text`, or the `plaque` / `sign` components), in the theme's label
   ink.
7. **Every object is a live readout** where it can be:
   - the compute rack's LEDs are the real slots in use;
   - the FULL reactor bubbles with load;
   - screens scroll while an agent works in the room;
   - a gate's door is sealed and glowing while something waits for your signature, and folds open when
     nothing does;
   - the clock is real time.

## Anatomy of a room

A room is a diorama box: a back wall, a ceiling and side walls in perspective, and a floor running from
the back wall to the front edge. Everything standing on the floor is placed by its **feet** in
normalised room coordinates. It is scaled by depth, smaller toward the back wall, and sorted by depth,
so nearer things overlap farther ones.

```js
VivWorld.defineRoom({
  key: 'lab', title: 'The Lab', order: 3, floor: 0, size: [1600, 900], gate: 2,
  states: ['active', 'analysis'],                        // registry states that live here
  shell: { wall: 'tiles', floor: 'tiles', windows: [0.3, 0.5, 0.7], accent: 'wash.teal', banner: 'The Lab' },
  stations: { experiments: { x: 0.40, y: 0.58 }, … },    // where creatures stand (feet)
  stateStation: { active: 'experiments', analysis: 'analysis' },
  roleStation: { 'experiment-runner': 'experiments', overseer: 'quality' },
  props: [
    { c: 'bench', at: [0.40, 0.505], props: { w: 500, items: ['flask', 'bell'], label: 'Experiments' } },
    { c: 'vessel', at: [0.60, 0.515], props: { kind: 'reactor', label: 'FULL' } },
    …
  ],
  paths: [[0.35, 0.87], [0.42, 0.78], …],               // the walk creatures stroll along
});
```

- **`floor`** places the room in the building: `1` is the upper floor, `0` the ground, `-1` the cellar.
  **`order`** sets its place within the floor. The building lays itself out from these and draws the cut
  walls, slabs, roof and glasshouse wings.
- **Keep the floor readable.** Tall pieces (bookcases, boards, racks) go near the back wall (`y` about
  0.45–0.55). The middle of the floor is for creatures and low tables. Big plants frame the front corners.

## Anatomy of a component

```js
VivWorld.defineComponent('vessel', {
  size: p => [p.w || 120, p.h || 300],         // bounding box; the anchor is bottom-centre (the feet)
  draw(P, p) {                                 // baked once per theme
    P.piece(S.rrect(…), { fill: 'glass.fill', lift: 1.4, glow: 'glass.liquid', glowAlpha: 0.25 });
    …
  },
  parts: p => [{ id: 'wheel', at, size, pivot, anim: { kind: 'spin', bind: 'busy' }, draw(P) { … } }],
  fx: p => [{ kind: 'bubbles', rect: […], bind: 'load' }],   // live effects
  hover: (p, st) => st.slotsUse ? 'FULL runs · bubbling' : 'FULL runs · idle',
  action: 'slots',                             // what a click does: 'slots' · 'gate' · (default) a toast
});
```

- **`parts`** are separately baked pieces the engine animates:
  - `sway` for plants and hanging things;
  - `spin` for the printing-press wheel;
  - `fold` for gate doors (bound to `gateOpen`);
  - `bob`.
- **`fx`** are the shared live effects:
  - `bubbles` and `steam`;
  - `leds` (bound to compute slots);
  - `screen` (`code` scrolls while agents work; `chart`);
  - `ring` (a scanner);
  - `flicker` (lamps, lanterns, mushrooms; `nightOnly` for night-only glows);
  - `pulse` (a gate seal while something waits);
  - `clock`.
- **Live state** a component can bind to, computed per room: `slotsUse`, `slotsCap`, `busy` (agents
  working here), `n`, `nActive`, `nAnalysis`, `gateWaiting`, `gateOpen`, `load`.

The library covers furniture (bench, desk, console, table, board, bookcase, lectern, easel, cabinet,
press, armchair, crates) and apparatus (vessel, rack, dais, trays, jars). It also has signage (plaque,
sign, door) and atmosphere (lantern, stringLights, hangingPlant, pinned papers, plant, rug, clock).
Reuse before adding.

## Add a workflow room in five steps

1. **Decide its registry states.** Anything in those states will live in this room.
2. **Create `dashboard/static/world/rooms/<key>.js`** with `VivWorld.defineRoom({…})`: states, stations,
   `stateStation`, `roleStation`, `props` and `paths`. Give it a `floor` and an `order`.
3. **Add a `<script>` tag** for it in `dashboard/static/index.html` (after `world/building.js`, before
   `world/engine.js`), and in `world/gallery.html`.
4. **Check it in the gallery.** Open `/static/world/gallery.html?view=world&theme=day&room=<key>`, then
   `theme=night`. `?view=components` shows every component in both inks.
5. **Run the tests** (`pytest tests/test_world.py`). They check that:
   - states are covered once;
   - stations and paths are valid;
   - props reference real components;
   - the building doesn't overlap;
   - no colours are hard-coded.

## Performance rules

- **Baking:** everything static is baked once per theme into textures. Rooms are built one per frame, so
  the page never stalls, and each pops up as it lands (about 150–250 ms for the whole building here).
- **Per frame:** only transforms and a few small `Graphics`/sprites change: the LEDs, screens, rings,
  bubbles and spores.
- **Culling:** rooms outside the view aren't drawn.
- **Reduced motion:** the ticker stops and frames render only when something changes. There is no
  parallax, pop-up or drifting.
- **No WebGL?** The dashboard falls back to the classic painted world. ⚙ Settings → *World*, or
  `?world=classic`, switches to it on purpose.
