# Starter looks for the Lab, one per project type

Each file here is a room look **as data** — the same JSON a lab writes to `lab/rooms3d/<id>.json`, checked by
`room_check` in `dashboard/compose.py` and built by `Lab3D.defineRoomData` (`world3d/kit.js`). Nothing in them
runs: a size, colours, furniture by name (built-ins from `world3d/components.js`, or the file's own
`components` made of boxes, cylinders, cones and spheres), a station per Lab procedure (`experiment`,
`improve`, `research-loop`, `analyze`) and a station per subagent role.

| file | for a project of type | what it shows |
|---|---|---|
| `lab.ml.json` | `ml` | GPU racks with status lights, a wall of training-curve screens, a long bench of workstations |
| `lab.empirical.json` | `empirical` | instrument benches, sample shelves, a sample cart, a whiteboard of plots |
| `lab.simulation.json` | `simulation` | a row of cluster cabinets, a big heat-map screen, a curved control desk |
| `lab.theory.json` | `theory` | two chalkboards, a big table covered in papers, a reading corner of bookshelves |
| `lab.target-driven.json` | `target-driven` | a leaderboard, a scoreboard (current vs target), sprint desks, a floor target and a finish line |

- **How the world picks one:** the Lab is one room per project; the world draws a project's Lab with the look
  `lab.<project_type>` when one exists, and the built-in `lab` (`world3d/rooms/lab.js`) otherwise.
- **Overriding:** a lab replaces any of these by writing its own `lab/rooms3d/<same-key>.json` (e.g.
  `lab/rooms3d/lab.ml.json`, whose `key` is `"lab.ml"`); the lab's file wins.
- **For `/design-room`:** these are the worked examples it reads — complete, valid looks showing how stations,
  role stations, built-in props and new components fit together in a 13.5 × 8.5 m room (x across, z toward the
  open front, the back wall at −z; a station's facing π turns the newt toward the back wall).
