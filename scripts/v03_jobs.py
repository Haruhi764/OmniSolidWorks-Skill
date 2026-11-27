"""Validation, local execution and compact summaries for V0.3 jobs."""
import argparse
import hashlib
import json
import math
import msvcrt
import os
import re
import shutil
import subprocess
import time
import winreg
from pathlib import Path
from uuid import uuid4

from v03_schema import normalize, output_path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "v0.3"
MAX_JOB_BYTES = 4 * 1024 * 1024
MAX_JOB_DEPTH = 32


def decode_document(payload):
    if len(payload) > MAX_JOB_BYTES:
        raise ValueError("JSON input exceeds the size limit")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object field")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Expected standard finite JSON numbers")

    try:
        document = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=unique_keys,
                              parse_constant=invalid_constant)
    except RecursionError as error:
        raise ValueError("JSON input exceeds the depth limit") from error

    def validate_depth(node, depth):
        if isinstance(node, (dict, list)):
            if depth >= MAX_JOB_DEPTH:
                raise ValueError("JSON input exceeds the depth limit")
            for child in node.values() if isinstance(node, dict) else node:
                validate_depth(child, depth + 1)
        elif isinstance(node, float) and not math.isfinite(node):
            raise ValueError("Expected standard finite JSON numbers")

    validate_depth(document, 0)
    return document


def load_job(path):
    with path.open("rb") as stream:
        return decode_document(stream.read(MAX_JOB_BYTES + 1))


def registered_releases():
    """Resolve registered major versions without activating any COM server."""
    found = {}
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as classes:
        for index in range(winreg.QueryInfoKey(classes)[0]):
            key = winreg.EnumKey(classes, index)
            match = re.fullmatch(r"SldWorks\.Application\.(\d{1,3})", key, re.IGNORECASE)
            if not match:
                continue
            major = int(match[1])
            try:
                found[major] = registration(major)
            except (OSError, TypeError, ValueError):
                continue
    return found


def registration(revision):
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, fr"SldWorks.Application.{revision}\CLSID") as key:
        clsid = winreg.QueryValueEx(key, "")[0]
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, fr"CLSID\{clsid}\LocalServer32") as key:
        command = winreg.QueryValueEx(key, "")[0].strip()
    command = os.path.expandvars(command)
    # Registered command lines may carry flags after the executable.
    end = command.casefold().find(".exe")
    if end <= 0:
        raise ValueError("SolidWorks registration has no executable")
    executable = Path(command[:end + 4].lstrip('"'))
    if not executable.is_absolute() or executable.name.casefold() != "sldworks.exe":
        raise ValueError("The registered server is not SolidWorks")
    install = executable.parent
    return {"clsid": clsid, "executable": str(executable),
            "available": executable.is_file() and (install / "SolidWorks.Interop.sldworks.dll").is_file()}


def configuration():
    selected = os.environ.get("SOLIDWORKS_REVISION_MAJOR")
    install = os.environ.get("SOLIDWORKS_INSTALL_DIR")
    if selected and not re.fullmatch(r"[1-9][0-9]{0,2}", selected):
        raise ValueError("SOLIDWORKS_REVISION_MAJOR must be a positive COM major, e.g. 22")
    revision = int(selected) if selected else 22
    if not install:
        try:
            row = registration(revision)
        except (OSError, TypeError, ValueError):
            row = None
        if not selected and (not row or not row["available"]):
            available = {major: info for major, info in registered_releases().items() if info["available"]}
            if not available:
                raise ValueError("No usable SolidWorks COM registration with SLDWORKS.exe and PIA; repair the local installation or set SOLIDWORKS_INSTALL_DIR and SOLIDWORKS_REVISION_MAJOR")
            if len(available) != 1:
                choices = ", ".join(map(str, sorted(available)))
                raise ValueError(f"Multiple registered COM majors ({choices}); set SOLIDWORKS_REVISION_MAJOR")
            revision, row = next(iter(available.items()))
        if not row or not row["available"]:
            raise ValueError(f"SolidWorks COM major {revision} has no usable registered executable and PIA; verify the installation or set SOLIDWORKS_INSTALL_DIR")
        install = Path(row["executable"]).parent
    install = Path(install)
    if not install.is_absolute() or not install.is_dir():
        raise ValueError(f"SolidWorks installation directory is missing or relative: {install}; set SOLIDWORKS_INSTALL_DIR to the absolute folder containing SLDWORKS.exe")
    install = install.resolve(strict=True)
    required = ("SLDWORKS.exe", "SolidWorks.Interop.sldworks.dll")
    missing = [name for name in required if not (install / name).is_file()]
    if missing:
        raise ValueError(f"Missing {', '.join(missing)} in {install}; check SOLIDWORKS_INSTALL_DIR or repair the local SolidWorks installation")
    program_data = os.environ.get("ProgramData")
    if not program_data or not Path(program_data).is_absolute():
        raise ValueError("Windows ProgramData does not identify an absolute path")
    template = Path(program_data) / "SolidWorks" / f"SolidWorks {revision + 1992}" / "templates"
    return revision, install, template


