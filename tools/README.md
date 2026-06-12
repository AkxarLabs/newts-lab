# Hub tools

Mechanical checks for lab state and paper claims. The hub deliberately has no Python
environment of its own — invoke with uv's ephemeral env:

```bash
uv run --with pyyaml python tools/check_lab.py            # registry/idea consistency lint
uv run --with pyyaml python tools/audit_claims.py papers/<slug> [--check-commits]
uv run --with pyyaml python tools/show_config.py [<project-path> [exp-NNN.yaml]]  # 3-layer config + provenance
uv run --with pyyaml python tools/run_slots.py acquire|release|status             # cross-project compute slots
```

- `check_lab.py` — used by `/lab-status`: detects registry↔IDEA.md state drift, orphan
  idea/project/paper dirs, and stale rows. Exit 1 = real inconsistency, fix immediately.
- `audit_claims.py` — used by `/review-paper` Part A: verifies every number in a paper's
  `claims.yaml` against the referenced run artifacts. Exit 0 all verified · 2 MANUAL
  items need human verification · 1 any FAIL (a FAIL or unresolved MANUAL blocks review).

Project-level helpers (sweep/compare/status) live in each project's `scripts/`, not here.
