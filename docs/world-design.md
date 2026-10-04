# The world's design

Behind Home, the dashboard draws your lab as an **open tabletop in 3D**: your desk in the middle, the
workflow's rooms standing round it on plots, streets between them, and a newt for every agent at work. It
is drawn by code (`dashboard/static/world3d/`, rendered with three.js), from the same snapshot the rest of
the dashboard reads. Nothing in it writes anything: a click calls back into the dashboard.

This page is the design and the recipe book.

## Why a world at all

Function over decoration. Terminals can't scale research: you can follow one or two agent sessions in a
terminal, not a dozen runs across many studies at once. The world exists so one scientist can keep
oversight of many agents at a glance: who is working, where, on what, who is stuck, and who is waiting on
you.

So every space is **openly interpretable**. Rooms have no roofs and you never go inside a building:
everything is visible from above, and zooming into a room only brings the camera closer. Every newt, card,
lamp and arch is a readout of something real. If a piece of the picture means nothing, it shouldn't be
there.

## The table

- **The plaza** at `[0, 0]` is your desk. The big Newt (your assistant) stands there with an inbox; its
  envelopes are the items needing you.
- **Plots** sit on a grid round the plaza, with streets between them. Each room stands on one plot
  (`Lab3D.plan`, `world3d/layout.js`). Compose's layout editor uses the same plan, so both always agree.
- In `workflow/stages.yaml` a room line can carry `place: [column, row]` and `facing: n|e|s|w` (Compose →
  Rooms: drag it on the table; turn its door). Without them a room takes the next free plot going round
  the plaza, rooms holding the lifecycle first, door toward your desk.

```yaml
rooms:
  - {id: data, label: Data, title: The Data Room, states: [data-prep]}
  - {id: lab,  label: Lab,  title: The Lab, states: [active, analysis], gate: 2, per_project: true, place: [1, 0], facing: w}
```

## Rooms and project labs

Which rooms exist is the workflow's; what they look like is the room's look (below). A room with no look
is drawn **plain**: a floor, low walls and a desk per procedure.

`per_project: true` (the Lab has it) makes a room one room **per live project**, titled by its study,
with the kicker "Lab". Without the flag, a room is treated as per-project when most of its procedures are
project-level. Compose → a room → About has a "One per live project" toggle.

- While `/spawn-project` runs for a study, its new lab stands as scaffolding ("being built") and rises out
  of the table when ready.
- Further project labs cluster as a **lab district** on the free plots nearest the first lab.
- With no projects, the bare Lab stands with a "No projects yet" sign.
- Each project's lab takes the look for its type, `lab.<type>`, the type taken from the project's
  `control.yaml` `project_type` (default `ml`). Starter looks for every shipped type (`ml`, `empirical`,
  `simulation`, `theory`, `target-driven`) come with the dashboard in `world3d/looks/lab.<type>.json`; the
  lab's own `lab/rooms3d/lab.<type>.json` wins over them. With neither, the built-in Lab look is used.

## Newts: who is where

Every **run** (a headless main agent: claude, codex or opencode; many at once, one per study or project,
within the caps in Settings → Autonomy) is a newt at the station of the procedure it runs. Each run has a
family colour of its own (a hue from its run id) and an orchestrator badge. Its **subagents** are smaller
newts (0.62 scale) in the same family colour, with a badge coloured by role, at the room's `roleStation`
for that role.

Where a run stands, first match wins:

1. `/design-room`: in the room it designs.
2. `/spawn-project`: in the lab being built.
3. A project-level procedure: in that project's lab.
4. Other work on a study: in the study's room.
5. Otherwise the room of the procedure's stage; else your desk.

What the poses mean:

- **work**: at its station, busy.
- **wait**: a run waiting for you walks to your desk with a "?" bubble. Queued runs wait at the desk too.
- **sleep**: a stalled run (no heartbeat for over 3 minutes) dozes.
- **fail**: a failed run slumps.
- **walk** / **carry**: moving along the streets, or carrying a card.

Traced workers not launched from the dashboard appear too.

