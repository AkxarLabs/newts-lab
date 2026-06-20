"""Obtain/record an external target score — the OUTWARD action gate for target-driven projects.

    # record a score you (or the loop) read from the scorer/leaderboard for a run:
    uv run --with pyyaml python scripts/report_score.py --run-id <id> --score 0.873 --note "exp-007 5-fold"
    # obtain a score via the task's configured command (target.scoring.read_back: command):
    uv run --with pyyaml python scripts/report_score.py --run-id <id> --via command --note "exp-007"
    # backfill a score for an already-counted read (does NOT consume a daily slot):
    uv run --with pyyaml python scripts/report_score.py --run-id <id> --score 0.881 --record-only

NOTHING here is specific to any host or tool. When the score is EXTERNAL (sending output out to
be scored), this runs under the PI-signed `target.score_envelope` in control.yaml (the Gate-2
analogue) and is enforced HERE: no signed envelope, a passed deadline, or a per-day / total cap
reached blocks it. `--via command` runs whatever `target.scoring.score_command` the agent filled
for THIS task (a CLI, an HTTP call, a grader). Every read is appended to `runs/scores.jsonl`
(append-only) and mirrored to `runs/<run_id>/score.json`. Choosing the FINAL output for the
hidden/final split is a Gate-3 action done by the PI in a session — never by this script.

Exit codes:  0 = recorded · 1 = BLOCKED (not authorized / invalid) · 2 = recorded with warnings.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "runs" / "scores.jsonl"
LOCK = ROOT / "runs" / "scores.jsonl.lock"
SCORE_TIMEOUT_S = 600

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling lab_bus
try:
    import lab_bus  # optional dashboard bus
except Exception:  # noqa: BLE001
    lab_bus = None


def _target() -> dict:
    try:
        doc = yaml.safe_load((ROOT / "control.yaml").read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc.get("target") or {}


def _ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append(record: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@contextlib.contextmanager
def _read_lock():
    """Serialize authorized EXTERNAL reads so the PI-signed cap can't be raced (the cap-check and the
    append must be atomic, and two leaderboard submissions must never run in parallel). Held across the
    whole check -> submit -> record section. A crashed holder (lockfile >20 min old) is reclaimed."""
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + SCORE_TIMEOUT_S + 60
    fd = None
    while fd is None:
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            broke = False
            with contextlib.suppress(OSError):
                if time.time() - LOCK.stat().st_mtime > 1200:
                    LOCK.unlink(); broke = True
            if broke:
                continue
            if time.time() > deadline:
                raise TimeoutError("another external read is in progress")
            time.sleep(0.1)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            LOCK.unlink()


def _kill_tree(proc) -> None:
    """Kill a score_command and its children so a hung external submission can't outlive the timeout
    (a bare proc.kill() leaves the grandchild — kaggle/curl/grader — running on Windows)."""
    if proc is None or proc.poll() is not None:
        return
    with contextlib.suppress(Exception):
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)


def _deadline_passed(deadline) -> bool:
    """True only if `deadline` parses as a date strictly before today. Tolerates non-zero-
    padded ISO (`2026-6-9`); empty / truly unparseable input never blocks here (a naive
    string-slice compare got non-padded dates wrong)."""
    d = str(deadline or "").strip()
    if not d or d.lower() in ("null", "none"):
        return False
    datepart = re.split(r"[T ]", d, 1)[0]   # drop any time component BEFORE parsing the date
    try:
        dl = date.fromisoformat(datepart)
    except ValueError:
        try:
            y, m, dd = (int(x) for x in datepart.replace("/", "-").split("-")[:3])
            dl = date(y, m, dd)
        except (ValueError, IndexError):
            return False
    return dl < date.today()


def _parse_score(text: str) -> float | None:
    """Pull the last numeric token out of a score command's stdout (e.g. a grader that
    prints `0.873`). Best-effort: returns None if nothing numeric is present."""
    nums = re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text or "")
    if not nums:
        return None
    try:
        return float(nums[-1])
    except ValueError:
        return None


def _validate_output(run_id: str, output: dict) -> int:
    """If there's an output contract, run check_output.py on this run's file. 0/2 ok, 1 invalid."""
    if not output or not output.get("path"):
        return 0  # local-metric-only target: nothing to validate
    out_file = ROOT / "runs" / run_id / output["path"]
    if not out_file.exists():
        print(f"[report_score] INVALID: no output at runs/{run_id}/{output['path']}")
        return 1
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_output.py"), str(out_file)],
        capture_output=True, text=True, cwd=ROOT,
    )
    if proc.stdout.strip():
        print(proc.stdout.rstrip())
    return proc.returncode


def _run_score_command(tmpl: str, run_id: str, note: str, name: str,
                       output: dict) -> tuple[bool, str, float | None]:
    """Run the task's own score command (PI/agent-authored, from control.yaml — trusted).
    Generic: any CLI/HTTP/grader. Placeholders {file} {run_id} {note} {name} are substituted
    LITERALLY (not str.format, so a template containing JSON/awk/${} braces doesn't crash).
    Best-effort; returns (ok, output_tail, parsed_score)."""
    out_path = ""
    if output and output.get("path"):
        out_path = str(ROOT / "runs" / run_id / output["path"])
    cmd = (tmpl.replace("{file}", out_path).replace("{run_id}", run_id)
               .replace("{note}", note or run_id).replace("{name}", name or ""))
    # Own the process group so a timeout reaps the whole tree (the shell AND the grandchild
    # submitter), not just cmd.exe — otherwise an in-flight external submission is orphaned.
    grp = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=ROOT, **grp)
    except OSError as e:
        return False, f"score_command failed to launch: {e}", None
    try:
        out_s, err_s = proc.communicate(timeout=SCORE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        return False, f"score_command timed out ({SCORE_TIMEOUT_S}s) — killed", None
    out = (out_s or err_s or "").strip()
    return (proc.returncode == 0), out[:500], _parse_score(out_s or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--score", type=float, default=None)
    ap.add_argument("--final-score", type=float, default=None, help="hidden/final-split score, when known")
    ap.add_argument("--note", default="")
    ap.add_argument("--via", choices=("manual", "command"), default="manual")
    ap.add_argument("--record-only", action="store_true",
                    help="log a score for an already-counted read; does NOT consume a daily slot")
    args = ap.parse_args()

    target = _target()
    if not target or not target.get("active"):
        print("[report_score] BLOCKED: no active `target` block in control.yaml")
        return 1

    scoring = target.get("scoring") or {}
    output = target.get("output") or {}
    external = bool(scoring.get("external"))
    today = time.strftime("%Y-%m-%d")
    warnings: list[str] = []

    # --- score backfill: append-only, no authorization/cap consumption -----------------
    if args.record_only:
        if args.score is None and args.final_score is None:
            print("[report_score] BLOCKED: --record-only needs --score and/or --final-score")
            return 1
        _record(args, status="score")
        print(f"[report_score] recorded score for {args.run_id} (no slot consumed)")
        return 0

    # --- the authorized-read flow. An EXTERNAL (outward) read runs under an exclusive lock so the
    #     PI-signed cap can't be raced (check + append are atomic) and two submissions can't overlap. ---
    status = "read"
    with contextlib.ExitStack() as stack:
        if external:
            try:
                stack.enter_context(_read_lock())
            except TimeoutError:
                print("[report_score] BLOCKED: another external read is in progress — try again shortly")
                return 1
            env = target.get("score_envelope") or {}
            if not env.get("pi_signed"):
                print("[report_score] BLOCKED: scoring is external but no PI-signed target.score_envelope — "
                      "the PI must authorize external reads (/configure or the /compete interview)")
                return 1
            if _deadline_passed(target.get("deadline")):
                print(f"[report_score] BLOCKED: deadline {target.get('deadline')} has passed — scoring window closed")
                return 1
            reads = [r for r in _ledger_rows() if r.get("status") == "read"]   # re-read INSIDE the lock
            per_day_max = int(env.get("per_day_max") or 0)
            total_max = int(env.get("total_max") or 0)
            today_n = sum(1 for r in reads if str(r.get("ts", ""))[:10] == today)
            # total_max is THE authorization cap: 0 means "none authorized" (matching the
            # control.yaml doc + guard.py's all-zero-envelope rule), NOT "unlimited".
            if total_max <= 0:
                print("[report_score] BLOCKED: score_envelope.total_max is 0 — no external reads "
                      "authorized; the PI must set a cap > 0")
                return 1
            if len(reads) >= total_max:
                print(f"[report_score] BLOCKED: total external-read cap reached ({len(reads)}/{total_max})")
                return 1
            # per_day_max is an OPTIONAL daily rate limit (0 = no daily sub-limit, total still binds).
            if per_day_max > 0 and today_n >= per_day_max:
                print(f"[report_score] BLOCKED: daily external-read cap reached ({today_n}/{per_day_max} today)")
                return 1

        # validate the output before spending an external read
        rc = _validate_output(args.run_id, output)
        if rc == 1:
            print("[report_score] BLOCKED: output failed check_output.py — fix it before an external read")
            return 1
        if rc == 2:
            warnings.append("check_output reported warnings (see above)")

        # obtain the score via the task's configured command, or record a manual read
        read_ok = True
        if args.via == "command":
            tmpl = scoring.get("score_command") or ""
            if not tmpl:
                print("[report_score] BLOCKED: --via command but target.scoring.score_command is empty — "
                      "fill it in control.yaml (any tool; placeholders {file}{run_id}{note}{name})")
                return 1
            read_ok, msg, parsed = _run_score_command(tmpl, args.run_id, args.note, target.get("name") or "", output)
            print(f"[report_score] score_command: {msg}")
            if parsed is not None and args.score is None:
                args.score = parsed
                print(f"[report_score] parsed score from command output: {parsed}")

        # A failed/scoreless EXTERNAL command read is logged as 'read_failed', which the cap filter
        # above excludes — so a transient failure (auth/network) does NOT burn the PI-signed budget.
        if external and args.via == "command" and (not read_ok or args.score is None):
            status = "read_failed"
            warnings.append("score_command produced no usable score — logged as a failed attempt "
                            "(no cap slot consumed); verify and retry")
        _record(args, status=status, warnings=warnings)
        if lab_bus:
            lab_bus.emit("score_read", detail=target.get("name") or args.run_id,
                         data={"run_id": args.run_id, "score": args.score, "external": external, "status": status})

    if status == "read_failed":
        print(f"[report_score] external read FAILED for {args.run_id} — no cap slot consumed; retry.")
        return 2
    where = "external read recorded" if external else "score recorded (internal)"
    print(f"[report_score] {where} for {args.run_id} (score={args.score}). "
          "Final-output selection is a PI Gate-3 action.")
    return 2 if warnings else 0


def _record(args, *, status: str, warnings: list[str] | None = None) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run_id": args.run_id,
        "status": status,
        "score": args.score,
        "final_score": args.final_score,
        "note": args.note,
        "via": args.via,
    }
    if warnings:
        record["warnings"] = warnings
    _append(record)
    run_dir = ROOT / "runs" / args.run_id
    if run_dir.exists():
        sj = run_dir / "score.json"
        prev = {}
        if sj.exists():
            try:
                prev = json.loads(sj.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                prev = {}
        if args.score is not None:
            prev["score"] = args.score
        if args.final_score is not None:
            prev["final_score"] = args.final_score
        prev["last_update"] = record["ts"]
        sj.write_text(json.dumps(prev, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
