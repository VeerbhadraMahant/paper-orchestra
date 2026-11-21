import subprocess
import sys
from pathlib import Path

import pytest

from citebench import extract as ex
from citebench.extract import extract, main, parse_bbl
from citebench.units import Unit, make_unit_id, read_jsonl

FIX = Path(__file__).parent / "fixtures" / "extract"
ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def multi():
    return extract(FIX / "multi", "2401.00001")


def by_latex(units, needle):
    return [u for u in units if needle in u.sentence_latex]


def check_offsets(root, units):
    for u in units:
        text = (Path(root) / u.source_file).read_bytes().decode("utf-8", errors="replace")
        assert text[u.char_start : u.char_end] == u.sentence_latex


def run(tmp_path, body):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n", encoding="utf-8"
    )
    units, stats = extract(tmp_path, "x")
    check_offsets(tmp_path, units)
    return units, stats


def tex_project(tmp_path, body):
    return run(tmp_path, body)[0]


def test_multifile_and_offsets(multi):
    units, stats = multi
    assert {u.source_file for u in units} == {"main.tex", "sections/body.tex", "sections/extra.tex"}
    for u in units:
        text = (FIX / "multi" / u.source_file).read_bytes().decode("utf-8", errors="replace")
        assert text[u.char_start : u.char_end] == u.sentence_latex
        assert u.unit_id == make_unit_id("2401.00001", u.source_file, u.char_start, u.cite_key)
        assert u.sentence_latex == u.sentence_latex.strip()
    assert stats.files_read == 3
    assert stats.units == len(units) == 11
    assert stats.sentences_with_citations == 10
    assert stats.distinct_keys == 5
    assert stats.missing_keys == ["missing_key"]


def test_comments_ignored(multi):
    keys = {u.cite_key for u in multi[0]}
    assert not keys & {"ghost", "ghost2", "preamble"}
    u = [u for u in multi[0] if u.cite_key == "delta" and "comment test" in u.sentence_latex]
    assert len(u) == 1 and "ghost2" not in u[0].sentence_text


def test_abbreviations_do_not_split(multi):
    units = multi[0]
    assert by_latex(units, "Smith et al.")[0].sentence_latex == "Smith et al. \\cite{gamma} agree."
    assert by_latex(units, "Prior work, e.g.")[0].sentence_latex.endswith("showed gains.")
    assert by_latex(units, "Then Eq. 3 (cf.")[0].cite_key == "gamma"
    assert by_latex(units, "We follow Fig. 2")[0].sentence_latex == "We follow Fig. 2 of \\cite{beta}."


def test_inline_math_not_split(multi):
    u = by_latex(multi[0], "$x = 1.5. Next$")
    assert len(u) == 1 and u[0].cite_key == "alpha"  # \citet* starred form


def test_multikey_optional_args(multi):
    us = by_latex(multi[0], "Prior work, e.g.")
    assert [(u.cite_key, u.cocited_keys) for u in us] == [("alpha", ["beta"]), ("beta", ["alpha"])]
    assert us[0].sentence_text == "Prior work, e.g. [CITE], showed gains."


def test_repeated_key_single_unit(multi):
    us = by_latex(multi[0], "Repeated")
    assert len(us) == 1 and us[0].cocited_keys == []


def test_nocite_figure_caption_skipped(multi):
    keys = {u.cite_key for u in multi[0]}
    assert not keys & {"nokey", "figkey", "capkey"}
    assert by_latex(multi[0], "text continues")[0].sentence_latex == "text continues \\cite{delta}."


def test_sections(multi):
    sec = {u.sentence_latex[:12]: u.section for u in multi[0]}
    assert sec["Prior work, "] == "Introduction"
    assert sec["We follow Fi"] == "Methods"
    assert sec["New paragrap"] == "Sub part"
    assert sec["Extra file s"] == "Deep"
    assert sec["text continu"] == "Deep"


def test_reference_fields(multi):
    refs = {u.cite_key: u.reference for u in multi[0]}
    a, b, g, d = refs["alpha"], refs["beta"], refs["gamma"], refs["delta"]
    assert a.title == "BERT: Pre-training of Deep Models" and a.year == 2020 and a.venue == "Journal of Tests"
    assert a.authors == ["Doe, Jane", "Roe, Rick", "Big Lab"]
    assert a.arxiv_id == "2001.01234"  # from eprint
    assert b.arxiv_id == "2301.00001" and b.title == "A Study of M\u00fcller Things"  # from journal text
    assert g.doi == "10.1000/xyz123" and g.arxiv_id == "2105.12345" and g.venue == "Proc. of Testing"
    assert d.arxiv_id == "2202.03333" and d.year is None and d.venue is None
    assert a.raw.startswith("@article{alpha,") and refs["missing_key"] is None


