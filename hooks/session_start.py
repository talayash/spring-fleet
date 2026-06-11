#!/usr/bin/env python3
"""SessionStart hook for spring-fleet.

When Claude Code starts a session in a project that has a spring-fleet config,
this hook emits an `additionalContext` block summarising the fleet so the model
does not have to re-read the config on every turn.

Activation: wired via plugin.json `hooks.SessionStart`. Receives the standard
hook JSON on stdin, writes a JSON response on stdout, exits 0.

Resolution order for the config:
    1. SPRING_FLEET_CONFIG env var (absolute path, set by the user)
    2. <cwd>/spring-fleet.config.json
    3. <hook_input.workspace_root>/spring-fleet.config.json

If no config is found, the hook prints an empty JSON object and exits 0 — it
must never block a session.

Dependency-free (Python 3 stdlib only).
"""
from __future__ import annotations

import json
import os
import sys


def _candidate_paths(hook_input):
    paths = []
    env = os.environ.get("SPRING_FLEET_CONFIG")
    if env:
        paths.append(env)
    paths.append(os.path.join(os.getcwd(), "spring-fleet.config.json"))
    workspace = (hook_input or {}).get("workspace_root") or (hook_input or {}).get("cwd")
    if workspace:
        paths.append(os.path.join(workspace, "spring-fleet.config.json"))
    return paths


def find_config(hook_input):
    for p in _candidate_paths(hook_input):
        if p and os.path.isfile(p):
            return p
    return None


def summarize(config, config_path):
    """Render a compact, model-friendly description of the fleet."""
    services = config.get("services", [])
    libs = config.get("sharedLibs", [])
    trace_keys = config.get("traceKeys", [])
    topology = config.get("topology", {}) or {}
    edges = topology.get("edges", []) or []
    entries = topology.get("entry", []) or []

    lines = []
    lines.append("spring-fleet detected at " + config_path)
    lines.append("reposRoot: " + str(config.get("reposRoot", "?")))
    lines.append("logDir:    " + str(config.get("logDir", "?")))
    if trace_keys:
        lines.append("traceKeys: " + ", ".join(trace_keys))
    if services:
        rendered = []
        for svc in services:
            tag = svc["name"]
            extras = []
            if svc.get("port") is not None:
                extras.append("port " + str(svc["port"]))
            if svc.get("contextPath"):
                extras.append(svc["contextPath"])
            stack = svc.get("stack") or {}
            modern_bits = []
            if stack.get("springBootMajor"):
                modern_bits.append("boot" + str(stack["springBootMajor"]))
            if stack.get("java"):
                modern_bits.append("java" + str(stack["java"]))
            if stack.get("virtualThreads"):
                modern_bits.append("vt")
            if stack.get("graalNative"):
                modern_bits.append("native")
            if stack.get("dockerCompose"):
                modern_bits.append("compose")
            if stack.get("testcontainers"):
                modern_bits.append("tc")
            if stack.get("opentelemetry"):
                modern_bits.append("otel")
            if modern_bits:
                extras.append("/".join(modern_bits))
            if extras:
                tag += " (" + ", ".join(extras) + ")"
            rendered.append(tag)
        lines.append("services:  " + "; ".join(rendered))
    if libs:
        lines.append("sharedLibs: " + ", ".join(l["name"] for l in libs))
    if entries or edges:
        edge_str = " -> ".join(entries) if not edges else (
            ", ".join("{}→{}".format(a, b) for a, b in edges)
        )
        lines.append("topology:  " + edge_str)
    return "\n".join(lines)


def build_response(config_path, config):
    summary = summarize(config, config_path)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "## Spring-Fleet Context\n"
                "(Loaded by the spring-fleet SessionStart hook. Use this instead\n"
                "of re-reading the config on each turn.)\n\n"
                + summary
            ),
        }
    }


def main(argv=None):
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    cfg_path = find_config(hook_input)
    if cfg_path is None:
        # No config in this workspace; do not inject anything.
        print("{}")
        return 0

    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # Surface a minimal note rather than crashing the session.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "## Spring-Fleet Context\n"
                    "(spring-fleet config at " + cfg_path
                    + " could not be loaded: " + str(exc) + ")"
                ),
            }
        }))
        return 0

    print(json.dumps(build_response(cfg_path, config)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
