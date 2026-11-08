"""Rebuild data/sample/ (the bundled pilot sample) from parsed/*.jsonl.

Usage: uv run --extra parquet python scripts/make_sample.py
Keeps only the five pilot repositories. Metadata only; no file contents.
"""
import json
from pathlib import Path

from scenariomine.build import to_parquet

PILOT = {"esmini/esmini", "asam-ev/qc-openscenarioxml", "carla-simulator/scenario_runner",
         "openMSL/sl-3-1-osc-alks-scenarios", "vectorgrp/OSC-NCAP-scenarios"}
OUT = Path("data/sample")
OUT.mkdir(parents=True, exist_ok=True)
for src, dest in (("file_versions", "pilot_file_versions"), ("scenario_changes", "pilot_scenario_changes")):
    tmp = OUT / f"{dest}.jsonl.tmp"
    with open(f"parsed/{src}.jsonl") as f, open(tmp, "w") as g:
        n = sum(1 for line in f if json.loads(line)["repo"] in PILOT and g.write(line))
    to_parquet(tmp, OUT / f"{dest}.parquet")
    tmp.unlink()
    print(dest, n)
