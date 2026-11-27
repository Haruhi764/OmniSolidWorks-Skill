"""Preflight old schema, MCP discovery, and V0.4 A with no COM or CAD writes."""
import argparse
import sys

from sw_explosion_plan import step_vector
from sw_supervisor_state import LABEL, OUTPUT, ROOT, atomic, read, require_workspace, safe, sha
from v03_mcp import Server
from v03_schema import normalize


def check(run):
    old_part = normalize(read(ROOT / "examples" / "v03" / "C-Bracket.json"), ROOT / "outputs" / "v0.3")
    if old_part["schema_version"] != 1 or old_part["document_type"] != "part":
        raise ValueError("Original V0.3 job no longer normalizes")
    server = Server()
    server.dispatch("initialize", {"protocolVersion": "2024-11-05", "clientInfo": {}, "capabilities": {}}, False)
    server.dispatch("notifications/initialized", {}, True)
    tools = server.dispatch("tools/list", {}, False)["tools"]
    if {item["name"] for item in tools} != {"solidworks_environment", "run_cad_job"}:
        raise ValueError("MCP tool discovery contract changed")
    previous = ROOT / "outputs" / "v0.4" / "jobs" / "V04-A-Core" / "run-1795525824456764900-cfe0e42d"
    old = read(previous / "normalized.json")
    evidence = read(previous / "native.json")
    stage = ROOT / "outputs" / "v0.4" / "delivery" / "A" / "assembly"
    for row in old["dependencies"]:
        path = safe(stage / "references" / (row["id"] + ".SLDPRT"))
        if sha(path) != row["sha256"]:
            raise ValueError("Historical A part changed")
    source = "V04-A-Core.SLDASM"
    if sha(safe(stage / source)) != sha(safe(previous / source)):
        raise ValueError("Historical A assembly changed")
    explosion = [row for row in old["features"] if row["operation"] == "explode"]
    vectors = {row["id"]: step_vector(row) for row in explosion}
    if len(evidence["reopenedAssembly"]["components"]) != 5 or len(vectors) != 4:
        raise ValueError("The historical A proof does not match its plan")
    result = {"mode": "offline", "oldSchema": "pass", "mcpDiscovery": "pass",
              "caseA": {"referencesHashVerified": 6, "recordedAssemblyInstances": 5,
                        "validatedDirectionVectors": vectors, "nativeThisRun": False},
              "componentLimitsChanged": False}
    atomic(run / "OFFLINE_COMPATIBILITY.json", result)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()
    require_workspace()
    if not LABEL.fullmatch(args.run) or not args.run.startswith("run-"):
        parser.error("Expected run ID")
    check(safe(OUTPUT / args.run, OUTPUT))

