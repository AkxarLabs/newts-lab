"""Code-drawn dashboard rooms (dashboard/static/rooms/): they register cleanly and keep the contract the
scene engine relies on — every station the painted room had, a walk path, hoverable objects inside the
room, and bake/live entry points. Runs the real JS under node with a bare `window` (no DOM needed to
register; baking needs a canvas and is exercised in the browser)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from conftest import REPO

NODE = shutil.which("node")
STATIC = REPO / "dashboard" / "static"


@pytest.mark.skipif(not NODE, reason="node is needed to load the room scripts")
def test_lab_room_registers_with_the_full_station_contract():
    js = f"""
      global.window = {{}};
      eval(require('fs').readFileSync({json.dumps(str(STATIC / 'rooms' / 'kit.js'))}, 'utf8'));
      eval(require('fs').readFileSync({json.dumps(str(STATIC / 'rooms' / 'lab.js'))}, 'utf8'));
      const R = window.CodeRooms.lab;
      const objs = R.objects({{ slotsCap: 2, slotsUse: 1, busy: 1, nActive: 1, nAnalysis: 0 }});
      console.log(JSON.stringify({{ stations: R.stations, paths: R.paths, objs, fns: [typeof R.bake, typeof R.live] }}));
    """
    out = json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True, timeout=30).stdout)
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    painted = re.search(r"^\s*lab:\s*\{(.*?)\},\s*$", app[app.index("const STATIONS = {"):], re.M).group(1)
    keys = set(re.findall(r"(\w+):\s*\{\s*x:", painted))
    assert keys and keys <= set(out["stations"]), (keys, out["stations"])
    for st in out["stations"].values():
        assert 0 < st["x"] < 1 and 0 < st["y"] < 1
    assert len(out["paths"]) >= 4 and all(0 <= a <= 1 and 0 <= b <= 1 for a, b in out["paths"])
    assert out["fns"] == ["function", "function"]
    ids = {o["id"] for o in out["objs"]}
    assert {"rack", "reactor", "bench", "desk", "dais", "analysis"} <= ids
    for o in out["objs"]:
        assert o["label"] and 0 <= o["x"] and o["x"] + o["w"] <= 1600 and 0 <= o["y"] and o["y"] + o["h"] <= 900, o
    rack = next(o for o in out["objs"] if o["id"] == "rack")
    assert "1 of 2" in rack["label"]                      # live data, not decoration


def test_room_scripts_load_before_the_app():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    i_kit, i_lab, i_app = html.index("rooms/kit.js"), html.index("rooms/lab.js"), html.index('src="app.js"')
    assert i_kit < i_lab < i_app
