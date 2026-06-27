# References

A shared, append-only **reading index** — one row per paper worth remembering, logged as it is read during `/ideate` research scans or `/lit-review`. It is grounding that **compounds across ideas**: `/ideate` Phase 0 and `/discuss direction` skim it, so a paper already read for one idea is reused as grounding instead of re-fetched for the next.

This is **not** one of hard rule 11's three triggered operators — it carries no kill/result gate and is maintained continuously, not at session-end. It only *points*: the deep, per-idea analysis of a paper stays in that idea's `studies/<slug>/lit-review.md`. Record a paper when it changed your thinking or you'd want it back — the same bar as lit-review's "relevant papers", **not** every abstract skimmed (the exhaustive query trail already lives in each lit-review's search log).

Entry format (append-only, newest first):

```markdown
| bibkey | Authors, "Title", venue year — <link/DOI> | What it actually shows (one line) | seen-for |
|---|---|---|---|
| vaswani2017 | Vaswani et al., "Attention Is All You Need", NeurIPS 2017 — arxiv.org/abs/1706.03762 | Transformer beats RNN/CNN seq2seq on WMT14 EN–DE (28.4 BLEU) and trains in less wall-clock | attn-survey, Q-003 |
```

- **bibkey** — a stable citekey (e.g. `vaswani2017`), reusable verbatim in a paper's bibliography.
- **seen-for** — the idea slug(s) / `Q-NNN` this paper grounded, so later ideation can trace why it's here.

---

*(no references yet)*
