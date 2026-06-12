---
name: setup-lab
description: First-run interview — ask the PI the key questions, write lab/config.yaml accordingly, verify the environment, and seed the first directions. Run once after instantiating the template (and any time to reconfigure).
---

# Setup Lab

Goal: a 5-minute interview that leaves the lab configured, verified, and pointed at
the PI's research interests. Ask the questions below (grouped, not one at a time);
write the answers into `lab/config.yaml` (preserving comments); report what was set.

## 1. Interview

**Research focus**
- What area(s) do you research, and the 1–3 directions you most want explored first?
  → seed each as an entry in `lab/knowledge/OPEN-QUESTIONS.md` (Q-001…), which
  `/ideate` reads first.

**Compute reality**
- What hardware runs experiments (GPU? how many concurrent training runs can it take)?
  → `compute.max_concurrent_runs`.
- Typical tolerable wall-clock for a FULL run? → noted for proposal/control defaults.

**Autonomy appetite**
- Default Gate 2 stance: per-FULL-run approval, or routinely grant envelopes at Gate 1?
  → note in config comments; affects what `/propose` offers.
- Oversight level (`oversight.level`): `standard` (recommended) or `strict` (more
  overseer checks, more tokens)?

**Models & keys**
- Different models for subagent roles (`agents.*`), or `inherit` everywhere (default)?
- Semantic Scholar API key? (Free with an institutional email — strongly recommended;
  keyless access is saturated.) → tell them to set `S2_API_KEY`; same for
  `OPENALEX_API_KEY`.

**Projects location**
- Keep `lab.projects_root` at `../AutoScientist-Projects` or elsewhere?

## 2. Apply & verify

1. Write the answers into `lab/config.yaml`.
2. Environment check: `git --version`, `uv --version`, `uv run --with pyyaml python
   tools/check_lab.py` (should pass on an empty lab), `uv run --with mkdocs-material
   mkdocs build` (docs build). Report anything missing with the install command.
3. Smoke the project template once in a temp copy (run + tests) so the first real
   spawn is never the first test.

## 3. Hand off

Report the configuration summary, then offer the two on-ramps:
- Interactive: `/ideate <first direction>` — walk the lifecycle with gates.
- Unattended: `/overnight` — authorize a campaign and let the lab run while you sleep.
