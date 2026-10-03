r"""Mechanically audit a paper's claims.yaml against run artifacts.

    uv run --with pyyaml python checks/audit_claims.py studies/<slug>/paper [--rel-tol 1e-3]
        [--check-commits] [--verify-hashes]

Artifacts resolve from the hub archive (studies/<slug>/paper/artifacts/, locked by .claude/skills/finalize/tools/lock_artifacts.py
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

Completeness scan (unless --no-coverage): every measurement-like numeral (a DECIMAL or a
percentage) in main.tex body prose must carry a `% CNNN` annotation — an unannotated one
is a number typed into the paper without a claims entry, which the per-claim audit can
never see. Each is a FAIL. NOTE: bare integers are deliberately NOT scanned (years, counts,
section/figure numbers would swamp it with false positives); annotate integer headline
results with `% CNNN` yourself — the scan won't force it.

Novelty scan (--scan-novelty, opt-in): flag priority/superiority claims (state-of-the-art,
"first to", "outperforms all", unprecedented, best-known) in main.tex body prose that carry
NO backing on their line — no `\cite` positioning them against the prior work they claim to
beat, and no `% Cnnn/Nnnn` annotation (a traced number, or a `% Nnnn` lit-review novelty
pointer). Each is a WARN (exit 2): the discovery-vs-rediscovery gate. Cite the closest prior
work, add the lit-review pointer, or soften the wording — never ship an unbacked "we're first".

Exit codes: 0 all PASS/PASS-derived · 2 MANUAL items remain or unbacked novelty claims · 1 any FAIL.
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import labfiles  # noqa: E402 — the lab's files, read one way (tools/labfiles.py)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
FLOAT_RE = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")
# A measurement-like token for the coverage scan: a decimal (3.14) or a percentage (42%).
MEASUREMENT_RE = re.compile(r"-?\d+\.\d+|-?\d+\s*\\?%")
CLAIM_ANNOT_RE = re.compile(r"%.*\bC\d+\b")
# --scan-integers opt-in: a BARE integer (not part of a decimal) that sits near a result word — a
# headline count typed into the paper without a claims entry. Years and structural refs are excluded.
_INT_RE = re.compile(r"(?<![\d.eE])\d+(?![\d.])")
_METRIC_WORDS = re.compile(
    r"\b(samples?|tasks?|parameters?|params?|wins?|runs?|seeds?|points?|percentile|score|accuracy|"
    r"acc|loss|F1|episodes?|steps?|examples?|tokens?|images?|trials?|queries?)\b", re.I)
# Structural macros whose bracketed/braced args must not be scanned as prose (shared by all scans).
_STRUCT_MACRO_RE = re.compile(
    r"\\(?:includegraphics|include|input|usepackage|cite\w*|ref|label|url|href|figure|table|"
    r"equation|theorem|subsubsection|subsection|section)"
    r"(?![a-zA-Z])\s*(?:\[[^\]]*\])?\s*(?:\{[^}]*\})?")
# --scan-novelty opt-in: a PRIORITY/SUPERIORITY claim (SOTA / first-to / outperforms-all /
# unprecedented). These are the "we discovered something new" assertions that ship OUTSIDE the lab;
# each must be BACKED on its line by a \cite (positioning it against the prior work it claims to beat)
# or a % Cnnn/Nnnn annotation (a traced number, or a lit-review novelty pointer). An unbacked one is
# the field's most public failure mode: rediscovery mislabeled as discovery.
_PRIORITY_RE = re.compile(
    r"\b(?:state[- ]of[- ]the[- ]art|SOTA|"
    r"(?:the\s+)?first\s+(?:to\b|method|work|approach|system|model|paper|study|algorithm|framework)|"
    r"for\s+the\s+first\s+time|"
    r"outperforms?\s+all|surpass(?:es)?\s+all|beats?\s+all|"
    r"best[- ](?:known|performing)|"
    r"unprecedented)", re.I)
_NOVELTY_BACKING_RE = re.compile(r"\\cite|%.*\b[CN]\d+\b")


def projects_root() -> Path:
    """Resolve lab.projects_root from lab/config.yaml (relative paths anchor at the hub)."""
    return labfiles.projects_root(HUB)




def _registry_project_path(slug: str) -> Path | None:
    """Map a slug to its project dir via lab/REGISTRY.md's Project column — authoritative for."""
    return labfiles.registry_project_path(HUB, slug)


