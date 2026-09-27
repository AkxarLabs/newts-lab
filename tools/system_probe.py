"""What this machine offers the lab: CPUs, memory, GPUs, disk, job schedulers (and SLURM partitions),
environment modules, and the tools the lab uses. Read-only; prints JSON.

    uv run --with pyyaml python tools/system_probe.py [--hub <lab>]

The dashboard's Settings → System shows it (for a remote lab, it runs on that machine) and uses it to
prefill `compute.scheduler` — the structured half of describing a machine. The prose half (quirks, data
locations, site rules) is lab/SYSTEM.md.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]


def _out(argv: list[str], timeout: float = 20) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _mem_gb() -> float | None:
    try:
        if sys.platform.startswith("linux"):
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
        if sys.platform == "darwin":
            v = _out(["sysctl", "-n", "hw.memsize"]).strip()
            return round(int(v) / 1024 ** 3, 1) if v else None
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def _gpus() -> list[dict]:
    out = []
    if shutil.which("nvidia-smi"):
        for line in _out(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]).splitlines():
            parts = [p.strip() for p in line.split(",")]
            if parts and parts[0]:
                out.append({"vendor": "nvidia", "name": parts[0], "memory_gb": round(float(parts[1]) / 1024, 1) if len(parts) > 1 and parts[1].replace(".", "").isdigit() else None})
    if not out and shutil.which("rocm-smi"):
        for line in _out(["rocm-smi", "--showproductname"]).splitlines():
            m = re.search(r"Card series:\s*(.+)", line)
            if m:
                out.append({"vendor": "amd", "name": m.group(1).strip(), "memory_gb": None})
    if not out and sys.platform == "darwin" and platform.machine() == "arm64":
        out.append({"vendor": "apple", "name": "Apple silicon (MPS)", "memory_gb": None})
    return out


def _slurm() -> dict | None:
    if not shutil.which("sbatch"):
        return None
    parts = []
    for line in _out(["sinfo", "-h", "-o", "%P|%l|%G|%a|%D"]).splitlines():
        name, lim, gres, avail, nodes = (line.split("|") + [""] * 5)[:5]
        if not name:
            continue
        parts.append({"name": name.rstrip("*"), "default": name.endswith("*"), "time_limit": lim, "gres": gres,
                      "up": avail == "up", "nodes": nodes})
    acct = ""
    if shutil.which("sacctmgr"):
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        acct = _out(["sacctmgr", "-n", "-P", "show", "assoc", f"user={user}", "format=account"]).strip().splitlines()
        acct = sorted(set(a for a in acct if a))
    return {"partitions": parts, "accounts": acct or []}


def probe(hub: Path) -> dict:
    sched = {k: bool(shutil.which(c)) for k, c in (("slurm", "sbatch"), ("pbs", "qsub"), ("lsf", "bsub"))}
    slurm = _slurm()
    try:
        du = shutil.disk_usage(hub)
        disk = {"free_gb": round(du.free / 1024 ** 3, 1), "total_gb": round(du.total / 1024 ** 3, 1)}
    except OSError:
        disk = None
    gpus = _gpus()
    facts = {
        "hostname": platform.node(), "os": platform.system(), "release": platform.release(), "arch": platform.machine(),
        "python": platform.python_version(), "cpus": os.cpu_count(), "memory_gb": _mem_gb(), "gpus": gpus,
        "disk": disk, "schedulers": sched, "slurm": slurm,
        "modules": bool(os.environ.get("MODULESHOME") or os.environ.get("LMOD_CMD")),
        "tools": {t: bool(shutil.which(t)) for t in ("uv", "git", "latexmk", "docker", "apptainer", "singularity")},
        "login_node_hint": bool(slurm) and not os.environ.get("SLURM_JOB_ID"),
    }
    # what compute.scheduler should probably say here
    sug: dict = {"kind": "local"}
    if slurm:
        default = next((p for p in slurm["partitions"] if p["default"]), (slurm["partitions"] or [None])[0])
        gpu_part = next((p for p in slurm["partitions"] if "gpu" in (p["gres"] or "")), None)
        part = gpu_part or default
        sug = {"kind": "slurm", "stages": ["PILOT", "FULL"],
               "slurm": {"partition": part["name"] if part else None,
                         "gpus_per_run": 1 if part and "gpu" in (part.get("gres") or "") else 0,
                         "account": (slurm["accounts"] or [None])[0] if len(slurm["accounts"]) == 1 else None}}
    elif sched["pbs"] or sched["lsf"]:
        sug = {"kind": "custom", "note": "PBS/LSF detected — describe submit/state/cancel in compute.scheduler.custom"}
    facts["suggested_scheduler"] = sug
    return facts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", default=str(HUB))
    a = ap.parse_args()
    print(json.dumps(probe(Path(a.hub)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
