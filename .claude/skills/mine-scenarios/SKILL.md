---
name: mine-scenarios
description: Mine OpenSCENARIO (.xosc) scenarios from one, several, or all repositories in data/repos.csv. Collects git history, parses versions, links evolution, validates, and summarises. Use when the user asks to mine, collect, refresh, or re-run the pipeline for specific repos or the whole list.
argument-hint: "[owner/repo ...| all] [--since YYYY-MM-DD]"
---

# mine-scenarios

Runs the ScenarioMine pipeline (`scenariomine/`) on a chosen set of repositories from `data/repos.csv`.

## Inputs

Parse `$ARGUMENTS`:
- One or more `owner/repo` names that must appear in `data/repos.csv` (column `full_name`), or `all`.
- Optional `--since YYYY-MM-DD`. Default is full history.
- No arguments: ask which repos, or whether to mine all.

## Guardrails (project rules, do not skip)

1. **Always exclude `yangyh408/onsite-test-server`** unless the user names it explicitly. It is deferred (not yet collected), and every corpus figure excludes it.
2. `derekwuchengyu/esmini_scenario_tools` (generated, 33k files) is already excluded from `data/repos.csv` by `snapshot`, so it is not in scope. If the user asks for it, explain that and do not add it.
3. A repo missing from `data/repos.csv` is not in scope: say so. To add one, the user must re-run `snapshot` (it overwrites the CSV from a discovery inventory CSV, which is not in this repository), so ask first.
4. `raw/` and `parsed/` are git-ignored. Never commit them or the ASAM XSDs in `schemas/`.
5. Licence policy is applied downstream from `data/repos.csv`; mining is archive-only and publishes nothing. Do not copy file contents anywhere outside `raw/`/`parsed/`.
6. `all` is slow (359 repos, network-bound). Warn the user and run it in the background. A subset run is fine in the foreground.
7. Running `parse`/`evolve` without `--only` re-processes everything in `raw/`. Be aware that it rewrites `parsed/*` wholesale, which also replaces output from earlier runs for other repos. For a subset, use `--out` to a separate directory unless the user wants the main corpus refreshed.

## Procedure

1. **Validate targets.** For each name, `grep -i "^<name>," data/repos.csv`. Report any not found, and stop if none remain. Show file count and `license_class` for each.
2. **Collect** (stdlib only):
   ```bash
   uv run python -m scenariomine collect --only <repo> [--only <repo2> ...] --jobs 4 [--since DATE]
   ```
   For `all`: `uv run python -m scenariomine collect --jobs 4 --exclude yangyh408/onsite-test-server` (run in background; 360 repositories are listed, 359 collectable: `SimForgeinc/simforge-oss` no longer exists on GitHub and will fail). Add `--force` only if the user wants repos redone; collection resumes otherwise.
3. **Schemas** (once; skip if `schemas/` is populated):
   ```bash
   uv run --extra dev python -m scenariomine fetch-schemas
   ```
4. **Parse** and **evolve** (need lxml):
   ```bash
   uv run --extra parquet --extra dev python -m scenariomine parse --only <repo> --parquet [--out parsed_subset]
   uv run --extra parquet --extra dev python -m scenariomine evolve --parquet [--rows parsed_subset/file_versions.jsonl --out parsed_subset/scenario_changes.jsonl]
   ```
   `parse --only` takes the repo's full name (`owner/repo`) and `--out` is a directory; `evolve --rows/--out` take file paths. Use the same directory consistently across parse, evolve and validate. Current schemas: `scenario_version` 0.2.2, `scenario_change` 0.1.0.
5. **Validate**:
   ```bash
   uv run --extra dev python -m scenariomine validate
   uv run --extra dev python -m scenariomine validate --rows parsed/scenario_changes.jsonl --schema schema/scenario_change.schema.json
   ```
   (Adjust paths if a separate `--out` was used.) Any schema failure is a real finding: report it, do not edit rows.
6. **Summarise** for the user, per repo and total: files at HEAD, distinct blobs, versions, changes, how many parsed vs flagged (non-1.0–1.3, catalogues, distribution files), XSD-valid count, collection failures (clone errors, truncated trees, repo gone). Read counts from the `parsed/` JSONL (use `uv run python -I` with a small inline script or `jq`); do not guess.

## Reporting

- Say exactly what ran, what failed, and what was skipped. If a repo fails to clone (deleted/private), name it and move on.
- Corpus figures in the paper and dataset card describe the full 359-repo corpus; do not treat subset-run counts as replacing them.
- Suggest `uv run --extra parquet --extra dev python -m scenariomine qc` after a full run (it is meaningless on a subset). A full run that changes parser output also invalidates the manual spot-check done on an earlier schema version: say so.
- To explore a result, `Dataset.load("<out dir>")` (`from scenariomine import Dataset`) gives `query`, `history` and `changes` over the parsed tables.
- To rebuild an existing corpus exactly, use `collect --pin-from raw --out raw_repro` (checks reproducibility at the recorded `head_sha`s).
