from collections import Counter
import sys

from sw_blind_gripper import DEFINITIONS, build_modules, build_parts, component, init_run, mate, step
from omni_gb import audit
from sw_incremental_plan import input_row, make_plan
from sw_supervisor import inspect, supervise
from sw_supervisor_state import OUTPUT, atomic, read, require_workspace


def finished_assets():
    base = OUTPUT / "run-gripper-parts"
    parts = {name: base / name.lower() / "verified" / (name + ".SLDPRT") for name, _, _ in DEFINITIONS}
    base = OUTPUT / "run-gripper-modules"
    modules = {name: base / name.lower() / "verified" / (name + ".SLDASM")
               for name in ("JawModuleLeft", "JawModuleCenter", "JawModuleRight")}
    for path in [*parts.values(), *modules.values()]:
        status = inspect(path.parent.parent)
        if status["status"] != "verified" or not status["hashes_match"]:
            raise ValueError(f"Native input checkpoint was not verified: {path.stem}")
    return parts, modules


def publish(run, phase, job, inputs, formats):
    current = inspect(run / phase)
    if current["status"] == "verified" and current["hashes_match"]:
        previous = read(run / "plans" / (phase + ".json"))
        if previous["job"] != job or previous["outputs"] != formats or previous["inputs"] != {dest: input_row(source) for dest, source in inputs.items()}:
            raise ValueError(f"Verified phase {phase} inputs changed")
        return run / phase / "verified"
    plan = make_plan(run, phase, job, {dest: input_row(source) for dest, source in inputs.items()},
                     formats, inputs)
    state = supervise(run, phase, plan, host_job_limit=12)
    print({key: state.get(key) for key in ("status", "stage", "failure")}, flush=True)
    if state["status"] != "verified" or not inspect(run / phase)["hashes_match"]:
        raise ValueError(f"Phase {phase} did not pass")
    return run / phase / "verified"


def assemble(run, parts, modules):
    components = [component("Base", "GripperBase", [0, 0, 0], True),
                  component("Rail", "LinearRail", [0, 0, 12]),
                  component("Locator", "LocatorBlock", [0, 45, 12])]
    station_keys = ["StationLeft", "StationCenter", "StationRight"]
    # The first inserted slider is centered about its subassembly origin.
    station_origin_z = 12 + 12 + 15 / 2
    for key, module, x in zip(station_keys, modules, (-90, 0, 90), strict=True):
        components.append(component(key, module, [x, 0, station_origin_z]))
    mates = [mate("Mount" + row["id"], "Base", row["id"], row["location"][2]) for row in components[1:]]
    steps = [step("LiftLocator", ["Locator"], "Base", 30)]
    steps.extend(step("Lift" + key, [key], "Base", distance)
                 for key, distance in zip(station_keys, (72, 90, 108), strict=True))
    steps.append(step("WithdrawRail", ["Rail"], "Base", 100, "-y"))
    spec = {"document_type": "assembly", "schema_version": 2, "hierarchy": True,
            "subassembly": next(iter(modules)), "module_files": list(modules), "child_parts": list(parts),
            "anchor": "Base", "datum_part": "GripperBase", "features": [*components, *mates, *steps],
            "validation": {"relative_positions": {row["id"]: row["location"] for row in components},
                           "mate_count": len(mates), "leaf_count": 18, "clearance_check": True},
            "outputs": {"name": "ThreeStationGripper"}}
    inputs = {f"references/{path.name}": path for path in modules.values()}
    inputs.update({f"references/references/{path.name}": path for path in parts.values()})
    return publish(run, "gripper-top-r2", spec, inputs,
                   ["ThreeStationGripper.SLDASM", "Collapsed.bmp", "Exploded.bmp"])


def draw(run, parent, parts, modules, phase):
    model = parent / "ThreeStationGripper.SLDASM"
    input_map = {"references/" + model.name: model}
    input_map.update({f"references/references/{p.name}": parent / "references" / p.name for p in modules.values()})
    input_map.update({f"references/references/references/{p.name}": parent / "references" / "references" / p.name
                      for p in parts.values()})
    job = {"document_type": "drawing", "schema_version": 2, "drawing_modules": list(modules),
           "features": [{"id": "Sheet1", "operation": "drawing_sheet", "paper": "a2",
                         "title": "Three-station parallel-jaw gripper", "drawing_number": "PG-00",
                         "exploded": True, "bom": True, "section": True, "detail": False, "center_marks": False,
                         "witness_dimensions": [{"view": "Front", "part": "GripperBase", "model_axis": i, "mm": val}
                                                for i, val in ((0, 300), (1, 120))]}],
           "dependencies": [{"id": model.stem, "path": model.name},
                            *({"id": name, "path": p.name} for name, p in parts.items())],
           "validation": {"component_count": 18, "dimensions_mm": [300, 120]},
           "outputs": {"name": "ThreeStationGripperDrawing"}}
    proof = publish(run, phase, job, input_map,
                    ["ThreeStationGripperDrawing." + ext for ext in ("SLDDRW", "PDF", "DWG", "DXF")])
    top = read(parent / "native.json")
    drawing = read(proof / "native.json")["reopenedDrawing"]
    expected = {key: (1 if key in {"GripperBase", "LinearRail", "LocatorBlock"} else 3) for key in parts}
    tree_bom = Counter(row["path"].rsplit("\\", 1)[-1].removesuffix(".SLDPRT")
                       for row in top["assemblyTree"]["instances"] if row["type"] == 1)
    result = audit({"paper": "A2", "view_scale": drawing["scale"], "views": {"Front": [300, 120]},
                    "bom": expected}, drawing)
    wrong = dict(expected, LeftJaw=4)
    negative = audit({"paper": "A2", "view_scale": drawing["scale"], "bom": wrong}, drawing)
    if result["passed"] is not True or dict(tree_bom) != expected or negative["passed"] is not False:
        raise ValueError(f"Gripper drawing or BOM audit failed: {result}")
    atomic(run / "GRIPPER_ACCEPTANCE.json", {"status": "PASS", "native_bom_quantities": expected,
           "module_steps": top["sourceChildStepCounts"], "native_top_steps": len(top["reopenedExplosion"]["steps"]),
           "leaf_instances": top["assemblyTree"]["partInstances"], "subassembly_instances": top["assemblyTree"]["subassemblyInstances"],
           "top_mates": len(top["reopenedAssembly"]["mates"]), "static_interference": top["solidInterferences"],
           "native_drawing": result, "wrong_bom": negative,
           "production_approval": False, "native_route_persistence": "FAIL / experimental outside stable scope"})


if __name__ == "__main__":
    require_workspace(allow_installed=True)
    parts, modules = finished_assets()
    run = init_run("run-gripper-final")
    parent = assemble(run, parts, modules)
    draw(run, parent, parts, modules, sys.argv[1] if len(sys.argv) > 1 else "gripper-drawing")
