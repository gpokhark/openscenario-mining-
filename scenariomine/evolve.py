"""Step 5: link consecutive versions of each scenario and classify what changed.

Input is parsed/file_versions.jsonl; output is one `scenario_change` row per
step between two consecutive versions of a lineage (same scenario_id). Only
what the parser extracted can be diffed by name; anything else that changed
shows up as `other_content` (the canonical hash differs but no extracted field
does), which is itself informative: positions, dynamics and other numeric
content are not diffed in v1.

Versions are ordered by git's log order (commit date), not by graph topology;
on branchy histories two consecutive versions may sit on different branches.
"""
import json
import re
from collections import defaultdict

CHANGE_SCHEMA_VERSION = "0.1.0"

# GitHub squash/merge commit conventions, and closing keywords.
PR_RE = [re.compile(r"Merge pull request #(\d+)"), re.compile(r"\(#(\d+)\)\s*$", re.M)]
ISSUE_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)", re.I)
REF_RE = re.compile(r"(?<![\w/])#(\d+)\b")


def refs(message):
    pr = sorted({int(n) for rx in PR_RE for n in rx.findall(message)})
    issues = sorted({int(n) for n in ISSUE_RE.findall(message)} - set(pr))
    other = sorted({int(n) for n in REF_RE.findall(message)} - set(pr) - set(issues))
    return pr, issues, other


def _names(items, key="name"):
    return [i[key] for i in items]


def _added_removed(old, new):
    o, n = set(old), set(new)
    return sorted(x for x in n - o if x is not None), sorted(x for x in o - n if x is not None)


def _params(old, new):
    o = {p["name"]: p for p in old}
    n = {p["name"]: p for p in new}
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = [{"name": k, "old_value": o[k]["value"], "new_value": n[k]["value"],
                "old_type": o[k]["type"], "new_type": n[k]["type"]}
               for k in sorted(set(o) & set(n))
               if (o[k]["value"], o[k]["type"]) != (n[k]["value"], n[k]["type"])]
    return added, removed, changed


