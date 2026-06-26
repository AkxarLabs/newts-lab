"""Literature API helper — Semantic Scholar primary, with keyless DOI fallbacks + OpenAlex.

    uv run --with pyyaml python tools/s2.py search "small language model distillation" [--limit 10] [--year 2023:] [--bulk]
    uv run --with pyyaml python tools/s2.py bibtex arXiv:2504.08066 [--append studies/<slug>/paper/references.bib]
    uv run --with pyyaml python tools/s2.py bibtex DOI:10.48550/arXiv.2504.08066   # the agentic websearch→DOI fallback
    uv run --with pyyaml python tools/s2.py verify studies/<slug>/paper/references.bib [--threshold 0.85]
    uv run --with pyyaml python tools/s2.py citecheck studies/<slug>/paper          # every \\cite traces to bib + lit-review

Why: replayable, logged literature searches for /lit-review and /scope; mechanical BibTeX from
paper ids for /write-paper (no hand-typed entries); zero-assumption citation verification for
/review-paper (every bib entry checked against the real record; retractions via OpenAlex
`is_retracted`); and a cite-from-lit-review lint. LLM-free-generated citations are fabricated at
~18% (GPT-4 class) — generation and verification are mechanical, not optional.

BibTeX resolution chain — all KEYLESS except the optional S2 key: Semantic Scholar `citationStyles`
→ doi.org content-negotiation (`Accept: application/x-bibtex`) → Crossref transform → OpenAlex
(reconstructed from fields). arXiv ids resolve via their DataCite DOI (`10.48550/arXiv.<id>`). When a
paper has no usable id/DOI, the intended fallback is AGENTIC: web-search the title for its DOI, then
`s2.py bibtex DOI:<doi> --append <bibfile>` fills the entry and returns the cite-key — you supply the
DOI, the script does the rest. Never hand-type a BibTeX entry.

Keys (optional — keyless works, just rate-limited):
    S2_API_KEY        header x-api-key (free: semanticscholar.org/product/api)
    OPENALEX_API_KEY  param api_key (free account: openalex.org; required since 2026-02)

Exit codes (verify): 0 all verified · 2 title/year mismatches only · 1 not-found or retracted ·
3 BLOCKED (S2 unreachable for ≥1 entry — NOT evidence of a bad citation; retry).
Exit codes (search): 0 results (or a genuinely empty literature) · 3 BOTH backends
unreachable — an empty result then is NOT evidence of absence (matters for /lit-review's
novelty verdict).
Exit codes (citecheck): 0 every \\cite resolves to a bib entry AND a lit-review note · 1 a DANGLING
cite (no bib entry — LaTeX would fail) · 2 UNGROUNDED cite(s) (no lit-review note — confirm by hand).
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
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

S2 = "https://api.semanticscholar.org/graph/v1"
OPENALEX = "https://api.openalex.org"
FIELDS = "title,abstract,year,venue,citationCount,externalIds,authors.name,tldr"

# Sentinel: the request could not reach the backend (network error / non-404 HTTP / exhausted
# retries) — distinct from a successful-but-empty result (a dict) and from a 404 (None). "Unreachable"
# must NEVER be read as "this paper does not exist".
UNREACHABLE = object()


def http_get(url: str, retries: int = 4) -> dict | None:
    headers = {"User-Agent": "newts-lab-tools"}
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
            return UNREACHABLE
        except Exception as e:  # noqa: BLE001 — network tool, report and move on
            print(f"[s2] {e}", file=sys.stderr)
            return UNREACHABLE
    return UNREACHABLE


def http_get_text(url: str, accept: str, retries: int = 4):
    """Like http_get but returns the raw response TEXT (for BibTeX content-negotiation endpoints).
    Same sentinels: a str on success, None on 404, UNREACHABLE on a request failure."""
    headers = {"User-Agent": "newts-lab-tools", "Accept": accept}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep((2 ** attempt) + random.random())
                continue
            if e.code == 404:
                return None
            print(f"[s2] HTTP {e.code} for {url}", file=sys.stderr)
            return UNREACHABLE
        except Exception as e:  # noqa: BLE001
            print(f"[s2] {e}", file=sys.stderr)
            return UNREACHABLE
    return UNREACHABLE


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
    papers = (data.get("data") if isinstance(data, dict) else None) or []

    if not papers:  # S2 empty or unreachable -> OpenAlex
        print("[s2] no S2 results/unreachable — falling back to OpenAlex", file=sys.stderr)
        oa = http_get(openalex_url("/works", {"search": args.query, "per-page": args.limit,
                                              "select": "title,publication_year,doi,cited_by_count,primary_location"}))
        # Distinguish a genuine empty literature from both backends being unreachable: http_get returns
        # UNREACHABLE on a request failure and a dict (possibly with an empty list) on a real hit.
        if data is UNREACHABLE and oa is UNREACHABLE:
            print("\n**BOTH BACKENDS UNREACHABLE — this empty result is NOT evidence of "
                  "absence.** Do not issue a novelty verdict from it; record the search as "
                  "blocked and retry, or fall back to web search.", flush=True)
            return 3
        for w in (oa.get("results") if isinstance(oa, dict) else None) or []:
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

def _doi_of(paper_id: str) -> str | None:
    """A DOI the keyless fallbacks can use. arXiv ids map to their DataCite DOI; a bare 10.* is a DOI."""
    pid = paper_id.strip()
    low = pid.lower()
    if low.startswith("doi:"):
        return pid[4:].strip() or None
    if low.startswith("arxiv:"):
        arxiv = pid[6:].strip()
        return f"10.48550/arXiv.{arxiv}" if arxiv else None
    if low.startswith("10."):
        return pid
    return None


def _bib_key(bib: str) -> str:
    m = re.search(r"@\w+\s*\{\s*([^,\s]+)", bib)
    return m.group(1).strip() if m else ""


def bibtex_from_doi_org(doi: str):
    """DOI content negotiation — the registrar (Crossref/DataCite) returns the record AS BibTeX."""
    return http_get_text(f"https://doi.org/{urllib.parse.quote(doi, safe='/')}", "application/x-bibtex")


def bibtex_from_crossref(doi: str):
    return http_get_text(
        f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}/transform/application/x-bibtex",
        "application/x-bibtex")


def bibtex_from_openalex(doi: str):
    """Last resort: reconstruct a BibTeX entry from OpenAlex fields when no source ships a ready one."""
    work = http_get(openalex_url(f"/works/https://doi.org/{urllib.parse.quote(doi, safe='/')}",
                                 {"select": "title,authorships,publication_year,primary_location,type"}))
    if not isinstance(work, dict) or not work.get("title"):
        return work if work is UNREACHABLE else None
    authors = [a for a in ((au.get("author") or {}).get("display_name", "")
                           for au in (work.get("authorships") or [])) if a]
    year = work.get("publication_year") or ""
    venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    first_last = re.sub(r"[^a-z]", "", authors[0].split()[-1].lower()) if authors else "anon"
    first_word = next((w for w in re.findall(r"[a-z0-9]+", work["title"].lower()) if len(w) > 3), "ref")
    key = f"{first_last}{year}{first_word}"

    def _lastfirst(name: str) -> str:
        parts = name.split()
        return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else name

    author_field = " and ".join(_lastfirst(a) for a in authors) or "Unknown"
    etype = "article" if work.get("type") in (None, "article", "journal-article") else "misc"
    lines = [f"@{etype}{{{key},", f"  title = {{{work['title']}}},", f"  author = {{{author_field}}},"]
    if year:
        lines.append(f"  year = {{{year}}},")
    if venue:
        lines.append(f"  journal = {{{venue}}},")
    lines += [f"  doi = {{{doi}}},", "}"]
    return "\n".join(lines)


def _append_bib(path: str, bib: str, key: str) -> str:
    """Append the entry unless its key OR doi is already present (dedup). Returns 'added' | 'present'."""
    p = Path(path)
    existing = p.read_text(encoding="utf-8-sig") if p.exists() else ""
    present = parse_bib(existing)
    parsed_new = parse_bib(bib)
    new_doi = (parsed_new[0].get("doi") or "").lower() if parsed_new else ""
    if key in {e["key"] for e in present} or \
            (new_doi and new_doi in {(e.get("doi") or "").lower() for e in present if e.get("doi")}):
        return "present"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(bib.rstrip() + "\n")
    return "added"


def cmd_bibtex(args) -> int:
    bib = None
    # 1. Semantic Scholar (paperId / arXiv: / DOI: all resolve here) — ships a clean BibTeX string.
    data = http_get(f"{S2}/paper/{urllib.parse.quote(args.paper_id)}?fields=citationStyles,title")
    if isinstance(data, dict):
        bib = (data.get("citationStyles") or {}).get("bibtex")
    # 2-4. keyless DOI fallbacks when S2 is down / keyless-throttled / has no bibtex for the id.
    doi = _doi_of(args.paper_id)
    if not bib and doi:
        for src in (bibtex_from_doi_org, bibtex_from_crossref, bibtex_from_openalex):
            r = src(doi)
            if isinstance(r, str) and r.lstrip().startswith("@"):
                bib = r
                break
    if not bib:
        print(f"no bibtex for {args.paper_id} via S2 / doi.org / Crossref / OpenAlex", file=sys.stderr)
        if not doi:
            print("  → no DOI in the id. AGENTIC FALLBACK: web-search the paper title for its DOI, then\n"
                  "    uv run --with pyyaml python tools/s2.py bibtex DOI:<doi> --append <references.bib>",
                  file=sys.stderr)
        return 1
    bib = bib.strip()
    key = _bib_key(bib)
    if args.append:
        status = _append_bib(args.append, bib, key)
        print(f"cite-key: {key}")                                   # stdout: the \cite{...} key
        print(f"[{status}] {args.append}", file=sys.stderr)
        return 0
    print(bib)                                                      # stdout: the entry (for capture)
    print(f"\ncite-key: {key}", file=sys.stderr)                    # stderr: the \cite{...} key
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
    """True/False when OpenAlex could be read; None when the status is UNKNOWN (DOI not found or
    OpenAlex unreachable). Callers must not treat None as 'not retracted'. The DOI is quoted (safe='/'
    keeps the registrant/object slash) so spaces/parens in messy .bib DOIs don't break the request."""
    work = http_get(openalex_url(f"/works/https://doi.org/{urllib.parse.quote(doi, safe='/')}",
                                 {"select": "is_retracted"}))
    return bool(work.get("is_retracted")) if isinstance(work, dict) else None


