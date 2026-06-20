# Paper venue templates

Each subdirectory is a **complete, ready-to-compile** paper skeleton for one venue:
a `main.tex` with the correct preamble **plus the official style/bib files vendored
alongside it**. The venue is selected by `writing.venue` in `lab/config.yaml`
(default `neurips`); a project's `control.yaml` may override it per-project. The
section skeleton is identical across venues — only the `\documentclass` / style
package / title block / `\bibliographystyle` differ.

`/write-paper` copies the **entire chosen venue directory** into `studies/<slug>/paper/`
(so the `.sty`/`.bst` travel with `main.tex` — it compiles offline, no fetch
needed). `generic` (no style files) uses the venue-agnostic `templates/paper/main.tex`
(`\documentclass{article}`).

## Vendored versions (current)

| `writing.venue` | Vendored style files | Version | `\bibliographystyle` | Cols | Page limit (body) | Submission mode |
|---|---|---|---|---|---|---|
| `neurips` *(default)* | `neurips_2025.sty` | **NeurIPS 2025** | `plainnat` | 1 | 9 | anonymous (default; `[preprint]`/`[final]` to reveal) |
| `icml`   | `icml2025.sty` `icml2025.bst` `fancyhdr.sty` `algorithm.sty` `algorithmic.sty` | **ICML 2025** | `icml2025` | 2 | 8 | anonymous (`[accepted]` for camera-ready) |
| `iclr`   | `iclr2026_conference.{sty,bst,bib}` `fancyhdr.sty` `natbib.sty` `math_commands.tex` | **ICLR 2026** | `iclr2026_conference` | 1 | 9 | anonymous (`\iclrfinalcopy` to reveal) |
| `aclarr` | `acl.sty` `acl_natbib.bst` | **ACL (rolling)** | `acl_natbib` | 2 | 8 (long) | anonymous (`[review]`; drop for camera-ready) |
| `aaai`   | `aaai2026.sty` `aaai2026.bst` | **AAAI 2026** | `aaai2026` | 2 | 7 (+2 refs) | anonymous (`[submission]`; drop for camera-ready) |
| `generic`| *(none — uses `templates/paper/main.tex`)* | `plainnat` | 1 | `writing.page_limit` | n/a |

The preambles default to **drafting / anonymous-review** mode. Each `main.tex`
header comment names the one-line edit to switch to camera-ready (de-anonymized);
`/finalize` makes that switch as part of the Gate-3 reproducibility pass.

## Refreshing to a newer year

Style files are versioned yearly. When a deadline targets a newer cycle, drop the
new `.sty`/`.bst` into the venue dir, bump the filename in that `main.tex`
(`\usepackage{…}` + `\bibliographystyle{…}`), and update the table above. Official
sources:

- **NeurIPS** — `https://media.neurips.cc/Conferences/NeurIPS<YEAR>/Styles.zip`
- **ICML** — `https://media.icml.cc/Conferences/ICML<YEAR>/Styles/icml<YEAR>.zip`
- **ICLR** — https://github.com/ICLR/Master-Template (per-year `iclr<YEAR>/` dir)
- **ACL ARR** — https://github.com/acl-org/acl-style-files (rolling; `acl.sty`, `acl_natbib.bst`)
- **AAAI** — https://aaai.org/ author kit (AAAI-`<YY>`); `aaai<YEAR>.sty`, `aaai<YEAR>.bst`

If a newer file can't be fetched (offline) at draft time, `/write-paper` keeps the
vendored version (still compiles) and queues "refresh `<venue>` style to `<year>`"
as a PI note for `/finalize` — it never leaves a non-compiling preamble.

> License note: these style files are redistributed under each venue's author-kit
> terms (free use for preparing submissions to that venue). They are author tooling,
> not lab code.
