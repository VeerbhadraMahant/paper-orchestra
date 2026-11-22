# CiteBench (work in progress)

Benchmark and study of citation claim-support checking. See `DESIGN.md` for the plan.

## Layout

- `citebench/units.py`: shared data contract (Unit, Reference, SourceRecord) and JSONL I/O.
- `citebench/corpus.py`: corpus selection (D1 to D7) and safe arXiv source download and extraction.
- `citebench/extract.py`: arXiv LaTeX source (.tex + .bib/.bbl) to citing-sentence units.
- `citebench/fetch.py`: free source text per cited reference (arXiv, Semantic Scholar, OpenAlex, ACL Anthology, Europe PMC), cached and resumable. No API keys, no contact details sent.
- `citebench/sample.py`: unit sampling (D8 to D10): provisional strata, capped stratified draw, finalisation, and `materialize` from the public manifest.
- `citebench/retrieval.py`: deterministic passage retrieval for the judge (chunking and a small TF-IDF).
- `citebench/judge.py`: judge harness: (unit, source) pairs to prompts under the experimental conditions, backends, validated predictions.
- `citebench/annotate.py`: offline annotation tooling: export a sheet and per-unit packets, validate, ingest, reliability pairs.
- `citebench/planted.py`: planted-set bookkeeping (D13 to D15): manages copies of sentences the author edits by hand.
- `citebench/evaluate.py`: metrics (PROTOCOL section 7).
- `citebench/report.py`: coverage report: access level by publication year, source and error breakdowns.
- `citebench/checks.py`: author spot checks on the benchmark itself (D18 wrong_related pairs).
- `tests/`: pytest suite. Network calls are stubbed; tests never hit the internet.
- Docs: `DESIGN.md` (plan), `PROTOCOL.md` (pre-registered protocol), `DECISIONS.md` (resolved open items), `ANNOTATION_GUIDELINES.md`, `CORPUS_CANDIDATES.md`, `SMOKE.md` (real-data checks).

## Usage

```
python -m citebench.extract <arxiv_source_dir> --survey-id <arxiv_id> --out units.jsonl
python -m citebench.fetch units.jsonl --out sources.jsonl --cache .cache/citebench
python -m citebench.corpus draw --candidates candidates.json --out selected.json [--n 10] [--seed S]
python -m citebench.corpus fetch-sources --selected selected.json --dest D
python -m citebench.corpus extract-all --selected selected.json --dest D --work W
python -m citebench.sample candidates --units-dir D --out candidates.jsonl
python -m citebench.sample finalize --candidates candidates.jsonl --sources sources.jsonl --out final.jsonl --manifest manifest.json
python -m citebench.sample materialize --manifest data/sample/manifest_v1.json --units-dir D --out units.jsonl
python -m citebench.judge build --units units.jsonl --sources sources.jsonl --cache .cache/citebench --out calls.jsonl --conditions correct,wrong_related
python -m citebench.judge run --units units.jsonl --sources sources.jsonl --cache .cache/citebench --calls calls.jsonl --backend claude_cli --model M --out preds.jsonl
python -m citebench.annotate export --units units.jsonl --sources sources.jsonl --cache .cache/citebench --out annot/
python -m citebench.annotate validate --sheet annot/sheet.csv
python -m citebench.annotate ingest --sheet annot/sheet.csv --units units.jsonl --sources sources.jsonl --cache .cache/citebench --out gold.jsonl
python -m citebench.annotate reliability --a gold_a.jsonl --b gold_b.jsonl --out pairs.json
python -m citebench.planted eligible --labels gold.jsonl --units units.jsonl
python -m citebench.planted template --labels gold.jsonl --units units.jsonl --out template.json --all-eligible
python -m citebench.planted build --template template.json --units units.jsonl --out planted.jsonl
python -m citebench.evaluate --gold gold.jsonl --pred preds.jsonl --by condition [--compare] [--e3] [--json out.json]
python -m citebench.report coverage --units units.jsonl --sources sources.jsonl [--json out.json]
python -m citebench.checks wrong-pairs export --calls calls.jsonl --units units.jsonl --sources sources.jsonl --cache .cache/citebench --n 20 --out sheet.csv
python -m citebench.checks wrong-pairs summarize --sheet sheet.csv
```

## Run tests

```
python -m pytest
```

This project lives inside a fork of google-research/paper-orchestra (Apache 2.0). CiteBench code is new and does not modify PaperOrchestra's code.
