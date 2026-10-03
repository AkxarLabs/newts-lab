"""The lab's own files, read the same way by every tool: lab/config.yaml, lab/REGISTRY.md, and where a
study's project repo lives — plus the few defensive readers everything shares. Every lab function takes
the hub root, so a tool (or a test) can point it anywhere. pyyaml is used for YAML; the rest is stdlib.

    read_text(path)                    the text ("" when unreadable; bad bytes replaced, never raised)
    read_jsonl(path, tail=None)        the dict lines of a JSONL file (torn/invalid lines skipped)
    load_yaml(path)                    a YAML file as a dict ({} when missing, malformed or not a mapping)
    to_int / to_float(v, default)      a number, or the default
    now() / parse_ts(ts)               the lab's local timestamp format, and back to epoch seconds
    read_env(path)                     KEY=value lines (lab/.env.local)
    config(hub)                        lab/config.yaml
    registry_rows(hub)                 the registry table as dicts (COLS)
    row(hub, slug)                     one idea's row
    projects_root(hub)                 lab.projects_root, resolved against the hub
    registry_project_path(hub, slug)   the row's Project column (an /adopt-ed repo can live anywhere)
    project_dir(hub, slug)             that, or projects_root/<slug> when it exists
    project_types(hub)                 {type: its TYPE.md} — every folder in templates/project-types/
"""

from __future__ import annotations

import json
import time
from pathlib import Path

COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
DEFAULT_PROJECTS_ROOT = "../newts-lab-projects"
_EMPTY = ("—", "-", "")


def read_text(path) -> str:
    # errors="replace": one non-UTF-8 byte a training script writes into a tailed file must not raise
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def read_jsonl(path, tail: int | None = None) -> list[dict]:
    lines = read_text(path).splitlines()
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


def load_yaml(path) -> dict:
    try:
        import yaml
        data = yaml.safe_load(read_text(path))
    except Exception:  # noqa: BLE001 — a malformed file is an empty config, never a crash
        return {}
    return data if isinstance(data, dict) else {}


def to_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def to_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


def now() -> str:
    return time.strftime(TS_FORMAT)


def parse_ts(ts) -> float | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return time.mktime(time.strptime(ts[:19], TS_FORMAT))
    except ValueError:
        return None


def read_env(path) -> dict:
    """KEY=value lines (lab/.env.local): comments and blanks skipped, surrounding quotes removed."""
    out = {}
    for line in read_text(path).splitlines():
        k, eq, v = line.strip().partition("=")
        if eq and k.strip() and not k.lstrip().startswith("#"):
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def config(hub) -> dict:
    return load_yaml(Path(hub) / "lab" / "config.yaml")


def registry_rows(hub) -> list[dict]:
    reg = Path(hub) / "lab" / "REGISTRY.md"
    out = []
    for line in read_text(reg).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < len(COLS) or cells[0] in ("ID", "", "—") or set(cells[0]) <= {"-"}:
            continue
        out.append(dict(zip(COLS, cells)))
    return out


def row(hub, slug: str) -> dict | None:
    return next((r for r in registry_rows(hub) if r["id"] == slug), None) if slug else None


def projects_root(hub) -> Path:
    root = (config(hub).get("lab") or {}).get("projects_root")
    return (Path(hub) / (root or DEFAULT_PROJECTS_ROOT)).resolve()


def registry_project_path(hub, slug: str, r: dict | None = None) -> Path | None:
    r = r or row(hub, slug)
    raw = ((r or {}).get("project") or "").strip().strip("`")
    if raw in _EMPTY:
        return None
    p = Path(raw)
    return p if p.is_absolute() else (Path(hub) / p).resolve()


def project_dir(hub, slug: str, r: dict | None = None) -> Path | None:
    p = registry_project_path(hub, slug, r)
    if p:
        return p
    cand = projects_root(hub) / slug
    return cand if cand.exists() else None


def project_types(hub) -> dict[str, str]:
    """Every project type (templates/project-types/<type>/TYPE.md): adding one is adding that folder."""
    root = Path(hub) / "templates" / "project-types"
    out = {}
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        f = d / "TYPE.md"
        if f.is_file():
            out[d.name] = f.read_text(encoding="utf-8", errors="replace")
    return out
