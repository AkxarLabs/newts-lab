"""Mechanically audit a paper's claims.yaml against run artifacts.

    uv run --with pyyaml python tools/audit_claims.py papers/<slug> [--rel-tol 1e-3] [--check-commits]

For every claim, each number must be found in the referenced artifacts:
  PASS         direct match in some artifact (within tolerance)
  PASS-derived matches the mean or std of a metric across the claim's artifact list
               (covers the canonical "mean over N seeds" case)
  MANUAL       no match, but the claim states a derivation — a human must verify it;
               never silently passed
  FAIL         artifact missing, or no match anywhere (closest value reported)

Tolerance per number = half-ULP of its printed precision (claim says 2.3 -> +/-0.05),
or |value| * --rel-tol, whichever is looser.

Exit codes: 0 all PASS/PASS-derived · 2 MANUAL items remain · 1 any FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[1]
FLOAT_RE = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")


def projects_root() -> Path:
    """Resolve lab.projects_root from lab/config.yaml (relative paths anchor at the hub)."""
    config = yaml.safe_load((HUB / "lab" / "config.yaml").read_text(encoding="utf-8")) or {}
    root = ((config.get("lab") or {}).get("projects_root")) or "../AutoScientist-Projects"
    return (HUB / root).resolve()


def numeric_leaves(node, prefix: str = "") -> list[tuple[str, float]]:
    """Recursively collect (key_path, value) numeric leaves from JSON data."""
    out = []
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out.append((prefix, float(node)))
    elif isinstance(node, dict):
        for k, v in node.items():
            out.extend(numeric_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(numeric_leaves(v, f"{prefix}[{i}]"))
    return out


def extract_numbers(path: Path) -> list[tuple[str, float]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return numeric_leaves(json.loads(text))
    if path.suffix == ".jsonl":
        out = []
        for i, line in enumerate(text.strip().splitlines()):
            if line.strip():
                out.extend(numeric_leaves(json.loads(line), prefix=f"L{i}"))
        return out
    return [("", float(m.group())) for m in FLOAT_RE.finditer(text)]


def tolerance(value: float, printed: str, rel_tol: float) -> float:
    decimals = len(printed.split(".")[1]) if "." in printed and "e" not in printed.lower() else 0
    half_ulp = 0.5 * 10 ** -decimals
    return max(half_ulp, abs(value) * rel_tol)


def leaf_key(path: str) -> str:
    """'L3.metrics.val_loss' -> 'val_loss' — group artifact values by final key name."""
    return re.split(r"[.\[]", path)[-1].rstrip("]") if path else ""


def audit_claim(claim: dict, rel_tol: float, check_commits: bool) -> tuple[str, str]:
    project_dir = projects_root() / str(claim.get("project", ""))
    artifacts = claim.get("artifacts") or []
    numbers = claim.get("numbers") or []

    if check_commits and claim.get("commit"):
        ok = subprocess.run(["git", "-C", str(project_dir), "cat-file", "-e", str(claim["commit"])],
                            capture_output=True).returncode == 0
        if not ok:
            return "FAIL", f"commit {claim['commit']} not found in {project_dir.name}"

    per_artifact: list[list[tuple[str, float]]] = []
    for rel in artifacts:
        path = project_dir / rel
        if not path.exists():
            return "FAIL", f"artifact missing: {rel}"
        try:
            per_artifact.append(extract_numbers(path))
        except (json.JSONDecodeError, ValueError) as e:
            return "FAIL", f"unreadable artifact {rel}: {e}"

    direct = [v for art in per_artifact for _, v in art]
    # Derived candidates: mean/std of each leaf key across the artifact list.
    by_key: dict[str, list[float]] = {}
    for art in per_artifact:
        for key, v in art:
            by_key.setdefault(leaf_key(key), []).append(v)
    derived = []
    for vals in by_key.values():
        derived.append(statistics.mean(vals))
        if len(vals) >= 2:
            derived.append(statistics.stdev(vals))

    all_direct, any_derived, misses = True, False, []
    for n in numbers:
        value = float(n)
        tol = tolerance(value, str(n), rel_tol)
        if any(abs(value - v) <= tol for v in direct):
            continue
        all_direct = False
        if any(abs(value - v) <= tol for v in derived):
            any_derived = True
            continue
        closest = min(direct + derived, key=lambda v: abs(v - value)) if (direct or derived) else None
        misses.append(f"{n} (closest: {closest:.6g})" if closest is not None else f"{n} (no numbers found)")

    if misses:
        if str(claim.get("derivation", "")).strip():
            return "MANUAL", f"unmatched: {', '.join(misses)}; verify derivation by hand"
        return "FAIL", f"unmatched: {', '.join(misses)}"
    if all_direct:
        return "PASS", "all numbers found directly"
    return "PASS-derived", "matched via mean/std across artifacts" + (" + direct" if any_derived else "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paper_dir", help="e.g. papers/<slug>")
    parser.add_argument("--rel-tol", type=float, default=1e-3)
    parser.add_argument("--check-commits", action="store_true")
    args = parser.parse_args()

    claims_path = (HUB / args.paper_dir / "claims.yaml") if not Path(args.paper_dir).is_absolute() \
        else Path(args.paper_dir) / "claims.yaml"
    if not claims_path.exists():
        print(f"no claims.yaml at {claims_path}")
        return 1
    claims = (yaml.safe_load(claims_path.read_text(encoding="utf-8")) or {}).get("claims") or []
    if not claims:
        print("claims.yaml has no claims — nothing to audit (a results paper with zero claims is suspicious)")
        return 0

    print(f"## Claims audit — {args.paper_dir} ({len(claims)} claims)\n")
    print("| id | status | detail | location |")
    print("|---|---|---|---|")
    counts = {"PASS": 0, "PASS-derived": 0, "MANUAL": 0, "FAIL": 0}
    for claim in claims:
        status, detail = audit_claim(claim, args.rel_tol, args.check_commits)
        counts[status] += 1
        print(f"| {claim.get('id')} | **{status}** | {detail} | {claim.get('location', '')} |")

    print(f"\n{counts['PASS']} pass · {counts['PASS-derived']} derived · "
          f"{counts['MANUAL']} manual · {counts['FAIL']} fail")
    if counts["FAIL"]:
        return 1
    if counts["MANUAL"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
