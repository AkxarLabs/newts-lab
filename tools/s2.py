"""Literature API helper — Semantic Scholar (primary) with OpenAlex fallback.

    uv run --with pyyaml python tools/s2.py search "small language model distillation" [--limit 10] [--year 2023:] [--bulk]
    uv run --with pyyaml python tools/s2.py bibtex arXiv:2504.08066
    uv run --with pyyaml python tools/s2.py verify papers/<slug>/references.bib [--threshold 0.85]

Why: replayable, logged literature searches for /lit-review and /scope, mechanical
BibTeX from paper ids for /write-paper, and zero-assumption citation verification for
/review-paper (every bib entry checked against the real record; retractions via
OpenAlex `is_retracted`). LLM-free-generated citations are fabricated at ~18% (GPT-4
class) — verification is mandatory, not optional.

Keys (optional but recommended — keyless S2 shares a saturated global pool):
    S2_API_KEY        header x-api-key (free: semanticscholar.org/product/api)
    OPENALEX_API_KEY  param api_key (free account: openalex.org; required since 2026-02)

Exit codes (verify): 0 all verified · 2 title/year mismatches only · 1 not-found or retracted.
Exit codes (search): 0 results (or a genuinely empty literature) · 3 BOTH backends
unreachable — an empty result then is NOT evidence of absence (matters for /lit-review's
novelty verdict).
stdlib only (urllib); pyyaml unused but kept for uniform tool invocation.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

S2 = "https://api.semanticscholar.org/graph/v1"
OPENALEX = "https://api.openalex.org"
FIELDS = "title,abstract,year,venue,citationCount,externalIds,authors.name,tldr"


def http_get(url: str, retries: int = 4) -> dict | None:
    headers = {"User-Agent": "AutoScientist-lab-tools"}
    if "semanticscholar" in url and os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                wait = (2 ** attempt) + random.random()
                print(f"[s2] {e.code}, backing off {wait:.1f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 404:
                return None
            print(f"[s2] HTTP {e.code} for {url}", file=sys.stderr)
            return None
        except Exception as e:  # noqa: BLE001 — network tool, report and move on
            print(f"[s2] {e}", file=sys.stderr)
            return None
    return None


def openalex_url(path: str, params: dict) -> str:
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    return f"{OPENALEX}{path}?{urllib.parse.urlencode(params)}"


# ── search ──────────────────────────────────────────────────────────────────

def cmd_search(args) -> int:
    endpoint = "search/bulk" if args.bulk else "search"
    params = {"query": args.query, "fields": FIELDS, "limit": args.limit}
    if args.year:
        params["year"] = args.year
    data = http_get(f"{S2}/paper/{endpoint}?{urllib.parse.urlencode(params)}")
    papers = (data or {}).get("data") or []

    if not papers:  # S2 down/saturated -> OpenAlex
        print("[s2] no S2 results/unreachable — falling back to OpenAlex", file=sys.stderr)
        oa = http_get(openalex_url("/works", {"search": args.query, "per-page": args.limit,
                                              "select": "title,publication_year,doi,cited_by_count,primary_location"}))
        # Distinguish a genuine empty literature from both backends being unreachable:
        # http_get returns None on request failure, {} (truthy-empty .get) on a real empty hit.
        if data is None and oa is None:
            print("\n**BOTH BACKENDS UNREACHABLE — this empty result is NOT evidence of "
                  "absence.** Do not issue a novelty verdict from it; record the search as "
                  "blocked and retry, or fall back to web search.", flush=True)
            return 3
        for w in (oa or {}).get("results") or []:
            venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
            print(f"- **{w.get('title')}** ({w.get('publication_year')}, {venue}; "
                  f"cites={w.get('cited_by_count')}) {w.get('doi') or ''}")
        return 0

    for p in papers:
        ids = p.get("externalIds") or {}
        handle = f"arXiv:{ids['ArXiv']}" if ids.get("ArXiv") else (f"DOI:{ids['DOI']}" if ids.get("DOI") else p.get("paperId", ""))
        authors = ", ".join(a["name"] for a in (p.get("authors") or [])[:3])
        tldr = (p.get("tldr") or {}).get("text") or (p.get("abstract") or "")[:200]
        print(f"- **{p.get('title')}** — {authors} ({p.get('year')}, {p.get('venue') or '—'}; "
              f"cites={p.get('citationCount')}) `{handle}`\n  {tldr}")
    return 0


# ── bibtex ──────────────────────────────────────────────────────────────────

def cmd_bibtex(args) -> int:
    data = http_get(f"{S2}/paper/{urllib.parse.quote(args.paper_id)}?fields=citationStyles,title")
    bib = ((data or {}).get("citationStyles") or {}).get("bibtex")
    if not bib:
        print(f"no bibtex for {args.paper_id}", file=sys.stderr)
        return 1
    print(bib.strip())
    return 0


# ── verify ──────────────────────────────────────────────────────────────────

def parse_bib_fields(body: str) -> dict:
    """Parse `key = {value}, key = "value", key = 2024` tolerating multi-line, brace-balanced
    values (a regex that stops at the first `}` truncates wrapped titles → false MISMATCH)."""
    fields, i, n = {}, 0, len(body)
    while i < n:
        m = re.match(r"\s*(\w+)\s*=\s*", body[i:])
        if not m:
            i += 1
            continue
        key = m.group(1).lower()
        i += m.end()
        if i >= n:
            break
        if body[i] == "{":
            depth, j = 0, i
            while j < n:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            val, i = body[i + 1:j], j + 1
        elif body[i] == '"':
            j = body.find('"', i + 1)
            val, i = (body[i + 1:j], j + 1) if j != -1 else (body[i + 1:], n)
        else:
            j = i
            while j < n and body[j] not in ",\n":
                j += 1
            val, i = body[i:j], j
        fields[key] = re.sub(r"\s+", " ", val).strip()
        while i < n and body[i] in ", \n\t":
            i += 1
    return fields


def parse_bib(text: str) -> list[dict]:
    """Brace-count each @entry so a `}` inside an abstract/note doesn't end it early."""
    entries = []
    for m in re.finditer(r"@\w+\s*\{", text):
        depth, j = 1, m.end()
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        key, _, rest = text[m.end():j - 1].partition(",")
        entries.append({"key": key.strip(), **parse_bib_fields(rest)})
    return entries


def normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", title.lower())).strip()


def check_retracted(doi: str) -> bool | None:
    work = http_get(openalex_url(f"/works/https://doi.org/{doi}", {"select": "is_retracted"}))
    return None if work is None else bool(work.get("is_retracted"))


def cmd_verify(args) -> int:
    text = open(args.bibfile, encoding="utf-8-sig").read()
    entries = parse_bib(text)
    if not entries:
        print("no bib entries found")
        return 0

    print(f"## Citation verification — {args.bibfile} ({len(entries)} entries, "
          f"threshold {args.threshold})\n")
    print("| key | status | detail |")
    print("|---|---|---|")
    worst = 0
    for idx, e in enumerate(entries):
        if idx:  # client-side rate limit, paid on EVERY iteration incl. the continue paths
            time.sleep(1.1 if os.environ.get("S2_API_KEY") else 2.0)
        title = e.get("title", "")
        if not title:
            print(f"| {e['key']} | **NOT-FOUND** | entry has no title |")
            worst = max(worst, 2)
            continue
        match = http_get(f"{S2}/paper/search/match?query={urllib.parse.quote(title)}"
                         f"&fields=title,year,externalIds")
        found = (match or {}).get("data") or ([match] if match and match.get("title") else [])
        if not found:
            print(f"| {e['key']} | **NOT-FOUND** | no S2 match for title |")
            worst = max(worst, 2)
            continue
        hit = found[0]
        ratio = difflib.SequenceMatcher(None, normalize(title), normalize(hit.get("title", ""))).ratio()
        notes = []
        if ratio < args.threshold:
            notes.append(f"title sim {ratio:.2f} — found: \"{hit.get('title')}\"")
        bib_year, real_year = e.get("year"), hit.get("year")
        if bib_year and real_year and str(real_year) != str(bib_year):
            notes.append(f"year {bib_year} != {real_year}")
        doi = e.get("doi") or ((hit.get("externalIds") or {}).get("DOI"))
        if doi:
            retracted = check_retracted(doi)
            if retracted:
                print(f"| {e['key']} | **RETRACTED** | OpenAlex is_retracted=true |")
                worst = max(worst, 2)
                continue
        if notes:
            print(f"| {e['key']} | MISMATCH | {'; '.join(notes)} |")
            worst = max(worst, 1)
        else:
            print(f"| {e['key']} | verified | sim {ratio:.2f} |")

    return {0: 0, 1: 2, 2: 1}[worst]


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("query"); p.add_argument("--limit", type=int, default=10)
    p.add_argument("--year"); p.add_argument("--bulk", action="store_true")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("bibtex")
    p.add_argument("paper_id", help="S2 paperId, arXiv:NNNN.NNNNN, or DOI:...")
    p.set_defaults(fn=cmd_bibtex)
    p = sub.add_parser("verify")
    p.add_argument("bibfile"); p.add_argument("--threshold", type=float, default=0.85)
    p.set_defaults(fn=cmd_verify)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
