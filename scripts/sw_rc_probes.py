"""Run bounded native negative cases and a separate explode route-line probe."""
import argparse
from datetime import datetime, timezone
import json
import sys

from sw_incremental_plan import input_row, make_plan
from sw_supervisor import inspect, supervise
from sw_supervisor_state import OUTPUT, ROOT, atomic, read, require_workspace, safe, sha
from v03_schema import normalize

sys.path.insert(0, str(ROOT / "examples"))
from v09_guide_fixture import job, part


def staged_smoke(phase, filename):
    path = safe(OUTPUT / "run-omni-install" / phase, OUTPUT)
    state = inspect(path)
    if state["status"] != "verified" or not state["hashes_match"]:
        raise ValueError(f"Verified smoke checkpoint required: {phase}")
    return safe(path / "verified" / filename, path)


def negative_checks(run):
    pin = staged_smoke("pin", "RcPin.SLDPRT")
    root = ROOT / "outputs"
    dependency = {"id": "RcPin", "path": pin.relative_to(root).as_posix(), "sha256": sha(pin)}
    components = [
        {"id": "FixedPin", "operation": "component", "dependency": "RcPin", "location": [0, 0, 0], "fixed": True},
        {"id": "OverlapPin", "operation": "component", "dependency": "RcPin", "location": [0, 0, 4], "fixed": False},
    ]
    mates = [
        {"id": "PinOffset", "operation": "mate", "kind": "distance", "components": ["FixedPin", "OverlapPin"],
         "distance_mm": 4},
        {"id": "SameAxis", "operation": "mate", "kind": "concentric", "components": ["FixedPin", "OverlapPin"],
         "diameters": [10, 10]},
    ]
    assembly = job("RcOverlapNegative", "assembly", components + mates,
                   {"relative_positions": {row["id"]: row["location"] for row in components},
                    "mate_count": 2, "clearance_check": True}, ["sldasm"], [dependency])
    escaped = dict(dependency, path="missing-model/RcPin.SLDPRT")
    try:
        normalize(dict(assembly, dependencies=[escaped]), root)
    except (ValueError, OSError):
        lost_ref = True
    else:
        lost_ref = False
    assembly = dict(normalize(assembly, root), review_assembly=True)
    source = {"references/RcPin.SLDPRT": input_row(pin)}
    bad = part("RcWrongEdit", 10, 8)
    bad["validation"]["edit"]["geometry"]["volume_mm3"] += 1
    suites = [("interference-negative", assembly, source, ["RcOverlapNegative.SLDASM"]),
              ("edit-negative", normalize(bad, root), {}, ["RcWrongEdit.SLDPRT", "RcWrongEdit.STEP"])]
    results = {"missing_reference_preflight": lost_ref}
    for phase, spec, inputs, names in suites:
        plan = make_plan(run, phase, spec, inputs, names, inputs)
        state = inspect(run / phase)
        if state["status"] not in ("failed", "verified"):
            state = supervise(run, phase, plan)
        partial = run / state["partial"] / "native.json" if state.get("partial") else None
        data = read(partial) if partial and partial.is_file() else {}
        expected_failure = (state["status"] == "failed" and data.get("documentCountAfter") == 0
                            and (bool(data.get("solidInterferences")) if phase == "interference-negative"
                                 else "solid volume" in data.get("error", "") and "edit" in data.get("stage", "")))
        results[phase] = {"expected_rejection": expected_failure, "stage": state.get("stage"),
                          "nativeInterferences": data.get("solidInterferences"), "failure": state.get("failure")}
    atomic(run / "NEGATIVE_CHECKS.json", results)
    print(json.dumps(results, ensure_ascii=True), flush=True)


def route(run, edges):
    mount = staged_smoke("mount", "RcMount.SLDASM")
    refs = [mount.parent / "references" / name for name in ("RcSeat.SLDPRT", "RcPin.SLDPRT")]
    inputs = {"checkpoint.SLDASM": input_row(mount)}
    inputs.update({f"references/{path.name}": input_row(path) for path in refs})
    spec = {"document_type": "assembly", "outputs": {"name": "RcMountRoute"},
            "dependencies": [{"id": path.stem} for path in refs],
            "route_probe": {"first": "RcSeat", "second": "RcPin", "diameter": 10, "circular_edges": edges}}
    phase = "route-r1" if edges else "route"
    plan = make_plan(run, phase, spec, inputs, ["RcMountRoute.SLDASM"], inputs)
    result = supervise(run, phase, plan)
    print({key: result.get(key) for key in ("status", "stage", "call", "failure", "events")}, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("negative", "route"))
    parser.add_argument("--edges", action="store_true")
    args = parser.parse_args()
    require_workspace(allow_installed=True)
    run = safe(OUTPUT / ("run-omni-" + args.mode), OUTPUT)
    run.mkdir(parents=True, exist_ok=True)
    baseline = run / "BASELINE.json"
    if not baseline.exists():
        atomic(baseline, {"started": datetime.now(timezone.utc).isoformat(), "revision": "22.0.0"})
    if args.mode == "negative":
        negative_checks(run)
    else:
        route(run, args.edges)


if __name__ == "__main__":
    main()
