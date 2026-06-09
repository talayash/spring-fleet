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

    def test_draft_includes_placeholder_topology(self):
        self.assertIn("topology", self.draft)
        self.assertEqual(self.draft["topology"]["edges"], [])


if __name__ == "__main__":
    unittest.main()
