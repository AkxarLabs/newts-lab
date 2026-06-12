# Ideas

One directory per idea: `ideas/<slug>/`. Created by `/ideate`, enriched by `/lit-review` and `/propose`.

```
ideas/<slug>/
├── IDEA.md          # frontmatter = state + scores; the idea itself (template: templates/idea/IDEA.md)
├── lit-review.md    # added by /lit-review
├── critiques/       # /critique-paper outputs for load-bearing external papers
├── decisions.md     # added by /scope — ADR-style design deliberation record
├── proposal.md      # added by /propose (built from decisions.md)
└── reviews/         # proposal/paper review reports for this idea
```

The slug is the idea's lab-wide ID — the same slug names its project and paper directories.