def test_bbl_only():
    units, stats = extract(FIX / "bblonly", "2402.00002")
    s, j = (u.reference for u in units)
    assert s.title == "A neural thing for Testing" and s.arxiv_id == "2003.04567" and s.year == 2020
    assert s.authors == [] and s.raw.startswith("\\bibitem[Smith") and "newblock" in s.raw
    assert j.title == "Another title, with comma" and j.doi == "10.1234/abc.567" and j.year == 2019
    assert units[0].cocited_keys == ["jones19"] and stats.missing_keys == []


def test_bbl_without_newblock_leaves_title_none():
    r = parse_bbl("\\begin{thebibliography}{1}\n\\bibitem{k} Someone, A thing, 2020.\n\\end{thebibliography}")["k"]
    assert r.title is None and r.raw.startswith("\\bibitem{k}")


def test_bib_parse_error_reported_not_fatal(tmp_path, monkeypatch):
    (tmp_path / "main.tex").write_text("\\documentclass{a}\\begin{document}A \\cite{k}.\\end{document}")
    (tmp_path / "bad.bib").write_text("@article{k, title={x}}")

    def boom(text):
        raise ValueError("broken")

    monkeypatch.setattr(ex, "parse_bib", boom)
    units, stats = extract(tmp_path, "x")
    assert len(units) == 1 and units[0].reference is None
    assert stats.bib_errors and "bad.bib" in stats.bib_errors[0]


def test_garbage_bytes_do_not_crash(tmp_path):
    (tmp_path / "main.tex").write_text("\\documentclass{a}\\begin{document}A \\cite{k}.\\end{document}")
    (tmp_path / "bad.bib").write_bytes(b"@article{k, title={unterminated\xff\n")
    units, _ = extract(tmp_path, "x")
    assert len(units) == 1


def test_paragraph_and_comment_only_line(tmp_path):
    us = tex_project(
        tmp_path, "First para no period \\cite{a}\n\nSecond para \\cite{b}\n% only a comment\ncontinues here \\cite{c}."
    )
    assert us[0].sentence_latex == "First para no period \\cite{a}"
    assert us[1].sentence_latex.startswith("Second para") and us[1].cocited_keys == ["c"]


def test_pylatexenc_failure_falls_back(tmp_path, monkeypatch):
    def boom(s):
        raise RuntimeError

    monkeypatch.setattr(ex._L2T, "latex_to_text", boom)
    us = tex_project(tmp_path, "A \\textbf{bold} claim \\cite{a}.")
    assert us[0].sentence_text == "A bold claim [CITE]."


def test_missing_input_file_ignored(tmp_path):
    units, stats = run(tmp_path, "\\input{nope}\nHello \\cite{a}.")
    assert len(units) == 1 and stats.unresolved_includes == 1


