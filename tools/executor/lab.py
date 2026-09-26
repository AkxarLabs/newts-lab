"""The lab context every executor call runs against.

The executor never reads module globals for paths: every public function takes a `Lab`, built from
a hub root. Production builds `Lab()` (this repo); tests build `Lab(tmp_hub)`; the dashboard builds
`Lab(serve.HUB)` at call time. That keeps the whole package hermetically testable and lets several
hubs share one interpreter.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

DEFAULT_HUB = Path(__file__).resolve().parents[2]
REGISTRY_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
HUB_TARGET = "hub"


def load_yaml(path: Path) -> dict:
    """Always a dict — a missing, unreadable, non-mapping, or invalid YAML file is {}."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path, tail: int | None = None) -> list[dict]:
    """Parse a JSONL file, skipping torn/invalid lines. `tail` keeps only the last N lines."""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []
    if tail:
        lines = lines[-tail:]
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def pos_int(value, default: int, minimum: int) -> int:
    """Parse a numeric config knob defensively: unparseable -> default; below minimum -> clamped."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return v if v >= minimum else minimum


def pos_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class Lab:
    """Paths + config for one hub. Cheap to build; reads config lazily on every call (so a PI's
    /configure edit takes effect on the next tick without a restart)."""

    def __init__(self, hub: Path | str | None = None):
        self.hub = Path(hub).resolve() if hub else DEFAULT_HUB
        self.lab = self.hub / "lab"
        self.bus = self.lab / ".bus"
        self.tools = self.hub / "tools"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Lab({str(self.hub)!r})"

    # ── config ──────────────────────────────────────────────────────────────
    def config(self) -> dict:
        return load_yaml(self.lab / "config.yaml")

    def prog(self) -> dict:
        """agents.programmatic — the executor's whole config surface."""
        p = (self.config().get("agents") or {}).get("programmatic")
        return p if isinstance(p, dict) else {}

    def dashboard_cfg(self) -> dict:
        d = self.config().get("dashboard")
        return d if isinstance(d, dict) else {}

    # ── registry / projects ─────────────────────────────────────────────────
    def registry_rows(self) -> list[dict]:
        reg = self.lab / "REGISTRY.md"
        try:
            text = reg.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 8 or cells[0] in ("ID", "") or set(cells[0]) <= {"-"} or cells[0] == "—":
                continue
            out.append(dict(zip(REGISTRY_COLS, cells)))
        return out

    def row(self, slug: str) -> dict | None:
        return next((r for r in self.registry_rows() if r.get("id") == slug), None)

    def projects_root(self) -> Path:
        root = ((self.config().get("lab") or {}).get("projects_root")) or "../newts-lab-projects"
        return (self.hub / root).resolve()

    def project_dir(self, slug: str) -> Path | None:
        """A registered project's dir: the registry Project column wins, else projects_root/<slug>.
        Only an existing directory counts (a pre-spawn idea has none)."""
        row = self.row(slug)
        if row:
            raw = (row.get("project") or "").strip().strip("`")
            if raw and raw not in ("—", "-"):
                p = Path(raw)
                p = p if p.is_absolute() else (self.hub / p).resolve()
                return p if p.is_dir() else None
        cand = self.projects_root() / slug
        return cand if cand.is_dir() else None

    def project_dirs(self) -> list[tuple[str, Path]]:
        """(slug, dir) for every registry row whose project dir exists."""
        out, seen = [], set()
        for r in self.registry_rows():
            d = self.project_dir(r["id"])
            if d and d not in seen:
                seen.add(d)
                out.append((r["id"], d))
        return out

    # ── buses / agent dirs ──────────────────────────────────────────────────
    def target_dir(self, target: str) -> Path | None:
        """Where a run executes: the hub itself, or a project repo."""
        if target in (HUB_TARGET, "", None):
            return self.hub
        return self.project_dir(target)

    def bus_of(self, workdir: Path) -> Path:
        return self.bus if Path(workdir).resolve() == self.hub else Path(workdir) / ".bus"

    def source_of(self, workdir: Path) -> str:
        return HUB_TARGET if Path(workdir).resolve() == self.hub else Path(workdir).name

    def agents_dir(self, workdir: Path, create: bool = True) -> Path:
        d = self.bus_of(workdir) / "agents"
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def all_agent_dirs(self) -> list[tuple[str, Path, Path]]:
        """(target, workdir, agents_dir) for the hub and every registry project — existing dirs only."""
        out = [(HUB_TARGET, self.hub, self.bus / "agents")]
        out += [(slug, d, d / ".bus" / "agents") for slug, d in self.project_dirs()]
        return out

    @property
    def runs_ledger(self) -> Path:
        return self.bus / "runs.jsonl"

    @property
    def acks_ledger(self) -> Path:
        return self.bus / "attention-acks.jsonl"

    @property
    def pi_actions(self) -> Path:
        return self.bus / "pi-actions.jsonl"
