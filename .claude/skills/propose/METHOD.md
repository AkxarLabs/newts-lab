# Proposal: the method

How this lab writes a proposal by default. The PI can add to it or replace it (dashboard → Workflow).
The contract (SKILL.md) fixes what the proposal must contain and where it stops; this file is how to make
it good.

## Building it from the decisions

- Assemble the proposal from the settled decisions: §3 Method and §4 Experimental design follow
  `decisions.md` directly.
- An OPEN decision becomes an explicit pilot row whose criterion is "settles D-NNN".

## Making each required section strong

- **Headline hypothesis**: one sentence, the single central claim the project's novelty rests on,
  consistent with the `Headline: yes` decisions.
- **Frozen eval protocol**: design the split so that never reading the test set is physically easy to
  honour. Its concrete form follows the project type chosen at spawn: the literal split for `ml`,
  pre-registration plus a hold-out or placebo for `empirical`, calibration moments for `simulation`
  (see `templates/project-types/`).
- **Baseline**: the strongest fair baseline from the lit review's positioning section, not the
  convenient one.
- **Staged plan**:
  - exp-001 is always a SMOKE;
  - pilots answer the hypothesis cheaply;
  - FULL runs are few.

  Every row gets its promotion/success criterion written now. Criteria invented after seeing results
  are not criteria.
- **Ablations**: every method component gets a removal test. If the method has one component, plan the
  sanity ablations (for example, against a random or shuffled control).
- **Budgets and kill criteria**: concrete enough that a future session can apply them mechanically.

## Self-review

- Review the proposal once against the lit review. Would the authors of the closest work consider the
  comparison fair?
- Is the cheapest decisive experiment actually in the pilot stage?
