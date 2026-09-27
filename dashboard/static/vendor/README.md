# Vendored renderer libraries (offline, pinned)

The UI is built with Preact + htm, the Library reader renders Markdown + LaTeX, and the world renders with PixiJS, fully
offline — no CDN, no build step — so these third-party files are committed verbatim. Each is a pristine
upstream `dist` file fetched from the npm registry (via jsdelivr) at the pinned version.

| File(s) | Library | Version | License | Source |
|---|---|---|---|---|
| `marked.min.js` | [marked](https://github.com/markedjs/marked) — Markdown → HTML | 15.0.12 | MIT (`LICENSE-marked.md`) | `npm:marked@15.0.12/marked.min.js` |
| `purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) — HTML sanitizer | 3.2.6 | Apache-2.0 OR MPL-2.0 (`LICENSE-dompurify`) | `npm:dompurify@3.2.6/dist/purify.min.js` |
| `katex.min.js` · `katex.min.css` · `fonts/*.woff2` | [KaTeX](https://katex.org/) — LaTeX math | 0.16.22 | MIT (`LICENSE-katex`) | `npm:katex@0.16.22/dist/…` |
| `pixi/pixi.min.js` | [PixiJS](https://pixijs.com/) — the diorama world's 2D GPU renderer (global `PIXI`) | 8.21.0 | MIT (`pixi/LICENSE-pixi`) | `npm:pixi.js@8.21.0/dist/pixi.min.js` |
| `preact/preact.umd.js` · `preact/hooks.umd.js` | [Preact](https://preactjs.com/) — the UI's component + diffing runtime (globals `preact`, `preactHooks`) | 10.29.8 | MIT (`preact/LICENSE-preact`) | `npm:preact@10.29.8/dist/preact.umd.js`, `…/hooks/dist/hooks.umd.js` |
| `preact/htm.umd.js` | [htm](https://github.com/developit/htm) — JSX-like tagged templates, no build (global `htm`) | 3.1.1 | Apache-2.0 (`preact/LICENSE-htm`) | `npm:htm@3.1.1/dist/htm.umd.js` |
| `xterm/xterm.js` · `xterm/xterm.css` | [xterm.js](https://xtermjs.org/) — the in-browser terminal (sign-in / install / shell on a remote or headless machine); loaded only when a terminal opens (global `Terminal`) | 6.0.0 | MIT (`xterm/LICENSE-xterm`) | `npm:@xterm/xterm@6.0.0/lib/xterm.js`, `…/css/xterm.css` |
| `xterm/addon-fit.js` | xterm fit addon (global `FitAddon`) | 0.11.0 | MIT (`xterm/LICENSE-addon-fit`) | `npm:@xterm/addon-fit@0.11.0/lib/addon-fit.js` |
| `pixi/pixi-filters.js` | [pixi-filters](https://github.com/pixijs/filters) — optional effects (gallery / future use; not loaded by the dashboard) | 6.1.5 | MIT (`pixi/LICENSE-pixi-filters`) | `npm:pixi-filters@6.1.5/dist/pixi-filters.js` |

Notes:

- **Do not edit these files** — to upgrade, re-fetch the new version's dist files, update
  the pins here, and re-test the Library reader (tables, `$…$` / `$$…$$` math, dark+light).
- Fonts are the **woff2 set only** (every modern browser); `katex.min.css` also lists
  woff/ttf fallbacks, which 404 harmlessly if an ancient browser asks.
- The reader degrades gracefully: if a vendor script fails to load, documents fall back
  to plain preformatted text (see `NL.mdToHtml()` in `../ui/components.js`).
