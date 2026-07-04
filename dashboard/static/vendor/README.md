# Vendored renderer libraries (offline, pinned)

The Library tab's document reader renders Markdown + LaTeX fully offline — no CDN, no
build step — so these third-party files are committed verbatim. Each is a pristine
upstream `dist` file fetched from the npm registry (via jsdelivr) at the pinned version.

| File(s) | Library | Version | License | Source |
|---|---|---|---|---|
| `marked.min.js` | [marked](https://github.com/markedjs/marked) — Markdown → HTML | 15.0.12 | MIT (`LICENSE-marked.md`) | `npm:marked@15.0.12/marked.min.js` |
| `purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) — HTML sanitizer | 3.2.6 | Apache-2.0 OR MPL-2.0 (`LICENSE-dompurify`) | `npm:dompurify@3.2.6/dist/purify.min.js` |
| `katex.min.js` · `katex.min.css` · `fonts/*.woff2` | [KaTeX](https://katex.org/) — LaTeX math | 0.16.22 | MIT (`LICENSE-katex`) | `npm:katex@0.16.22/dist/…` |

Notes:

- **Do not edit these files** — to upgrade, re-fetch the new version's dist files, update
  the pins here, and re-test the Library reader (tables, `$…$` / `$$…$$` math, dark+light).
- Fonts are the **woff2 set only** (every modern browser); `katex.min.css` also lists
  woff/ttf fallbacks, which 404 harmlessly if an ancient browser asks.
- The reader degrades gracefully: if a vendor script fails to load, documents fall back
  to plain preformatted text (see `renderMarkdown()` in `../app.js`).
