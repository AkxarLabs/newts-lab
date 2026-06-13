"""The lab event bus — append-only signals out of every step, for the dashboard.

    python tools/lab_bus.py emit <kind> [--idea X] [--run-id R] [--stage S]
                                       [--status ST] [--detail "..."] [--data k=v ...]
    python tools/lab_bus.py inbox                      # unresolved PI directives
    python tools/lab_bus.py ack <id> seen|done|blocked [--note "..."] [--evidence PATH]

One JSONL file per source, gitignored runtime state (like the slot ledger). This same
file is shipped into every spawned project as scripts/lab_bus.py and auto-detects whether
it is running in the hub or in a project:

  - HUB    (tools/lab_bus.py):     bus at  <hub>/lab/.bus/     source = "hub"
  - PROJECT(scripts/lab_bus.py):   bus at  <project>/.bus/     source = <project dir name>

Emitting is always safe and cheap and never required: it is wrapped so a bus failure can
never break the lab. The dashboard (optional) tails these files; with no dashboard running
they are simply a local audit trail.

Event line:  {ts, source, kind, idea, run_id, stage, status, detail, data{}}
Directive line (written by the dashboard to directives.jsonl): a free-text note
{id, ts, from, text}, a STRUCTURED command {id, ts, from, kind:"command", action, args, text}
(the agent executes the action in-protocol — start_loop/set_mode/park/kill/request_run/…),
or a withdrawal {kind:"withdraw", ref:<id>, ts}. Acks are events of kind directive_seen /
directive_done / directive_blocked carrying data.ref = the directive id. A command that would
touch a frozen/PI-owned setting is acked `blocked` — directives/commands are never gate approval.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
IS_HUB = (ROOT / "lab" / "REGISTRY.md").exists()
BUS = (ROOT / "lab" / ".bus") if IS_HUB else (ROOT / ".bus")
SOURCE = "hub" if IS_HUB else ROOT.name

KINDS = {
    "session_start", "session_end", "state_change", "gate_waiting", "gate_resolved",
    "run_started", "run_finished", "sweep_started", "sweep_finished",
    "slot_acquired", "slot_released", "slot_denied", "slot_reclaimed",
    "cycle", "review_verdict", "paper_compiled", "kill", "writeback",
    "frontier_expand", "decision_revisit", "replan",
    "directive_seen", "directive_done", "directive_blocked", "note",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def emit(kind: str, **fields) -> None:
    """Append one event. Swallows every error — the bus must never break the lab."""
    try:
        BUS.mkdir(parents=True, exist_ok=True)
        record = {"ts": _now(), "source": SOURCE, "kind": kind}
        for k in ("idea", "run_id", "stage", "status", "detail"):
            if fields.get(k) is not None:
                record[k] = fields[k]
        if fields.get("data"):
            record["data"] = fields["data"]
        with (BUS / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 — emitting is best-effort by contract
        pass


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def unresolved_directives() -> list[dict]:
    """Directives with no terminal ack (done/blocked) and not withdrawn."""
    directives = _read_jsonl(BUS / "directives.jsonl")
    withdrawn = {d["ref"] for d in directives if d.get("kind") == "withdraw" and d.get("ref")}
    acked: dict[str, str] = {}
    for e in _read_jsonl(BUS / "events.jsonl"):
        if e.get("kind", "").startswith("directive_"):
            ref = (e.get("data") or {}).get("ref")
            if ref:
                acked[ref] = e["kind"]
    pending = []
    for d in directives:
        if d.get("kind") == "withdraw" or not d.get("id"):
            continue
        if d["id"] in withdrawn:
            continue
        last = acked.get(d["id"])
        if last in ("directive_done", "directive_blocked"):
            continue
        pending.append({**d, "_status": "seen" if last == "directive_seen" else "pending"})
    return pending


def cmd_emit(args) -> int:
    if args.kind not in KINDS:
        print(f"[bus] unknown kind '{args.kind}'. Known: {', '.join(sorted(KINDS))}", file=sys.stderr)
        return 1
    data = {}
    for item in args.data or []:
        k, _, v = item.partition("=")
        data[k.strip()] = v
    emit(args.kind, idea=args.idea, run_id=args.run_id, stage=args.stage,
         status=args.status, detail=args.detail, data=data or None)
    return 0


def cmd_inbox(args) -> int:
    pending = unresolved_directives()
    if not pending:
        print(f"no unresolved directives for {SOURCE}")
        return 0
    print(f"## Directive inbox — {SOURCE} ({len(pending)} unresolved)\n")
    for d in pending:
        label = (d.get("text", "") or "").strip()
        if d.get("kind") == "command":
            args = d.get("args") or {}
            label = f"[command: {d.get('action')}]" + (f" {args}" if args else "") + (f" — {label}" if label else "")
        print(f"- [{d['_status']}] `{d['id']}` ({d.get('ts', '?')}) — {label}")
    print("\nAct within the protocol, then ack: `lab_bus.py ack <id> done --evidence <path>`.")
    print("A `command` directive is a structured PI instruction (start_loop, set_mode, park, …);")
    print("a command that would touch a frozen/PI-owned setting is acked `blocked` — never a gate.")
    return 0


def cmd_ack(args) -> int:
    if args.state not in ("seen", "done", "blocked"):
        print("state must be seen | done | blocked", file=sys.stderr)
        return 1
    data = {"ref": args.id}
    if args.note:
        data["note"] = args.note
    if args.evidence:
        data["evidence"] = args.evidence
    emit(f"directive_{args.state}", detail=args.note, data=data)
    print(f"acked {args.id} -> {args.state}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("emit")
    p.add_argument("kind")
    p.add_argument("--idea"); p.add_argument("--run-id", dest="run_id")
    p.add_argument("--stage"); p.add_argument("--status"); p.add_argument("--detail")
    p.add_argument("--data", action="append", help="k=v (repeatable)")
    p.set_defaults(fn=cmd_emit)

    p = sub.add_parser("inbox"); p.set_defaults(fn=cmd_inbox)

    p = sub.add_parser("ack")
    p.add_argument("id"); p.add_argument("state")
    p.add_argument("--note"); p.add_argument("--evidence")
    p.set_defaults(fn=cmd_ack)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