def cmd_verify(args) -> int:
    with open(args.bibfile, encoding="utf-8-sig") as f:
        text = f.read()
    entries = parse_bib(text)
    if not entries:
        print("no bib entries found")
        return 0

    print(f"## Citation verification — {args.bibfile} ({len(entries)} entries, "
          f"threshold {args.threshold})\n")
    print("| key | status | detail |")
    print("|---|---|---|")
    worst = 0
    blocked = False
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
        if match is UNREACHABLE:
            # NOT a fabricated/missing citation — S2 just couldn't be reached. Mirror cmd_search:
            # an unreachable backend is never evidence of absence. Reported as exit 3 (blocked).
            print(f"| {e['key']} | BLOCKED | S2 unreachable — verification could not run |")
            blocked = True
            continue
        found = (match.get("data") if isinstance(match, dict) else None) or \
                ([match] if isinstance(match, dict) and match.get("title") else [])
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
        retr_note = ""
        if doi:
            retracted = check_retracted(doi)
            if retracted is True:
                print(f"| {e['key']} | **RETRACTED** | OpenAlex is_retracted=true |")
                worst = max(worst, 2)
                continue
            if retracted is None:   # unknown (OpenAlex unreachable / no key) — surface it, don't fail
                retr_note = " · retraction check unavailable"
        if notes:
            print(f"| {e['key']} | MISMATCH | {'; '.join(notes)}{retr_note} |")
            worst = max(worst, 1)
        else:
            print(f"| {e['key']} | verified | sim {ratio:.2f}{retr_note} |")

    if blocked:
        print("\n**S2 UNREACHABLE for one or more entries — verification BLOCKED, not failed. Retry; "
              "do not treat this as fabricated/missing citations.**", flush=True)
        return 3
    return {0: 0, 1: 2, 2: 1}[worst]


