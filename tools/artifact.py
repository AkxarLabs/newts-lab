#!/usr/bin/env python3
"""Show the PI something: publish an artifact to the lab's dashboard (Artifacts, and a pinned sheet in the world).

    python tools/artifact.py publish --title "Pilot results" --file analysis/pilot.md [--study <slug>] [--note "…"]
    python tools/artifact.py publish --title "Which eval set?" --question "Freeze A or B?" --choices "A — held-out;B — synthetic"
    python tools/artifact.py publish --title "Loss curves" --file figs/loss.png --question "Good to scale up?" --choices "Yes;Not yet"
    python tools/artifact.py replies [--id <artifact>] [--run <run_id>]     # what the PI answered (JSON lines)
    python tools/artifact.py list [--study <slug>]

An artifact is something an agent made FOR the PI to look at — a plan, a report, a figure, a table, an HTML page —
optionally with a question and choices. The kind follows the file: .md (rendered), .html (shown in a sandbox),
.png/.jpg/.webp/.gif/.svg (an image), .pdf, .csv/.tsv (a table), .txt/.log/.json (text). With no file, a question
alone is a "choice". The PI's reply reaches the run that published it (as its next message), and is readable
here with `replies`. Publishing is how you ask for a look; it is never a gate signature and never approval of a
FULL run.

Where: <hub>/lab/.bus/artifacts/<id>/ — artifact.json and a copy of the file. The hub is $NEWTS_HUB (set for
every run the dashboard launches), else this repository when it is the hub, else a project's control.yaml
`hub_path`. The run, its procedure and its study come from $NEWTS_RUN_ID / $NEWTS_RUN_SKILL / $NEWTS_RUN_SUBJECT.
Only the dashboard writes reply.json and seen (the signature guard refuses a run that tries).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
KINDS = {".md": "md", ".markdown": "md", ".html": "html", ".htm": "html", ".png": "image", ".jpg": "image",
         ".jpeg": "image", ".webp": "image", ".gif": "image", ".svg": "image", ".pdf": "pdf", ".csv": "table",
         ".tsv": "table", ".txt": "text", ".log": "text", ".json": "text"}
MAX_BYTES = 8 * 1024 * 1024
MAX_TITLE, MAX_NOTE, MAX_CHOICES = 140, 2000, 8


class ArtifactError(Exception):
    pass


def hub() -> Path:
    env = os.environ.get("NEWTS_HUB")
    if env and (Path(env) / "lab").is_dir():
        return Path(env)
    if (ROOT / "lab" / "REGISTRY.md").exists():
        return ROOT
    for d in (Path.cwd(), *Path.cwd().parents):            # a project repo: control.yaml names its hub
        ctl = d / "control.yaml"
        if ctl.is_file():
            m = re.search(r'^hub_path:\s*"?([^"\n#]+?)"?\s*(?:#|$)', ctl.read_text(encoding="utf-8", errors="replace"), re.M)
            if m and (Path(m.group(1).strip()) / "lab").is_dir():
                return Path(m.group(1).strip())
    raise ArtifactError("can't find the lab: set NEWTS_HUB to the hub repository")


def root(h: Path | None = None) -> Path:
    return (h or hub()) / "lab" / ".bus" / "artifacts"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _emit(h: Path, kind: str, detail: str, data: dict) -> None:
    try:    # the lab's event bus, best effort — the dashboard reads the artifact folder either way
        bus = h / "lab" / ".bus"
        rec = {"ts": _now(), "source": "hub", "kind": kind, "detail": detail, "data": data}
        if data.get("run_id"):
            rec["run_id"] = data["run_id"]
        if data.get("study"):
            rec["idea"] = data["study"]
        with (bus / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def publish(title: str, file: str | None = None, *, kind: str | None = None, study: str | None = None,
            note: str | None = None, question: str | None = None, choices: list[str] | None = None,
            h: Path | None = None) -> dict:
    h = h or hub()
    title = " ".join((title or "").split())[:MAX_TITLE]
    if not title:
        raise ArtifactError("give it a title")
    choices = [c.strip()[:200] for c in (choices or []) if c and c.strip()][:MAX_CHOICES]
    question = (question or "").strip()[:MAX_NOTE] or None
    if choices and not question:
        question = title
    src = Path(file) if file else None
    if src is not None:
        if not src.is_file():
            raise ArtifactError(f"no file {file}")
        if src.stat().st_size > MAX_BYTES:
            raise ArtifactError(f"{file} is over {MAX_BYTES // (1024 * 1024)} MB — publish a smaller summary")
        kind = kind or KINDS.get(src.suffix.lower())
        if not kind:
            raise ArtifactError(f"can't show a {src.suffix or 'bare'} file — use .md, .html, an image, .pdf, .csv or .txt")
    elif not question:
        raise ArtifactError("give a --file to show, or a --question to ask")
    else:
        kind = "choice"
    study = study or os.environ.get("NEWTS_RUN_SUBJECT") or None
    if study and not re.match(r"^[A-Za-z0-9][\w.-]{0,80}$", study):
        raise ArtifactError(f"bad study slug {study!r}")
    aid = time.strftime("a-%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    d = root(h) / aid
    d.mkdir(parents=True, exist_ok=False)
    name = None
    if src is not None:
        name = "content" + src.suffix.lower()
        shutil.copyfile(src, d / name)
    m = {"id": aid, "title": title, "kind": kind, "file": name, "source_path": str(src) if src else None,
         "size": (d / name).stat().st_size if name else 0, "created": _now(), "study": study,
         "run_id": os.environ.get("NEWTS_RUN_ID") or None, "skill": os.environ.get("NEWTS_RUN_SKILL") or None,
         "note": (note or "").strip()[:MAX_NOTE] or None, "question": question, "choices": choices}
    (d / "artifact.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    _emit(h, "artifact", f"published “{title}”" + (" — a question for the PI" if question else ""),
          {"id": aid, "kind": kind, "run_id": m["run_id"], "study": study})
    return m


def load(aid: str, h: Path | None = None) -> dict | None:
    if not re.match(r"^a-\d{8}-\d{6}-[0-9a-f]{4}$", aid or ""):
        return None
    d = root(h) / aid
    try:
        m = json.loads((d / "artifact.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        m["reply"] = json.loads((d / "reply.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m["reply"] = None
    m["seen"] = (d / "seen").exists()
    return m


def all_artifacts(h: Path | None = None, limit: int = 300) -> list[dict]:
    r = root(h)
    ids = sorted((p.name for p in r.iterdir() if p.is_dir()), reverse=True) if r.is_dir() else []
    return [m for m in (load(i, h) for i in ids[:limit]) if m]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("--title", required=True, help="what the PI sees in the list — make it self-explanatory (≤ 140 chars)")
    p.add_argument("--file", help=".md (rendered), .html (sandboxed), an image, .pdf, .csv/.tsv (a table) or .txt")
    p.add_argument("--kind", choices=sorted(set(KINDS.values())))
    p.add_argument("--study", help="the study it is about (default: this run's subject)")
    p.add_argument("--note", help="one line shown above it: why you are showing this")
    p.add_argument("--question", help="a decision you need, as a full sentence — say what you will do with each answer")
    p.add_argument("--choices", help="mutually exclusive options separated by ';' — include a \"not yet\" option")
    r = sub.add_parser("replies")
    r.add_argument("--id")
    r.add_argument("--run")
    ls = sub.add_parser("list")
    ls.add_argument("--study")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "publish":
            m = publish(a.title, a.file, kind=a.kind, study=a.study, note=a.note, question=a.question,
                        choices=(a.choices or "").split(";") if a.choices else None)
            print(f"[artifact] published {m['id']} ({m['kind']}) — the PI sees it in the dashboard"
                  + ("; their answer comes back to this run, or read it with `artifact.py replies`" if m["question"] else ""))
            return 0
        rows = all_artifacts()
        if a.cmd == "replies":
            run = a.run or (None if a.id else os.environ.get("NEWTS_RUN_ID"))
            for m in rows:
                if m.get("reply") and (not a.id or m["id"] == a.id) and (not run or m.get("run_id") == run):
                    print(json.dumps({"id": m["id"], "title": m["title"], "reply": m["reply"]}))
            return 0
        for m in rows:
            if not a.study or m.get("study") == a.study:
                state = "answered" if m.get("reply") else "asks" if m.get("question") else "seen" if m.get("seen") else "new"
                print(f"{m['id']}  {m['kind']:<6} {state:<8} {m.get('study') or '-':<16} {m['title']}")
        return 0
    except ArtifactError as e:
        print(f"[artifact] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
