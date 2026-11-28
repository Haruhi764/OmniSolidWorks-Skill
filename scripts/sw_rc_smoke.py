"""Repeatable native part, assembly and drawing verification in an isolated install."""
import argparse
from datetime import datetime, timezone
import json
import sys

from omni_gb import audit
from sw_release_case import dependency, execute
from v03_jobs import preflight
from sw_supervisor_state import OUTPUT, ROOT, atomic, read, require_workspace, safe

sys.path.insert(0, str(ROOT / "examples"))
from v09_guide_fixture import drawing, job, part


def build_demo(run):
    pin_spec = part("RcPin", 10, 8)
    for row, thickness in ((pin_spec["validation"], 8), (pin_spec["validation"]["edit"]["geometry"], 9)):
        row["centroid_mm"] = [0, 0, thickness / 2]
    ring_spec = part("RcSeat", 30, 6, [(10, (0, 0))])
    ring = execute(run, "seat", ring_spec)
    pin = execute(run, "pin", pin_spec)
    components = [
        {"id": "Seat", "operation": "component", "dependency": ring.stem, "location": [0, 0, 0], "fixed": True},
        {"id": "Pin", "operation": "component", "dependency": pin.stem, "location": [0, 0, 0], "fixed": False},
    ]
    mates = [
        {"id": "AxialSeat", "operation": "mate", "kind": "coincident", "components": ["Seat", "Pin"]},
        {"id": "PinAxis", "operation": "mate", "kind": "concentric", "components": ["Seat", "Pin"],
         "diameters": [10, 10]},
    ]
    explode = [{"id": "WithdrawPin", "operation": "explode", "components": ["Pin"], "axis_component": "Seat",
                "axis_diameter": 10, "distance_mm": 28, "direction": "+z"}]
    spec = job("RcMount", "assembly", components + mates + explode,
               {"relative_positions": {r["id"]: r["location"] for r in components},
                "mate_count": 2, "clearance_check": True}, ["sldasm"], map(dependency, (ring, pin)))
    native = execute(run, "mount", spec, options={"review_assembly": True})
    references = [native.parent / "references" / source.name for source in (ring, pin)]
    plans = [{"id": "Sheet1", "operation": "drawing_sheet", "paper": "a3", "exploded": True, "bom": True,
              "title": "Pin and locating seat", "drawing_number": "RP-00"}]
    spec = job("RcMountDrawing", "drawing", plans, {"component_count": 2, "dimensions_mm": []},
               ["slddrw", "pdf", "dwg", "dxf"], map(dependency, [native, *references]))
    execute(run, "mount-drawing", spec)
    data = read(run / "mount-drawing" / "verified" / "native.json")["reopenedDrawing"]
    result = audit({"paper": "A3", "view_scale": data["scale"], "bom": {"RcSeat": 1, "RcPin": 1}}, data)
    atomic(run / "GB_DEMO_CHECK.json", result)
    if not result["passed"]:
        raise ValueError("Native GB demonstration did not pass its plan")


def bearing(run, drawing_phase):
    spec = read(ROOT / "examples" / "v03" / "D-BearingBlock.json")
    spec["job_id"] = spec["outputs"]["name"] = "RcBearingBlock"
    spec["validation"]["centroid_mm"] = [0, 0, 10]
    spec["validation"]["edit"]["geometry"]["centroid_mm"] = [0, 0, 10.5]
    model = execute(run, "bearing", spec)
    if drawing_phase:
        features = [{"id": "Sheet1", "operation": "drawing_sheet", "paper": "a2", "section": True,
                     "center_marks": True, "title": "Bearing support block", "drawing_number": "BR-01",
                     "witness_dimensions": [{"view": "Front", "part": model.stem, "model_axis": axis, "mm": value}
                                            for axis, value in ((0, 80), (1, 50))]}]
        sheet = job("RcBearingDrawing", "drawing", features, {"dimensions_mm": [80, 50, 20, 30]},
                    ["slddrw", "pdf", "dwg", "dxf"], [dependency(model)])
        execute(run, drawing_phase, sheet)


def fixture_drawing(run):
    root = safe(ROOT / "outputs" / "release-sprint" / "local-native-case")
    report = read(root / "DELIVERY_VERIFIED.json")
    if report["status"] != "PASS":
        raise ValueError("The previous fixture does not have verified reference evidence")
    source = root / "references" / "GuideFixture.SLDASM"
    paths = sorted(p for p in (source.parent / "references").glob("*.SLDPRT") if not p.name.startswith("~$"))
    spec = drawing(map(dependency, [source, *paths]))
    execute(run, "fixture-drawing", spec)
    data = read(run / "fixture-drawing" / "verified" / "native.json")["reopenedDrawing"]
    contract = read(ROOT / "examples" / "gb_fixture_plan.json")
    result = audit(contract, data)
    atomic(run / "GB_FIXTURE_CHECK.json", result)
    if not result["passed"]:
        raise ValueError("Fixture drawing did not pass the GB contract")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("install", "bearing", "bearing-drawing", "fixture"))
    parser.add_argument("--drawing-phase", choices=("bearing-drawing", "bearing-drawing-r1", "bearing-drawing-r2", "bearing-drawing-r3"), default="bearing-drawing-r3")
    args = parser.parse_args()
    require_workspace(allow_installed=True)
    run = safe(OUTPUT / ("run-omni-" + args.mode), OUTPUT)
    run.mkdir(parents=True, exist_ok=True)
    baseline = run / "BASELINE.json"
    host = preflight()
    if host.get("status") != "PASS":
        raise ValueError(f"Smoke preflight failed: {host.get('error', host.get('stage'))}")
    if not baseline.exists():
        atomic(baseline, {"started": datetime.now(timezone.utc).isoformat(), "revision": host["revision"]})
    elif read(baseline)["revision"] != host["revision"]:
        raise ValueError("Use a fresh installation to test a different SolidWorks revision")
    if args.mode == "install":
        build_demo(run)
    elif args.mode == "fixture":
        fixture_drawing(run)
    else:
        bearing(run, args.drawing_phase if args.mode == "bearing-drawing" else None)
    print(json.dumps({"status": "PASS", "mode": args.mode}))


if __name__ == "__main__":
    raise SystemExit(main())
