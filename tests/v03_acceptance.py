"""Score preserved live COM evidence without rebuilding accepted cases."""

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import score_benchmark
from v03_jobs import OUTPUT, artifact_rows, sha
from v03_schema import output_path


WEIGHTS = {"geometry": 30, "structure": 20, "native_files": 15,
           "reopen": 15, "real_evidence": 10, "delivery": 10}
BASELINE = {
    "A": "shaft-20261123-184005-38bf539c/report.json",
    "B": "flange-20261123-184020-81e8b74e/report.json",
    "C": "jobs/BracketBaseFirst/run-1795445436874316700-b271968e/result.json",
    "D": "jobs/BearingBlock/run-1795444125307350100-cff3bb70/result.json",
    "E": "jobs/TwoPartAssembly/run-1795447554216420700-080cfb39/result.json",
    "F": "jobs/FourPartAssembly/run-1795447564461041900-ac35d348/result.json",
    "G": "jobs/ExplodedAssembly/run-1795448890225562100-53068b21/result.json",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def near(actual, expected, tolerance=0.005):
    return math.isclose(actual, expected, rel_tol=0, abs_tol=tolerance)


def coordinates(actual, expected):
    return len(actual) == len(expected) and all(near(a, b) for a, b in zip(actual, expected))


def scored(case, evidence, checks, *, status=None, detail=None, extra_gates=()):
    gates = ("geometry", "native_files", "reopen", "real_evidence", *extra_gates)
    hard = {key: bool(checks.get(key)) for key in gates}
    sections = {name: weight if checks.get(name) else 0 for name, weight in WEIGHTS.items()}
    total = sum(sections.values())
    actual = "PASS" if all(hard.values()) and total >= 90 else status or "FAIL"
    return {"case": case, "status": actual, "score": total, "sections": sections,
            "hard_gates": hard, "evidence": str(evidence.relative_to(OUTPUT)) if evidence else None, "detail": detail}


def legacy(case, path):
    data = load(path)
    spec = load(ROOT / "examples" / "benchmarks.json")
    old = score_benchmark.grade(path, spec)
    return scored(case, path, {
        "geometry": old["hard_gates"]["geometry"], "structure": old["points"]["parameters_and_features"] == 20,
        "native_files": score_benchmark.valid_artifacts(data, path.parent),
        "reopen": old["hard_gates"]["file_integrity_and_reopen"],
        "real_evidence": old["hard_gates"]["real_api_run"],
        "delivery": data["documentCountAfter"] == 0 and data["dimensionPromptRestored"] is True})


def run_evidence(result_path):
    result = load(result_path)
    run = result_path.parent
    job = load(run / "normalized.json")
    raw = run / "native.json"
    native = load(raw)
    files = False
    try:
        artifacts = artifact_rows(job, run, OUTPUT)
        files = artifacts == result["artifacts"]
        dependency_hashes = {entry["sha256"] for entry in artifacts if "/references/" in entry["path"]}
        files &= dependency_hashes == {entry["sha256"] for entry in job["dependencies"]}
    except (OSError, ValueError, KeyError):
        pass
    real = (result["status"] == native["status"] == "PASS" and native["revision"] == "22.0.0" and
            result.get("native_sha256") == sha(raw) and native.get("transport") == "SolidWorks installed PIA" and
            isinstance(native.get("pid"), int) and native.get("trackedComInvocations", 0) > 0)
    closed = native.get("documentCountBefore") == native.get("documentCountAfter") == 0 and native.get("preferencesRestored") is True
    opened = (native.get("nativeOpen", {}).get("ok") is True and native["nativeOpen"].get("errors") == 0 and
              "CloseDoc" in native.get("trackedCalls", []) and native.get("rebuildCount", 0) >= 1)
    return job, native, {"native_files": files, "real_evidence": real, "reopen": opened, "delivery": closed}


def geometry_rows(read, expectation, expected_volume=None):
    if read.get("solids") != 1 or read.get("bodyCheckCode") != 0 or not read.get("verified"):
        return False
    if not near(read["volumeMm3"], expectation["volume_mm3"] if expected_volume is None else expected_volume, 0.02):
        return False
    if not all(coordinates(a, b) for a, b in zip(read["boundsMm"], expectation["bounds_mm"], strict=True)):
        return False
    return all(sum(coordinates(found["center"], hole["center"]) and coordinates(found["z"], hole["z"]) and
                   near(found["diameter"], hole["diameter"]) for found in read["cylinders"]) == 1 for hole in expectation["cylinders"])


def part_checks(case, job, native, checks):
    target = job["validation"]
    independent = {"C": 80 * 50 * 8 + 80 * 10 * 32 - 2 * math.pi * 4**2 * 8,
                   "D": (80 * 50 - math.pi * (15**2 + 2 * 4**2)) * 20}
    checks["geometry"] = all(geometry_rows(native.get(key, {}), target, independent[case]) for key in
                             ("geometry", "reopenedGeometry", "stepGeometry"))
    features = native.get("reopenedFeatures", [])
    edit = native.get("edit", {})
    profiles = {"rectangle": 2, "circle": 1, "polygon": 0}
    checks["structure"] = (len(features) == len(job["features"]) and all(
        got["id"] == feature["id"] and got["error"] == got["profileError"] == 0 and
        len(got["profileDimensions"]) >= profiles[feature["profile"]["kind"]] for got, feature in zip(features, job["features"])) and
        edit.get("changeCode") == edit.get("restoreCode") == 0 and
        geometry_rows(edit.get("geometry", {}), target["edit"]["geometry"]) and geometry_rows(edit.get("restoredGeometry", {}), target))
    checks["reopen"] &= native.get("stepOpen", {}).get("ok") is True and native.get("stepPreferencesRestored") is True
    return checks


def assembly_checks(case, job, native, checks):
    reference = job["validation"]["relative_positions"]
    checked = native.get("reopenedAssembly", {})
    actual = {row["id"]: row["relativeMm"] for row in checked.get("components", [])}
    source = {row["id"]: row["dependency"] for row in job["features"] if row["operation"] == "component"}
    mates = {row["id"]: row for row in checked.get("mates", [])}
    mate_types = {"coincident": 0, "concentric": 1, "distance": 5}
    checks["geometry"] = actual.keys() == reference.keys() and all(coordinates(actual[k], v) for k, v in reference.items())
    checks["structure"] = len(mates) == job["validation"]["mate_count"] and all(
        row["id"] in mates and mates[row["id"]]["type"] == mate_types[row["kind"]] and mates[row["id"]]["error"] == 0
        and len(set(mates[row["id"]]["references"])) == 2 for row in job["features"] if row["operation"] == "mate")
    checks["reopen"] &= checked.get("verified") is True and all(Path(row["path"]).stem == source[row["id"]] for row in checked["components"])
    if case == "G":
        explode = native.get("reopenedExplosion", {})
        checks["structure"] &= len(explode.get("steps", [])) == 2 and explode.get("verified") is True
        offsets = explode.get("deltaMm", {})
        wanted = {"Shaft": 30, "GuideRear": 40, "GuideFront": 0, "Base": 0}
        checks["geometry"] &= offsets.keys() == wanted.keys() and all(coordinates(offsets[key], [0, 0, z]) for key, z in wanted.items())
        checks["reopen"] &= explode.get("expandedChecked") is explode.get("collapsedChecked") is True
    return checks


def drawing_case(path):
    job, native, checks = run_evidence(path)
    data = native.get("reopenedDrawing", {})
    views = {row["role"]: row for row in data.get("views", [])}
    expected = {"Front", "Top", "Left", "Isometric"}
    plan = job["features"][0]
    expected.update(role for key, role in (("section", "Section"), ("detail", "Detail")) if plan.get(key))
    checks["geometry"] = bool(data.get("firstAngle")) and all(any(near(value, dimension) for value in data.get("dimensionsMm", []))
        for dimension in job["validation"]["dimensions_mm"])
    checks["structure"] = views.keys() == expected and all(views[key]["base"] == views["Front"]["name"] for key in ("Top", "Left"))
    if plan.get("bom"):
        bom = data.get("bom", {})
        checks["structure"] &= (bom.get("componentCount") == job["validation"]["component_count"] and len(bom.get("balloons", [])) > 0
                                and views.get("Isometric", {}).get("exploded") is plan["exploded"])
    checks["reopen"] &= data.get("sheetFormat", "").lower().endswith("- gb.slddrt") and data.get("detailStandard") == 7
    quality_path = path.parent / "visual-review.json"
    quality = load(quality_path) if quality_path.exists() else {}
    pdf = path.parent / (job["outputs"]["name"] + ".PDF")
    reviewed = quality.get("verdict") == "PASS" and pdf.is_file() and quality.get("pdf_sha256") == sha(pdf)
    checks["delivery"] &= reviewed
    checks["layout_review"] = reviewed
    return scored(job["job_id"], path, checks, extra_gates=("layout_review",),
                  status=native["status"] if native["status"] != "PASS" else None,
                  detail="PDF visual review accepted" if reviewed else "PDF visual review not accepted or absent")


def mcp_case(path):
    wire = load(path)
    messages = {entry.get("id"): entry for entry in wire["replies"]}
    rendered = messages[7]["result"]
    result = json.loads(rendered["content"][0]["text"])
    run_path = output_path(OUTPUT, result["evidence"]).with_name("result.json")
    job, native, checks = run_evidence(run_path)
    part_checks("D", job, native, checks)
    protocol = (wire["status"] == "PASS" and wire["exit_code"] == 0 and messages[1]["result"]["protocolVersion"] == "2025-03-26" and
                any(tool["name"] == "run_cad_job" for tool in messages[2]["result"]["tools"]) and messages[5]["error"]["code"] == -32602 and
                rendered["isError"] is False and result.get("cache_hit") is False)
    checks["real_evidence"] &= protocol and result["native_sha256"] == sha(run_path.with_name("native.json"))
    return scored("I", path, checks, detail=f"MCP response traffic: {wire['stdout_bytes']} bytes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--drawing", nargs="*", type=Path, default=[])
    args = parser.parse_args()
    cases = []
    for case, relative in BASELINE.items():
        path = OUTPUT / relative
        if case in ("A", "B"):
            cases.append(legacy(case, path))
            continue
        job, native, checks = run_evidence(path)
        validate = part_checks if case in ("C", "D") else assembly_checks
        cases.append(scored(case, path, validate(case, job, native, checks)))
    cases.extend(drawing_case(item.resolve()) for item in args.drawing)
    if not args.drawing:
        cases.append(scored("H", None, {}, status="BLOCKED", detail="No accepted live drawing result supplied"))
    cases.append(mcp_case(OUTPUT / "mcp-build-I.json"))
    report = {"live_only": True, "weights": WEIGHTS, "pass_threshold": 90, "cases": cases}
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
    print(json.dumps([{k: row[k] for k in ("case", "status", "score")} for row in cases], ensure_ascii=True))
    return 0 if all(case["status"] == "PASS" for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
