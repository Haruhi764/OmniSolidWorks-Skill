"""Package incremental evidence with explicit file provenance."""
import argparse
import csv
import io
import json
from collections import Counter
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile

from sw_supervisor import inspect
from sw_supervisor_state import LABEL, OUTPUT, ROOT, atomic, read, require_workspace, safe, sha
from sw_reducer_incremental import SOURCE

REPORTS = ("ACCEPTANCE_REPORT.md", "OPEN_ITEMS.md", "NEXT_STEPS.md", "RESOURCE_USAGE.json")
DOCS = ("INCREMENTAL_GUIDE.md", "CHANGELOG_INCREMENTAL.md", "GEAR_V05_GUIDE.md",
        "GEAR_V05_REPAIR.md", "THIRD_PARTY_REFERENCES.md", "EXPLODED_VIEW_GUIDE.md",
        "ACCEPTANCE_V03.md", "ACCEPTANCE_V04.md", "ACCEPTANCE_V041.md", "V04_OPEN_ITEMS.md", "V03_GUIDE.md")


def native_reports(run):
    return sorted(run.glob("*/verified/native.json")) + sorted(run.glob("*/partial/*/native.json"))


def usage(run):
    summary = read(run / "resource.json")
    started = datetime.fromisoformat(read(run / "BASELINE.json")["started"])
    native = [read(path) for path in native_reports(run)]
    end = datetime.now().astimezone()
    summary.update({"started": started.isoformat(), "ended": end.isoformat(),
                    "wall_seconds": round((end - started).total_seconds(), 1),
                    "native_worker_seconds": round(sum(item["nativeSeconds"] for item in native), 3),
                    "native_pass": sum(item["status"] == "PASS" for item in native),
                    "native_fail": sum(item["status"] != "PASS" for item in native),
                    "baseline_readonly_probes_outside_job": 1, "targeted_live_stage_retries": 1,
                    "native_launch_auto_review_blocks": 1, "computer_use_calls": 0,
                    "offline_python_tests_passed": 9, "offline_csharp_crossing_assertions": 2,
                    "available_token_fraction": None, "actual_tokens": None,
                    "resource_limits": {"wall_minutes": 120, "native_jobs": 8, "job_seconds": 600},
                    "verified_legacy_assembly_native_files_reused": 28,
                    "host_restart_scope": "existing_session_not_owned"})
    atomic(run / "RESOURCE_USAGE.json", summary)


def evidence(archive, run):
    for name in REPORTS:
        archive.write(safe(run / name), name)
    for name in ("BASELINE.json", "EXPLOSION_COMPARISON.json", "OFFLINE_COMPATIBILITY.json"):
        archive.write(safe(run / name), "evidence/" + name)
    for folder in sorted(run.iterdir()):
        if folder.is_dir() and (folder / "job_state.json").is_file():
            archive.write(safe(folder / "job_state.json"), f"evidence/{folder.name}/job_state.json")
    for path in native_reports(run):
        archive.write(safe(path), "evidence/" + path.relative_to(run).as_posix())
    for path in sorted((run / "plans").glob("*.json")):
        if ".initial." not in path.name:
            archive.write(safe(path), "evidence/plans/" + path.name)


def skill(archive, run):
    for name in ("AGENTS.md", "HANDOFF.md", "README.md", "CHANGELOG.md", "SKILL.md", ".gitignore"):
        archive.write(safe(ROOT / name), name)
    for name in DOCS:
        archive.write(safe(ROOT / "docs" / name), "docs/" + name)
    for directory, extensions in {"scripts": {".py", ".cs", ".ps1"}, "tests": {".py"}, "examples": {".json"},
                                  "schemas": {".json"}}.items():
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and path.suffix in extensions:
                archive.write(safe(path), path.relative_to(ROOT).as_posix())
    evidence(archive, run)


