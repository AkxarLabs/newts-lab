"""Run lab procedures as headless agent sessions — the executor's command line.

    uv run --with pyyaml python tools/executor_cli.py enqueue --skill propose --target my-idea [--args "..."]
                                  [--backend claude|codex|opencode] [--model M] [--effort E]
                                  [--max-minutes N] [--chain off|next|loop] [--repeat-minutes N] [--wait]
    uv run --with pyyaml python tools/executor_cli.py enqueue --prompt-file brief.md --target my-project [--wait]
                                  (a free-form instruction instead of a procedure; {{slug}} is substituted)
    uv run --with pyyaml python tools/executor_cli.py serve [--interval 2]     # the scheduler loop (no dashboard needed)
    uv run --with pyyaml python tools/executor_cli.py tick                     # one scheduling pass
    uv run --with pyyaml python tools/executor_cli.py list [--all]
    uv run --with pyyaml python tools/executor_cli.py show <run_id>
    uv run --with pyyaml python tools/executor_cli.py answer <run_id> --pick "<question>=<label>" ... | --text "..."
    uv run --with pyyaml python tools/executor_cli.py reply  <run_id> --text "..."
    uv run --with pyyaml python tools/executor_cli.py resume|cancel|stop <run_id>
    uv run --with pyyaml python tools/executor_cli.py stop --target <slug> | --campaign <name>   # every live run
    uv run --with pyyaml python tools/executor_cli.py reconcile | attention | health | skills

Every run is `/skill args` from the allowlist (`skills`) or the PI's free-form instruction, executed by the unmodified agent CLI as the
logged-in user, in a detached supervisor that survives the caller. Gates and hard rules bind exactly
as in a session; Gate 3 is never delegated. Programmatic launching is PI-owned and OFF by default
(agents.programmatic.enabled). Exit: 0 ok · 1 refused/error · 2 run ended non-cleanly (--wait).
"""

from __future__ import annotations

import argparse
import os
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import executor  # noqa: E402
from executor import Lab, RunSpec, SpecError  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_enqueue(lab: Lab, a) -> int:
    prompt = None
    if a.prompt_file:
        prompt = Path(a.prompt_file).read_text(encoding="utf-8").replace("{{slug}}", a.target)
    elif not a.skill:
        print("[executor] REFUSED: give --skill or --prompt-file")
        return 1
    spec = RunSpec(skill=a.skill or "", prompt=prompt, target=a.target, args=a.args or "", backend=a.backend, model=a.model,
                   effort=a.effort, max_minutes=a.max_minutes, max_turns=a.max_turns, chain=a.chain,
                   repeat_minutes=a.repeat_minutes, max_repeats=a.max_repeats, created_by="cli")
    try:
        m = executor.enqueue(lab, spec)
    except SpecError as e:
        print(f"[executor] REFUSED: {e}")
        return 1
    print(f"[executor] queued {m['run_id']} (#{m['position']}) — {m.get('command') or m['prompt_summary']}")
    if not a.wait:
        print("[executor] a scheduler starts it: the dashboard, `executor_cli.py serve`, or `tick`")
        return 0
    return _wait(lab, m["run_id"], a.interval)


def _wait(lab: Lab, run_id: str, interval: float) -> int:
    last = None
    while True:
        executor.tick(lab)
        hit = executor.find_run(lab, run_id)
        m = hit[3] if hit else {}
        st = m.get("status")
        if st != last:
            print(f"[executor] {run_id}: {st}" + (f" — {m.get('reason')}" if m.get("reason") else ""), flush=True)
            last = st
        if st == "waiting_input":
            qs = ((m.get("pending_question") or {}).get("input") or {}).get("questions") or []
            for q in qs:
                opts = ", ".join(o.get("label", "") for o in q.get("options") or [])
                print(f"  ? {q.get('question')}  [{opts}]")
            print(f"  answer: executor_cli.py answer {run_id} --pick \"<question>=<label>\"")
            return 0
        if st in executor.TERMINAL:
            if m.get("last_message"):
                print(f"[executor] last message: {str(m['last_message'])[:600]}")
            return 0 if st == "completed" else 2
        time.sleep(interval)