def resolve_project_dir(claim: dict) -> Path:
    """Where this claim's artifacts live. Precedence: explicit claim `project_path` >
    REGISTRY.md Project column > projects_root()/<slug> (the legacy default)."""
    pp = str(claim.get("project_path") or "").strip()
    if pp:
        p = Path(pp)
        return p if p.is_absolute() else (HUB / p).resolve()
    slug = str(claim.get("project", ""))
    return _registry_project_path(slug) or (projects_root() / slug)


def _body_lines(main_tex: Path):
    """Yield (lineno, raw, code) for each main.tex line after \\begin{document}: `raw` is the
    verbatim line (annotations live in its comment); `code` has the comment split off and
    structural macros (\\cite/\\ref/\\includegraphics/…) with their [..]/{..} args stripped so
    their internals aren't scanned as prose — yet a measurement/claim SHARING a line with a
    \\cite is still seen. Shared by every main.tex prose scan (DRY)."""
    in_body = False
    for i, raw in enumerate(main_tex.read_text(encoding="utf-8-sig").splitlines(), 1):
        if "\\begin{document}" in raw:
            in_body = True
            continue
        if not in_body:
            continue
        m = re.search(r"(?<!\\)%", raw)
        code = raw[:m.start()] if m else raw
        yield i, raw, _STRUCT_MACRO_RE.sub(" ", code)


def coverage_scan(paper_dir: Path, scan_integers: bool = False) -> list[str]:
    """Flag measurement-like numerals in main.tex body prose with no `% CNNN` annotation.
    Returns a list of 'Lnn: <line>' findings (empty = clean / no main.tex). With scan_integers, also
    flag a BARE integer sitting near a result word (excluding years 1900–2099 and structural refs)."""
    main_tex = paper_dir / "main.tex"
    if not main_tex.exists():
        return []
    findings = []
    for i, raw, code in _body_lines(main_tex):
        annotated = bool(CLAIM_ANNOT_RE.search(raw))
        if MEASUREMENT_RE.search(code) and not annotated:
            findings.append(f"L{i}: {raw.strip()[:90]}")
            continue
        if scan_integers and not annotated and _METRIC_WORDS.search(code):
            ints = [int(t) for t in _INT_RE.findall(code)]
            if any(not (1900 <= v <= 2099) for v in ints):   # a non-year integer near a result word
                findings.append(f"L{i} [int]: {raw.strip()[:90]}")
    return findings