def windows_powershell():
    system_root = os.environ.get("SystemRoot")
    if not system_root or not Path(system_root).is_absolute():
        raise ValueError("Windows SystemRoot is missing or relative")
    executable = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not executable.is_file():
        raise ValueError("64-bit Windows PowerShell 5.1 is required for the STA COM bridge")
    return executable


def host_command(script, *args):
    return [str(windows_powershell()), "-NoProfile", "-NonInteractive", "-Sta", "-ExecutionPolicy", "RemoteSigned",
            "-File", str(ROOT / "scripts" / script), *map(str, args)]


def run_host(command, timeout=150):
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout, check=False,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("COM host did not return. Inspect the interactive session before retrying.") from exc


def configured_pid():
    value = os.environ.get("SOLIDWORKS_TARGET_PID", "0")
    if not value.isascii() or not value.isdigit() or not 0 <= int(value) <= 2**31 - 1:
        raise ValueError("SOLIDWORKS_TARGET_PID must be a valid decimal process ID")
    return int(value)


def environment():
    try:
        revision, install, _ = configuration()
        pid = configured_pid()
        process = run_host(host_command("Invoke-V03Probe.ps1", revision, install, pid), timeout=30)
        if process.returncode:
            detail = process.stderr.decode("utf-8", errors="replace").strip()
            return {"status": "BLOCKED", "stage": "powershell_probe",
                    "error": detail or f"Windows PowerShell probe exited with code {process.returncode}"}
        return json.loads(process.stdout.decode("utf-8-sig"))
    except (ValueError, OSError, TimeoutError) as exc:
        return {"status": "BLOCKED", "stage": "environment", "error": str(exc)}


def preflight():
    """Read the configured host profile without starting SolidWorks or editing documents."""
    try:
        revision, install, directory = configuration()
        windows_powershell()
        configured_pid()
    except (ValueError, OSError) as exc:
        return {"status": "BLOCKED", "stage": "configuration", "error": str(exc)}
    required, optional = {}, {}
    errors = []
    for kind in ("part", "assembly", "drawing"):
        try:
            required[kind] = str(get_template(kind, directory))
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
    if "drawing" in required:
        drawing_dir = Path(required["drawing"]).parent
        optional = {f"A{size}": (drawing_dir / f"gb_a{size}.drwdot").is_file() for size in range(4)}
    details = {"selected_major": revision, "install_directory": str(install), "templates": required,
               "optional_sheet_templates": optional}
    if errors:
        return dict(details, status="BLOCKED", stage="templates", error=" | ".join(errors))
    result = environment()
    if result.get("status") == "PASS" and result.get("documents") != 0:
        result.update(status="BLOCKED", stage="open_documents",
                      error="Use an empty SolidWorks session for the smoke test. Save and close your documents yourself, or select an empty session using SOLIDWORKS_TARGET_PID.")
    return dict(details, **result)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()


def create_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=True, allow_nan=False, indent=2)


def get_template(kind, location):
    name = {"part": "gb_part.prtdot", "assembly": "gb_assembly.asmdot", "drawing": "gb_a4.drwdot"}[kind]
    key = f"SOLIDWORKS_{kind.upper()}_TEMPLATE"
    override = os.environ.get(key)
    path = Path(override) if override else location / name
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != Path(name).suffix:
        raise ValueError(f"Invalid or missing {kind} template: {path}. Set {key} to an absolute {Path(name).suffix} file.")
    return path.resolve(strict=True)


