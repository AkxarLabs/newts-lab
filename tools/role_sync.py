"""Render backend-native subagent role files from ONE canonical source, so a lab role means the
same thing whether Claude or Codex runs it — and so the non-Claude scaffolding can't silently drift.

Canonical source: `agent-roles/<name>.yaml` (metadata) + `agent-roles/<name>.md` (the verbatim
instruction body). Rendered targets:
  - `.claude/agents/<name>.md`                       (Claude Code Task subagents — model from config)
  - `.codex/agents/<name>.toml`                       (Codex GA subagents)
  - `templates/project/.codex/agents/<name>.toml`     (the copy spawned projects ship)

Only Claude and Codex are rendered: their file schemas are known. opencode / Gemini CLI / Cursor are
COMPATIBILITY-ONLY (documented in docs/autonomy.md) until a CLI smoke proves their role-file schema —
the robust cross-backend path meanwhile is one headless process per unit of work via agent_runner.py.

    uv run --with pyyaml python tools/role_sync.py render     # write/update the generated files
    uv run --with pyyaml python tools/role_sync.py check      # exit 1 if any generated file is stale

The Claude `model:` line is resolved from `lab/config.yaml` agents.<model_key> (same source
tools/profiles.py and /configure sync), so a model change re-renders identically. Exit 0 = in sync.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _roles_dir() -> Path:
    return HUB / "agent-roles"


def _role_names() -> list[str]:
    return sorted(p.stem for p in _roles_dir().glob("*.yaml"))


def _cfg_agents() -> dict:
    return (_load_yaml(HUB / "lab" / "config.yaml").get("agents") or {})


def _norm(text: str) -> str:
    """Compare line-endings-insensitively (the generated files are LF; a CRLF checkout must not
    read as drift)."""
    return text.replace("\r\n", "\n")


def _model_for(meta: dict) -> str:
    key = meta.get("model_key")
    val = _cfg_agents().get(key) if key else None
    val = str(val).strip() if val is not None else ""
    return val or "inherit"


def _spec(name: str) -> tuple[dict, str]:
    meta = _load_yaml(_roles_dir() / f"{name}.yaml")
    body = _norm((_roles_dir() / f"{name}.md").read_text(encoding="utf-8"))
    if not body.endswith("\n"):
        body += "\n"
    return meta, body


def _render_claude(meta: dict, body: str) -> str:
    return ("---\n"
            f"name: {meta['name']}\n"
            f"description: {meta['description']}\n"
            f"tools: {meta['tools_claude']}\n"
            f"model: {_model_for(meta)}\n"
            "---\n\n" + body)


def _toml_str(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _render_codex(meta: dict, body: str) -> str:
    cx = meta.get("codex") or {}
    lines = [f'name = "{_toml_str(meta["name"])}"',
             f'description = "{_toml_str(meta["description"])}"']
    if cx.get("model_reasoning_effort"):
        lines.append(f'model_reasoning_effort = "{cx["model_reasoning_effort"]}"')
    lines.append(f'sandbox_mode = "{cx.get("sandbox_mode", "read-only")}"')
    lines += ['developer_instructions = """', body.rstrip("\n"), '"""']
    return "\n".join(lines) + "\n"


def _targets(name: str) -> list[tuple[Path, str]]:
    """(output path, kind) for one role. kind ∈ {claude, codex}."""
    return [
        (HUB / ".claude" / "agents" / f"{name}.md", "claude"),
        (HUB / ".codex" / "agents" / f"{name}.toml", "codex"),
        (HUB / "templates" / "project" / ".codex" / "agents" / f"{name}.toml", "codex"),
    ]


def _content(kind: str, meta: dict, body: str) -> str:
    return _render_claude(meta, body) if kind == "claude" else _render_codex(meta, body)


def _plan() -> list[tuple[Path, str]]:
    """(path, expected_content) for every generated file across every role."""
    out = []
    for name in _role_names():
        meta, body = _spec(name)
        for path, kind in _targets(name):
            out.append((path, _content(kind, meta, body)))
    return out


def render() -> int:
    changed = 0
    for path, expected in _plan():
        path.parent.mkdir(parents=True, exist_ok=True)
        current = _norm(path.read_text(encoding="utf-8")) if path.exists() else None
        if current == expected:
            continue
        path.write_text(expected, encoding="utf-8", newline="")  # LF on every platform
        changed += 1
        print(f"[role_sync] wrote {path.relative_to(HUB)}")
    print(f"[role_sync] render complete — {changed} file(s) written, "
          f"{len(_plan())} total across {len(_role_names())} role(s)")
    return 0


def check() -> int:
    stale = []
    for path, expected in _plan():
        current = _norm(path.read_text(encoding="utf-8")) if path.exists() else None
        if current != expected:
            stale.append(path.relative_to(HUB) if path.exists() else f"{path.relative_to(HUB)} (missing)")
    if stale:
        for s in stale:
            print(f"  - STALE: {s}")
        print(f"[role_sync] {len(stale)} generated file(s) out of sync — run `role_sync.py render`")
        return 1
    print(f"[role_sync] all {len(_plan())} generated role file(s) in sync")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="render/check backend-native subagent role files")
    ap.add_argument("cmd", choices=["render", "check"])
    a = ap.parse_args()
    return render() if a.cmd == "render" else check()


if __name__ == "__main__":
    sys.exit(main())
