"""The lab's own files, read the same way by every tool: lab/config.yaml, lab/REGISTRY.md, and where a
study's project repo lives. Every function takes the hub root, so a tool (or a test) can point it
anywhere. pyyaml is used for YAML; the rest is stdlib.

    load_yaml(path)                    a YAML file as a dict ({} when missing or malformed)
    registry_rows(hub)                 the registry table as dicts (COLS)
    row(hub, slug)                     one idea's row
    projects_root(hub)                 lab.projects_root, resolved against the hub
    registry_project_path(hub, slug)   the row's Project column (an /adopt-ed repo can live anywhere)
    project_dir(hub, slug)             that, or projects_root/<slug> when it exists
"""

from __future__ import annotations

from pathlib import Path

COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
DEFAULT_PROJECTS_ROOT = "../newts-lab-projects"
_EMPTY = ("—", "-", "")


def load_yaml(path) -> dict:
    try:
        import yaml
        return yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001 — a missing / malformed file is an empty config
        return {}


def registry_rows(hub) -> list[dict]:
    reg = Path(hub) / "lab" / "REGISTRY.md"
    try:
        text = reg.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
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
    root = (load_yaml(Path(hub) / "lab" / "config.yaml").get("lab") or {}).get("projects_root")
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