def dependency_path(job, folder, index, row):
    anchor = folder / "references"
    if job["document_type"] == "drawing" and index > 0:
        anchor /= "references"
    return anchor / f'{row["id"]}{Path(row["path"]).suffix.upper()}'


def artifact_rows(job, folder, root):
    paths = [folder / f'{job["outputs"]["name"]}.{kind.upper()}' for kind in job["outputs"]["formats"]]
    paths += [dependency_path(job, folder, index, row) for index, row in enumerate(job["dependencies"])]
    signatures = {".sldprt": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".sldasm": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
                  ".slddrw": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".step": b"ISO-10303-21;", ".pdf": b"%PDF-", ".dwg": b"AC10"}
    result = []
    for path in paths:
        with path.open("rb") as stream:
            suffix = path.suffix.lower()
            if suffix == ".dxf":
                start = stream.read(512)
                valid = start.startswith(b"AutoCAD Binary DXF") or start.lstrip(b"\xef\xbb\xbf \t\r\n").startswith((b"0\r\nSECTION", b"0\nSECTION", b"999"))
                if valid and not start.startswith(b"AutoCAD Binary DXF"):
                    stream.seek(max(0, path.stat().st_size - 100))
                    valid = stream.read().rstrip().endswith(b"EOF")
            else:
                valid = stream.read(24).startswith(signatures[suffix])
            if not valid:
                raise ValueError(f"Unexpected file signature for {path.name}")
        result.append({"path": path.relative_to(root).as_posix(), "sha256": sha(path), "bytes": path.stat().st_size})
    return result


def stage_dependencies(job, folder, root):
    if not job["dependencies"]:
        return
    for index, row in enumerate(job["dependencies"]):
        source = output_path(root, row["path"])
        target = dependency_path(job, folder, index, row)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as input_file, target.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
        if sha(target) != row["sha256"]:
            raise ValueError(f"The staged dependency changed: {row['id']}")


def cached_result(job, directory, root, fingerprint):
    for candidate in sorted(directory.glob("run-*/result.json"), reverse=True):
        if not candidate.resolve().is_relative_to(root):
            continue
        record = json.loads(candidate.read_text(encoding="utf-8"))
        if record.get("fingerprint") == fingerprint:
            if record["status"] != "PASS":
                return None
            try:
                artifacts = artifact_rows(job, candidate.parent, root)
                native = candidate.parent / "native.json"
                if artifacts == record["artifacts"] and sha(native) == record["native_sha256"]:
                    record["cache_hit"] = True
                    return record
            except (OSError, ValueError):
                pass
    return None


def execute(job, directory, root, fingerprint, revision, install, template, checkpoint):
    folder = directory / f"run-{time.time_ns()}-{uuid4().hex[:8]}"
    folder.mkdir()
    create_json(folder / "normalized.json", job)
    started = time.perf_counter()
    process = None
    report = folder / "native.json"
    result = {"job_id": job["job_id"], "fingerprint": fingerprint, "cache_hit": False,
              "evidence": report.relative_to(root).as_posix(), "artifacts": []}
    try:
        stage_dependencies(job, folder, root)
        if checkpoint:
            source = output_path(root, checkpoint["path"])
            target = folder / "checkpoint.SLDASM"
            with source.open("rb") as inp, target.open("xb") as out:
                shutil.copyfileobj(inp, out)
            if sha(target) != checkpoint["sha256"]:
                raise ValueError("Assembly checkpoint hash mismatch")
            create_json(folder / "checkpoint.json", checkpoint)
        process = run_host(host_command("Invoke-V03Job.ps1", revision, install, template, folder, configured_pid()))
        if not report.exists():
            raise ValueError(process.stderr.decode("utf-8", errors="replace").strip() or "Native evidence is absent")
        native = json.loads(report.read_text(encoding="utf-8"))
        result.update({"status": native["status"], "stage": native["stage"], "revision": native.get("revision"),
                       "native_sha256": sha(report), "com_calls": native.get("trackedComInvocations"),
                       "rebuilds": native.get("rebuildCount")})
        if process.returncode == 0 and native["status"] == "PASS":
            result["artifacts"] = artifact_rows(job, folder, root)
            if native.get("reopenedGeometry"):
                result["volume_mm3"] = native["reopenedGeometry"]["volumeMm3"]
            if native.get("reopenedAssembly"):
                result["components"] = len(native["reopenedAssembly"]["components"])
                result["mates"] = len(native["reopenedAssembly"]["mates"])
            if native.get("reopenedDrawing"):
                result["views"] = len(native["reopenedDrawing"]["views"])
        else:
            result["status"] = native["status"] if native["status"] != "PASS" else "FAIL"
            result["error"] = native.get("error", "Native execution did not complete")
    except (ValueError, OSError) as exc:
        result.update(status="FAIL", error=str(exc))
    except TimeoutError as exc:
        result.update(status="BLOCKED", error=str(exc))
    if process and process.stderr:
        (folder / "stderr.txt").write_bytes(process.stderr)
    result["duration_seconds"] = round(time.perf_counter() - started, 3)
    create_json(folder / "result.json", result)
    return result


