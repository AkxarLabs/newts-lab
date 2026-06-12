---
name: lab-status
description: Orient in the lab — read the registry, knowledge, and notebook; report state and recommend the next action. Run at the start of any session or when unsure what to do.
---

# Lab Status

1. Read `lab/REGISTRY.md`, the latest 1–2 entries in `lab/notebook/`, and skim `lab/knowledge/OPEN-QUESTIONS.md`.
2. For any idea in an active state (`active`, `analysis`, `writing`, `internal-review`), read its `IDEA.md` state log and — if a project exists — the tail of `projects/<slug>/EXPERIMENT_LOG.md`.
3. Run `uv run --with pyyaml python tools/check_lab.py` — fix any registry/IDEA.md drift and orphans it reports immediately; flag stale items and budget overruns to the PI.
4. Report to the user:
   - One line per non-final item: state, last activity, what unblocks it.
   - Items waiting at a **PI gate** (call these out first — they block on the human).
   - A single recommended next action (the highest-leverage one), with the command to run it.