**The cast.** A newt is the default, but an agent can be drawn as any of six characters
(`world3d/characters.js`, `Lab3D.CHARACTERS`): the newt, a mini human scientist, a frog, an owl, a fox and a
robot. Settings → Appearance → The cast picks one per tool (by default Claude a newt, Codex the scientist,
opencode the robot) or one for everyone. Subagents are smaller copies of their main agent's character, in
the same family colour. All of them take the same poses.

When the table changes (a new lab rises, a room moves) the agents keep their places and walk on to where
they now belong; nobody respawns.

## Cards, couriers and gates

- **Studies are cards** on their room's shelf, in the study's own hue.
- When a study moves on, a newt **carries its card** along the streets to the next room.
- **Gates** are arches at a room's street door, with a lamp. A lit gate means a study is waiting there for
  your signature.

## Lenses

Top-left on Home. Each re-tints the table by what you ask:

| Lens | Shows |
|---|---|
| Work | what each newt is doing |
| Cost | today's spend per room and per run; floors tinted by it |
| Waiting on you | only the asks |
| Risk | denials and failures, flagged |

Room labels never overlap: the busiest rooms get theirs first.

## Your other labs

The other labs in Labs & machines (this computer's and other machines', all in this one dashboard) stand
as small tables beyond the table's back edge, each with a bridge to yours. Each shows its name, its
machine, "N need you", a light per agent at work, and "not connected" when its machine can't be reached.
Click one to go to that lab.

## Interactions

- A newt → its run sheet. A card → the study. The desk → the inbox. The big Newt → Start something. A
  gate arch → the study waiting on it. A room → zoom into it (a crumb, and back).
- Drag to turn, wheel to zoom, hover for a tooltip.
- Day and night themes follow the lamp.
- On a phone the table fits above the bottom sheet.
- `?settle` on the page URL runs the world forward until everyone is in place, for screenshots.
- Demo mode (server started with `--demo`, page `?demo`) shows a synthetic living lab and writes nothing.

## The files

All under `dashboard/static/world3d/`; three.js is vendored at `dashboard/static/vendor/three/` (r169, MIT).

| File | Role |
|---|---|
| `kit.js` | `Lab3D.defineComponent`, `defineRoom`, `defineRoomData` (a room given as JSON data), the day/night themes |
| `newt.js` | the 3D newt (`Lab3D.makeNewt`; options `color`, `hue`, `scale`) |
| `characters.js` | the rest of the cast (`Lab3D.CHARACTERS`, `Lab3D.makeCharacter(K, id, {color, hue, scale})`), same interface as the newt |
| `components.js` | the furniture kit, about 25 pieces built from primitives |
| `layout.js` | `Lab3D.plan`: plots on a grid round your desk |
| `model.js` | `Lab3D.model`: pure logic, no drawing (`roomList`, `placeRooms` with the lab district, `placeOfRun`, `roomOfItem`) |
| `rooms/*.js` | the built-in looks: incubator, study, lab, writing, archive, margins |
| `looks/lab.<type>.json` | starter Lab looks per project type, as data (a README there says what each shows) |
| `world.js` | `Lab3D.createWorld`: the live world |
| `scene.js` | `VivScene`: one stable API over the world, and a quiet stand-in without WebGL |
| `sandbox-room.html` | a sandboxed room preview, used by Compose |
| `newt.html` | "The cast": every character side by side (`?pose=idle\|work\|walk\|wait\|carry\|sleep\|fail\|mix`, `?theme=night`, `?grid` for every pose) |

The server inserts one `<script>` per built-in room file at the `<!-- newts:rooms3d -->` marker in
`index.html`. Looks given as data come from `/api/rooms3d` at run time: the starter looks first, then the
lab's own (`lab/rooms3d/`), so the lab's own win.

## Room looks

Units are metres, y up. A room's coordinates are local: `x` across, `z` toward the open front (the street
door), the back wall at `-z`. Colours are theme names (`wood`, `teal`, `paper`, …), so every piece reads
right by day and by night; a lab's JSON may also use `#rrggbb`.

**Built-in looks are code**, `world3d/rooms/<id>.js`:

