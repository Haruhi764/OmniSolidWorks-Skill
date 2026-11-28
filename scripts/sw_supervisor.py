"""Supervise incremental jobs through the existing STA native bridge."""
import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from sw_supervisor_state import (
    LABEL, OUTPUT, ROOT, atomic, classify, digest, exclusive, read, refresh,
    require_workspace, safe, sha, shorten, snapshot,
)
from v03_jobs import NATIVE_TYPES, configuration, environment, get_template, host_command, verify_native_output

PHASES = {"smoke", "explode-capture", "explode", "drawing", "drawing-r1", "drawing-r2", "regression"}
HARD_TIMEOUT = 600
MAX_ATTEMPTS = 3
HOST_FAILURES = {"host_timeout", "host_disconnected", "worker_missing_evidence"}
REOPEN = {"part": "reopenedGeometry", "assembly": "reopenedAssembly", "drawing": "reopenedDrawing"}


def fault_events():
    command = """$ErrorActionPreference='SilentlyContinue'
    Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000,1002; StartTime=(Get-Date).AddMinutes(-12)} -MaxEvents 25 |
    Where-Object {$_.Message -match '(?i)sldworks.exe|sldapiu.dll|swccu.dll'} |
    Select-Object -First 4 |
    ForEach-Object {$p=$_.Properties; [pscustomobject]@{
      utc=$_.TimeCreated.ToUniversalTime().ToString('o'); event=$_.Id;
      module=if($p.Count -gt 3){[IO.Path]::GetFileName([string]$p[3].Value)}else{''};
      exception=if($p.Count -gt 6){[string]$p[6].Value}else{''};
      process=if($p.Count -gt 8){[string]$p[8].Value}else{''}
    }} | ConvertTo-Json -Compress"""
    try:
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
        return json.loads(proc.stdout.decode("utf-8-sig")) if proc.stdout.strip() else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unavailable"}


def native_worker(folder, kind, host, timeout, progress):
    revision, install, templates = configuration()
    template = get_template(kind, templates)
    cmd = host_command("Invoke-V03Job.ps1", revision, install, template, folder, host["pid"])
    return bounded_worker(cmd, folder, timeout, progress)


def bounded_worker(cmd, folder, timeout, progress):
    log = folder / "worker.log"
    deadline = time.monotonic() + timeout
    last_update = time.monotonic()
    warned = False
    with log.open("xb") as stream, log.open("rb") as reader:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        progress(worker_pid=proc.pid)
        try:
            while proc.poll() is None:
                position = reader.tell()
                raw = reader.readline()
                if raw.endswith(b"\n"):
                    fields = raw.decode("utf-8", "replace").strip().split("\t")
                    if len(fields) == 4 and fields[0] == "SW_PROGRESS":
                        last_update = time.monotonic()
                        warned = False
                        progress(stage=shorten(fields[2]), call=shorten(fields[3]), heartbeat=fields[1])
                else:
                    reader.seek(position)
                    time.sleep(.25)
                if not warned and time.monotonic() - last_update >= 90:
                    warned = True
                    progress(observation="90s without a native milestone")
                if time.monotonic() >= deadline:
                    proc.kill()
                    proc.wait(timeout=10)
                    return proc.returncode, True
            return proc.returncode, False
        finally:
            # This handle belongs to the helper launched here. SLDWORKS is external.
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)


