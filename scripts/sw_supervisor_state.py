"""Recoverable state and file publication for the existing SolidWorks bridge."""
import hashlib
import json
import msvcrt
import os
import re
import stat
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from v03_jobs import ROOT, canonical, sha

OUTPUT = ROOT / "outputs" / "incremental"
LABEL = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
HOST_FAULTS = {"0x80010108", "0x800706BA", "0x800706BE", "0x800401FD", "0xC0000005"}
BUSY_FAULTS = {"0x80010001", "0x8001010A"}


def safe(path, parent=ROOT):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(parent):
        raise ValueError("Path is outside the authorized output or repository")
    for item in (path, *path.parents):
        try:
            flags = item.lstat().st_file_attributes
        except FileNotFoundError:
            continue
        if flags & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Reparse point in managed path")
    return path


def require_workspace(*, allow_installed=False):
    if Path.cwd() != ROOT:
        raise ValueError("Run the SolidWorks workflow from its own root")
    if allow_installed and not (ROOT / ".git").exists():
        manifest = safe(ROOT / "RELEASE_MANIFEST.json")
        if manifest.is_file():
            release = json.loads(manifest.read_text(encoding="utf-8-sig"))
            skill = safe(ROOT / "SKILL.md")
            if release.get("schema") == 1 and any(
                    row.get("path") == "SKILL.md" and row.get("sha256") == sha(skill)
                    for row in release.get("files", ())):
                return
    actual = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True).strip()
    if Path(actual) != ROOT:
        raise ValueError("Wrong SolidWorks workspace")
    safe(ROOT)


def read(path):
    return json.loads(safe(path).read_text(encoding="utf-8-sig"))


def atomic(path, data):
    safe(path)
    encoded = canonical(data) + b"\n"
    pending = safe(path.with_name(path.name + "." + uuid4().hex[:10] + ".writing"))
    try:
        with pending.open("xb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        if pending.read_bytes() != encoded:
            raise OSError("State verification failed")
        pending.replace(path)
    finally:
        if pending.exists():
            pending.unlink()


@contextmanager
def exclusive(path):
    with safe(path).open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError("Another supervisor holds the launch lock") from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def digest(data):
    return hashlib.sha256(canonical(data)).hexdigest()


def snapshot(folder, names):
    records = {}
    for name in names:
        path = safe(folder / name, folder)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("Missing or empty artifact: " + name)
        records[name] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    return records


def refresh(state_path, state, status, stage, **extra):
    now = time.time()
    if state.get("stage") != stage or state.get("status") != status:
        state.setdefault("transitions", []).append({"status": status, "stage": stage, "utc_epoch": now})
    state.update(extra, status=status, stage=stage, updated_at=now)
    atomic(state_path, state)


def classify(code, native, timed_out=False):
    if timed_out:
        return "blocked", "host_timeout"
    error = (native.get("hresult") or "").upper().replace("0X", "0x")
    if error in BUSY_FAULTS:
        if native.get("stage") == "attach" or native.get("documentCountAfter") == 0:
            return "retryable", "rpc_busy"
        return "blocked", "rpc_busy_cleanup_unknown"
    if error in HOST_FAULTS or (code & 0xffffffff) == 0xc0000005:
        return "blocked", "host_disconnected"
    if not native:
        return "blocked", "worker_missing_evidence"
    message = (native.get("error") or "").casefold()
    if (native.get("status") == "BLOCKED" or native.get("stage") in {"attach", "compile"}
            or any(flag in message for flag in ("license", "access denied", "part references",
                                               "reference is unresolved", "already active", "mutex"))):
        return "blocked", "native_precondition"
    return "failed", "model_or_api"


def shorten(value):
    text = str(value).replace(str(ROOT), "<workspace>")
    text = re.sub(r"(?i)[a-z]:\\Users\\[^\\\r\n]+", "<user-profile>", text)
    return " ".join(text.split())[:360]

