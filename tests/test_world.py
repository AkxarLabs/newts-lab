"""The world (dashboard/static/world3d/): the room contract, and what the world decides from a snapshot.

Loads the real world scripts under node with a bare `window` (no DOM, no WebGL — registering furniture and
room looks, and the model that decides which rooms stand where and who goes in which, need neither) and checks
what the dashboard relies on: every lifecycle state lands in exactly one room, every built-in look keeps the
station contract, a per-project room stands once per live project (and is built while /spawn-project runs),
the lab district keeps a lab's projects together without two rooms on one plot, and every run stands where its
work is.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml

from conftest import REPO, load

NODE = shutil.which("node")
STATIC = REPO / "dashboard" / "static"
W3 = STATIC / "world3d"
CORE = ["kit.js", "components.js", "layout.js", "model.js"]
ROOM_FILES = sorted(p.name for p in (W3 / "rooms").glob("*.js"))
_WF = yaml.safe_load((REPO / "workflow" / "stages.yaml").read_text(encoding="utf-8"))
LIFECYCLE = [s["id"] for s in _WF["states"] + _WF["side_states"]]
WF_ROOM = {s["id"]: s["room"] for s in _WF["states"] + _WF["side_states"]}

pytestmark = pytest.mark.skipif(not NODE, reason="node is needed to load the world scripts")


def _node(body: str) -> dict:
    """Run `body` under node with the world scripts loaded (window.Lab3D as L, the manifest as WF)."""
    files = [str(W3 / f) for f in CORE] + [str(W3 / "rooms" / f) for f in ROOM_FILES]
    js = f"""
      global.window = global; const fs = require('fs');
      for (const f of {json.dumps(files)}) eval(fs.readFileSync(f, 'utf8'));
      const L = window.Lab3D, M = L.model, WF = {json.dumps(_WF)};
      const out = (() => {{ {body} }})();
      console.log(JSON.stringify(out));
    """
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_every_lifecycle_state_lives_in_exactly_one_room():
    owners = {}
    for r in _WF["rooms"]:
        for st in r["states"]:
            assert st not in owners, f"{st} claimed by {owners[st]} and {r['id']}"
            owners[st] = r["id"]
    assert set(LIFECYCLE) <= set(owners), set(LIFECYCLE) - set(owners)
    assert {st: owners[st] for st in LIFECYCLE} == WF_ROOM
    assert [r["id"] for r in _WF["rooms"] if r.get("per_project")] == ["lab"]


def test_every_room_has_a_look_that_keeps_the_station_contract():
    """Stations and props stand inside the room, props name known furniture, stations are [x, z, facing]."""
    got = _node("return { rooms: L.rooms, comps: Object.keys(L.components) };")
    assert {r["id"] for r in _WF["rooms"]} == set(got["rooms"]), "every shipped room has its look"
    for f in ROOM_FILES:
        assert f[:-3] in got["rooms"], f"{f} defines a room keyed by its file name"
    for key, r in got["rooms"].items():
        hw, hd = r["size"][0] / 2, r["size"][1] / 2
        for kind in ("stations", "roleStation"):
            for name, p in r[kind].items():
                assert len(p) == 3 and abs(p[0]) < hw and abs(p[1]) < hd, (key, kind, name, p)
        for pr in r["props"]:
            assert pr["c"] in got["comps"], f"{key}: unknown furniture {pr['c']}"
            assert abs(pr["at"][0]) <= hw and abs(pr["at"][1]) <= hd, (key, pr)
    lab = got["rooms"]["lab"]
    assert lab["size"][0] >= 13, "the Lab is the biggest room (a project's own)"
    assert {"experiment", "improve", "analyze"} <= set(lab["stations"]) and "experiment-runner" in lab["roleStation"]


SNAP = {
    "items": [
        {"id": "moe", "title": "Sparse MoE", "state": "active", "has_project": True, "project_type": "ml"},
        {"id": "rl", "title": "RL", "state": "active", "has_project": True},
        {"id": "ana", "title": "Probes", "state": "analysis", "has_project": True},
        {"id": "old", "title": "Done", "state": "final", "has_project": True},
        {"id": "new", "title": "New", "state": "proposal", "gate_signed": True},
        {"id": "lit", "title": "Lit", "state": "lit-review"},
    ],
    "runs": [
        {"run_id": "r1", "skill": "spawn-project", "subject": "new", "status": "running"},
        {"run_id": "r2", "skill": "experiment", "subject": "moe", "status": "running"},
        {"run_id": "r3", "skill": "lit-review", "subject": "lit", "status": "running"},
        {"run_id": "r4", "skill": "ask", "status": "running"},
        {"run_id": "r5", "skill": "design-room", "args": "writing a cosier room", "status": "running"},
        {"run_id": "r6", "skill": "analyze", "subject": "ana", "status": "running"},
    ],
}


def test_a_per_project_room_stands_once_per_live_project():
    got = _node(f"""
      const s = Object.assign({json.dumps(SNAP)}, {{ workflow: WF }});
      const list = M.roomList(s), none = M.roomList({{ workflow: WF, items: [], runs: [] }});
      return {{ list: list.map(r => ({{ id: r.id, building: !!r.building, extra: !!r.extra, type: r.type || null }})),
               none: none.map(r => [r.id, !!r.empty]) }};""")
    labs = {r["id"]: r for r in got["list"] if r["id"].startswith("lab")}
    assert set(labs) == {"lab:moe", "lab:rl", "lab:ana", "lab:new"}, "a lab per live project (not a finished one), one being built"
    assert labs["lab:new"]["building"] and labs["lab:moe"]["type"] == "ml"
    assert [labs[k]["extra"] for k in ("lab:moe", "lab:rl", "lab:ana")] == [False, True, True]
    assert ["lab", True] in got["none"], "no projects yet: the bare Lab stands, marked empty"


def test_the_lab_district_keeps_projects_together_on_their_own_plots():
    got = _node("""
      const items = Array.from({ length: 9 }, (_, i) => ({ id: 'p' + i, title: 'P' + i, state: 'active', has_project: true }));
      const s = { workflow: WF, items, runs: [] };
      const a = M.placeRooms(M.roomList(s), WF), b = M.placeRooms(M.roomList(s), WF);
      return { a, same: JSON.stringify(a) === JSON.stringify(b) };""")
    cells = [tuple(v["cell"]) for v in got["a"].values()]
    assert got["same"], "the same lab lays out the same way every time"
    assert len(cells) == len(set(cells)) and (0, 0) not in cells, "one room per plot, the plaza kept free"
    first = got["a"]["lab:p0"]["cell"]
    near = [abs(v["cell"][0] - first[0]) + abs(v["cell"][1] - first[1]) for k, v in got["a"].items() if k.startswith("lab:")]
    assert max(near) <= 4, f"a lab's projects cluster round its first lab: {near}"
    assert all(v["facing"] in "nesw" for v in got["a"].values())


def test_every_run_stands_where_its_work_is():
    got = _node(f"""
      const s = Object.assign({json.dumps(SNAP)}, {{ workflow: WF }});
      const rooms = Object.fromEntries(M.roomList(s).map(r => [r.id, r]));
      return Object.fromEntries(s.runs.map(r => [r.run_id, M.placeOfRun(s, r, rooms)]));""")
    assert got == {"r1": "lab:new", "r2": "lab:moe", "r3": WF_ROOM["lit-review"], "r4": "hub", "r5": "writing", "r6": "lab:ana"}


def test_world_scripts_load_before_the_app():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = ["vendor/three/three.module.min.js"] + [f"world3d/{f}" for f in ["kit.js", "newt.js", "components.js", "layout.js", "model.js"]] \
        + ["newts:rooms3d", "world3d/world.js", "world3d/scene.js", "ui/core.js", "ui/app.js"]
    pos = [html.index(o) for o in order]
    assert pos == sorted(pos), order
    assert "pixi" not in html


def test_the_server_puts_every_built_in_room_on_the_page():
    serve = load("dashboard/serve")
    page = serve._with_rooms3d((STATIC / "index.html").read_text(encoding="utf-8"), "static/world3d/rooms/")
    for f in ROOM_FILES:
        assert f'<script src="static/world3d/rooms/{f}"></script>' in page, f
    assert "newts:rooms3d" not in page
    assert page.index("world3d/model.js") < page.index("rooms/" + ROOM_FILES[0]) < page.index("world3d/world.js")


def test_the_scene_has_a_quiet_stand_in_without_webgl():
    sc = (W3 / "scene.js").read_text(encoding="utf-8")
    assert "Lab3D.createWorld" in sc and "quietWorld(" in sc and "Pixi" not in sc
