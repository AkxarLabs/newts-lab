# Experiment Log — {{title}}

Append-only narrative ledger. One entry per experiment attempt (including failures — especially
failures). Read this file AND `runs/registry.jsonl` AND `git log` before proposing a new experiment.

Entry format:

```markdown
## exp-NNN attempt N — YYYY-MM-DD HH:MM
**Config:** configs/experiments/exp-NNN-<name>.yaml · **Run id(s):** <run_id> · **Commit:** <sha>
**Hypothesis/question:** what this attempt tests.
**Outcome:** key metric(s) with values, or the failure mode (error class + one-line diagnosis).
**Decision:** keep / revert / debug (attempt k of 3) / move on — and why.
```

---

*(no entries yet)*
