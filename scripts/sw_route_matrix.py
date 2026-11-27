"""Independent native route probes for contextual entities and COM array contracts."""
import argparse
from datetime import datetime, timezone
import json
from itertools import product

from sw_incremental_plan import input_row, make_plan
from sw_rc_probes import staged_smoke
from sw_supervisor import inspect, supervise
from sw_supervisor_state import OUTPUT, atomic, read, require_workspace, safe


def cases(suite):
    if suite == "core":
        return [("selection", "edges", "typed", True), ("corresponding", "faces", "variant", False),
                ("body", "mixed", "typed", False)]
    if suite in ("discover", "verify", "commit"):
        return [("selection", "edges", "typed", True), ("body", "faces", "typed", False)]
    if suite in ("official", "official-3d"):
        return [("body", "faces", "typed", False)]
    if suite == "matrix":
        return [(source, shape, "typed", shape == "edges")
                for source, shape in product(("body", "corresponding", "selection"), ("faces", "edges", "mixed"))]
    return [("selection", "edges", "dispatch", True), ("corresponding", "faces", "dispatch", False),
            ("selection", "mixed", "variant", False)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("core", "matrix", "dispatch", "discover", "verify", "commit", "official", "official-3d"))
    args = parser.parse_args()
    require_workspace(allow_installed=True)
    control = args.suite in ("official", "official-3d")
    mount = staged_smoke("mount", "RcMount_base.SLDASM" if control else "RcMount.SLDASM")
    parts = [mount.parent / "references" / name for name in ("RcSeat.SLDPRT", "RcPin.SLDPRT")]
    inputs = {"checkpoint.SLDASM": input_row(mount)}
    inputs.update({f"references/{path.name}": input_row(path) for path in parts})
    run = safe(OUTPUT / ("run-final-routes-" + args.suite), OUTPUT)
    run.mkdir(parents=True, exist_ok=True)
    if not (run / "BASELINE.json").is_file():
        atomic(run / "BASELINE.json", {"started": datetime.now(timezone.utc).isoformat(), "revision": "22.0.0"})
    summaries = []
    for source, witness, packing, along in cases(args.suite):
        phase = "-".join((source, witness, packing))
        spec = {"document_type": "assembly", "outputs": {"name": "RouteValidation"},
                "dependencies": [{"id": path.stem} for path in parts],
                "route_probe": {"first": "RcSeat", "second": "RcPin", "diameter": 10,
                                "source": source, "witness": witness, "packing": packing, "along": along,
                                "auto_explode": control, "exit_with_3d": args.suite == "official-3d"}}
        state = inspect(run / phase)
        if state["status"] not in ("verified", "failed"):
            plan = make_plan(run, phase, spec, inputs, ["RouteValidation.SLDASM"], inputs)
            state = supervise(run, phase, plan, host_job_limit=14)
        where = run / phase / "verified" if state["status"] == "verified" else run / state.get("partial", phase)
        native_path = where / "native.json"
        native = read(native_path) if native_path.is_file() else {}
        item = {"phase": phase, "status": state["status"], "stage": state.get("stage"),
                "apiStage": native.get("routeFailureStage"),
                "actualReturn": native.get("nativeRouteLineCreated"), "segments": native.get("routeSegments"),
                "editable": native.get("routeEditable"), "error": native.get("error") or state.get("failure")}
        summaries.append(item)
        atomic(run / "ROUTE_MATRIX.json", summaries)
        print(json.dumps(item, ensure_ascii=True), flush=True)
        if state.get("reason") in ("host_timeout", "host_disconnected", "worker_missing_evidence"):
            break
    return int(not any(row["status"] == "verified" for row in summaries))


if __name__ == "__main__":
    raise SystemExit(main())
