#!/usr/bin/env python3
"""Tests for the run_fleet planner.

Run from the repo root:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import run_fleet  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "fixtures")


class TestPlanner(unittest.TestCase):
    """The planner branches on stack.dockerCompose. We synthesise a minimal
    config that pairs each fixture service with a stack so the branching is
    exercised."""

    def _config(self, repos_root):
        return {
            "reposRoot": repos_root,
            "logDir": os.path.join(repos_root, ".spring-fleet-logs"),
            "buildTool": {"type": "gradle", "run": "bootRun"},
            "services": [
                {
                    "name": "order-api", "path": "order-api", "port": 8081,
                    "logFile": "order-api.log",
                    "stack": {"springBootMajor": 3, "dockerCompose": False},
                },
                {
                    "name": "inventory-api", "path": "inventory-api", "port": 8083,
                    "logFile": "inventory-api.log",
                    "stack": {"springBootMajor": 4, "dockerCompose": True},
                },
            ],
        }

    def test_compose_service_uses_docker_compose(self):
        cfg = self._config(os.path.join(FIXTURES, "repos"))
        plan = run_fleet.plan_fleet(cfg, service_filter="inventory-api")
        self.assertEqual(len(plan), 1)
        step = plan[0]
        self.assertEqual(step["mode"], "compose")
        self.assertEqual(step["command"][:3], ["docker", "compose", "up"])
        self.assertFalse(step["tee"])  # compose has its own log story

    def test_non_compose_service_uses_build_tool_and_tees(self):
        cfg = self._config(os.path.join(FIXTURES, "repos"))
        plan = run_fleet.plan_fleet(cfg, service_filter="order-api")
        step = plan[0]
        self.assertEqual(step["mode"], "gradle")
        self.assertEqual(step["command"], ["gradle", "bootRun"])
        self.assertTrue(step["tee"], "non-compose services must tee stdout to logPath")
        self.assertTrue(step["logPath"].endswith("order-api.log"))

    def test_maven_service_uses_mvn(self):
        cfg = self._config(os.path.join(FIXTURES, "repos"))
        cfg["buildTool"] = {"type": "maven", "run": "spring-boot:run"}
        plan = run_fleet.plan_fleet(cfg, service_filter="order-api")
        step = plan[0]
        self.assertEqual(step["mode"], "maven")
        self.assertEqual(step["command"], ["mvn", "spring-boot:run"])

    def test_service_filter_returns_empty_for_unknown_name(self):
        cfg = self._config(os.path.join(FIXTURES, "repos"))
        plan = run_fleet.plan_fleet(cfg, service_filter="nope")
        self.assertEqual(plan, [])

    def test_all_services_when_no_filter(self):
        cfg = self._config(os.path.join(FIXTURES, "repos"))
        plan = run_fleet.plan_fleet(cfg)
        self.assertEqual({s["service"] for s in plan}, {"order-api", "inventory-api"})


if __name__ == "__main__":
    unittest.main()
