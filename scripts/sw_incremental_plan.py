"""Make hash-bound jobs for incremental validation."""
import argparse
import math

from sw_supervisor_state import LABEL, OUTPUT, ROOT, atomic, read, require_workspace, safe, sha


def input_row(source):
    source = safe(source)
    return {"path": source.relative_to(ROOT).as_posix(), "sha256": sha(source)}


def make_plan(run, phase, job, inputs, outputs, retain=(), checkpoint=None):
    engine_paths = [ROOT / "scripts" / name for name in (
        "Invoke-V03Job.ps1", "sw_supervisor.py", "sw_supervisor_state.py", "sw_incremental_plan.py")]
    engine_paths += sorted((ROOT / "scripts").glob("V03Native*.cs"))
    plan = {"host_revision": read(run / "BASELINE.json")["revision"], "job": job, "inputs": inputs,
            "outputs": list(outputs), "retain": list(retain), "checkpoint": checkpoint,
            "engine": {path.relative_to(ROOT).as_posix(): sha(safe(path)) for path in engine_paths}}
    folder = safe(run / "plans", run)
    folder.mkdir(exist_ok=True)
    path = safe(folder / f"{phase}.json", folder)
    if path.exists():
        if read(path) != plan:
            raise FileExistsError("The previous job plan is immutable")
    else:
        atomic(path, plan)
    return plan


def smoke():
    return {
        "document_type": "part", "outputs": {"name": "RecoverySmoke"},
        "features": [{"id": "Cylinder", "operation": "boss_extrude", "plane": "base",
                      "depth": 7, "profile": {"kind": "circle", "center": [0, 0], "diameter": 16}}],
        "validation": {"volume_mm3": math.pi * 8 ** 2 * 7,
                       "bounds_mm": [[-8, -8, 0], [8, 8, 7]],
                       "cylinders": [{"center": [0, 0], "diameter": 16, "z": [0, 7]}]},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()
    require_workspace()
    if not LABEL.fullmatch(args.run) or not args.run.startswith("run-"):
        parser.error("Expected run ID")
    run = safe(OUTPUT / args.run, OUTPUT)
    make_plan(run, "smoke", smoke(), {}, ("RecoverySmoke.SLDPRT", "RecoverySmoke.STEP"))


if __name__ == "__main__":
    main()

