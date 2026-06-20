# TARGET.md — the fixed target this project pursues

*PI-owned and target-specific. Written by the PI (or by `/compete` from the PI's answers);
agents read and obey it, never edit it. It is the **frozen brief** for a target-driven
project — the analogue of `SYSTEM.md`, but for the goal instead of the machine. The numeric
/ contract fields are mirrored, machine-readable, in `control.yaml` → `target:`; this file is
the human source of truth and the rules. Delete any section that doesn't apply.*

> **A target-driven project** has a task with a **straightforward, fixed target** — a metric
> to hit, a benchmark to beat, a leaderboard to climb, an internal KPI to reach. There is no
> paper, no novelty gate, no headline hypothesis. The **frozen set** = `{the task data/
> resources, the metric + direction, the output contract, the rules below, the deadline}`.
> Everything else — model, features, approach, ensembling — is **open**, to be iterated toward
> the target by fanning out ideas inside the project and running experiments. The goal is to
> move the metric, honestly, within the rules.
>
> *Kaggle is one instance of this; so is "beat SOTA on benchmark X", "get this internal model
> to RMSE < 0.4", or "win the leaderboard at host Y". Nothing here assumes a specific tool —
> if the task is a Kaggle competition, work out and record the Kaggle specifics below.*

## The task & target

- **Name / host:**
- **URL (if any):**
- **Target / done-condition:** <!-- e.g. "public score >= 0.90", "RMSE < 0.42 on the grader",
     "top-10 on the leaderboard by the deadline" -->
- **Deadline (hard, if any):** <!-- YYYY-MM-DD. A loop stop-condition. -->

## Metric & scoring

- **Metric:** <!-- the scored metric, e.g. AUC, RMSE, accuracy, mAP@3, log-loss -->
- **Direction:** <!-- maximize | minimize -->
- **How a score is obtained:**
  - **Internal** — computed locally on a held-out split you hold (no data leaves the lab), **or**
  - **External** — you send an output to a scorer / leaderboard and read a score back. If
    external, fill `target.scoring.score_command` in control.yaml (any tool: a CLI, an HTTP
    call, a grader script) **and** the submission authorization section below.
- **Public / private (or val / final) split:** <!-- if the scorer hides a final split -->

## Data & resources

<!-- What the task provides and where it lives locally (mirror SYSTEM.md "Data locations" if
     shared). Train vs. test/unlabeled files; the id/key column; the target column(s); the
     exact output row count (so an output can be validated). How to fetch/authenticate
     (the exact command + which env-var key — names only, never values). -->

- **Train / resources:**
- **Test / unlabeled / grader input:**
- **Fetch / auth:**

## Output contract (only if the target is scored on an artifact you produce)

- **What a run produces:** <!-- e.g. a CSV `submission.csv` with header `id,target` -->
- **Path produced by a run:** <!-- e.g. runs/<run_id>/submission.csv -->
- **id column / target column(s):**
- **Expected row count:**
- **Validation:** `uv run --with pyyaml python scripts/check_output.py runs/<run_id>/<file>`

*If the target is just a local metric (no artifact leaves the project), there is no output
contract — delete this section and leave `target.output` unset in control.yaml.*

## Rules & constraints (compliance — binding like SYSTEM.md "Forbidden actions")

<!-- The task's own rules the agent must NOT break: allowed external data, pre-trained-model
     restrictions, compute/runtime limits, team/account rules, scorer rate limits, licence
     terms. A run that would break a rule here is blocked, not attempted. For a Kaggle task,
     this is where the competition's specific rules go. -->

## Selection-discipline note (hard rule 5, sharpened for a fixed target)

When the score is **external**, the scorer/leaderboard **is the held-out test** — you "read"
it only by sending an output, and the more you chase it the more you overfit it. Tune and
select on a **local validation split that mirrors the scorer**; treat each external read as a
scarce, trust-but-verify signal. The output the project *selects* as final is chosen on local
CV + sparing external confirmation, never on the external rank alone.

## Submission authorization (only if scoring is EXTERNAL — a Gate-2 analogue)

Sending an output to an external scorer **sends data outside the lab**, so it runs under a
PI-signed envelope, recorded in `control.yaml` → `target.score_envelope` (`per_day_max`,
`total_max`, `pi_signed`, `signed_via`) and enforced by `scripts/report_score.py`. No
envelope = every external read waits for the PI. **Selecting the final output** for the
hidden/final split is a **Gate 3** action — done by the PI in a session, never automated,
never dashboard-signed.
