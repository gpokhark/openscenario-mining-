import argparse

from . import collect as collect_mod
from . import find as find_mod
from . import snapshot as snapshot_mod

GENERATED = "derekwuchengyu/esmini_scenario_tools"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scenariomine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="freeze docs/inventory.csv into data/repos.csv")
    s.add_argument("--inventory", default="docs/inventory.csv")
    s.add_argument("--overrides", default="data/license_overrides.csv")
    s.add_argument("--out", default="data/repos.csv")
    s.add_argument("--exclude", action="append", default=[GENERATED])

    c = sub.add_parser("collect", help="clone repos and archive .xosc history")
    c.add_argument("--repos", default="data/repos.csv")
    c.add_argument("--out", default="raw")
    c.add_argument("--since", help="only commits after this date (YYYY-MM-DD); default: full history")
    c.add_argument("--only", action="append", help="restrict to this repo (repeatable)")
    c.add_argument("--exclude", action="append", help="skip this repo (repeatable)")
    c.add_argument("--limit", type=int)
    c.add_argument("--jobs", type=int, default=4)
    c.add_argument("--blob-limit", default="1m", help="git partial-clone blob size limit; blobs above it are fetched lazily")
    c.add_argument("--pin-from", help="raw/ dir of an earlier run: collect each repo at its recorded head_sha (reproducibility check)")
    c.add_argument("--keep-clones", action="store_true")
    c.add_argument("--force", action="store_true", help="redo repos already complete")

    sc = sub.add_parser("fetch-schemas", help="download the pinned OpenSCENARIO XSDs")
    sc.add_argument("--dir", default="schemas")

    b = sub.add_parser("parse", help="parse archived blobs into parsed/file_versions.jsonl")
    b.add_argument("--raw", default="raw")
    b.add_argument("--out", default="parsed")
    b.add_argument("--schemas", default="schemas")
    b.add_argument("--only", action="append")
    b.add_argument("--parquet", action="store_true")

    e = sub.add_parser("evolve", help="link consecutive versions -> parsed/scenario_changes.jsonl")
    e.add_argument("--rows", default="parsed/file_versions.jsonl")
    e.add_argument("--out", default="parsed/scenario_changes.jsonl")
    e.add_argument("--parquet", action="store_true")

    q = sub.add_parser("qc", help="Step 6 checks; writes parsed/qc_report.json")
    q.add_argument("--rows", default="parsed/file_versions.jsonl")
    q.add_argument("--raw", default="raw")
    q.add_argument("--repro", help="raw dir of a --pin-from re-collection to compare with --raw")
    q.add_argument("--out", default="parsed/qc_report.json")

    ss = sub.add_parser("qc-sample", help="draw the manual spot-check sample -> worksheet CSV")
    ss.add_argument("--rows", default="parsed/file_versions.jsonl")
    ss.add_argument("--raw", default="raw")
    ss.add_argument("--n", type=int, default=50)
    ss.add_argument("--seed", type=int, default=20261004)
    ss.add_argument("--per-repo-cap", type=int, default=2)
    ss.add_argument("--out", default="parsed/spotcheck_worksheet.csv")

    f = sub.add_parser("find", help="find scenarios by topic, trigger, action or name")
    f.add_argument("--data", default="parsed", help="directory with file_versions (default: parsed; use data/sample for the bundled sample)")
    f.add_argument("--topic", choices=sorted(find_mod.TOPICS))
    f.add_argument("--keyword", help="regex matched against path and entity/maneuver/parameter names")
    f.add_argument("--trigger"); f.add_argument("--action"); f.add_argument("--entity"); f.add_argument("--repo")
    f.add_argument("--publishable", action="store_true", help="only files whose contents may be redistributed")
    f.add_argument("--all-copies", action="store_true", help="do not collapse identical content")
    f.add_argument("--weather", choices=["rain", "fog", "snow"], help="rain/snow: declared precipitation with intensity > 0; fog: visual range at most --max-visibility")
    f.add_argument("--max-visibility", type=float, default=2000.0, help="metres; fog definitions above this are treated as the simulator default")
    f.add_argument("--raw", default="raw", help="archive used to read fog range and rain intensity")
    f.add_argument("--limit", type=int, default=25)
    f.add_argument("--json", action="store_true")

    v = sub.add_parser("validate", help="check parsed rows against the JSON Schema")
    v.add_argument("--rows", default="parsed/file_versions.jsonl")
    v.add_argument("--schema", default="schema/scenario_version.schema.json")

    a = ap.parse_args(argv)
    if a.cmd == "snapshot":
        rows = snapshot_mod.build(a.inventory, a.overrides, a.out, set(a.exclude))
        print(f"wrote {len(rows)} repositories to {a.out}")
    elif a.cmd == "fetch-schemas":
        from . import schemas
        schemas.fetch(a.dir)
    elif a.cmd == "parse":
        from . import build
        n, blobs = build.build(a.raw, a.out, a.schemas, set(a.only) if a.only else None)
        print(f"{n} rows from {blobs} distinct blobs -> {a.out}/file_versions.jsonl")
        if a.parquet:
            build.to_parquet(f"{a.out}/file_versions.jsonl", f"{a.out}/file_versions.parquet")
            print(f"wrote {a.out}/file_versions.parquet")
    elif a.cmd == "evolve":
        from . import build, evolve
        print(evolve.evolve(a.rows, a.out))
        if a.parquet:
            build.to_parquet(a.out, a.out.replace(".jsonl", ".parquet"))
    elif a.cmd == "qc":
        import json
        from . import qc
        rows = qc.load(a.rows)
        groups = qc.blob_groups(rows)
        report = {"provenance": qc.provenance(rows), "dedup": qc.dedup(rows, groups),
                  "publish_rules": qc.publish_rules(rows, groups),
                  "parser_crosscheck": qc.crosscheck(a.raw, rows), "xsd": qc.xsd_summary(rows)}
        if a.repro:
            report["reproducibility"] = qc.reproduce(a.raw, a.repro)
        json.dump(report, open(a.out, "w"), indent=2)
        print(json.dumps(report, indent=2))
    elif a.cmd == "qc-sample":
        import csv
        from . import qc
        rows = qc.worksheet(qc.spotcheck_sample(qc.load(a.rows), a.n, a.seed, a.per_repo_cap), a.raw)
        with open(a.out, "w", newline="") as f:
            w = csv.DictWriter(f, list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} files from {len({r['repo'] for r in rows})} repos -> {a.out}")
    elif a.cmd == "find":
        import json
        from .dataset import Dataset
        hits = find_mod.find(Dataset.load(a.data), a.topic, a.keyword, a.trigger, a.action, a.entity,
                             a.repo, a.publishable, not a.all_copies, a.limit,
                             a.weather, a.max_visibility, a.raw)
        if a.json:
            print(json.dumps(hits, indent=1))
        else:
            if a.topic in find_mod.CONFIDENCE:
                print(f"note: confidence {find_mod.CONFIDENCE[a.topic]}")
            for h in hits:
                tag = "contents ok" if h["publish_contents"] else "pointer only"
                print(f"{h['score']:3} {h['repo']} :: {h['path']} [{h['osc_version']}, {h['license_spdx'] or 'no licence'}, {tag}]")
                print(f"      {'; '.join(h['evidence'])}\n      {h['permalink']}")
            print(f"{len(hits)} distinct scenarios shown")
    elif a.cmd == "validate":
        from . import build
        n, bad = build.validate(a.rows, a.schema)
        print(f"{n - bad}/{n} rows valid")
        return 1 if bad else 0
    else:
        res = collect_mod.collect(a.repos, a.out, a.since, a.only, a.exclude, a.limit,
                                  a.jobs, a.keep_clones, a.force, a.blob_limit, a.pin_from)
        bad = [m["repo"] for m in res if m["status"] != "complete"]
        print(f"{len(res) - len(bad)} complete, {len(bad)} failed")
        return 1 if bad else 0
