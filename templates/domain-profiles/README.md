# templates/domain-profiles/ — the domain layer (content, not structure)

A **domain profile** is the *second axis* of a project (the first is the methodology type in
`templates/project-types/`). It carries **content** a methodology type can't: target venues, data
sources, and the field's conventions — so `theory × econ` = math-econ theory on the `theory`
engine, without inventing a new type.

A profile is **light by design** — a short card the agent reads at spawn and may copy into the
project as `DOMAIN.md`. The agent **generates a profile on demand** for any field; the ones here
are just starters. A profile never changes the engine or the hard rules — only the vocabulary,
the citation targets, and where data comes from.

A profile names:
- **Venues** — where this field publishes (sets `writing.venue` / the bibliography targets).
- **Data sources** — canonical datasets/APIs and how to access them (command + env-var key names,
  never secret values).
- **Conventions** — what rigor looks like here (identification, robustness, pre-registration,
  reporting norms) and which methodology types are typical.

Starters: `econ.md`. To add one, write `<domain>.md` in this shape (or let the agent draft it).
