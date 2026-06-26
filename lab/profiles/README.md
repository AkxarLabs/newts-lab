# Config profiles — budget tiers & engine presets

A **profile** is a named, *partial* set of `lab/config.yaml` overrides. Applying one stamps its
values into `lab/config.yaml` in place (comments preserved) so the lab uses them going forward.

```bash
uv run --with pyyaml python tools/profiles.py list
uv run --with pyyaml python tools/profiles.py show high
uv run --with pyyaml python tools/profiles.py diff high          # what would change
uv run --with pyyaml python tools/profiles.py apply high         # stamp it into lab/config.yaml
uv run --with pyyaml python tools/profiles.py save my-preset     # snapshot current settings as a profile
```

Or drive it from the agent with `/configure profile <list|show|diff|apply|save> <name>`.

## Two axes (they compose — apply a tier, then an engine preset)

**Budget tiers** scale *exploration* — how many agents/subagents, ideas, reviewer lenses, drafts,
parallelism, and how strong the models are:

| | `low` | `medium` (default) | `high` |
|---|---|---|---|
| ideas / critics / reviewers | few, 1 critic | the defaults | many, 3 critics, 7 reviewers |
| parallel subagents | 1 (serial) | 3 | 6 |
| per-role models | sonnet / haiku | session default | opus |
| **multi_seed_n (floor)** | **3** | **3** | **5** |
| **oversight (floor)** | **standard** | **standard** | **strict** |

**Engine presets** set *which* headless backend + its model: `claude-opus`, `claude-balanced`,
`claude-fast`, `codex`, `opencode`, `mixed` (strong model on verification, cheap on running).

## The one rule: budget scales exploration, never rigor

A profile may **never** lower an integrity floor — `experiment.multi_seed_n` below 3,
`oversight.level` to `off`, or touch `eval_frozen` / the Gate-2 envelope. `tools/profiles.py
validate <name>` (and `apply`) refuses any profile that does. A `low` run is *cheaper*, not
*sloppier* — it explores less but is held to the same gates, seeds, and verification.

## Make your own

Apply the closest tier, tweak any keys with `/configure set …`, then
`tools/profiles.py save <name>` to snapshot the current budget/model settings as a new named
profile. It lands here as `<name>.yaml` and is available to `apply` like any built-in.
