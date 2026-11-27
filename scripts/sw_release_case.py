"""Build the original guide fixture with the existing immutable native checkpoints."""
import argparse
import json
import sys
from datetime import datetime, timezone

from sw_incremental_plan import input_row, make_plan
from sw_supervisor import inspect, supervise
from sw_supervisor_state import LABEL, OUTPUT, ROOT, atomic, read, require_workspace, safe, sha
from v03_jobs import configuration
from v03_schema import normalize

sys.path.insert(0, str(ROOT / "examples"))
from v09_guide_fixture import assembly, drawing, parts


def dependency(path):
    return {"id": path.stem, "path": path.relative_to(ROOT / "outputs").as_posix(), "sha256": sha(path)}


def execute(run, phase, spec, *, options=None):
    root = ROOT / "outputs"
    job = normalize(spec, root)
    if options:
        job.update(options)
    inputs = {}
    for index, item in enumerate(job["dependencies"]):
        name = "references/"
        if job["document_type"] == "drawing" and index:
            name += "references/"
        name += item["id"] + safe(root / item["path"]).suffix.upper()
        inputs[name] = input_row(safe(root / item["path"]))
    names = [job["outputs"]["name"] + "." + suffix.upper() for suffix in job["outputs"]["formats"]]
    if job["document_type"] == "assembly":
        names += ["Collapsed.bmp", "Exploded.bmp"]
    existing = inspect(run / phase)
    if existing["status"] == "verified":
        plan = read(run / "plans" / f"{phase}.json")
        if (not existing["hashes_match"] or plan["job"] != job or plan["inputs"] != inputs
                or plan["outputs"] != names):
            raise ValueError(f"Verified phase {phase} differs from the requested case")
        state = existing
    else:
        plan = make_plan(run, phase, job, inputs, names, inputs)
        state = supervise(run, phase, plan, host_job_limit=14)
    print(json.dumps({"phase": phase, "status": state["status"], "stage": state.get("stage"),
                      "failure": state.get("failure"), "reason": state.get("reason")}), flush=True)
    if state["status"] != "verified":
        raise ValueError(f"Phase {phase} did not pass")
    return safe(run / phase / "verified" / names[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run")
    parser.add_argument("--through", choices=("parts", "assembly", "drawing"), default="drawing")
    parser.add_argument("--assembly-phase", default="fixture-assembly")
    parser.add_argument("--drawing-phase", default="fixture-drawing")
    args = parser.parse_args()
    for phase, name in ((args.assembly_phase, "fixture-assembly"), (args.drawing_phase, "fixture-drawing")):
        if not LABEL.fullmatch(phase) or not (phase == name or phase.startswith(name + "-r")):
            parser.error("Use the case phase or a revision suffix beginning with -r")
    require_workspace(allow_installed=True)
    if not LABEL.fullmatch(args.run) or not args.run.startswith("run-"):
        parser.error("Expected run ID beginning with run-")
    run = safe(OUTPUT / args.run, OUTPUT)
    run.mkdir(parents=True, exist_ok=True)
    baseline = run / "BASELINE.json"
    if not baseline.exists():
        revision, _, _ = configuration()
        if revision != 22:
            raise ValueError("This acceptance specimen is calibrated for SolidWorks 2014 SP0")
        atomic(baseline, {"revision": "22.0.0", "started": datetime.now(timezone.utc).isoformat()})
    finished = []
    for spec in parts():
        finished.append(execute(run, spec["job_id"].lower(), spec))
    if args.through == "parts":
        return
    model = execute(run, args.assembly_phase, assembly(map(dependency, finished)),
                    options={"review_assembly": True})
    if args.through == "assembly":
        return
    staged_parts = [model.parent / "references" / path.name for path in finished]
    execute(run, args.drawing_phase, drawing(map(dependency, [model, *staged_parts])))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
