# ScenarioMine (tool)

Collector, parser and query API for mining ASAM OpenSCENARIO (`.xosc`) files
and their Git history from open-source repositories. This repository contains
the **tool only**. It accompanies the paper *ScenarioMine: A Version-History
Dataset of ASAM OpenSCENARIO Files from Open-Source Repositories* (MSR 2027,
Data and Tool Showcase). The dataset is a separate artefact; this repository
holds only the tool that builds and queries it.

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

## The Claude Code skill

The paper's agent skill, `find-scenarios`, lives in `.claude/skills/find-scenarios/`.
It turns a natural-language testing need into matching scenarios, with the
evidence, licence and GitHub permalink of each match, and says plainly when the
corpus cannot answer. Open [Claude Code](https://claude.com/claude-code) in this
repository and it loads automatically.

```
/find-scenarios pedestrian crossing at night
```

It runs `scenariomine find` underneath and works on the bundled sample out of
the box. The same searches work without Claude:
`uv run python -m scenariomine find --data data/sample --topic near_miss`.

## Install

Requires [uv](https://docs.astral.sh/uv/) and `git` on the PATH. uv creates
the virtual environment (`.venv/`) and installs Python >= 3.10 and the
dependencies pinned in `uv.lock`.

```bash
uv sync --extra parquet --extra dev   # lxml, pyarrow, jsonschema, and the package itself
```

The collector uses only the standard library; `parse` and `evolve` need `lxml`;
Parquet output needs `pyarrow`. Run every command below through `uv run`, which
uses that environment; there is no need to activate it.

## Quick start (no cloning)

The repo bundles a small pilot sample (five repositories, Parquet) in `data/sample/`.

```bash
uv run python examples/quickstart.py
uv run python -m scenariomine find --data data/sample --topic collision --limit 5
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
uv run python -m scenariomine collect --jobs 4 --only esmini/esmini

# 2. Fetch the ASAM XSDs (not redistributed here, see Licensing)
uv run python -m scenariomine fetch-schemas

# 3. Parse and link versions
uv run python -m scenariomine parse --parquet
uv run python -m scenariomine evolve --parquet

# 4. Validate and check
uv run python -m scenariomine validate
uv run python -m scenariomine validate --rows parsed/scenario_changes.jsonl \
    --schema schema/scenario_change.schema.json
uv run python -m scenariomine qc
```

Output goes to `raw/` and `parsed/` (git-ignored). `data/repos.csv` is the
frozen repository list, with a licence class per repository; hand-checked
decisions are in `data/license_overrides.csv`. To rebuild the bundled sample
from a full `parsed/` run: `uv run python scripts/make_sample.py`.

## Repository layout

```
scenariomine/    Python package (CLI entry point: uv run python -m scenariomine)
schema/          JSON Schemas: scenario_version, scenario_change
data/            repos.csv, license_overrides.csv, sample/ (pilot Parquet)
examples/        quickstart.py
.claude/skills/  find-scenarios (the Claude Code skill)
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
