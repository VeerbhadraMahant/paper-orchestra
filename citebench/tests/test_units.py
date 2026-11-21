from citebench.units import Reference, SourceRecord, Unit, make_unit_id, read_jsonl, write_jsonl


def test_roundtrip(tmp_path):
    ref = Reference(key="vaswani2017", title="Attention Is All You Need", authors=["A. Vaswani"], year=2017)
    u = Unit(
        unit_id=make_unit_id("2402.00001", "main.tex", 10, "vaswani2017"),
        survey_id="2402.00001",
        source_file="main.tex",
        char_start=10,
        char_end=60,
        section="Background",
        sentence_latex="Transformers \\cite{vaswani2017} use attention.",
        sentence_text="Transformers [CITE] use attention.",
        cite_key="vaswani2017",
        reference=ref,
    )
    p = tmp_path / "units.jsonl"
    assert write_jsonl(p, [u]) == 1
    assert list(read_jsonl(p, Unit)) == [u]

    s = SourceRecord(cite_key="vaswani2017", survey_id="2402.00001", access_level="none", error="not found")
    p2 = tmp_path / "src.jsonl"
    write_jsonl(p2, [s])
    assert list(read_jsonl(p2, SourceRecord)) == [s]


def test_unit_id_stable():
    assert make_unit_id("a", "b", 1, "k") == make_unit_id("a", "b", 1, "k")
    assert make_unit_id("a", "b", 1, "k") != make_unit_id("a", "b", 2, "k")
