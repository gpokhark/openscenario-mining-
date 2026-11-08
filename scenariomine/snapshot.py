"""Freeze docs/inventory.csv into a dated repos.csv the collector reads.

Applies the hand-maintained licence overrides, drops repositories with no
.xosc files and the generated repository (excluded from v1, see
docs/step2-scope.md).
"""
import csv
import datetime as dt

# File-level weak copyleft: unmodified files may be redistributed with their licence
# notice, so they are treated like permissive licences for publication (policy,
# docs/step6-qc.md). Decided by the authors; not legal advice.
WEAK_COPYLEFT = {"MPL-2.0", "EPL-2.0"}

KEEP = ["full_name", "xosc_file_count", "license_spdx", "license_class",
        "license_name", "license_source", "default_branch", "stars",
        "pushed_at", "tree_truncated", "snapshot_date"]


def build(inventory, overrides, out, exclude):
    with open(overrides, newline="") as f:
        fixes = {r["full_name"]: r for r in csv.DictReader(f)}
    today = dt.date.today().isoformat()
    rows = []
    with open(inventory, newline="") as f:
        for r in csv.DictReader(f):
            if r["full_name"] in exclude or int(r["xosc_file_count"]) == 0:
                continue
            fix = fixes.get(r["full_name"])
            if fix:
                r["license_spdx"] = fix["license_spdx"]
                r["license_class"] = fix["license_class"]
                r["license_name"] = fix["license_spdx"]
                r["license_source"] = "manual: " + fix["note"]
            elif r["license_spdx"] in WEAK_COPYLEFT and r["license_class"] != "permissive":
                r["license_class"] = "permissive"
                r["license_source"] = "policy: weak copyleft treated as redistributable with per-file notice"
            else:
                r["license_source"] = "github"
            r["snapshot_date"] = today
            rows.append({k: r[k] for k in KEEP})
    rows.sort(key=lambda r: r["full_name"].lower())
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, KEEP)
        w.writeheader()
        w.writerows(rows)
    return rows
