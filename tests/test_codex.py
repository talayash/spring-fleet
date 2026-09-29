#!/usr/bin/env python3
"""Tests for Codex compatibility.

Codex loads the same plugin directory as Claude Code, but through
.codex-plugin/plugin.json. Two Codex behaviours shape these tests, both
observed against codex-cli 0.149:
  - MCP args are passed through literally (no ${PLUGIN_ROOT} substitution);
    only a relative `cwd` is resolved, against the plugin root. The server
    therefore does not start in the user's project, so config-dependent tools
    accept an explicit `config_path`.
  - Claude Code auto-loads hooks/hooks.json, so Codex hooks must live
    elsewhere or every hook would fire twice under Claude Code.

Run from the repo root:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import mcp_server  # noqa: E402

FLEET_CONFIG = os.path.join(REPO_ROOT, "fixtures", "fleet.config.json")
CODEX_MANIFEST = os.path.join(REPO_ROOT, ".codex-plugin", "plugin.json")
CLAUDE_MANIFEST = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _plugin_path(rel):
    """Resolve a manifest-relative `./...` path to an absolute path."""
    assert rel.startswith("./"), "manifest paths must start with ./ (got {!r})".format(rel)
    return os.path.normpath(os.path.join(REPO_ROOT, rel))


def _frontmatter(skill_md):
    with open(skill_md, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "{} has no frontmatter".format(skill_md)
    fields = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, text


class TestCodexManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = _load(CODEX_MANIFEST)

    def test_identity_matches_claude_manifest(self):
        claude = _load(CLAUDE_MANIFEST)
        for key in ("name", "version", "description", "license"):
            self.assertEqual(self.manifest[key], claude[key], key)

    def test_version_matches_mcp_server(self):
        self.assertEqual(self.manifest["version"], mcp_server.SERVER_VERSION)

    def test_component_paths_exist(self):
        for key in ("skills", "mcpServers", "hooks"):
            self.assertIn(key, self.manifest)
            self.assertTrue(os.path.exists(_plugin_path(self.manifest[key])), key)

    def test_no_default_hooks_file(self):
        """Claude Code auto-loads hooks/hooks.json on top of plugin.json
        hooks; a file there would double-fire every hook."""
        self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, "hooks", "hooks.json")))
        self.assertNotEqual(os.path.normpath(_plugin_path(self.manifest["hooks"])),
                            os.path.join(REPO_ROOT, "hooks", "hooks.json"))


class TestCodexMcpConfig(unittest.TestCase):
    def setUp(self):
        manifest = _load(CODEX_MANIFEST)
        self.servers = _load(_plugin_path(manifest["mcpServers"]))["mcpServers"]

    def test_server_launches_relative_to_plugin_root(self):
        server = self.servers["spring-fleet"]
        self.assertEqual(server["cwd"], "./")
        joined = " ".join([server["command"]] + server["args"])
        self.assertNotIn("${", joined, "Codex does not substitute variables in MCP args")
        script = os.path.join(REPO_ROOT, server["args"][-1])
        self.assertTrue(os.path.isfile(script), script)


class TestCodexHooks(unittest.TestCase):
    def test_hook_commands_reference_existing_scripts(self):
        manifest = _load(CODEX_MANIFEST)
        hooks = _load(_plugin_path(manifest["hooks"]))["hooks"]
        self.assertIn("SessionStart", hooks)
        for groups in hooks.values():
            for group in groups:
                for handler in group["hooks"]:
                    m = re.search(r"\$\{PLUGIN_ROOT\}/(\S+?\.py)", handler["command"])
                    self.assertIsNotNone(m, handler["command"])
                    self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, m.group(1))))


class TestSkillsReplaceCommands(unittest.TestCase):
    """Codex plugins have no slash commands, so every workflow ships as a
    skill. Claude Code still exposes them as /spring-fleet:<name>."""

    WORKFLOWS = ("debug", "doctor", "fleet-init", "impact", "logs", "run", "trace")

    def test_commands_dir_is_gone(self):
        self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT, "commands")),
                         "commands/ would duplicate the workflow skills in Claude Code")

    def test_each_workflow_is_a_skill(self):
        for name in self.WORKFLOWS:
            path = os.path.join(REPO_ROOT, "skills", name, "SKILL.md")
            self.assertTrue(os.path.isfile(path), path)
            fields, _ = _frontmatter(path)
            self.assertEqual(fields.get("name"), name)
            self.assertTrue(fields.get("description"), name)

    def test_plugin_root_is_explained_wherever_it_is_used(self):
        """Codex does not substitute ${CLAUDE_PLUGIN_ROOT} in skill text, so
        a skill that uses it must say how to resolve it."""
        skills_dir = os.path.join(REPO_ROOT, "skills")
        for name in os.listdir(skills_dir):
            path = os.path.join(skills_dir, name, "SKILL.md")
            if not os.path.isfile(path):
                continue
            _, text = _frontmatter(path)
            if "${CLAUDE_PLUGIN_ROOT}" in text:
                self.assertIn("two directories above this SKILL.md", text, name)

    def test_run_is_explicit_only(self):
        """`run` launches processes; neither client should pick it on its own."""
        fields, _ = _frontmatter(os.path.join(REPO_ROOT, "skills", "run", "SKILL.md"))
        self.assertEqual(fields.get("disable-model-invocation"), "true")
        policy = os.path.join(REPO_ROOT, "skills", "run", "agents", "openai.yaml")
        with open(policy, "r", encoding="utf-8") as fh:
            self.assertIn("allow_implicit_invocation: false", fh.read())


class TestConfigPathArgument(unittest.TestCase):
    """Under Codex the MCP server's cwd is the plugin cache, so callers pass
    the project's config explicitly."""

    def setUp(self):
        self._saved = os.environ.pop("SPRING_FLEET_CONFIG", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["SPRING_FLEET_CONFIG"] = self._saved

    def _call(self, name, args):
        return mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": args}})["result"]

    def test_config_path_beats_missing_env_and_cwd(self):
        result = self._call("list_services", {"config_path": FLEET_CONFIG})
        self.assertFalse(result["isError"], result)
        names = {s["name"] for s in json.loads(result["content"][0]["text"])["services"]}
        self.assertIn("payment", names)

    def test_config_path_beats_env(self):
        os.environ["SPRING_FLEET_CONFIG"] = os.path.join(REPO_ROOT, "does-not-exist.json")
        try:
            result = self._call("get_topology", {"config_path": FLEET_CONFIG})
        finally:
            os.environ.pop("SPRING_FLEET_CONFIG", None)
        self.assertFalse(result["isError"], result)

    def test_missing_config_path_is_structured_error(self):
        result = self._call("list_services",
                            {"config_path": os.path.join(REPO_ROOT, "nope.json")})
        self.assertTrue(result["isError"])
        self.assertIn("nope.json", result["content"][0]["text"])

    def test_every_config_tool_accepts_config_path(self):
        for tool in mcp_server.TOOLS:
            if tool["name"] == "scan_repos_root":
                continue  # takes a repos directory, not a config
            self.assertIn("config_path", tool["inputSchema"]["properties"], tool["name"])


if __name__ == "__main__":
    unittest.main()
