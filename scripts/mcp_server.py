#!/usr/bin/env python3
"""spring-fleet MCP server: exposes the deterministic fleet operations as
typed tools so Claude (and any MCP-aware client) can call them without
parsing CLI output.

Transport: stdio (newline-delimited JSON-RPC 2.0).
Protocol:  MCP 2025-03-26 subset: initialize / tools/list / tools/call / ping.

Tools exposed:
    doctor                 - read-only fleet diagnostics and suggested fixes
    list_services          - services + ports + stack + sharedLibs
    get_topology           - entry services + [from,to] edges
    correlate_by_trace     - cross-service timeline for a trace value
    tail_service_log       - last N lines of one service log (optional grep)
    scan_repos_root        - generate a draft config from a repos directory
    find_service_log_path  - resolve a service name to its absolute log path

Config resolution (in order):
    1. `config_path` tool argument (absolute path). Codex starts plugin MCP
       servers in the plugin directory, not the project, so it must pass this.
    2. SPRING_FLEET_CONFIG env var (absolute path)
    3. <cwd>/spring-fleet.config.json

If the config is required by a tool and missing, the tool returns a
structured error in the MCP CallToolResult; the server does not crash.

Dependency-free (Python 3 stdlib only). Cross-platform.
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import correlate_logs   # noqa: E402  same dir
import scan_repos       # noqa: E402
import tail_logs        # noqa: E402
import doctor           # noqa: E402
from validation import validate  # noqa: E402

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "spring-fleet"
SERVER_VERSION = "0.2.0"  # keep in lockstep with .claude-plugin/plugin.json
MAX_OUTPUT_CHARS = 100000
MAX_LOG_CHARS = 8000


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------

def _config_path(args=None):
    explicit = (args or {}).get("config_path")
    if explicit:
        return explicit
    env = os.environ.get("SPRING_FLEET_CONFIG")
    if env:
        return env
    cwd_cfg = os.path.join(os.getcwd(), "spring-fleet.config.json")
    if os.path.isfile(cwd_cfg):
        return cwd_cfg
    return None


def _require_config(args=None):
    """Return (config, None) on success, (None, error_text) on failure."""
    path = _config_path(args)
    if path is None:
        return None, (
            "No spring-fleet config found. Pass config_path (the absolute "
            "path of the project's spring-fleet.config.json), set "
            "SPRING_FLEET_CONFIG, or run /fleet-init to generate one in the "
            "current working directory."
        )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            config = json.load(fh)
        with open(doctor.SCHEMA_PATH, encoding="utf-8") as fh:
            errors = validate(config, json.load(fh))
        if errors:
            return None, "Invalid config: " + "; ".join(errors)
        return config, None
    except (OSError, json.JSONDecodeError) as exc:
        return None, "Failed to read {}: {}".format(path, exc)


# ---------------------------------------------------------------------------
# Tool implementations - each returns a JSON-serializable structure that we
# wrap in MCP CallToolResult content blocks.
# ---------------------------------------------------------------------------

def tool_list_services(args):
    cfg, err = _require_config(args)
    if err:
        return {"error": err}
    return {
        "services": cfg.get("services", []),
        "sharedLibs": cfg.get("sharedLibs", []),
        "proxyLib": cfg.get("proxyLib"),
        "traceKeys": cfg.get("traceKeys", []),
        "logDir": cfg.get("logDir"),
        "reposRoot": cfg.get("reposRoot"),
    }


def tool_get_topology(args):
    cfg, err = _require_config(args)
    if err:
        return {"error": err}
    topology = cfg.get("topology", {}) or {}
    return {
        "entry": topology.get("entry", []) or [],
        "edges": topology.get("edges", []) or [],
        "services": [s["name"] for s in cfg.get("services", [])],
    }


def tool_correlate_by_trace(args):
    cfg, err = _require_config(args)
    if err:
        return {"error": err}
    value = (args or {}).get("trace_value")
    if not value:
        return {"error": "missing required argument 'trace_value'"}
    service = (args or {}).get("service")
    records, missing = correlate_logs.correlate(
        cfg, value, service_filter=service, match=args.get("match", "substring"), key=args.get("key"))
    total = len(records)
    records = records[:args.get("max_records", 200)]
    for record in records:
        if len(record["line"]) > MAX_LOG_CHARS:
            record["line"] = record["line"][:MAX_LOG_CHARS]
            record["lineTruncated"] = True
    return {
        "value": value,
        "count": len(records),
        "records": records,
        "totalCount": total,
        "truncated": len(records) < total or any(r.get("lineTruncated") for r in records),
        "missingLogs": [{"service": n, "path": p} for n, p in missing],
    }


def tool_tail_service_log(args):
    cfg, err = _require_config(args)
    if err:
        return {"error": err}
    service = (args or {}).get("service")
    lines = int((args or {}).get("lines", 50))
    grep = (args or {}).get("grep")
    files = tail_logs.selected_files(cfg, service)
    if not files:
        return {"error": "no services matched (got '{}')".format(service)}
    out = []
    for name, path in files:
        if not os.path.isfile(path):
            out.append({"service": name, "missing": True, "path": path, "lines": []})
            continue
        body = []
        for line in tail_logs.tail_lines(path, lines):
            line = line.rstrip("\n")
            if tail_logs.matches(line, grep):
                body.append(line[:MAX_LOG_CHARS] + (" [truncated]" if len(line) > MAX_LOG_CHARS else ""))
        out.append({"service": name, "missing": False, "path": path, "lines": body})
    return {"services": out, "grep": grep, "linesPerService": lines}


def tool_doctor(args):
    path = _config_path(args)
    return doctor.check_file(path or "spring-fleet.config.json")


def tool_scan_repos_root(args):
    repos_root = (args or {}).get("repos_root")
    log_dir = (args or {}).get("log_dir")
    if not repos_root:
        return {"error": "missing required argument 'repos_root'"}
    if not os.path.isdir(repos_root):
        return {"error": "not a directory: {}".format(repos_root)}
    return scan_repos.scan(repos_root, log_dir)


def tool_find_service_log_path(args):
    cfg, err = _require_config(args)
    if err:
        return {"error": err}
    service = (args or {}).get("service")
    if not service:
        return {"error": "missing required argument 'service'"}
    log_dir = cfg.get("logDir", "")
    for svc in cfg.get("services", []):
        if svc.get("name") == service:
            log_file = svc.get("logFile") or (service + ".log")
            path = os.path.join(log_dir, log_file)
            return {
                "service": service,
                "logFile": log_file,
                "path": path,
                "exists": os.path.isfile(path),
            }
    return {"error": "unknown service '{}'".format(service)}


# ---------------------------------------------------------------------------
# Tool registry - surface as JSON Schema so MCP clients (Claude included) can
# call them with typed arguments.
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "doctor",
        "description": "Read-only checks of fleet config, repositories, logs, ports and required executables; returns findings with fixes.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "impl": tool_doctor,
    },
    {
        "name": "list_services",
        "description": (
            "Return every service in the fleet with its port, contextPath, "
            "detected stack (Spring Boot version, Java, virtual threads, "
            "Docker Compose, Testcontainers, OpenTelemetry), plus shared "
            "libs and the configured proxyLib. Use this before tracing a "
            "request so you know which repos exist."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "impl": tool_list_services,
    },
    {
        "name": "get_topology",
        "description": (
            "Return the directed call graph of the fleet: which services "
            "receive external requests (entry) and the [from, to] edges "
            "between services. Use this to decide which downstream service "
            "to hop to during a trace."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "impl": tool_get_topology,
    },
    {
        "name": "correlate_by_trace",
        "description": (
            "Build a single cross-service chronological timeline for a "
            "trace value (W3C trace_id, span_id, sessionId, or any "
            "substring in the logs). Use match=exact or key for exact trace matching. Returns the matching log records "
            "merged across services, tagged with service/file/lineNo, and "
            "lists any services with no log file. Defaults to the earliest 200 records; inspect truncated and totalCount."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_value": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The value to correlate on. Prefer an OTel trace_id (32 lowercase hex chars).",
                },
                "service": {
                    "type": "string",
                    "description": "Limit to a single service name (optional).",
                },
                "match": {"type": "string", "enum": ["substring", "exact"], "default": "substring"},
                "key": {"type": "string", "minLength": 1, "description": "Specific trace key; implies exact matching."},
                "max_records": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
            },
            "required": ["trace_value"],
            "additionalProperties": False,
        },
        "impl": tool_correlate_by_trace,
    },
    {
        "name": "tail_service_log",
        "description": (
            "Return the last N lines of one or more service logs, "
            "optionally filtered by a grep substring. Useful for "
            "diagnostics when you don't yet have a trace value."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name, or omit for all."},
                "lines": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50},
                "grep": {"type": "string", "description": "Substring filter (optional)."},
            },
            "additionalProperties": False,
        },
        "impl": tool_tail_service_log,
    },
    {
        "name": "scan_repos_root",
        "description": (
            "Scan a directory of repos and return a draft spring-fleet "
            "config (services vs shared libs, ports, context paths, "
            "detected stack). The draft cannot infer traceKeys or "
            "topology mechanically; the caller must confirm those."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repos_root": {"type": "string"},
                "log_dir": {"type": "string"},
            },
            "required": ["repos_root"],
            "additionalProperties": False,
        },
        "impl": tool_scan_repos_root,
    },
    {
        "name": "find_service_log_path",
        "description": "Resolve a service name to its absolute log file path.",
        "inputSchema": {
            "type": "object",
            "properties": {"service": {"type": "string"}},
            "required": ["service"],
            "additionalProperties": False,
        },
        "impl": tool_find_service_log_path,
    },
]


CONFIG_PATH_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "description": (
        "Absolute path to the project's spring-fleet.config.json. Pass it "
        "whenever the server may not run in the project directory (always "
        "under Codex); otherwise SPRING_FLEET_CONFIG, then "
        "<cwd>/spring-fleet.config.json, is used."
    ),
}
for _tool in TOOLS:
    if _tool["name"] != "scan_repos_root":  # takes a repos directory instead
        _tool["inputSchema"]["properties"]["config_path"] = CONFIG_PATH_SCHEMA


def _public_tool(t):
    return {k: v for k, v in t.items() if k != "impl"}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------

def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def handle(message):
    """Dispatch one JSON-RPC message. Returns the response dict, or None for
    notifications (which by spec receive no response)."""
    if isinstance(message, list):
        if not message:
            return _error(None, -32600, "empty batch")
        responses = [handle(item) if not isinstance(item, list) else
                     _error(None, -32600, "nested batch") for item in message]
        return [r for r in responses if r is not None] or None
    if not isinstance(message, dict):
        return _error(None, -32600, "request must be an object")
    method = message.get("method")
    req_id = message.get("id")
    if (message.get("jsonrpc") != "2.0" or not isinstance(method, str)
            or ("id" in message and (isinstance(req_id, bool) or not isinstance(req_id, (str, int))))):
        return _error(None, -32600, "invalid JSON-RPC request")

    # Notifications have no id; we never respond.
    is_notification = "id" not in message
    if is_notification:
        return None
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(req_id, -32602, "params must be an object")

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # client handshake complete

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": [_public_tool(t) for t in TOOLS]})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(args, dict):
            return _error(req_id, -32602, "tool name must be a string and arguments an object")
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            return _error(req_id, -32601, "unknown tool: {}".format(name))
        errors = validate(args, tool["inputSchema"])
        if errors:
            return _result(req_id, {"isError": True, "content": [
                {"type": "text", "text": "Invalid arguments: " + "; ".join(errors)}]})
        try:
            data = tool["impl"](args)
        except Exception as exc:  # noqa: BLE001 - exposed back to the model
            return _result(req_id, {
                "isError": True,
                "content": [{"type": "text", "text": "tool '{}' raised {}: {}".format(
                    name, type(exc).__name__, exc)}],
            })
        text = json.dumps(data, indent=2, default=str)
        # Bound the entire serialized payload, including unusually large
        # configs and fleets. Do not return broken JSON or silently lose data.
        if len(text) > MAX_OUTPUT_CHARS:
            return _result(req_id, {"isError": True, "content": [{
                "type": "text", "text": "Tool output exceeds 100000 characters. Narrow the service/filter, reduce max_records or lines, or use the CLI for full output."}]})
        is_error = isinstance(data, dict) and "error" in data
        return _result(req_id, {
            "isError": bool(is_error),
            "content": [{"type": "text", "text": text}],
        })

    if is_notification:
        return None
    return _error(req_id, -32601, "method not found: {}".format(method))


def serve(stdin=None, stdout=None):
    """Run the stdio loop. Each input line is one JSON-RPC message; each
    response is one line on stdout. Exits cleanly on EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            stdout.write(json.dumps(_error(None, -32700, "parse error: " + str(exc))) + "\n")
            stdout.flush()
            continue
        response = handle(message)
        if response is None:
            continue
        stdout.write(json.dumps(response) + "\n")
        stdout.flush()


if __name__ == "__main__":
    serve()
