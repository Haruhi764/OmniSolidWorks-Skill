"""Resume the verified reducer reference graph in isolated incremental jobs."""
import argparse

from sw_incremental_plan import input_row, make_plan
from sw_supervisor_state import LABEL, OUTPUT, ROOT, atomic, read, require_workspace, safe

SOURCE = ROOT / "outputs" / "v0.5" / "reducer" / "pinion-phase"


def baseline_inputs():
    job = read(SOURCE / "job.json")
    report = read(SOURCE / "native.json")
    if not report["reopenedExplosion"]["verified"] or report["solidInterferences"] != []:
        raise ValueError("Missing verified reducer checkpoint")
    inputs = {"checkpoint.SLDASM": input_row(SOURCE / "ReducerAssembly.SLDASM")}
    for row in job["dependencies"]:
        destination = "references/" + row["path"]
        inputs[destination] = input_row(SOURCE / destination)
        if inputs[destination]["sha256"] != row["sha256"]:
            raise ValueError("Historical reference no longer matches its recorded hash")
    job["checkpoint_names"] = {row["id"]: row["instance"] for row in report["reopenedAssembly"]["components"]}
    for field in ("repair_pinion_mate", "reuse_explosion"):
        job.pop(field, None)
    return job, inputs


def capture(run):
    job, inputs = baseline_inputs()
    job["incremental"] = {"capture_only": True}
    make_plan(run, "explode-capture", job, inputs, (), checkpoint="v0.5/pinion-phase")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("phase", choices=["capture", "explode", "drawing", "drawing-r1", "drawing-r2"])
    args = parser.parse_args()
    require_workspace()
    if not LABEL.fullmatch(args.run) or not args.run.startswith("run-"):
        parser.error("Expected run ID")
    run = safe(OUTPUT / args.run, OUTPUT)
    if args.phase == "capture":
        capture(run)
    elif args.phase == "explode":
        from sw_explosion_plan import plan_explosion
        plan_explosion(run)
    else:
        from sw_drawing_plan import plan_drawing
        plan_drawing(run, args.phase)


if __name__ == "__main__":
    main()

