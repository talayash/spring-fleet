#!/usr/bin/env python3
"""Tests for the spring-fleet deterministic scripts, run against fixtures.

Run from the repo root:
    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import correlate_logs  # noqa: E402
import scan_repos  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "fixtures")
FLEET_CONFIG = os.path.join(FIXTURES, "fleet.config.json")


def load_fixture_config():
    cfg = correlate_logs.load_config(FLEET_CONFIG)
    # Resolve logDir relative to repo root so tests run from anywhere.
    cfg["logDir"] = os.path.join(REPO_ROOT, cfg["logDir"])
    return cfg


class TestCorrelate(unittest.TestCase):
    def setUp(self):
        self.cfg = load_fixture_config()

    def test_correlates_session_across_three_services(self):
        records, missing = correlate_logs.correlate(self.cfg, "ABC123")
        self.assertEqual(missing, [])
        services = {r["service"] for r in records}
        self.assertEqual(services, {"orchestrator", "order", "payment"})

    def test_timeline_is_chronological(self):
        records, _ = correlate_logs.correlate(self.cfg, "ABC123")
        timestamps = [r["ts"] for r in records]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_first_event_is_orchestrator_receive(self):
        records, _ = correlate_logs.correlate(self.cfg, "ABC123")
        self.assertEqual(records[0]["service"], "orchestrator")
        self.assertIn("received reserve request", records[0]["line"])

    def test_failure_origin_is_payment_gateway(self):
        records, _ = correlate_logs.correlate(self.cfg, "ABC123")
        errors = [r for r in records if "ERROR" in r["line"]]
        # The earliest error should be the payment gateway timeout.
        self.assertEqual(errors[0]["service"], "payment")
        self.assertIn("gateway timeout", errors[0]["line"])

    def test_filter_excludes_other_session(self):
        records, _ = correlate_logs.correlate(self.cfg, "ABC123")
        self.assertTrue(all("ZZZ999" not in r["line"] for r in records))

    def test_service_filter(self):
        records, _ = correlate_logs.correlate(self.cfg, "ABC123", service_filter="payment")
        self.assertTrue(records)
        self.assertTrue(all(r["service"] == "payment" for r in records))

    def test_no_match_returns_empty(self):
        records, _ = correlate_logs.correlate(self.cfg, "NOPE-NO-SUCH-ID")
        self.assertEqual(records, [])

    def test_text_line_does_not_duplicate_timestamp(self):
        records, _ = correlate_logs.correlate(self.cfg, "ABC123")
        line = correlate_logs.format_text_line(records[0])
        # The timestamp must appear exactly once in the rendered line.
        self.assertEqual(line.count(records[0]["ts"]), 1)
        # Format is "<ts> [service] <message>".
        self.assertTrue(line.startswith(records[0]["ts"] + " "))
        self.assertIn("[orchestrator]", line)

    def test_correlates_by_w3c_trace_id(self):
        """OTel W3C trace_id is a 32-char lowercase hex string and is the
        modern primary correlation key (Micrometer Observation MDC). The same
        trace_id must appear on every service participating in the request."""
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        records, missing = correlate_logs.correlate(self.cfg, trace_id)
        self.assertEqual(missing, [])
        services = {r["service"] for r in records}
        self.assertEqual(services, {"orchestrator", "order", "payment"})

    def test_each_service_has_distinct_span_id(self):
        """Each service hop gets its own 16-hex span_id under a shared trace_id.
        Correlating on a service-specific span_id must return only that service."""
        records, _ = correlate_logs.correlate(self.cfg, "00f067aa0ba902b7")
        self.assertTrue(records, "expected payment-only span lines")
        self.assertEqual({r["service"] for r in records}, {"payment"})


class TestScanRepos(unittest.TestCase):
    def setUp(self):
        self.root = os.path.join(FIXTURES, "repos")
        self.draft = scan_repos.scan(self.root, log_dir=None)

    def test_detects_service_and_lib_separately(self):
        names = {s["name"] for s in self.draft["services"]}
        libs = {l["name"] for l in self.draft["sharedLibs"]}
        self.assertIn("order-api", names)
        self.assertIn("core-lib", libs)
        self.assertNotIn("core-lib", names)

    def test_extracts_port_and_context_path(self):
        order = next(s for s in self.draft["services"] if s["name"] == "order-api")
        self.assertEqual(order["port"], 8081)
        self.assertEqual(order["contextPath"], "/order-v1")

    def test_build_tool_is_gradle(self):
        self.assertEqual(self.draft["buildTool"]["type"], "gradle")

    def test_draft_includes_topology_shape(self):
        """The draft always has a topology object with entry + edges arrays.
        Edges may be empty (no Backstage catalog files present) or populated
        (Backstage catalog-info.yaml dependsOn was ingested) — either is
        fine here; the dedicated TestBackstageIngestion tests cover content."""
        self.assertIn("topology", self.draft)
        self.assertIn("entry", self.draft["topology"])
        self.assertIn("edges", self.draft["topology"])
        self.assertIsInstance(self.draft["topology"]["entry"], list)
        self.assertIsInstance(self.draft["topology"]["edges"], list)

    def test_default_trace_keys_lead_with_otel(self):
        """scan_repos must produce OTel-first trace keys by default so new
        configs land aligned with Micrometer Observation / OpenTelemetry."""
        self.assertEqual(self.draft["traceKeys"][:2], ["trace_id", "span_id"])


class TestStackDetection(unittest.TestCase):
    """scan_repos.py learns the modern Spring Boot stack so consumers (MCP
    tools, /run, agents) can branch on what's actually deployed."""

    def setUp(self):
        self.root = os.path.join(FIXTURES, "repos")
        self.draft = scan_repos.scan(self.root, log_dir=None)
        self.services = {s["name"]: s for s in self.draft["services"]}

    def test_inventory_api_is_detected(self):
        self.assertIn("inventory-api", self.services)

    def test_inventory_api_stack_is_modern(self):
        stack = self.services["inventory-api"].get("stack", {})
        self.assertEqual(stack.get("springBootMajor"), 4)
        self.assertEqual(stack.get("java"), 21)
        self.assertTrue(stack.get("virtualThreads"))
        self.assertTrue(stack.get("graalNative"))
        self.assertTrue(stack.get("dockerCompose"))
        self.assertTrue(stack.get("testcontainers"))
        self.assertTrue(stack.get("opentelemetry"))
        self.assertTrue(stack.get("springAiMcpServer"),
                        "fixture inventory-api ships a Spring AI MCP server starter")

    def test_order_api_is_spring_boot_3_baseline(self):
        stack = self.services["order-api"].get("stack", {})
        self.assertEqual(stack.get("springBootMajor"), 3)
        # order-api is the baseline fixture: no compose, no testcontainers,
        # no virtual threads, no native plugin, no OTel.
        self.assertFalse(stack.get("dockerCompose"))
        self.assertFalse(stack.get("testcontainers"))
        self.assertFalse(stack.get("virtualThreads"))
        self.assertFalse(stack.get("graalNative"))
        self.assertFalse(stack.get("opentelemetry"))


