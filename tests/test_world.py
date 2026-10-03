"""The diorama world (dashboard/static/world/): the design language and the room contract.

Loads the real world scripts under node with a bare `window` (no DOM, no Pixi — registering tokens,
components and rooms and laying out the building need neither) and checks what the engine and the rest of
the dashboard rely on: every lifecycle state lands in exactly one room, stations/paths/props are valid,
the building layout is deterministic and non-overlapping, both themes define the same tokens, and
components/rooms never hard-code a colour (they name tokens, so both themes and future palettes work).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
import yaml

from conftest import REPO

NODE = shutil.which("node")
STATIC = REPO / "dashboard" / "static"
WORLD = STATIC / "world"
CORE = ["noise.js", "tokens.js", "paper.js", "components.js", "building.js"]
ROOM_FILES = sorted(p.name for p in (WORLD / "rooms").glob("*.js"))
_WF = yaml.safe_load((REPO / "workflow" / "stages.yaml").read_text(encoding="utf-8"))
LIFECYCLE = [s["id"] for s in _WF["states"] + _WF["side_states"]]    # the workflow manifest's states
WF_ROOM = {s["id"]: s["room"] for s in _WF["states"] + _WF["side_states"]}
WF_STATION = {s["id"]: s["station"] for s in _WF["states"] + _WF["side_states"]}


def _world() -> dict:
    files = [str(WORLD / f) for f in CORE] + [str(WORLD / "rooms" / f) for f in ROOM_FILES]
    js = f"""
      global.window = global; const fs = require('fs');
      for (const f of {json.dumps(files)}) eval(fs.readFileSync(f, 'utf8'));
      const W = window.VivWorld, lay = W.layoutBuilding(), lay2 = W.layoutBuilding();
      const comps = {{}};
      for (const [k, c] of Object.entries(W.components)) comps[k] = {{ size: c.size(k === 'shell' ? {{ w: 1000, h: 600 }} : {{}}),
        parts: !!c.parts, fx: typeof c.fx === 'function' ? c.fx({{}}).map(f => f.kind) : [], hover: typeof c.hover }};
      const flat = o => Object.keys(o).sort().map(k => (o[k] && typeof o[k] === 'object') ? k + '{{' + flat(o[k]) + '}}' : k).join(',');
      console.log(JSON.stringify({{ rooms: W.rooms, lay, same: JSON.stringify(lay) === JSON.stringify(lay2), comps,
        tokens: {{ day: flat(W.tokens.day), night: flat(W.tokens.night) }}, back: W.BOX.back, stateRoom: W.stateRoom() }}));
    """
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


pytestmark = pytest.mark.skipif(not NODE, reason="node is needed to load the world scripts")


@pytest.fixture(scope="module")
def world():
    return _world()


def test_every_lifecycle_state_lives_in_exactly_one_room(world):
    owners = {}
    for key, r in world["rooms"].items():
        for st in r["states"]:
            assert st not in owners, f"{st} claimed by {owners[st]} and {key}"
            owners[st] = key
    assert set(LIFECYCLE) <= set(owners), set(LIFECYCLE) - set(owners)
    assert world["stateRoom"] == owners
    # the art agrees with the workflow manifest (which the engine follows at runtime)
    assert {st: owners[st] for st in LIFECYCLE} == WF_ROOM
    for st, room in WF_ROOM.items():
        assert WF_STATION[st] in world["rooms"][room]["stations"], (st, room, WF_STATION[st])


def test_rooms_keep_the_station_contract(world):
    comps = world["comps"]
    for key, r in world["rooms"].items():
        st = r["stations"]
        assert st, key
        for name, p in st.items():
            assert 0 < p["x"] < 1 and world["back"] <= p["y"] <= 1, (key, name, p)
        for m in ("stateStation", "roleStation"):
            for k, v in r[m].items():
                assert v in st, f"{key}.{m}[{k}] → unknown station {v}"
        for s in r["states"]:
            assert s in r["stateStation"], f"{key}: state {s} has no station"
        assert len(r["paths"]) >= 4 and all(0 <= a <= 1 and 0 <= b <= 1 for a, b in r["paths"]), key
        for pr in r["props"]:
            assert pr["c"] in comps, f"{key}: unknown component {pr['c']}"
            assert 0 <= pr["at"][0] <= 1 and 0 <= pr["at"][1] <= 1, (key, pr)
        if r.get("gate"):
            assert any(pr["c"] == "door" and pr["props"].get("gate") == r["gate"] for pr in r["props"]), f"{key}: gate {r['gate']} has no door"


def test_role_default_stations_exist(world):
    """Workers stand at their room's roleStation, else the role's default station (scene.js ROLE_STATION)."""
    app = (STATIC / "world" / "scene.js").read_text(encoding="utf-8")
    role_station = dict(re.findall(r"'([\w-]+)':\s*'([\w-]+)'", re.search(r"const ROLE_STATION = \{(.*?)\};", app).group(1)))
    for key, r in world["rooms"].items():
        for role, stn in r["roleStation"].items():
            assert stn in r["stations"], (key, role, stn)
    assert role_station.get("experiment-runner") in world["rooms"]["lab"]["stations"]


def test_building_layout_is_deterministic_and_non_overlapping(world):
    lay, boxes = world["lay"], list(world["lay"]["boxes"].items())
    assert world["same"]
    assert set(lay["boxes"]) == set(world["rooms"])
    for i, (ka, a) in enumerate(boxes):
        for kb, b in boxes[i + 1:]:
            sep = a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
            assert sep, f"{ka} overlaps {kb}"
    floors = {b["floor"] for _, b in boxes}
    assert {0, 1, -1} <= floors                                  # ground, upper floor, cellar (the cutaway)


def test_both_themes_define_the_same_design_tokens(world):
    assert world["tokens"]["day"].replace("name,", "") == world["tokens"]["night"].replace("name,", "")


def test_components_and_rooms_name_tokens_never_colours():
    literal = re.compile(r"(?<![\w&])#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
    files = [WORLD / "components.js", WORLD / "building.js"] + sorted((WORLD / "rooms").glob("*.js"))
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//")[0]
            assert not literal.search(code), f"{f.name}:{i} hard-codes a colour: {line.strip()[:120]}"


def test_components_declare_size_and_known_fx(world):
    known_fx = {"bubbles", "steam", "leds", "screen", "ring", "flicker", "clock", "pulse"}
    for name, c in world["comps"].items():
        w, h = c["size"]
        assert w > 0 and h > 0, name
        assert set(c["fx"]) <= known_fx, (name, c["fx"])


def test_world_scripts_load_before_the_app():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = ["vendor/pixi/pixi.min.js"] + [f"world/{f}" for f in CORE] + ["world/engine.js", "world/scene.js", "ui/core.js", "ui/app.js"]
    pos = [html.index(o) for o in order]
    assert pos == sorted(pos), order
    for f in ROOM_FILES:   # every room spec is loaded, after the building registry and before the engine starts
        assert html.index("world/building.js") < html.index(f"world/rooms/{f}") < html.index("world/engine.js"), f
    assert (STATIC / "vendor" / "pixi" / "LICENSE-pixi").exists()


def test_the_scene_has_a_quiet_stand_in_without_webgl():
    sc = (STATIC / "world" / "scene.js").read_text(encoding="utf-8")
    assert "createPixiWorld" in sc and "quietWorld(" in sc
    assert "createWorld" not in sc and "classic" not in sc
