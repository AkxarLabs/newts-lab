"""Render backend-native subagent role files from ONE canonical source, so a lab role means the
same thing whether Claude or Codex runs it — and so the non-Claude scaffolding can't silently drift.

Canonical source: `agent-roles/<name>.yaml` (metadata) + `agent-roles/<name>.md` (the verbatim
instruction body). Rendered targets:
  - `.claude/agents/<name>.md` · `.codex/agents/<name>.toml`   (HUB subagents — RESOLVED from the
                                                                live config, so a hub session's
                                                                subagents honor the PI's tier ladder)
  - `templates/project/.claude/agents/<name>.md` · `.codex/...` (the shipped project TEMPLATE — always
                                                                rendered NEUTRAL: `model: inherit` /
                                                                role-yaml effort, so a PI's local tier
                                                                choice can never leak into the
                                                                committed template)

A spawned project INSTANCE is resolved at spawn by `render_project(dir)` (called from
tools/spawn_project.py) — a snapshot of the hub tiers at that moment, so the project (and any headless
agent working in it) runs its named-role subagents at the resolved tier, not the neutral `inherit`.

Claude, Codex and opencode are rendered (`.opencode/agents/<name>.md`: `mode: subagent`, the role's
Claude tool list mapped onto opencode permissions, no model line — opencode models are provider/model
strings the lab's tier ladder doesn't know, so its subagents inherit the session model). Gemini CLI /
Cursor stay COMPATIBILITY-ONLY (docs/autonomy.md).

    uv run --with pyyaml python tools/role_sync.py render               # write/update hub + template
    uv run --with pyyaml python tools/role_sync.py check                # exit 1 if any is stale
    uv run --with pyyaml python tools/role_sync.py render-project <dir>  # resolve tiers into a project
    uv run --with pyyaml python tools/role_sync.py resolve <role>        # print a role's model+effort

`resolve <role>` (reviewer|runner|overseer|critic) is the token-free spawn helper: skills that spawn
the INLINE critics/advocates (no role file) run it once and pass the printed model/effort to each Task
spawn, instead of the agent re-deriving them from config. The Claude `model:`/`effort:` lines resolve
from `lab/config.yaml` agents.<role>_model / _effort — a role key may name a TIER
(agents.tiers.strong/standard/fast) or a model directly; both flow through resolve_model (same source
tools/profiles.py and /configure sync), so a tier or model change re-renders identically. Exit 0 = in sync.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
import labfiles  # noqa: E402 — the lab's files, read one way (tools/labfiles.py)


def _roles_dir() -> Path:
    return HUB / "agent-roles"


def _role_names() -> list[str]:
    return sorted(p.stem for p in _roles_dir().glob("*.yaml"))


def _cfg_agents() -> dict:
    return (labfiles.load_yaml(HUB / "lab" / "config.yaml").get("agents") or {})


def _norm(text: str) -> str:
    """Compare line-endings-insensitively (the generated files are LF; a CRLF checkout must not
    read as drift)."""
    return text.replace("\r\n", "\n")


def resolve_model(val: str, agents_cfg: dict) -> str:
    """Resolve a tier name (agents.tiers) to its model; pass anything else through.
    Cycle-safe; empty/None -> inherit."""
    tiers = agents_cfg.get("tiers") or {}
    seen = set()
    val = (str(val).strip() if val is not None else "") or "inherit"
    while val in tiers and val not in seen:
        seen.add(val)
        val = (str(tiers[val]).strip() if tiers[val] is not None else "") or "inherit"
    return val


# role name -> (model_key, effort_key) in lab/config.yaml agents.*. The three NAMED roles also have
# an agent-roles/<name>.yaml (rendered role files); `critic` is the INLINE ideation-critic / scoping-
# advocate — no role file, resolved on demand by resolve_role() for a per-spawn Task model/effort.
_ROLE_KEYS = {
    "reviewer": ("reviewer_model", "reviewer_effort"),
    "runner": ("runner_model", "runner_effort"),
    "overseer": ("overseer_model", "overseer_effort"),
    "critic": ("critic_model", "critic_effort"),
}


def _model_for(meta: dict, agents_cfg: dict) -> str:
    key = meta.get("model_key")
    return resolve_model(agents_cfg.get(key) if key else None, agents_cfg)


def _effort_for(meta: dict, agents_cfg: dict) -> str:
    """Per-role reasoning effort from agents.<role>_effort (the model_key with _model -> _effort).
    '' = the model's default (render nothing)."""
    key = meta.get("model_key")
    if not key:
        return ""
    val = agents_cfg.get(key.replace("_model", "_effort"))
    return str(val).strip() if val is not None else ""