class TestBackstageIngestion(unittest.TestCase):
    """Backstage's catalog-info.yaml dominates the 2026 service-catalog space.
    Ingesting it gives scan_repos a free source of ownership + dependencies."""

    def setUp(self):
        self.root = os.path.join(FIXTURES, "repos")
        self.draft = scan_repos.scan(self.root, log_dir=None)
        self.services = {s["name"]: s for s in self.draft["services"]}

    def test_catalog_owner_and_system_lifted_into_service(self):
        inv = self.services["inventory-api"]
        self.assertEqual(inv.get("backstage", {}).get("owner"), "team-fleet")
        self.assertEqual(inv.get("backstage", {}).get("system"), "fleet-platform")
        self.assertEqual(inv.get("backstage", {}).get("lifecycle"), "production")

    def test_depends_on_components_become_topology_edges(self):
        """A `dependsOn: component:order-api` in inventory's catalog becomes
        an edge inventory-api -> order-api in the topology draft."""
        edges = self.draft["topology"]["edges"]
        self.assertIn(["inventory-api", "order-api"], edges)

    def test_components_become_topology_entries_when_no_inbound_edges(self):
        """A component with no inbound `dependsOn:component:` reference is a
        topology entry candidate. inventory-api has no inbound, so it should
        be in entry; order-api has an inbound from inventory and should not."""
        entries = self.draft["topology"]["entry"]
        self.assertIn("inventory-api", entries)
        self.assertNotIn("order-api", entries)


if __name__ == "__main__":
    unittest.main()
