"""Step 6: quality-control checks over raw/ and parsed/.

Each check returns a dict and prints nothing; cli.py prints and writes the
combined report. Nothing here modifies the corpus.
"""
import datetime as dt
import json
import re
from urllib.parse import quote
from collections import Counter, defaultdict
from pathlib import Path

PROVENANCE = ("repo", "commit", "path", "license_class", "publish_contents", "blob_sha",
              "authored_at", "scenario_id")


def _utc(ts):
    return dt.datetime.fromisoformat(ts).astimezone(dt.timezone.utc)


def load(jsonl):
    return [json.loads(l) for l in open(jsonl)]


def head_files(rows):
    """Latest version of every lineage that was not deleted (rows are newest-first per repo)."""
    seen, out = set(), []
    for r in rows:
        if r["scenario_id"] in seen:
            continue
        seen.add(r["scenario_id"])
        if r["change_type"] != "deleted":
            out.append(r)
    return out


def provenance(rows):
    """Every row carries repo, commit, path and licence; deletions have no blob by design."""
    missing = Counter()
    for r in rows:
        for k in PROVENANCE:
            if r[k] is None and not (k == "blob_sha" and r["change_type"] == "deleted"):
                missing[k] += 1
        if r["license_class"] == "permissive" and not r["license_spdx"]:
            missing["license_spdx(permissive)"] += 1
    return {"rows": len(rows), "rows_missing_provenance": sum(missing.values()),
            "missing_by_field": dict(missing)}


def blob_groups(rows):
    """Per distinct blob: where and when it first appeared, and in how many repos.

    First appearance is by authored time (UTC). It is a heuristic for origin, not
    proof: squashed or re-imported histories carry fresh dates."""
    g = {}
    for r in rows:
        sha = r["blob_sha"]
        if not sha:
            continue
        t = _utc(r["authored_at"])
        e = g.setdefault(sha, {"blob_sha": sha, "canonical_hash": r["canonical_hash"],
                               "file_type": r["file_type"], "repos": set(),
                               "first_t": t, "first_repo": r["repo"], "first_path": r["path"],
                               "first_class": r["license_class"], "first_commit": r["commit"]})
        e["repos"].add(r["repo"])
        if t < e["first_t"]:
            e.update(first_t=t, first_repo=r["repo"], first_path=r["path"],
                     first_class=r["license_class"], first_commit=r["commit"])
    return g


def dedup(rows, groups):
    head = head_files(rows)
    by_canon = defaultdict(set)
    for g in groups.values():
        if g["canonical_hash"]:
            by_canon[g["canonical_hash"]].add(g["blob_sha"])
    heads = [r for r in head if r["blob_sha"]]
    own = sum(groups[r["blob_sha"]]["first_repo"] == r["repo"] for r in heads)
    canon_distinct = len({groups[r["blob_sha"]]["canonical_hash"] or r["blob_sha"] for r in heads})
    per_repo = defaultdict(lambda: [0, 0])  # repo -> [head files, files first seen elsewhere]
    for r in heads:
        per_repo[r["repo"]][0] += 1
        per_repo[r["repo"]][1] += groups[r["blob_sha"]]["first_repo"] != r["repo"]
    shares = sorted(((v[1] / v[0], k, v[0]) for k, v in per_repo.items()), reverse=True)
    buckets = Counter()
    for s, _, _ in shares:
        buckets["100%" if s == 1 else ">=90%" if s >= .9 else ">=50%" if s >= .5 else ">0%" if s > 0 else "0%"] += 1
    spread = Counter(len(g["repos"]) for g in groups.values())
    top = sorted(((len(g["repos"]), g["first_path"].rsplit("/", 1)[-1]) for g in groups.values()), reverse=True)[:10]
    return {
        "head_files": len(heads), "distinct_blobs_at_head": len({r["blob_sha"] for r in heads}),
        "distinct_canonical_at_head": canon_distinct,
        "head_files_first_seen_in_own_repo": own,
        "head_files_first_seen_elsewhere": len(heads) - own,
        "repos_by_share_of_files_first_seen_elsewhere": dict(buckets),
        "blobs_in_1_repo": spread[1], "blobs_in_2_to_5_repos": sum(v for k, v in spread.items() if 2 <= k <= 5),
        "blobs_in_over_5_repos": sum(v for k, v in spread.items() if k > 5),
        "most_widespread": [{"repos": n, "name": name} for n, name in top],
        "repos_with_all_files_copied": [k for s, k, n in shares if s == 1][:15],
    }