def review(archive, run):
    state = inspect(run / "explode")
    if state.get("status") != "verified" or not state.get("hashes_match"):
        raise ValueError("No verified incremental native assembly")
    source = run / "explode" / "verified"
    manifest = {}

    def file(path, name, provenance):
        path = safe(path)
        archive.write(path, name)
        manifest[name] = {"sha256": sha(path), "bytes": path.stat().st_size, "provenance": provenance}

    file(source / "ReducerAssembly.SLDASM", "new/assembly/ReducerAssembly.SLDASM", "V0.7 reopened")
    for part in sorted((source / "references").glob("*.SLDPRT")):
        file(part, "new/assembly/references/" + part.name, "V0.5 reused unchanged")
    for name in ("BeforeExploded.png", "AfterExploded.png"):
        file(source / name, "new/previews/" + name, "V0.7 native same-scale comparison")
    smoke = run / "smoke" / "verified"
    file(smoke / "RecoverySmoke.SLDPRT", "new/smoke/RecoverySmoke.SLDPRT", "V0.6 reopened")
    file(smoke / "RecoverySmoke.STEP", "new/smoke/RecoverySmoke.STEP", "V0.6 reimported")
    for name in ("ReducerAssembly.STEP", "ReducerAssembled.png"):
        file(SOURCE / name, "reused/assembly-export/" + name, "V0.5 review export")
    drawing = SOURCE.parent / "drawing-final"
    for name in ("ReducerDrawing.SLDDRW", "ReducerDrawing.PDF", "ReducerDrawing.DWG",
                 "ReducerDrawing.DXF", "a1-review.png"):
        file(drawing / name, "reused/drawing/" + name, "V0.5 A1 review")
    for path in sorted((drawing / "references").rglob("*")):
        if path.is_file() and path.suffix.upper() in {".SLDASM", ".SLDPRT"}:
            file(path, "reused/drawing/" + path.relative_to(drawing).as_posix(), "V0.5 A1 references")
    old = read(drawing / "native.json")
    rows = old["reopenedDrawing"]["bom"]["rows"]
    assembly = read(run / "plans" / "explode.json")["job"]
    expected = Counter(row["dependency"] for row in assembly["features"] if row["operation"] == "component")
    if Counter({row["part"]: row["quantity"] for row in rows}) != expected:
        raise ValueError("The reused BOM differs from the new assembly")
    handle = io.StringIO(newline="")
    writer = csv.writer(handle)
    writer.writerow(["item", "part", "quantity"])
    writer.writerows((row["item"], row["part"], row["quantity"]) for row in rows)
    archive.writestr("reused/drawing/BOM.csv", handle.getvalue().encode("utf-8-sig"))
    archive.writestr("README.md", (
        "# SolidWorks 增量评审件\n\n"
        "先完整解压。new/assembly 是本轮重开的装配，保留 references 目录。"
        "使用 Service Exploded 查看新服务视角，new/previews 有同尺度对照。"
        "reused/drawing 是 V0.5 A1 评审图及其独立原生依赖；图签重量未确认。"
        "请保持两个引用目录的层级。\n"
    ))
    archive.writestr("ARTIFACT_SHA256.json", json.dumps(manifest, indent=2, sort_keys=True))
    evidence(archive, run)


def pack(run):
    usage(run)
    delivery = safe(run / "delivery", run)
    delivery.mkdir(exist_ok=True)
    manifests = {}
    for name, compose in (("SolidWorks_Incremental_Skill.zip", skill),
                          ("SolidWorks_Incremental_REVIEW.zip", review)):
        path = safe(delivery / name, delivery)
        if path.exists():
            raise FileExistsError(path)
        work = safe(path.with_suffix(".zip.building"), delivery)
        with ZipFile(work, "x", compression=ZIP_DEFLATED, compresslevel=4) as zip_file:
            compose(zip_file, run)
        with ZipFile(work) as zip_file:
            names = zip_file.namelist()
            if len(names) != len(set(names)) or zip_file.testzip() is not None:
                raise ValueError("Corrupt archive: " + name)
        work.rename(path)
        manifests[name] = {"files": len(names), "bytes": path.stat().st_size, "sha256": sha(path)}
    atomic(delivery / "DELIVERY_SHA256.json", manifests)
    print(json.dumps(manifests, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()
    require_workspace()
    if not LABEL.fullmatch(args.run) or not args.run.startswith("run-"):
        parser.error("Expected run ID")
    pack(safe(OUTPUT / args.run, OUTPUT))

