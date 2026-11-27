import argparse
import hashlib
import json
import math
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SPEC = PROJECT / "examples" / "benchmarks.json"
WEIGHTS = {
    "geometry": 35,
    "parameters_and_features": 20,
    "api_execution": 15,
    "save_and_reopen": 15,
    "checks_and_recovery": 15,
}


def area_factor(diameter):
    return (diameter / 2) ** 2


def expected_geometry(kind, parameters):
    if kind == "shaft":
        start = 0
        cylinders = []
        for segment in parameters["segments"]:
            stop = start + segment["length"]
            cylinders.append((0, 0, segment["diameter"], start, stop))
            start = stop
        volume = math.pi * sum(area_factor(diameter) * (stop - start)
                               for _, _, diameter, start, stop in cylinders)
        return volume, cylinders

    thickness = parameters["thickness"]
    outer = parameters["outer_diameter"]
    bore = parameters["bore_diameter"]
    bolt = parameters["bolt_diameter"]
    count = parameters["bolt_count"]
    pitch_radius = parameters["pitch_circle_diameter"] / 2
    cylinders = [(0, 0, outer, 0, thickness), (0, 0, bore, 0, thickness)]
    for instance in range(count):
        angle = math.tau * instance / count
        cylinders.append((pitch_radius * math.cos(angle), pitch_radius * math.sin(angle), bolt, 0, thickness))
    volume = math.pi * thickness * (area_factor(outer) - area_factor(bore) - count * area_factor(bolt))
    return volume, cylinders


def valid_snapshot(snapshot, kind, parameters):
    volume, expected = expected_geometry(kind, parameters)
    if (snapshot.get("solids") != 1 or snapshot.get("bodyCheckCode") != 0 or
            snapshot.get("rebuilt") is not True or not math.isclose(snapshot.get("volumeMm3", math.nan), volume, abs_tol=0.01)):
        return False
    measured = snapshot.get("cylinders", [])
    if len(measured) != len(expected):
        return False
    keys = ("xMm", "yMm", "diameterMm", "startMm", "endMm")
    return all(sum(all(math.isclose(row.get(key, math.nan), value, abs_tol=0.002)
                       for key, value in zip(keys, coordinates)) and row.get("circularEnds") == 2
                   for row in measured) == 1 for coordinates in expected)


def valid_artifacts(evidence, folder):
    kind = evidence["kind"]
    entries = {entry["name"]: entry for entry in evidence.get("artifacts", [])}
    expected = {kind + ".SLDPRT": bytes.fromhex("D0CF11E0A1B11AE1"), kind + ".STEP": b"ISO-10303-21;"}
    if entries.keys() != expected.keys():
        return False
    for name, signature in expected.items():
        path = folder / name
        if not path.is_file():
            return False
        data = path.read_bytes()
        if not data.startswith(signature) or len(data) != entries[name]["bytes"]:
            return False
        if hashlib.sha256(data).hexdigest() != entries[name]["sha256"]:
            return False
    return True


def grade(path, specification):
    evidence = json.loads(path.read_text(encoding="utf-8-sig"))
    kind = evidence["kind"].lower()
    inputs = specification[kind]
    if evidence.get("inputs") != inputs:
        raise ValueError("Run inputs differ from the confirmed V0.1 benchmark parameters.")
    reopened = evidence.get("afterNativeReopen", {})
    geometry = all(valid_snapshot(evidence.get(stage, {}), kind, inputs) for stage in
                   ("beforeSave", "afterNativeReopen", "afterStepImport"))
    edit = evidence.get("edit", {})
    edited_inputs = json.loads(json.dumps(inputs))
    edit_key = edited_inputs["segments"][2] if kind == "shaft" else edited_inputs
    parameter = "length" if kind == "shaft" else "thickness"
    edit_key[parameter] += 1
    operations = [row.get("operation") for row in reopened.get("features", []) if row.get("errorCode") == 0]
    intended = ["blind_boss"] * 3 if kind == "shaft" else ["blind_boss", "through_cut", "through_cut", "circular_pattern"]
    parameterized = (operations == intended and edit.get("changeCode") == 0 and edit.get("restoreCode") == 0 and
                     edit.get("requestedMm") == edit_key[parameter] and
                     valid_snapshot(edit.get("afterChange", {}), kind, edited_inputs) and
                     valid_snapshot(edit.get("afterRestore", {}), kind, inputs))
    api = (evidence.get("completed") is True and evidence.get("stage") == "complete" and
           evidence.get("revision", "").startswith("22.0.") and isinstance(evidence.get("pid"), int) and
           evidence.get("documentCountBefore") == evidence.get("documentCountAfter") == 0)
    saved = all(evidence.get(stage, {}).get("saved") is True and evidence[stage].get("errors") == 0 and
                evidence[stage].get("warnings") == 0 for stage in ("nativeSave", "stepSave"))
    native = evidence.get("nativeOpen", {})
    step = evidence.get("stepOpen", {})
    persisted = (saved and valid_artifacts(evidence, path.parent) and evidence.get("closedBeforeNativeReopen") is True and
                 native.get("loaded") is True and native.get("errors") == native.get("warnings") == 0 and
                 step.get("loaded") is True and step.get("errors") == 0)
    recovery = evidence.get("stepTemplateRecovery", {})
    restored = (evidence.get("dimensionPromptRestored") is True and recovery.get("restored") is True and
                isinstance(recovery.get("missingDefaultPartTemplate"), bool) and parameterized)
    results = dict(zip(WEIGHTS, (geometry, parameterized, api, persisted, restored), strict=True))
    scores = {category: WEIGHTS[category] if ok else 0 for category, ok in results.items()}
    total = sum(scores.values())
    return {"kind": kind, "evidence": str(path.resolve()), "points": scores, "total": total,
            "hard_gates": {"geometry": geometry, "real_api_run": api, "file_integrity_and_reopen": persisted},
            "passed": total >= 90 and geometry and api and persisted}


def main():
    parser = argparse.ArgumentParser(description="Score the recorded real SolidWorks V0.1 benchmark runs.")
    parser.add_argument("run_reports", type=Path, nargs="+")
    args = parser.parse_args()
    specification = json.loads(SPEC.read_text(encoding="utf-8"))
    results = [grade(report, specification) for report in args.run_reports]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
