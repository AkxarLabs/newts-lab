"""The lab's read-only tools, run from the dashboard (the Tools menu, a study's claims audit): only these,
never anything that trains or writes.
"""

from __future__ import annotations

import subprocess
import sys

import ctx


# Read-only / safe tools the dashboard may run directly. Never anything that trains or writes.
# audit_claims runs tools/audit_claims.py (reads claims.yaml + artifacts, prints PASS/FAIL/MANUAL — writes nothing).
SAFE_TOOLS = {"check_lab", "show_config", "status", "compare", "inbox", "slots", "audit_claims"}


def run_tool(name: str, idea: str | None = None) -> dict:
    if name not in SAFE_TOOLS:
        return {"error": f"tool '{name}' is not in the read-only whitelist"}
    py = sys.executable
    pdir = ctx.pdir(idea) if idea else None
    cmd, cwd = None, ctx.HUB
    if name == "check_lab":
        cmd = [py, str(ctx.HUB / "tools" / "check_lab.py")]
    elif name == "show_config":
        cmd = [py, str(ctx.HUB / "tools" / "show_config.py")] + ([str(pdir)] if pdir else [])
    elif name == "slots":
        cmd = [py, str(ctx.HUB / "tools" / "run_slots.py"), "status"]
    elif name == "audit_claims":
        s = ctx.slug(idea or "")
        if not s:
            return {"error": "audit_claims needs an idea slug"}
        rel_tol = (ctx.config().get("critique") or {}).get("claim_rel_tol", 1e-3)
        cmd = [py, str(ctx.HUB / "tools" / "audit_claims.py"), f"studies/{s}/paper", "--rel-tol", str(rel_tol)]
    elif name == "inbox":
        if pdir:
            cmd, cwd = [py, str(pdir / "scripts" / "lab_bus.py"), "inbox"], pdir
        else:
            cmd = [py, str(ctx.HUB / "tools" / "lab_bus.py"), "inbox"]
    elif name in ("status", "compare"):
        if not pdir:
            return {"error": f"'{name}' needs a project (pass idea)"}
        script = pdir / "scripts" / f"{name}.py"
        # compare.py requires a subcommand (`list`); status.py takes none.
        cmd, cwd = [py, str(script)] + (["list", "--last", "20"] if name == "compare" else []), pdir
    try:
        out = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        return {"ok": True, "tool": name, "exit": out.returncode,
                "output": (out.stdout or "") + (("\n[stderr]\n" + out.stderr) if out.stderr.strip() else "")}
    except subprocess.TimeoutExpired:
        return {"error": f"{name} timed out"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{name} failed: {e}"}