def resolve_role(role: str, agents_cfg: dict | None = None) -> tuple[str, str]:
    """Mechanically resolve a role's (model, effort) from the hub config — model through the tier
    ladder, effort as a direct value. The token-free path skills use to spawn INLINE subagents
    (critics/advocates) with the right model/effort, instead of the agent re-deriving it from config."""
    cfg = _cfg_agents() if agents_cfg is None else agents_cfg
    mkey, ekey = _ROLE_KEYS[role]
    model = resolve_model(cfg.get(mkey), cfg)
    effort = cfg.get(ekey)
    return model, (str(effort).strip() if effort is not None else "")


def _spec(name: str) -> tuple[dict, str]:
    meta = labfiles.load_yaml(_roles_dir() / f"{name}.yaml")
    body = _norm((_roles_dir() / f"{name}.md").read_text(encoding="utf-8"))
    if not body.endswith("\n"):
        body += "\n"
    return meta, body


def _with_pi(name: str, body: str) -> str:
    """The role body plus the PI's lab-wide instructions for this role (lab/workflow/roles/<role>.add.md,
    edited in the dashboard's Workflow page). Hub and spawned-project copies carry them; the shipped
    template copies never do."""
    try:
        sys.path.insert(0, str(HUB / "tools"))
        import workflow  # noqa: PLC0415
        add = workflow.role_addon(name, HUB)
    except Exception:  # noqa: BLE001 — no manifest / unreadable: the role as shipped
        add = ""
    if not add:
        return body
    return body.rstrip("\n") + "\n\n## The PI's instructions for this role\n\n" + _norm(add).rstrip("\n") + "\n"


def _render_claude(meta: dict, body: str, agents_cfg: dict) -> str:
    effort = _effort_for(meta, agents_cfg)
    effort_line = f"effort: {effort}\n" if effort else ""   # '' = model default -> emit no effort line
    return ("---\n"
            f"name: {meta['name']}\n"
            f"description: {meta['description']}\n"
            f"tools: {meta['tools_claude']}\n"
            f"model: {_model_for(meta, agents_cfg)}\n"
            f"{effort_line}"
            "---\n\n" + body)


