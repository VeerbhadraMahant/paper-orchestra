# CiteBench (work in progress)

Benchmark and study of citation claim-support checking. See `DESIGN.md` for the plan.

## Layout

- `citebench/units.py`: shared data contract (Unit, Reference, SourceRecord) and JSONL I/O.
- `citebench/extract.py`: arXiv LaTeX source (.tex + .bib/.bbl) to citing-sentence units.
- `citebench/fetch.py`: free source text per cited reference (arXiv, Semantic Scholar, OpenAlex), cached and resumable. No API keys, no contact details sent.
- `tests/`: pytest suite. Network calls are stubbed; tests never hit the internet.
- Docs: `DESIGN.md` (plan), `PROTOCOL.md` (pre-registered protocol), `DECISIONS.md` (resolved open items), `ANNOTATION_GUIDELINES.md`, `CORPUS_CANDIDATES.md`, `SMOKE.md` (real-data checks).

## Usage

```
python -m citebench.extract <arxiv_source_dir> --survey-id <arxiv_id> --out units.jsonl
python -m citebench.fetch units.jsonl --out sources.jsonl --cache .cache/citebench
python -m citebench.evaluate --gold gold.jsonl --pred preds.jsonl --by condition [--compare] [--e3] [--json out.json]
```

## Run tests

```
python -m pytest
```

This project lives inside a fork of google-research/paper-orchestra (Apache 2.0). CiteBench code is new and does not modify PaperOrchestra's code.
