# NOTES — distilled memory for {{title}}

**Read this at the start of every session** (it is short by design). It is the *distilled*
index over `EXPERIMENT_LOG.md`: the ledger is the full chronological record; this file is the
"don't make me re-learn this" layer that survives even when early entries scroll out of the
log tail. **Append-only**, one line per lesson, each with an evidence pointer (`exp-NNN` /
`run_id` / commit). Keep it lean — a line earns its place only if it would save a future
session a repeated mistake or a re-tried dead end. Durable *cross-project* lessons are also
promoted to the hub knowledge (see this project's `CLAUDE.md` → "Session end").

## Gotchas & fixes (environment / data / infra)

<!-- One line each: the trap → the fix/workaround, with an evidence pointer.
     e.g.  - data path `/mnt/x` stalls under load → stage to local scratch first (exp-004) -->

*(none yet)*

## Tried & abandoned (approaches that didn't work — do not re-try blindly)

<!-- approach → where it was tried → why it failed → "don't retry unless <condition>".
     e.g.  - label smoothing 0.1: exp-006/exp-009, no val gain (-0.1%), reverted; skip unless data noise rises -->

*(none yet)*

## What worked / settled here (keepers + key results)

<!-- The decisions and results that HOLD for this project, with run-id evidence. Cross-ref a
     hub design decision as decisions.md D-NNN where one applies.
     e.g.  - cosine LR is the baseline keeper: +0.6% val over step (exp-007, run 20260620-…) -->

*(none yet)*
