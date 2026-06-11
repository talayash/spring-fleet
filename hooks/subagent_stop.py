#!/usr/bin/env python3
"""SubagentStop hook — persists fleet-explorer / log-correlator output to a
shared handoff log so the main agent can refer back without re-running the
subagent or relying on cleared context.

Activation: wired via plugin.json `hooks.SubagentStop`. Receives the standard
hook JSON on stdin which includes `subagent_name` and `output` (or a transcript
path). Writes to <logDir>/.spring-fleet-handoff.log when the subagent is one
of ours; ignores everything else.

Dependency-free (Python 3 stdlib only).
"""
from __future__ import annotations

import json
import os
import sys
import time

OUR_AGENTS = {"fleet-explorer", "log-correlator", "impact-analyzer"}


def _config_path(hook_input):
    env = os.environ.get("SPRING_FLEET_CONFIG")
    if env and os.path.isfile(env):
        return env
    cwd = (hook_input or {}).get("workspace_root") or (hook_input or {}).get("cwd") or os.getcwd()
    candidate = os.path.join(cwd, "spring-fleet.config.json")
    if os.path.isfile(candidate):
        return candidate
    return None


def _handoff_log_path(hook_input):
    """Resolve <logDir>/.spring-fleet-handoff.log without crashing if logDir
    is missing — we'd rather no-op than block the agent loop."""
    cfg_path = _config_path(hook_input)
    if not cfg_path:
        return None
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    log_dir = cfg.get("logDir")
    if not log_dir:
        return None
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        return None
    return os.path.join(log_dir, ".spring-fleet-handoff.log")


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        payload = {}

    name = (payload.get("subagent_name") or payload.get("subagentName")
            or payload.get("agent") or "")
    if name not in OUR_AGENTS:
        # Not our agent — silently no-op.
        print("{}")
        return 0

    log_path = _handoff_log_path(payload)
    if log_path is None:
        print("{}")
        return 0

    output = (payload.get("output") or payload.get("response") or "").strip()
    if not output:
        # Some clients hand us a transcript file instead of inline output.
        transcript = payload.get("transcript_path") or payload.get("transcriptPath")
        if transcript and os.path.isfile(transcript):
            try:
                with open(transcript, "r", encoding="utf-8", errors="replace") as fh:
                    output = fh.read().strip()
            except OSError:
                output = ""

    entry = "----- {ts} {name} -----\n{body}\n".format(
        ts=time.strftime("%Y-%m-%d %H:%M:%S"),
        name=name,
        body=output or "(no output captured)",
    )
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(entry)
    except OSError:
        # Non-fatal; surfaces in stderr but does not block the agent loop.
        print("# (handoff log append failed)", file=sys.stderr)

    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
