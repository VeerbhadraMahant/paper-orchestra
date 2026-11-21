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
    sfs = [c["subfield"] for c in s1]
    assert sorted(sfs[:3]) == ["A", "B", "C"] and sfs[3:] == sfs[:2]  # round-robin in a fixed (seeded) subfield order
    s, log = draw(pool(), n=10)
    assert len(s) == 6 and all(sum(c["subfield"] == sf for c in s) == 2 for sf in "ABC")  # cap 2
    assert "only 6 of 10" in log[-1]


def test_draw_seed_changes_order():
    big = [cand(f"x{k:02d}") for k in range(20)]
    assert [c["arxiv_id"] for c in draw(big, n=2, seed=1)[0]] != [c["arxiv_id"] for c in draw(big, n=2, seed=2)[0]]


def test_draw_subfield_independent_and_order_seeded():
    # a subfield's own order does not change when another subfield is added
    base = [cand(f"A{k:02d}", sf="A") for k in range(10)]
    only = [c["arxiv_id"] for c in draw(base, n=2, per_subfield_cap=2)[0]]
    both = [c["arxiv_id"] for c in draw(base + [cand("B00", sf="B")], n=3, per_subfield_cap=2)[0] if c["subfield"] == "A"]
    assert only == both
    orders = {tuple(c["subfield"] for c in draw([cand(f"{sf}{k}", sf=sf) for sf in "ABCDEF" for k in range(2)],
                                                n=6, seed=s)[0]) for s in range(30)}
    assert len(orders) > 1  # not always alphabetical


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


def test_gzip_bomb_rejected(tmp_path):
    bomb = gzip.compress(b"\x00" * (50 * 1024 * 1024))
    with pytest.raises(ValueError, match="exceeds"):
        extract_eprint(bomb, tmp_path / "b", max_bytes=10 * 1024 * 1024)
    assert not (tmp_path / "b").exists()


def test_tar_size_and_member_caps(tmp_path):
    data = make_tar([("a.tex", "file", b"x" * 100), ("b.tex", "file", b"x" * 100)], mode="w:")
    with pytest.raises(ValueError, match="exceed"):
        extract_eprint(data, tmp_path / "s", max_bytes=150)
    with pytest.raises(ValueError, match="more than"):
        extract_eprint(data, tmp_path / "m", max_members=1)
    assert extract_eprint(data, tmp_path / "ok", max_bytes=200, max_members=2) == "tar"


@pytest.mark.parametrize("name", ["a:b.tex", "dir/C:evil.tex", "a\\b.tex", "CON", "nul.txt", "sub/aux.tex",
                                  "com1.tex", "Lpt9", "x/PRN.y.tex"])
def test_extract_rejects_windows_names(tmp_path, name):
    with pytest.raises(ValueError):
        extract_eprint(make_tar([("ok.tex", "file", b"x"), (name, "file", b"x")]), tmp_path / "o")
    assert not (tmp_path / "o").exists()