def novelty_scan(paper_dir: Path) -> list[str]:
    """--scan-novelty: flag priority/superiority claims (SOTA / first-to / outperforms-all /
    unprecedented / best-known) in main.tex body prose that carry NO backing on their line —
    no \\cite positioning them against the prior work they claim to beat, and no `% Cnnn/Nnnn`
    annotation (a traced number or a lit-review novelty pointer). Each is a claim of discovery
    that may be rediscovery — the author must cite the closest prior work, add a `% Nnnn`
    lit-review pointer, or soften the wording. Returns 'Lnn [novelty ...]' findings."""
    main_tex = paper_dir / "main.tex"
    if not main_tex.exists():
        return []
    findings = []
    for i, raw, code in _body_lines(main_tex):
        m = _PRIORITY_RE.search(code)
        if m and not _NOVELTY_BACKING_RE.search(raw):
            findings.append(f"L{i} [novelty '{m.group(0).strip()}']: {raw.strip()[:80]}")
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
        if not (project_dir / ".git").exists():
            # No repo to check against (an /adopt project, or a hub-only archived audit) is NOT a
            # provenance failure — note it and skip, rather than reporting the commit as missing.
            print(f"[audit] note: {project_dir.name} is not a git repo — commit check skipped for "
                  f"{claim.get('id')}", file=sys.stderr)
        else:
            try:
                ok = subprocess.run(["git", "-C", str(project_dir), "cat-file", "-e", str(claim["commit"])],
                                    capture_output=True).returncode == 0
            except FileNotFoundError:
                print("[audit] note: git not on PATH — commit checks skipped", file=sys.stderr)
                ok = True
            if not ok:
                return "FAIL", f"commit {claim['commit']} not found in {project_dir.name}"

    per_artifact: list[list[tuple[str, float]]] = []
    for rel in artifacts:
        # hub archive first (studies/<slug>/paper/artifacts/, locked at /finalize), live project second —
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
    # An unstructured artifact (not .json/.jsonl) exposes EVERY float (timestamps, seeds, paths) to
    # the match pool, so without a `metric:` key a coincidental hit is possible — tracked below.
    unstructured = any(Path(rel).suffix not in (".json", ".jsonl") for rel in artifacts)

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

    if not numbers:
        if str(claim.get("derivation", "")).strip():
            return "MANUAL", "claim states a derivation but lists no numbers — verify by hand"
        return "FAIL", "claim has no numbers to verify (hard rule 1: a claim that checks nothing must not pass)"

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
        if unstructured and not want:
            # every match came from an unstructured artifact with no `metric:` key — a coincidental
            # hit (a timestamp, a seed) can't be ruled out, so a human must confirm it.
            return "MANUAL", "matched only in an unstructured artifact without a `metric:` — verify by hand"
        return "PASS", "all numbers found directly"
    return "PASS-derived", "matched via mean/std across artifacts" + (" + direct" if any_derived else "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paper_dir", help="e.g. studies/<slug>/paper")
    parser.add_argument("--rel-tol", type=float, default=1e-3)
    parser.add_argument("--check-commits", action="store_true")
    parser.add_argument("--verify-hashes", action="store_true",
                        help="verify each artifact against the locked artifact_sha256 (post-/finalize)")
    parser.add_argument("--no-coverage", action="store_true",
                        help="skip the main.tex unannotated-numeral completeness scan")
    parser.add_argument("--scan-integers", action="store_true", dest="scan_integers",
                        help="also flag bare integers near result words (excludes years/refs)")
    parser.add_argument("--scan-novelty", action="store_true", dest="scan_novelty",
                        help="flag priority/superiority claims (SOTA/first-to/outperforms-all) in "
                             "main.tex with no \\cite or %% Cnnn/Nnnn backing (WARN, exit 2)")
    args = parser.parse_args()

    paper_dir = (HUB / args.paper_dir) if not Path(args.paper_dir).is_absolute() else Path(args.paper_dir)
    claims_path = paper_dir / "claims.yaml"
    if not claims_path.exists():
        print(f"no claims.yaml at {claims_path}")
        return 1
    claims = (yaml.safe_load(claims_path.read_text(encoding="utf-8-sig")) or {}).get("claims") or []
    if not claims:
        if (paper_dir / "main.tex").exists():
            print("claims.yaml has no claims but main.tex exists — a results paper with zero traced "
                  "claims FAILS hard rule 1 (every quantitative claim must map to an artifact).")
            return 1
        print("claims.yaml has no claims and there is no main.tex yet — nothing to audit.")
        return 0

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

    coverage = [] if args.no_coverage else coverage_scan(paper_dir, scan_integers=args.scan_integers)
    if coverage:
        print(f"\n**Completeness FAIL — {len(coverage)} unannotated numeral(s) in main.tex "
              f"(no `% CNNN`):**")
        for f in coverage:
            print(f"- {f}")

    novelty = novelty_scan(paper_dir) if args.scan_novelty else []
    if novelty:
        print(f"\n**Novelty WARN — {len(novelty)} priority/superiority claim(s) in main.tex with no "
              f"`\\cite` or `% Cnnn/Nnnn` backing (cite the closest prior work, add a `% Nnnn` "
              f"lit-review pointer, or soften):**")
        for f in novelty:
            print(f"- {f}")

    print(f"\n{counts['PASS']} pass · {counts['PASS-derived']} derived · "
          f"{counts['MANUAL']} manual · {counts['FAIL']} fail · {len(coverage)} uncovered"
          + (f" · {len(novelty)} novelty" if args.scan_novelty else ""))
    if counts["FAIL"] or coverage:
        return 1
    if counts["MANUAL"] or novelty:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
