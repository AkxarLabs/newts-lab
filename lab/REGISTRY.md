# Lab Registry

Single source of truth for everything in the lab. Every procedure that changes an idea/project's state updates this file in the same session.

**States:** `seed` · `triaged` · `lit-review` · `proposal` · `active` · `analysis` · `writing` · `internal-review` · `final` · `parked` · `killed`

| ID | Title | State | Idea | Project | Paper | Updated | Next action |
|----|-------|-------|------|---------|-------|---------|-------------|
| — | *(empty — run `/ideate` to start)* | | | | | | |

## Conventions

- **ID**: short kebab-case slug, assigned at idea creation, reused for `ideas/<id>/`, `projects/<id>/`, `papers/<id>/`.
- **Updated**: date of last state change (YYYY-MM-DD).
- **Next action**: one line — what unblocks this idea (e.g., "awaiting PI gate 1", "run pilot exp-003").
- Killed/parked rows stay in the table (move to the bottom) with the reason linked in their `IDEA.md`.
