"""Read-only access to the ScenarioMine tables.

    from scenariomine import Dataset
    ds = Dataset.load()                                   # bundled pilot sample
    ds.query(entity="pedestrian", action="lane_change_action")
    ds.history(scenario_id="...")                         # version chain, oldest first
    ds.changes(kind="parameters")                         # evolution records

Reads Parquet (needs pyarrow) or JSONL (standard library only). Rows are plain
dicts that follow schema/scenario_version.schema.json and
schema/scenario_change.schema.json.
"""
import json
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
_NAMES = {"versions": ("pilot_file_versions", "file_versions"),
          "changes": ("pilot_scenario_changes", "scenario_changes")}


def _read(directory, key):
    for stem in _NAMES[key]:
        pq, jl = directory / f"{stem}.parquet", directory / f"{stem}.jsonl"
        if pq.exists():
            try:
                import pyarrow.parquet as parquet
            except ImportError:
                if not jl.exists():
                    raise ImportError("reading Parquet needs pyarrow: pip install 'scenariomine[parquet]'")
            else:
                return parquet.read_table(pq).to_pylist()
        if jl.exists():
            with open(jl, encoding="utf-8") as f:
                return [json.loads(line) for line in f]
    raise FileNotFoundError(f"no {key} table found in {directory}")


class Dataset:
    def __init__(self, versions, changes):
        self.versions = versions
        self.changes_rows = changes

    @classmethod
    def load(cls, path=None):
        """Load from a directory holding the two tables. Default: the bundled
        pilot sample (five repositories). For the full corpus pass `parsed/`."""
        d = Path(path) if path else DEFAULT_DIR
        return cls(_read(d, "versions"), _read(d, "changes"))

    def query(self, entity=None, action=None, trigger=None, osc_version=None, repo=None,
              license_class=None, file_type="scenario", head_only=True):
        """Scenario versions matching every given filter.

        entity: entity type (vehicle, pedestrian, misc_object, catalog_reference, unspecified)
        action: action term from init or event actions, e.g. lane_change_action
        trigger: trigger term, e.g. time_headway_condition
        head_only: keep only the latest version of each lineage (deleted lineages dropped)
        """
        rows = self.heads() if head_only else [r for r in self.versions if r["change_type"] != "deleted"]
        out = []
        for r in rows:
            if file_type and r.get("file_type") != file_type:
                continue
            if entity and not any(e["type"] == entity for e in r.get("entities") or []):
                continue
            if action and action not in (r.get("init_action_types") or []) + (r.get("event_action_types") or []):
                continue
            if trigger and trigger not in (r.get("trigger_types") or []):
                continue
            if osc_version and r.get("osc_version") != osc_version:
                continue
            if repo and r["repo"] != repo:
                continue
            if license_class and r["license_class"] != license_class:
                continue
            out.append(r)
        return out

    def heads(self):
        """Latest row per lineage, excluding lineages whose last row is a deletion."""
        last = {}
        for r in sorted(self.versions, key=lambda r: (r["committed_at"], r["commit"])):
            last[r["scenario_id"]] = r
        return [r for r in last.values() if r["change_type"] != "deleted"]

    def history(self, scenario_id):
        """All rows of one lineage, oldest first (deletions included)."""
        rows = [r for r in self.versions if r["scenario_id"] == scenario_id]
        return sorted(rows, key=lambda r: (r["committed_at"], r["commit"]))

    def changes(self, kind=None, scenario_id=None, repo=None):
        """Version-to-version change records, optionally filtered by a
        `change_kinds` value (path, cosmetic, version, entities, maneuvers,
        parameters, triggers, environment, road_network, catalog_refs,
        other_content, unparsed_content)."""
        return [c for c in self.changes_rows
                if (kind is None or kind in c["change_kinds"])
                and (scenario_id is None or c["scenario_id"] == scenario_id)
                and (repo is None or c["repo"] == repo)]
