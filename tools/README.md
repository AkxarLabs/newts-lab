# tools/ — the harness

The small amount of code that makes the lab's rules hold whatever an agent does, and connects the
dashboard to coding agents. Everything a lab *defines* lives elsewhere: procedures in
`.claude/skills/` (with their method helpers in each skill's own `tools/`), the workflow and the rules in
`workflow/`, mechanical checks in `checks/`, roles in `agent-roles/`, templates in `templates/`. stdlib +
pyyaml; run with uv's ephemeral env:

```bash
uv run --with pyyaml python tools/guard.py <command|check> <slug> …   # the gates, transitions, and checks/ (--list)
uv run --with pyyaml python tools/workflow.py check | brief <proc> | render-docs | propose …
uv run --with pyyaml python tools/check_lab.py                        # lab lint (registry, wiring, workflow)
uv run --with pyyaml python tools/configure.py view|set|profile …     # owner-aware config edits
uv run --with pyyaml python tools/show_config.py [<project> [exp.yaml]]  # 3-layer config with provenance
uv run --with pyyaml python tools/run_slots.py acquire|touch|release|status
uv run python tools/lab_bus.py emit|inbox|ack|escalate …             # the event bus + PI directives
uv run --with pyyaml python tools/executor_cli.py enqueue|serve|list|answer|stop …   # headless runs
uv run --with pyyaml python tools/upgrade_project.py --all [--check]  # bring older projects up to date
```

| Group | Files | What they do |
|---|---|---|
| **Signatures and gates** | `markers.py`, `signature_guard.py`, `guard.py`, `gate3.py` | recognise the PI's marks; refuse a headless run that would forge one; check a gate is recorded before the irreversible step (`guard.py` also dispatches `checks/`) |
| **The lab's definition** | `workflow.py`, `labfiles.py` | read `workflow/stages.yaml`, `workflow/rules.yaml` and the skills; the brief; the PI's instruction layers; the generated docs; the lab's files read one way |
| **Observability** | `lab_bus.py`, `trace_hook.py` | the append-only event bus and directive inbox; the per-agent action tracer (both ship into every project too) |
| **Coordination** | `run_slots.py`, `hub_writeback.py`, `process_writebacks.py` | compute slots across projects; the project→hub write-back boundary |
| **Agents** | `executor/`, `executor_cli.py`, `lab_profile.py`, `role_sync.py` | run procedures as live or headless sessions of claude / codex / opencode (`executor/` knows nothing about this lab; `lab_profile.py` is everything it needs to); render the roles for each CLI |
| **Setup and config** | `spawn_project.py`, `new_lab.py`, `configure.py`, `profiles.py`, `show_config.py`, `check_lab.py`, `upgrade_project.py`, `system_probe.py`, `terminal.py` | stamp projects and labs; owner-aware config; lint; what this machine offers; a terminal for a CLI's sign-in |

Exit codes for the guard and checks: **0 = OK · 1 = BLOCKED · 2 = WARN**. A guard never grants a gate; it
only confirms one is recorded. See `docs/tools.md` for each tool and `docs/extending.md` for adding to the
lab.
