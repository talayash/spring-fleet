#!/usr/bin/env python3
"""spring-fleet status line.

Claude Code calls this on each status-line tick with the standard JSON blob on
stdin. When the workspace has a spring-fleet config, we print a one-line
summary:

    [fleet: <name> · <N> svc · otel:<M>/<N> · entry:<service>]

When there's no config, we print nothing (exit 0) so the status line stays
clean.

Dependency-free (Python 3 stdlib only).
"""
from __future__ import annotations

import json
import os
import sys


def _find_config(payload):
    env = os.environ.get("SPRING_FLEET_CONFIG")
    if env and os.path.isfile(env):
        return env
    cwd = (payload or {}).get("cwd") or (payload or {}).get("workspace_root") or os.getcwd()
    candidate = os.path.join(cwd, "spring-fleet.config.json")
    if os.path.isfile(candidate):
        return candidate
    return None


def render(config, config_path):
    name = os.path.splitext(os.path.basename(os.path.dirname(config_path) or "."))[0]
    # Use repo dir name as a friendly fleet label when no explicit name is set.
    fleet_name = config.get("name") or name or "fleet"
    services = config.get("services", []) or []
    otel = sum(1 for s in services if (s.get("stack") or {}).get("opentelemetry"))
    entries = (config.get("topology") or {}).get("entry") or []
    entry = entries[0] if entries else "?"

    return "[fleet: {name} · {n} svc · otel:{o}/{n} · entry:{e}]".format(
        name=fleet_name, n=len(services), o=otel, e=entry,
    )


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cfg_path = _find_config(payload)
    if not cfg_path:
        return 0
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return 0
    sys.stdout.write(render(config, cfg_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
