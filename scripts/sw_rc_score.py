"""Evaluate the original seven-weight release gate from local run evidence."""
from datetime import datetime, timezone
from collections import Counter

from sw_supervisor import inspect
from sw_supervisor_state import OUTPUT, ROOT, atomic, read, require_workspace


def check(run, phase):
    directory = OUTPUT / run / phase
    state = inspect(directory)
    if state["status"] != "verified" or not state["hashes_match"]:
        return {}
    return read(directory / "verified" / "native.json")


def main():
    require_workspace()
    current = ROOT / "outputs" / "omnisolidworks-rc"
    base = read(ROOT / "outputs" / "release-sprint" / "acceptance.json")
    hierarchy = check("run-omni-hierarchy", "hierarchy")
    bearing = check("run-omni-bearing-drawing", "bearing")
    bearing_sh = check("run-omni-bearing-drawing", "bearing-drawing-r3")
    fixture_sh = check("run-omni-fixture", "fixture-drawing")
    a2 = bearing_sh.get("reopenedDrawing", {})
    a2_views = {v["role"]: v for v in a2.get("views", [])}
    a2_front = Counter(round(row["valueMm"], 5) for row in a2_views.get("Front", {}).get("dimensions", []))
    centers = {tuple(round(value, 6) for value in row[:2]) for row in bearing_sh.get("centerMarkLocationsMm", [])}
    a2_pass = (a2.get("sheetMm") == [594, 420] and a2.get("firstAngle") is True and
               "Section" in a2_views and a2_front[80] == a2_front[50] == a2_front[30] == 1 and
               a2_front[8] == 2 and a2_views["Front"]["centerMarks"] >= 3 and
               centers == {(-28, 0), (0, 0), (28, 0)})
    tree = hierarchy.get("assemblyTree", {})
    nested_pass = (tree.get("maxDepth") == 2 and tree.get("subassemblyInstances") == 6 and
                   tree.get("partInstances") == 108 and tree.get("independentPartFiles") == 8 and
                   tree["missing"] == tree["unresolved"] == [] and hierarchy["solidInterferences"] == [] and
                   len(hierarchy["reopenedAssembly"]["mates"]) == 1 and
                   len(hierarchy["reopenedExplosion"]["steps"]) == 5)
    gb_fixture = read(OUTPUT / "run-omni-fixture" / "GB_FIXTURE_CHECK.json")
    negative = read(OUTPUT / "run-omni-negative" / "NEGATIVE_CHECKS.json")
    negatives = (negative["missing_reference_preflight"] and
                 all(negative[key]["expected_rejection"] for key in ("interference-negative", "edit-negative")) and
                 all(row["exit"] == 0 for row in read(current / "offline-tests.json")))
    install_record = current / "isolated-install.json"
    installed = read(install_record) if install_record.is_file() else {}
    isolated = (installed.get("installer", {}).get("status") == "PASS" and
                installed["installer"]["smoke"]["status"] == "PASS" and installed["native_demo"] == "PASS")
    route_start = [check("run-omni-route", name) for name in ("route", "route-r1")]
    route_pass = any(row.get("nativeRouteLineCreated") is True and row.get("reopenedAssembly") for row in route_start)

    scores = {name: dict(row) for name, row in base["scores"].items()}
    scores["assembly_and_constraints"]["earned"] += 3 * nested_pass
    scores["drawing_and_bom"]["earned"] += int(a2_pass)
    scores["automated_acceptance"]["earned"] += int(negatives)
    if not isolated:
        scores["deployment_and_portability"]["earned"] = 0
    measured = bearing.get("reopenedGeometry", {}).get("centroidMm", [])
    centroid_ok = len(measured) == 3 and all(abs(a - b) <= .003 for a, b in zip(measured, (0, 0, 10), strict=True))
    hard = dict(base["hard_gates"], fresh_install_smoke=isolated,
                new_native_geometry=centroid_ok,
                new_native_references=nested_pass,
                new_drawing_readback=bool(fixture_sh and a2_pass and gb_fixture["passed"]),
                required_native_route_line=route_pass,
                public_license_confirmed=False)
    total = sum(row["earned"] for row in scores.values())
    started = datetime.fromisoformat(read(current / "start.json")["started_utc"])
    result = {"host": "22.0.0", "status": "formal candidate" if total >= 90 and all(hard.values()) else "RC1",
              "total": total, "scores": scores, "hard_gates": hard, "case_a2": a2_pass, "case_c": nested_pass,
              "case_e": negatives, "development_elapsed_seconds": round((datetime.now(timezone.utc) - started).total_seconds())}
    atomic(current / "acceptance.json", result)
    import json
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
