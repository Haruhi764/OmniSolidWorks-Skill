"""Create a multi-station fixture assembly from verified native guide modules."""
import argparse
from datetime import datetime, timezone
import json

from sw_explosion_plan import evaluate_path
from sw_incremental_plan import input_row, make_plan
from sw_supervisor import supervise
from sw_supervisor_state import OUTPUT, ROOT, atomic, read, require_workspace, safe


def create_job(count, sources):
    module = next(path for path in sources if path.endswith(".SLDASM"))
    model_id = module.split("/")[-1].removesuffix(".SLDASM")
    parts = sorted(PathName.split("/")[-1].removesuffix(".SLDPRT")
                   for PathName in sources if PathName.endswith(".SLDPRT"))
    rows = []
    for index in range(count):
        rows.append({"id": f"Station{index + 1}", "operation": "component", "dependency": model_id,
                     "location": [250 * (index % 3), 180 * (index // 3), 0],
                     "fixed": index != count - 1})
    mate = {"id": "CommonMountPlane", "operation": "mate", "kind": "coincident",
            "components": [rows[0]["id"], rows[-1]["id"]]}
    steps = [{"id": f"LiftModule{index}", "operation": "explode", "components": [row["id"]],
              "axis_component": "StationDatum", "distance_mm": 70 + 12 * index, "direction": "+z"}
             for index, row in enumerate(rows[1:], 1)]
    return {"document_type": "assembly", "schema_version": 2, "hierarchy": True,
            "subassembly": model_id, "child_parts": parts, "anchor": rows[0]["id"],
            "datum_part": "FixtureBase", "features": rows + [mate] + steps,
            "validation": {"relative_positions": {row["id"]: row["location"] for row in rows},
                           "mate_count": 1, "leaf_count": 18 * count, "clearance_check": True},
            "outputs": {"name": "MultiStationFixture"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations", type=int, choices=range(2, 9), default=6)
    parser.add_argument("--phase", choices=("hierarchy", "hierarchy-r1", "hierarchy-r2"), default="hierarchy")
    parser.add_argument("--cross-level", action="store_true")
    args = parser.parse_args()
    require_workspace(allow_installed=True)
    root = safe(ROOT / "outputs" / "release-sprint" / "local-native-case")
    if read(root / "DELIVERY_VERIFIED.json")["status"] != "PASS":
        raise ValueError("The staged fixture dependency source did not pass reference verification")
    sources = {"references/GuideFixture.SLDASM": input_row(root / "references" / "GuideFixture.SLDASM")}
    sources.update({f"references/references/{path.name}": input_row(path)
                    for path in (root / "references" / "references").glob("*.SLDPRT")
                    if not path.name.startswith("~$")})
    if len(sources) != 9:
        raise ValueError("Expected one qualified module and eight independent part files")
    run = safe(OUTPUT / ("run-omni-cross-level" if args.cross_level else "run-omni-hierarchy"), OUTPUT)
    run.mkdir(parents=True, exist_ok=True)
    baseline = run / "BASELINE.json"
    if not baseline.exists():
        atomic(baseline, {"started": datetime.now(timezone.utc).isoformat(), "revision": "22.0.0"})
    job = create_job(args.stations, sources)
    if args.cross_level:
        leaf = {"id": "LiftLooseSupport", "operation": "explode", "components": ["NestedPad"],
                "axis_component": "StationDatum", "distance_mm": 24, "direction": "+z"}
        job["cross_level"] = {"parent": "Station2", "leaf": "SupportPad-1", "alias": "NestedPad"}
        job["features"].append(leaf)
        # Parent and child envelopes are not independent solid interference pairs.
        job["validation"]["clearance_check"] = False
    plan = make_plan(run, args.phase, job, sources,
                     ("MultiStationFixture.SLDASM", "Collapsed.bmp", "Exploded.bmp"), sources)
    state = supervise(run, args.phase, plan)
    print({key: state.get(key) for key in ("status", "stage", "failure")}, flush=True)
    if state["status"] != "verified":
        return 1
    report = read(run / args.phase / "verified" / "native.json")
    steps = [row for row in job["features"] if row["operation"] == "explode"]
    parent_steps = [step for step in steps if set(step["components"]) <= report["moduleBoxesMm"].keys()]
    _, sweep = evaluate_path(report["moduleBoxesMm"], parent_steps)
    atom = {"leaf_instances": report["assemblyTree"]["partInstances"],
            "subassembly_instances": report["assemblyTree"]["subassemblyInstances"],
            "independent_files": report["assemblyTree"]["independentPartFiles"],
            "native_top_mates": len(report["reopenedAssembly"]["mates"]),
            "native_top_steps": len(report["reopenedExplosion"]["steps"]),
            "cross_level_direct_instance": report.get("crossLevelDirectInstance"),
            "cross_level_delta_mm": report["reopenedExplosion"]["deltaMm"].get("NestedPad"),
            "observed_transforms": report.get("crossLevelObservedOccurrences"),
            "source_child_native_steps": report["sourceChildExplodeSteps"],
            "sweep_proxy": sweep, "solid_interferences": report["solidInterferences"]}
    atomic(run / f"{args.phase}-summary.json", atom)
    print(json.dumps(atom, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