```js
Lab3D.defineRoom({
  key: 'lab', size: [13.5, 8.5], floor: 'tiles', accent: 'teal',
  props: [{ c: 'labBench', at: [-4.4, -3.1], props: { w: 2.8 } }, …],
  stations: { experiment: [-4.4, -2.3, Math.PI], improve: [3.3, -1.95, Math.PI] },        // by procedure: [x, z, facing]
  roleStation: { 'experiment-runner': [-1.2, -2.35, Math.PI], overseer: [-2.4, 2.1, Math.PI] },  // by subagent role
});
```

A procedure with no station gets a desk of its own, laid out by the engine.

**A lab's own look is data, never code**: `lab/rooms3d/<id>.json`, checked by `compose.room_check`:

- only the keys `key` (must equal the room id), `title`, `size` (`[width, depth]`, 3–30 m), `floor`,
  `wall`, `accent` (a colour name or `#rrggbb`), `walls` (true/false), `props`, `stations`, `roleStation`,
  `components`;
- a prop is `{c: furniture name, at: [x, z], rot?, props?: {simple values}}`, at most 150;
- `stations` and `roleStation` map a name to `[x, z]` or `[x, z, facing]`;
- `components` is new furniture, at most 40 pieces, each 1–120 primitive parts
  `{shape: box|cyl|cone|sphere, size, at: [x, y, z], color, rot?, glow?, alpha?}`; at most 1500 parts in a
  room.

The starter looks in `world3d/looks/` are the same format and are the worked examples `/design-room` reads.
Nothing an agent writes ever runs in the page. `lab/rooms3d/` is protected from headless runs by the
signature guard.

## Add a room, design its look

1. **Add the room.** `tools/new.py room <id> --like <room>` adds the line on the next free plot and copies
   the lab's own JSON look for the like if there is one (`lab/rooms3d/<like>.json` → `<id>.json`).
   Built-in looks are code, so otherwise the room is drawn plain until designed; `--plain` never copies.
   Or add the line in Compose → Rooms.
2. **Design its look by describing it.** Compose → the room → Look → "Design it" launches the
   `/design-room` skill: a coding agent writes `lab/.bus/designs/<room>/room.json` and `notes.md`
   (`tools/workflow.py room <id>` prints the room brief it works from). You preview it in a sandboxed
   frame and click "Use this design"; it goes to the Compose draft, then Publish. For a per-project room,
   the Look tab has a "Look for: every project / <type>" switch: a design for one type is saved as
   `lab.<type>` (`/design-room lab.ml "…"`; `tools/workflow.py room lab.ml` briefs it).
3. **Run the tests** (`pytest tests/test_world.py`).

## The contract

`Lab3D.createWorld(canvas, {lamp, reduced})` returns the world. `scene.js` wraps it as `VivScene.create()`,
buffers calls made while it boots, and keeps the same contract with nothing drawn when there is no WebGL.

| Call | Does |
|---|---|
| `sync(snapshot)` | redraws from the lab's snapshot |
| `setPose(p)` | the big Newt's pose |
| `setLamp('day' \| 'night')` | the theme |
| `setView('WORLD')`, `goRoom(id)`, `back()` | the whole table, or one room |
| `focusProject(id)` | zooms to a study's lab or room |
| `viewInfo()` | `{level, label}`, for the crumb |
| `highlight(role)` | picks out one subagent role |
| `layout()` | the plan of the table, for the minimap |
| `setAmbient(on)` | idle motion on or off |
| `setLens(l)` / `lens()` | `work`, `cost`, `waiting` or `risk` |
| `followWorker(id)`, `stopFollow()`, `following()` | the camera follows one newt |
| `setCast(cast)` | who plays the agents (Settings → Appearance → The cast) |
| `setNeighbours(labs)` | your other labs, past the back edge |
| `onClick(item, inbox)`, `onWorker`, `onRun`, `onNewt`, `onView`, `onFollow`, `onLab` | callbacks into the dashboard |

## Testing

`tests/test_world.py` loads the real world scripts under node with a bare `window` (no DOM, no WebGL) and
checks what the dashboard relies on: every lifecycle state lands in exactly one room, every built-in look
keeps the station contract, a per-project room stands once per live project (and is built while
`/spawn-project` runs), the lab district never puts two rooms on one plot, and every run stands where its
work is. It skips when node isn't installed.

Headless screenshots of the world need software WebGL (e.g. SwiftShader); without it you get the stand-in.
Without WebGL the dashboard works the same, minus the world.
