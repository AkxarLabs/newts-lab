# checks/ — the lab's mechanical rules

A **check** turns one of the lab's rules (`workflow/rules.yaml`) from prose into something an agent can't
skip: it reads the lab's files and exits **0 = OK · 1 = BLOCKED · 2 = WARN**. The skills call checks at
the moments that need them. The three gates and the lifecycle transitions are not here: they are built
into `tools/guard.py` and can't be removed.

A check takes one of two forms:

1. **A guard check** — a module with `NAME`, `add_args(parser)` and `run(args, guard) -> int`. The guard
   finds it by itself, so it runs as `uv run --with pyyaml python tools/guard.py <NAME> …` (and
   `tools/guard.py --list` shows it). `guard` gives it the lab: `HUB`, `LAB`, `labfiles`,
   `_row(slug)`, `_project_dir(slug)`, `_today()`, and `_verdict(code, message)` to print and return the
   result. `writeback.py` is the smallest example.
2. **A standalone script** with its own arguments — the paper audits (`audit_*.py`). Run it as
   `uv run --with pyyaml python checks/<script>.py …`. Listing one under `gate3_audits` in
   `workflow/rules.yaml` makes it part of what a campaign must pass before it may record a delegated
   Gate 3.

| Check | Enforces | Called by |
|---|---|---|
| `append-only` | the project's ledgers were only appended | `/experiment`, `/improve`, the loop |
| `writeback` | the session wrote back to the hub | session end |
| `evolve` | a kill left a CORRECTION; a result left a RECIPE | after a kill, at results-stage exits |
| `decisions` | settled non-headline decisions carry a Revisit predicate | `/scope`, the loop |
| `plan-trace` | every PLAN.md row traces to an authorized origin | the loop, `/improve` |
| `audit_claims.py` | every paper number traces to a run artifact | `/write-paper`, `/review-paper`, `/finalize`, Gate 3 |
| `audit_multiseed.py` | headline claims are multi-seed | the same |
| `audit_ablation_coverage.py` | every planned ablation ran, was waived, or was routed back | the same |
| `audit_eval_discipline.py` | tuned on validation, reported on held-out test | the same |

**Adding a rule with a check:** add the rule to `workflow/rules.yaml` (with `checks: [<name>]`), drop the
check here, call it from the skills that need it, and run `tools/workflow.py render-docs`. A lab that
does not use a method (say, `decisions.md`) can delete its check and the calls to it.
