# CiteBench (work in progress)

Benchmark and study of citation claim-support checking. See `DESIGN.md` for the plan.

## Layout

- `citebench/units.py`: shared data contract (Unit, Reference, SourceRecord) and JSONL I/O.
- `tests/`: pytest suite. Network calls are mocked; tests never hit the internet.

## Run tests

```
python -m pytest
```

This project lives inside a fork of google-research/paper-orchestra (Apache 2.0). CiteBench code is new and does not modify PaperOrchestra's code.