def publish_rules(rows, groups):
    """What each candidate rule would let us publish, for the authors' decision."""
    heads = [r for r in head_files(rows) if r["blob_sha"]]
    a = [r for r in heads if r["publish_contents"]]
    b = [r for r in a if groups[r["blob_sha"]]["first_class"] == "permissive"]
    # rule C: every repo that ever held the blob is permissive
    cls = {r["repo"]: r["license_class"] for r in rows}
    c = [r for r in a if all(cls[x] == "permissive" for x in groups[r["blob_sha"]]["repos"])]
    f = lambda xs: {"head_files": len(xs), "distinct_blobs": len({r["blob_sha"] for r in xs})}
    return {"A_repo_is_permissive": f(a), "B_and_first_seen_in_a_permissive_repo": f(b),
            "C_and_every_repo_holding_it_is_permissive": f(c), "all_head_files": f(heads)}


def _text(path):
    b = path.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return b.decode("utf-16", errors="replace")
    return b.decode("utf-8-sig", errors="replace")


def crosscheck(raw, rows):
    """Independent count of the same tags by regular expression vs the parser, for
    every distinct in-range scenario blob. Mismatches are listed, not hidden."""
    tags = {"n_events": "Event", "n_acts": "Act", "n_stories": "Story", "n_maneuvers": "Maneuver",
            "n_maneuver_groups": "ManeuverGroup", "n_entities": "ScenarioObject"}
    seen, checked, bad = set(), 0, defaultdict(list)
    for r in rows:
        if r["file_type"] != "scenario" or not r["osc_version_in_range"] or r["blob_sha"] in seen:
            continue
        seen.add(r["blob_sha"])
        p = Path(raw) / r["repo"].replace("/", "__") / "blobs" / r["blob_sha"][:2] / f"{r['blob_sha']}.xosc"
        t = re.sub(r"<!--.*?-->", "", _text(p), flags=re.S)
        checked += 1
        for field, tag in tags.items():
            n = len(re.findall(r"<%s[\s/>]" % tag, t))
            if n != r[field]:
                bad[field].append({"repo": r["repo"], "path": r["path"], "regex": n, "parser": r[field]})
    return {"checked_blobs": checked, "blobs_with_any_mismatch": len({(x["repo"], x["path"]) for v in bad.values() for x in v}),
            "mismatches_by_field": {k: len(v) for k, v in bad.items()},
            "examples": {k: v[:3] for k, v in bad.items()}}


def xsd_summary(rows):
    heads = [r for r in head_files(rows) if r["blob_sha"]]
    inr = [r for r in heads if r["osc_version_in_range"]]
    first = Counter()
    for r in inr:
        if r["validates_against_xsd"] is False:
            m = r["xsd_first_error"] or ""
            first[re.sub(r"'[^']*'", "'*'", m)[:110]] += 1
    types = Counter(r["file_type"] for r in heads)
    return {"head_files_in_range": len(inr),
            "validate": sum(r["validates_against_xsd"] is True for r in inr),
            "fail": sum(r["validates_against_xsd"] is False for r in inr),
            "not_validated": sum(r["validates_against_xsd"] is None for r in inr),
            "head_file_types": dict(types),
            "out_of_range_head_files": sum(r["osc_version_in_range"] is False for r in heads),
            "top_first_errors": first.most_common(8)}


