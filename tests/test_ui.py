"""The dashboard UI (dashboard/static/ui/) — static checks that need no browser.

Every file parses; the page loads Preact/htm before the UI and the UI after the world; every `NL.x` the
UI uses is defined by some UI file (a typo'd helper would otherwise only fail on click); every API path
the UI calls exists on the server; day and night define the same colour tokens; the retired files stay
retired and the vendored libraries carry their licences.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from conftest import REPO, load

STATIC = REPO / "dashboard" / "static"
UI = STATIC / "ui"
NODE = shutil.which("node")
UI_ORDER = ["workflow-default", "core", "components", "runs", "terminal", "composer", "campaign", "gates", "library", "studies", "workflow", "compose", "home", "settings", "setup", "machines", "demo", "app"]


def _js():
    return {f.stem: f.read_text(encoding="utf-8") for f in sorted(UI.glob("*.js"))}


@pytest.mark.skipif(not NODE, reason="node is needed to parse the UI")
@pytest.mark.parametrize("name", UI_ORDER + ["../world/scene"])
def test_every_ui_file_parses(name):
    r = subprocess.run([NODE, "--check", str(UI / f"{name}.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_script_order():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = ["vendor/preact/preact.umd.js", "vendor/preact/hooks.umd.js", "vendor/preact/htm.umd.js",
             "vendor/pixi/pixi.min.js", "world/engine.js", "world/scene.js"] + [f"ui/{n}.js" for n in UI_ORDER]
    pos = [html.index(o) for o in order]
    assert pos == sorted(pos), order
    assert set(_js()) == set(UI_ORDER), "every ui/*.js is loaded, in order"
    assert "ui/ui.css" in html and 'id="app"' in html and 'id="scene"' in html


def test_every_NL_name_used_is_defined():
    src = _js()
    allsrc = "\n".join(src.values())
    defined = set(re.findall(r"\bNL\.([A-Za-z_]\w*)\s*=(?!=)", allsrc))
    # Object.assign(NL, { h, render, … , ...H }) in core.js + the preact hooks spread into NL
    m = re.search(r"Object\.assign\(NL, \{([^}]*)\}\)", src["core"])
    defined |= {x.strip() for x in m.group(1).split(",") if x.strip() and not x.strip().startswith("...")}
    defined |= {"useState", "useEffect", "useRef", "useMemo", "useReducer", "useCallback", "useLayoutEffect", "useContext"}
    used = set(re.findall(r"\bNL\.([A-Za-z_]\w*)", allsrc))
    missing = sorted(used - defined)
    assert not missing, f"used but never defined: {missing}"


def test_every_api_path_the_ui_calls_exists_on_the_server():
    serve = load("dashboard/serve")
    routes = set(serve.GET_ROUTES) | set(serve.POST_ROUTES) | set(serve.FILE_ROUTES) | {"/api/events", "/api/ping"}
    paths = set()
    for text in _js().values():
        paths |= set(re.findall(r"['\"`](/api/[a-z0-9/_-]+)", text))
    # a path the UI builds (`/api/run/${op}`) shows up as its prefix
    missing = sorted(p for p in paths if p not in routes and not (p.endswith("/") and any(r.startswith(p) for r in routes)))
    assert not missing, f"the UI calls endpoints the server doesn't route: {missing}"


def test_day_and_night_define_the_same_tokens():
    css = (UI / "ui.css").read_text(encoding="utf-8")
    night = re.search(r':root, html\[data-lamp="night"\] \{(.*?)\n\}', css, re.S).group(1)
    day = re.search(r'html\[data-lamp="day"\] \{(.*?)\n\}', css, re.S).group(1)
    colour = lambda block: {k for k in re.findall(r"(--[\w-]+):", block) if k not in ("--sans", "--serif", "--mono", "--round", "--r", "--r-l", "--top", "--rail-w")}   # noqa: E731
    assert colour(night) == colour(day), colour(night) ^ colour(day)


def test_retired_files_stay_retired_and_vendored_libs_carry_licences():
    for f in ("app.js", "terrarium.css"):
        assert not (STATIC / f).exists(), f
    for f in ("preact.umd.js", "hooks.umd.js", "htm.umd.js", "LICENSE-preact", "LICENSE-htm"):
        assert (STATIC / "vendor" / "preact" / f).exists(), f
    fonts = STATIC / "vendor" / "fonts"         # the bundled type (SIL OFL), each with its licence
    for fam in ("newsreader", "instrument-sans", "ibm-plex-mono"):
        assert list(fonts.glob(f"{fam}-*.woff2")) and (fonts / f"OFL-{fam}.txt").exists(), fam
    css = (UI / "ui.css").read_text(encoding="utf-8")
    assert "fonts.googleapis" not in css and all(f"'{n}'" in css for n in ("Newsreader", "Instrument Sans", "IBM Plex Mono"))


def test_gate3_and_free_form_are_wired_in_the_ui():
    src = "\n".join(_js().values())
    assert "typed: it.id" in src                       # Gate 3 needs the study name typed
    assert "prompt:" in src and "/api/run" in src       # Ask Newt sends a free-form prompt
    assert "/api/terminal" in src                       # sign-in opens the CLI's own login window
