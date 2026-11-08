---
name: find-scenarios
description: Find OpenSCENARIO driving scenarios in the ScenarioMine corpus for a topic such as collisions, near misses, cut-ins, pedestrian crossings, intersections or speed bumps. Returns ranked hits with the evidence, licence and a GitHub permalink. Use when the user asks to find, list or pick scenarios for an autonomous-driving test or study.
argument-hint: "<topic or description, e.g. 'near miss with pedestrian'>"
---

# find-scenarios

Searches the parsed corpus (`parsed/file_versions.*`, or the bundled five-repository sample in `data/sample/`) with `uv run python -m scenariomine find`. Evidence comes from what the parser extracted: trigger types, action types, entity, maneuver and parameter names, and the file path. Only the weather filter reads the local archive (fog visibility, rain intensity); it never changes or copies files.

## Pick the data

- Full corpus: `--data parsed` (default). Exists only after the pipeline has run locally; check `ls parsed/file_versions.*`. If missing, say so and either use `--data data/sample` (5 repositories, about 340 scenarios) or offer the `mine-scenarios` skill.
- Always run with `uv run --extra parquet python -m scenariomine find ...` (Parquet needs pyarrow).

## Map the request to a command

| User asks for | Command |
| --- | --- |
| collisions, crashes | `find --topic collision` (triggers `collision_condition`, `time_to_collision_condition`, plus names) |
| near misses, emergency braking, AEB, close calls | `find --topic near_miss` (TTC, clearance and headway triggers plus names). Say it is a proxy: no scenario file states "near miss" |
| cut-in / cut-out | `find --topic cut_in` |
| pedestrians, crossings, cyclists | `find --topic pedestrian` |
| intersections, junctions, turns | `find --topic intersection` |
| speed bumps, humps, potholes | `find --topic speed_bump`, then see the note below |
| rain, snow | `find --weather rain` (declared precipitation with intensity above 0, read from the archive; combine with `--topic pedestrian`, `--entity vehicle`, etc.) |
| fog, poor visibility | `find --weather fog` (visual range at most `--max-visibility`, default 2000 m) |
| anything else | `find --keyword "<regex>"`, optionally `--trigger`, `--action`, `--entity` (vehicle, pedestrian, misc_object), `--repo` |

Useful flags: `--publishable` (only files whose contents may be redistributed), `--limit N`, `--all-copies` (do not collapse identical content), `--json`. Combine a topic with `--entity pedestrian` to narrow it.

## Weather: rain and fog

Weather is a parsed field, but read it with care:

- **Fog.** The parsed `fog_present` flag only means a `<Fog>` element exists. 3,971 of the 3,981 scenarios with a weather block have one, almost all at the simulator default (visual range 10,000 to 100,000 m). So `--weather fog` reads `visualRange` from the local archive and keeps only values at or below `--max-visibility`. At the last run: 158 distinct scenarios up to 2,000 m, most of them 500 m or less. Never report `fog_present` as "has fog".
- **Rain/snow.** Uses the declared precipitation type and requires intensity above 0. Intensity should lie in 0 to 1; larger values (for example 11110, seen in a CARLA-derived set) are placeholders, shown as "not trusted" and not used for ranking. At the last run: 607 distinct rain scenarios, only 44 with publishable contents; snow is nearly absent (4 files).
- Both need `raw/` on disk for the visibility and intensity values. Without it (for example with `--data data/sample` alone), rain falls back to the parsed type and fog returns nothing; say so.
- Weather declared in the file only. A scenario can also change weather at run time (`environment_action`) or reference an environment catalogue (not resolved); neither is detected here.

## Speed bumps and road-surface features: be honest

OpenSCENARIO describes actors, maneuvers and triggers. It has no element for road-surface features; speed bumps, potholes and manholes belong to the OpenDRIVE road network (`.xodr`), which is outside this corpus. So `speed_bump` only matches names, and at the last run found **0** scenarios. Say that plainly. Offer, clearly labelled as proxies:

- objects placed on the road: `find --entity misc_object --keyword "(?<![a-z])patch(?![a-z])|obstacle|barrier|roadmark"` (MiscObject categories `obstacle`, `patch`, `roadMark`, `barrier`);
- the road network each scenario references (`road_network.logic_file`) if the user wants to look for OpenDRIVE files with bump features outside this corpus;
- or the scenarios with speed changes near an object (`--action speed_action --entity misc_object`).

Never present a name match as a verified speed-bump scenario.

## Presenting results

For each hit show: repository and path, OpenSCENARIO version, the evidence line (what matched), licence, and whether contents are publishable or the record is pointer-only, then the permalink. Group near-identical hits (the tool already collapses identical content; copies in several repositories are marked `--all-copies` only). Lead with 5 to 10 hits, then say how many more there are.

Then say what the evidence does not prove: ranking is a heuristic, precision has not been measured, and a trigger such as `collision_condition` shows the scenario checks for a collision, not that it stages one. Offer to open the top files to confirm. When the user wants a file:

- `contents ok` (permissive or weak-copyleft, and first seen in a permissive repository): the file can be shared with its repository's licence and attribution.
- `pointer only` (no licence, copyleft, non-commercial or restricted): give the permalink; reading the local copy under `raw/` for the user's own inspection is fine, but do not paste it into committed files, papers or datasets.

## Limits to mention when relevant

Default branch only; latest version of each file; catalogue references are not resolved; versions outside OpenSCENARIO 1.0 to 1.3 are only partly parsed; `yangyh408/onsite-test-server` is not in the corpus yet; many files are copies of simulator examples (about 39% were first seen in another repository).
