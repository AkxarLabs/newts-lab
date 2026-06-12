# Projects

One directory per approved proposal: `projects/<slug>/`, instantiated from `templates/project/` by `/spawn-project`.

**Each project is its own git repository** — the hub does not track project contents (see root `.gitignore`); the link is `lab/REGISTRY.md`. This keeps projects independently cloneable, publishable, and reproducible by others.

All experiment code, configs, runs, and ledgers live inside the project. See the project template's README for the layout and reproduction instructions.
