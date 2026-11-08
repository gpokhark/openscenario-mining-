"""Step 4: turn one .xosc blob into a structured record.

parse_blob() is pure (bytes in, dict out). Every key in FIELDS is always
present so records share one schema; fields that do not apply to a file type
are null (scalars) or empty (lists). Files are never dropped: invalid XML,
non-OpenSCENARIO roots and out-of-range versions get a record with
file_type / osc_version_in_range / parse_error saying why.
"""
import copy
import hashlib

from lxml import etree

from . import schemas
from .vocab import classify_action, classify_condition, snake

DESC_CAP = 500
ENTITY_KINDS = {"Vehicle": ("vehicle", "vehicleCategory"),
                "Pedestrian": ("pedestrian", "pedestrianCategory"),
                "MiscObject": ("misc_object", "miscObjectCategory")}
CATALOG_LOCATIONS = "CatalogLocations"


def empty():
    return {
        "file_type": None, "parse_error": None,
        "osc_version": None, "osc_rev_major": None, "osc_rev_minor": None,
        "osc_version_in_range": None,
        "xsd_version": None, "validates_against_xsd": None,
        "xsd_error_count": None, "xsd_first_error": None,
        "header_description": None, "header_date": None,
        "canonical_hash": None, "maneuver_names": [],
        "entities": [], "n_entities": None, "n_vehicles": None,
        "n_pedestrians": None, "n_misc_objects": None, "n_catalog_entities": None,
        "n_stories": None, "n_acts": None, "n_maneuver_groups": None,
        "n_maneuvers": None, "n_events": None, "n_event_actions": None,
        "n_init_actions": None, "n_conditions": None,
        "init_action_types": [], "event_action_types": [],
        "action_families": [], "trigger_types": [],
        "environment": None, "parameters": [], "catalog_refs": [],
        "catalog_locations": [], "road_network": None,
        "catalog_name": None, "catalog_entries": [],
        "scenario_file": None, "distribution_kind": None,
    }


FIELDS = tuple(empty())


class Validators:
    """Lazily compiled XSDs keyed by XSD version."""

    def __init__(self, directory):
        self.directory, self._cache = directory, {}

    def get(self, version):
        if version not in self._cache:
            p = schemas.path(self.directory, version)
            self._cache[version] = etree.XMLSchema(etree.parse(str(p))) if p.exists() else None
        return self._cache[version]


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = el.tag.split("}", 1)[1]


def _kids(el, tag=None):
    return [c for c in el if isinstance(c.tag, str) and (tag is None or c.tag == tag)]


def _trim(s, n=DESC_CAP):
    return s[:n] if s else s


def parse_blob(data, validators):
    out = empty()
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True,
                                 load_dtd=False, huge_tree=False)
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as e:
        out.update(file_type="invalid_xml", parse_error=str(e)[:300])
        return out
    _strip_ns(root)
    out["canonical_hash"] = _canonical_hash(root)
    if root.tag != "OpenSCENARIO":
        out.update(file_type="not_openscenario", parse_error=f"root element is {root.tag}")
        return out

    header = next(iter(_kids(root, "FileHeader")), None)
    major = _int(header.get("revMajor")) if header is not None else None
    minor = _int(header.get("revMinor")) if header is not None else None
    out.update(
        osc_rev_major=major, osc_rev_minor=minor,
        osc_version=f"{major}.{minor}" if major is not None and minor is not None else None,
        osc_version_in_range=major == 1 and minor in schemas.BY_MINOR,
        header_description=_trim(header.get("description")) if header is not None else None,
        header_date=header.get("date") if header is not None else None)

    body = [c for c in _kids(root) if c.tag != "FileHeader"]
    tags = {c.tag for c in body}
    # Out-of-range versions are classified but not parsed past the header (docs/step2-scope.md).
    detail = out["osc_version_in_range"]
    if "Storyboard" in tags:
        out["file_type"] = "scenario"
        if detail:
            _scenario(root, out)
    elif "Catalog" in tags:
        out["file_type"] = "catalog"
        if detail:
            _catalog(next(c for c in body if c.tag == "Catalog"), out)
    elif "ParameterValueDistribution" in tags:
        out["file_type"] = "parameter_distribution"
        if detail:
            _distribution(next(c for c in body if c.tag == "ParameterValueDistribution"), out)
    else:
        out.update(file_type="unknown", parse_error="no Storyboard, Catalog or ParameterValueDistribution")

    if out["osc_version_in_range"]:
        _validate(data, out, validators)
    return out


def _canonical_hash(root):
    """SHA-256 of the canonical (C14N) form with comments, processing
    instructions and whitespace-only text removed, so formatting-only edits
    hash identically. Unresolved entity references are kept as written."""
    root = copy.deepcopy(root)
    for el in list(root.iter()):
        if isinstance(el, (etree._Comment, etree._ProcessingInstruction)):
            el.getparent().remove(el)  # lxml keeps the removed node's tail
            continue
        if not isinstance(el.tag, str):
            continue  # entity reference
        for attr in ("text", "tail"):
            v = getattr(el, attr)
            if v is not None and not v.strip():
                setattr(el, attr, None)
    return hashlib.sha256(etree.tostring(root, method="c14n")).hexdigest()


def _validate(data, out, validators):
    version = schemas.BY_MINOR[out["osc_rev_minor"]]
    out["xsd_version"] = version
    xsd = validators.get(version)
    if xsd is None:
        return  # schema not fetched: leave validates_against_xsd null
    try:
        doc = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return
    # xsi:* attributes (e.g. noNamespaceSchemaLocation) are not content and the
    # XSD does not declare them; strip so a file is not failed for carrying them.
    for el in doc.iter():
        for a in [a for a in el.attrib if a.startswith("{http://www.w3.org/2001/XMLSchema-instance}")]:
            del el.attrib[a]
    ok = xsd.validate(doc)
    out["validates_against_xsd"] = ok
    out["xsd_error_count"] = len(xsd.error_log)
    out["xsd_first_error"] = _trim(str(xsd.error_log[0].message), 300) if not ok else None


