"""Mechanically audit a paper's claims.yaml against run artifacts.

    uv run --with pyyaml python tools/audit_claims.py papers/<slug> [--rel-tol 1e-3]
        [--check-commits] [--verify-hashes]

Artifacts resolve from the hub archive (papers/<slug>/artifacts/, locked by tools/lock_artifacts.py
at /finalize) first, then the live project — so a finalized paper audits from the hub alone.
--verify-hashes checks each artifact against the claim's locked artifact_sha256.

For every claim, each number must be found in the referenced artifacts:
  PASS         direct match in some artifact (within tolerance)
  PASS-derived matches the mean or std of a metric across the claim's artifact list
               (covers the canonical "mean over N seeds" case)
  MANUAL       no match, but the claim states a derivation — a human must verify it;
               never silently passed
  FAIL         artifact missing, no match anywhere (closest value reported), or a
               malformed claim entry

An optional `metric:` field per claim restricts matching to artifact leaves whose final
key equals it (e.g. metric: val_acc) — without it, any leaf within tolerance matches,
which can produce coincidental PASSes.

Tolerance per number = half-ULP of its printed precision. QUOTE numbers in claims.yaml to
preserve trailing zeros ("71.30" -> +/-0.005; the bare float 71.30 parses to 71.3 ->
+/-0.05, 10x looser), or |value| * --rel-tol, whichever is looser.

Completeness scan (unless --no-coverage): every measurement-like numeral (a decimal or a
percentage) in main.tex body prose must carry a `% CNNN` annotation — an unannotated one
is a number typed into the paper without a claims entry, which the per-claim audit can
never see. Each is a FAIL.

Exit codes: 0 all PASS/PASS-derived · 2 MANUAL items remain · 1 any FAIL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
FLOAT_RE = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")
# A measurement-like token for the coverage scan: a decimal (3.14) or a percentage (42%).
MEASUREMENT_RE = re.compile(r"-?\d+\.\d+|-?\d+\s*\\?%")
CLAIM_ANNOT_RE = re.compile(r"%.*\bC\d+\b")


def projects_root() -> Path:
    """Resolve lab.projects_root from lab/config.yaml (relative paths anchor at the hub)."""
    config = yaml.safe_load((HUB / "lab" / "config.yaml").read_text(encoding="utf-8-sig")) or {}
    root = ((config.get("lab") or {}).get("projects_root")) or "../AutoScientist-Projects"
    return (HUB / root).resolve()


_REG_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]


def _registry_project_path(slug: str) -> Path | None:
    """Map a slug to its project dir via lab/REGISTRY.md's Project column — authoritative for
    where a project actually lives (so an /adopt project outside projects_root still audits)."""
    reg = HUB / "lab" / "REGISTRY.md"
    if not slug or not reg.exists():
        return None
    for line in reg.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < len(_REG_COLS) or cells[0] != slug:
            continue
        raw = (dict(zip(_REG_COLS, cells)).get("project") or "").strip().strip("`")
        if raw and raw not in ("—", "-"):
            p = Path(raw)
            return p if p.is_absolute() else (HUB / p).resolve()
    return None


def resolve_project_dir(claim: dict) -> Path:
    """Where this claim's artifacts live. Precedence: explicit claim `project_path` >
    REGISTRY.md Project column > projects_root()/<slug> (the legacy default)."""
    pp = str(claim.get("project_path") or "").strip()
    if pp:
        p = Path(pp)
        return p if p.is_absolute() else (HUB / p).resolve()
    slug = str(claim.get("project", ""))
    return _registry_project_path(slug) or (projects_root() / slug)


def coverage_scan(paper_dir: Path) -> list[str]:
    """Flag measurement-like numerals in main.tex body prose with no `% CNNN` annotation.
    Returns a list of 'Lnn: <line>' findings (empty = clean / no main.tex)."""
    main_tex = paper_dir / "main.tex"
    if not main_tex.exists():
        return []
    findings, in_body = [], False
    for i, raw in enumerate(main_tex.read_text(encoding="utf-8-sig").splitlines(), 1):
        if "\\begin{document}" in raw:
            in_body = True
            continue
        if not in_body:
            continue
        # Split code from comment (first unescaped %); the annotation, if any, is in the comment.
        m = re.search(r"(?<!\\)%", raw)
        code = raw[:m.start()] if m else raw
        annotated = bool(CLAIM_ANNOT_RE.search(raw))
        # Skip structural lines whose numbers aren't prose measurements.
        if re.search(r"\\(input|include|includegraphics|cite\w*|ref|label|section|subsection|subsubsection|url|href|usepackage)", code):
            continue
        if MEASUREMENT_RE.search(code) and not annotated:
            findings.append(f"L{i}: {raw.strip()[:90]}")
    return findings


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
    text = path.read_text(encoding="utf-8-sig")
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


def audit_claim(claim: dict, paper_dir: Path, rel_tol: float, check_commits: bool,
                verify_hashes: bool) -> tuple[str, str]:
    project_dir = resolve_project_dir(claim)
    artifacts = claim.get("artifacts") or []
    numbers = claim.get("numbers") or []
    hashes = claim.get("artifact_sha256") or {}

    if check_commits and claim.get("commit"):
        ok = subprocess.run(["git", "-C", str(project_dir), "cat-file", "-e", str(claim["commit"])],
                            capture_output=True).returncode == 0
        if not ok:
            return "FAIL", f"commit {claim['commit']} not found in {project_dir.name}"

    per_artifact: list[list[tuple[str, float]]] = []
    for rel in artifacts:
        # hub archive first (papers/<slug>/artifacts/, locked at /finalize), live project second —
        # so a finalized paper stays auditable even if the project repo is gone.
        archived = paper_dir / "artifacts" / rel
        path = archived if archived.exists() else project_dir / rel
        if not path.exists():
            return "FAIL", f"artifact missing (hub archive + project): {rel}"
        if verify_hashes and rel in hashes:
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[rel]:
                return "FAIL", f"artifact hash mismatch (tampered/regenerated since /finalize): {rel}"
        try:
            per_artifact.append(extract_numbers(path))
        except (json.JSONDecodeError, ValueError) as e:
            return "FAIL", f"unreadable artifact {rel}: {e}"

    # Optional metric: restricts matching to leaves whose final key equals it, so a number
    # can't pass on a coincidental match against an unrelated leaf.
    want = str(claim.get("metric", "")).strip()
    def keep(key: str) -> bool:
        return not want or leaf_key(key) == want

    direct = [v for art in per_artifact for k, v in art if keep(k)]
    # Derived candidates: mean/std of each leaf key across the artifact list.
    by_key: dict[str, list[float]] = {}
    for art in per_artifact:
        for key, v in art:
            if keep(key):
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
    parser.add_argument("--verify-hashes", action="store_true",
                        help="verify each artifact against the locked artifact_sha256 (post-/finalize)")
    parser.add_argument("--no-coverage", action="store_true",
                        help="skip the main.tex unannotated-numeral completeness scan")
    args = parser.parse_args()

    paper_dir = (HUB / args.paper_dir) if not Path(args.paper_dir).is_absolute() else Path(args.paper_dir)
    claims_path = paper_dir / "claims.yaml"
    if not claims_path.exists():
        print(f"no claims.yaml at {claims_path}")
        return 1
    claims = (yaml.safe_load(claims_path.read_text(encoding="utf-8-sig")) or {}).get("claims") or []
    if not claims:
        print("claims.yaml has no claims — nothing to audit (a results paper with zero claims is suspicious)")

    print(f"## Claims audit — {args.paper_dir} ({len(claims)} claims)\n")
    print("| id | status | detail | location |")
    print("|---|---|---|---|")
    counts = {"PASS": 0, "PASS-derived": 0, "MANUAL": 0, "FAIL": 0}
    for claim in claims:
        try:
            status, detail = audit_claim(claim, paper_dir, args.rel_tol, args.check_commits,
                                         args.verify_hashes)
        except Exception as e:  # one malformed entry is a FAIL row, never a crashed audit
            status, detail = "FAIL", f"malformed claim entry: {e}"
        counts[status] += 1
        cid = claim.get("id") if isinstance(claim, dict) else "(non-mapping)"
        loc = claim.get("location", "") if isinstance(claim, dict) else ""
        print(f"| {cid} | **{status}** | {detail} | {loc} |")

    coverage = [] if args.no_coverage else coverage_scan(paper_dir)
    if coverage:
        print(f"\n**Completeness FAIL — {len(coverage)} unannotated numeral(s) in main.tex "
              f"(no `% CNNN`):**")
        for f in coverage:
            print(f"- {f}")

    print(f"\n{counts['PASS']} pass · {counts['PASS-derived']} derived · "
          f"{counts['MANUAL']} manual · {counts['FAIL']} fail · {len(coverage)} uncovered")
    if counts["FAIL"] or coverage:
        return 1
    if counts["MANUAL"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