def cmd_list(lab: Lab, a) -> int:
    runs = executor.list_runs(lab, None if a.all else 30)
    if not runs:
        print("no runs")
        return 0
    for m in runs:
        q = " ?" if m.get("status") == "waiting_input" else ""
        print(f"- {m.get('run_id') or m.get('agent_id')}  [{m.get('backend')}] {m.get('status')}{q}  "
              f"{m.get('command') or m.get('prompt_summary', '')[:60]}  started={m.get('started')}")
    return 0


def cmd_show(lab: Lab, a) -> int:
    hit = executor.find_run(lab, a.run_id)
    if not hit:
        print(f"no run {a.run_id}")
        return 1
    _p(hit[3])
    return 0


def _parse_picks(picks: list[str]) -> dict:
    out: dict = {}
    for p in picks or []:
        q, _, lab_ = p.rpartition("=")
        if not q:
            raise SpecError(f"--pick needs '<question>=<label>', got {p!r}")
        if q in out:
            prev = out[q] if isinstance(out[q], list) else [out[q]]
            out[q] = prev + [lab_]
        else:
            out[q] = lab_
    return out


def cmd_answer(lab: Lab, a) -> int:
    try:
        m = executor.answer(lab, a.run_id, _parse_picks(a.pick) or None, a.text, by="cli")
    except SpecError as e:
        print(f"[executor] REFUSED: {e}")
        return 1
    print(f"[executor] answered — {m['run_id']} queued to resume")
    return 0


def _simple(fn_name: str):
    def run(lab: Lab, a) -> int:
        try:
            if fn_name == "reply":
                m = executor.reply(lab, a.run_id, a.text, by="cli")
            else:
                m = getattr(executor, fn_name)(lab, a.run_id, by="cli")
        except SpecError as e:
            print(f"[executor] REFUSED: {e}")
            return 1
        print(f"[executor] {fn_name}: {m.get('run_id')} -> {m.get('status')}")
        return 0
    return run


def cmd_stop(lab: Lab, a) -> int:
    if a.run_id:
        return _simple("stop")(lab, a)
    if not (a.target or a.campaign):
        print("[executor] REFUSED: give a run id, --target or --campaign")
        return 1
    hits = [m for m in executor.list_runs(lab) if m.get("status") not in executor.TERMINAL
            and (not a.target or m.get("target") == a.target) and (not a.campaign or m.get("campaign") == a.campaign)]
    for m in hits:
        try:
            executor.stop(lab, m["run_id"], by="cli")
            print(f"[executor] stop: {m['run_id']}")
        except SpecError as e:
            print(f"[executor] {m['run_id']}: {e}")
    if not hits:
        print("[executor] nothing live to stop")
    return 0


def cmd_tick(lab: Lab, a) -> int:
    _p(executor.tick(lab, wait=5))
    return 0


def cmd_serve(lab: Lab, a) -> int:
    if a.until_idle:
        ls = executor.scheduler.lease(lab)
        age = ls.get("age")
        # a lease written by whoever spawned us is ours to take over; any other fresh one means a live ticker
        if age is not None and age < 10 and not str(ls.get("by") or "").startswith("spawned"):
            print("[executor] another scheduler is ticking — nothing to do", flush=True)
            return 0
        os.environ["NEWTS_TICKER"] = "serve --until-idle"
    print(f"[executor] scheduler running for {lab.hub} (every {a.interval}s"
          + ("; exits when idle" if a.until_idle else "; Ctrl-C to stop") + " — runs already started keep going in "
          "their own supervisors)", flush=True)
    stop = threading.Event()
    try:
        executor.tick_loop(lambda: Lab(lab.hub), stop, interval=a.interval, until_idle=a.until_idle,
                           idle_seconds=a.idle_seconds)
    except KeyboardInterrupt:
        stop.set()
        print("\n[executor] scheduler stopped")
    return 0


def cmd_supervise(lab: Lab, a) -> int:
    return executor.run_supervisor(lab, a.run, a.target)


def cmd_reconcile(lab: Lab, a) -> int:
    print(f"[executor] reconciled {executor.reconcile(lab)} orphaned run(s)")
    return 0