# ── citecheck (cite-from-lit-review lint) ────────────────────────────────────

CITE_RE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]+)\}")


def _grounded(entry: dict, lit_norm: str, lit_raw: str, threshold: float = 0.7) -> bool:
    """Is this cited paper present in the lit-review? Strong signal: its DOI or arXiv id appears
    verbatim; else ≥`threshold` of the title's content words (>3 chars) appear in the notes."""
    doi = (entry.get("doi") or "").lower()
    if doi and doi in lit_raw:
        return True
    arxiv = (entry.get("eprint") or "").lower()
    if arxiv and arxiv in lit_raw:
        return True
    title = normalize(entry.get("title", ""))
    toks = [w for w in title.split() if len(w) > 3] or title.split()
    return bool(toks) and sum(1 for w in toks if w in lit_norm) / len(toks) >= threshold


def cmd_citecheck(args) -> int:
    paper = Path(args.paper_dir)
    texs = sorted(paper.glob("*.tex"))
    if not texs:
        print(f"no .tex files in {paper}", file=sys.stderr)
        return 1
    cited: dict[str, str] = {}
    for t in texs:
        for m in CITE_RE.finditer(t.read_text(encoding="utf-8-sig")):
            for k in (x.strip() for x in m.group(1).split(",")):
                if k:
                    cited.setdefault(k, t.name)
    bibfile = Path(args.bib) if args.bib else (paper / "references.bib")
    entries = {e["key"]: e for e in parse_bib(bibfile.read_text(encoding="utf-8-sig"))} \
        if bibfile.exists() else {}
    lit_path = Path(args.lit_review) if args.lit_review else (paper.parent / "lit-review.md")
    lit_raw = lit_path.read_text(encoding="utf-8-sig").lower() if lit_path.exists() else ""
    lit_norm = normalize(lit_raw)
    threshold = getattr(args, "threshold", 0.7)

    print(f"## Cite-from-lit-review — {paper} ({len(cited)} cite keys, {len(entries)} bib entries, "
          f"lit-review {'found' if lit_raw else 'MISSING'})\n")
    print("| cite key | status | detail |")
    print("|---|---|---|")
    dangling = ungrounded = 0
    for key in sorted(cited):
        if key not in entries:
            print(f"| {key} | **DANGLING** | \\cite in {cited[key]} has no references.bib entry |")
            dangling += 1
        elif not lit_raw:
            print(f"| {key} | UNGROUNDED | lit-review.md not found at {lit_path} |")
            ungrounded += 1
        elif not _grounded(entries[key], lit_norm, lit_raw, threshold):
            print(f"| {key} | UNGROUNDED | no lit-review note matches \"{entries[key].get('title', '')[:60]}\" |")
            ungrounded += 1
        else:
            print(f"| {key} | verified | |")
    orphans = sorted(set(entries) - set(cited))
    if orphans:
        print(f"\n_{len(orphans)} bib entries never \\cite'd (informational): "
              f"{', '.join(orphans[:8])}{' …' if len(orphans) > 8 else ''}_")
    if dangling:
        print(f"\n**{dangling} DANGLING cite(s) — no references.bib entry (LaTeX would fail). FAIL.**", flush=True)
        return 1
    if ungrounded:
        print(f"\n**{ungrounded} UNGROUNDED cite(s) — cited but no lit-review note. Add the paper to "
              "lit-review.md (with a note) or cut the citation; confirm each by hand.**", flush=True)
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("query"); p.add_argument("--limit", type=int, default=10)
    p.add_argument("--year"); p.add_argument("--bulk", action="store_true")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("bibtex")
    p.add_argument("paper_id", help="S2 paperId, arXiv:NNNN.NNNNN, DOI:..., or a bare 10.* DOI")
    p.add_argument("--append", help="append the resolved entry to this references.bib (dedup) and print the cite-key")
    p.set_defaults(fn=cmd_bibtex)
    p = sub.add_parser("verify")
    p.add_argument("bibfile"); p.add_argument("--threshold", type=float, default=0.85)
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("citecheck")
    p.add_argument("paper_dir", help="studies/<slug>/paper")
    p.add_argument("--bib", help="references.bib (default <paper_dir>/references.bib)")
    p.add_argument("--lit-review", dest="lit_review", help="lit-review.md (default <paper_dir>/../lit-review.md)")
    p.add_argument("--threshold", type=float, default=0.7,
                   help="title-word overlap to call a cite 'grounded' (lab writing.cite_grounding_threshold)")
    p.set_defaults(fn=cmd_citecheck)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
