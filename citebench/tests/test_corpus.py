import gzip
import io
import tarfile

import pytest

from citebench.corpus import draw, eligible, extract_eprint


def cand(i, sf="LLM", year=2023, refs=150):
    return {"arxiv_id": i, "subfield": sf, "year": year, "ref_count": refs}


def test_eligible_reasons():
    ok, ex = eligible([cand("a"), cand("b", year=2021), cand("c", year=2027), cand("d", refs=None),
                       cand("e", refs=99), cand("f"), cand("g", refs=100)], exclude_ids={"f"})
    assert [c["arxiv_id"] for c in ok] == ["a", "g"]
    assert dict(ex) == {"b": "year_out_of_range", "c": "year_out_of_range", "d": "ref_count_unverified",
                        "e": "ref_count_below_100", "f": "excluded"}


def pool():
    return [cand(f"{sf}{k}", sf=sf) for sf in ("A", "B", "C") for k in range(4)]


def test_draw_deterministic_cap_and_round_robin():
    s1, _ = draw(pool(), n=5)
    s2, _ = draw(list(reversed(pool())), n=5)
    assert [c["arxiv_id"] for c in s1] == [c["arxiv_id"] for c in s2]
    assert [c["subfield"] for c in s1] == ["A", "B", "C", "A", "B"]  # round-robin in sorted subfield order
    s, log = draw(pool(), n=10)
    assert len(s) == 6 and all(sum(c["subfield"] == sf for c in s) == 2 for sf in "ABC")  # cap 2
    assert "only 6 of 10" in log[-1]


def test_draw_seed_changes_order():
    big = [cand(f"x{k:02d}") for k in range(20)]
    assert [c["arxiv_id"] for c in draw(big, n=2, seed=1)[0]] != [c["arxiv_id"] for c in draw(big, n=2, seed=2)[0]]


def make_tar(members, mode="w:gz"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tf:
        for name, kind, data in members:
            ti = tarfile.TarInfo(name)
            if kind == "file":
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            elif kind == "sym":
                ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tf.addfile(ti)
            elif kind == "hard":
                ti.type, ti.linkname = tarfile.LNKTYPE, "a.tex"
                tf.addfile(ti)
    return buf.getvalue()


def test_extract_tar_ok(tmp_path):
    data = make_tar([("main.tex", "file", b"x"), ("sub/refs.bib", "file", b"y")])
    assert extract_eprint(data, tmp_path / "o") == "tar"
    assert (tmp_path / "o" / "sub" / "refs.bib").read_bytes() == b"y"


@pytest.mark.parametrize("members", [
    [("../evil.tex", "file", b"x")],
    [("/abs/evil.tex", "file", b"x")],
    [("a/../../evil.tex", "file", b"x")],
    [("link.tex", "sym", b"")],
    [("link.tex", "hard", b"")],
])
def test_extract_rejects_unsafe(tmp_path, members):
    with pytest.raises(ValueError):
        extract_eprint(make_tar([("ok.tex", "file", b"x")] + members), tmp_path / "o")
    assert not (tmp_path / "o").exists()  # validated before writing
    assert not (tmp_path / "evil.tex").exists()


def test_single_gzip_and_pdf(tmp_path):
    assert extract_eprint(gzip.compress(b"\\documentclass{article}"), tmp_path / "s") == "single_tex"
    assert (tmp_path / "s" / "main.tex").read_bytes() == b"\\documentclass{article}"
    assert extract_eprint(b"%PDF-1.5 ...", tmp_path / "p") == "no_tex_source"
    assert extract_eprint(gzip.compress(b"%PDF-1.5 ..."), tmp_path / "q") == "no_tex_source"
    assert not (tmp_path / "p").exists()


def test_tar_without_tex(tmp_path):
    assert extract_eprint(make_tar([("fig.png", "file", b"x")]), tmp_path / "n") == "no_tex_source"