def _catalog_refs(root):
    return [{"catalog_name": r.get("catalogName"), "entry_name": r.get("entryName")}
            for r in root.iter("CatalogReference")]


def _scenario(root, out):
    out["parameters"] = [
        {"name": p.get("name"), "type": p.get("parameterType"), "value": p.get("value")}
        for pd in _kids(root, "ParameterDeclarations") for p in _kids(pd, "ParameterDeclaration")]
    out["catalog_refs"] = _catalog_refs(root)
    for cl in _kids(root, CATALOG_LOCATIONS):
        for loc in _kids(cl):
            d = next(iter(_kids(loc, "Directory")), None)
            out["catalog_locations"].append(
                {"kind": snake(loc.tag), "path": d.get("path") if d is not None else None})
    rn = next(iter(_kids(root, "RoadNetwork")), None)
    if rn is not None:
        lf, sg = (next(iter(_kids(rn, t)), None) for t in ("LogicFile", "SceneGraphFile"))
        out["road_network"] = {"logic_file": lf.get("filepath") if lf is not None else None,
                               "scene_graph_file": sg.get("filepath") if sg is not None else None}

    ents = [e for ents in _kids(root, "Entities") for e in _kids(ents, "ScenarioObject")]
    for so in ents:
        inner = next(iter(c for c in _kids(so) if c.tag in ENTITY_KINDS or c.tag == "CatalogReference"), None)
        if inner is None:  # a ScenarioObject with no Vehicle/Pedestrian/MiscObject/CatalogReference
            out["entities"].append({"name": so.get("name"), "type": "unspecified", "category": None})
        elif inner.tag == "CatalogReference":
            out["entities"].append({"name": so.get("name"), "type": "catalog_reference", "category": None})
        else:
            kind, attr = ENTITY_KINDS[inner.tag]
            out["entities"].append({"name": so.get("name"), "type": kind, "category": inner.get(attr)})
    count = lambda t: sum(e["type"] == t for e in out["entities"])
    out.update(n_entities=len(out["entities"]), n_vehicles=count("vehicle"),
               n_pedestrians=count("pedestrian"), n_misc_objects=count("misc_object"),
               n_catalog_entities=count("catalog_reference"))

    sb = next(iter(_kids(root, "Storyboard")))
    init_types, event_types, families = set(), set(), set()
    n_init = 0
    for a in sb.iterfind("Init/Actions/*"):
        wrapped = _kids(a) if a.tag == "Private" else [a]
        for act in wrapped:
            if act.tag in ("GlobalAction", "UserDefinedAction", "PrivateAction"):
                for fam, term in classify_action(act):
                    init_types.add(term); families.add(fam)
                n_init += 1
    n_event_actions = 0
    for ev in sb.iter("Event"):
        for act in _kids(ev, "Action"):
            n_event_actions += 1
            inner = next(iter(_kids(act)), None)
            if inner is None:
                continue
            if inner.tag == "CatalogReference":
                event_types.add("catalog_reference"); families.add("catalog")
            else:
                for fam, term in classify_action(inner):
                    event_types.add(term); families.add(fam)
    triggers, n_cond = set(), 0
    for trig in list(sb.iter("StartTrigger")) + list(sb.iter("StopTrigger")):
        for cond in trig.iter("Condition"):
            n_cond += 1
            triggers.add(classify_condition(cond))
    out.update(
        n_stories=len(list(sb.iter("Story"))), n_acts=len(list(sb.iter("Act"))),
        n_maneuver_groups=len(list(sb.iter("ManeuverGroup"))),
        n_maneuvers=len(list(sb.iter("Maneuver"))),
        maneuver_names=[m.get("name") for m in sb.iter("Maneuver")], n_events=len(list(sb.iter("Event"))),
        n_event_actions=n_event_actions, n_init_actions=n_init, n_conditions=n_cond,
        init_action_types=sorted(init_types), event_action_types=sorted(event_types),
        action_families=sorted(families), trigger_types=sorted(triggers),
        environment=_environment(root))


def _environment(root):
    envs = list(root.iter("Environment"))
    weather = next(iter(w for e in envs for w in _kids(e, "Weather")), None)
    precip = next(iter(weather.iter("Precipitation")), None) if weather is not None else None
    road = next(iter(r for e in envs for r in _kids(e, "RoadCondition")), None)
    friction = road.get("frictionScaleFactor") if road is not None else None
    return {
        "n_environment_definitions": len(envs),
        "weather_present": weather is not None,
        "precipitation_type": precip.get("precipitationType") if precip is not None else None,
        "fog_present": weather is not None and next(iter(weather.iter("Fog")), None) is not None,
        "time_of_day_present": any(_kids(e, "TimeOfDay") for e in envs),
        "road_condition_present": road is not None,
        "road_friction_scale": friction,
    }


def _catalog(cat, out):
    out["catalog_name"] = cat.get("name")
    out["catalog_entries"] = [{"kind": snake(e.tag), "name": e.get("name")} for e in _kids(cat)]


def _distribution(dist, out):
    sf = next(iter(_kids(dist, "ScenarioFile")), None)
    out["scenario_file"] = sf.get("filepath") if sf is not None else None
    for kind in ("Deterministic", "Stochastic"):
        if _kids(dist, kind):
            out["distribution_kind"] = kind.lower()