def prepare(folder, plan):
    for path, expected in plan.get("engine", {}).items():
        if sha(safe(ROOT / path)) != expected:
            raise ValueError("Executor code changed since preflight")
    for name, src in plan.get("inputs", {}).items():
        source = safe(ROOT / src["path"])
        target = safe(folder / name, folder)
        if sha(source) != src["sha256"]:
            raise ValueError("Resume input hash changed: " + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as inp, target.open("xb") as out:
            shutil.copyfileobj(inp, out)
        if sha(target) != src["sha256"]:
            raise ValueError("Staged input hash mismatch: " + name)
    atomic(folder / "normalized.json", plan["job"])


def eligible(native, phase, kind, host):
    return (native.get("status") == "PASS" and native.get("stage") == "complete"
            and native.get("pid") == host["pid"] and native.get("revision") == host["revision"]
            and native.get("documentCountAfter") == 0 and native.get("preferencesRestored") is True
            and (native.get("capturedAssembly") if phase == "explode-capture"
                 else native.get(REOPEN[kind]) and native.get("nativeSave", {}).get("ok")
                 and native.get("nativeOpen", {}).get("ok"))
            and (phase != "explode" or (
                native.get("solidInterferenceQuery") is True and native.get("solidInterferences") == []
                and native.get("reopenedExplosion", {}).get("verified") is True)))


def inspect(folder):
    path = folder / "job_state.json"
    state = read(path) if path.exists() else {"status": "queued", "attempt": 0}
    if state["status"] == "verified":
        try:
            state["hashes_match"] = snapshot(folder / "verified", state["accepted"]) == state["accepted"]
        except (ValueError, OSError):
            state["hashes_match"] = False
    return state


def supervise(run, phase, plan, probe=environment, worker=native_worker, event_probe=fault_events,
              *, host_job_limit=8):
    if not 1 <= host_job_limit <= 16:
        raise ValueError("The native job budget must be between 1 and 16")
    folder = safe(run / phase, run)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "job_state.json"
    journal = run / "resource.json"
    base = read(run / "BASELINE.json")
    deadline = datetime.fromisoformat(base["started"]).timestamp() + 7200
    fingerprint = digest(plan)
    with exclusive(OUTPUT / ".launch.lock"):
        budget = read(journal) if journal.exists() else {"host_jobs": 0, "retries": 0, "restarts": 0,
                                                         "cache_hits": 0, "host_faults": 0}
        state = inspect(folder)
        if state["status"] == "checkpointed":
            candidate = safe(folder / "verified", folder)
            if not candidate.is_dir():
                candidate = safe(run / state["partial"], folder)
            if (state.get("input_hash") != fingerprint or
                    snapshot(candidate, state["accepted"]) != state["accepted"]):
                raise ValueError("An interrupted publication no longer matches its verified hashes")
            if candidate.name != "verified":
                candidate.rename(folder / "verified")
            refresh(path, state, "verified", "published_after_interruption", last_verified=phase)
            return state
        if state["status"] == "verified":
            if state.get("input_hash") != fingerprint or not state.get("hashes_match"):
                raise ValueError("Verified checkpoint changed. Use a new phase/run ID.")
            for src in plan.get("inputs", {}).values():
                if sha(safe(ROOT / src["path"])) != src["sha256"]:
                    raise ValueError("Verified job input changed")
            budget["cache_hits"] += 1
            atomic(journal, budget)
            return state
        if state.get("input_hash") not in (None, fingerprint):
            raise ValueError("Resume input changed. Preserve this run and use another run ID.")
        open_phases = [previous for previous in run.iterdir() if previous.is_dir() and
                       (previous / "job_state.json").is_file() and inspect(previous)["status"] == "running"]
        if open_phases:
            raise BlockingIOError("Unresolved interrupted native worker. Preserve partial output and check host.")
        for retry in range(2):
            remaining = deadline - time.time()
            if remaining <= 1 or budget["host_jobs"] >= host_job_limit or budget["host_faults"] >= 2:
                refresh(path, state, "blocked", "budget_or_circuit_breaker", input_hash=fingerprint)
                return state
            if state["attempt"] >= MAX_ATTEMPTS:
                return state
            refresh(path, state, "preflight", "host_and_inputs", input_hash=fingerprint,
                    resume=f"python -B scripts/sw_supervisor.py {run.name} {phase}",
                    last_verified=state.get("last_verified"))
            try:
                host = probe()
            except (ValueError, OSError, TimeoutError) as error:
                host = {"status": "BLOCKED", "error": shorten(error)}
            if (host.get("status") != "PASS" or host.get("documents") != 0 or
                    host.get("revision") != plan["host_revision"] or
                    host.get("pid") == budget.get("unsafe_pid")):
                events = event_probe() if host.get("status") != "PASS" else []
                refresh(path, state, "blocked", "host_precondition", host=host, events=events)
                return state
            if state.get("reason") in HOST_FAILURES and host["pid"] == state.get("host_pid"):
                refresh(path, state, "blocked", "prior_host_cleanup_unconfirmed")
                return state
            index = len(list((folder / "partial").glob("attempt-*"))) + 1
            partial = safe(folder / "partial" / f"attempt-{index}", folder)
            partial.mkdir(parents=True)
            try:
                prepare(partial, plan)
            except (OSError, ValueError) as error:
                refresh(path, state, "blocked", "input_validation", failure=shorten(error))
                return state
            budget["host_jobs"] += 1
            budget["retries"] += int(state["attempt"] > 0)
            atomic(journal, budget)
            refresh(path, state, "running", "worker_start", attempt=state["attempt"] + 1,
                    host_pid=host["pid"], host_revision=host["revision"], host_owned=False,
                    partial=partial.relative_to(run).as_posix(), failure=None, reason=None,
                    accepted={}, resume_from=plan.get("checkpoint"))
            def progress(stage=None, **data):
                refresh(path, state, "running", stage or state["stage"], **data)
            try:
                code, timed_out = worker(partial, plan["job"]["document_type"], host,
                                         min(HARD_TIMEOUT, max(1, remaining)), progress)
                native_path = partial / "native.json"
                native = read(native_path) if native_path.exists() else {}
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                code, timed_out, native = 1, False, {}
                state["failure"] = shorten(error)
            if code == 0 and not timed_out and eligible(native, phase, plan["job"]["document_type"], host):
                try:
                    accepted = snapshot(partial, ["native.json", *plan["outputs"], *plan.get("retain", [])])
                    for name in plan["outputs"]:
                        artifact = partial / name
                        if artifact.suffix.lower() in NATIVE_TYPES:
                            row = accepted[name]
                            verify_native_output(artifact, native, row["bytes"], row["sha256"])
                except (OSError, ValueError) as error:
                    refresh(path, state, "failed", "artifact_validation", failure=shorten(error))
                    return state
                refresh(path, state, "checkpointed", "checked_hashes", accepted=accepted)
                verified = safe(folder / "verified", folder)
                if verified.exists():
                    raise FileExistsError("Verified checkpoint already exists")
                partial.rename(verified)
                refresh(path, state, "verified", "published", last_verified=phase, failure=None,
                        elapsed_native=native.get("nativeSeconds"))
                return state
            status, reason = classify(code, native, timed_out)
            if reason in HOST_FAILURES:
                budget["host_faults"] += 1
                budget["unsafe_pid"] = host["pid"]
                atomic(journal, budget)
            refresh(path, state, status, native.get("stage", state["stage"]), reason=reason,
                    hresult=native.get("hresult"), failure=state.get("failure") or shorten(
                        native.get("error") or ("Native worker timed out" if timed_out else "Native verification failed")),
                    events=event_probe() if reason in HOST_FAILURES else [],
                    worker_exit=code, native_rebuilds=native.get("rebuildCount"))
            if status != "retryable" or retry == 1:
                return state
            time.sleep(.8)
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("phase", choices=sorted(PHASES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    require_workspace()
    if not LABEL.fullmatch(args.run) or not args.run.startswith("run-"):
        parser.error("Expected run ID")
    run = safe(OUTPUT / args.run, OUTPUT)
    if args.dry_run:
        result = inspect(run / args.phase)
        if (run / "resource.json").is_file():
            result["run_budget"] = read(run / "resource.json")
    else:
        plan = read(run / "plans" / f"{args.phase}.json")
        result = supervise(run, args.phase, plan)
    print(json.dumps({k: v for k, v in result.items() if k != "transitions"}, ensure_ascii=True))
    return int(not args.dry_run and result["status"] != "verified")


if __name__ == "__main__":
    raise SystemExit(main())

