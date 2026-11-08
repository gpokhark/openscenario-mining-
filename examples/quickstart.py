"""Run with: uv run --extra parquet python examples/quickstart.py

Uses the bundled pilot sample (5 repositories), so nothing is cloned or downloaded.
"""
from collections import Counter

from scenariomine import Dataset

ds = Dataset.load()
heads = ds.query()
print(f"{len(ds.versions)} history rows, {len(heads)} scenarios at their latest version")

print("\nBy declared OpenSCENARIO version:")
for v, n in Counter(r["osc_version"] for r in heads).most_common():
    print(f"  {v}: {n}")

lane = ds.query(entity="vehicle", action="lane_change_action")
print(f"\nscenarios with a vehicle and a lane_change_action: {len(lane)}")

changed = ds.changes(kind="parameters")
print(f"parameter changes: {len(changed)}")
if changed:
    c = changed[0]
    print(f"  first: {c['repo']} {c['path']}")
    print("  history of that file:")
    for r in ds.history(c["scenario_id"])[:5]:
        print(f"    {r['committed_at'][:10]} {r['change_type']:9} {r['commit'][:8]}")