def _toml_str(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _render_codex(meta: dict, body: str, agents_cfg: dict) -> str:
    cx = meta.get("codex") or {}
    lines = [f'name = "{_toml_str(meta["name"])}"',
             f'description = "{_toml_str(meta["description"])}"']
    if cx.get("model"):                                    # optional per-role Codex model (absent today)
        lines.append(f'model = "{_toml_str(cx["model"])}"')
    effort = _effort_for(meta, agents_cfg) or cx.get("model_reasoning_effort")  # config override, else role-yaml default
    if effort:
        lines.append(f'model_reasoning_effort = "{effort}"')
    lines.append(f'sandbox_mode = "{cx.get("sandbox_mode", "read-only")}"')
    lines += ['developer_instructions = """', body.rstrip("\n"), '"""']
    return "\n".join(lines) + "\n"


def _render_opencode(meta: dict, body: str, agents_cfg: dict) -> str:
    """opencode agent file (1.18 schema: description, mode, permission{edit,bash,webfetch,task,...}).
    A lab subagent never spawns subagents (hard rule), so `task` is always denied."""
    import json as _json
    tools = {t.strip() for t in str(meta.get("tools_claude") or "").split(",") if t.strip()}
    perm = {"edit": "allow" if tools & {"Edit", "Write", "NotebookEdit"} else "deny",
            "bash": "allow" if "Bash" in tools else "deny",
            "webfetch": "allow" if "WebFetch" in tools else "deny",
            "websearch": "allow" if "WebSearch" in tools else "deny",
            "task": "deny"}
    lines = ["---", f"description: {_json.dumps(str(meta['description']))}", "mode: subagent", "permission:"]
    lines += [f"  {k}: {v}" for k, v in perm.items()]
    return "\n".join(lines) + "\n---\n\n" + body


# Per role: the two HUB files render from the LIVE config (a hub session's subagents honor the PI's
# ladder); the two project-TEMPLATE files render NEUTRAL (empty config -> model: inherit / role-yaml
# effort) so a PI's local tier choice can never leak into the committed, shipped template. A spawned
# project INSTANCE is resolved at spawn by render_project(), never here.
def _rel_targets(name: str) -> list[tuple[Path, str]]:
    return [(Path(".claude") / "agents" / f"{name}.md", "claude"),
            (Path(".codex") / "agents" / f"{name}.toml", "codex"),
            (Path(".opencode") / "agents" / f"{name}.md", "opencode")]


def _content(kind: str, meta: dict, body: str, agents_cfg: dict) -> str:
    return {"claude": _render_claude, "codex": _render_codex, "opencode": _render_opencode}[kind](meta, body, agents_cfg)


def _plan() -> list[tuple[Path, str]]:
    """(path, expected_content) for every generated file across every role — HUB files resolved from
    the live config, TEMPLATE files rendered neutral (`{}`)."""
    live = _cfg_agents()
    out = []
    for name in _role_names():
        meta, body = _spec(name)
        for rel, kind in _rel_targets(name):
            out.append((HUB / rel, _content(kind, meta, _with_pi(name, body), live)))       # hub: resolved + PI
            out.append((HUB / "templates" / "project" / rel, _content(kind, meta, body, {})))  # template: neutral
    return out


def render_project(project_dir) -> int:
    """Resolve the CURRENT hub tier/effort config into a spawned project's role files — a spawn-time
    SNAPSHOT (it does NOT track later hub `/configure` changes; re-run to refresh). Called by
    spawn_project after the template copy so the project (and any headless agent working in it) runs
    its named-role subagents at the resolved tier, not the template's neutral `inherit`. It CREATES the
    role files (both backends) — so a spawned project always ships them even if the committed template
    somehow lacked the dir; spawn correctness never silently depends on the template being complete.
    Resolves against `role_sync.HUB` (== spawn_project's hub in every real call). Returns files written."""
    project_dir = Path(project_dir)
    live = _cfg_agents()
    written = 0
    for name in _role_names():
        meta, body = _spec(name)
        for rel, kind in _rel_targets(name):
            path = project_dir / rel
            expected = _content(kind, meta, _with_pi(name, body), live)
            current = _norm(path.read_text(encoding="utf-8")) if path.exists() else None
            if current != expected:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8", newline="")
                written += 1
    return written


def project_stale(project_dir) -> list[Path]:
    """Role files in a spawned project that `render_project` would (re)write — a read-only check."""
    project_dir = Path(project_dir)
    live = _cfg_agents()
    stale = []
    for name in _role_names():
        meta, body = _spec(name)
        for rel, kind in _rel_targets(name):
            path = project_dir / rel
            current = _norm(path.read_text(encoding="utf-8")) if path.exists() else None
            if current != _content(kind, meta, _with_pi(name, body), live):
                stale.append(path)
    return stale


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
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render")
    sub.add_parser("check")
    rp = sub.add_parser("render-project", help="resolve the live hub tiers into a project's role files")
    rp.add_argument("project_dir")
    rv = sub.add_parser("resolve", help="print a role's resolved model/effort (token-free spawn helper)")
    rv.add_argument("role", choices=sorted(_ROLE_KEYS))
    a = ap.parse_args()
    if a.cmd == "render":
        return render()
    if a.cmd == "check":
        return check()
    if a.cmd == "render-project":
        n = render_project(a.project_dir)
        print(f"[role_sync] render-project {a.project_dir} — {n} role file(s) resolved from the hub tiers")
        return 0
    model, effort = resolve_role(a.role)      # `resolve <role>`: one mechanical line per field
    print(f"model={model}")
    print(f"effort={effort}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
