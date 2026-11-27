from datetime import datetime, timezone
import json

from sw_release_case import dependency, execute
from v09_guide_fixture import job, part
from sw_supervisor_state import OUTPUT, atomic, read, require_workspace, safe

DEFINITIONS = (
    ("GripperBase", (300, 120), 12), ("LinearRail", (280, 20), 12),
    ("RailSlider", (60, 40), 15), ("JawCarrier", (45, 30), 12),
    ("LeftJaw", (35, 12), 10), ("RightJaw", (35, 12), 10),
    ("GuidePin", 8, 25), ("LocatorBlock", (20, 20), 8),
)


def component(key, model, position, fixed=False):
    return dict(id=key, operation="component", dependency=model, location=position, fixed=fixed)


def mate(key, base, moving, distance):
    return dict(id=key, operation="mate", kind="distance", components=[base, moving], distance_mm=distance)


def step(key, group, axis, distance, direction="+z"):
    return dict(id=key, operation="explode", components=group, axis_component=axis,
                direction=direction, distance_mm=distance)


def spec(name, components, mates, steps, paths):
    return job(name, "assembly", components + mates + steps,
               {"relative_positions": {row["id"]: row["location"] for row in components},
                "mate_count": len(mates), "clearance_check": True}, ["sldasm"], map(dependency, paths))


def init_run(name):
    run = safe(OUTPUT / name, OUTPUT)
    run.mkdir(parents=True, exist_ok=True)
    marker = run / "BASELINE.json"
    if not marker.exists():
        atomic(marker, {"started": datetime.now(timezone.utc).isoformat(), "revision": "22.0.0"})
    return run


def build_parts():
    run = init_run("run-gripper-parts")
    paths = {}
    for name, size, depth in DEFINITIONS:
        request = part(name, size, depth)
        for row, height in ((request["validation"], depth), (request["validation"]["edit"]["geometry"], depth + 1)):
            row["centroid_mm"] = [0, 0, height / 2]
        paths[name] = execute(run, name.lower(), request)
    return paths


def build_modules(paths):
    run = init_run("run-gripper-modules")
    components = [
        component("Slider", "RailSlider", [0, 0, 0], True),
        component("Carrier", "JawCarrier", [0, 0, 15]),
        component("Left", "LeftJaw", [0, -12, 27]),
        component("Right", "RightJaw", [0, 12, 27]),
        component("Pin", "GuidePin", [0, 0, 27]),
    ]
    mates = [mate("Seat" + row["id"], "Slider", row["id"], row["location"][2]) for row in components[1:]]
    steps = [step("WithdrawPin", ["Pin"], "Slider", 30),
             step("ReleaseLeft", ["Left"], "Slider", 20, "-y"),
             step("ReleaseRight", ["Right"], "Slider", 20, "+y"),
             step("LiftCarrier", ["Carrier"], "Slider", 18)]
    return {name: execute(run, name.lower(),
                          spec(name, components, mates, steps, [paths[row["dependency"]] for row in components]),
                          options={"review_assembly": True})
            for name in ("JawModuleLeft", "JawModuleCenter", "JawModuleRight")}


if __name__ == "__main__":
    require_workspace(allow_installed=True)
    paths = build_parts()
    build_modules(paths)
