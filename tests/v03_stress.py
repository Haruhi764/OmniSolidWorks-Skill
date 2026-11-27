"""Run ten native parts in a single client batch and verify reuse/validation guards."""
import argparse
import copy
import json
import math
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from v03_jobs import OUTPUT, run_tool
from v03_schema import output_path


def cylinder_geometry(radius, depth):
    return {"volume_mm3": math.pi * radius * radius * depth,
            "bounds_mm": [[-radius, -radius, 0], [radius, radius, depth]],
            "cylinders": [{"center": [0, 0], "diameter": 2 * radius, "z": [0, depth]}]}


def cylinder_job(index):
    name = f"BatchCylinder{index:02}"
    radius = 5 + index
    depth = 10 + index
    geometry = cylinder_geometry(radius, depth)
    geometry["edit"] = {"feature_id": "Cylinder", "depth_mm": depth + 0.5,
                        "geometry": cylinder_geometry(radius, depth + 0.5)}
    return {"schema_version": 1, "job_id": name, "document_type": "part", "units": "mm",
            "features": [{"id": "Cylinder", "plane": "base", "operation": "boss_extrude", "depth": depth,
                          "profile": {"kind": "circle", "center": [0, 0], "diameter": 2 * radius}}],
            "parameters": {}, "dependencies": [], "outputs": {"name": name, "formats": ["sldprt", "step"]},
            "validation": geometry}


def refused(call):
    try:
        call()
    except ValueError as exc:
        return str(exc)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    started = time.perf_counter()
    jobs = [cylinder_job(index) for index in range(1, 11)]
    results = []
    consecutive_host_failures = 0
    for job in jobs:
        try:
            result = run_tool(job, force=True)
        except (ValueError, OSError) as exc:
            result = {"job_id": job["job_id"], "status": "FAIL", "error": str(exc)}
        results.append(result)
        print(job["job_id"], result["status"], flush=True)
        consecutive_host_failures = consecutive_host_failures + 1 if result["status"] != "PASS" else 0
        if consecutive_host_failures == 2:
            break
    baseline = results[0]
    cache_start = time.perf_counter()
    hit = run_tool(jobs[0]) if baseline["status"] == "PASS" else {}
    cache_seconds = round(time.perf_counter() - cache_start, 3)
    invalid = copy.deepcopy(jobs[0])
    invalid["features"][0]["profile"]["diameter"] = -1
    conflicting = copy.deepcopy(jobs[0])
    conflicting["features"][0]["depth"] += 1
    checks = {"reject_negative_dimension": refused(lambda: run_tool(invalid)),
              "reject_artifact_path_escape": refused(lambda: output_path(OUTPUT.resolve(), "../V0.1.SLDPRT")),
              "reject_conflicting_job_id": refused(lambda: run_tool(conflicting))}
    complete = [row for row in results if row["status"] == "PASS"]
    native_reports = [json.loads((OUTPUT / row["evidence"]).read_text(encoding="utf-8")) for row in complete]
    edited = sum(row.get("edit", {}).get("changeCode") == row.get("edit", {}).get("restoreCode") == 0
                 for row in native_reports)
    cleanup = sum(row.get("documentCountAfter") == 0 and row.get("preferencesRestored") is True for row in native_reports)
    cache_ok = hit.get("cache_hit") is True and baseline["artifacts"] == hit["artifacts"]
    summary = {"status": "PASS" if len(complete) == edited == cleanup == 10 and cache_ok and all(checks.values()) else "FAIL",
               "attempted": len(results), "native_runs": len(complete), "parameter_round_trips": edited, "cleanups": cleanup,
               "step_exports": sum(item["path"].upper().endswith(".STEP") for row in complete for item in row["artifacts"]),
               "cache_hit": cache_ok, "cache_lookup_seconds": cache_seconds, "invalid_inputs": checks,
               "tracked_com_invocations": sum(row.get("com_calls") or 0 for row in results),
               "rebuilds": sum(row.get("rebuilds") or 0 for row in results),
               "duration_seconds": round(time.perf_counter() - started, 3), "results": results}
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
    print(summary["status"], summary["duration_seconds"], args.report)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
