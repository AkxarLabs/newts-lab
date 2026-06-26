"""Config profiles — named bundles of lab/config.yaml overrides (budget tiers + engine presets).

    uv run --with pyyaml python tools/profiles.py list
    uv run --with pyyaml python tools/profiles.py show high
    uv run --with pyyaml python tools/profiles.py diff high           # what apply would change
    uv run --with pyyaml python tools/profiles.py validate high       # rigor-floor check only
    uv run --with pyyaml python tools/profiles.py apply high          # stamp into lab/config.yaml
    uv run --with pyyaml python tools/profiles.py save my-preset      # snapshot current settings

A profile is a PARTIAL config (only the keys it sets), at lab/profiles/<name>.yaml. Budget tiers
(low/medium/high) scale EXPLORATION — agent/subagent counts, parallelism, model strength; engine
presets (claude-*/codex/opencode/mixed) set the headless backend. `apply` STAMPS each leaf value
into lab/config.yaml IN PLACE (comments preserved — no YAML round-trip that would strip the
documented reference file), syncs the .claude/agents/*.md `model:` frontmatter for per-role model
keys, and REFUSES any profile that lowers an integrity floor:
    experiment.multi_seed_n >= 3 · oversight.level != off · eval_frozen / gate2_envelope untouched.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"

# per-role model key -> the .claude/agents/<file>.md it drives (kept in sync on apply, like /configure)
AGENT_FILE = {"reviewer_model": "fresh-context-reviewer",
              "runner_model": "experiment-runner",
              "overseer_model": "overseer"}

# the dotted keys `save --from-current` snapshots (the budget/model/engine-choice surface)
PROFILE_KEYS = [
    "ideation.candidates", "ideation.reflection_rounds", "ideation.critics_per_idea",
    "ideation.enable_combination", "ideation.in_project_candidates",
    "scoping.options_per_decision", "scoping.advocate_subagents",
    "critique.ensemble_external", "critique.ensemble_own_draft", "critique.max_review_cycles",
    "experiment.num_drafts", "experiment.max_parallel_subagents", "experiment.multi_seed_n",
    "loop.explore_max_expansion_rounds", "loop.explore_max_new_lines_per_round",
    "discuss.max_research_minutes", "oversight.level",
    "agents.reviewer_model", "agents.runner_model", "agents.overseer_model",
    "agents.programmatic.backend", "agents.programmatic.max_concurrent",
]


# ── yaml + dict helpers ───────────────────────────────────────────────────────

def _load_yaml(p: Path) -> dict:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return {}


def _flatten(d: dict, prefix: tuple = ()) -> dict:
    """Leaf dotted-tuple -> value, e.g. {('agents','reviewer_model'): 'opus'}."""
    out: dict = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out.update(_flatten(v, prefix + (k,)))
        else:
            out[prefix + (k,)] = v
    return out


def _nest_set(d: dict, dotted: tuple, value) -> None:
    cur = d
    for k in dotted[:-1]:
        cur = cur.setdefault(k, {})
    cur[dotted[-1]] = value


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ── comment-preserving in-place stamp ─────────────────────────────────────────

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _block_end(lines: list, start: int, indent: int) -> int:
    """First line after `start` whose indent is <= `indent` (ignoring blank/comment lines)."""
    for i in range(start + 1, len(lines)):
        s = lines[i]
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        if _indent(s) <= indent:
            return i
    return len(lines)


def _find_key(lines: list, key: str, lo: int, hi: int, indent: int) -> int:
    pat = re.compile(r"^" + " " * indent + re.escape(key) + r"\s*:")
    for i in range(lo, hi):
        if pat.match(lines[i]):
            return i
    return -1


def _replace_value(line: str, value) -> str:
    """Swap the value on a `key: value  # comment` line, keeping the inline comment near its column."""
    m = re.match(r"^(\s*[A-Za-z0-9_]+\s*:)(\s*)([^#\n]*?)(\s*)(#.*)?$", line)
    if not m:
        return line
    keypart, sp, old, sp2, comment = m.groups()
    head = f"{keypart}{sp}{_fmt(value)}"
    if comment:
        orig_col = len(keypart) + len(sp) + len(old) + len(sp2)
        return f"{head}{' ' * max(1, orig_col - len(head))}{comment}"
    return head


def stamp(text: str, dotted: list, value) -> tuple:
    """Set nested key `dotted` to `value` in YAML `text`, preserving every other byte. lab/config.yaml
    uses 2-space indent per level. Returns (new_text, changed?). changed=False if the path is absent."""
    lines = text.split("\n")
    lo, hi, indent = 0, len(lines), 0
    for depth, key in enumerate(dotted):
        i = _find_key(lines, key, lo, hi, indent)
        if i < 0:
            return text, False
        if depth == len(dotted) - 1:
            lines[i] = _replace_value(lines[i], value)
            return "\n".join(lines), True
        lo, hi = i + 1, _block_end(lines, i, indent)
        indent += 2
    return text, False


# ── rigor floors ──────────────────────────────────────────────────────────────

def rigor_violations(flat: dict) -> list:
    """Reasons a profile must be refused — it would lower an integrity floor. Empty list = OK."""
    out = []
    for dotted, value in flat.items():
        key = ".".join(dotted)
        if key == "experiment.multi_seed_n":
            try:
                if int(value) < 3:
                    out.append(f"experiment.multi_seed_n={value} < 3 (paper-grade seed floor)")
            except (TypeError, ValueError):
                out.append(f"experiment.multi_seed_n={value!r} is not an integer")
        elif key == "oversight.level" and str(value).lower() == "off":
            out.append("oversight.level=off disables the confabulation circuit-breaker")
        elif key == "eval_frozen" and value is False:
            out.append("eval_frozen=false — a profile may never unfreeze the eval")
        elif key.startswith("gate2_envelope"):
            out.append(f"{key} — a profile may not touch the Gate-2 envelope (PI-signed)")
    return out


# ── agent frontmatter sync ────────────────────────────────────────────────────

def _sync_agent_model(role_key: str, value) -> bool:
    f = HUB / ".claude" / "agents" / (AGENT_FILE[role_key] + ".md")
    if not f.exists():
        return False
    text = f.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^model:[^\n]*$", f"model: {_fmt(value)}", text, count=1)
    if new != text:
        f.write_text(new, encoding="utf-8", newline="")   # keep LF on every platform
        return True
    return False


# ── profiles dir ──────────────────────────────────────────────────────────────

def _profiles_dir() -> Path:
    return LAB / "profiles"


def _profile_path(name: str) -> Path:
    return _profiles_dir() / f"{name}.yaml"


def _load_profile(name: str) -> dict:
    p = _profile_path(name)
    if not p.exists():
        print(f"no profile '{name}' at {p}", file=sys.stderr)
        raise SystemExit(2)
    return _load_yaml(p)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_list(args) -> int:
    d = _profiles_dir()
    files = sorted(d.glob("*.yaml")) if d.exists() else []
    if not files:
        print(f"no profiles in {d}")
        return 0
    print(f"## Profiles in {d}\n")
    for f in files:
        first = next((ln.strip("# ").rstrip() for ln in f.read_text(encoding="utf-8").splitlines()
                      if ln.strip().startswith("#")), "")
        print(f"- **{f.stem}** — {first}")
    return 0


def cmd_show(args) -> int:
    print(_profile_path(args.name).read_text(encoding="utf-8"))
    return 0


def cmd_diff(args) -> int:
    flat = _flatten(_load_profile(args.name))
    cur = _flatten(_load_yaml(LAB / "config.yaml"))
    print(f"## diff: lab/config.yaml -> profile '{args.name}'\n")
    changes = 0
    for dotted, value in flat.items():
        old = cur.get(dotted, "(absent)")
        if str(old) != str(value):
            print(f"  {'.'.join(dotted)}: {old}  ->  {value}")
            changes += 1
    if not changes:
        print("  (no changes — config already matches this profile)")
    return 0


def cmd_validate(args) -> int:
    violations = rigor_violations(_flatten(_load_profile(args.name)))
    if violations:
        print(f"profile '{args.name}' REFUSED — would lower an integrity floor:")
        for v in violations:
            print("  - " + v)
        return 1
    print(f"profile '{args.name}' OK — keeps every integrity floor")
    return 0


def cmd_apply(args) -> int:
    flat = _flatten(_load_profile(args.name))
    violations = rigor_violations(flat)
    if violations:
        print(f"REFUSED — profile '{args.name}' would lower an integrity floor:")
        for v in violations:
            print("  - " + v)
        print("(budget scales exploration, never rigor — fix the profile and retry)")
        return 1
    cfg = LAB / "config.yaml"
    text = cfg.read_text(encoding="utf-8")
    changed, missing = [], []
    for dotted, value in flat.items():
        new, ok = stamp(text, list(dotted), value)
        if ok:
            text = new
            changed.append(f"{'.'.join(dotted)} = {_fmt(value)}")
        else:
            missing.append(".".join(dotted))
    cfg.write_text(text, encoding="utf-8", newline="")   # keep LF on every platform
    synced = [f"{AGENT_FILE[d[1]]} -> {v}" for d, v in flat.items()
              if len(d) == 2 and d[0] == "agents" and d[1] in AGENT_FILE and _sync_agent_model(d[1], v)]
    print(f"Applied profile '{args.name}' to lab/config.yaml — {len(changed)} key(s) set.")
    for c in changed:
        print("  " + c)
    if synced:
        print("Agent model frontmatter synced: " + "; ".join(synced))
    if missing:
        print("WARN — keys not present in lab/config.yaml (skipped): " + ", ".join(missing))
    return 0


def cmd_save(args) -> int:
    cur = _flatten(_load_yaml(LAB / "config.yaml"))
    out: dict = {}
    for key in PROFILE_KEYS:
        dotted = tuple(key.split("."))
        if dotted in cur:
            _nest_set(out, dotted, cur[dotted])
    _profiles_dir().mkdir(parents=True, exist_ok=True)
    dest = _profile_path(args.name)
    header = (f"# Saved profile: {args.name} — snapshot of the current budget / model settings.\n"
              f"# Apply with: uv run --with pyyaml python tools/profiles.py apply {args.name}\n")
    dest.write_text(header + yaml.safe_dump(out, sort_keys=False, default_flow_style=False),
                    encoding="utf-8", newline="")
    print(f"Saved {len(_flatten(out))} key(s) to {dest}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    for name in ("show", "diff", "validate", "apply", "save"):
        p = sub.add_parser(name)
        p.add_argument("name")
        p.set_defaults(fn={"show": cmd_show, "diff": cmd_diff, "validate": cmd_validate,
                           "apply": cmd_apply, "save": cmd_save}[name])
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