def cmd_attention(lab: Lab, a) -> int:
    items = executor.attention.collect(lab, brake_reason=executor.brake(lab, executor.list_runs(lab)))
    if not items:
        print("nothing needs you")
    for it in items:
        print(f"- [{it['sev']}] {it['kind']}: {it['title']}" + (f" ({it['run_id']})" if it.get("run_id") else ""))
        if it.get("body"):
            print(f"    {str(it['body'])[:200]}")
    return 0


def cmd_health(lab: Lab, a) -> int:
    _p(executor.health(lab))
    return 0


def cmd_skills(lab: Lab, a) -> int:
    for name, cfg in executor.SKILL_REGISTRY.items():
        print(f"- /{name:<15} {cfg['level']:<8} {cfg['mode']:<12} {cfg['args'] or '-':<11} {cfg['hint']}")
    print(f"never headless: {', '.join('/' + s for s in sorted(executor.NEVER))}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="the Newts' Lab executor (headless procedure runs)")
    ap.add_argument("--hub", default=None, help="hub root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enqueue", help="queue a procedure run")
    e.add_argument("--skill", default=None)
    e.add_argument("--prompt-file", default=None, dest="prompt_file", help="a free-form instruction instead of --skill")
    e.add_argument("--target", default="hub", help="'hub' or an idea/project slug")
    e.add_argument("--args", default="")
    e.add_argument("--backend", default=None, choices=("claude", "codex", "opencode", "_dummy"))
    e.add_argument("--model", default=None)
    e.add_argument("--effort", default=None)
    e.add_argument("--max-minutes", type=float, default=None, dest="max_minutes")
    e.add_argument("--max-turns", type=int, default=None, dest="max_turns")
    e.add_argument("--chain", default="off", choices=("off", "next", "loop"))
    e.add_argument("--repeat-minutes", type=float, default=None, dest="repeat_minutes")
    e.add_argument("--max-repeats", type=int, default=None, dest="max_repeats")
    e.add_argument("--wait", action="store_true", help="tick until it pauses or ends")
    e.add_argument("--interval", type=float, default=2.0)
    e.set_defaults(fn=cmd_enqueue)

    s = sub.add_parser("serve", help="run the scheduler loop")
    s.add_argument("--interval", type=float, default=2.0)
    s.add_argument("--until-idle", action="store_true", dest="until_idle",
                   help="exit once nothing is queued, running or being kept (started by a supervisor when "
                        "the dashboard is closed)")
    s.add_argument("--idle-seconds", type=float, default=120.0, dest="idle_seconds", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_serve)

    sub.add_parser("tick").set_defaults(fn=cmd_tick)
    lp = sub.add_parser("list")
    lp.add_argument("--all", action="store_true")
    lp.set_defaults(fn=cmd_list)
    sp = sub.add_parser("show")
    sp.add_argument("run_id")
    sp.set_defaults(fn=cmd_show)

    an = sub.add_parser("answer")
    an.add_argument("run_id")
    an.add_argument("--pick", action="append", help="'<question text>=<option label>' (repeatable)")
    an.add_argument("--text", default=None, help="a free-form reply instead of picking options")
    an.set_defaults(fn=cmd_answer)
    rp = sub.add_parser("reply")
    rp.add_argument("run_id")
    rp.add_argument("--text", required=True)
    rp.set_defaults(fn=_simple("reply"))
    for name in ("resume", "cancel"):
        q = sub.add_parser(name)
        q.add_argument("run_id")
        q.set_defaults(fn=_simple(name))
    st = sub.add_parser("stop", help="stop a run, or every live run of a target / campaign")
    st.add_argument("run_id", nargs="?")
    st.add_argument("--target", default=None)
    st.add_argument("--campaign", default=None)
    st.set_defaults(fn=cmd_stop)

    sv = sub.add_parser("supervise", help=argparse.SUPPRESS)
    sv.add_argument("--run", required=True)
    sv.add_argument("--target", required=True)
    sv.set_defaults(fn=cmd_supervise)

    sub.add_parser("reconcile").set_defaults(fn=cmd_reconcile)
    sub.add_parser("attention").set_defaults(fn=cmd_attention)
    sub.add_parser("health").set_defaults(fn=cmd_health)
    sub.add_parser("skills").set_defaults(fn=cmd_skills)

    a = ap.parse_args(argv)
    return a.fn(Lab(a.hub), a)


if __name__ == "__main__":
    sys.exit(main())
