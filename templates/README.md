# Templates

Scaffolds the lifecycle skills instantiate. Two kinds live here: **whole-repo templates**
(`project/`, with the `compete/` overlay) that become spawned project repos elsewhere, and
**single-artifact scaffolds** (everything else) the hub copies into `studies/<slug>/` or a project
as a stage begins. Placeholders like `{{slug}}`, `{{title}}`, `{{hub_path}}`, `{{date}}` are
substituted at instantiation.

| Subdir | What it is | Consumed by |
|---|---|---|
| `project/` | the full spawned **project repo** scaffold — `src/project_pkg/`, `scripts/run.py` + `sweep.py`, `control.yaml`, `configs/`, `AGENTS.md`/`CLAUDE.md`, `.claude/` (settings + vendored engineering skills), CI | `/spawn-project`, `/adopt` |
| `compete/` | **overlay** applied on top of `project/` for target-driven projects — `TARGET.md`, `control.target.yaml`, output contract + scorer scripts | `/compete` |
| `project-types/<type>/TYPE.md` | one-page **methodology card** (`ml` · `empirical` · `simulation` · `theory` · `target-driven`) defining what an "experiment" is for that type; one is copied into the project | `/spawn-project` (PI-confirmed `project_type`) |
| `domain-profiles/` | orthogonal **domain layer** (e.g. `econ.md`) adding venues / data sources / conventions on top of a type | `/spawn-project` |
| `idea/` | hub **idea scaffolds** — `IDEA.md`, `lit-review.md`, `proposal.md`, `decisions.md`, `session.md` — copied into `studies/<slug>/` | `/ideate`, `/lit-review`, `/scope`, `/propose`, `/discuss` |
| `paper/` | **LaTeX paper** scaffold (`main.tex`, `references.bib`, `claims.yaml`) + `venues/<venue>/` style files | `/write-paper` |
| `review/` | **review scaffolds** — `critique-lenses.md`, `rubric.md`, `meta-review.md`, `response.md` | `/critique-paper`, `/review-paper` |
| `loop/` | unattended-run scaffolds — `LOOP_BRIEF.md` (the PI's Gate-2 brief) + `CAMPAIGN.md` | `/research-loop`, `/autopilot` |
| `SYSTEM.md` | optional **machine/cluster** description the PI fills in; copied into each project at spawn | `/setup-lab`, `/spawn-project` |

Each whole-repo template and the two orthogonal axes (`project-types/`, `domain-profiles/`) carry
their own `README.md` with the details.
