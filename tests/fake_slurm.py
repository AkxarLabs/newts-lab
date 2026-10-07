"""A stand-in for SLURM's sbatch / squeue / sacct / scancel, for hermetic scheduler tests (POSIX).

The test puts tiny wrapper scripts named sbatch, squeue, sacct, scancel on PATH that call this file with
the command name. Jobs are real background processes: `sbatch --parsable job.sh` runs the script under
bash (after FAKE_SLURM_PENDING seconds in PENDING), with SLURM_JOB_ID set and stdout to the #SBATCH
--output file; state lives in $FAKE_SLURM_DIR. FAKE_SLURM_KILL_AFTER=<s> kills the job mid-run (a node
failure). Every call is logged to $FAKE_SLURM_DIR/calls.jsonl.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

D = Path(os.environ.get("FAKE_SLURM_DIR") or "/tmp/fake-slurm")


def _log(cmd, args):
    D.mkdir(parents=True, exist_ok=True)
    with (D / "calls.jsonl").open("a") as f:
        f.write(json.dumps({"cmd": cmd, "args": args}) + "\n")


def _job(jid):
    try:
        return json.loads((D / f"{jid}.json").read_text())
    except (OSError, ValueError):
        return None


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sbatch(args):
    script = Path(args[-1])
    text = script.read_text()
    m = re.search(r"#SBATCH --output=(\S+)", text)
    D.mkdir(parents=True, exist_ok=True)
    n = len(list(D.glob("*.json"))) + 1001
    jid = str(n)
    out = (m.group(1) if m else f"slurm-{jid}.out").replace("%j", jid)
    pending = float(os.environ.get("FAKE_SLURM_PENDING") or 0)
    kill_after = os.environ.get("FAKE_SLURM_KILL_AFTER")
    body = f"sleep {pending}; " if pending else ""
    body += f"SLURM_JOB_ID={jid} bash {script} > {out} 2>&1 & p=$!; "
    body += f"(sleep {kill_after}; kill -9 $p) & " if kill_after else ""
    body += f"wait $p; echo $? > {D}/{jid}.rc"
    p = subprocess.Popen(["bash", "-c", body], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (D / f"{jid}.json").write_text(json.dumps({"pid": p.pid, "t0": time.time(), "pending": pending, "script": str(script)}))
    print(f"{jid};fakecluster" if "--parsable" in args else f"Submitted batch job {jid}")
    return 0


def squeue(args):
    jid = args[args.index("-j") + 1]
    j = _job(jid)
    if j and _alive(j["pid"]) and not (D / f"{jid}.rc").exists():
        print("PENDING" if time.time() - j["t0"] < j["pending"] else "RUNNING")
    return 0


def sacct(args):
    jid = args[args.index("-j") + 1]
    rc = (D / f"{jid}.rc").read_text().strip() if (D / f"{jid}.rc").exists() else ""
    if (D / f"{jid}.cancelled").exists():
        print("CANCELLED 0:15")
    elif rc == "0":
        print("COMPLETED 0:0")
    else:
        print(f"NODE_FAIL {rc or '?'}:0 None")
    return 0


def scancel(args):
    jid = args[-1]
    j = _job(jid)
    (D / f"{jid}.cancelled").write_text("1")
    if j:
        try:
            os.killpg(j["pid"], signal.SIGKILL)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    cmd, rest = sys.argv[1], sys.argv[2:]
    _log(cmd, rest)
    raise SystemExit({"sbatch": sbatch, "squeue": squeue, "sacct": sacct, "scancel": scancel}[cmd](rest))
