"""Tests for tools/s2.py — the literature helper.

Network paths (S2/doi.org/Crossref/OpenAlex) are NOT hit; we test the pure logic: DOI/key
parsing, the keyless bibtex fallback CHAIN (with http_get/http_get_text monkeypatched), the
--append dedup, and the cite-from-lit-review lint over fixture files. Hermetic.
"""

from __future__ import annotations

import types

from conftest import load


def _m():
    return load("s2")


# ── _doi_of / _bib_key ─────────────────────────────────────────────────────────

def test_doi_of_forms():
    m = _m()
    assert m._doi_of("DOI:10.1/abc") == "10.1/abc"
    assert m._doi_of("doi: 10.2/x ") == "10.2/x"
    assert m._doi_of("arXiv:2504.08066") == "10.48550/arXiv.2504.08066"   # DataCite DOI for arXiv
    assert m._doi_of("10.5/y") == "10.5/y"
    assert m._doi_of("649fa0b3c1") is None                                 # a bare S2 paperId has no DOI


def test_bib_key():
    m = _m()
    assert m._bib_key("@article{vaswani2017, title={x}}") == "vaswani2017"
    assert m._bib_key("@inproceedings{ a_b:c , year=2020}") == "a_b:c"
    assert m._bib_key("not an entry") == ""


# ── bibtex fallback chain (no network) ─────────────────────────────────────────

def test_bibtex_falls_back_to_doi_org_when_s2_empty(monkeypatch):
    m = _m()
    monkeypatch.setattr(m, "http_get", lambda url, **k: {"citationStyles": {}})   # S2 has no bibtex
    calls = []

    def fake_text(url, accept, retries=4):
        calls.append(url)
        return "@article{foo2020, title={T}}" if "doi.org" in url else m.UNREACHABLE

    monkeypatch.setattr(m, "http_get_text", fake_text)
    rc = m.cmd_bibtex(types.SimpleNamespace(paper_id="DOI:10.1/foo", append=None))
    assert rc == 0
    assert any("doi.org" in u for u in calls)                                       # the keyless fallback fired


def test_bibtex_no_doi_returns_1_with_agentic_hint(monkeypatch, capsys):
    m = _m()
    monkeypatch.setattr(m, "http_get", lambda url, **k: {"citationStyles": {}})     # S2 miss
    # a bare paperId yields no DOI, so the fallbacks can't run -> exit 1 + the websearch→DOI hint
    rc = m.cmd_bibtex(types.SimpleNamespace(paper_id="649fa0b3c1", append=None))
    assert rc == 1
    assert "AGENTIC FALLBACK" in capsys.readouterr().err


def test_bibtex_append_dedups_by_key_and_doi(tmp_path, monkeypatch):
    m = _m()
    monkeypatch.setattr(
        m, "http_get",
        lambda url, **k: {"citationStyles": {"bibtex": "@article{key2020, title={T}, doi={10.1/x}}"}})
    f = tmp_path / "references.bib"
    rc = m.cmd_bibtex(types.SimpleNamespace(paper_id="arXiv:1234.5678", append=str(f)))
    assert rc == 0 and "key2020" in f.read_text(encoding="utf-8")
    # second call: same key/doi -> not duplicated
    m.cmd_bibtex(types.SimpleNamespace(paper_id="arXiv:1234.5678", append=str(f)))
    assert f.read_text(encoding="utf-8").count("@article{key2020") == 1


def test_append_bib_dedup_by_doi_under_different_key(tmp_path):
    m = _m()
    f = tmp_path / "references.bib"
    assert m._append_bib(str(f), "@article{a2020, title={T}, doi={10.1/x}}", "a2020") == "added"
    assert m._append_bib(str(f), "@article{b2021, title={T2}, doi={10.1/x}}", "b2021") == "present"   # same DOI
    assert m._append_bib(str(f), "@article{c2022, title={T3}, doi={10.9/z}}", "c2022") == "added"


# ── citecheck (cite-from-lit-review) ───────────────────────────────────────────

def test_cite_re_matches_variants():
    m = _m()
    keys: set[str] = set()
    for txt in [r"\cite{a,b}", r"\citep[see][p.2]{c}", r"\citet{d}", r"\citeauthor{e}", r"\textcite{f}"]:
        for mm in m.CITE_RE.finditer(txt):
            keys |= {x.strip() for x in mm.group(1).split(",")}
    assert {"a", "b", "c", "d", "e", "f"} <= keys


def test_grounded_by_title_and_id():
    m = _m()
    lit_raw = "we build on attention is all you need (arxiv:1706.03762) for the encoder.".lower()
    lit_norm = m.normalize(lit_raw)
    assert m._grounded({"title": "Attention Is All You Need"}, lit_norm, lit_raw)        # title overlap
    assert m._grounded({"title": "x", "eprint": "1706.03762"}, lit_norm, lit_raw)        # id match
    assert m._grounded({"title": "A Totally Unrelated Paper Nobody Reviewed"}, lit_norm, lit_raw) is False


def test_citecheck_dangling_is_fail(tmp_path):
    m = _m()
    paper = tmp_path / "studies" / "demo" / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text(r"intro \cite{good} and \cite{bad}.", encoding="utf-8")
    (paper / "references.bib").write_text("@article{good, title={Attention Is All You Need}}\n", encoding="utf-8")
    (paper.parent / "lit-review.md").write_text("note on Attention Is All You Need.", encoding="utf-8")
    rc = m.cmd_citecheck(types.SimpleNamespace(paper_dir=str(paper), bib=None, lit_review=None))
    assert rc == 1                                                                       # 'bad' has no bib entry


def test_citecheck_ungrounded_is_warn(tmp_path):
    m = _m()
    paper = tmp_path / "studies" / "demo" / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text(r"\cite{ungrounded}", encoding="utf-8")
    (paper / "references.bib").write_text("@article{ungrounded, title={Unrelated Title Never Reviewed}}\n",
                                          encoding="utf-8")
    (paper.parent / "lit-review.md").write_text("nothing relevant here.", encoding="utf-8")
    rc = m.cmd_citecheck(types.SimpleNamespace(paper_dir=str(paper), bib=None, lit_review=None))
    assert rc == 2                                                                       # in bib, not in lit-review


def test_citecheck_all_grounded_passes(tmp_path):
    m = _m()
    paper = tmp_path / "studies" / "demo" / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text(r"\citep{good}", encoding="utf-8")
    (paper / "references.bib").write_text("@article{good, title={Scaling Laws For Language Models}}\n",
                                          encoding="utf-8")
    (paper.parent / "lit-review.md").write_text("we cite Scaling Laws for Language Models throughout.",
                                                 encoding="utf-8")
    rc = m.cmd_citecheck(types.SimpleNamespace(paper_dir=str(paper), bib=None, lit_review=None))
    assert rc == 0