def reproduce(raw, repro):
    """Compare a pinned re-collection (--pin-from) with the original archive."""
    raw, repro = Path(raw), Path(repro)
    same = diff = missing = 0
    problems = []
    for m in sorted(repro.glob("*/manifest.json")):
        d = m.parent
        o = raw / d.name
        if not (o / "manifest.json").exists() or json.loads(m.read_text())["status"] != "complete":
            missing += 1
            problems.append(f"{d.name}: not comparable")
            continue
        h_same = (d / "history.jsonl").read_bytes() == (o / "history.jsonl").read_bytes()
        b1 = {p.name for p in (d / "blobs").rglob("*.xosc")}
        b2 = {p.name for p in (o / "blobs").rglob("*.xosc")}
        if h_same and b1 == b2:
            same += 1
        else:
            diff += 1
            problems.append(f"{d.name}: history_identical={h_same} blobs {len(b1)} vs {len(b2)}")
    return {"repos_compared": same + diff, "identical": same, "different": diff,
            "not_comparable": missing, "problems": problems[:20]}


def spotcheck_sample(rows, n=50, seed=20261004, per_repo_cap=2, versions=("1.0", "1.1", "1.2", "1.3")):
    """Draw the manual spot-check sample: distinct in-range scenario files at HEAD,
    stratified by declared version, at most `per_repo_cap` per repository, fixed
    seed, so one large repository cannot dominate and the draw is reproducible."""
    import random
    seen, cands = set(), defaultdict(list)
    for r in head_files(rows):
        if (r["file_type"] == "scenario" and r["osc_version"] in versions
                and r["canonical_hash"] not in seen):
            seen.add(r["canonical_hash"])
            cands[r["osc_version"]].append(r)
    rng = random.Random(seed)
    quota = {v: n // len(versions) + (i < n % len(versions)) for i, v in enumerate(versions)}
    taken, per_repo = [], Counter()
    for v in versions:
        pool = sorted(cands[v], key=lambda r: (r["repo"], r["path"]))
        rng.shuffle(pool)
        got = 0
        for r in pool:
            if got == quota[v]:
                break
            if per_repo[r["repo"]] < per_repo_cap:
                per_repo[r["repo"]] += 1
                taken.append(r)
                got += 1
    return taken


def worksheet(sample, raw):
    """Rows for the reviewer: what the parser recorded, next to where to read the XML."""
    out = []
    for i, r in enumerate(sample, 1):
        out.append({
            "id": i, "repo": r["repo"], "path": r["path"], "commit": r["commit"][:10],
            "github_url": f"https://github.com/{r['repo']}/blob/{r['commit']}/{quote(r['path'])}",
            "xml_file": str(Path(raw) / r["repo"].replace("/", "__") / "blobs" / r["blob_sha"][:2] / f"{r['blob_sha']}.xosc"),
            "osc_version": r["osc_version"], "validates_against_xsd": r["validates_against_xsd"],
            "entities": "; ".join(f"{e['name']}:{e['type']}/{e['category'] or ''}" for e in r["entities"]),
            "n_stories": r["n_stories"], "n_acts": r["n_acts"], "n_maneuver_groups": r["n_maneuver_groups"],
            "n_maneuvers": r["n_maneuvers"], "maneuver_names": "; ".join(n or "" for n in r["maneuver_names"]),
            "n_events": r["n_events"], "init_action_types": "; ".join(r["init_action_types"]),
            "event_action_types": "; ".join(r["event_action_types"]),
            "trigger_types": "; ".join(r["trigger_types"]), "n_conditions": r["n_conditions"],
            "parameters": "; ".join(f"{p['name']}={p['value']}" for p in r["parameters"]),
            "environment": json.dumps(r["environment"]), "road_network": json.dumps(r["road_network"]),
            "all_fields_correct (y/n)": "", "fields_wrong": "", "notes": ""})
    return out