def run_tool(job, *, force=False, checkpoint=None):
    if not isinstance(job, dict):
        raise ValueError("Expected a CAD job object")
    version = "v0.4.1" if "limits" in job else ("v0.4" if job.get("schema_version") == 2 else "v0.3")
    output = OUTPUT.with_name(version)
    root = output.resolve()
    if not root.is_relative_to(ROOT):
        raise ValueError("The versioned output directory escapes the workspace")
    root.mkdir(parents=True, exist_ok=True)
    job = normalize(job, root)
    if checkpoint is not None and (job["schema_version"] != 2 or job["document_type"] != "assembly"
                                   or output_path(root, checkpoint["path"]).suffix.lower() != ".sldasm"):
        raise ValueError("Only a V0.4 assembly can resume from an assembly checkpoint")
    revision, install, location = configuration()
    template = get_template(job["document_type"], location)
    source = [ROOT / "scripts" / name for name in ("v03_jobs.py", "v03_schema.py", "Invoke-V03Job.ps1")]
    source += sorted((ROOT / "scripts").glob("V03Native*.cs"))
    if job["document_type"] == "drawing":
        source.extend(path for name in ("gb_a3.drwdot", "gb_a0.drwdot")
                      if (path := template.with_name(name)).is_file())
    fingerprint = hashlib.sha256(canonical({"job": job, "release": revision, "checkpoint": checkpoint,
        "engine": [sha(path) for path in [*source, install / "SLDWORKS.exe", template]]})).hexdigest()
    directory = root / "jobs" / job["job_id"]
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(root):
        raise ValueError("The job directory escapes the output root")
    lock_file = directory / ".lock"
    if lock_file.is_symlink():
        raise ValueError("The job lock must be a local file")
    with lock_file.open("a+b") as guard:
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            request = directory / "request.json"
            if not request.exists():
                create_json(request, job)
            elif canonical(json.loads(request.read_text(encoding="utf-8"))) != canonical(job):
                raise ValueError("This job ID already belongs to different parameters")
            if not force:
                hit = cached_result(job, directory, root, fingerprint)
                if hit:
                    return hit
            return execute(job, directory, root, fingerprint, revision, install, template, checkpoint)
        finally:
            guard.seek(0)
            msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", nargs="*", type=Path)
    parser.add_argument("--preflight", action="store_true", help="Check local COM, empty session and CAD templates")
    parser.add_argument("--force", action="store_true", help="Run fresh in a new folder even if a valid result exists")
    args = parser.parse_args()
    if args.preflight:
        if args.job or args.force:
            parser.error("--preflight runs without a job or --force")
        result = preflight()
        print(json.dumps(result, ensure_ascii=True))
        return int(result["status"] != "PASS")
    if not args.job:
        print(json.dumps(environment(), ensure_ascii=True))
        return 0
    results = []
    for path in args.job:
        try:
            results.append(run_tool(load_job(path), force=args.force))
        except (ValueError, OSError) as exc:
            results.append({"status": "FAIL", "error": str(exc), "input": str(path)})
    print(json.dumps(results, ensure_ascii=True, indent=2))
    return 0 if all(row["status"] == "PASS" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
