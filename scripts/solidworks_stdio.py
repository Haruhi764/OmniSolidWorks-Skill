import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Literal
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]


def configuration():
    revision = int(os.environ.get("SOLIDWORKS_REVISION_MAJOR", "22"))
    install = Path(os.environ["SOLIDWORKS_INSTALL_DIR"]).resolve(strict=True)
    template = Path(os.environ["SOLIDWORKS_PART_TEMPLATE"]).resolve(strict=True)
    return revision, install, template


def solidworks_session() -> dict:
    """Read the running SolidWorks COM revision using the version-specific ProgID."""
    import pythoncom

    revision, _, _ = configuration()
    prog_id = f"SldWorks.Application.{revision}"
    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    try:
        # Direct IDispatch invocation avoids consulting the default Automation
        # type information, which was unreadable in 2014 SP0 over late binding.
        app = pythoncom.GetActiveObject(prog_id).QueryInterface(pythoncom.IID_IDispatch)
        version = app.Invoke(app.GetIDsOfNames("RevisionNumber"), 0, pythoncom.DISPATCH_METHOD, 1)
        pid = app.Invoke(app.GetIDsOfNames("GetProcessID"), 0, pythoncom.DISPATCH_METHOD, 1)
        return {"ok": str(version).startswith(f"{revision}."), "revision": version, "pid": pid}
    except pythoncom.com_error as error:
        return {"ok": False, "prog_id": prog_id, "hresult": f"0x{error.hresult & 0xFFFFFFFF:08X}", "message": str(error)}
    finally:
        pythoncom.CoUninitialize()


def build_native_part(kind: Literal["shaft", "flange"], parameters_mm: dict) -> dict:
    """Build an editable shaft or flange and return the SolidWorks reopen evidence."""
    revision, install, template = configuration()
    evidence_root = (PROJECT / "evidence").resolve(strict=True)
    if not evidence_root.is_relative_to(PROJECT):
        raise ValueError("The evidence directory must resolve within the project.")
    job_folder = evidence_root / f"mcp-{uuid4().hex}"
    job_folder.mkdir()
    specification = job_folder / "request.json"
    with specification.open("x", encoding="ascii") as stream:
        json.dump({"schema_version": 1, "unit": "mm", kind: parameters_mm}, stream, allow_nan=False)

    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    command = [str(powershell), "-NoProfile", "-NonInteractive", "-Sta", "-ExecutionPolicy", "RemoteSigned", "-File",
               str(PROJECT / "scripts" / "Invoke-NativePartJob.ps1"), "-InstallDirectory", str(install),
               "-PartTemplate", str(template), "-RevisionMajor", str(revision), "-OutputRoot", str(job_folder),
               "-Specification", str(specification), "-Kind", kind.capitalize()]
    try:
        run = subprocess.run(command, cwd=PROJECT, capture_output=True, encoding="utf-8", errors="replace",
                             timeout=180, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "stage": "backend_timeout", "job": str(job_folder),
                "message": "The COM job timed out. Inspect the SolidWorks session before starting another job."}
    reports = list(job_folder.glob("*/report.json"))
    if len(reports) != 1:
        return {"ok": False, "stage": "backend_start", "job": str(job_folder), "message": run.stderr.strip()}
    report_path = reports[0]
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    return {"ok": run.returncode == 0 and report.get("completed") is True, "report": str(report_path), "result": report}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SolidWorks Mechanical over stdio or run a local benchmark.")
    parser.add_argument("--benchmark", choices=("shaft", "flange"))
    arguments = parser.parse_args()
    if arguments.benchmark:
        spec = json.loads((PROJECT / "examples" / "benchmarks.json").read_text(encoding="utf-8"))
        result = build_native_part(arguments.benchmark, spec[arguments.benchmark])
        print(json.dumps({key: value for key, value in result.items() if key != "result"}, ensure_ascii=True))
        return 0 if result["ok"] else 1

    from mcp.server.fastmcp import FastMCP

    server = FastMCP("SolidWorks Mechanical")
    server.tool()(solidworks_session)
    server.tool()(build_native_part)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
