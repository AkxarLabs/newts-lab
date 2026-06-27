"""Hermetic test harness for the hub's trust tools.

Every hub tool resolves paths from a module-global ``HUB = Path(__file__).resolve().parents[1]``
(and some have ``LAB = HUB / "lab"``). The tools read those globals *at call time*, so each test
loads the tool as a fresh module object and ``monkeypatch.setattr``-s its globals to a throwaway
``tmp_path`` fake hub built by the ``hub`` fixture. Nothing here touches the real lab, the network,
or a port — pure ``tmp_path`` and in-process function calls.

Exposed:
  REPO         — absolute Path to the repo root (so tests load the *real* tool source).
  load(name)   — import a tool module fresh from ``REPO/tools/<name>.py`` (or a full relative path).
  hub fixture  — builds a minimal fake hub under tmp_path and returns a small handle object.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

# tests/ lives directly under the repo root.
REPO = Path(__file__).resolve().parents[1]


def load(name: str):
    """Load a tool module fresh from the repo, by short name or relative path.

    ``load("audit_claims")``  -> REPO/tools/audit_claims.py
    ``load("dashboard/sources")`` -> REPO/dashboard/sources.py
    Each call produces an independent module object so a test's global overrides never leak.
    """
    if "/" in name or name.endswith(".py"):
        rel = name if name.endswith(".py") else f"{name}.py"
        path = REPO / rel
        mod_name = f"_hubtest_{Path(rel).stem}_{abs(hash(rel))}"
    else:
        path = REPO / "tools" / f"{name}.py"
        mod_name = f"_hubtest_{name}_{abs(hash(name))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    # Register so dataclasses / relative imports that look themselves up resolve.
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# ── the fake-hub fixture ──────────────────────────────────────────────────────

_CONFIG_YAML = textwrap.dedent(
    """\
    lab:
      projects_root: "../projects"
      stale_days: 14
    compute:
      max_concurrent_runs: 1
      stale_slot_minutes: 360
    dashboard:
      port: 8787
    """
)

_REGISTRY_HEADER = textwrap.dedent(
    """\
    # Lab Registry

    **States:** `seed` · `active` · `final`

    | ID | Title | State | Idea | Project | Paper | Updated | Next action |
    |----|-------|-------|------|---------|-------|---------|-------------|
    """
)


class FakeHub:
    """Handle to a fake hub built under tmp_path. ``root`` is the hub dir; ``projects_root`` is its
    sibling project root (``../projects`` per the fixture config)."""

    def __init__(self, root: Path):
        self.root = root
        self.lab = root / "lab"
        self.projects_root = (root / ".." / "projects").resolve()
        self._rows: list[dict] = []

    # --- registry helpers -----------------------------------------------------
    def add_registry_row(self, id, title="T", state="seed", idea="-", project="-",
                         paper="-", updated="2026-06-19", next="-"):
        self._rows.append(dict(id=id, title=title, state=state, idea=idea,
                               project=project, paper=paper, updated=updated, next=next))
        self._write_registry()

    def _write_registry(self):
        lines = [_REGISTRY_HEADER.rstrip("\n")]
        for r in self._rows:
            lines.append("| " + " | ".join([r["id"], r["title"], r["state"], r["idea"],
                                             r["project"], r["paper"], r["updated"],
                                             r["next"]]) + " |")
        (self.lab / "REGISTRY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- project scaffolding --------------------------------------------------
    def make_project(self, slug: str, *, control: bool = True, eval_frozen=True,
                     gate2=None, in_root: bool = True) -> Path:
        """Create a project dir (under projects_root by default) with a minimal control.yaml."""
        pdir = (self.projects_root / slug) if in_root else (self.root / ".." / "elsewhere" / slug).resolve()
        pdir.mkdir(parents=True, exist_ok=True)
        if control:
            self.write_control(pdir, eval_frozen=eval_frozen, gate2=gate2)
        return pdir

    def write_control(self, pdir: Path, *, eval_frozen=True, gate2=None):
        import yaml
        doc = {
            "eval_frozen": eval_frozen,
            "budgets": {"max_minutes": 10},
            "seeds": [0, 1, 2],
            "gate2_envelope": gate2 if gate2 is not None else {
                "pi_signed": False, "signed_via": None, "expires": None,
                "full_runs": 0, "per_run_max_minutes": 0, "total_max_minutes": 0,
            },
        }
        (pdir / "control.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    def write_metrics(self, pdir: Path, rel: str, data: dict):
        import json
        f = pdir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), encoding="utf-8")
        return f

    def notebook_entry(self, name: str, body: str):
        nb = self.lab / "notebook"
        nb.mkdir(parents=True, exist_ok=True)
        (nb / name).write_text(body, encoding="utf-8")


@pytest.fixture
def hub(tmp_path) -> FakeHub:
    """A minimal fake hub: lab/config.yaml (projects_root -> ../projects), REGISTRY.md header,
    empty knowledge/notebook dirs. Sibling projects_root is created too."""
    root = tmp_path / "hub"
    lab = root / "lab"
    (lab / "knowledge").mkdir(parents=True, exist_ok=True)
    (lab / "notebook").mkdir(parents=True, exist_ok=True)
    (lab / "config.yaml").write_text(_CONFIG_YAML, encoding="utf-8")
    (lab / "REGISTRY.md").write_text(_REGISTRY_HEADER, encoding="utf-8")
    for kf in ("FINDINGS.md", "FAILURES.md", "OPEN-QUESTIONS.md", "REFERENCES.md"):
        (lab / "knowledge" / kf).write_text(f"# {kf}\n", encoding="utf-8")
    h = FakeHub(root)
    h.projects_root.mkdir(parents=True, exist_ok=True)
    return h
