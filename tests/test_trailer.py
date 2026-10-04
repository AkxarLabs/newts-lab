"""The trailer (dashboard/static/trailer.html) drives the real dashboard's demo lab, so it must keep pointing at
pages, procedures and controls that exist."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dashboard" / "static"


def test_trailer_files_exist_and_load_from_the_static_route():
    page = (STATIC / "trailer.html").read_text(encoding="utf-8")
    for src in re.findall(r'src="(static/[^"]+)"', page):
        assert (STATIC / src.replace("static/", "", 1)).exists(), src
    for url in re.findall(r"url\('(static/[^']+)'\)", page):
        assert (STATIC / url.replace("static/", "", 1)).exists(), url
    assert 'src="/?demo#/"' in page      # the footage is the demo lab, never the real one


def test_every_route_the_trailer_visits_is_a_dashboard_page():
    js = (STATIC / "trailer" / "trailer.js").read_text(encoding="utf-8")
    app = (STATIC / "ui" / "app.js").read_text(encoding="utf-8")
    pages = set(re.findall(r"(\w+): \(\) => (?:null|NL\.\w+)", app))
    assert {"home", "runs", "studies", "artifacts", "compose", "labs"} <= pages
    for hash_ in re.findall(r"go\('#/([a-z]*)", js):
        assert (hash_ or "home") in pages, hash_


def test_the_controls_the_trailer_uses_still_exist():
    js = (STATIC / "trailer" / "trailer.js").read_text(encoding="utf-8")
    ui = "".join(p.read_text(encoding="utf-8") for p in (STATIC / "ui").glob("*.js"))
    for api in sorted(set(re.findall(r"NL\(\)\.(\w+)\(", js))):
        assert f"NL.{api} =" in ui, api
    for cls in ["askbar-in", "art-row", "lenses", "topbtn", "rail-sec"]:
        assert cls in ui or cls in (STATIC / "ui" / "ui.css").read_text(encoding="utf-8"), cls
    for label in ["Approve Gate", "Approve and start"]:
        assert label in ui, label
