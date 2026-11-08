# ScenarioMine (tool)

Collector, parser and query API for mining ASAM OpenSCENARIO (`.xosc`) files
and their Git history from open-source repositories. This repository contains
the **tool only**. It accompanies the paper *ScenarioMine: A Version-History
Dataset of ASAM OpenSCENARIO Files from Open-Source Repositories* (MSR 2027,
Data and Tool Showcase). The dataset itself is archived separately
(Zenodo DOI: _to be added_).

## What it does

```
data/repos.csv --collect--> raw/ --parse--> parsed/file_versions --evolve--> parsed/scenario_changes
                  (git history,     (normalised records,         (version-to-version
                   every .xosc       JSON Schema 0.2.2)           change records)
                   revision)
```

| Command | Purpose |
| --- | --- |
| `collect` | Clone each repository in `data/repos.csv` and archive every revision of every `.xosc` file. `--pin-from` re-collects at recorded commit SHAs for reproducibility. |
| `fetch-schemas` | Download the ASAM OpenSCENARIO XSDs into `schemas/` (needed for `validate`). |
| `parse` | Classify each file (scenario, catalogue, parameter distribution) and extract normalised records. |
| `evolve` | Link versions into lineages and emit `scenario_change` records. |
| `validate` | Check output rows against the JSON Schemas in `schema/`. |
| `qc`, `qc-sample` | Automated consistency checks and a sampler for manual spot-checking. |
| `find` | Search a parsed corpus by topic, weather, etc., reporting licence and a GitHub permalink. |
| `snapshot` | Freeze a repository inventory (`--inventory`, a CSV from the discovery step) into `data/repos.csv`. Not needed to reproduce a run. |

## Install

Python >= 3.10, `git` on the PATH.

```bash
pip install -r requirements.txt      # lxml, pyarrow, jsonschema, and the package itself
```

The collector uses only the standard library; `parse` and `evolve` need `lxml`;
Parquet output needs `pyarrow`.

## Quick start (no cloning)

The repo bundles a small pilot sample (five repositories, Parquet) in `data/sample/`.

```bash
python examples/quickstart.py
python -m scenariomine find --data data/sample --topic collision --limit 5
```

```python
from scenariomine import Dataset

ds = Dataset.load()                  # bundled sample; Dataset.load("parsed/") for a full run
ds.query(entity="vehicle", action="lane_change_action")
ds.history(scenario_id="...")
ds.changes(kind="parameters")
```

## Re-running the pipeline

```bash
# 1. Collect (slow for the full list; use --only to try one repository)
python -m scenariomine collect --jobs 4 --only esmini/esmini

# 2. Fetch the ASAM XSDs (not redistributed here, see Licensing)
python -m scenariomine fetch-schemas

# 3. Parse and link versions
python -m scenariomine parse --parquet
python -m scenariomine evolve --parquet

# 4. Validate and check
python -m scenariomine validate
python -m scenariomine validate --rows parsed/scenario_changes.jsonl \
    --schema schema/scenario_change.schema.json
python -m scenariomine qc
```

Output goes to `raw/` and `parsed/` (git-ignored). `data/repos.csv` is the
frozen repository list, with a licence class per repository; hand-checked
decisions are in `data/license_overrides.csv`. To rebuild the bundled sample
from a full `parsed/` run: `python scripts/make_sample.py`.

## Repository layout

```
scenariomine/    Python package (CLI entry point: python -m scenariomine)
schema/          JSON Schemas: scenario_version, scenario_change
data/            repos.csv, license_overrides.csv, sample/ (pilot Parquet)
examples/        quickstart.py
scripts/         make_sample.py
```

## Licensing

Each repository is classed `permissive`, `copyleft` or `review`. File
contents are republished only for permissive repositories; everything else is
a pointer (repository, commit SHA, path) plus extracted metadata. This is a
project policy, not legal advice. The bundled sample follows it.

The ASAM OpenSCENARIO XSDs are ASAM-licensed. `fetch-schemas` downloads them
on your machine; they are not included here.

The tool's own code licence: _to be added before release_.

## Citation

See `CITATION.cff`.
