"""Regression tests for real-world logs, doctor and malformed MCP clients."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import correlate_logs
import doctor
import mcp_server


class TestLogEvents(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "app.log"
        self.config = {"logDir": self.temp.name, "traceKeys": ["sessionId"],
                       "services": [{"name": "app"}]}

    def logs(self, body, **kwargs):
        self.path.write_text(body, encoding="utf-8")
        return correlate_logs.correlate(self.config, "ABC123", **kwargs)[0]

    def test_exact_keys_and_value_boundaries(self):
        records = self.logs("\n".join([
            "sessionId=ABC1234", "other_sessionId=ABC123", "message=ABC123",
            "sessionId=ABC123", 'sessionId="ABC123"', "sessionId: 'ABC123'",
            "sessionId=ABC123-extra", "sessionId=ABC123.foo",
        ]), match="exact")
        self.assertEqual([r["lineNo"] for r in records], [4, 5, 6])

    def test_substring_compatibility(self):
        self.assertEqual(len(self.logs("message=ABC1234\n")), 1)

    def test_specific_key_overrides_config(self):
        records = self.logs("requestId=ABC123\nsessionId=ABC123\n", key="requestId")
        self.assertEqual([r["lineNo"] for r in records], [1])

    def test_structured_formats_and_nested_mdc(self):
        events = [
            {"@timestamp": "2026-06-09T12:00:00Z", "sessionId": "ABC123"},
            {"timestamp": 1781006401.125, "_sessionId": "ABC123"},
            {"@timestamp": "2026-06-09T12:00:02Z", "mdc": {"sessionId": "ABC123"}},
            {"contextMap": {"sessionId": "ABC123"}},
            {"sessionId": "ABC1234", "message": "ABC123"},
        ]
        records = self.logs("\n".join(json.dumps(e) for e in events), match="exact")
        self.assertEqual(len(records), 4)
        self.assertTrue(all("_json" not in r for r in records))
        self.assertEqual(records[-1]["timestampUtc"], None)

    def test_nested_and_flat_ecs_keys(self):
        body = '\n'.join(json.dumps(e) for e in [
            {"trace": {"id": "ABC123"}}, {"trace.id": "ABC123"},
            {"trace": {"id": "ABC1234"}},
        ])
        self.assertEqual(len(self.logs(body, key="trace.id")), 2)

    def test_timezone_and_nanosecond_order(self):
        records = self.logs("\n".join([
            "2026-06-09T12:00:00.000000002Z sessionId=ABC123",
            "2026-06-09 14:00:00,000000001+02:00 sessionId=ABC123",
            "2026-06-09T07:00:00-0500 sessionId=ABC123",
            "2026-06-09 11:59:59 sessionId=ABC123",
            "2026-99-99 00:00:00 sessionId=ABC123",
        ]))
        self.assertEqual([r["lineNo"] for r in records], [4, 3, 2, 1, 5])

    def test_stack_trace_stays_with_matching_event(self):
        records = self.logs("\n".join([
            "2026-06-09 12:00:00 sessionId=ABC123 failed",
            "java.lang.IllegalStateException: broken",
            "\tat example.Main.run(Main.java:42)",
            "Caused by: java.io.IOException: gone",
            "\t... 2 more",
            "2026-06-09 12:00:01 sessionId=OTHER failed",
            "\tat example.Other.run(Other.java:1)",
        ]), match="exact")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["endLineNo"], 5)
        self.assertIn("IOException", records[0]["line"])
        self.assertNotIn("Other.java", records[0]["line"])

    def test_error_search_in_continuation_returns_event(self):
        records = self.logs("2026-06-09 12:00:00 failure\n\tat ABC123.run(Main.java:1)\n")
        self.assertEqual(records[0]["lineNo"], 1)

    def test_malformed_json_and_invalid_timestamp_do_not_crash(self):
        records = self.logs('{broken ABC123\n{"timestamp": [], "sessionId": "ABC123"}\n')
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["timestampUtc"] is None for r in records))

    def test_empty_search_is_rejected(self):
        with self.assertRaises(ValueError):
            correlate_logs.correlate(self.config, "")

    def test_unknown_service_is_not_reported_as_no_matches(self):
        with self.assertRaisesRegex(ValueError, "unknown service"):
            correlate_logs.correlate(self.config, "ABC123", service_filter="typo")


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app").mkdir()
        (self.root / "app.log").touch()
        self.config = {"reposRoot": str(self.root), "logDir": str(self.root),
                       "buildTool": {"type": "gradle"}, "traceKeys": ["trace_id"],
                       "services": [{"name": "app", "path": "app", "port": 8080}]}

    def diagnose(self):
        with patch("doctor.shutil.which", return_value="/tools/executable"):
            return doctor.diagnose(self.config)

    def test_healthy_fleet(self):
        self.assertEqual(self.diagnose(), {"ok": True, "findings": [], "errors": 0, "warnings": 0})

    def test_invalid_shapes_are_findings(self):
        for config in ([], None, {"services": "wrong"}, dict(self.config, services=[None]),
                       dict(self.config, services=[{"name": "app", "path": "app", "port": True}])):
            with self.subTest(config=config):
                result = doctor.diagnose(config)
                self.assertFalse(result["ok"])
                self.assertEqual(result["findings"][0]["code"], "config.invalid")

    def test_duplicate_ports_missing_repos_logs_and_unknown_edges(self):
        self.config["services"].append({"name": "other", "path": "missing", "port": 8080})
        self.config["topology"] = {"edges": [["app", "unknown"]]}
        codes = {f["code"] for f in self.diagnose()["findings"]}
        self.assertTrue({"port.duplicate", "repo.missing", "log.missing", "topology.unknown"} <= codes)

    def test_dynamic_ports_do_not_conflict(self):
        self.config["services"][0]["port"] = 0
        self.config["services"].append({"name": "other", "path": "app", "port": 0})
        self.assertTrue(self.diagnose()["ok"])

    def test_missing_executables_follow_launch_plan(self):
        with patch("doctor.shutil.which", return_value=None):
            result = doctor.diagnose(self.config)
        self.assertEqual(result["errors"], 2)
        self.assertTrue(all(f["code"] == "executable.missing" for f in result["findings"]))

    def test_compose_requires_docker_not_java_or_gradle(self):
        (self.root / "app" / "compose.yaml").touch()
        self.config["services"][0]["stack"] = {"dockerCompose": True}
        with patch("doctor.shutil.which", return_value="/tools/docker") as which:
            self.assertTrue(doctor.diagnose(self.config)["ok"])
        which.assert_called_once_with("docker")

    def test_cli_exit_codes_and_json(self):
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(self.config), encoding="utf-8")
        with patch("doctor.shutil.which", return_value="/tools/executable"), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(doctor.main(["--config", str(config_path), "--format", "json"]), 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        config_path.write_text("{broken", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(doctor.main(["--config", str(config_path), "--format", "json"]), 1)
        self.assertEqual(json.loads(out.getvalue())["findings"][0]["code"], "config.read")


class TestMcpValidation(unittest.TestCase):
    def call(self, name, arguments):
        return mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": arguments}})

    def test_invalid_envelopes(self):
        for message in (None, 42, "ping", {}, [], {"jsonrpc": "1.0", "method": "ping"},
                        {"jsonrpc": "2.0", "method": "ping", "id": True},
                        {"jsonrpc": "2.0", "method": "ping", "id": None}):
            with self.subTest(message=message):
                self.assertEqual(mcp_server.handle(message)["error"]["code"], -32600)

    def test_invalid_params(self):
        for params in (None, [], "bad", 42):
            response = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
            self.assertEqual(response["error"]["code"], -32602)

    def test_invalid_arguments(self):
        for args in ({"lines": True}, {"lines": -1}, {"lines": 0}, {"lines": 1001},
                     {"lines": "5"}, {"extra": 1}, {"service": []}):
            with self.subTest(args=args):
                self.assertTrue(self.call("tail_service_log", args)["result"]["isError"])
        for args in ([], None, "bad"):
            self.assertEqual(self.call("tail_service_log", args)["error"]["code"], -32602)
        self.assertTrue(self.call("correlate_by_trace", {"trace_value": ""})["result"]["isError"])

    def test_notifications_do_not_execute_tools(self):
        with patch("doctor.check_file") as mocked:
            for method in ("ping", "initialize", "tools/list", "tools/call"):
                self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": method,
                                                    "params": {"name": "doctor"}}))
            mocked.assert_not_called()

    def test_batches_exclude_notifications(self):
        responses = mcp_server.handle([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                       {"jsonrpc": "2.0", "method": "ping"}, 7])
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["result"], {})
        self.assertEqual(responses[1]["error"]["code"], -32600)

    def test_stream_survives_bad_messages(self):
        payload = '\n'.join(['{broken', 'null', '42', '"bad"',
                             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})]) + '\n'
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "mcp_server.py")],
                                input=payload, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 5)
        self.assertEqual(responses[-1], {"jsonrpc": "2.0", "id": 2, "result": {}})

    def test_log_limits_report_truncation(self):
        env = {"SPRING_FLEET_CONFIG": str(ROOT / "fixtures" / "fleet.config.json")}
        with patch.dict(os.environ, env):
            response = self.call("correlate_by_trace", {"trace_value": "ABC123", "max_records": 2})
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["totalCount"], 9)
        self.assertTrue(data["truncated"])

    def test_large_payload_returns_actionable_error(self):
        with patch("mcp_server.MAX_OUTPUT_CHARS", 20), patch("doctor.check_file", return_value={"x": "a" * 100}):
            result = self.call("doctor", {})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("CLI", result["content"][0]["text"])

    def test_explicit_missing_config_does_not_fall_back(self):
        with patch.dict(os.environ, {"SPRING_FLEET_CONFIG": "missing-fleet-test-config.json"}):
            self.assertTrue(self.call("list_services", {})["result"]["isError"])

    def test_long_records_are_marked_truncated(self):
        with patch("mcp_server._require_config", return_value=({}, None)), patch(
                "correlate_logs.correlate", return_value=([{"line": "x" * 9000}], [])):
            data = mcp_server.tool_correlate_by_trace({"trace_value": "x"})
        self.assertEqual(len(data["records"][0]["line"]), 8000)
        self.assertTrue(data["records"][0]["lineTruncated"])
        self.assertTrue(data["truncated"])


if __name__ == "__main__":
    unittest.main()