def diff(a, b):
    """a, b: consecutive file_versions rows (a older). Returns a scenario_change row."""
    pr, issues, other = refs(b["message"])
    content = a["blob_sha"] != b["blob_sha"]
    canon = (a["canonical_hash"] != b["canonical_hash"]
             if a["canonical_hash"] and b["canonical_hash"] else None)
    comparable = all(r["file_type"] == "scenario" and r["osc_version_in_range"] for r in (a, b))
    row = {
        "schema_version": CHANGE_SCHEMA_VERSION,
        "scenario_id": b["scenario_id"], "repo": b["repo"],
        "license_class": b["license_class"], "publish_contents": b["publish_contents"],
        "from_commit": a["commit"], "to_commit": b["commit"],
        "from_sha": a["blob_sha"], "to_sha": b["blob_sha"],
        "from_authored_at": a["authored_at"], "authored_at": b["authored_at"],
        "committed_at": b["committed_at"],
        "from_path": a["path"], "path": b["path"], "path_changed": a["path"] != b["path"],
        "content_changed": content, "canonical_changed": canon,
        "file_type_from": a["file_type"], "file_type_to": b["file_type"],
        "comparable": comparable,
        "osc_version_from": a["osc_version"], "osc_version_to": b["osc_version"],
        "osc_version_bumped": (a["osc_version"] != b["osc_version"]
                               if a["osc_version"] and b["osc_version"] else None),
        "xsd_valid_from": a["validates_against_xsd"], "xsd_valid_to": b["validates_against_xsd"],
    }
    null_fields = ("entities_added", "entities_removed", "maneuvers_added", "maneuvers_removed",
                   "action_types_added", "action_types_removed", "trigger_types_added",
                   "trigger_types_removed", "parameters_added", "parameters_removed",
                   "parameters_changed")
    if comparable:
        row["entities_added"], row["entities_removed"] = _added_removed(
            _names(a["entities"]), _names(b["entities"]))
        row["maneuvers_added"], row["maneuvers_removed"] = _added_removed(
            a["maneuver_names"], b["maneuver_names"])
        row["action_types_added"], row["action_types_removed"] = _added_removed(
            a["init_action_types"] + a["event_action_types"],
            b["init_action_types"] + b["event_action_types"])
        row["trigger_types_added"], row["trigger_types_removed"] = _added_removed(
            a["trigger_types"], b["trigger_types"])
        row["parameters_added"], row["parameters_removed"], row["parameters_changed"] = \
            _params(a["parameters"], b["parameters"])
        row["n_maneuvers_delta"] = b["n_maneuvers"] - a["n_maneuvers"]
        row["n_events_delta"] = b["n_events"] - a["n_events"]
        row["n_conditions_delta"] = b["n_conditions"] - a["n_conditions"]
        row["trigger_conditions_changed"] = (a["trigger_types"] != b["trigger_types"]
                                             or a["n_conditions"] != b["n_conditions"])
        row["environment_changed"] = a["environment"] != b["environment"]
        row["road_network_changed"] = a["road_network"] != b["road_network"]
        row["catalog_refs_changed"] = (sorted(map(json.dumps, a["catalog_refs"]))
                                       != sorted(map(json.dumps, b["catalog_refs"])))
    else:
        for k in null_fields:
            row[k] = None
        for k in ("n_maneuvers_delta", "n_events_delta", "n_conditions_delta",
                  "trigger_conditions_changed", "environment_changed",
                  "road_network_changed", "catalog_refs_changed"):
            row[k] = None

    kinds = []
    if row["path_changed"]:
        kinds.append("path")
    if content and canon is False:
        kinds.append("cosmetic")  # bytes differ, canonical form identical
    if row["osc_version_bumped"]:
        kinds.append("version")
    if comparable and canon is not False:
        for kind, hit in (
                ("entities", row["entities_added"] or row["entities_removed"]),
                ("maneuvers", row["maneuvers_added"] or row["maneuvers_removed"]
                 or row["action_types_added"] or row["action_types_removed"]),
                ("parameters", row["parameters_added"] or row["parameters_removed"]
                 or row["parameters_changed"]),
                ("triggers", row["trigger_conditions_changed"]),
                ("environment", row["environment_changed"]),
                ("road_network", row["road_network_changed"]),
                ("catalog_refs", row["catalog_refs_changed"])):
            if hit:
                kinds.append(kind)
        if canon and not any(k in kinds for k in (
                "version", "entities", "maneuvers", "parameters", "triggers",
                "environment", "road_network", "catalog_refs")):
            kinds.append("other_content")
    elif canon or (content and canon is None):
        # changed, but not comparable field by field (out-of-range version,
        # catalogue or other file type, or not well-formed XML)
        kinds.append("unparsed_content")
    row["change_kinds"] = kinds

    row.update(
        commit_message=b["message"], associated_pr=pr, closed_issues=issues, other_refs=other,
        source_code_changed_same_commit=b["code_changed_in_commit"],
        n_files_in_commit=b["n_files_in_commit"])
    return row


def evolve(jsonl, out):
    """Write scenario_changes.jsonl; return summary counts."""
    chains = defaultdict(list)
    for line in open(jsonl):
        r = json.loads(line)
        chains[r["scenario_id"]].append(r)
    changes, per_commit = [], defaultdict(set)
    lineages = versions = 0
    for rows in chains.values():
        rows.reverse()  # file is newest-first within a repo; chain oldest-first
        live = [r for r in rows if r["change_type"] != "deleted"]
        lineages += 1
        versions += len(live)
        for a, b in zip(live, live[1:]):
            changes.append(diff(a, b))
        for r in rows:
            per_commit[(r["repo"], r["commit"])].add(r["scenario_id"])
    for c in changes:
        c["n_scenarios_changed_in_commit"] = len(per_commit[(c["repo"], c["to_commit"])])
    changes.sort(key=lambda c: (c["repo"], c["scenario_id"], c["authored_at"]))
    with open(out, "w") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return {"lineages": lineages, "versions": versions, "changes": len(changes)}
