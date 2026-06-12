"""Paper-grade figure & table utilities. Every figure script in scripts/figures/ uses
these — one shared style, so figures are consistent by construction and projects carry
no plotting boilerplate.

Principles baked in (see hub docs/tools.md for the research basis):
- Figures are sized at FINAL printed width and never rescaled in LaTeX.
- Vector PDF output, TrueType fonts (fonttype 42 — Type 3 fails camera-ready checks),
  PNG copy for quick visual review.
- Colorblind-safe palette (Okabe-Ito), vary linestyle/marker as well as color.
- Multi-seed results plot as mean with a band whose semantics the caption must state.
- Tables: booktabs, numbers formatted by `format_measurement` (std to 1-2 sig figs,
  mean to matching decimals) — prose never carries numerals; tables are emitted from
  artifacts.

matplotlib is imported lazily so the template has no hard mpl dependency until a
project actually plots (add `matplotlib` to pyproject.toml then).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Okabe-Ito, colorblind-safe (skip black; <=7 series — beyond that, rethink the figure)
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442"]
LINESTYLES = ["-", "--", "-.", ":"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X"]

# Final printed widths (inches): single column / full text width for common ML venues
WIDTHS = {"single": 3.3, "double": 6.9}

RC = {
    "figure.constrained_layout.use": True,
    "savefig.format": "pdf",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "axes.linewidth": 0.5,
    "lines.linewidth": 1.0,
    "lines.markersize": 3,
    "axes.prop_cycle": None,  # set in new_fig (needs cycler import)
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
}


def new_fig(width: str = "single", height_ratio: float = 0.66, ncols: int = 1):
    """Create (fig, ax) at final print size with the lab style applied."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from cycler import cycler

    rc = {k: v for k, v in RC.items() if v is not None}
    rc["axes.prop_cycle"] = cycler(color=PALETTE)
    plt.rcParams.update(rc)

    w = WIDTHS[width]
    fig, ax = plt.subplots(1, ncols, figsize=(w, w * height_ratio), constrained_layout=True)
    return fig, ax


def save_fig(fig, name: str, out_dir: str | Path = "figures", consumed_runs: list[str] | None = None) -> Path:
    """Save vector PDF + review PNG; print the run ids consumed (claims.yaml provenance)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / f"{name}.pdf"
    fig.savefig(pdf)
    fig.savefig(out / f"{name}.png", dpi=300)
    print(f"[fig] {pdf}  runs={consumed_runs or 'STATE-THE-RUN-IDS'}")
    return pdf


# ── artifact access ─────────────────────────────────────────────────────────

def load_registry(repo: Path | None = None) -> list[dict]:
    path = (repo or REPO) / "runs" / "registry.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines() if l.strip()]
    return [r for r in rows if r.get("status") == "completed"]


def metric_curve(run_id: str, metric: str, repo: Path | None = None) -> tuple[list, list]:
    """(steps, values) streamed during a run — for training curves."""
    path = (repo or REPO) / "runs" / run_id / "metrics.jsonl"
    steps, values = [], []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        rec = json.loads(line)
        if metric in rec:
            steps.append(rec.get("step", len(steps)))
            values.append(rec[metric])
    return steps, values


def seed_stats(rows: list[dict], metric: str) -> tuple[float, float, int]:
    """(mean, std, n) of a final metric across registry rows (e.g. one experiment's seeds)."""
    vals = [r["metrics"][metric] for r in rows
            if isinstance((r.get("metrics") or {}).get(metric), (int, float))]
    if not vals:
        raise ValueError(f"no values for metric '{metric}'")
    return (statistics.mean(vals),
            statistics.stdev(vals) if len(vals) >= 2 else 0.0,
            len(vals))


# ── numbers & tables ────────────────────────────────────────────────────────

def format_measurement(mean: float, std: float, n: int | None = None, sig: int = 2) -> str:
    """Sig-fig discipline: round std to `sig` significant figures, mean to match.
    71.2847 ± 0.3912 -> '71.28 ± 0.39'. std==0 -> mean at 4 sig figs."""
    if std <= 0:
        return f"{mean:.4g}"
    decimals = max(0, sig - 1 - int(math.floor(math.log10(abs(std)))))
    out = f"{mean:.{decimals}f} \\pm {std:.{decimals}f}"
    return f"{out} ({n})" if n is not None else out


def emit_table(headers: list[str], rows: list[list[str]], path: str | Path,
               caption: str = "", label: str = "", bold_row: int | None = None) -> Path:
    """Emit a booktabs LaTeX table file. Cells are pre-formatted strings (use
    format_measurement) — this function never computes, only lays out, so the numbers'
    provenance stays in the calling script."""
    lines = ["\\begin{table}[t]", "\\centering"]
    if caption:
        lines.append(f"\\caption{{{caption}}}")
    if label:
        lines.append(f"\\label{{{label}}}")
    lines.append("\\begin{tabular}{l" + "r" * (len(headers) - 1) + "}")
    lines.append("\\toprule")
    lines.append(" & ".join(headers) + " \\\\")
    lines.append("\\midrule")
    for i, row in enumerate(rows):
        cells = [f"\\textbf{{{c}}}" for c in row] if i == bold_row else list(row)
        lines.append(" & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[table] {out}")
    return out
