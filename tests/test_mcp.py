#!/usr/bin/env python3
"""Tests for the spring-fleet MCP server.

We exercise it two ways:
  - direct dispatch via mcp_server.handle() for fast, deterministic checks
  - subprocess stdio round-trip to confirm the JSON-RPC newline framing

Run from the repo root:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import mcp_server  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "fixtures")
FLEET_CONFIG = os.path.join(FIXTURES, "fleet.config.json")


def _call_tool(name, args, env_overrides=None):
    """Direct in-process dispatch — sets SPRING_FLEET_CONFIG, restores after."""
    original = os.environ.get("SPRING_FLEET_CONFIG")
    if env_overrides:
        os.environ.update(env_overrides)
    try:
        resp = mcp_server.handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        })
    finally:
        if original is None:
            os.environ.pop("SPRING_FLEET_CONFIG", None)
        else:
            os.environ["SPRING_FLEET_CONFIG"] = original
    return resp


class TestProtocol(unittest.TestCase):
    def test_initialize_returns_capabilities(self):
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        result = resp["result"]
        self.assertEqual(result["serverInfo"]["name"], "spring-fleet")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["protocolVersion"], mcp_server.PROTOCOL_VERSION)

    def test_tools_list_includes_core_tools(self):
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("list_services", names)
        self.assertIn("get_topology", names)
        self.assertIn("correlate_by_trace", names)
        self.assertIn("tail_service_log", names)
        self.assertIn("scan_repos_root", names)
        self.assertIn("find_service_log_path", names)

    def test_tools_list_schemas_have_no_impl_field(self):
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        for t in resp["result"]["tools"]:
            self.assertNotIn("impl", t)
            self.assertIn("inputSchema", t)
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_initialized_notification_returns_none(self):
        # Notifications have no id and never get a response.
        resp = mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(resp)

    def test_unknown_method_yields_jsonrpc_error(self):
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 9, "method": "no.such.method"})
        self.assertEqual(resp["error"]["code"], -32601)

    def test_unknown_tool_yields_jsonrpc_error(self):
        resp = mcp_server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "bogus", "arguments": {}}
        })
        self.assertEqual(resp["error"]["code"], -32601)


class TestTools(unittest.TestCase):
    def setUp(self):
        self.env = {"SPRING_FLEET_CONFIG": FLEET_CONFIG}

    def _payload(self, resp):
        return json.loads(resp["result"]["content"][0]["text"])

    def test_list_services_returns_fleet(self):
        resp = _call_tool("list_services", {}, env_overrides=self.env)
        data = self._payload(resp)
        names = {s["name"] for s in data["services"]}
        self.assertEqual(names, {"orchestrator", "order", "payment"})
        self.assertEqual(data["traceKeys"][0], "trace_id")

    def test_get_topology_returns_edges(self):
        resp = _call_tool("get_topology", {}, env_overrides=self.env)
        data = self._payload(resp)
        self.assertEqual(data["entry"], ["orchestrator"])
        self.assertIn(["orchestrator", "order"], data["edges"])

    def test_correlate_by_trace_id_returns_all_services(self):
        resp = _call_tool(
            "correlate_by_trace",
            {"trace_value": "4bf92f3577b34da6a3ce929d0e0e4736"},
            env_overrides=self.env,
        )
        data = self._payload(resp)
        self.assertEqual(data["count"], 9)  # full fixture timeline
        services = {r["service"] for r in data["records"]}
        self.assertEqual(services, {"orchestrator", "order", "payment"})

    def test_correlate_missing_argument_is_error(self):
        resp = _call_tool("correlate_by_trace", {}, env_overrides=self.env)
        self.assertTrue(resp["result"]["isError"])

    def test_tail_service_log_returns_lines(self):
        resp = _call_tool(
            "tail_service_log",
            {"service": "payment", "lines": 5},
            env_overrides=self.env,
        )
        data = self._payload(resp)
        services = {s["service"] for s in data["services"]}
        self.assertEqual(services, {"payment"})
        self.assertTrue(any("gateway timeout" in l for s in data["services"] for l in s["lines"]))

    def test_find_service_log_path_resolves(self):
        resp = _call_tool(
            "find_service_log_path",
            {"service": "order"},
            env_overrides=self.env,
        )
        data = self._payload(resp)
        self.assertTrue(data["path"].endswith("order.log"))

    def test_no_config_returns_structured_error(self):
        # Use a directory we know has no spring-fleet.config.json.
        original = os.environ.get("SPRING_FLEET_CONFIG")
        os.environ.pop("SPRING_FLEET_CONFIG", None)
        original_cwd = os.getcwd()
        os.chdir(os.path.join(REPO_ROOT, "docs"))
        try:
            resp = mcp_server.handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "list_services", "arguments": {}}
            })
        finally:
            os.chdir(original_cwd)
            if original is not None:
                os.environ["SPRING_FLEET_CONFIG"] = original
        self.assertTrue(resp["result"]["isError"])


class TestStdioFraming(unittest.TestCase):
    """Subprocess round-trip — confirms newline-delimited JSON-RPC."""

    def test_initialize_then_tools_list(self):
        env = os.environ.copy()
        env["SPRING_FLEET_CONFIG"] = FLEET_CONFIG
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "mcp_server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )
        try:
            init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            tlist = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            out, err = proc.communicate(init + "\n" + tlist + "\n", timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
        lines = [json.loads(l) for l in out.strip().splitlines()]
        self.assertEqual(len(lines), 2, "expected one response per request, got " + repr(out))
        self.assertEqual(lines[0]["id"], 1)
        self.assertEqual(lines[1]["id"], 2)
        names = {t["name"] for t in lines[1]["result"]["tools"]}
        self.assertIn("correlate_by_trace", names)


if __name__ == "__main__":
    unittest.main()
