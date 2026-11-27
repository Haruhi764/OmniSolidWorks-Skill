"""Local, synchronous MCP stdio transport. The native executor owns CAD operations."""
import json
import sys

import v03_jobs


PROTOCOLS = ("2025-03-26", "2024-11-05")
MAX_LINE = 1_048_576


def encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


class RequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def tool_definitions():
    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    return {
        "solidworks_environment": ("Read the registered SolidWorks release and the attached COM revision.", empty, v03_jobs.environment),
        "run_cad_job": ("Execute a validated SolidWorks CAD job and return its artifact and evidence summary.",
                        {"type": "object", "required": ["job"], "properties": {"job": {"type": "object"}},
                         "additionalProperties": False}, v03_jobs.run_tool),
    }


class Server:
    def __init__(self):
        self.initialized = False
        self.ready = False
        self.tools = tool_definitions()

    def receive(self, request):
        request_id = None
        notification = False
        try:
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                raise RequestError(-32600, "Invalid Request")
            notification = "id" not in request
            request_id = request.get("id")
            if not notification and type(request_id) not in (str, int):
                request_id = None
                raise RequestError(-32600, "Invalid request ID")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise RequestError(-32602, "Expected an object for params")
            result = self.dispatch(request["method"], params, notification)
            if not notification:
                return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RequestError as exc:
            if not notification:
                return error(request_id, exc.code, str(exc))

    def dispatch(self, method, params, notification):
        if method == "notifications/initialized" and notification:
            self.ready = self.initialized
            return None
        if notification:
            return None
        if method == "ping":
            return {}
        if method == "initialize" and not self.initialized:
            version = params.get("protocolVersion")
            if not isinstance(version, str) or not isinstance(params.get("clientInfo"), dict) or not isinstance(params.get("capabilities"), dict):
                raise RequestError(-32602, "Invalid initialize params")
            self.initialized = True
            return {"protocolVersion": version if version in PROTOCOLS else PROTOCOLS[0],
                    "serverInfo": {"name": "SolidWorks Mechanical", "version": "0.3.0-dev"},
                    "capabilities": {"tools": {"listChanged": False}}}
        if not self.ready:
            raise RequestError(-32002, "Server is not initialized")
        if method == "tools/list":
            return {"tools": [{"name": name, "description": description, "inputSchema": schema}
                              for name, (description, schema, _) in self.tools.items()]}
        if method != "tools/call":
            raise RequestError(-32601, "Method not found")
        name = params.get("name")
        args = params.get("arguments", {})
        if not isinstance(name, str) or name not in self.tools or not isinstance(args, dict):
            raise RequestError(-32602, "Unknown tool or invalid arguments")
        _, schema, handler = self.tools[name]
        if set(args) != set(schema.get("required", [])):
            raise RequestError(-32602, "Unexpected tool arguments")
        try:
            result = handler(**args)
        except (ValueError, OSError, TimeoutError) as exc:
            result = {"status": "FAIL", "error": str(exc)}
        return {"isError": result.get("status") != "PASS",
                "content": [{"type": "text", "text": encode(result)}]}


def error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main():
    server = Server()
    while line := sys.stdin.buffer.readline(MAX_LINE + 1):
        if len(line) > MAX_LINE:
            print(encode(error(None, -32700, "Request exceeds the stdio limit")), flush=True)
            return 1
        try:
            message = v03_jobs.decode_document(line)
        except (ValueError, UnicodeError):
            reply = error(None, -32700, "Parse error")
        else:
            reply = server.receive(message)
        if reply is not None:
            print(encode(reply), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
