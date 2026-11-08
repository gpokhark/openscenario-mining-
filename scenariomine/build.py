"""Join raw/ history with parsed blob records -> parsed/file_versions.jsonl.

One output row per (commit, .xosc path) change, i.e. one `scenario_version`.
Each distinct blob is parsed once, however many commits or repos contain it.
"""
import csv
import json
from pathlib import Path

from . import qc
from .parse import FIELDS, Validators, empty, parse_blob

SCHEMA_VERSION = "0.2.2"


def lineage_ids(repo, records):
    """scenario_id per record, following renames. `records` is newest-first as
    git emits it; lineage is assigned oldest-first. Git's default log order is
    by commit date, so a skewed clock can misorder two commits (limitation)."""
    current, used, ids = {}, {}, [None] * len(records)
    for i in range(len(records) - 1, -1, -1):
        r = records[i]
        kind = r["change_type"]
        if kind == "renamed" and r["old_path"] in current:
            sid = current.pop(r["old_path"])
        elif kind in ("modified", "deleted", "renamed") and r["path"] in current:
            sid = current[r["path"]]
            if kind == "deleted":
                current.pop(r["path"])
        else:  # added, or history that begins mid-life (--since)
            n = used.get(r["path"], 0)
            used[r["path"]] = n + 1
            sid = f"{repo}::{r['path']}" + (f"#{n + 1}" if n else "")
        if kind != "deleted":
            current[r["path"]] = sid
        ids[i] = sid
    return ids


def build(raw, out, schemas_dir, only=None, repos_csv="data/repos.csv"):
    raw, out = Path(raw), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    validators, cache = Validators(schemas_dir), {}
    # Licence comes from the frozen repos.csv (single source of truth, includes the
    # authors' overrides and policy), not from the collection-time manifest.
    with open(repos_csv, newline="") as f:
        lic = {r["full_name"]: r for r in csv.DictReader(f)}
    rows = []
    for mpath in sorted(raw.glob("*/manifest.json")):
        m = json.loads(mpath.read_text())
        if m["status"] != "complete" or (only and m["repo"] not in only):
            continue
        rdir = mpath.parent
        L = lic[m["repo"]]
        recs = [json.loads(l) for l in open(rdir / "history.jsonl")]
        for r, sid in zip(recs, lineage_ids(m["repo"], recs)):
            sha = r["blob_sha"]
            if sha is None:
                parsed = empty()
            else:
                if sha not in cache:
                    blob = rdir / "blobs" / sha[:2] / f"{sha}.xosc"
                    cache[sha] = parse_blob(blob.read_bytes(), validators) if blob.exists() \
                        else dict(empty(), parse_error="blob missing from archive")
                parsed = cache[sha]
            row = {
                "schema_version": SCHEMA_VERSION,
                "scenario_id": sid, "repo": m["repo"],
                "license_spdx": L["license_spdx"] or None, "license_class": L["license_class"],
                "publish_contents": L["license_class"] == "permissive",
                "repo_head_sha": m["head_sha"],
                **{k: r[k] for k in ("commit", "parents", "authored_at", "committed_at",
                                     "path", "old_path", "change_type", "blob_sha",
                                     "blob_size", "message", "n_files_in_commit",
                                     "code_changed_in_commit")},
                **{k: parsed[k] for k in FIELDS},
            }
            rows.append(row)
    # Publication rule B: contents are published only if the repository is permissive
    # AND the blob was first seen in a permissive repository (guards against a file
    # vendored from an unlicensed or restricted origin).
    groups = qc.blob_groups(rows)
    for row in rows:
        if row["blob_sha"] and groups[row["blob_sha"]]["first_class"] != "permissive":
            row["publish_contents"] = False
    with open(out / "file_versions.jsonl", "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(out / "blob_groups.jsonl", "w") as f:
        for g in groups.values():
            f.write(json.dumps({
                "blob_sha": g["blob_sha"], "canonical_hash": g["canonical_hash"],
                "file_type": g["file_type"], "n_repos": len(g["repos"]),
                "first_seen_repo": g["first_repo"], "first_seen_commit": g["first_commit"],
                "first_seen_path": g["first_path"], "first_seen_at": g["first_t"].isoformat(),
                "first_seen_license_class": g["first_class"],
                "origin_permissive": g["first_class"] == "permissive",
            }) + "\n")
    return len(rows), len(cache)


def to_parquet(jsonl, dest):
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = [json.loads(l) for l in open(jsonl)]
    pq.write_table(pa.Table.from_pylist(rows), dest, compression="zstd")
    return len(rows)


def validate(jsonl, schema_path):
    from jsonschema import Draft202012Validator
    v = Draft202012Validator(json.loads(Path(schema_path).read_text()))
    n = bad = 0
    for line in open(jsonl):
        n += 1
        errs = list(v.iter_errors(json.loads(line)))
        if errs:
            bad += 1
            if bad <= 5:
                print(f"row {n}: {errs[0].message[:200]}")
    return n, bad
