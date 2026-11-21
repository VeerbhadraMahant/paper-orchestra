from citebench.retrieval import chunk, most_similar, tokenize, top_passages


def test_tokenize_lowercases_and_drops_stopwords():
    assert tokenize("The Diffusion-Models are 3D, and GANs!") == ["diffusion", "models", "3d", "gans"]


def test_chunk_size_overlap_and_determinism():
    paras = [f"Paragraph {i} " + ("word " * 60).strip() + "." for i in range(20)]
    text = "\n\n".join(paras)
    cs = chunk(text)
    assert len(cs) > 3
    assert all(len(c) <= 1200 for c in cs)
    for a, b in zip(cs, cs[1:]):
        # the next chunk starts with a suffix of the previous one, at most 200 characters long
        n = next(n for n in range(min(len(a), len(b)), 0, -1) if b.startswith(a[-n:]) and a[-n:][0] != " ")
        assert 0 < n <= 200
    assert chunk(text) == cs


def test_chunk_splits_long_paragraph_on_sentences_and_empty():
    sent = "This is a sentence about training. "
    cs = chunk(sent * 200)
    assert len(cs) > 1 and all(len(c) <= 1200 for c in cs)
    assert chunk("  \n\n ") == []
    assert chunk("short text") == ["short text"]


def test_top_passages_ranking_document_order_and_skip_first():
    filler = "unrelated material about cooking pasta and boiling water. " * 15
    texts = [f"{filler}", "federated learning with differential privacy noise " * 20, filler,
             "membership inference attack on diffusion models " * 20, filler]
    doc = "\n\n".join(texts)
    cs = chunk(doc)
    top = top_passages("membership inference attack diffusion", doc, k=1)
    assert len(top) == 1 and "membership" in top[0].text and top[0].score > 0
    two = top_passages("membership inference differential privacy", doc, k=2)
    assert [p.index for p in two] == sorted(p.index for p in two)
    skip = top_passages(cs[0], doc, k=3, skip_first=True)
    assert all(p.index != 0 for p in skip)
    assert top_passages("zzzz qqqq", doc) == []


def test_most_similar_ranks_and_ties_by_key():
    r = most_similar("graph neural networks", {"b": "graph neural networks survey", "a": "cooking recipes",
                                               "c": "graph neural networks survey"})
    assert [k for k, _ in r][:2] == ["b", "c"] and r[-1][0] == "a"
    assert most_similar("x", {}) == []
