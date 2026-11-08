"""Find scenarios by topic (collision, near miss, speed bump, ...) in the parsed corpus.

Evidence comes only from what the parser extracted: trigger types, action types,
entity/maneuver/parameter names, and the file path. OpenSCENARIO has no element for
road-surface features (speed bumps, potholes belong to OpenDRIVE), so those topics
are matched by name only and are low confidence. Every hit lists its evidence so a
human can check it. Nothing here reads file contents.
"""
import os
import re
from urllib.parse import quote

from .dataset import Dataset

# topic -> (structured triggers, structured actions, name regex, needs_name_match)
TOPICS = {
    "collision": ({"collision_condition", "time_to_collision_condition"}, set(),
                  r"collision|collid|crash", False),
    "near_miss": ({"time_to_collision_condition", "relative_clearance_condition",
                   "time_headway_condition"}, set(),
                  r"near.?miss|critical|emergency|aeb|brak|cut.?in|cut.?out|cutin|cutout", False),
    "cut_in": (set(), {"lane_change_action"}, r"cut.?in|cut.?out|cutin|cutout", True),
    "pedestrian": (set(), set(), r"pedestrian|crossing|crosswalk|vru|cyclist", True),
    "intersection": (set(), set(), r"intersection|junction|roundabout|turn", True),
    "speed_bump": (set(), set(),
                   r"speed.?bump|speedbump|speed.?hump|speed.?table|traffic.?calming|pothole|manhole|"
                   r"(?<![a-z])bump(?![a-z])|(?<![a-z])hump(?![a-z])", True),
}
CONFIDENCE = {"speed_bump": "low (name match only; OpenSCENARIO cannot express road-surface features)"}


def _s(x):
    return "" if x is None else str(x)


def _fields(r):
    names = [_s(m) for m in r.get("maneuver_names") or []]
    names += [_s(e.get("name")) + " " + _s(e.get("category")) for e in r.get("entities") or []]
    names += [_s(p.get("name")) for p in r.get("parameters") or []]
    return r["path"].lower(), " ".join(names).lower()


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def weather_details(r, raw="raw"):
    """Fog visual range (m) and rain/snow intensity read from the archived XML.

    The parsed `fog_present` flag only says a <Fog> element exists, and nearly every
    esmini-style file carries one at the default 100000 m, so real fog needs the
    visualRange. Returns None if the archived blob is not available locally."""
    sha = r.get("blob_sha")
    path = os.path.join(raw, r["repo"].replace("/", "__"), "blobs", (sha or "xx")[:2], f"{sha}.xosc")
    if not sha or not os.path.exists(path):
        return None
    from lxml import etree
    try:
        tree = etree.parse(path)
    except (etree.XMLSyntaxError, OSError):
        return None
    vis = [v for v in (_num(f.get("visualRange")) for f in tree.iter("Fog")) if v is not None]
    prec = [(p.get("precipitationType"), _num(p.get("intensity") if p.get("intensity") is not None
                                                else p.get("precipitationIntensity")))
            for p in tree.iter("Precipitation")]
    return {"visual_range": min(vis) if vis else None, "precipitation": prec}


def permalink(r):
    return f"https://github.com/{r['repo']}/blob/{r['commit']}/{quote(r['path'])}"


def _hit(r):
    return {"repo": r["repo"], "path": r["path"], "osc_version": r.get("osc_version"),
            "license_class": r["license_class"], "license_spdx": r.get("license_spdx"),
            "publish_contents": r["publish_contents"], "canonical_hash": r.get("canonical_hash"),
            "scenario_id": r["scenario_id"], "permalink": permalink(r)}


def find(ds, topic=None, keyword=None, trigger=None, action=None, entity=None, repo=None,
         publishable=False, distinct=True, limit=50, weather=None, max_visibility=2000.0, raw="raw"):
    """Ranked hits: list of dicts with score, evidence, repo, path, permalink, licence."""
    triggers, actions, rx, need_name = TOPICS[topic] if topic else (set(), set(), "", False)
    if keyword:
        rx = f"{rx}|{keyword}" if rx else keyword
        need_name = need_name or not topic
    name_re = re.compile(rx, re.I) if rx else None
    triggers = set(triggers) | ({trigger} if trigger else set())
    actions = set(actions) | ({action} if action else set())
    hits = []
    for r in ds.query(entity=entity, repo=repo):
        if publishable and not r.get("publish_contents"):
            continue
        if weather:
            env = r.get("environment") or {}
            ptype = str(env.get("precipitation_type") or "").lower()
            if weather == "fog" and not env.get("fog_present"):
                continue
            if weather in ("rain", "snow") and ptype != weather:
                continue
            det = weather_details(r, raw)
            if weather == "fog":
                if det is None or det["visual_range"] is None or det["visual_range"] > max_visibility:
                    continue  # a default-range Fog element is not fog
                wev, wscore = f"fog: visual range {det['visual_range']:g} m", 1 + 2000 / max(det["visual_range"], 1)
            else:
                inten = next((i for t, i in (det or {}).get("precipitation", []) if str(t).lower() == weather), None)
                if inten is not None and inten <= 0:
                    continue  # declared but zero intensity
                if inten is not None and inten > 1:  # the standard's range is 0..1; larger values are placeholders
                    wev, wscore = f"{weather}: intensity {inten:g} (outside 0 to 1, not trusted)", 1
                else:
                    wev = f"{weather}" + (f": intensity {inten:g}" if inten is not None else " (intensity not checked: archive missing)")
                    wscore = 1 + (inten or 0)
            if not (topic or keyword or trigger or action):
                hits.append({"score": wscore, "evidence": [wev], **_hit(r)})
                continue
        path, names = _fields(r)
        ev, score = [], 0
        t = sorted(triggers & set(r.get("trigger_types") or []))
        a = sorted(actions & set(r.get("init_action_types") or r.get("event_action_types") or []))
        if t and not need_name:
            ev.append("trigger: " + ", ".join(t)); score += 3 * len(t)
        elif t:
            ev.append("trigger: " + ", ".join(t)); score += 1
        if a:
            ev.append("action: " + ", ".join(a)); score += 1
        if name_re:
            nm = sorted({m.group(0) for m in name_re.finditer(names)})
            pm = sorted({m.group(0) for m in name_re.finditer(path)})
            if nm:
                ev.append("name: " + ", ".join(nm)); score += 2 * len(nm)
            if pm:
                ev.append("path: " + ", ".join(pm)); score += len(pm)
        matched_name = bool(name_re) and any(e.startswith(("name", "path")) for e in ev)
        matched_struct = bool(t) or (bool(a) and not (need_name and name_re))
        if not ((matched_name) or (matched_struct and not need_name) or (matched_struct and matched_name)):
            continue
        if topic is None and not (matched_name or t or a):
            if not (entity or repo):
                continue
        if weather:
            ev.insert(0, wev); score += wscore
        hits.append({"score": score, "evidence": ev, **_hit(r)})
    hits.sort(key=lambda h: (-h["score"], not h["publish_contents"], h["repo"], h["path"]))
    if distinct:
        seen, out = set(), []
        for h in hits:
            k = h["canonical_hash"] or h["scenario_id"]
            if k in seen:
                continue
            seen.add(k); out.append(h)
        hits = out
    return hits[:limit] if limit else hits
