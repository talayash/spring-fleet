#!/usr/bin/env python3
"""Tests for spring-fleet hooks.

The SessionStart hook receives a JSON blob on stdin and prints a JSON
response. We exercise it as a subprocess so the test mirrors how Claude Code
actually invokes it.

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
HOOK = os.path.join(REPO_ROOT, "hooks", "session_start.py")
FIXTURES = os.path.join(REPO_ROOT, "fixtures")
FLEET_CONFIG = os.path.join(FIXTURES, "fleet.config.json")


def _run_hook(stdin_text, env_overrides=None, cwd=None):
    env = os.environ.copy()
    # Strip any inherited SPRING_FLEET_CONFIG so tests are deterministic.
    env.pop("SPRING_FLEET_CONFIG", None)
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, HOOK],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or REPO_ROOT,
        timeout=10,
    )
    return proc


class TestSessionStartHook(unittest.TestCase):
    def test_no_config_returns_empty_json(self):
        """Outside a spring-fleet project the hook must be a no-op so it
        never blocks a session."""
        proc = _run_hook("{}", cwd=os.path.join(REPO_ROOT, "docs"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {})

    def test_config_via_env_var(self):
        proc = _run_hook(
            "{}",
            env_overrides={"SPRING_FLEET_CONFIG": FLEET_CONFIG},
            cwd=os.path.join(REPO_ROOT, "docs"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")
        ctx = data["hookSpecificOutput"]["additionalContext"]
        # Topology lists every service from the fixture fleet.
        self.assertIn("orchestrator", ctx)
        self.assertIn("order", ctx)
        self.assertIn("payment", ctx)
        # Trace keys are present and OTel-first.
        self.assertIn("trace_id", ctx)
        # Edges render.
        self.assertIn("orchestrator", ctx)

    def test_corrupt_config_does_not_crash(self):
        bad = os.path.join(REPO_ROOT, "tests", "_corrupt.config.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        try:
            proc = _run_hook(
                "{}",
                env_overrides={"SPRING_FLEET_CONFIG": bad},
                cwd=os.path.join(REPO_ROOT, "docs"),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertIn("could not be loaded", data["hookSpecificOutput"]["additionalContext"])
        finally:
            os.remove(bad)


STATUSLINE = os.path.join(REPO_ROOT, "hooks", "statusline.py")
SUBAGENT_STOP = os.path.join(REPO_ROOT, "hooks", "subagent_stop.py")


def _run_statusline(stdin_text, env_overrides=None, cwd=None):
    env = os.environ.copy()
    env.pop("SPRING_FLEET_CONFIG", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, STATUSLINE],
        input=stdin_text, capture_output=True, text=True,
        env=env, cwd=cwd or REPO_ROOT, timeout=10,
    )


def _run_subagent_stop(stdin_text, env_overrides=None, cwd=None):
    env = os.environ.copy()
    env.pop("SPRING_FLEET_CONFIG", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, SUBAGENT_STOP],
        input=stdin_text, capture_output=True, text=True,
        env=env, cwd=cwd or REPO_ROOT, timeout=10,
    )


class TestSubagentStopHook(unittest.TestCase):
    def setUp(self):
        # Use a temporary handoff log directory so tests don't pollute fixtures.
        self.tmpdir = os.path.join(REPO_ROOT, "tests", "_tmp_handoff")
        os.makedirs(self.tmpdir, exist_ok=True)
        self.cfg_path = os.path.join(self.tmpdir, "spring-fleet.config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as fh:
            json.dump({
                "reposRoot": self.tmpdir, "buildTool": {"type": "gradle"},
                "logDir": self.tmpdir, "services": [{"name": "x", "path": "x"}],
            }, fh)
        self.handoff = os.path.join(self.tmpdir, ".spring-fleet-handoff.log")
        if os.path.isfile(self.handoff):
            os.remove(self.handoff)

    def tearDown(self):
        for fn in (".spring-fleet-handoff.log", "spring-fleet.config.json"):
            p = os.path.join(self.tmpdir, fn)
            if os.path.isfile(p):
                os.remove(p)
        if os.path.isdir(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_our_agent_output_is_appended(self):
        payload = json.dumps({
            "subagent_name": "log-correlator",
            "output": "TRACE VALUE: abc\nFAILURE ORIGIN: payment\n",
        })
        proc = _run_subagent_stop(
            payload,
            env_overrides={"SPRING_FLEET_CONFIG": self.cfg_path},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(self.handoff))
        with open(self.handoff, "r", encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("log-correlator", body)
        self.assertIn("FAILURE ORIGIN: payment", body)

    def test_foreign_agent_is_ignored(self):
        payload = json.dumps({"subagent_name": "some-other-agent", "output": "noise"})
        proc = _run_subagent_stop(
            payload,
            env_overrides={"SPRING_FLEET_CONFIG": self.cfg_path},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(os.path.isfile(self.handoff),
                         "handoff log must not exist for non-fleet subagents")

    def test_no_config_is_noop(self):
        payload = json.dumps({"subagent_name": "log-correlator", "output": "x"})
        proc = _run_subagent_stop(payload, cwd=os.path.join(REPO_ROOT, "docs"))
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestStatusLine(unittest.TestCase):
    def test_no_config_prints_nothing(self):
        proc = _run_statusline("{}", cwd=os.path.join(REPO_ROOT, "docs"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_with_fixture_config_prints_summary(self):
        proc = _run_statusline(
            "{}",
            env_overrides={"SPRING_FLEET_CONFIG": FLEET_CONFIG},
            cwd=os.path.join(REPO_ROOT, "docs"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("fleet:", proc.stdout)
        self.assertIn("3 svc", proc.stdout)
        # Fixture entry is orchestrator.
        self.assertIn("entry:orchestrator", proc.stdout)


if __name__ == "__main__":
    unittest.main()
