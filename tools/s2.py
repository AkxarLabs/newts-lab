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

BIB_ENTRY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)\n\}", re.DOTALL)
BIB_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.+?)[}\"]\s*,?\s*\n", re.DOTALL)


def normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", title.lower())).strip()


def check_retracted(doi: str) -> bool | None:
    work = http_get(openalex_url(f"/works/https://doi.org/{doi}", {"select": "is_retracted"}))
    return None if work is None else bool(work.get("is_retracted"))


def cmd_verify(args) -> int:
    text = open(args.bibfile, encoding="utf-8").read()
    entries = []
    for match in BIB_ENTRY.finditer(text):
        fields = {k.lower(): re.sub(r"\s+", " ", v).strip() for k, v in BIB_FIELD.findall(match.group(2) + "\n")}
        entries.append({"key": match.group(1), **fields})
    if not entries:
        print("no bib entries found")
        return 0

    print(f"## Citation verification — {args.bibfile} ({len(entries)} entries, "
          f"threshold {args.threshold})\n")
    print("| key | status | detail |")
    print("|---|---|---|")
    worst = 0
    for e in entries:
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
        time.sleep(1.1 if os.environ.get("S2_API_KEY") else 2.0)  # client-side rate limit

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
