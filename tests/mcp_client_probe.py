"""Integration client. Starts the actual stdio server and records protocol traffic."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def execute(job_path):
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "v03-integration-client", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "solidworks_environment"}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "solidworks_environment"}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "unknown_tool"}},
        {"jsonrpc": "2.0", "id": 6, "method": "ping"},
    ]
    if job_path:
        requests.append({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "run_cad_job", "arguments": {"job": json.loads(job_path.read_text(encoding="utf-8"))}}})
    payload = "\n".join(["{"] + [json.dumps(item, ensure_ascii=True) for item in requests]) + "\n"
    started = time.perf_counter()
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "v03_mcp.py")], input=payload.encode(),
                             capture_output=True, cwd=ROOT, timeout=180)
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    by_id = {response["id"]: response for response in replies}
    environment_calls = [json.loads(by_id[index]["result"]["content"][0]["text"]) for index in (3, 4)]
    checks = [process.returncode == 0, len(by_id) == len(replies) == (8 if job_path else 7),
              by_id[None]["error"]["code"] == -32700, by_id[1]["result"]["protocolVersion"] == "2025-03-26",
              by_id[2]["result"]["tools"][0]["name"] == "solidworks_environment",
              by_id[5]["error"]["code"] == -32602, by_id[6]["result"] == {},
              all(item["status"] == "PASS" and item["revision"] == "22.0.0" for item in environment_calls)]
    if job_path:
        checks.append(by_id[7].get("result", {}).get("isError") is False)
    return {"status": "PASS" if all(checks) else "FAIL", "mcp_tool_calls": 4 if job_path else 3,
            "duration_seconds": round(time.perf_counter() - started, 3), "stdout_bytes": len(process.stdout),
            "stderr": process.stderr.decode(errors="replace"), "exit_code": process.returncode,
            "requests": requests, "replies": replies}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--job", type=Path)
    args = parser.parse_args()
    result = execute(args.job)
    with args.evidence.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    print(result["status"], result["duration_seconds"], args.evidence)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
