"""The System page: what the machine this lab lives on offers (tools/system_probe.py — CPUs, memory, GPUs,
disk, job schedulers), and the lab's compute.scheduler block in lab/config.yaml (how training runs here).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time

import ctx
import settings


_SYS_CACHE: dict = {"hub": None, "at": 0.0, "facts": None}


_SAFE_WORD = re.compile(r"^[A-Za-z0-9_.,:=+@/%-]{0,120}$")


def system_info(q: dict) -> tuple[dict, int]:
    """tools/system_probe.py run on the machine this lab lives on (cached 10 min) + the scheduler block."""
    fresh = bool(q.get("fresh"))
    if fresh or _SYS_CACHE["hub"] != str(ctx.HUB) or time.time() - _SYS_CACHE["at"] > 600 or not _SYS_CACHE["facts"]:
        r = subprocess.run([sys.executable, str(ctx.TOOLS / "system_probe.py"),
                            "--hub", str(ctx.HUB)], capture_output=True, text=True, timeout=90)
        try:
            _SYS_CACHE.update(hub=str(ctx.HUB), at=time.time(), facts=json.loads(r.stdout))
        except ValueError:
            return {"error": f"the system probe failed: {(r.stderr or r.stdout)[-300:]}"}, 500
    cfg = ctx.config()
    sched = ((cfg.get("compute") or {}).get("scheduler")) or {"kind": "local"}
    return {"ok": True, "facts": _SYS_CACHE["facts"], "scheduler": sched,
            "system_md": (ctx.LAB / "SYSTEM.md").exists()}, 200


def _clean_scheduler(sc: dict) -> dict:
    """Validate the form into a compute.scheduler block (raises ValueError with a PI-readable message)."""
    kind = str(sc.get("kind") or "local")
    if kind not in ("local", "slurm", "custom"):
        raise ValueError("kind must be local, slurm or custom")
    stages = [str(x).upper() for x in (sc.get("stages") or ["PILOT", "FULL"])]
    if not set(stages) <= {"SMOKE", "PILOT", "FULL"}:
        raise ValueError("stages are SMOKE, PILOT, FULL")
    out: dict = {"kind": kind, "stages": stages,
                 "poll_seconds": int(sc.get("poll_seconds") or 30), "max_queue_hours": float(sc.get("max_queue_hours") or 48)}
    if not (5 <= out["poll_seconds"] <= 3600):
        raise ValueError("poll_seconds must be 5–3600")

    def lines(v, what, maxn=20):
        v = v if isinstance(v, list) else [x for x in str(v or "").splitlines()]
        v = [str(x).rstrip() for x in v if str(x).strip()]
        if len(v) > maxn or any("\n" in x or len(x) > 400 for x in v):
            raise ValueError(f"{what}: at most {maxn} lines of ≤400 characters")
        return v
    s = sc.get("slurm") or {}
    slurm: dict = {}
    for k in ("partition", "account", "qos", "constraint", "mem", "gres"):
        v = str(s.get(k) or "").strip()
        if v and not _SAFE_WORD.match(v):
            raise ValueError(f"slurm.{k} has characters a SLURM value can't have")
        slurm[k] = v or None
    for k, hi in (("gpus_per_run", 64), ("cpus_per_task", 512), ("time_grace_minutes", 1440)):
        v = s.get(k)
        slurm[k] = int(v) if v not in (None, "") else (10 if k == "time_grace_minutes" else None)
        if slurm[k] is not None and not (0 <= slurm[k] <= hi):
            raise ValueError(f"slurm.{k} must be 0–{hi}")
    slurm["extra_args"] = lines(s.get("extra_args"), "slurm.extra_args")
    if any(not a.startswith("--") for a in slurm["extra_args"]):
        raise ValueError("each extra sbatch argument starts with --, e.g. --exclusive")
    slurm["setup"] = lines(s.get("setup"), "slurm.setup")
    out["slurm"] = slurm
    c = sc.get("custom") or {}
    out["custom"] = {"submit": str(c.get("submit") or "").strip() or None, "state": str(c.get("state") or "").strip() or None,
                     "cancel": str(c.get("cancel") or "").strip() or None, "header": lines(c.get("header"), "custom.header"),
                     "setup": lines(c.get("setup"), "custom.setup")}
    if kind == "custom" and (not out["custom"]["submit"] or "{script}" not in out["custom"]["submit"]):
        raise ValueError("a custom scheduler needs a submit command containing {script}")
    return out


def _replace_block(text: str, parent: str, key: str, block: dict) -> str:
    """Replace (or add) `parent:\n  key: …` with a freshly rendered block; everything else is kept."""
    import yaml
    body = yaml.safe_dump({key: block}, sort_keys=False, default_flow_style=False).rstrip("\n").split("\n")
    body = ["  " + ln for ln in body]
    body[0] = body[0] + "                    # how training runs on this machine — Settings → System (docs/compute.md)"
    lines = text.replace("\r\n", "\n").split("\n")
    pi = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(parent)}:\s*(#.*)?$", ln)), None)
    if pi is None:
        return text.rstrip("\n") + f"\n\n{parent}:\n" + "\n".join(body) + "\n"
    end = len(lines)
    for j in range(pi + 1, len(lines)):
        if lines[j].strip() and not lines[j].startswith((" ", "\t")):
            end = j
            break
    ki = next((j for j in range(pi + 1, end) if re.match(rf"  {re.escape(key)}:", lines[j])), None)
    if ki is None:
        ins = end
        while ins > pi + 1 and not lines[ins - 1].strip():
            ins -= 1
        return "\n".join(lines[:ins] + body + lines[ins:])
    kend = end
    for j in range(ki + 1, end):
        ln = lines[j]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= 2 and not ln.lstrip().startswith("#"):
            kend = j
            break
    while kend > ki + 1 and not lines[kend - 1].strip():
        kend -= 1
    return "\n".join(lines[:ki] + body + lines[kend:])


def system_scheduler_set(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "changing how training runs needs explicit confirm"}, 400
    try:
        block = _clean_scheduler(body.get("scheduler") or {})
    except (TypeError, ValueError) as e:
        return {"error": str(e)}, 400
    cfg = ctx.LAB / "config.yaml"
    text = ctx.read(cfg)
    if text is None:
        return {"error": "no lab/config.yaml"}, 400
    new = _replace_block(text, "compute", "scheduler", block)
    err = settings.reads_back(new, {("compute", "scheduler"): block})
    if err:
        return {"error": err}, 400
    ctx.write_keep_eol(cfg, text, new)
    ctx.pi_log({"action": "system.scheduler", "scheduler": block})
    return {"ok": True, "scheduler": block,
            "note": "training runs locally" if block["kind"] == "local" else f"PILOT/FULL runs now go through {block['kind']}"}, 200