def test_cli_end_to_end(tmp_path, capsys):
    out = tmp_path / "units.jsonl"
    assert main([str(FIX / "multi"), "--survey-id", "2401.00001", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "units: 11" in text and "distinct keys: 5" in text and "missing from bibliography: 1" in text
    back = list(read_jsonl(out, Unit))
    assert len(back) == 11 and back[0].reference is not None


def test_cli_module_entry(tmp_path):
    out = tmp_path / "u.jsonl"
    r = subprocess.run(
        [sys.executable, "-m", "citebench.extract", str(FIX / "bblonly"), "--survey-id", "s", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0 and "units: 2" in r.stdout and out.exists()


def test_cli_no_main(tmp_path):
    assert main([str(tmp_path), "--survey-id", "s", "--out", str(tmp_path / "o.jsonl")]) == 1


def test_escaped_percent_and_double_backslash_comment(tmp_path):
    us = tex_project(tmp_path, "Gain of 50\\% in \\cite{a}. Line end \\\\% ghost \\cite{ghost}\nNext \\cite{b}.")
    assert {u.cite_key for u in us} == {"a", "b"}


def test_include_outside_root_rejected_and_counted(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "x.tex").write_text("Leak \\cite{leak}.")
    absolute = (tmp_path / "x.tex").as_posix()
    units, stats = run(root, "\\input{../x}\n\\input{../../x}\n\\input{%s}\nOK \\cite{a}." % absolute)
    assert [u.cite_key for u in units] == ["a"] and stats.unresolved_includes == 3 and stats.files_read == 1


def test_list_items_are_separate_sentences(tmp_path):
    us = tex_project(
        tmp_path,
        "\\begin{itemize}\n\\item Alpha one \\cite{a}\n\\item Beta two \\cite{b}\n\\end{itemize}\n"
        "\\paragraph{Head} Third \\cite{c}",
    )
    assert [(u.cite_key, u.cocited_keys) for u in us] == [("a", []), ("b", []), ("c", [])]
    assert us[0].sentence_latex == "Alpha one \\cite{a}"


def test_closing_paren_then_uppercase_splits(tmp_path):
    us = tex_project(tmp_path, "As shown (see \\cite{a}.) Then more \\cite{b}.")
    assert [(u.sentence_latex, u.cocited_keys) for u in us] == [
        ("As shown (see \\cite{a}.)", []), ("Then more \\cite{b}.", [])]


def test_etc_splits_before_uppercase_only(tmp_path):
    us = tex_project(tmp_path, "We use X, etc. Then \\cite{a}. Also Y, etc. \\cite{b} holds.")
    assert [u.sentence_latex for u in us] == ["Then \\cite{a}.", "Also Y, etc. \\cite{b} holds."]


def test_more_cite_commands(tmp_path):
    us, stats = run(
        tmp_path,
        "One \\citeyearpar{a}. Two \\citenum{b}. Three \\cites{c}{d}. Four \\cite[see {[1]}]{e}. "
        "Five \\citetext{x}. Six \\cites[p.1][q]{f}[r]{g}.",
    )
    assert [(u.cite_key, u.cocited_keys) for u in us] == [
        ("a", []), ("b", []), ("c", ["d"]), ("d", ["c"]), ("e", []), ("f", ["g"]), ("g", ["f"])]
    assert stats.unmatched_cite_tokens == 0
    assert us[2].sentence_text == "Three [CITE]." and us[4].sentence_text == "Four [CITE]."


def test_unmatched_cite_token_counted(tmp_path):
    us, stats = run(tmp_path, "A \\citefoo{x} claim. B \\cite{a}. C \\cite without args.")
    assert [u.cite_key for u in us] == ["a"]
    assert stats.unmatched_cite_tokens == 2 and stats.unmatched_examples[0].startswith("\\citefoo")
    assert "unmatched cite tokens: 2" in stats.summary()


def test_unterminated_env_counted_rest_extracted(tmp_path):
    us, stats = run(tmp_path, "Before \\cite{b}.\n\\begin{figure}\nunclosed \\cite{lost}\n\nAfter para \\cite{a}.")
    assert {u.cite_key for u in us} == {"b", "a"}
    assert stats.unterminated_envs == 1 and stats.cites_in_skipped_regions == 1


def test_cites_in_skipped_regions_counted(tmp_path):
    _, stats = run(
        tmp_path, "\\section{On \\cite{t}}\nText \\cite{a}.\n\\begin{figure}\\caption{Cap \\cite{c}}\\end{figure}"
    )
    assert stats.cites_in_skipped_regions == 2  # section title + figure (its caption is inside, counted once)


def test_dotdot_path_deduplicated(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.tex").write_text("Hello \\cite{k}.")
    units, stats = run(tmp_path, "\\input{sub/../a}\n\\input{a}")
    assert len(units) == 1 and units[0].source_file == "a.tex" and stats.files_read == 2


def test_duplicate_bib_key_consistent(tmp_path):
    (tmp_path / "r.bib").write_text(
        "@article{k,\n title={First},\n year={2001}\n}\n@article{k,\n title={Second},\n year={2002}\n}\n"
    )
    units, stats = run(tmp_path, "Hi \\cite{k}.")
    r = units[0].reference
    assert r.title == "First" and r.year == 2001 and "First" in r.raw and "Second" not in r.raw
    assert stats.duplicate_bib_keys == ["k"]


def test_main_file_with_documentclass_in_input_header(tmp_path):
    from citebench.extract import extract
    (tmp_path / "hdr.tex").write_text(r"\documentclass{article}" + "\n", encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        "\n".join([r"\input{hdr}", r"\begin{document}", r"Transformers use attention \cite{v}.", r"\end{document}", ""]),
        encoding="utf-8")
    (tmp_path / "refs.bib").write_text("@article{v, title={Attention Is All You Need}, year={2017}}\n", encoding="utf-8")
    units, _ = extract(tmp_path, "s")
    assert [u.cite_key for u in units] == ["v"]
